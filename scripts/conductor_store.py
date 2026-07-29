"""Single-writer SQLite WAL storage engine, atomic inbox processor, and leader lock for TruthDeck Conductor.

Port-free design operating over ~/.conductor (or a configured root path).
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import pathlib
import psutil
import shutil
import sqlite3
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
    Receipt,
    WorkItem,
    WorkItemState,
    can_transition,
    current_utc_iso,
)


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
        result.update(
            {
                "store_state": "AVAILABLE",
                "leader_id": leader_row["leader_id"] if leader_row else None,
                "leader_pid": int(leader_row["pid"]) if leader_row else None,
                "leader_process_start_time": float(leader_row["process_start_time"]) if leader_row else None,
                "leader_active": leader_active,
                "total_work_items": sum(int(row["count"]) for row in state_rows),
                "state_summary": {str(row["state"]): int(row["count"]) for row in state_rows},
            }
        )
    except (OSError, sqlite3.Error) as exc:
        result.update({"store_state": "CORRUPT_OR_UNREADABLE", "error": str(exc)[:500]})
    return result


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
    """Read one work item through a SQLite read-only URI."""
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
                    scope_digest_sha256, state, created_at_utc, created_by, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(work_item_id) DO UPDATE SET
                    priority = excluded.priority,
                    dependency_ids_json = excluded.dependency_ids_json,
                    authority_requirement = excluded.authority_requirement,
                    execution_budget_json = excluded.execution_budget_json,
                    scope_digest_sha256 = excluded.scope_digest_sha256,
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
            for table in ["work_items", "attempts", "claims", "leases", "checkpoints", "events", "authorizations"]:
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
                "state": row["state"],
                "created_at_utc": row["created_at_utc"],
                "created_by": row["created_by"],
                "schema_version": row["schema_version"],
            }
        )
