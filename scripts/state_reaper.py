#!/usr/bin/env python3
"""Bounded cleanup for state owned by the session lifecycle hooks."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from session_state import append_hook_error, read_session_binding


RETENTION_DAYS = 7
VERDICT_OUTER_BOUND_DAYS = 90
MAX_VERDICT_BYTES = 64 * 1024
MAX_SCAN_FILES = 5000
OWNED_PREFIXES = (
    "turn_counter_",
    "session_plan_",
    "session_binding_",
    "session_verdict_",
    "session_verdict_lock_",
)


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
    if verdict is None:
        return modified < outer_cutoff
    created = modified
    raw_created = verdict.get("created_at")
    if isinstance(raw_created, str):
        try:
            created = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
        except ValueError:
            pass
    if created < outer_cutoff:
        return True
    return bool(verdict.get("consumed_at")) and modified < retention_cutoff


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
    """Delete only old owned state, respecting liveness and verdict delivery."""

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
        entries = []
        with os.scandir(state_dir) as iterator:
            for entry in iterator:
                if time.perf_counter() >= deadline:
                    summary["time_budget_hit"] = True
                    break
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    continue
                if not entry.name.startswith(OWNED_PREFIXES):
                    continue
                try:
                    entries.append((entry.stat(follow_symlinks=False).st_mtime, Path(entry.path)))
                except FileNotFoundError:
                    continue
                if len(entries) >= MAX_SCAN_FILES:
                    summary["file_limit_hit"] = True
                    break
        entries.sort(key=lambda item: item[0])
    except FileNotFoundError:
        return summary
    except OSError as exc:
        append_hook_error("REAPER_SCAN_FAILED", type(exc).__name__, state_dir=state_dir)
        summary["errors"] = 1
        return summary

    # A fresh transcript is the observable lease for a session that may still
    # be alive in another process. Build the protection set before deleting
    # any member of that session's state family.
    for _, path in entries:
        if time.perf_counter() >= deadline:
            summary["time_budget_hit"] = True
            break
        if not path.name.startswith("session_binding_"):
            continue
        session_id = _session_id(path.name)
        if session_id is None:
            continue
        binding = read_session_binding(session_id, state_dir=state_dir)
        if binding is None:
            continue
        try:
            transcript_modified = datetime.fromtimestamp(
                Path(binding["transcript_path"]).stat().st_mtime,
                tz=UTC,
            )
        except (KeyError, OSError, TypeError, ValueError):
            continue
        if transcript_modified >= retention_cutoff:
            live.add(session_id)

    for modified_timestamp, path in entries:
        if time.perf_counter() >= deadline:
            summary["time_budget_hit"] = True
            break
        if int(summary["deleted"]) >= max(0, max_files):
            summary["file_limit_hit"] = True
            break
        summary["scanned"] = int(summary["scanned"]) + 1
        session_id = _session_id(path.name)
        if session_id is None:
            continue
        if session_id in live:
            summary["skipped_live"] = int(summary["skipped_live"]) + 1
            continue
        modified = datetime.fromtimestamp(modified_timestamp, tz=UTC)
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
        if path.name.startswith("session_verdict_") and path.name.endswith(".json"):
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
    return summary
