#!/usr/bin/env python3
"""Read budget and supervisor source-read deny (rule R4, read side).

PreToolUse covers Read, Grep, and Glob. The supervisor may not read or grep
source files outside the allow-list, and a single Read over 40 KB without a
limit is denied unless that path is allow-listed. Bytes are estimated on Read
and charged against 150 KB (supervisor) or 400 KB (Tier-2).

PostToolUse (``--post``) covers Read, Grep, Glob, Bash, and PowerShell. Real
output size is added for every tool except Read (Read was estimated in Pre).
A response over 30 KB, or a counter that passes the cap, adds context and
does not block.

decide() and decide_post() return the JSON object to print, or None. They do
not print. main() reads one UTF-8 JSON payload from stdin. Importing this
module creates no files.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from dispatch_guard_common import (
    BIG_OUTPUT_WARN,
    SINGLE_READ_CAP,
    SOURCE_EXTS,
    SUPERVISOR_READ_CAP,
    TIER2_READ_CAP,
    agent_key,
    bump_counter,
    context,
    deny,
    get_counter,
    is_allowlisted_read,
    is_source_path,
    is_tier2,
    override_active,
    read_payload,
    run_guarded,
)

_HOOK_FILE = "scripts/dispatch_read_guard.py"
_COUNTER = "read_bytes"
_SOURCE_DENY = "source reads go to `lane diagnose`"
_BUDGET_DENY = "read budget exhausted"
_SINGLE_DENY = "a single Read over 40 KB is denied unless allow-listed"
_LARGE_OUTPUT = (
    "Large output: redirect output to a file and read only the tail; "
    "send heavy reading to `lane diagnose`"
)
_STOP_READING = "STOP reading: send this to `lane diagnose`"
_GREP_SOURCE_TYPES = frozenset({"py", "js", "ts", "tsx"})
_ACCOUNT_TOOLS = frozenset({"Grep", "Glob", "Bash", "PowerShell"})
_POST_TOOLS = _ACCOUNT_TOOLS | {"Read"}
_BYTES_PER_LINE = 120


def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input")
    return raw if isinstance(raw, dict) else {}


def _text(tool_input: dict, key: str) -> str:
    value = tool_input.get(key)
    return value if isinstance(value, str) else ""


def _cap(payload: dict, env: Mapping[str, str] | None) -> int:
    if is_tier2(payload, env):
        return TIER2_READ_CAP
    return SUPERVISOR_READ_CAP


def _limit(tool_input: dict) -> int | None:
    """Read limit when it is a non-negative int. Absent or invalid means none."""
    raw = tool_input.get("limit")
    if type(raw) is int and raw >= 0:
        return raw
    return None


def _file_size(payload: dict, path: str) -> int:
    """Byte size of path. Missing, unreadable, or empty paths count as zero."""
    if not path:
        return 0
    try:
        candidate = Path(os.path.expandvars(path)).expanduser()
        if not candidate.is_absolute():
            cwd = payload.get("cwd")
            base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
            candidate = base / candidate
        return candidate.stat().st_size
    except OSError:
        return 0


def _allowlisted(path: str) -> bool:
    return bool(path) and is_allowlisted_read(path)


def _glob_targets_source(pattern: str) -> bool:
    lower = pattern.lower()
    return any(lower.endswith(ext) for ext in SOURCE_EXTS)


def _grep_targets_source(tool_input: dict) -> bool:
    """True when type, glob, or path selects source files."""
    kind = _text(tool_input, "type").strip().lower()
    if kind in _GREP_SOURCE_TYPES:
        return True
    if _glob_targets_source(_text(tool_input, "glob")):
        return True
    path = _text(tool_input, "path")
    return bool(path) and is_source_path(path)


def _charge(
    key: str,
    estimate: int,
    cap: int,
    env: Mapping[str, str] | None,
) -> dict | None:
    """Deny when estimate would pass the cap. Otherwise record the estimate."""
    if get_counter(_COUNTER, key, env) + estimate > cap:
        return deny(_BUDGET_DENY)
    if estimate:
        bump_counter(_COUNTER, key, estimate, env)
    return None


def _decide_read(
    payload: dict,
    tool_input: dict,
    key: str,
    cap: int,
    env: Mapping[str, str] | None,
) -> dict | None:
    path = _text(tool_input, "file_path")
    allow = _allowlisted(path)
    if not is_tier2(payload, env) and path and is_source_path(path) and not allow:
        return deny(_SOURCE_DENY)
    size = _file_size(payload, path)
    limit = _limit(tool_input)
    if limit is None and size > SINGLE_READ_CAP and not allow:
        return deny(_SINGLE_DENY)
    if limit is None:
        estimate = size
    else:
        estimate = min(size, limit * _BYTES_PER_LINE)
    return _charge(key, estimate, cap, env)


def _decide_grep(
    payload: dict,
    tool_input: dict,
    key: str,
    cap: int,
    env: Mapping[str, str] | None,
) -> dict | None:
    path = _text(tool_input, "path")
    supervisor = not is_tier2(payload, env)
    if supervisor and _grep_targets_source(tool_input) and not _allowlisted(path):
        return deny(_SOURCE_DENY)
    return _charge(key, 0, cap, env)


def decide(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """PreToolUse for Read, Grep, and Glob. None allows the call."""
    if override_active("hooks_off", env):
        return None
    tool_input = _tool_input(payload)
    key = agent_key(payload)
    cap = _cap(payload, env)
    tool = payload.get("tool_name")
    if tool == "Read":
        return _decide_read(payload, tool_input, key, cap, env)
    if tool == "Grep":
        return _decide_grep(payload, tool_input, key, cap, env)
    if tool == "Glob":
        return _charge(key, 0, cap, env)
    return None


def _response_len(payload: dict) -> int:
    """len(json.dumps(tool_response)). A missing response counts as zero."""
    if "tool_response" not in payload:
        return 0
    response = payload.get("tool_response")
    try:
        return len(json.dumps(response))
    except (TypeError, ValueError):
        return len(json.dumps(str(response)))


def decide_post(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """PostToolUse accounting. Context only; this path never denies."""
    if override_active("hooks_off", env):
        return None
    tool = payload.get("tool_name")
    if tool not in _POST_TOOLS:
        return None
    size = _response_len(payload)
    key = agent_key(payload)
    if tool in _ACCOUNT_TOOLS:
        total = bump_counter(_COUNTER, key, size, env)
    else:
        total = get_counter(_COUNTER, key, env)
    messages: list[str] = []
    if size > BIG_OUTPUT_WARN:
        messages.append(_LARGE_OUTPUT)
    if total > _cap(payload, env):
        messages.append(_STOP_READING)
    if not messages:
        return None
    return context("\n".join(messages), "PostToolUse")


def main(argv: list[str] | None = None) -> int:
    """Read one JSON payload from stdin. ``--post`` selects output accounting."""
    args = list(sys.argv[1:] if argv is None else argv)
    post = "--post" in args
    event = "PostToolUse" if post else "PreToolUse"

    def invoke() -> dict | None:
        payload = read_payload()
        if post:
            return decide_post(payload)
        return decide(payload)

    return run_guarded(_HOOK_FILE, invoke, event)


if __name__ == "__main__":
    raise SystemExit(main())
