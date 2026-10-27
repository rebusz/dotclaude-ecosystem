#!/usr/bin/env python3
"""Edit/Write guard: the supervisor cannot write source, and a Tier-2 task may change at most 20 source lines.

PreToolUse measures the tool input against the real file and reserves lines atomically.
PostToolUse (``--post``) measures the real ``git diff --numstat`` delta versus HEAD.
When the tier registry is corrupt or unreadable, source edits and writes are
denied for both tiers with an operator guidance message.
Importing this module creates no files.
"""

from __future__ import annotations

import difflib
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
    protected_path,
    read_payload,
    reserve_bytes,
    run_guarded,
    set_flag,
    state_dir,
    tier_state_corrupt,
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
_CORRUPT_DENY = (
    "tier registry corrupt: repair or delete state_dir()/tier2_sessions.json (operator)"
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
    value = tool_input.get("path")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _absolute_path(payload: dict, raw: str) -> Path:
    cleaned = raw.strip().strip("'\"")
    expanded = Path(os.path.expandvars(cleaned)).expanduser()
    if not expanded.is_absolute():
        cwd = payload.get("cwd")
        base = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()
        expanded = base / expanded
    try:
        return expanded.resolve()
    except Exception:
        return expanded


def _pair_lines(edit: Mapping[str, object]) -> int:
    return max(count_lines(edit.get("old_string")), count_lines(edit.get("new_string")))


def _diff_lines(old_text: str, new_text: str) -> int:
    """Added + deleted lines between old_text and new_text."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added = 0
    deleted = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            deleted += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added + deleted


def _declared_lines(tool_name: object, tool_input: dict) -> int:
    """Declared lines from tool_input alone for early rejection."""
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


def _measure_real_lines(
    tool_name: object,
    tool_input: dict,
    raw: str,
    current_content: str,
) -> tuple[int, dict | None]:
    """Measure changed lines against the real file content."""
    if tool_name == "Write":
        content = tool_input.get("content")
        if not isinstance(content, str):
            return 0, deny(f"measurement error on {raw}: content must be a string")
        return _diff_lines(current_content, content), None

    if tool_name == "MultiEdit":
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return 0, deny(f"measurement error on {raw}: edits must be a list")
        temp_content = current_content
        total = 0
        for edit in edits:
            if not isinstance(edit, dict):
                return 0, deny(f"measurement error on {raw}: edit item must be an object")
            old_str = edit.get("old_string")
            new_str = edit.get("new_string")
            if not isinstance(old_str, str) or not isinstance(new_str, str):
                return 0, deny(f"measurement error on {raw}: old_string and new_string must be strings")
            replace_all = bool(edit.get("replace_all") in (True, "true", "True", 1))
            if replace_all:
                occurrences = temp_content.count(old_str)
                if occurrences == 0:
                    return 0, deny(f"measurement error on {raw}: old_string not found in file")
                temp_content = temp_content.replace(old_str, new_str)
            else:
                if old_str not in temp_content:
                    return 0, deny(f"measurement error on {raw}: old_string not found in file")
                occurrences = 1
                temp_content = temp_content.replace(old_str, new_str, 1)
            pair = max(count_lines(old_str), count_lines(new_str))
            total += occurrences * pair
        return total, None

    if tool_name == "NotebookEdit":
        source = tool_input.get("new_source")
        if not isinstance(source, str):
            return 0, deny(f"measurement error on {raw}: new_source must be a string")
        return count_lines(source), None

    # Default / Edit tool
    old_str = tool_input.get("old_string")
    new_str = tool_input.get("new_string")
    if not isinstance(old_str, str) or not isinstance(new_str, str):
        return 0, deny(f"measurement error on {raw}: old_string and new_string must be strings")
    replace_all = bool(tool_input.get("replace_all") in (True, "true", "True", 1))
    if replace_all:
        occurrences = current_content.count(old_str)
        if occurrences == 0:
            return 0, deny(f"measurement error on {raw}: old_string not found in file")
    else:
        if old_str not in current_content:
            return 0, deny(f"measurement error on {raw}: old_string not found in file")
        occurrences = 1
    pair = max(count_lines(old_str), count_lines(new_str))
    lines = occurrences * pair
    return lines, None


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


def _is_git_tracked(path: Path) -> bool:
    try:
        directory = str(path.parent) if path.parent.parts else "."
        target = path.name
    except (OSError, ValueError):
        return False
    listed = _run_git(directory, ["ls-files", "--", target])
    if listed is None or listed.returncode != 0 or not listed.stdout.strip():
        return False
    return True


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
    if not _is_git_tracked(path):
        return 0
    try:
        directory = str(path.parent) if path.parent.parts else "."
        target = path.name
    except (OSError, ValueError):
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


def decide(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """PreToolUse for Edit, Write, MultiEdit, and NotebookEdit."""
    if override_active("hooks_off", env):
        return None

    tool_input = _tool_input(payload)
    raw = _raw_path(tool_input)

    # Protected paths cannot be edited by anyone (supervisor or Tier-2),
    # checked BEFORE any source exemption or line cap.
    if raw is not None:
        cwd = payload.get("cwd")
        cwd_str = cwd if isinstance(cwd, str) and cwd.strip() else None
        if protected_path(raw, cwd=cwd_str, env=env):
            return deny(f"cannot edit protected path: {raw}")

    # Non-source files (e.g. documentation, logs) are permitted.
    if raw is None or not is_source_path(raw):
        return None

    if tier_state_corrupt(env):
        return deny(_CORRUPT_DENY)

    # Supervisor cannot edit source files.
    if not is_tier2(payload, env):
        return deny(_SUPERVISOR_DENY)

    # Tier-2 with 'workers' override has edit cap lifted.
    if override_active("workers", env):
        return None

    key = agent_key(payload)
    if has_flag("edit_cap_exceeded", key, env):
        return deny(_CAP_DENY)

    # Fast pre-check: if declared lines alone exceed cap, deny immediately.
    tool_name = payload.get("tool_name")
    declared = _declared_lines(tool_name, tool_input)
    if declared > TIER2_EDIT_LINE_CAP:
        return deny(_CAP_DENY)

    # Tier-2 line accounting must use the real file.
    target_path = _absolute_path(payload, raw)
    if not _is_git_tracked(target_path):
        return deny(
            f"cannot edit untracked source file: {raw}. Dispatch changes to `lane impl`"
        )
    if not target_path.is_file():
        return deny(
            f"source file not found: {raw}. Dispatch changes to `lane impl`"
        )

    try:
        current_content = target_path.read_text(encoding="utf-8")
    except Exception as exc:
        return deny(
            f"cannot read source file {raw}: {exc}. Dispatch changes to `lane impl`"
        )

    lines, error = _measure_real_lines(tool_name, tool_input, raw, current_content)
    if error is not None:
        return error

    if not reserve_bytes("edit_lines", key, lines, TIER2_EDIT_LINE_CAP, env):
        return deny(_CAP_DENY)

    _write_presnap(payload, target_path, env)
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
    if tier_state_corrupt(env):
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
