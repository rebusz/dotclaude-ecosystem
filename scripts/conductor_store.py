"""Single-writer SQLite WAL storage engine, atomic inbox processor, and leader lock for TruthDeck Conductor.

Port-free design operating over ~/.conductor (or a configured root path).
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
import pathlib
import psutil
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Any, Dict, Iterator, List, Optional, Union
import uuid

from scripts.conductor_model import (
    Attempt,
    AuthorizationRecord,
    Claim,
    CommandEnvelope,
    EvidenceCheckpoint,
    Lease,
    HostResourceLease,
    HostResourcePool,
    HostResourceRequest,
    HostResourceRequestState,
    Receipt,
    WorkItem,
    WorkItemState,
    can_transition,
    current_utc_iso,
)


# H6: explicit report-only ceilings.  These are bounded storage contracts,
# not retention automation; status reports growth and operators decide any
# cleanup after reviewing the durable evidence.
STORAGE_QUOTAS_BYTES = {
    "artifacts": 1_073_741_824,  # 1 GiB
    "receipts": 268_435_456,  # 256 MiB
    "inbox": 67_108_864,  # 64 MiB
}


def get_default_conductor_dir() -> pathlib.Path:
    """Return default root directory ~/.conductor or TDCONDUCTOR_DIR if set."""
    env_dir = os.environ.get("TDCONDUCTOR_DIR")
    if env_dir:
        return pathlib.Path(env_dir).expanduser().resolve()
    return (pathlib.Path.home() / ".conductor").resolve()


def _file_signature(path: pathlib.Path) -> tuple[bool, int, int]:
    """Return a cheap stability signature without creating the path."""
    try:
        stat = path.stat()
        return True, stat.st_size, stat.st_mtime_ns
    except FileNotFoundError:
        return False, 0, 0


@contextmanager
def _read_only_snapshot_connection(db_path: pathlib.Path) -> Iterator[sqlite3.Connection]:
    """Open a consistent temp copy so SQLite never writes WAL/SHM beside the live DB."""
    source_paths = (db_path, db_path.with_name(f"{db_path.name}-wal"))
    with tempfile.TemporaryDirectory(prefix="conductor-read-snapshot-") as temp_dir:
        snapshot_db = pathlib.Path(temp_dir) / db_path.name
        for attempt in range(3):
            before = tuple(_file_signature(path) for path in source_paths)
            try:
                shutil.copy2(db_path, snapshot_db)
                source_wal = source_paths[1]
                snapshot_wal = snapshot_db.with_name(f"{snapshot_db.name}-wal")
                if source_wal.is_file():
                    shutil.copy2(source_wal, snapshot_wal)
                else:
                    snapshot_wal.unlink(missing_ok=True)
            except OSError:
                if attempt == 2:
                    raise
                continue
            after = tuple(_file_signature(path) for path in source_paths)
            if before == after:
                break
        else:
            raise sqlite3.OperationalError("store changed during read-only snapshot")

        conn = sqlite3.connect(str(snapshot_db), timeout=1.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            yield conn
        finally:
            conn.close()


def _row_to_request_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "request_id": str(row["request_id"]),
        "idempotency_key": str(row["idempotency_key"]),
        "resource_key": str(row["resource_key"]),
        "purpose": str(row["purpose"]),
        "attempt_id": str(row["attempt_id"]),
        "agent_instance": str(row["agent_instance"]),
        "state": str(row["state"]),
        "priority": int(row["priority"]),
        "parent_lease_id": str(row["parent_lease_id"]) if row["parent_lease_id"] is not None else None,
        "command_sha256": str(row["command_sha256"]) if row["command_sha256"] is not None else "",
        "created_at_utc": str(row["created_at_utc"]),
        "released_at_utc": str(row["released_at_utc"]) if row["released_at_utc"] is not None else None,
        "reason_code": str(row["reason_code"]) if row["reason_code"] is not None else None,
        "slot_key": str(row["slot_key"]) if "slot_key" in row.keys() and row["slot_key"] is not None else "",
        "schema_version": str(row["schema_version"]),
    }


def _row_to_lease_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "lease_id": str(row["lease_id"]),
        "request_id": str(row["request_id"]),
        "resource_key": str(row["resource_key"]),
        "attempt_id": str(row["attempt_id"]),
        "agent_instance": str(row["agent_instance"]),
        "heartbeat_sequence": int(row["heartbeat_sequence"]),
        "expires_at_utc": str(row["expires_at_utc"]),
        "last_heartbeat_utc": str(row["last_heartbeat_utc"]),
        "process_pid": int(row["process_pid"]) if row["process_pid"] is not None else None,
        "process_start_time": float(row["process_start_time"]) if row["process_start_time"] is not None else None,
        "schema_version": str(row["schema_version"]),
    }


def _join_request_lease(req_dict: Dict[str, Any], lease_dict: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    joined = dict(req_dict)
    joined["lease"] = lease_dict
    if lease_dict:
        joined["lease_id"] = lease_dict["lease_id"]
        joined["expires_at_utc"] = lease_dict["expires_at_utc"]
        joined["last_heartbeat_utc"] = lease_dict["last_heartbeat_utc"]
        joined["heartbeat_sequence"] = lease_dict["heartbeat_sequence"]
        joined["process_pid"] = lease_dict["process_pid"]
        joined["process_start_time"] = lease_dict["process_start_time"]
    else:
        joined["lease_id"] = None
        joined["expires_at_utc"] = None
        joined["last_heartbeat_utc"] = None
        joined["heartbeat_sequence"] = None
        joined["process_pid"] = None
        joined["process_start_time"] = None
    return joined


def _read_store_status_from_conn(conn: sqlite3.Connection, db_path: pathlib.Path) -> Dict[str, Any]:
    state_rows = conn.execute(
        "SELECT state, COUNT(*) AS count FROM work_items GROUP BY state ORDER BY state"
    ).fetchall()
    leader_row = conn.execute(
        "SELECT leader_id, pid, process_start_time FROM leader_locks WHERE lock_name = ?",
        ("primary_coordinator",),
    ).fetchone()
    leader_active = False
    if leader_row:
        try:
            process = psutil.Process(int(leader_row["pid"]))
            leader_active = process.is_running() and abs(
                process.create_time() - float(leader_row["process_start_time"])
            ) < 1.0
        except (psutil.Error, OSError, TypeError, ValueError):
            leader_active = False
    return {
        "store_state": "AVAILABLE",
        "leader_id": leader_row["leader_id"] if leader_row else None,
        "leader_pid": int(leader_row["pid"]) if leader_row else None,
        "leader_process_start_time": float(leader_row["process_start_time"]) if leader_row else None,
        "leader_active": leader_active,
        "db_path": str(db_path),
        "total_work_items": sum(int(row["count"]) for row in state_rows),
        "state_summary": {str(row["state"]): int(row["count"]) for row in state_rows},
    }


def _read_resource_live_snapshot_from_conn(
    conn: sqlite3.Connection,
    resource_key: str = "host:heavy",
) -> Dict[str, Any]:
    pool_row = conn.execute(
        "SELECT * FROM host_resource_pools WHERE resource_key = ?",
        (resource_key,),
    ).fetchone()
    if pool_row:
        pool_present = True
        capacity = int(pool_row["capacity"])
        enabled = bool(pool_row["enabled"])
    else:
        pool_present = False
        capacity = 0
        enabled = False

    term_row = conn.execute(
        "SELECT COUNT(*) AS count FROM host_resource_requests WHERE resource_key = ? AND state = 'RELEASED'",
        (resource_key,),
    ).fetchone()
    terminal_count = int(term_row["count"]) if term_row else 0

    req_rows = conn.execute(
        """
        SELECT * FROM host_resource_requests
        WHERE resource_key = ? AND state != 'RELEASED'
        ORDER BY priority DESC, created_at_utc, request_id
        """,
        (resource_key,),
    ).fetchall()

    lease_rows = conn.execute(
        "SELECT * FROM host_resource_leases WHERE resource_key = ?",
        (resource_key,),
    ).fetchall()
    leases_by_request_id = {str(row["request_id"]): _row_to_lease_dict(row) for row in lease_rows}

    live_counts = {
        "ACTIVE": 0,
        "INHERITED": 0,
        "QUEUED": 0,
        "RECOVERY_REQUIRED": 0,
        "QUARANTINED": 0,
    }
    active_reqs: List[Dict[str, Any]] = []
    inherited_reqs: List[Dict[str, Any]] = []
    queued_reqs: List[Dict[str, Any]] = []
    fenced_reqs: List[Dict[str, Any]] = []
    quarantined_reqs: List[Dict[str, Any]] = []

    for row in req_rows:
        req = _row_to_request_dict(row)
        st = req["state"]
        if st in live_counts:
            live_counts[st] += 1
        if st == HostResourceRequestState.ACTIVE.value:
            active_reqs.append(req)
        elif st == HostResourceRequestState.INHERITED.value:
            inherited_reqs.append(req)
        elif st == HostResourceRequestState.QUEUED.value:
            queued_reqs.append(req)
        elif st == HostResourceRequestState.RECOVERY_REQUIRED.value:
            fenced_reqs.append(req)
        elif st == HostResourceRequestState.QUARANTINED.value:
            quarantined_reqs.append(req)

    holders: List[Dict[str, Any]] = []
    for hreq in active_reqs:
        holders.append(_join_request_lease(hreq, leases_by_request_id.get(hreq["request_id"])))
    holder = holders[0] if holders else None

    fenced: List[Dict[str, Any]] = []
    for freq in fenced_reqs:
        fenced.append(_join_request_lease(freq, leases_by_request_id.get(freq["request_id"])))

    return {
        "resource_key": resource_key,
        "capacity": capacity,
        "enabled": enabled,
        "pool_present": pool_present,
        "live_counts": live_counts,
        "terminal_count": terminal_count,
        "holder": holder,
        "holders": holders,
        "inherited": inherited_reqs,
        "queue": queued_reqs,
        "fenced": fenced,
        "quarantined": quarantined_reqs,
    }


def read_store_status(root_dir: Optional[Union[str, pathlib.Path]] = None) -> Dict[str, Any]:
    """Read queue status without creating directories, a database, locks, or receipts."""
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    db_path = root / "conductor.db"
    result: Dict[str, Any] = {
        "store_state": "ABSENT",
        "leader_id": None,
        "leader_pid": None,
        "leader_process_start_time": None,
        "leader_active": False,
        "db_path": str(db_path),
        "total_work_items": 0,
        "state_summary": {},
    }
    if not db_path.is_file():
        return result

    try:
        with _read_only_snapshot_connection(db_path) as conn:
            return _read_store_status_from_conn(conn, db_path)
    except (OSError, sqlite3.Error) as exc:
        result.update({"store_state": "CORRUPT_OR_UNREADABLE", "error": str(exc)[:500]})
    return result


def read_resource_live_snapshot(
    resource_key: str = "host:heavy",
    root_dir: Optional[Union[str, pathlib.Path]] = None,
) -> Dict[str, Any]:
    """Read live host resource state without creating directories, DB, locks, or receipts.

    Note for PR #85 (branch agy/conductor-doctor-resource-pool):
    read_resource_live_snapshot is a strict superset of read_host_resource_status.
    Once PR #85 lands, read_host_resource_status can become a thin wrapper over
    read_resource_live_snapshot.
    """
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    db_path = root / "conductor.db"
    if not db_path.is_file():
        return {
            "resource_key": resource_key,
            "capacity": 0,
            "enabled": False,
            "pool_present": False,
            "live_counts": {
                "ACTIVE": 0,
                "INHERITED": 0,
                "QUEUED": 0,
                "RECOVERY_REQUIRED": 0,
                "QUARANTINED": 0,
            },
            "terminal_count": 0,
            "holder": None,
            "inherited": [],
            "queue": [],
            "fenced": [],
            "quarantined": [],
        }

    with _read_only_snapshot_connection(db_path) as conn:
        return _read_resource_live_snapshot_from_conn(conn, resource_key=resource_key)


DEFAULT_RESOURCE_POOLS = (
    "host:heavy",
    "cdp:perplexity",
    "cdp:chatgpt",
    "cdp:gemini",
    "cdp:tv",
)


def read_all_pools_live(
    root_dir: Optional[Union[str, pathlib.Path]] = None,
) -> Dict[str, Dict[str, Any]]:
    """Read live projection for all host resource pools from exactly one snapshot."""
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    db_path = root / "conductor.db"
    if not db_path.is_file():
        return {
            p: read_resource_live_snapshot(resource_key=p, root_dir=root)
            for p in DEFAULT_RESOURCE_POOLS
        }

    with _read_only_snapshot_connection(db_path) as conn:
        try:
            pool_rows = conn.execute("SELECT resource_key FROM host_resource_pools").fetchall()
            db_pools = [str(r["resource_key"]) for r in pool_rows]
        except sqlite3.OperationalError:
            db_pools = []

        seen = set()
        ordered_pools = []
        for p in list(DEFAULT_RESOURCE_POOLS) + db_pools:
            if p not in seen:
                seen.add(p)
                ordered_pools.append(p)

        return {
            p: _read_resource_live_snapshot_from_conn(conn, resource_key=p)
            for p in ordered_pools
        }


def read_gate_frame(
    resource_key: str = "host:heavy",
    root_dir: Optional[Union[str, pathlib.Path]] = None,
) -> Dict[str, Any]:
    """Read both store status and live gate frames for all pools from exactly one snapshot."""
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    db_path = root / "conductor.db"
    if not db_path.is_file():
        default_gates = {
            p: read_resource_live_snapshot(resource_key=p, root_dir=root)
            for p in DEFAULT_RESOURCE_POOLS
        }
        return {
            "store": read_store_status(root),
            "gate": default_gates.get(resource_key, read_resource_live_snapshot(resource_key=resource_key, root_dir=root)),
            "gates": default_gates,
        }

    with _read_only_snapshot_connection(db_path) as conn:
        store = _read_store_status_from_conn(conn, db_path)
        try:
            pool_rows = conn.execute("SELECT resource_key FROM host_resource_pools").fetchall()
            db_pools = [str(r["resource_key"]) for r in pool_rows]
        except sqlite3.OperationalError:
            db_pools = []

        seen = set()
        ordered_pools = []
        for p in list(DEFAULT_RESOURCE_POOLS) + db_pools:
            if p not in seen:
                seen.add(p)
                ordered_pools.append(p)

        gates = {p: _read_resource_live_snapshot_from_conn(conn, resource_key=p) for p in ordered_pools}
        gate = gates.get(resource_key) or _read_resource_live_snapshot_from_conn(conn, resource_key=resource_key)
    return {"store": store, "gate": gate, "gates": gates}


def read_resource_history_page(
    resource_key: str = "host:heavy",
    limit: int = 50,
    cursor: Optional[str] = None,
    root_dir: Optional[Union[str, pathlib.Path]] = None,
) -> Dict[str, Any]:
    """Read a page of terminal (RELEASED) resource requests using read-only snapshot.

    Returns newest terminal requests, paged by cursor.
    Does NOT construct ConductorStore or HostResourceManager.
    """
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    db_path = root / "conductor.db"
    if not db_path.is_file():
        return {
            "resource_key": resource_key,
            "items": [],
            "next_cursor": None,
            "has_more": False,
            "total_terminal": 0,
        }

    page_limit = max(1, min(int(limit), 500))

    with _read_only_snapshot_connection(db_path) as conn:
        count_row = conn.execute(
            "SELECT COUNT(*) AS c FROM host_resource_requests WHERE resource_key = ? AND state = 'RELEASED'",
            (resource_key,),
        ).fetchone()
        total_terminal = int(count_row["c"]) if count_row else 0

        query = """
            SELECT * FROM host_resource_requests
            WHERE resource_key = ? AND state = 'RELEASED'
        """
        params: List[Any] = [resource_key]

        if cursor:
            if "|" in cursor:
                ts_part, id_part = cursor.split("|", 1)
                query += " AND (COALESCE(released_at_utc, created_at_utc) < ? OR (COALESCE(released_at_utc, created_at_utc) = ? AND request_id < ?))"
                params.extend([ts_part, ts_part, id_part])
            elif cursor.isdigit():
                offset = int(cursor)
                query += " ORDER BY COALESCE(released_at_utc, created_at_utc) DESC, request_id DESC LIMIT ? OFFSET ?"
                params.extend([page_limit + 1, offset])
                rows = conn.execute(query, params).fetchall()
                has_more = len(rows) > page_limit
                page_rows = rows[:page_limit]
                items = [_row_to_request_dict(r) for r in page_rows]
                next_cursor = str(offset + len(items)) if has_more else None
                return {
                    "resource_key": resource_key,
                    "items": items,
                    "next_cursor": next_cursor,
                    "has_more": has_more,
                    "total_terminal": total_terminal,
                }
            else:
                cursor_row = conn.execute(
                    "SELECT COALESCE(released_at_utc, created_at_utc) AS sort_ts, request_id FROM host_resource_requests WHERE request_id = ?",
                    (cursor,),
                ).fetchone()
                if cursor_row:
                    ts_part = str(cursor_row["sort_ts"])
                    id_part = str(cursor_row["request_id"])
                    query += " AND (COALESCE(released_at_utc, created_at_utc) < ? OR (COALESCE(released_at_utc, created_at_utc) = ? AND request_id < ?))"
                    params.extend([ts_part, ts_part, id_part])

        query += " ORDER BY COALESCE(released_at_utc, created_at_utc) DESC, request_id DESC LIMIT ?"
        params.append(page_limit + 1)
        rows = conn.execute(query, params).fetchall()
        has_more = len(rows) > page_limit
        page_rows = rows[:page_limit]
        items = [_row_to_request_dict(r) for r in page_rows]
        next_cursor = None
        if has_more and items:
            last_item = items[-1]
            ts = last_item.get("released_at_utc") or last_item.get("created_at_utc") or ""
            next_cursor = f"{ts}|{last_item['request_id']}"

        return {
            "resource_key": resource_key,
            "items": items,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total_terminal": total_terminal,
        }



def format_duration(seconds: float) -> str:
    """Format elapsed seconds, clamped at 0. Returns '<1m' below 60 seconds."""
    sec = max(0.0, float(seconds))
    if sec < 60.0:
        return "<1m"
    if sec < 3600.0:
        mins = int(sec // 60)
        return f"{mins}m"
    hours = int(sec // 3600)
    mins = int((sec % 3600) // 60)
    return f"{hours}h {mins:02d}m"


class GateVerdict(str, Enum):
    DISABLED = "DISABLED"
    FENCED = "FENCED"
    OCCUPIED = "OCCUPIED"
    ANOMALY = "ANOMALY"
    CLEAR = "CLEAR"


@dataclass
class GateVerdictResult:
    verdict: str
    headline: str
    subtext: str
    resource_key: str
    blocker: Optional[Dict[str, Any]] = None
    fenced_count: int = 0
    queue_count: int = 0
    commands: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


@dataclass
class RecoveryAdjudication:
    request_id: str
    command: Optional[str]
    release_refusal_code: str  # Always "RECOVERY_REQUIRED_RELEASE_REFUSED"
    recover_code: str          # "OWNER_LIVENESS_UNPROVEN" | "RECOVERY_OWNER_GONE" | "OWNER_PROCESS_ALIVE" | "INHERITED_CHILD_ACTIVE" | "INVALID_REQUEST_ID"
    liveness_status: str       # "OWNER_UNRECORDED" | "OWNER_PROCESS_GONE" | "OWNER_PID_REUSED" | "OWNER_PROCESS_ALIVE" | "INHERITED_CHILD_ACTIVE" | "INVALID_REQUEST_ID"
    pid: Optional[int] = None
    inherited_child_id: Optional[str] = None
    reason_placeholder: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


_REQUEST_ID_REGEX = re.compile(r"^rr_[0-9a-f]{12}$")


def _powershell_quote(val: str) -> str:
    return "'" + str(val).replace("'", "''") + "'"


def adjudicate_recovery(
    fenced_request: Dict[str, Any],
    inherited_children: Optional[List[Dict[str, Any]]] = None,
    repo_path: Optional[Union[str, pathlib.Path]] = None,
    python_executable: Optional[str] = None,
) -> RecoveryAdjudication:
    """Adjudicate recovery path for a fenced request and build recovery command if applicable."""
    request_id = str(fenced_request.get("request_id", ""))
    if not _REQUEST_ID_REGEX.match(request_id):
        return RecoveryAdjudication(
            request_id=request_id,
            command=None,
            release_refusal_code="RECOVERY_REQUIRED_RELEASE_REFUSED",
            recover_code="INVALID_REQUEST_ID",
            liveness_status="INVALID_REQUEST_ID",
        )

    # Check for active inherited children
    lease_id = fenced_request.get("lease_id")
    if lease_id is None and "lease" in fenced_request and isinstance(fenced_request["lease"], dict):
        lease_id = fenced_request["lease"].get("lease_id")

    if inherited_children and lease_id:
        active_children = [
            child for child in inherited_children
            if child.get("parent_lease_id") == lease_id and child.get("state") == HostResourceRequestState.INHERITED.value
        ]
        if active_children:
            child_id = active_children[0].get("request_id")
            return RecoveryAdjudication(
                request_id=request_id,
                command=None,
                release_refusal_code="RECOVERY_REQUIRED_RELEASE_REFUSED",
                recover_code="INHERITED_CHILD_ACTIVE",
                liveness_status="INHERITED_CHILD_ACTIVE",
                inherited_child_id=child_id,
            )

    # Check process liveness
    pid = fenced_request.get("process_pid")
    start_time = fenced_request.get("process_start_time")
    if pid is None and "lease" in fenced_request and isinstance(fenced_request["lease"], dict):
        pid = fenced_request["lease"].get("process_pid")
        start_time = fenced_request["lease"].get("process_start_time")

    repo = pathlib.Path(repo_path).resolve() if repo_path else pathlib.Path(__file__).resolve().parents[1]
    ctl_script = (repo / "scripts" / "conductorctl.py").resolve()
    py_exe = python_executable or sys.executable

    if pid is None:
        cmd = f"& {_powershell_quote(str(py_exe))} {_powershell_quote(str(ctl_script))} resource-recover --request-id {request_id} --attest-owner-gone --reason '<why>'"
        return RecoveryAdjudication(
            request_id=request_id,
            command=cmd,
            release_refusal_code="RECOVERY_REQUIRED_RELEASE_REFUSED",
            recover_code="OWNER_LIVENESS_UNPROVEN",
            liveness_status="OWNER_UNRECORDED",
            pid=None,
            reason_placeholder="<why>",
        )

    try:
        proc = psutil.Process(int(pid))
        observed_start = proc.create_time()
        if start_time is not None and abs(observed_start - float(start_time)) > 1.0:
            cmd = f"& {_powershell_quote(str(py_exe))} {_powershell_quote(str(ctl_script))} resource-recover --request-id {request_id}"
            return RecoveryAdjudication(
                request_id=request_id,
                command=cmd,
                release_refusal_code="RECOVERY_REQUIRED_RELEASE_REFUSED",
                recover_code="RECOVERY_OWNER_GONE",
                liveness_status="OWNER_PID_REUSED",
                pid=int(pid),
            )
        else:
            return RecoveryAdjudication(
                request_id=request_id,
                command=None,
                release_refusal_code="RECOVERY_REQUIRED_RELEASE_REFUSED",
                recover_code="OWNER_PROCESS_ALIVE",
                liveness_status="OWNER_PROCESS_ALIVE",
                pid=int(pid),
            )
    except (OSError, ValueError, psutil.Error):
        cmd = f"& {_powershell_quote(str(py_exe))} {_powershell_quote(str(ctl_script))} resource-recover --request-id {request_id}"
        return RecoveryAdjudication(
            request_id=request_id,
            command=cmd,
            release_refusal_code="RECOVERY_REQUIRED_RELEASE_REFUSED",
            recover_code="RECOVERY_OWNER_GONE",
            liveness_status="OWNER_PROCESS_GONE",
            pid=int(pid),
        )


def build_recovery_command(
    fenced_request: Dict[str, Any],
    inherited_children: Optional[List[Dict[str, Any]]] = None,
    repo_path: Optional[Union[str, pathlib.Path]] = None,
    python_executable: Optional[str] = None,
) -> Optional[str]:
    """Emit a single-line PowerShell command to recover a fenced request, or None if not recoverable."""
    adjudication = adjudicate_recovery(
        fenced_request=fenced_request,
        inherited_children=inherited_children,
        repo_path=repo_path,
        python_executable=python_executable,
    )
    return adjudication.command


def evaluate_gate_verdict(
    snapshot: Dict[str, Any],
    now: Optional[datetime] = None,
    repo_path: Optional[Union[str, pathlib.Path]] = None,
    python_executable: Optional[str] = None,
) -> GateVerdictResult:
    """Evaluate host resource gate verdict in strict admission order."""
    now_dt = now or datetime.now(timezone.utc)
    resource_key = snapshot.get("resource_key", "host:heavy")
    pool_present = bool(snapshot.get("pool_present", False))
    enabled = bool(snapshot.get("enabled", False))
    live_counts = snapshot.get("live_counts", {})
    holder = snapshot.get("holder")
    fenced = list(snapshot.get("fenced", []))
    queue = list(snapshot.get("queue", []))
    inherited = list(snapshot.get("inherited", []))

    # 1. pool row absent OR enabled is false -> DISABLED
    if not pool_present or not enabled:
        return GateVerdictResult(
            verdict=GateVerdict.DISABLED.value,
            headline="Gate disabled. Admission is refused with HOST_RESOURCE_DISABLED.",
            subtext=f"Resource pool {resource_key} is disabled or absent.",
            resource_key=resource_key,
            blocker=None,
            fenced_count=len(fenced),
            queue_count=len(queue),
            commands=[],
        )

    # 2. any RECOVERY_REQUIRED -> FENCED
    if fenced or live_counts.get("RECOVERY_REQUIRED", 0) > 0:
        oldest_fenced = fenced[0] if fenced else None
        fenced_count = max(len(fenced), live_counts.get("RECOVERY_REQUIRED", 0))
        commands: List[str] = []
        for f in fenced:
            cmd = build_recovery_command(
                f,
                inherited_children=inherited,
                repo_path=repo_path,
                python_executable=python_executable,
            )
            if cmd is not None:
                commands.append(cmd)

        if oldest_fenced:
            agent = oldest_fenced.get("agent_instance", "unknown")
            created_str = oldest_fenced.get("created_at_utc")
            elapsed_sec = 0.0
            if created_str:
                try:
                    c_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    elapsed_sec = max(0.0, (now_dt - c_dt).total_seconds())
                except (ValueError, TypeError):
                    pass
            dur_str = format_duration(elapsed_sec)
            subtext = f"Blocked {dur_str} by {agent}. {len(queue)} requests waiting."
        else:
            subtext = f"{fenced_count} recovery required requests. {len(queue)} requests waiting."

        headline = (
            "Gate fenced. Nothing is running."
            if fenced_count == 1
            else f"Gate fenced ({fenced_count} recovery required). Clearing one fence may not open the gate."
        )

        return GateVerdictResult(
            verdict=GateVerdict.FENCED.value,
            headline=headline,
            subtext=subtext,
            resource_key=resource_key,
            blocker=oldest_fenced,
            fenced_count=fenced_count,
            queue_count=len(queue),
            commands=commands,
        )

    # 3. any ACTIVE -> OCCUPIED
    if holder is not None or live_counts.get("ACTIVE", 0) > 0:
        agent = holder.get("agent_instance", "unknown") if holder else "unknown"
        purpose = holder.get("purpose", "") if holder else ""
        elapsed_sec = 0.0
        if holder and holder.get("created_at_utc"):
            try:
                c_dt = datetime.fromisoformat(holder["created_at_utc"].replace("Z", "+00:00"))
                elapsed_sec = max(0.0, (now_dt - c_dt).total_seconds())
            except (ValueError, TypeError):
                pass
        dur_str = format_duration(elapsed_sec)
        purpose_str = f" running {purpose}" if purpose else ""
        subtext = f"Held {dur_str} by {agent}{purpose_str}. {len(queue)} requests waiting."

        return GateVerdictResult(
            verdict=GateVerdict.OCCUPIED.value,
            headline="Gate held. A job is running.",
            subtext=subtext,
            resource_key=resource_key,
            blocker=holder,
            fenced_count=0,
            queue_count=len(queue),
            commands=[],
        )

    # 4. queue non-empty and none of the above -> ANOMALY
    if queue or live_counts.get("QUEUED", 0) > 0:
        q_count = max(len(queue), live_counts.get("QUEUED", 0))
        return GateVerdictResult(
            verdict=GateVerdict.ANOMALY.value,
            headline="Queue is waiting with nothing holding the gate.",
            subtext=f"{q_count} requests queued but gate is neither occupied nor fenced.",
            resource_key=resource_key,
            blocker=None,
            fenced_count=0,
            queue_count=q_count,
            commands=[],
        )

    # 5. otherwise -> CLEAR
    return GateVerdictResult(
        verdict=GateVerdict.CLEAR.value,
        headline="Gate clear.",
        subtext=f"Nothing holds {resource_key} and nothing is waiting.",
        resource_key=resource_key,
        blocker=None,
        fenced_count=0,
        queue_count=0,
        commands=[],
    )


def read_store_diagnostics(root_dir: Optional[Union[str, pathlib.Path]] = None) -> Dict[str, Any]:
    """Inspect the installation surface without acquiring or renewing the leader lock."""
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    result = read_store_status(root)
    result.update(
        {
            "root_dir": str(root),
            "root_exists": root.is_dir(),
            "db_exists": (root / "conductor.db").is_file(),
            "inbox_exists": (root / "inbox").is_dir(),
            "receipts_exists": (root / "receipts").is_dir(),
            "locks_exists": (root / "locks").is_dir(),
            "leader_lock_present": result.get("leader_id") is not None,
        }
    )
    return result


def read_work_item_snapshot(
    work_item_id: str,
    root_dir: Optional[Union[str, pathlib.Path]] = None,
) -> Optional[Dict[str, Any]]:
    """Read one work item from a stable temporary DB+WAL snapshot."""
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    db_path = root / "conductor.db"
    if not db_path.is_file():
        return None
    try:
        with _read_only_snapshot_connection(db_path) as conn:
            row = conn.execute(
                "SELECT * FROM work_items WHERE work_item_id = ?",
                (work_item_id,),
            ).fetchone()
        if row is None:
            return None
        raw = dict(row)
        raw["dependency_ids"] = json.loads(raw.pop("dependency_ids_json"))
        raw["execution_budget"] = json.loads(raw.pop("execution_budget_json"))
        return WorkItem.from_dict(raw).to_dict()
    except (OSError, sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
        return None


def _directory_usage(path: pathlib.Path) -> Dict[str, int]:
    """Return recursive file count/bytes without following symlinks."""
    file_count = 0
    byte_count = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_symlink() or not entry.is_file():
                continue
            try:
                byte_count += entry.stat().st_size
                file_count += 1
            except OSError:
                continue
    except OSError:
        return {"files": file_count, "bytes": byte_count, "read_error": 1}
    return {"files": file_count, "bytes": byte_count, "read_error": 0}


def read_storage_status(root_dir: Optional[Union[str, pathlib.Path]] = None) -> Dict[str, Any]:
    """Read storage growth and quota state without creating or mutating paths."""
    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    usage: Dict[str, Dict[str, Any]] = {}
    overall = "PASS"
    for name, limit in STORAGE_QUOTAS_BYTES.items():
        path = root / name
        sample = _directory_usage(path)
        over_quota = bool(sample["read_error"] or sample["bytes"] > limit)
        if over_quota:
            overall = "BLOCKED"
        usage[name] = {
            "path": str(path),
            "files": sample["files"],
            "bytes": sample["bytes"],
            "ceiling_bytes": limit,
            "over_quota": over_quota,
            "read_error": bool(sample["read_error"]),
        }
    return {"status": overall, "retention_mode": "REPORT_ONLY", "directories": usage}


# Convergence point: design/plans/2026-08-27_conductor_operator_gui_r1.md (GP-1)
def read_host_resource_status(
    root_dir: Optional[Union[str, pathlib.Path]] = None,
    resource_key: str = "host:heavy",
) -> Dict[str, Any]:
    """Read host resource pool and live request counts without creating or mutating paths."""
    if isinstance(root_dir, str) and root_dir.startswith("host:"):
        resource_key = root_dir
        root_dir = None

    root = pathlib.Path(root_dir).expanduser().resolve() if root_dir else get_default_conductor_dir()
    db_path = root / "conductor.db"

    live_states = (
        HostResourceRequestState.ACTIVE.value,
        HostResourceRequestState.INHERITED.value,
        HostResourceRequestState.QUEUED.value,
        HostResourceRequestState.RECOVERY_REQUIRED.value,
        HostResourceRequestState.QUARANTINED.value,
    )
    counts = {s: 0 for s in live_states}

    result: Dict[str, Any] = {
        "resource_key": resource_key,
        "pool_exists": False,
        "capacity": 0,
        "enabled": False,
        "active": 0,
        "active_units": 0,
        "queued": 0,
        "recovery_required": 0,
        "inherited": 0,
        "quarantined": 0,
        "state_counts": dict(counts),
        "counts": dict(counts),
        "total_live_requests": 0,
    }

    if not db_path.is_file():
        return result

    try:
        with _read_only_snapshot_connection(db_path) as conn:
            try:
                pool_row = conn.execute(
                    "SELECT resource_key, capacity, enabled, schema_version FROM host_resource_pools WHERE resource_key = ?",
                    (resource_key,),
                ).fetchone()
            except sqlite3.OperationalError:
                pool_row = None

            if pool_row:
                result["pool_exists"] = True
                result["capacity"] = int(pool_row["capacity"])
                result["enabled"] = bool(pool_row["enabled"])

            try:
                state_rows = conn.execute(
                    """
                    SELECT state, COUNT(*) AS count
                    FROM host_resource_requests
                    WHERE resource_key = ? AND state IN (?, ?, ?, ?, ?)
                    GROUP BY state
                    """,
                    (
                        resource_key,
                        HostResourceRequestState.ACTIVE.value,
                        HostResourceRequestState.INHERITED.value,
                        HostResourceRequestState.QUEUED.value,
                        HostResourceRequestState.RECOVERY_REQUIRED.value,
                        HostResourceRequestState.QUARANTINED.value,
                    ),
                ).fetchall()
                for row in state_rows:
                    st = str(row["state"])
                    if st in counts:
                        counts[st] = int(row["count"])
            except sqlite3.OperationalError:
                pass

        result.update(
            {
                "active": counts[HostResourceRequestState.ACTIVE.value],
                "active_units": counts[HostResourceRequestState.ACTIVE.value],
                "queued": counts[HostResourceRequestState.QUEUED.value],
                "recovery_required": counts[HostResourceRequestState.RECOVERY_REQUIRED.value],
                "inherited": counts[HostResourceRequestState.INHERITED.value],
                "quarantined": counts[HostResourceRequestState.QUARANTINED.value],
                "state_counts": dict(counts),
                "counts": dict(counts),
                "total_live_requests": sum(counts.values()),
            }
        )
    except (OSError, sqlite3.Error) as exc:
        result.update({"error": str(exc)[:500]})

    return result


read_resource_pool_status = read_host_resource_status


class ConductorStore:
    """Single-writer SQLite WAL store and inbox manager."""

    def __init__(self, root_dir: Optional[Union[str, pathlib.Path]] = None):
        if root_dir:
            self.root_dir = pathlib.Path(root_dir).expanduser().resolve()
        else:
            self.root_dir = get_default_conductor_dir()

        self.db_path = self.root_dir / "conductor.db"
        self.inbox_dir = self.root_dir / "inbox"
        self.receipts_dir = self.root_dir / "receipts"
        self.artifacts_dir = self.root_dir / "artifacts"
        self.logs_dir = self.root_dir / "logs"
        self.locks_dir = self.root_dir / "locks"
        self.backups_dir = self.root_dir / "backups"

        self._ensure_directories()
        self.leader_id = f"leader_{uuid.uuid4().hex[:12]}"
        self._init_db()

    def _ensure_directories(self) -> None:
        """Create owned storage directory structure."""
        for path in [
            self.root_dir,
            self.inbox_dir,
            self.receipts_dir,
            self.artifacts_dir,
            self.logs_dir,
            self.locks_dir,
            self.backups_dir,
        ]:
            path.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self):
        """Yield a configured SQLite connection with auto-commit and guarantee closure."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def close(self) -> None:
        """Close any lingering handles if applicable."""
        pass

    @staticmethod
    def _directory_usage(path: pathlib.Path) -> Dict[str, int]:
        """Return recursive file count/bytes without following symlinks."""
        return _directory_usage(path)

    def storage_status(self) -> Dict[str, Any]:
        """Report bounded storage growth and quota state without retention writes."""
        usage: Dict[str, Dict[str, Any]] = {}
        overall = "PASS"
        for name, limit in STORAGE_QUOTAS_BYTES.items():
            path = getattr(self, f"{name}_dir")
            sample = self._directory_usage(path)
            over_quota = bool(sample["read_error"] or sample["bytes"] > limit)
            if over_quota:
                overall = "BLOCKED"
            usage[name] = {
                "path": str(path),
                "files": sample["files"],
                "bytes": sample["bytes"],
                "ceiling_bytes": limit,
                "over_quota": over_quota,
                "read_error": bool(sample["read_error"]),
            }
        return {
            "status": overall,
            "retention_mode": "REPORT_ONLY",
            "directories": usage,
        }

    def _init_db(self) -> None:
        """Initialize SQLite tables and forward-only schema migrations."""
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at_utc TEXT NOT NULL
                )
                """
            )

            cur = conn.execute("SELECT MAX(version) FROM schema_migrations")
            row = cur.fetchone()
            current_version = row[0] if (row and row[0] is not None) else 0

            if current_version < 1:
                # Backup before migration if DB existed
                if self.db_path.exists() and self.db_path.stat().st_size > 0:
                    backup_file = self.backups_dir / f"conductor_db_v{current_version}_{int(time.time())}.db"
                    shutil.copy2(self.db_path, backup_file)

                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS work_items (
                        work_item_id TEXT PRIMARY KEY,
                        idempotency_key TEXT UNIQUE NOT NULL,
                        title TEXT NOT NULL,
                        repo_id TEXT NOT NULL,
                        repo_path TEXT NOT NULL,
                        plan_path TEXT NOT NULL,
                        risk_class TEXT NOT NULL,
                        workflow TEXT NOT NULL,
                        requested_terminal_stage TEXT NOT NULL,
                        job_kind TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 50,
                        dependency_ids_json TEXT NOT NULL DEFAULT '[]',
                        authority_requirement TEXT NOT NULL DEFAULT 'standing_r2_go',
                        execution_budget_json TEXT NOT NULL,
                        scope_digest_sha256 TEXT NOT NULL DEFAULT '',
                        state TEXT NOT NULL,
                        created_at_utc TEXT NOT NULL,
                        created_by TEXT NOT NULL,
                        schema_version TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS attempts (
                        attempt_id TEXT PRIMARY KEY,
                        work_item_id TEXT NOT NULL,
                        attempt_number INTEGER NOT NULL,
                        agent_host TEXT NOT NULL,
                        agent_instance TEXT NOT NULL,
                        adapter_version TEXT NOT NULL,
                        worktree_path TEXT NOT NULL,
                        branch_name TEXT NOT NULL,
                        base_head_sha TEXT NOT NULL,
                        dispatch_idempotency_key TEXT UNIQUE NOT NULL,
                        status TEXT NOT NULL,
                        reason_code TEXT,
                        started_at_utc TEXT NOT NULL,
                        ended_at_utc TEXT,
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id)
                    );

                    CREATE TABLE IF NOT EXISTS claims (
                        claim_id TEXT PRIMARY KEY,
                        work_item_id TEXT NOT NULL,
                        attempt_id TEXT NOT NULL,
                        claimed_by_host TEXT NOT NULL,
                        claimed_at_utc TEXT NOT NULL,
                        lease_ttl_seconds INTEGER NOT NULL DEFAULT 300,
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id),
                        FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id)
                    );

                    CREATE TABLE IF NOT EXISTS leases (
                        lease_id TEXT PRIMARY KEY,
                        attempt_id TEXT NOT NULL,
                        agent_instance TEXT NOT NULL,
                        heartbeat_sequence INTEGER NOT NULL,
                        expires_at_utc TEXT NOT NULL,
                        last_heartbeat_utc TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id)
                    );

                    CREATE TABLE IF NOT EXISTS checkpoints (
                        checkpoint_id TEXT PRIMARY KEY,
                        work_item_id TEXT NOT NULL,
                        attempt_id TEXT,
                        boundary TEXT NOT NULL,
                        snapshot_path TEXT NOT NULL,
                        snapshot_sha256 TEXT NOT NULL,
                        snapshot_id TEXT NOT NULL,
                        required_gate TEXT NOT NULL,
                        observed_gate_state TEXT NOT NULL,
                        observed_head TEXT,
                        recorded_at_utc TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id)
                    );

                    CREATE TABLE IF NOT EXISTS events (
                        event_id TEXT PRIMARY KEY,
                        work_item_id TEXT NOT NULL,
                        attempt_id TEXT,
                        previous_state TEXT NOT NULL,
                        next_state TEXT NOT NULL,
                        actor_identity TEXT NOT NULL,
                        reason_code TEXT NOT NULL,
                        recorded_at_utc TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}',
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id)
                    );

                    CREATE TABLE IF NOT EXISTS authorizations (
                        authorization_id TEXT PRIMARY KEY,
                        work_item_id TEXT NOT NULL,
                        scope_digest_sha256 TEXT NOT NULL,
                        risk_class TEXT NOT NULL,
                        authorized_workflow TEXT NOT NULL,
                        permitted_terminal_stage TEXT NOT NULL,
                        issued_at_utc TEXT NOT NULL,
                        expires_at_utc TEXT,
                        operator_identity TEXT NOT NULL,
                        interactive_provenance_proven INTEGER NOT NULL DEFAULT 0,
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (work_item_id) REFERENCES work_items(work_item_id)
                    );

                    CREATE TABLE IF NOT EXISTS receipts (
                        receipt_id TEXT PRIMARY KEY,
                        command_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        status TEXT NOT NULL,
                        result_json TEXT NOT NULL DEFAULT '{}',
                        error_message TEXT,
                        processed_at_utc TEXT NOT NULL,
                        schema_version TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS leader_locks (
                        lock_name TEXT PRIMARY KEY,
                        leader_id TEXT NOT NULL,
                        pid INTEGER NOT NULL,
                        process_start_time REAL NOT NULL,
                        acquired_at_utc TEXT NOT NULL,
                        last_heartbeat_utc TEXT NOT NULL
                    );

                    INSERT INTO schema_migrations (version, applied_at_utc) VALUES (1, datetime('now'));
                    """
                )

            if current_version < 2:
                # Resource admission is additive. Preserve the pre-migration DB
                # before creating the host lease tables.
                if self.db_path.exists() and self.db_path.stat().st_size > 0:
                    backup_file = self.backups_dir / f"conductor_db_v{current_version}_pre_resource_{int(time.time())}.db"
                    shutil.copy2(self.db_path, backup_file)

                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS host_resource_pools (
                        resource_key TEXT PRIMARY KEY,
                        capacity INTEGER NOT NULL,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        schema_version TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS host_resource_requests (
                        request_id TEXT PRIMARY KEY,
                        idempotency_key TEXT UNIQUE NOT NULL,
                        resource_key TEXT NOT NULL,
                        purpose TEXT NOT NULL,
                        attempt_id TEXT NOT NULL,
                        agent_instance TEXT NOT NULL,
                        state TEXT NOT NULL,
                        priority INTEGER NOT NULL DEFAULT 50,
                        parent_lease_id TEXT,
                        command_sha256 TEXT NOT NULL DEFAULT '',
                        created_at_utc TEXT NOT NULL,
                        released_at_utc TEXT,
                        reason_code TEXT,
                        schema_version TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS host_resource_leases (
                        lease_id TEXT PRIMARY KEY,
                        request_id TEXT UNIQUE NOT NULL,
                        resource_key TEXT NOT NULL,
                        attempt_id TEXT NOT NULL,
                        agent_instance TEXT NOT NULL,
                        heartbeat_sequence INTEGER NOT NULL,
                        expires_at_utc TEXT NOT NULL,
                        last_heartbeat_utc TEXT NOT NULL,
                        process_pid INTEGER,
                        process_start_time REAL,
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (request_id) REFERENCES host_resource_requests(request_id)
                    );

                    CREATE TABLE IF NOT EXISTS host_resource_events (
                        event_id TEXT PRIMARY KEY,
                        request_id TEXT NOT NULL,
                        lease_id TEXT,
                        previous_state TEXT,
                        next_state TEXT NOT NULL,
                        actor_identity TEXT NOT NULL,
                        reason_code TEXT NOT NULL,
                        recorded_at_utc TEXT NOT NULL,
                        details_json TEXT NOT NULL DEFAULT '{}',
                        schema_version TEXT NOT NULL,
                        FOREIGN KEY (request_id) REFERENCES host_resource_requests(request_id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_host_resource_requests_state
                        ON host_resource_requests(resource_key, state, created_at_utc);
                    CREATE INDEX IF NOT EXISTS idx_host_resource_leases_active
                        ON host_resource_leases(resource_key, expires_at_utc);

                    INSERT OR IGNORE INTO host_resource_pools
                        (resource_key, capacity, enabled, schema_version)
                        VALUES ('host:heavy', 1, 1, 'conductor.resource-pool.v1');
                    INSERT INTO schema_migrations (version, applied_at_utc)
                        VALUES (2, datetime('now'));
                    """
                )

            if current_version < 3:
                # H8 binds the canonical CONTEXT.md identity to a WorkItem.
                # Preserve old databases and keep the digest optional for
                # legacy callers that have not supplied a context packet yet.
                if self.db_path.exists() and self.db_path.stat().st_size > 0:
                    backup_file = self.backups_dir / f"conductor_db_v{current_version}_pre_context_{int(time.time())}.db"
                    shutil.copy2(self.db_path, backup_file)

                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(work_items)").fetchall()
                }
                if "context_digest_sha256" not in columns:
                    conn.execute(
                        "ALTER TABLE work_items ADD COLUMN context_digest_sha256 TEXT NOT NULL DEFAULT ''"
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at_utc) VALUES (3, datetime('now'))"
                )

            if current_version < 4:
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(host_resource_requests)").fetchall()
                }
                if "priority" not in columns:
                    if self.db_path.exists() and self.db_path.stat().st_size > 0:
                        backup_file = self.backups_dir / f"conductor_db_v{current_version}_pre_priority_{int(time.time())}.db"
                        shutil.copy2(self.db_path, backup_file)
                    conn.execute(
                        "ALTER TABLE host_resource_requests ADD COLUMN priority INTEGER NOT NULL DEFAULT 50"
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at_utc) VALUES (4, datetime('now'))"
                )

            if current_version < 5:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS host_resource_pools (
                        resource_key TEXT PRIMARY KEY,
                        capacity INTEGER NOT NULL DEFAULT 1,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        schema_version TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO host_resource_pools
                        (resource_key, capacity, enabled, schema_version)
                        VALUES ('host:heavy', 1, 1, 'conductor.resource-pool.v1')
                    """
                )

                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(host_resource_requests)").fetchall()
                }
                if "slot_key" not in columns:
                    if self.db_path.exists() and self.db_path.stat().st_size > 0:
                        backup_file = self.backups_dir / f"conductor_db_v{current_version}_pre_slot_key_{int(time.time())}.db"
                        shutil.copy2(self.db_path, backup_file)
                    conn.execute(
                        "ALTER TABLE host_resource_requests ADD COLUMN slot_key TEXT NOT NULL DEFAULT ''"
                    )

                conn.execute(
                    """
                    INSERT OR IGNORE INTO host_resource_pools
                        (resource_key, capacity, enabled, schema_version)
                        VALUES ('cdp:perplexity', 3, 1, 'conductor.resource-pool.v1')
                    """
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO host_resource_pools
                        (resource_key, capacity, enabled, schema_version)
                        VALUES ('cdp:tv', 1, 1, 'conductor.resource-pool.v1')
                    """
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO host_resource_pools
                        (resource_key, capacity, enabled, schema_version)
                        VALUES ('cdp:chatgpt', 3, 1, 'conductor.resource-pool.v1')
                    """
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO host_resource_pools
                        (resource_key, capacity, enabled, schema_version)
                        VALUES ('cdp:gemini', 1, 1, 'conductor.resource-pool.v1')
                    """
                )
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at_utc) VALUES (5, datetime('now'))"
                )

    def acquire_leader_lock(self, lock_name: str = "primary_coordinator") -> bool:
        """Acquire or renew single-writer leader lock with PID + process start time verification."""
        current_pid = os.getpid()
        try:
            p = psutil.Process(current_pid)
            start_time = p.create_time()
        except Exception:
            start_time = 0.0

        now_iso = current_utc_iso()

        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM leader_locks WHERE lock_name = ?", (lock_name,))
            row = cur.fetchone()

            if row:
                existing_pid = row["pid"]
                existing_start_time = row["process_start_time"]
                existing_leader_id = row["leader_id"]

                if existing_leader_id == self.leader_id:
                    # Renew existing lock
                    conn.execute(
                        "UPDATE leader_locks SET last_heartbeat_utc = ? WHERE lock_name = ?",
                        (now_iso, lock_name),
                    )
                    return True

                # Check if existing leader process is still alive
                is_alive = False
                try:
                    proc = psutil.Process(existing_pid)
                    if proc.is_running() and abs(proc.create_time() - existing_start_time) < 1.0:
                        is_alive = True
                except Exception:
                    is_alive = False

                if is_alive:
                    # Another active leader exists
                    return False

                # Stale lock recovery
                conn.execute(
                    """
                    UPDATE leader_locks
                    SET leader_id = ?, pid = ?, process_start_time = ?, acquired_at_utc = ?, last_heartbeat_utc = ?
                    WHERE lock_name = ?
                    """,
                    (self.leader_id, current_pid, start_time, now_iso, now_iso, lock_name),
                )
                return True

            else:
                conn.execute(
                    """
                    INSERT INTO leader_locks (lock_name, leader_id, pid, process_start_time, acquired_at_utc, last_heartbeat_utc)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (lock_name, self.leader_id, current_pid, start_time, now_iso, now_iso),
                )
                return True

    def put_inbox_envelope(self, command_envelope: CommandEnvelope) -> pathlib.Path:
        """Atomically place a command envelope into inbox using unique temp file and rename."""
        payload_data = command_envelope.to_dict()
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self.inbox_dir), prefix="env_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(payload_data, f, indent=2)
            final_path = self.inbox_dir / f"env_{command_envelope.command_id}.json"
            os.replace(tmp_path, final_path)
            return final_path
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def poll_inbox_envelopes(self) -> List[pathlib.Path]:
        """List inbox files sorted by filename/creation time."""
        files = sorted([p for p in self.inbox_dir.glob("env_*.json") if p.is_file()])
        return files

    def save_receipt(self, receipt: Receipt) -> pathlib.Path:
        """Save receipt to database and write atomic receipt file."""
        receipt_data = receipt.to_dict()

        with self._connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO receipts (
                    receipt_id, command_id, idempotency_key, status, result_json, error_message, processed_at_utc, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.command_id,
                    receipt.idempotency_key,
                    receipt.status,
                    json.dumps(receipt.result),
                    receipt.error_message,
                    receipt.processed_at_utc,
                    receipt.schema_version,
                ),
            )

        receipt_file = self.receipts_dir / f"receipt_{receipt.command_id}.json"
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self.receipts_dir), prefix="rcp_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(receipt_data, f, indent=2)
            os.replace(tmp_path, receipt_file)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return receipt_file

    def get_receipt(self, idempotency_key: str) -> Optional[Receipt]:
        """Fetch receipt by idempotency key."""
        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM receipts WHERE idempotency_key = ?", (idempotency_key,))
            row = cur.fetchone()
            if row:
                return Receipt(
                    receipt_id=row["receipt_id"],
                    command_id=row["command_id"],
                    idempotency_key=row["idempotency_key"],
                    status=row["status"],
                    result=json.loads(row["result_json"]),
                    error_message=row["error_message"],
                    processed_at_utc=row["processed_at_utc"],
                    schema_version=row["schema_version"],
                )
        return None

    def save_work_item(self, item: WorkItem) -> None:
        """Insert or update WorkItem atomically."""
        item.validate()
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO work_items (
                    work_item_id, idempotency_key, title, repo_id, repo_path, plan_path,
                    risk_class, workflow, requested_terminal_stage, job_kind, priority,
                    dependency_ids_json, authority_requirement, execution_budget_json,
                    scope_digest_sha256, context_digest_sha256, state, created_at_utc, created_by, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_item_id) DO UPDATE SET
                    priority = excluded.priority,
                    dependency_ids_json = excluded.dependency_ids_json,
                    authority_requirement = excluded.authority_requirement,
                    execution_budget_json = excluded.execution_budget_json,
                    scope_digest_sha256 = excluded.scope_digest_sha256,
                    context_digest_sha256 = excluded.context_digest_sha256,
                    state = excluded.state
                """,
                (
                    item.work_item_id,
                    item.idempotency_key,
                    item.title,
                    item.repo_id,
                    item.repo_path,
                    item.plan_path,
                    item.risk_class,
                    item.workflow,
                    item.requested_terminal_stage,
                    item.job_kind,
                    item.priority,
                    json.dumps(item.dependency_ids),
                    item.authority_requirement,
                    json.dumps(item.execution_budget.to_dict()),
                    item.scope_digest_sha256,
                    item.context_digest_sha256,
                    item.state.value if isinstance(item.state, WorkItemState) else item.state,
                    item.created_at_utc,
                    item.created_by,
                    item.schema_version,
                ),
            )

    def get_work_item(self, work_item_id: str) -> Optional[WorkItem]:
        """Fetch WorkItem by ID."""
        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM work_items WHERE work_item_id = ?", (work_item_id,))
            row = cur.fetchone()
            if row:
                return self._row_to_work_item(row)
        return None

    def get_work_item_by_idempotency_key(self, key: str) -> Optional[WorkItem]:
        """Fetch WorkItem by idempotency key."""
        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM work_items WHERE idempotency_key = ?", (key,))
            row = cur.fetchone()
            if row:
                return self._row_to_work_item(row)
        return None

    def list_work_items(self, state: Optional[WorkItemState] = None) -> List[WorkItem]:
        """List WorkItems, optionally filtered by state."""
        with self._connection() as conn:
            if state:
                state_val = state.value if isinstance(state, WorkItemState) else state
                cur = conn.execute("SELECT * FROM work_items WHERE state = ? ORDER BY priority DESC, created_at_utc ASC", (state_val,))
            else:
                cur = conn.execute("SELECT * FROM work_items ORDER BY priority DESC, created_at_utc ASC")
            return [self._row_to_work_item(row) for row in cur.fetchall()]

    def transition_work_item_state(
        self,
        work_item_id: str,
        target_state: WorkItemState,
        actor: str,
        reason_code: str,
        attempt_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> WorkItem:
        """Transition WorkItem state safely, validating state machine and appending event log."""
        with self._connection() as conn:
            cur = conn.execute("SELECT * FROM work_items WHERE work_item_id = ?", (work_item_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"WorkItem {work_item_id} not found")

            current_item = self._row_to_work_item(row)
            current_state = current_item.state

            if not can_transition(current_state, target_state):
                raise ValueError(f"Invalid transition from {current_state} to {target_state}")

            now_iso = current_utc_iso()
            target_val = target_state.value if isinstance(target_state, WorkItemState) else target_state

            conn.execute(
                "UPDATE work_items SET state = ? WHERE work_item_id = ?",
                (target_val, work_item_id),
            )

            event_id = f"evt_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO events (
                    event_id, work_item_id, attempt_id, previous_state, next_state,
                    actor_identity, reason_code, recorded_at_utc, details_json, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    work_item_id,
                    attempt_id,
                    current_state.value if isinstance(current_state, WorkItemState) else current_state,
                    target_val,
                    actor,
                    reason_code,
                    now_iso,
                    json.dumps(details or {}),
                    "conductor.event.v1",
                ),
            )

            current_item.state = target_state
            return current_item

    def save_attempt(self, attempt: Attempt) -> None:
        """Insert or update Attempt."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO attempts (
                    attempt_id, work_item_id, attempt_number, agent_host, agent_instance,
                    adapter_version, worktree_path, branch_name, base_head_sha,
                    dispatch_idempotency_key, status, reason_code, started_at_utc, ended_at_utc, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO UPDATE SET
                    status = excluded.status,
                    reason_code = excluded.reason_code,
                    ended_at_utc = excluded.ended_at_utc
                """,
                (
                    attempt.attempt_id,
                    attempt.work_item_id,
                    attempt.attempt_number,
                    attempt.agent_host,
                    attempt.agent_instance,
                    attempt.adapter_version,
                    attempt.worktree_path,
                    attempt.branch_name,
                    attempt.base_head_sha,
                    attempt.dispatch_idempotency_key,
                    attempt.status,
                    attempt.reason_code,
                    attempt.started_at_utc,
                    attempt.ended_at_utc,
                    attempt.schema_version,
                ),
            )

    def save_claim(self, claim: Claim) -> None:
        """Insert Claim."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO claims (
                    claim_id, work_item_id, attempt_id, claimed_by_host, claimed_at_utc, lease_ttl_seconds, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.claim_id,
                    claim.work_item_id,
                    claim.attempt_id,
                    claim.claimed_by_host,
                    claim.claimed_at_utc,
                    claim.lease_ttl_seconds,
                    claim.schema_version,
                ),
            )

    def save_lease(self, lease: Lease) -> None:
        """Insert or update Lease."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO leases (
                    lease_id, attempt_id, agent_instance, heartbeat_sequence, expires_at_utc, last_heartbeat_utc, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    heartbeat_sequence = excluded.heartbeat_sequence,
                    expires_at_utc = excluded.expires_at_utc,
                    last_heartbeat_utc = excluded.last_heartbeat_utc
                """,
                (
                    lease.lease_id,
                    lease.attempt_id,
                    lease.agent_instance,
                    lease.heartbeat_sequence,
                    lease.expires_at_utc,
                    lease.last_heartbeat_utc,
                    lease.schema_version,
                ),
            )

    def save_resource_pool(self, pool: HostResourcePool) -> None:
        """Insert or update a host resource pool definition."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO host_resource_pools (resource_key, capacity, enabled, schema_version)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(resource_key) DO UPDATE SET
                    capacity = excluded.capacity,
                    enabled = excluded.enabled,
                    schema_version = excluded.schema_version
                """,
                (pool.resource_key, pool.capacity, 1 if pool.enabled else 0, pool.schema_version),
            )

    def get_resource_pool(self, resource_key: str) -> Optional[HostResourcePool]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM host_resource_pools WHERE resource_key = ?", (resource_key,)
            ).fetchone()
        if not row:
            return None
        return HostResourcePool(
            resource_key=row["resource_key"],
            capacity=int(row["capacity"]),
            enabled=bool(row["enabled"]),
            schema_version=row["schema_version"],
        )

    def save_resource_request(self, request: HostResourceRequest) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO host_resource_requests (
                    request_id, idempotency_key, resource_key, purpose, attempt_id,
                    agent_instance, state, priority, parent_lease_id, command_sha256,
                    created_at_utc, released_at_utc, reason_code, slot_key, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    state = excluded.state,
                    priority = excluded.priority,
                    parent_lease_id = excluded.parent_lease_id,
                    released_at_utc = excluded.released_at_utc,
                    reason_code = excluded.reason_code,
                    slot_key = excluded.slot_key
                """,
                (
                    request.request_id,
                    request.idempotency_key,
                    request.resource_key,
                    request.purpose,
                    request.attempt_id,
                    request.agent_instance,
                    request.state.value if isinstance(request.state, HostResourceRequestState) else request.state,
                    request.priority,
                    request.parent_lease_id,
                    request.command_sha256,
                    request.created_at_utc,
                    request.released_at_utc,
                    request.reason_code,
                    request.slot_key,
                    request.schema_version,
                ),
            )

    def save_resource_lease(self, lease: HostResourceLease) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO host_resource_leases (
                    lease_id, request_id, resource_key, attempt_id, agent_instance,
                    heartbeat_sequence, expires_at_utc, last_heartbeat_utc,
                    process_pid, process_start_time, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    heartbeat_sequence = excluded.heartbeat_sequence,
                    expires_at_utc = excluded.expires_at_utc,
                    last_heartbeat_utc = excluded.last_heartbeat_utc,
                    process_pid = excluded.process_pid,
                    process_start_time = excluded.process_start_time
                """,
                (
                    lease.lease_id,
                    lease.request_id,
                    lease.resource_key,
                    lease.attempt_id,
                    lease.agent_instance,
                    lease.heartbeat_sequence,
                    lease.expires_at_utc,
                    lease.last_heartbeat_utc,
                    lease.process_pid,
                    lease.process_start_time,
                    lease.schema_version,
                ),
            )

    def get_resource_request(self, request_id: str) -> Optional[HostResourceRequest]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM host_resource_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
        return self._row_to_resource_request(row) if row else None

    def get_resource_request_by_idempotency(self, idempotency_key: str) -> Optional[HostResourceRequest]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM host_resource_requests WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
        return self._row_to_resource_request(row) if row else None

    def list_resource_requests(
        self, resource_key: Optional[str] = None, states: Optional[List[str]] = None
    ) -> List[HostResourceRequest]:
        clauses: List[str] = []
        params: List[Any] = []
        if resource_key:
            clauses.append("resource_key = ?")
            params.append(resource_key)
        if states:
            placeholders = ",".join("?" for _ in states)
            clauses.append(f"state IN ({placeholders})")
            params.extend(states)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM host_resource_requests{where} ORDER BY priority DESC, created_at_utc, request_id", params
            ).fetchall()
        return [self._row_to_resource_request(row) for row in rows]

    def get_resource_lease(self, lease_id: str) -> Optional[HostResourceLease]:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM host_resource_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
        return self._row_to_resource_lease(row) if row else None

    def list_resource_leases(self, resource_key: Optional[str] = None) -> List[HostResourceLease]:
        query = "SELECT * FROM host_resource_leases"
        params: tuple[Any, ...] = ()
        if resource_key:
            query += " WHERE resource_key = ?"
            params = (resource_key,)
        query += " ORDER BY expires_at_utc, lease_id"
        with self._connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_resource_lease(row) for row in rows]

    @staticmethod
    def _row_to_resource_request(row: sqlite3.Row) -> HostResourceRequest:
        return HostResourceRequest(
            request_id=row["request_id"],
            idempotency_key=row["idempotency_key"],
            resource_key=row["resource_key"],
            purpose=row["purpose"],
            attempt_id=row["attempt_id"],
            agent_instance=row["agent_instance"],
            state=HostResourceRequestState(row["state"]),
            priority=int(row["priority"]),
            parent_lease_id=row["parent_lease_id"],
            command_sha256=row["command_sha256"],
            created_at_utc=row["created_at_utc"],
            released_at_utc=row["released_at_utc"],
            reason_code=row["reason_code"],
            slot_key=str(row["slot_key"]) if "slot_key" in row.keys() and row["slot_key"] is not None else "",
            schema_version=row["schema_version"],
        )

    @staticmethod
    def _row_to_resource_lease(row: sqlite3.Row) -> HostResourceLease:
        return HostResourceLease(
            lease_id=row["lease_id"],
            request_id=row["request_id"],
            resource_key=row["resource_key"],
            attempt_id=row["attempt_id"],
            agent_instance=row["agent_instance"],
            heartbeat_sequence=int(row["heartbeat_sequence"]),
            expires_at_utc=row["expires_at_utc"],
            last_heartbeat_utc=row["last_heartbeat_utc"],
            process_pid=row["process_pid"],
            process_start_time=row["process_start_time"],
            schema_version=row["schema_version"],
        )

    def save_checkpoint(self, checkpoint: EvidenceCheckpoint) -> None:
        """Insert EvidenceCheckpoint."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (
                    checkpoint_id, work_item_id, attempt_id, boundary, snapshot_path,
                    snapshot_sha256, snapshot_id, required_gate, observed_gate_state,
                    observed_head, recorded_at_utc, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.work_item_id,
                    checkpoint.attempt_id,
                    checkpoint.boundary,
                    checkpoint.snapshot_path,
                    checkpoint.snapshot_sha256,
                    checkpoint.snapshot_id,
                    checkpoint.required_gate,
                    checkpoint.observed_gate_state,
                    checkpoint.observed_head,
                    checkpoint.recorded_at_utc,
                    checkpoint.schema_version,
                ),
            )

    def save_authorization(self, auth: AuthorizationRecord) -> None:
        """Insert AuthorizationRecord."""
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO authorizations (
                    authorization_id, work_item_id, scope_digest_sha256, risk_class,
                    authorized_workflow, permitted_terminal_stage, issued_at_utc,
                    expires_at_utc, operator_identity, interactive_provenance_proven, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    auth.authorization_id,
                    auth.work_item_id,
                    auth.scope_digest_sha256,
                    auth.risk_class,
                    auth.authorized_workflow,
                    auth.permitted_terminal_stage,
                    auth.issued_at_utc,
                    auth.expires_at_utc,
                    auth.operator_identity,
                    1 if auth.interactive_provenance_proven else 0,
                    auth.schema_version,
                ),
            )

    def get_authorization(self, work_item_id: str) -> Optional[AuthorizationRecord]:
        """Fetch latest active AuthorizationRecord for WorkItem."""
        with self._connection() as conn:
            cur = conn.execute(
                "SELECT * FROM authorizations WHERE work_item_id = ? ORDER BY issued_at_utc DESC LIMIT 1",
                (work_item_id,),
            )
            row = cur.fetchone()
            if row:
                return AuthorizationRecord(
                    authorization_id=row["authorization_id"],
                    work_item_id=row["work_item_id"],
                    scope_digest_sha256=row["scope_digest_sha256"],
                    risk_class=row["risk_class"],
                    authorized_workflow=row["authorized_workflow"],
                    permitted_terminal_stage=row["permitted_terminal_stage"],
                    issued_at_utc=row["issued_at_utc"],
                    expires_at_utc=row["expires_at_utc"],
                    operator_identity=row["operator_identity"],
                    interactive_provenance_proven=bool(row["interactive_provenance_proven"]),
                    schema_version=row["schema_version"],
                )
        return None

    def export_jsonl(self, output_path: Union[str, pathlib.Path]) -> pathlib.Path:
        """Export all events and entities to a durable JSONL file."""
        out_p = pathlib.Path(output_path).expanduser().resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)

        with self._connection() as conn, open(out_p, "w", encoding="utf-8") as f:
            for table in [
                "work_items", "attempts", "claims", "leases", "checkpoints", "events",
                "authorizations", "host_resource_pools", "host_resource_requests",
                "host_resource_leases", "host_resource_events",
            ]:
                cur = conn.execute(f"SELECT * FROM {table}")
                for row in cur.fetchall():
                    item_dict = dict(row)
                    item_dict["_table"] = table
                    f.write(json.dumps(item_dict) + "\n")

        return out_p

    def _row_to_work_item(self, row: sqlite3.Row) -> WorkItem:
        return WorkItem.from_dict(
            {
                "work_item_id": row["work_item_id"],
                "idempotency_key": row["idempotency_key"],
                "title": row["title"],
                "repo_id": row["repo_id"],
                "repo_path": row["repo_path"],
                "plan_path": row["plan_path"],
                "risk_class": row["risk_class"],
                "workflow": row["workflow"],
                "requested_terminal_stage": row["requested_terminal_stage"],
                "job_kind": row["job_kind"],
                "priority": row["priority"],
                "dependency_ids": json.loads(row["dependency_ids_json"]),
                "authority_requirement": row["authority_requirement"],
                "execution_budget": json.loads(row["execution_budget_json"]),
                "scope_digest_sha256": row["scope_digest_sha256"],
                "context_digest_sha256": row["context_digest_sha256"],
                "state": row["state"],
                "created_at_utc": row["created_at_utc"],
                "created_by": row["created_by"],
                "schema_version": row["schema_version"],
            }
        )
