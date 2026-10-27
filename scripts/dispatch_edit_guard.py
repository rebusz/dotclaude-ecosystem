#!/usr/bin/env python3
"""Edit/Write guard: the supervisor cannot write source, and a Tier-2 task may change at most 20 source lines.

PreToolUse measures the tool input. PostToolUse (``--post``) measures the real
``git diff --numstat`` delta versus HEAD. Importing this module creates no files.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from dispatch_guard_common import (
    TIER2_EDIT_LINE_CAP,
    agent_key,
    block,
    bump_counter,
    deny,
    get_counter,
    has_flag,
    is_source_path,
    is_tier2,
    override_active,
    read_payload,
    run_guarded,
    set_flag,
    state_dir,
)

_HOOK_FILE = "scripts/dispatch_edit_guard.py"
_GIT_TIMEOUT_S = 5
_PRESNAP_DIR = "dispatch_flags"
_SUPERVISOR_DENY = "the supervisor does not write source: use `lane impl`"
_CAP_DENY = (
    "Tier-2 edit cap (20 changed source lines per task) reached: "
    "dispatch it to `lane impl`"
)
_POST_BLOCK = (
    "net source diff over 20 lines: stop editing, dispatch the rest to `lane impl`"
)
_PATH_KEYS = ("file_path", "notebook_path")

def count_lines(text: object) -> int:
    """Line count of a tool-input string. Empty and non-strings are zero."""
    if not isinstance(text, str) or text == "":
        return 0
    return len(text.splitlines())

def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input")
    return raw if isinstance(raw, dict) else {}

def _raw_path(tool_input: dict) -> str | None:
    for key in _PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None

def _absolute_path(payload: dict, raw: str) -> Path:
    expanded = Path(os.path.expandvars(raw)).expanduser()
    if not expanded.is_absolute():
        cwd = payload.get("cwd")
        base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
        expanded = base / expanded
    return expanded

def _pair_lines(edit: Mapping[str, object]) -> int:
    return max(count_lines(edit.get("old_string")), count_lines(edit.get("new_string")))

def _changed_lines(tool_name: object, tool_input: dict) -> int:
    """Declared lines for Edit, Write, MultiEdit, or NotebookEdit."""
    if tool_name == "Write":
        return count_lines(tool_input.get("content"))
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return 0
        total = 0
        for edit in edits:
            if isinstance(edit, dict):
                total += _pair_lines(edit)
        return total
    if tool_name == "NotebookEdit":
        source = tool_input.get("new_source")
        if isinstance(source, str):
            return count_lines(source)
    return _pair_lines(tool_input)

def _run_git(directory: str, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """git with shell=False and a 5s timeout. None means the call failed."""
    try:
        git_env = os.environ.copy()
        git_env["GIT_TERMINAL_PROMPT"] = "0"
        kwargs: dict[str, object] = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "timeout": _GIT_TIMEOUT_S,
            "shell": False,
            "check": False,
            "env": git_env,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.run(["git", "-C", directory, *args], **kwargs)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None

def _parse_numstat(output: str) -> int:
    total = 0
    for line in output.splitlines():
        added, separator, rest = line.partition("\t")
        deleted, separator2, _path = rest.partition("\t")
        if not separator or not separator2:
            continue
        if not added.isdigit() or not deleted.isdigit():
            continue
        total += int(added) + int(deleted)
    return total

def _git_numstat(path: Path) -> int:
    """Added+deleted versus HEAD via ``git -C <dir> diff --numstat HEAD -- <file>``.

    Untracked paths and any git failure are zero.
    """
    try:
        directory = str(path.parent) if path.parent.parts else "."
        target = path.name
    except (OSError, ValueError):
        return 0
    listed = _run_git(directory, ["ls-files", "--", target])
    if listed is None or listed.returncode != 0 or listed.stdout.strip() == "":
        return 0
    diff = _run_git(directory, ["diff", "--numstat", "HEAD", "--", target])
    if diff is None or diff.returncode != 0:
        return 0
    return _parse_numstat(diff.stdout)

def _presnap_path(payload: dict, env: Mapping[str, str] | None) -> Path:
    tool_use_id = payload.get("tool_use_id")
    token = tool_use_id if isinstance(tool_use_id, str) and tool_use_id else "missing"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", token)[:80] or "missing"
    return state_dir(env) / _PRESNAP_DIR / f"presnap-{safe}.json"

def _write_presnap(payload: dict, path: Path, env: Mapping[str, str] | None) -> None:
    dest = _presnap_path(payload, env)
    body = {"numstat": _git_numstat(path), "path": str(path).replace("\\", "/")}
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8") + b"\n"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)

def _read_presnap(path: Path) -> int:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return 0
    value = raw.get("numstat", 0) if isinstance(raw, dict) else raw
    if type(value) is not int or value < 0:
        return 0
    return value

def _remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        return

def _over_declared_cap(key: str, lines: int, env: Mapping[str, str] | None) -> bool:
    if has_flag("edit_cap_exceeded", key, env):
        return True
    return get_counter("edit_lines", key, env) + lines > TIER2_EDIT_LINE_CAP

def decide(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """PreToolUse for Edit, Write, MultiEdit, and NotebookEdit."""
    if override_active("hooks_off", env):
        return None
    tool_input = _tool_input(payload)
    raw = _raw_path(tool_input)
    if raw is None or not is_source_path(raw):
        return None
    if not is_tier2(payload, env):
        return deny(_SUPERVISOR_DENY)
    if override_active("workers", env):
        return None
    lines = _changed_lines(payload.get("tool_name"), tool_input)
    key = agent_key(payload)
    if _over_declared_cap(key, lines, env):
        return deny(_CAP_DENY)
    bump_counter("edit_lines", key, lines, env)
    _write_presnap(payload, _absolute_path(payload, raw), env)
    return None

def decide_post(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """PostToolUse net-diff check. Tier-2 source only; git errors count as zero."""
    if override_active("hooks_off", env):
        _remove(_presnap_path(payload, env))
        return None
    if not is_tier2(payload, env):
        return None
    if override_active("workers", env):
        _remove(_presnap_path(payload, env))
        return None
    tool_input = _tool_input(payload)
    raw = _raw_path(tool_input)
    presnap = _presnap_path(payload, env)
    if raw is None or not is_source_path(raw):
        _remove(presnap)
        return None
    before = _read_presnap(presnap)
    after = _git_numstat(_absolute_path(payload, raw))
    delta = max(0, after - before)
    total = bump_counter("net_diff_lines", agent_key(payload), delta, env)
    _remove(presnap)
    if total > TIER2_EDIT_LINE_CAP:
        set_flag("edit_cap_exceeded", agent_key(payload), env)
        return block(_POST_BLOCK)
    return None

def main(argv: list[str] | None = None) -> int:
    """Read one JSON payload from stdin. ``--post`` selects the net-diff check."""
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
