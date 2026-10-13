"""Read-only process diagnostics and fail-closed, opt-in orphan reclamation.

The registry, not a process name or parent PID, supplies launch ownership.
No environment is read, and command lines are reduced to a hash before leaving
the collector. This module is not a replacement for retained Popen supervision.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from typing import Any, Callable, Iterable, Mapping

try:
    import psutil
except ImportError:
    psutil = None


GIB = 1024**3
_AMBIGUOUS = {"SUBMIT_UNCONFIRMED", "RECOVERY_REQUIRED", "STARTING"}
_SCHEDULERS = {"taskeng", "taskhost", "taskhostw", "schtasks", "services", "svchost"}
_INTERACTIVE = {"windowsterminal", "openconsole", "explorer", "code", "codex"}


class ProcessTable(list):
    """A PID enumeration with explicit completeness; plain lists are unproven."""

    def __init__(self, rows=(), *, complete: bool = False, error: str | None = None):
        super().__init__(rows)
        self.complete = complete
        self.error = error


class ReapRefused(RuntimeError):
    pass


class TerminationCleanupUnconfirmed(ReapRefused):
    """The termination request succeeded but closing its pinned handle failed."""


def process_session_id(pid: int) -> int:
    """Return the Windows session id or POSIX session for ``pid``."""
    pid = int(pid)
    if pid <= 0:
        raise OSError(22, "session lookup failed: invalid pid")
    if os.name != "nt":
        return os.getsid(pid)
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32  # stdcall; WinDLL/cdecl mismatches yield ERROR_INVALID_PARAMETER (87)
    session = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(wintypes.DWORD(pid & 0xFFFFFFFF), ctypes.byref(session)):
        err = ctypes.get_last_error() or 87
        raise OSError(err, "session lookup failed")
    return int(session.value)


def command_sha256(command: Iterable[str]) -> str:
    return hashlib.sha256(json.dumps(list(command), separators=(",", ":")).encode()).hexdigest()


def _basename(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".exe")


def protected_reason(command=(), *, name: str = "", worktree: str = "") -> str | None:
    """Inspect transient text, returning only a fixed policy reason."""
    value = " ".join([name, worktree, *command]).replace("\\", "/").lower()
    if any(part in value for part in (".cursor/projects", ".devspace", "s1a-ledger-20261010-01a10bd5")):
        return "PROTECTED_DEVSPACE"
    if re.search(r"tsignal[_-]?bot|live[ _-]?bot", value):
        return "PROTECTED_LIVE_BOT"
    if re.search(r"\b(tws|ib|ibkr|ibgateway)\b|ib[ _-]?gateway|interactive[ _-]?brokers", value):
        return "PROTECTED_BROKER"
    if "cctv" in value or "tools.channel_reader_cv" in value:
        return "PROTECTED_CCTV"
    if "watchf" in value or "tsignallab" in value or re.search(r"\blab[ _/-]*(daemon|service|worker)", value):
        return "PROTECTED_DAEMON"
    if _basename(name) in _SCHEDULERS or re.search(r"scheduled[ _-]?task|--scheduled\b|schtasks", value):
        return "PROTECTED_SCHEDULED_TASK"
    return None


def launch_origin(pid: int | None = None) -> str:
    """Prove an interactive launcher; inaccessible/reused ancestry is unknown."""
    if psutil is None:
        return "unknown"
    try:
        current = psutil.Process(os.getpid() if pid is None else pid)
        session = process_session_id(current.pid)
        if session == 0:
            return "scheduled"
        interactive = False
        seen: set[int] = set()
        while current.pid not in seen:
            seen.add(current.pid)
            name = _basename(current.name())
            if name in _SCHEDULERS:
                return "scheduled"
            if process_session_id(current.pid) == session:
                if os.name == "nt" and name in _INTERACTIVE:
                    interactive = True
                elif os.name != "nt" and current.terminal():
                    interactive = True
            parent_pid = current.ppid()
            if parent_pid == 0:
                return "interactive" if interactive else "unknown"
            parent = psutil.Process(parent_pid)
            if parent.create_time() > current.create_time():
                return "unknown"
            current = parent
    except (psutil.Error, OSError, ValueError):
        return "unknown"
    return "unknown"


def collect_process_table() -> ProcessTable:
    """Enumerate processes without reading environments or returning arguments."""
    if psutil is None:
        return ProcessTable(error="PSUTIL_UNAVAILABLE")
    try:
        pids = psutil.pids()
    except (psutil.Error, OSError) as exc:
        return ProcessTable(error=type(exc).__name__)
    rows = ProcessTable(complete=True)
    for pid in pids:
        row = dict.fromkeys(("start_time", "parent_pid", "session_id", "username", "command_sha256", "rss_bytes", "name", "protected_reason", "inspection_error"))
        row["pid"] = pid
        try:
            process = psutil.Process(pid)
            row["start_time"] = process.create_time()
            row["parent_pid"] = process.ppid()
            row["session_id"] = process_session_id(pid)
            row["username"] = process.username()
            row["name"] = process.name()
            row["rss_bytes"] = process.memory_info().rss
            command = process.cmdline()
            row["command_sha256"] = command_sha256(command) if command else None
            row["protected_reason"] = protected_reason(command, name=row["name"], worktree=process.cwd())
            # A fresh Process avoids psutil's cached creation time concealing reuse.
            if not _same_time(row["start_time"], psutil.Process(pid).create_time()):
                row["inspection_error"] = "PID_REUSED_DURING_INSPECTION"
        except (psutil.Error, OSError, ValueError) as exc:
            row["inspection_error"] = type(exc).__name__
        rows.append(row)
    return rows


def read_registry(root):
    """Read existing ownership only; never create/migrate the live database."""
    import pathlib
    import sqlite3

    path = pathlib.Path(root).resolve() / "conductor.db"
    if not path.is_file():
        return [], "REGISTRY_ABSENT"
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        conn.row_factory = sqlite3.Row
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"process_lanes", "process_registry"}.issubset(tables):
            return [], "LEGACY_REGISTRY_NO_OWNERSHIP"
        rows = [dict(row) for row in conn.execute("""
            SELECT l.*, p.pid, p.start_time, p.parent_pid, p.session_id, p.username,
                   p.command_sha256 AS process_command_sha256, r.state AS request_state
            FROM process_lanes l JOIN process_registry p USING(lane_id)
            LEFT JOIN host_resource_requests r ON r.request_id=l.request_id
        """)]
    for row in rows:
        row["command_sha256"] = row.pop("process_command_sha256")
    return rows, "RECORDED"


def main(argv=None):
    """conductorctl process-report: read-only unless explicitly passed --kill."""
    import argparse
    import pathlib

    parser = argparse.ArgumentParser(description="Conductor owned process report (default dry-run)")
    parser.add_argument("--registry-root", type=pathlib.Path,
                        default=pathlib.Path(os.environ.get("TDCONDUCTOR_DIR", pathlib.Path.home() / ".conductor")))
    parser.add_argument("--owner", required=True, help="Exact Conductor owner ID; other owners always KEEP")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="Prefix for JSON and Markdown reports")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Default; never terminate anything")
    mode.add_argument("--kill", action="store_true", help="Explicitly act on freshly proven stale owned identities")
    args = parser.parse_args(argv)
    try:
        records, registry_status = read_registry(args.registry_root)
        processes = collect_process_table()
        controller = next((p for p in processes if p["pid"] == os.getpid()), {})
        context = dict(owner_id=args.owner, session_id=controller.get("session_id"),
                       username=controller.get("username"), controller_pid=os.getpid())
        if args.kill:
            if registry_status != "RECORDED" or not processes.complete:
                raise ReapRefused("complete process table and registry required")
            report = execute_reap(lambda: read_registry(args.registry_root)[0], kill=True, **context)
        else:
            report = build_report(records, processes, **context)
        report["registry_status"] = registry_status
        if psutil is not None:
            try:
                mem = psutil.virtual_memory()
                report["memory"] = {"available_gib": mem.available / GIB, "total_gib": mem.total / GIB}
            except (OSError, psutil.Error) as exc:
                report["memory_error"] = type(exc).__name__
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        args.output.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
        print(json.dumps({"mode": report["mode"], "registry_status": registry_status,
                          "collection_error": report["collection_error"], **report["summary"]}))
        return 0 if not report["collection_error"] and not report.get("actuation_incomplete") else 2
    except (OSError, ValueError, sqlite3.Error, ReapRefused) as exc:
        print(json.dumps({"status": "REPORT_FAILED", "reason": type(exc).__name__}))
        return 2


def _timestamp(value: Any) -> float | None:
    try:
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return None
            number = parsed.timestamp()
        elif isinstance(value, datetime):
            if value.tzinfo is None:
                return None
            number = value.timestamp()
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
        else:
            return None
        return number if math.isfinite(number) and number > 0 else None
    except (ValueError, OverflowError):
        return None


def _same_time(first: Any, second: Any) -> bool:
    a, b = _timestamp(first), _timestamp(second)
    return a is not None and b is not None and abs(a - b) <= 1e-6


def _valid_pid(value: Any, *, zero: bool = False) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= (0 if zero else 1)


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _metadata_known(process: Mapping[str, Any]) -> bool:
    return (
        not process.get("inspection_error")
        and "inspection_error" in process and "protected_reason" in process
        and _valid_pid(process.get("pid")) and _valid_pid(process.get("parent_pid"), zero=True)
        and _valid_pid(process.get("session_id")) and _timestamp(process.get("start_time")) is not None
        and bool(process.get("username")) and bool(process.get("name"))
        and _valid_hash(process.get("command_sha256"))
        and isinstance(process.get("rss_bytes"), int) and process["rss_bytes"] >= 0
    )


def _username(value: Any) -> str:
    return value.casefold() if isinstance(value, str) else ""


def _system_user(value: Any) -> bool:
    return _username(value).replace("/", "\\").rsplit("\\", 1)[-1] in {"system", "local service", "network service", "root"}


def _ancestors(pid: int, table: Mapping[int, Mapping[str, Any]]) -> set[int]:
    result: set[int] = set()
    while pid in table and pid not in result:
        result.add(pid)
        pid = table[pid].get("parent_pid")
    return result


def _ancestry_known(pid: int, table: Mapping[int, Mapping[str, Any]]) -> bool:
    seen: set[int] = set()
    while pid and pid in table and pid not in seen:
        seen.add(pid)
        item = table[pid]
        parent_pid = item.get("parent_pid")
        if item.get("inspection_error") or not _valid_pid(parent_pid, zero=True):
            return False
        if parent_pid == 0:
            return True
        parent = table.get(parent_pid)
        child_time = _timestamp(item.get("start_time"))
        parent_time = _timestamp(parent.get("start_time")) if parent else None
        if child_time is None or parent_time is None or parent_time > child_time:
            return False
        pid = parent_pid
    return False


def _keep_reason(record, process, table, *, owner_id, session_id, username, now, protected_pids):
    if process.get("pid") in protected_pids:
        return "CONTROLLER_OR_ANCESTOR"
    if process.get("protected_reason"):
        return process["protected_reason"]
    if process.get("session_id") == 0 or _system_user(process.get("username")):
        return "SYSTEM_OR_SESSION_ZERO"
    if process.get("session_id") != session_id or _username(process.get("username")) != _username(username):
        return "OTHER_SESSION_OR_USER"
    if not _metadata_known(process):
        return "PROCESS_METADATA_UNKNOWN"
    if record is None:
        return "UNREGISTERED"
    if record.get("owner_id") != owner_id:
        return "OTHER_OWNER"
    if record.get("launch_provenance") != "conductor" or record.get("launch_origin") != "interactive":
        return "LAUNCH_PROVENANCE_UNKNOWN"
    denied = protected_reason(worktree=str(record.get("worktree", "")))
    if denied:
        return denied
    if record.get("state") in _AMBIGUOUS or record.get("request_state") in _AMBIGUOUS:
        return "UNCERTAIN_ATTEMPT"
    if record.get("state") not in {"RUNNING", "TERMINAL"}:
        return "REGISTRY_STATE_UNKNOWN"
    if record.get("request_id") and not record.get("request_state"):
        return "REQUEST_STATE_UNKNOWN"
    if not all(record.get(key) for key in ("lane_id", "worktree", "owner_username")):
        return "REGISTRY_METADATA_UNKNOWN"
    if not _valid_pid(record.get("owner_pid")) or _timestamp(record.get("owner_start_time")) is None:
        return "OWNER_IDENTITY_UNKNOWN"
    if record.get("owner_session_id") != session_id or _username(record.get("owner_username")) != _username(username):
        return "OTHER_OWNER_SESSION_OR_USER"
    if record.get("session_id") != session_id or _username(record.get("username")) != _username(username):
        return "REGISTRY_SESSION_OR_USER_MISMATCH"
    if not _same_time(record.get("start_time"), process.get("start_time")):
        return "PID_REUSED"
    if record.get("command_sha256") != process.get("command_sha256"):
        return "COMMAND_IDENTITY_MISMATCH"
    if record.get("parent_pid") != process.get("parent_pid"):
        return "PARENT_IDENTITY_MISMATCH"
    heartbeat, deadline = _timestamp(record.get("heartbeat")), _timestamp(record.get("deadline"))
    started = _timestamp(record["start_time"])
    if (heartbeat is None or deadline is None or not started <= heartbeat <= now
            or deadline < started or _timestamp(record["owner_start_time"]) > started):
        return "REGISTRY_CLOCK_UNKNOWN"
    if record["state"] != "TERMINAL" and deadline >= now:
        return "LANE_NOT_STALE"
    if not table.complete:
        return "PROCESS_TABLE_INCOMPLETE"
    owner = table.by_pid.get(record["owner_pid"])
    if owner is not None:
        if not _metadata_known(owner):
            return "OWNER_LIVENESS_UNKNOWN"
        if _same_time(owner["start_time"], record["owner_start_time"]):
            return "OWNER_STILL_ALIVE"
        if _timestamp(owner["start_time"]) < _timestamp(record["owner_start_time"]):
            return "OWNER_IDENTITY_CONFLICT"
    for ancestor_pid in _ancestors(process["pid"], table.by_pid) - {process["pid"]}:
        ancestor = table.by_pid[ancestor_pid]
        if ancestor.get("protected_reason"):
            return "PROTECTED_ANCESTRY"
    return None


def build_report(records, processes, *, owner_id, session_id, username, now=None, controller_pid=None) -> dict:
    """Classify a snapshot; absent owners require proven complete enumeration."""
    timestamp = _timestamp(time.time() if now is None else now)
    if timestamp is None:
        raise ValueError("invalid report time")
    controller_pid = os.getpid() if controller_pid is None else controller_pid
    table = ProcessTable(processes, complete=getattr(processes, "complete", False) is True)
    table.by_pid = {row["pid"]: row for row in table if _valid_pid(row.get("pid"), zero=True)}
    if len(table.by_pid) != len(table):
        table.complete = False
    protected_pids = _ancestors(controller_pid, table.by_pid) | {controller_pid}
    records_by_pid: dict[int, list] = {}
    for record in records:
        records_by_pid.setdefault(record.get("pid"), []).append(record)
    rows = []
    for process in table:
        matches = records_by_pid.get(process.get("pid"), [])
        exact = [item for item in matches if _same_time(item.get("start_time"), process.get("start_time"))]
        record = exact[0] if len(exact) == 1 else matches[0] if len(matches) == 1 else None
        reason = _keep_reason(record, process, table, owner_id=owner_id, session_id=session_id,
                              username=username, now=timestamp, protected_pids=protected_pids)
        if not reason and not _ancestry_known(controller_pid, table.by_pid):
            reason = "CONTROLLER_ANCESTRY_UNKNOWN"
        if len(exact) > 1 or (len(matches) > 1 and not exact):
            reason = "REGISTRY_IDENTITY_CONFLICT"
        rss = process.get("rss_bytes")
        rows.append({
            "pid": process.get("pid"), "start_time": process.get("start_time"), "parent_pid": process.get("parent_pid"),
            "owner": record.get("owner_id") if record else None,
            "lane": record.get("lane_id") if record else None,
            "session_id": process.get("session_id"), "name": process.get("name"),
            "rss_gib": round(rss / GIB, 6) if isinstance(rss, int) and rss >= 0 else None,
            "action": "KEEP" if reason else "WOULD_KILL",
            "reason": reason or ("TERMINAL_LANE_OWNER_GONE" if record["state"] == "TERMINAL" else "DEADLINE_EXPIRED_OWNER_GONE"),
        })
    # Never terminate a parent while a descendant is unidentified, protected or
    # alive under another lane. Unknown PPIDs make descendant absence unproven.
    row_by_pid = {row["pid"]: row for row in rows}
    unknown_parents = any(not _valid_pid(process.get("parent_pid"), zero=True) for process in table)
    changed = True
    while changed:
        changed = False
        for row in rows:
            if row["action"] != "WOULD_KILL":
                continue
            blocked = unknown_parents or any(
                child["action"] != "WOULD_KILL" and row["pid"] in _ancestors(child["pid"], table.by_pid) - {child["pid"]}
                for child in row_by_pid.values()
            )
            if blocked:
                row.update(action="KEEP", reason="DESCENDANT_OWNERSHIP_UNKNOWN")
                changed = True
    reason_totals = {}
    for row in rows:
        group = reason_totals.setdefault(row["reason"], {"count": 0, "rss_gib": 0.0})
        group["count"] += 1
        group["rss_gib"] = round(group["rss_gib"] + (row["rss_gib"] or 0), 6)
    return {
        "schema_version": 1, "mode": "dry-run", "generated_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "process_table_complete": table.complete, "collection_error": getattr(processes, "error", None), "rows": rows,
        "summary": {"processes": len(rows), "would_kill": sum(row["action"] == "WOULD_KILL" for row in rows),
                    "keep": sum(row["action"] == "KEEP" for row in rows),
                    "would_free_rss_gib": round(sum(row["rss_gib"] or 0 for row in rows if row["action"] == "WOULD_KILL"), 6),
                    "keep_rss_gib": round(sum(row["rss_gib"] or 0 for row in rows if row["action"] == "KEEP"), 6),
                    "rss_unknown_count": sum(row["rss_gib"] is None for row in rows),
                    "by_reason": reason_totals},
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    def cell(value):
        return str(value if value is not None else "unknown").replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    summary = report["summary"]
    lines = ["# Conductor process report", "", f"Mode: {report['mode']}. Process table complete: {report['process_table_complete']}.",
             f"Processes: {summary['processes']}; would-kill: {summary['would_kill']} ({summary['would_free_rss_gib']} GiB RSS); "
             f"keep: {summary['keep']} ({summary['keep_rss_gib']} GiB RSS); unknown RSS: {summary['rss_unknown_count']}.",
             "RSS sums can double-count shared pages; they are not guaranteed physical RAM savings.",
             f"Registry: {cell(report.get('registry_status'))}. Collection error: {cell(report.get('collection_error'))}.",
             "", "| PID | Owner | Lane | RSS GiB | Action | Reason |", "| --- | --- | --- | ---: | --- | --- |"]
    lines.extend("| " + " | ".join(cell(row.get(key)) for key in ("pid", "owner", "lane", "rss_gib", "action", "reason")) + " |" for row in report["rows"])
    if report.get("actuation"):
        lines.extend(["", "## Actuation outcomes", "", "| PID | Status | Reason |", "| --- | --- | --- |"])
        lines.extend("| " + " | ".join(cell(row.get(key)) for key in ("pid", "status", "reason")) + " |"
                     for row in report["actuation"])
    if report.get("actuation_incomplete"):
        lines.extend(["", "Actuation stopped: " + cell(report.get("actuation_error"))])
    return "\n".join(lines) + "\n"


def _terminate_windows_identity(process: Mapping[str, Any]) -> None:
    """Pin process identity in a kernel handle; never fall back to PID/tree kill."""
    if os.name != "nt":
        raise ReapRefused("UNSUPPORTED_PLATFORM")
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000 | 0x0001, False, process["pid"])
    if not handle:
        raise ReapRefused("OPEN_PROCESS_FAILED")
    requested = False
    try:
        created, exited, system, user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            raise ReapRefused("PROCESS_TIME_UNAVAILABLE")
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        start_time = (ticks // 10_000_000 - 11644473600) + ticks % 10_000_000 / 10_000_000
        if not _same_time(start_time, process["start_time"]):
            raise ReapRefused("PID_REUSED_AT_ACTUATION")
        if not kernel.TerminateProcess(handle, 1):
            raise ReapRefused("TERMINATION_FAILED")
        requested = True
    finally:
        if not kernel.CloseHandle(handle):
            if requested:
                raise TerminationCleanupUnconfirmed("PROCESS_HANDLE_CLOSE_FAILED_AFTER_TERMINATION_REQUEST")
            raise ReapRefused("PROCESS_HANDLE_CLOSE_FAILED")


def execute_reap(read_records: Callable, *, owner_id, session_id, username, controller_pid=None,
                 kill: bool = False, now=None, collect: Callable | None = None) -> dict:
    """Opt-in actuator. Every action uses a fresh registry and process snapshot."""
    collect = collect or collect_process_table
    context = dict(owner_id=owner_id, session_id=session_id, username=username, controller_pid=controller_pid, now=now)
    report = build_report(read_records(), collect(), **context)
    report["actuation"] = []
    if not kill:
        return report
    report["mode"] = "kill"
    # Leaf-first reduces the chance of orphaning a separately registered child.
    initial_by_pid = {row["pid"]: row for row in report["rows"]}
    candidates = [row for row in report["rows"] if row["action"] == "WOULD_KILL"]
    candidates.sort(key=lambda row: len(_ancestors(row["pid"], initial_by_pid)), reverse=True)
    for candidate in candidates:
        try:
            fresh = build_report(read_records(), collect(), **context)
        except (OSError, ValueError, sqlite3.Error) as exc:
            report.update(actuation_incomplete=True, actuation_error=type(exc).__name__)
            break
        row = next((item for item in fresh["rows"] if item["pid"] == candidate["pid"]), None)
        outcome = {"pid": candidate["pid"], "status": "KEPT", "reason": "IDENTITY_OR_POLICY_CHANGED"}
        if row and row["action"] == "WOULD_KILL" and _same_time(row["start_time"], candidate["start_time"]):
            try:
                _terminate_windows_identity(row)
                outcome.update(status="TERMINATION_REQUESTED", reason="PINNED_IDENTITY_TERMINATION")
            except TerminationCleanupUnconfirmed as exc:
                outcome.update(status="TERMINATION_REQUESTED_CLEANUP_UNCONFIRMED", reason=str(exc))
                report.update(actuation_incomplete=True, actuation_error=str(exc))
            except ReapRefused as exc:
                outcome["reason"] = str(exc)
            except (OSError, ValueError) as exc:
                outcome["reason"] = type(exc).__name__
        report["actuation"].append(outcome)
        if report.get("actuation_incomplete"):
            break
    return report
