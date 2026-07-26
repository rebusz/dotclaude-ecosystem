#!/usr/bin/env python3
"""Bounded cleanup for state owned by the session lifecycle hooks."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from session_state import append_hook_error, atomic_write_bytes, read_session_binding


RETENTION_DAYS = 7
VERDICT_OUTER_BOUND_DAYS = 90
MAX_VERDICT_BYTES = 64 * 1024
MAX_SCAN_FILES = 5000
MAX_CURSOR_BYTES = 1024
SCAN_CURSOR_SCHEMA = "session.reaper.cursor.v1"
SCAN_CURSOR_NAME = ".session_reaper_cursor.json"
OWNED_PREFIXES = (
    "turn_counter_",
    "session_plan_",
    "session_binding_",
    "session_verdict_",
    "session_verdict_lock_",
)


@dataclass(frozen=True)
class _Candidate:
    priority_timestamp: float
    name: str
    modified_timestamp: float
    path: Path


@dataclass(frozen=True)
class _NewestFirst:
    candidate: _Candidate

    def __lt__(self, other: _NewestFirst) -> bool:
        mine = (self.candidate.priority_timestamp, self.candidate.name)
        theirs = (other.candidate.priority_timestamp, other.candidate.name)
        return mine > theirs


def _session_id(name: str) -> str | None:
    if name.startswith("turn_counter_"):
        return name.removeprefix("turn_counter_") or None
    if name.startswith("session_plan_") and name.endswith(".json"):
        return name.removeprefix("session_plan_").removesuffix(".json") or None
    if name.startswith("session_binding_") and name.endswith(".json"):
        return name.removeprefix("session_binding_").removesuffix(".json") or None
    if name.startswith("session_verdict_") and name.endswith(".json"):
        return name.removeprefix("session_verdict_").removesuffix(".json") or None
    if name.startswith("session_verdict_lock_"):
        return name.removeprefix("session_verdict_lock_") or None
    return None


def _read_verdict(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_VERDICT_BYTES:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _should_delete_verdict(
    path: Path,
    *,
    modified: datetime,
    retention_cutoff: datetime,
    outer_cutoff: datetime,
) -> bool:
    verdict = _read_verdict(path)
    created = _verdict_created_at(verdict, modified=modified)
    if created < outer_cutoff:
        return True
    return (
        verdict is not None
        and bool(verdict.get("consumed_at"))
        and modified < retention_cutoff
    )


def _verdict_created_at(
    verdict: dict[str, Any] | None,
    *,
    modified: datetime,
) -> datetime:
    if verdict is None:
        return modified
    raw_created = verdict.get("created_at")
    if isinstance(raw_created, str):
        try:
            created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
            return created if created.tzinfo is not None else created.replace(tzinfo=UTC)
        except ValueError:
            pass
    return modified


def _verdict_past_outer_bound(
    path: Path,
    *,
    modified: datetime,
    outer_cutoff: datetime,
) -> bool:
    return _verdict_created_at(
        _read_verdict(path),
        modified=modified,
    ) < outer_cutoff


def _binding_transcript_is_fresh(
    session_id: str,
    *,
    state_dir: Path,
    retention_cutoff: datetime,
) -> bool:
    binding = read_session_binding(session_id, state_dir=state_dir)
    if binding is None:
        return False
    try:
        transcript_modified = datetime.fromtimestamp(
            Path(binding["transcript_path"]).stat().st_mtime,
            tz=UTC,
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False
    return transcript_modified >= retention_cutoff


def _candidate_priority(path: Path, *, modified_timestamp: float) -> float:
    if path.name.startswith("session_verdict_") and path.name.endswith(".json"):
        modified = datetime.fromtimestamp(modified_timestamp, tz=UTC)
        return _verdict_created_at(
            _read_verdict(path),
            modified=modified,
        ).timestamp()
    return modified_timestamp


def _oldest_candidates(
    state_dir: Path,
    *,
    limit: int,
) -> tuple[list[_Candidate], bool]:
    """Return the globally oldest bounded candidates from a complete name scan."""

    import heapq

    limit = max(1, limit)
    heap: list[_NewestFirst] = []
    owned_count = 0
    with os.scandir(state_dir) as iterator:
        for entry in iterator:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            if not entry.name.startswith(OWNED_PREFIXES):
                continue
            try:
                modified_timestamp = entry.stat(follow_symlinks=False).st_mtime
            except FileNotFoundError:
                continue
            path = Path(entry.path)
            candidate = _Candidate(
                priority_timestamp=_candidate_priority(
                    path,
                    modified_timestamp=modified_timestamp,
                ),
                name=entry.name,
                modified_timestamp=modified_timestamp,
                path=path,
            )
            owned_count += 1
            item = _NewestFirst(candidate)
            if len(heap) < limit:
                heapq.heappush(heap, item)
                continue
            newest_retained = heap[0].candidate
            if (candidate.priority_timestamp, candidate.name) < (
                newest_retained.priority_timestamp,
                newest_retained.name,
            ):
                heapq.heapreplace(heap, item)
    candidates = sorted(
        (item.candidate for item in heap),
        key=lambda item: (item.priority_timestamp, item.name),
    )
    return candidates, owned_count > limit


def _scan_cursor_path(state_dir: Path) -> Path:
    return state_dir / SCAN_CURSOR_NAME


def _read_scan_cursor(state_dir: Path) -> str | None:
    path = _scan_cursor_path(state_dir)
    try:
        if path.is_symlink():
            return None
        raw = path.read_bytes()
        if len(raw) > MAX_CURSOR_BYTES:
            return None
        value = json.loads(raw)
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != SCAN_CURSOR_SCHEMA
        or not isinstance(value.get("after_name"), str)
    ):
        return None
    return value["after_name"]


def _write_scan_cursor(state_dir: Path, after_name: str) -> None:
    payload = (
        json.dumps(
            {
                "schema_version": SCAN_CURSOR_SCHEMA,
                "after_name": after_name,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_CURSOR_BYTES:
        raise ValueError("reaper cursor exceeds size bound")
    atomic_write_bytes(_scan_cursor_path(state_dir), payload)


def _rotate_after_cursor(
    candidates: list[_Candidate],
    after_name: str | None,
) -> list[_Candidate]:
    if not candidates or after_name is None:
        return candidates
    for index, candidate in enumerate(candidates):
        if candidate.name == after_name:
            split = index + 1
            return candidates[split:] + candidates[:split]
    return candidates


def reap_state(
    *,
    state_dir: Path,
    current_session_id: str,
    live_session_ids: set[str] | None,
    now: datetime | None = None,
    retention_days: int = RETENTION_DAYS,
    verdict_outer_bound_days: int = VERDICT_OUTER_BOUND_DAYS,
    max_files: int = 200,
    time_budget_s: float = 0.15,
) -> dict[str, int | bool]:
    """Delete only old owned state, respecting liveness and verdict delivery.

    Candidate selection is a complete bounded-memory pass so directory order
    cannot starve old files. ``time_budget_s`` bounds the subsequent evidence
    and deletion phase; the caller separately bounds the full hook wall time.
    """

    started = time.perf_counter()
    deadline = started + max(0.001, time_budget_s)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    retention_cutoff = current - timedelta(days=max(1, retention_days))
    outer_cutoff = current - timedelta(days=max(retention_days + 1, verdict_outer_bound_days))
    live = set(live_session_ids or ())
    live.add(current_session_id)
    summary: dict[str, int | bool] = {
        "scanned": 0,
        "deleted": 0,
        "skipped_live": 0,
        "errors": 0,
        "time_budget_hit": False,
        "file_limit_hit": False,
    }

    try:
        entries, candidate_limit_hit = _oldest_candidates(
            state_dir,
            limit=MAX_SCAN_FILES,
        )
        summary["file_limit_hit"] = candidate_limit_hit
        entries = _rotate_after_cursor(entries, _read_scan_cursor(state_dir))
    except FileNotFoundError:
        return summary
    except OSError as exc:
        append_hook_error("REAPER_SCAN_FAILED", type(exc).__name__, state_dir=state_dir)
        summary["errors"] = 1
        return summary

    binding_liveness: dict[str, bool] = {}
    last_scanned_name: str | None = None
    for candidate in entries:
        if int(summary["scanned"]) > 0 and time.perf_counter() >= deadline:
            summary["time_budget_hit"] = True
            break
        if int(summary["deleted"]) >= max(0, max_files):
            summary["file_limit_hit"] = True
            break
        summary["scanned"] = int(summary["scanned"]) + 1
        last_scanned_name = candidate.name
        modified_timestamp = candidate.modified_timestamp
        path = candidate.path
        session_id = _session_id(path.name)
        if session_id is None:
            continue
        if session_id not in live:
            is_fresh = binding_liveness.get(session_id)
            if is_fresh is None:
                is_fresh = _binding_transcript_is_fresh(
                    session_id,
                    state_dir=state_dir,
                    retention_cutoff=retention_cutoff,
                )
                binding_liveness[session_id] = is_fresh
            if is_fresh:
                live.add(session_id)
        modified = datetime.fromtimestamp(modified_timestamp, tz=UTC)
        is_verdict = path.name.startswith("session_verdict_") and path.name.endswith(".json")
        verdict_hard_expired = is_verdict and _verdict_past_outer_bound(
            path,
            modified=modified,
            outer_cutoff=outer_cutoff,
        )
        if session_id in live and not verdict_hard_expired:
            summary["skipped_live"] = int(summary["skipped_live"]) + 1
            continue
        delete = (
            path.name.startswith(
                (
                    "turn_counter_",
                    "session_plan_",
                    "session_binding_",
                    "session_verdict_lock_",
                )
            )
            and modified < retention_cutoff
        )
        if is_verdict:
            delete = _should_delete_verdict(
                path,
                modified=modified,
                retention_cutoff=retention_cutoff,
                outer_cutoff=outer_cutoff,
            )
        if not delete:
            continue
        try:
            path.unlink()
            summary["deleted"] = int(summary["deleted"]) + 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            summary["errors"] = int(summary["errors"]) + 1
            append_hook_error(
                "REAPER_DELETE_FAILED",
                f"{path.name}:{type(exc).__name__}",
                state_dir=state_dir,
            )
    if last_scanned_name is not None:
        try:
            _write_scan_cursor(state_dir, last_scanned_name)
        except (OSError, ValueError) as exc:
            summary["errors"] = int(summary["errors"]) + 1
            append_hook_error("REAPER_CURSOR_WRITE_FAILED", type(exc).__name__, state_dir=state_dir)
    return summary
