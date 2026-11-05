#!/usr/bin/env python3
"""Read budget and supervisor source-read deny (rule R4, read side).

PreToolUse covers Read, Grep, and Glob. The supervisor may not read or grep
source files outside the allow-list, and a single Read over 40 KB without a
limit is denied unless that path is allow-listed. Bytes are measured for
the selected slice (cap 2 MB, binary-safe) and charged against 150 KB
(supervisor) or 400 KB (Tier-2) atomically.

Supervisor Grep denies directory paths and path-less Grep (cwd search) unless
allowlisted or restricted to non-source extensions.

When the tier registry is corrupt or unreadable, source reads and counted
actions are denied with an operator guidance message for both tiers.

PostToolUse (``--post``) covers Read, Grep, Glob, Bash, and PowerShell. Real
output size is added for Grep and Glob (Read was charged in Pre; Bash and
PowerShell do not count toward the read budget). A response over 30 KB, or
a counter that passes the cap (for Read, Grep, and Glob), adds context and
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
    reserve_bytes,
    run_guarded,
    tier_state_corrupt,
)

_HOOK_FILE = "scripts/dispatch_read_guard.py"
_COUNTER = "read_bytes"
_SOURCE_DENY = "source reads go to `lane diagnose`"
_BUDGET_DENY = "read budget exhausted"
_SINGLE_DENY = "a single Read over 40 KB is denied unless allow-listed"
_CORRUPT_DENY = (
    "tier registry corrupt: repair or delete state_dir()/tier2_sessions.json (operator)"
)
_LARGE_OUTPUT = (
    "Large output: redirect output to a file and read only the tail; "
    "send heavy reading to `lane diagnose`"
)
_STOP_READING = "STOP reading: send this to `lane diagnose`"
_GREP_SOURCE_TYPES = frozenset({
    "py",
    "python",
    "js",
    "javascript",
    "ts",
    "typescript",
    "tsx",
    "jsx",
    "mjs",
    "cjs",
})
_ACCOUNT_TOOLS = frozenset({"Grep", "Glob"})
_READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
_POST_TOOLS = _READ_TOOLS | {"Bash", "PowerShell"}
_SLICE_CAP = 2 * 1024 * 1024


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


def _offset(tool_input: dict) -> int | None:
    """Read offset when it is a non-negative int. Absent or invalid means none."""
    raw = tool_input.get("offset")
    if type(raw) is int and raw >= 0:
        return raw
    return None


def _resolve_path(payload: dict, path: str) -> Path | None:
    if not path:
        return None
    try:
        candidate = Path(os.path.expandvars(path)).expanduser()
        if not candidate.is_absolute():
            cwd = payload.get("cwd")
            base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
            candidate = base / candidate
        return candidate
    except Exception:
        return None


def _file_size(payload: dict, path: str) -> int:
    """Byte size of path. Missing, unreadable, or empty paths count as zero."""
    candidate = _resolve_path(payload, path)
    if candidate is None:
        return 0
    try:
        return candidate.stat().st_size
    except OSError:
        return 0


def _is_allowlisted_path_or_dir(payload: dict, path: str) -> bool:
    if not path or not path.strip():
        return False
    cwd = payload.get("cwd")
    cwd_str = cwd if isinstance(cwd, str) and cwd.strip() else None
    if is_allowlisted_read(path, cwd=cwd_str):
        return True
    candidate = _resolve_path(payload, path)
    if candidate is not None:
        cand_str = str(candidate).replace("\\", "/")
        if is_allowlisted_read(cand_str, cwd=cwd_str) or is_allowlisted_read(
            cand_str + "/", cwd=cwd_str
        ):
            return True
    return False


def _is_directory(payload: dict, path: str) -> bool:
    if not path:
        return False
    clean = path.strip()
    if clean in (".", "..") or clean.endswith(("/", "\\")):
        return True
    candidate = _resolve_path(payload, clean)
    if candidate is not None:
        try:
            if candidate.is_dir():
                return True
            if candidate.is_file():
                return False
        except OSError:
            pass
    suffix = Path(clean).suffix
    return not suffix


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


def _type_restricts_to_non_source(type_val: str) -> bool:
    if not type_val:
        return False
    clean = type_val.strip().lower().lstrip(".")
    if not clean or clean in ("all", "default"):
        return False
    if clean in _GREP_SOURCE_TYPES:
        return False
    if ("." + clean) in SOURCE_EXTS:
        return False
    return True


def _glob_restricts_to_non_source(glob_val: str) -> bool:
    if not glob_val:
        return False
    cleaned = glob_val.strip().lower()
    if not cleaned:
        return False
    if any(cleaned.endswith(ext) for ext in SOURCE_EXTS):
        return False
    if "{" in cleaned and "}" in cleaned:
        inside = cleaned[cleaned.find("{") + 1 : cleaned.find("}")]
        pieces = [p.strip().lstrip(".") for p in inside.split(",") if p.strip()]
        if pieces and all(
            ("." + p) not in SOURCE_EXTS and p not in _GREP_SOURCE_TYPES
            for p in pieces
        ):
            return True
        return False
    suffix = Path(cleaned).suffix
    if suffix and not any(c in suffix for c in ("*", "?", "[", "]")):
        if suffix not in SOURCE_EXTS:
            return True
    return False


def _restricts_to_non_source(tool_input: dict) -> bool:
    if _grep_targets_source(tool_input):
        return False
    type_val = _text(tool_input, "type")
    if _type_restricts_to_non_source(type_val):
        return True
    glob_val = _text(tool_input, "glob")
    if _glob_restricts_to_non_source(glob_val):
        return True
    return False


def _charge(
    key: str,
    delta: int,
    cap: int,
    env: Mapping[str, str] | None,
) -> dict | None:
    """Reserve delta bytes atomically. Deny when budget would be exceeded."""
    if tier_state_corrupt(env):
        return deny(_CORRUPT_DENY)
    if not reserve_bytes(_COUNTER, key, delta, cap, env):
        return deny(_BUDGET_DENY)
    return None


def _read_slice_size(
    payload: dict,
    path: str,
    offset: int | None,
    limit: int | None,
    size: int,
) -> int:
    """Read the requested slice in binary mode, capped at 2 MB."""
    if not path or size <= 0:
        return 0
    candidate = _resolve_path(payload, path)
    if candidate is None:
        return 0
    lines_to_skip = max(0, offset - 1) if offset is not None else 0
    if lines_to_skip == 0 and limit is None:
        return min(size, _SLICE_CAP)
    if limit == 0:
        return 0
    try:
        with open(candidate, "rb") as f:
            while lines_to_skip > 0:
                line = f.readline()
                if not line:
                    return 0
                if line.endswith(b"\n"):
                    lines_to_skip -= 1
            if limit is None:
                content = f.read(_SLICE_CAP)
                return min(len(content), _SLICE_CAP)
            accumulated = 0
            lines_read = 0
            while lines_read < limit and accumulated < _SLICE_CAP:
                chunk = f.readline(_SLICE_CAP - accumulated)
                if not chunk:
                    break
                accumulated += len(chunk)
                if chunk.endswith(b"\n"):
                    lines_read += 1
            return min(accumulated, _SLICE_CAP)
    except OSError:
        return 0


def _decide_read(
    payload: dict,
    tool_input: dict,
    key: str,
    cap: int,
    env: Mapping[str, str] | None,
) -> dict | None:
    if tier_state_corrupt(env):
        return deny(_CORRUPT_DENY)
    path = _text(tool_input, "file_path")
    allow = _is_allowlisted_path_or_dir(payload, path)
    if not is_tier2(payload, env) and path and is_source_path(path) and not allow:
        return deny(_SOURCE_DENY)
    size = _file_size(payload, path)
    limit = _limit(tool_input)
    if limit is None and size > SINGLE_READ_CAP and not allow:
        return deny(_SINGLE_DENY)
    offset = _offset(tool_input)
    slice_size = _read_slice_size(payload, path, offset, limit, size)
    return _charge(key, slice_size, cap, env)


def _decide_grep(
    payload: dict,
    tool_input: dict,
    key: str,
    cap: int,
    env: Mapping[str, str] | None,
) -> dict | None:
    if tier_state_corrupt(env):
        return deny(_CORRUPT_DENY)
    supervisor = not is_tier2(payload, env)
    path = _text(tool_input, "path").strip()
    if supervisor:
        if not path:
            if not _restricts_to_non_source(tool_input):
                return deny(_SOURCE_DENY)
        else:
            allow = _is_allowlisted_path_or_dir(payload, path)
            if _grep_targets_source(tool_input) and not allow:
                return deny(_SOURCE_DENY)
            if _is_directory(payload, path) and not allow and not _restricts_to_non_source(tool_input):
                return deny(_SOURCE_DENY)
    return _charge(key, 0, cap, env)


def decide(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """PreToolUse for Read, Grep, and Glob. None allows the call."""
    if override_active("hooks_off", env):
        return None
    tool = payload.get("tool_name")
    if tool not in ("Read", "Grep", "Glob"):
        return None
    if tier_state_corrupt(env):
        return deny(_CORRUPT_DENY)
    tool_input = _tool_input(payload)
    key = agent_key(payload)
    cap = _cap(payload, env)
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
    elif tool in _READ_TOOLS:
        total = get_counter(_COUNTER, key, env)
    else:
        total = 0
    messages: list[str] = []
    if size > BIG_OUTPUT_WARN:
        messages.append(_LARGE_OUTPUT)
    if tool in _READ_TOOLS and total > _cap(payload, env):
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
