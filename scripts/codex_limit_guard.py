#!/usr/bin/env python3
"""Refuse `codex exec` once the Codex weekly limit is exhausted (paid credits would be spent).

Stdlib-only port of WatchF's ``watchf/ai/codex_limit_guard.py``.

Codex CLI records its rate limits in every session rollout
(``$CODEX_HOME/sessions/**/rollout-*.jsonl``, key ``rate_limits.primary.used_percent``
with the window's ``resets_at``). At 100% the CLI keeps working by drawing down paid
credits. This guard reads the newest recorded value and refuses with
``codex_weekly_limit_exhausted_credits_would_be_spent`` unless the operator opts in via
``DOTCLAUDE_ALLOW_CODEX_CREDITS=1`` (or ``WATCHF_ALLOW_CODEX_CREDITS=1``).

Unknown state (no rollout, unreadable file) allows the call.

CLI:
  codex_limit_guard.py --check           one JSON line {"allowed", "reason"}; exit 0 / 75
  codex_limit_guard.py -- <command...>   check, then run the command (exit 75 if refused)
Silent: no audio, no prompts.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

REFUSAL = "codex_weekly_limit_exhausted_credits_would_be_spent"
ALLOW_ENV = "DOTCLAUDE_ALLOW_CODEX_CREDITS"
ALLOW_ENVS = ("DOTCLAUDE_ALLOW_CODEX_CREDITS", "WATCHF_ALLOW_CODEX_CREDITS")
EXIT_REFUSED = 75
_TAIL_BYTES = 1_500_000
_CACHE_TTL_S = 30.0
_cache: dict[str, Any] = {"at": 0.0, "value": None, "dir": None}
_cache_lock = threading.Lock()


def _sessions_dir() -> Path:
    override = os.environ.get("CODEX_HOME")
    base = Path(override) if override else Path.home() / ".codex"
    return base / "sessions"


def _newest_rollouts(sessions: Path, limit: int = 4) -> list[Path]:
    """Newest rollout files by walking YYYY/MM/DD directories newest-first."""
    found: list[Path] = []
    try:
        for year in sorted((d for d in sessions.iterdir() if d.is_dir()), reverse=True):
            for month in sorted((d for d in year.iterdir() if d.is_dir()), reverse=True):
                for day in sorted((d for d in month.iterdir() if d.is_dir()), reverse=True):
                    files = [p for p in day.glob("rollout-*.jsonl") if p.is_file()]
                    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                    found.extend(files)
                    if len(found) >= limit:
                        return found[:limit]
    except OSError:
        return found[:limit]
    return found[:limit]


def _find_rate_limits(node: Any) -> dict[str, Any] | None:
    if isinstance(node, dict):
        value = node.get("rate_limits")
        if isinstance(value, dict) and isinstance(value.get("primary"), dict):
            return value
        for child in node.values():
            found = _find_rate_limits(child)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _find_rate_limits(child)
            if found is not None:
                return found
    return None


def latest_rate_limits(sessions: Path | None = None) -> dict[str, Any] | None:
    """The most recent ``rate_limits`` object any recent rollout recorded, or None."""
    sessions = sessions or _sessions_dir()
    for path in _newest_rollouts(sessions):
        try:
            with path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - _TAIL_BYTES))
                tail = stream.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        for line in reversed(tail.splitlines()):
            if '"rate_limits"' not in line:
                continue
            try:
                found = _find_rate_limits(json.loads(line))
            except ValueError:
                continue  # the first tail line may be cut mid-record
            if found is not None:
                return found
    return None


def _opted_in() -> bool:
    return any(os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"} for name in ALLOW_ENVS)


def codex_limit_refusal(*, now: float | None = None, sessions: Path | None = None) -> str | None:
    """Refusal text when Codex is at its weekly limit and credits would be spent, else None."""
    if _opted_in():
        return None
    now = time.time() if now is None else now
    with _cache_lock:
        if sessions is None and now - _cache["at"] < _CACHE_TTL_S and _cache["dir"] == str(_sessions_dir()):
            limits = _cache["value"]
        else:
            limits = latest_rate_limits(sessions)
            if sessions is None:
                _cache.update(at=now, value=limits, dir=str(_sessions_dir()))
    if not limits:
        return None
    exhausted: dict[str, Any] | None = None
    used = 0.0
    for window_name in ("primary", "secondary"):
        window = limits.get(window_name)
        if not isinstance(window, dict):
            continue
        try:
            window_used = float(window.get("used_percent"))
        except (TypeError, ValueError):
            continue
        window_resets = window.get("resets_at")
        if isinstance(window_resets, (int, float)) and window_resets <= now:
            continue  # that recorded window has already rolled over
        if window_used >= 100.0:
            exhausted, used = window, window_used
            break
    reached = limits.get("rate_limit_reached_type")
    if exhausted is None and reached:
        exhausted, used = limits.get("primary") or {}, 100.0
    if exhausted is None:
        return None
    resets_at = exhausted.get("resets_at")
    credits = limits.get("credits") or {}
    balance = credits.get("balance") if isinstance(credits, dict) else None
    reset_note = ""
    if isinstance(resets_at, (int, float)):
        reset_note = " resets_at=" + time.strftime("%Y-%m-%d %H:%M", time.localtime(resets_at))
    return (
        f"{REFUSAL}: weekly used_percent={used:g}{reset_note}"
        f"{' credit_balance=' + str(balance) if balance is not None else ''}; "
        f"set {ALLOW_ENV}=1 to spend credits deliberately"
    )


def reset_cache_for_tests() -> None:
    with _cache_lock:
        _cache.update(at=0.0, value=None, dir=None)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command: list[str] = []
    if "--" in args:
        idx = args.index("--")
        command = args[idx + 1:]
        args = args[:idx]
    parser = argparse.ArgumentParser(description="Codex weekly-limit credit guard")
    parser.add_argument("--check", action="store_true", help="print one JSON line; exit 0 allowed / 75 refused")
    opts = parser.parse_args(args)
    if not opts.check and not command:
        parser.error("use --check or -- <command...>")
    refusal = codex_limit_refusal()
    if opts.check:
        print(json.dumps({"allowed": refusal is None, "reason": refusal}))
        return 0 if refusal is None else EXIT_REFUSED
    if refusal is not None:
        print(refusal, file=sys.stderr)
        return EXIT_REFUSED
    try:
        return subprocess.run(command, shell=False).returncode
    except OSError as exc:
        print(f"codex_limit_guard: cannot run {command[0]!r}: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main())
