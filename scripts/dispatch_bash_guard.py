#!/usr/bin/env python3
"""PreToolUse guard for Bash and PowerShell (rules R2 and R3).

Models are reachable only through ``python D:/APPS/_shared/dispatch/dispatch.py``.
Direct launches of codex, glm, kimi, cursor-agent, agy, opencode, claude -p/--print,
and the CDP/audit scripts are denied. Bash and PowerShell may not write guarded
paths or source files. The supervisor may not read source files or non-allowlisted
source directories with shell utilities. Nested shells are unwrapped up to
recursion depth 4.

Honest boundary note: hooks stop accidental and rationalised bypass; they are
not a security boundary against an agent that deliberately uses the operator OS
credentials. Python inline/heredoc mutation checks provide a heuristic speed
bump, not an airtight sandbox.

decide() is pure. main() prints one JSON object or nothing.
Importing this module creates no files.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_guard_common import (  # noqa: E402 - sibling import, same pattern as other hooks
    GUARDED_PATH_PATTERNS,
    SOURCE_EXTS,
    deny,
    is_allowlisted_read,
    is_source_path,
    is_tier2,
    lane_repair_job_exists,
    norm_path,
    override_active,
    protected_path,
    read_payload,
    run_guarded,
)

_HOOK_FILE = "dispatch_bash_guard.py"
_ROUTER = (
    "python D:/APPS/_shared/dispatch/dispatch.py "
    "lane <impl|review|grill|plan|diagnose> --brief FILE"
)
_DIRECT = frozenset({"codex", "glm", "kimi", "cursor-agent", "agy", "opencode"})
_PYTHON = frozenset({"python", "python3", "py", "pythonw"})
_WRAPPERS = frozenset({"env", "time", "nohup", "call", "start"})
_ENV_VALUE_FLAGS = frozenset({"-u", "-C", "--unset", "--chdir"})
_ROUTER_CMDS = frozenset({"lane", "plan", "ledger", "status"})
_INTROSPECTION = frozenset({
    "--help", "-h", "--version", "--probe", "--probe-models",
    "--check-slots", "--check-args", "--list-models",
})
_DEST_CMDS = frozenset({
    "cp", "mv", "copy", "move", "copy-item", "move-item", "ren", "rename",
})
_WRITE_CMDS = frozenset({
    "tee", "rm", "del", "remove-item", "ni", "new-item",
    "set-content", "out-file", "add-content",
})
_DEST_OPTS = frozenset({
    "-destination", "-destinationpath", "-target-directory", "-t", "--target-directory",
})
_PATH_OPTS = frozenset({
    "-path", "-literalpath", "-filepath", "-outpath", "-name",
    "--path", "--literal-path", "--file-path",
})
_VALUE_OPTS = _PATH_OPTS | _DEST_OPTS | frozenset({
    "-value", "-encoding", "-itemtype", "-argumentlist", "-filter",
    "-include", "-exclude", "-inputobject",
})
_STRIP_EXT = (".exe", ".cmd", ".ps1", ".bat", ".js")
_SCRIPT_RE = re.compile(
    r"^(?:cdp_.*(?:\.py)?|auditgpt(?:\.py)?|coderpx(?:\.py)?|perplexity_audit(?:\.py)?)$",
    re.IGNORECASE,
)
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_REDIR_RE = re.compile(r"(\d*)(>>|>)")

_MAX_RECURSION_DEPTH = 4
_INTERPRETERS = frozenset({
    "python", "python3", "py", "pythonw",
    "bash", "sh", "zsh", "pwsh", "powershell",
    "node", "perl", "ruby",
})
_READ_CMDS = frozenset({
    "cat", "head", "tail", "type", "more", "less",
    "get-content", "gc", "awk", "rg", "grep",
    "select-string", "findstr",
})
_PYTHON_VALUE_OPTS = frozenset({"-w", "-x", "--check-hash-based-pycs"})
_PY_EXEC_RE = re.compile(r"\b(?:subprocess|os\.system|Popen|spawn)\b")
_PY_LAUNCHER_RE = re.compile(
    r"\b(?:codex|glm|kimi|cursor-agent|cursor_agent|agy|opencode|cdp_[A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
_PY_WRITE_RE = re.compile(
    r"\b(?:write_text|write_bytes|shutil\.copy\w*|shutil\.move|os\.replace|os\.rename)\b|"
    r"\bopen\s*\([^)]*['\"][wax\+]",
    re.IGNORECASE,
)
_PY_SPECIAL_STRINGS_RE = re.compile(
    r"\b(?:dispatch_guard_common|lane_authorize|write_override|load_or_create_key)\b"
)
_SOURCE_EXT_STR_RE = re.compile(
    r"['\"][^'\"]*?\.(?:py|ts|tsx|js|jsx|mjs|cjs)['\"]",
    re.IGNORECASE,
)


class _Cmd(NamedTuple):
    program: str
    args: list[str]
    words: list[str]
    redirs: list[str]
    input_redirs: list[str] = []


def split_statements(command: str) -> list[str]:
    """Split a Bash or PowerShell command into statements.

    Non-interpreter heredoc bodies and PowerShell here-string bodies are
    removed first. Interpreter heredoc bodies are preserved intact. Separators
    are newlines, ``;``, ``&&``, ``||``, ``|``, and a lone ``&``. A separator
    inside single or double quotes does not split. ``2>&1`` is not a separator.
    """
    text = _strip_bodies(command)
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(text)
    in_single = False
    in_double = False
    escaped = False

    def flush() -> None:
        piece = "".join(buf).replace("\x00", "\n").strip()
        buf.clear()
        if piece:
            parts.append(piece)

    while i < n:
        ch = text[i]
        if escaped:
            buf.append(ch)
            escaped = False
            i += 1
            continue
        if in_single:
            buf.append(ch)
            if ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            buf.append(ch)
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "\\":
            if i + 1 < n and text[i + 1] == "\n":
                i += 2
                continue
            escaped = True
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue
        if ch == "\r":
            i += 1
            continue
        two = text[i:i + 2]
        if two in {"&&", "||"}:
            flush()
            i += 2
            continue
        if ch in {";", "\n"}:
            flush()
            i += 1
            continue
        if ch == "|":
            flush()
            i += 1
            continue
        if ch == "&":
            prev = text[i - 1] if i else ""
            if prev in "<>" or two == "&>":
                buf.append(ch)
                i += 1
                continue
            # If buf is empty (or whitespace only), & is a leading operator (e.g. PowerShell call operator)
            if not "".join(buf).strip():
                buf.append(ch)
                i += 1
                continue
            flush()
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    return parts


def program_of(statement: str) -> str:
    """Return the lowercase program basename, or "" when the statement has none.

    Leading assignments and the wrappers env/time/nohup/call/start/& are
    skipped. cd and pushd have no program. Start-Process uses its executable.
    python/python3/py/pythonw yield the script basename instead of the launcher.
    Extensions .exe .cmd .ps1 .bat .js are removed. A name that only appears
    later in the statement is not the program.
    """
    return _parse(statement).program


def decide(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """Return a PreToolUse deny object, or None when the command may run."""
    if override_active("hooks_off", env):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None

    raw_cwd = payload.get("cwd")
    effective_cwd = str(raw_cwd) if raw_cwd else os.getcwd()
    tier2 = is_tier2(payload, env)

    for statement in split_statements(command):
        reason = _statement_reason(
            statement=statement,
            env=env,
            depth=0,
            effective_cwd=effective_cwd,
            is_tier2_caller=tier2,
        )
        if reason is not None:
            return deny(reason)
        effective_cwd = _update_cwd(effective_cwd, statement)
    return None


def main() -> int:
    """Read one hook payload from stdin and apply decide() under run_guarded."""

    def _from_stdin() -> dict | None:
        return decide(read_payload())

    return run_guarded(_HOOK_FILE, _from_stdin)


def _statement_reason(
    statement: str,
    env: Mapping[str, str] | None,
    depth: int = 0,
    effective_cwd: str = "",
    is_tier2_caller: bool = False,
) -> str | None:
    if depth >= _MAX_RECURSION_DEPTH:
        return _depth_exceeded_reason(statement)

    parsed = _parse(statement)

    # 1. Check outer statement redirections
    for path in parsed.redirs:
        kind = _write_kind(path, effective_cwd, env)
        if kind is not None:
            return _mutate_reason(statement, kind)

    # 2. Check wrapper unwrapping
    err_reason, inner_cmd = _unwrap_statement(statement, parsed)
    if err_reason is not None:
        return err_reason
    if inner_cmd is not None:
        inner_stmts = split_statements(inner_cmd)
        inner_cwd = effective_cwd
        for inner_stmt in inner_stmts:
            inner_reason = _statement_reason(
                statement=inner_stmt,
                env=env,
                depth=depth + 1,
                effective_cwd=inner_cwd,
                is_tier2_caller=is_tier2_caller,
            )
            if inner_reason is not None:
                return inner_reason
            inner_cwd = _update_cwd(inner_cwd, inner_stmt)
        return None

    # 3. Python inline code / script inspection
    if parsed.program in _PYTHON:
        py_reason = _python_check(statement, parsed, effective_cwd, env)
        if py_reason is not None:
            return py_reason

    # 4. Git execution-bearing config check
    if parsed.program == "git":
        git_reason = _git_check(statement, parsed)
        if git_reason is not None:
            return git_reason
        return None

    # 5. Direct launch check
    if not _is_router(parsed) and _is_direct(parsed) and not _introspects(parsed):
        job_id = _repair_job(parsed.args)
        if job_id is None:
            return _launch_reason(statement)
        if not lane_repair_job_exists(job_id, env):
            return _unknown_job_reason(statement, job_id)

    # 6. Supervisor read rule
    if not is_tier2_caller and _is_read_cmd(parsed):
        read_reason = _supervisor_read_check(statement, parsed, effective_cwd)
        if read_reason is not None:
            return read_reason

    # 7. Mutation checks for other commands (cp, mv, sed, tee, rm, set-content, etc.)
    for path in _write_paths(parsed, effective_cwd):
        kind = _write_kind(path, effective_cwd, env)
        if kind is not None:
            return _mutate_reason(statement, kind)

    return None


def _unwrap_statement(statement: str, parsed: _Cmd) -> tuple[str | None, str | None]:
    """Return (error_reason, inner_command_text) if statement is an unwrappable wrapper."""
    words = parsed.words
    if not words:
        return None, None

    first_non_assign = 0
    while first_non_assign < len(words) and _ASSIGN_RE.match(words[first_non_assign]):
        first_non_assign += 1
    if first_non_assign >= len(words):
        return None, None

    head_word = words[first_non_assign]
    if head_word == "&":
        if first_non_assign + 1 < len(words):
            inner = " ".join(words[first_non_assign + 1:])
            return None, inner
        return None, None

    head_low = _normalize_exe(head_word)

    # Start-Process
    if head_low == "start-process":
        exe, arg_list = _start_process_info(words, first_non_assign + 1)
        if exe:
            inner = f"{exe} {arg_list}".strip()
            return None, inner
        return None, None

    # cmd / cmd.exe
    if head_low == "cmd":
        idx = -1
        for i, w in enumerate(words[first_non_assign + 1:], start=first_non_assign + 1):
            if w.lower() in {"/c", "-c"}:
                idx = i
                break
        if idx >= 0 and idx + 1 < len(words):
            inner = " ".join(words[idx + 1:])
            if inner.strip():
                return None, inner
        return None, None

    # bash, sh, zsh
    if head_low in {"bash", "sh", "zsh"}:
        idx = -1
        for i, w in enumerate(words[first_non_assign + 1:], start=first_non_assign + 1):
            if w == "-c":
                idx = i
                break
            if w.startswith("-c") and len(w) > 2:
                return None, w[2:]
        if idx >= 0 and idx + 1 < len(words):
            return None, words[idx + 1]
        return None, None

    # powershell, pwsh
    if head_low in {"powershell", "pwsh"}:
        for w in words[first_non_assign + 1:]:
            w_low = w.lower()
            if w_low == "-encodedcommand" or w_low.startswith("-enc"):
                return _encoded_ps_reason(statement), None
        idx = -1
        for i, w in enumerate(words[first_non_assign + 1:], start=first_non_assign + 1):
            w_low = w.lower()
            if w_low in {"-c", "-command", "/c", "/command", "--command"}:
                idx = i
                break
            if w_low.startswith("-c:") or w_low.startswith("-command:"):
                return None, w.split(":", 1)[1]
        if idx >= 0 and idx + 1 < len(words):
            inner = " ".join(words[idx + 1:])
            return None, inner
        return None, None

    # Invoke-Expression / iex
    if head_low in {"invoke-expression", "iex"}:
        args = words[first_non_assign + 1:]
        if args:
            for i, a in enumerate(args):
                if a.lower() in {"-command", "-c"} and i + 1 < len(args):
                    return None, " ".join(args[i + 1:])
            return None, " ".join(args)
        return None, None

    # env
    if head_low == "env":
        args = words[first_non_assign + 1:]
        for i, a in enumerate(args):
            if a in {"-S", "--split-string"} and i + 1 < len(args):
                return None, " ".join(args[i + 1:])
        rem = _skip_wrapper(words, first_non_assign + 1, "env")
        if rem < len(words):
            return None, " ".join(words[rem:])
        return None, None

    # xargs
    if head_low == "xargs":
        args = words[first_non_assign + 1:]
        i = 0
        while i < len(args):
            a = args[i]
            if a in {"-n", "-L", "-I", "-s", "-E", "-d", "-P", "-a"} and i + 1 < len(args):
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            break
        if i < len(args):
            return None, " ".join(args[i:])
        return None, None

    # time, nohup
    if head_low in {"time", "nohup"}:
        rem = _skip_wrapper(words, first_non_assign + 1, head_low)
        if rem < len(words):
            return None, " ".join(words[rem:])
        return None, None

    # sudo
    if head_low == "sudo":
        args = words[first_non_assign + 1:]
        i = 0
        while i < len(args):
            a = args[i]
            if a in {"-u", "-g", "-p", "-h", "-c"} and i + 1 < len(args):
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            break
        if i < len(args):
            return None, " ".join(args[i:])
        return None, None

    return None, None


def _start_process_info(words: list[str], start_index: int) -> tuple[str, str]:
    """Return (executable, argument_string) from Start-Process tokens."""
    index = start_index
    total = len(words)
    exe = ""
    arg_list = ""
    positional: list[str] = []

    while index < total:
        word = words[index]
        name, inline = _opt(word)
        if name in {"-filepath", "-filename", "-file", "-path"}:
            if inline is not None:
                exe = inline
                index += 1
                continue
            if index + 1 < total:
                exe = words[index + 1]
                index += 2
                continue
            index += 1
            continue
        if name in {"-argumentlist", "-args", "-arguments"}:
            if inline is not None:
                arg_list = inline
                index += 1
                continue
            if index + 1 < total:
                arg_list = words[index + 1]
                index += 2
                continue
            index += 1
            continue
        if name in {"-workingdirectory", "-wd"}:
            if inline is None and index + 1 < total:
                index += 2
                continue
            index += 1
            continue
        if name is not None:
            if name in _VALUE_OPTS and inline is None and index + 1 < total:
                index += 2
                continue
            index += 1
            continue
        positional.append(word)
        index += 1

    if not exe and positional:
        exe = positional[0]
        if len(positional) > 1 and not arg_list:
            arg_list = " ".join(positional[1:])

    return exe, arg_list


def _python_check(
    statement: str,
    parsed: _Cmd,
    effective_cwd: str,
    env: Mapping[str, str] | None,
) -> str | None:
    code_pieces: list[str] = []

    args = parsed.args
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-c":
            if i + 1 < len(args):
                code_pieces.append(args[i + 1])
                i += 2
            else:
                i += 1
        elif arg.startswith("-c"):
            code_pieces.append(arg[2:])
            i += 1
        else:
            i += 1

    if "<<" in statement:
        code_pieces.append(statement)

    for code in code_pieces:
        if _PY_EXEC_RE.search(code) and _PY_LAUNCHER_RE.search(code):
            return (
                "R2 direct model launch via Python denied: "
                f"\"{_snippet(statement)}\". "
                f"Reach the model only through {_ROUTER}."
            )
        if _PY_WRITE_RE.search(code):
            if _PY_SPECIAL_STRINGS_RE.search(code):
                return (
                    "R3 guarded-path mutation via Python denied (heuristic speed bump): "
                    f"\"{_snippet(statement)}\". "
                    f"Send the change through {_ROUTER}."
                )
            if _SOURCE_EXT_STR_RE.search(code):
                return (
                    "R3 source-file mutation via Python denied (heuristic speed bump): "
                    f"\"{_snippet(statement)}\". "
                    f"Send the change through {_ROUTER}."
                )
            for literal in re.findall(r"['\"]([^'\"]+)['\"]", code):
                if _is_guarded(literal, effective_cwd, env):
                    return (
                        "R3 guarded-path mutation via Python denied (heuristic speed bump): "
                        f"\"{_snippet(statement)}\". "
                        f"Send the change through {_ROUTER}."
                    )
                if _is_source_target(literal, effective_cwd):
                    return (
                        "R3 source-file mutation via Python denied (heuristic speed bump): "
                        f"\"{_snippet(statement)}\". "
                        f"Send the change through {_ROUTER}."
                    )

    return None


def _git_check(statement: str, parsed: _Cmd) -> str | None:
    args = parsed.args
    i = 0
    while i < len(args):
        arg = args[i]
        cfg: str | None = None
        if arg == "-c":
            if i + 1 < len(args):
                cfg = args[i + 1]
                i += 2
            else:
                i += 1
        elif arg.startswith("-c="):
            cfg = arg[3:]
            i += 1
        elif arg.startswith("-c"):
            cfg = arg[2:]
            i += 1
        else:
            i += 1
            continue

        if cfg:
            key, sep, val = cfg.partition("=")
            key_low = key.strip().lower()
            val_clean = val.strip()
            if key_low.startswith("alias.") and val_clean.startswith("!"):
                return _git_config_reason(statement)
            if key_low.startswith("core."):
                return _git_config_reason(statement)
    return None


def _is_direct(parsed: _Cmd) -> bool:
    program = parsed.program
    if program in _DIRECT:
        return True
    if program == "claude":
        return "-p" in parsed.args or "--print" in parsed.args
    return _SCRIPT_RE.fullmatch(program) is not None


def _is_router(parsed: _Cmd) -> bool:
    if parsed.program != "dispatch.py" or not parsed.args:
        return False
    first = parsed.args[0].lower()
    return first in _ROUTER_CMDS or first.endswith(".md")


def _introspects(parsed: _Cmd) -> bool:
    if not parsed.args:
        return False
    first = parsed.args[0]
    if first == "--":
        return False
    if first.lower() == "exec":
        if len(parsed.args) < 2:
            return False
        candidate = parsed.args[1]
    else:
        candidate = first

    if candidate == "--":
        return False
    flag = candidate.split("=", 1)[0].lower() if candidate.startswith("--") else candidate.lower()
    return flag in _INTROSPECTION


def _repair_job(args: list[str]) -> str | None:
    for index, arg in enumerate(args):
        if arg == "--lane-repair":
            if index + 1 < len(args):
                return args[index + 1]
            return ""
        if arg.startswith("--lane-repair="):
            return arg.split("=", 1)[1]
    return None


def _is_read_cmd(parsed: _Cmd) -> bool:
    if parsed.program in _READ_CMDS:
        return True
    if parsed.program == "sed":
        return any(a in {"-n", "--quiet", "--silent"} for a in parsed.args)
    return False


def _supervisor_read_check(statement: str, parsed: _Cmd, effective_cwd: str) -> str | None:
    # Check input redirections
    for r in parsed.input_redirs:
        if _is_non_allowlisted_source(r, effective_cwd) or _is_non_allowlisted_dir(r, effective_cwd):
            return _supervisor_read_reason(statement)

    targets: list[str] = []
    args = parsed.args
    prog = parsed.program

    if prog in {"cat", "head", "tail", "type", "more", "less"}:
        for a in args:
            if not a.startswith("-") and not a.startswith("/"):
                targets.append(a)
    elif prog in {"get-content", "gc"}:
        index = 0
        while index < len(args):
            a = args[index]
            name, inline = _opt(a)
            if name in {"-path", "-literalpath"}:
                if inline is not None:
                    targets.append(inline)
                elif index + 1 < len(args):
                    targets.append(args[index + 1])
                    index += 1
                index += 1
                continue
            if not a.startswith("-"):
                targets.append(a)
            index += 1
    elif prog == "sed":
        index = 0
        saw_expr = False
        while index < len(args):
            a = args[index]
            name, inline = _opt(a)
            if name in {"-e", "-f", "--expression", "--file"}:
                saw_expr = True
                index += 1 if inline is not None else 2
                continue
            if name in {"-n", "--quiet", "--silent"}:
                index += 1
                continue
            if name is not None:
                index += 1
                continue
            if not saw_expr:
                saw_expr = True
            else:
                targets.append(a)
            index += 1
    elif prog in {"grep", "rg"}:
        index = 0
        saw_pat = False
        has_recursive = any(a in {"-r", "-R", "--recursive"} for a in args)
        while index < len(args):
            a = args[index]
            name, inline = _opt(a)
            if name in {"-e", "-f", "--regexp", "--file"}:
                saw_pat = True
                index += 1 if inline is not None else 2
                continue
            if a.startswith("-"):
                index += 1
                continue
            if not saw_pat:
                saw_pat = True
            else:
                targets.append(a)
            index += 1
        if not targets and (has_recursive or prog == "rg"):
            targets.append(effective_cwd)
    elif prog == "select-string":
        index = 0
        saw_pat = False
        while index < len(args):
            a = args[index]
            name, inline = _opt(a)
            if name in {"-pattern"}:
                saw_pat = True
                index += 1 if inline is not None else 2
                continue
            if name in {"-path", "-literalpath"}:
                if inline is not None:
                    targets.append(inline)
                elif index + 1 < len(args):
                    targets.append(args[index + 1])
                    index += 1
                index += 1
                continue
            if a.startswith("-"):
                index += 1
                continue
            if not saw_pat:
                saw_pat = True
            else:
                targets.append(a)
            index += 1
        if not targets and not parsed.input_redirs:
            targets.append(effective_cwd)
    elif prog == "findstr":
        index = 0
        saw_pat = False
        has_recursive = any(a.lower() == "/s" for a in args)
        while index < len(args):
            a = args[index]
            if a.lower().startswith("/c:") or a.lower().startswith("/r:"):
                saw_pat = True
                index += 1
                continue
            if a.startswith("/") or a.startswith("-"):
                index += 1
                continue
            if not saw_pat:
                saw_pat = True
            else:
                targets.append(a)
            index += 1
        if not targets and has_recursive:
            targets.append(effective_cwd)
    elif prog == "awk":
        index = 0
        saw_prog = False
        while index < len(args):
            a = args[index]
            name, inline = _opt(a)
            if name in {"-f", "--file"}:
                saw_prog = True
                index += 1 if inline is not None else 2
                continue
            if name in {"-f", "-v"}:
                index += 1 if inline is not None else 2
                continue
            if a.startswith("-"):
                index += 1
                continue
            if not saw_prog:
                saw_prog = True
            else:
                targets.append(a)
            index += 1

    for t in targets:
        if _is_non_allowlisted_source(t, effective_cwd) or _is_non_allowlisted_dir(t, effective_cwd):
            return _supervisor_read_reason(statement)
    return None


def _is_non_allowlisted_source(path: str, cwd: str) -> bool:
    if is_allowlisted_read(path) or _under_scratch_or_tmp(path, cwd):
        return False
    try:
        resolved = _canonical_path(path, cwd)
        if is_allowlisted_read(str(resolved)) or _under_scratch_or_tmp(str(resolved), cwd):
            return False
        if is_source_path(str(resolved)) or is_source_path(path):
            return True
    except Exception:
        if is_source_path(path):
            return True
    return False


def _is_non_allowlisted_dir(path: str, cwd: str) -> bool:
    if is_allowlisted_read(path) or _under_scratch_or_tmp(path, cwd):
        return False
    try:
        resolved = _canonical_path(path, cwd)
        if is_allowlisted_read(str(resolved)) or _under_scratch_or_tmp(str(resolved), cwd):
            return False
        if resolved.is_dir():
            return True
    except Exception:
        pass
    cleaned = path.strip().strip("'\"")
    if cleaned.endswith("/") or cleaned.endswith("\\"):
        return True
    return False


def _canonical_path(p: str, cwd: str) -> Path:
    cleaned = p.strip().strip("'\"")
    expanded = os.path.expanduser(os.path.expandvars(cleaned))
    path_obj = Path(expanded)
    if not path_obj.is_absolute():
        path_obj = Path(cwd) / path_obj
    try:
        return path_obj.resolve()
    except Exception:
        return path_obj


def _under_scratch_or_tmp(path: str, cwd: str) -> bool:
    try:
        resolved = _canonical_path(path, cwd)
        parts_lower = [part.lower() for part in resolved.parts]
        for part in parts_lower[:-1]:
            if part in {"scratchpad", "tmp"}:
                return True
        tmp_dir = Path(tempfile.gettempdir()).resolve()
        try:
            resolved.relative_to(tmp_dir)
            return True
        except (ValueError, RuntimeError):
            pass
    except Exception:
        pass
    return False


def _is_guarded(path: str, cwd: str, env: Mapping[str, str] | None) -> bool:
    if protected_path(path, cwd=cwd, env=env):
        return True
    try:
        normalized = norm_path(path)
    except (OSError, ValueError):
        normalized = path
    for candidate in (path, normalized):
        folded = candidate.replace("\\", "/")
        if any(pattern.search(folded) for pattern in GUARDED_PATH_PATTERNS):
            return True
    return False


def _is_source_target(path: str, cwd: str) -> bool:
    cleaned = path.strip().strip("'\"")
    if _under_scratch_or_tmp(cleaned, cwd):
        return False
    if is_source_path(cleaned):
        return True
    if "*" in cleaned or "?" in cleaned:
        for ext in SOURCE_EXTS:
            if cleaned.lower().endswith(ext):
                return True
        if cleaned.endswith("*") or cleaned.endswith("/*") or cleaned.endswith(r"\*"):
            return True
    return False


def _write_kind(path: str, cwd: str, env: Mapping[str, str] | None) -> str | None:
    if _is_guarded(path, cwd, env):
        return "guarded"
    if _is_source_target(path, cwd):
        return "source"
    return None


def _update_cwd(current_cwd: str, statement: str) -> str:
    parsed = _parse(statement)
    words = parsed.words
    first_non_assign = 0
    while first_non_assign < len(words) and _ASSIGN_RE.match(words[first_non_assign]):
        first_non_assign += 1
    if first_non_assign < len(words):
        cmd_name = _normalize_exe(words[first_non_assign])
        if cmd_name in {"cd", "chdir", "pushd"}:
            args = [
                a for a in words[first_non_assign + 1:]
                if not a.startswith("/") and not a.startswith("-")
            ]
            if args:
                target = args[0].strip().strip("'\"")
                try:
                    expanded = os.path.expanduser(os.path.expandvars(target))
                    p = Path(expanded)
                    if not p.is_absolute():
                        p = Path(current_cwd) / p
                    return str(p.resolve())
                except Exception:
                    pass
    return current_cwd


def _write_paths(parsed: _Cmd, cwd: str) -> list[str]:
    if parsed.program == "git":
        return []
    paths = list(parsed.redirs)
    program = parsed.program
    if program == "sed":
        paths.extend(_sed_files(parsed.args))
    elif program == "tee":
        paths.extend(_collect_tee(parsed.args))
    elif program in {"set-content", "add-content", "out-file"}:
        paths.extend(_collect_powershell_content(parsed.args))
    elif program in {"mv", "move", "move-item", "ren", "rename"}:
        paths.extend(_collect_move_both(parsed.args, cwd))
    elif program in {"cp", "copy", "copy-item"}:
        paths.extend(_collect_copy(parsed.args, cwd))
    elif program in _WRITE_CMDS:
        paths.extend(_collect_general_write(parsed.args))
    return paths


def _sed_files(args: list[str]) -> list[str]:
    if not any(_sed_inplace(arg) for arg in args):
        return []
    positional: list[str] = []
    saw_expr = False
    index = 0
    while index < len(args):
        arg = args[index]
        name, inline = _opt(arg)
        if name in {"-e", "-f", "--expression", "--file"}:
            saw_expr = True
            index += 1 if inline is not None else 2
            continue
        if name is not None:
            index += 1
            continue
        positional.append(arg)
        index += 1
    if not positional:
        return []
    if saw_expr or len(positional) == 1:
        return positional
    return positional[1:]


def _sed_inplace(arg: str) -> bool:
    if arg in {"-i", "--in-place"} or arg.startswith("--in-place="):
        return True
    return arg.startswith("-i") and not arg.startswith("--")


def _collect_tee(args: list[str]) -> list[str]:
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positional.extend(args[index + 1:])
            break
        if arg.startswith("-"):
            index += 1
            continue
        positional.append(arg)
        index += 1
    return positional


def _collect_powershell_content(args: list[str]) -> list[str]:
    index = 0
    positional: list[str] = []
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positional.extend(args[index + 1:])
            break
        name, inline = _opt(arg)
        if name in {"-path", "-filepath", "-literalpath"}:
            if inline is not None:
                return [inline]
            if index + 1 < len(args):
                return [args[index + 1]]
            return []
        if name is not None:
            takes_val = name in _VALUE_OPTS
            if takes_val and inline is None and index + 1 < len(args):
                index += 1
            index += 1
            continue
        positional.append(arg)
        index += 1
    if positional:
        return [positional[0]]
    return []


def _parse_dest_args(args: list[str]) -> tuple[list[str], str | None]:
    positional: list[str] = []
    dest_opt: str | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positional.extend(args[index + 1:])
            break
        name, inline = _opt(arg)
        if name in _DEST_OPTS:
            if inline is not None:
                dest_opt = inline
            elif index + 1 < len(args):
                dest_opt = args[index + 1]
                index += 1
            index += 1
            continue
        if name in _PATH_OPTS:
            val = inline
            if val is None and index + 1 < len(args):
                val = args[index + 1]
                index += 1
            if val is not None:
                positional.append(val)
            index += 1
            continue
        if name is not None:
            takes_val = name in _VALUE_OPTS
            if takes_val and inline is None and index + 1 < len(args):
                index += 1
            index += 1
            continue
        positional.append(arg)
        index += 1
    return positional, dest_opt


def _collect_copy(args: list[str], cwd: str) -> list[str]:
    positional, dest_opt = _parse_dest_args(args)
    dest = dest_opt if dest_opt is not None else (positional[-1] if positional else None)
    sources = positional[:-1] if (dest_opt is None and len(positional) > 1) else positional
    if not dest:
        return []

    is_dir = False
    cleaned_dest = dest.strip().strip("'\"")
    if cleaned_dest.endswith("/") or cleaned_dest.endswith("\\"):
        is_dir = True
    else:
        try:
            cand = _canonical_path(cleaned_dest, cwd)
            if cand.is_dir():
                is_dir = True
        except Exception:
            pass

    if is_dir and sources:
        results = []
        for src in sources:
            src_name = Path(src.strip().strip("'\"")).name
            results.append(f"{cleaned_dest.rstrip('/\\')}/{src_name}")
        return results
    return [dest]


def _collect_move_both(args: list[str], cwd: str) -> list[str]:
    positional, dest_opt = _parse_dest_args(args)
    dest = dest_opt if dest_opt is not None else (positional[-1] if positional else None)
    sources = positional[:-1] if (dest_opt is None and len(positional) > 1) else positional
    paths_to_check: list[str] = []
    for src in sources:
        paths_to_check.append(src)
    if dest:
        is_dir = False
        cleaned_dest = dest.strip().strip("'\"")
        if cleaned_dest.endswith("/") or cleaned_dest.endswith("\\"):
            is_dir = True
        else:
            try:
                cand = _canonical_path(cleaned_dest, cwd)
                if cand.is_dir():
                    is_dir = True
            except Exception:
                pass
        if is_dir and sources:
            for src in sources:
                src_name = Path(src.strip().strip("'\"")).name
                paths_to_check.append(f"{cleaned_dest.rstrip('/\\')}/{src_name}")
        else:
            paths_to_check.append(dest)
    return paths_to_check


def _collect_general_write(args: list[str]) -> list[str]:
    positional: list[str] = []
    named: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positional.extend(args[index + 1:])
            break
        name, inline = _opt(arg)
        if name in _PATH_OPTS:
            if inline is not None:
                named.append(inline)
            elif index + 1 < len(args):
                named.append(args[index + 1])
                index += 1
            index += 1
            continue
        if name is not None:
            takes_val = name in _VALUE_OPTS
            if takes_val and inline is None and index + 1 < len(args):
                index += 1
            index += 1
            continue
        positional.append(arg)
        index += 1
    return named + positional


def _parse(statement: str) -> _Cmd:
    words: list[str] = []
    redirs: list[str] = []
    input_redirs: list[str] = []
    for kind, text in _lex(statement):
        if kind == "write":
            redirs.append(text)
        elif kind == "read":
            input_redirs.append(text)
        elif text:
            words.append(text)
    program, arg_at = _head(words)
    return _Cmd(program, words[arg_at:], words, redirs, input_redirs)


def _head(words: list[str]) -> tuple[str, int]:
    index = 0
    total = len(words)
    while index < total:
        word = words[index]
        if _ASSIGN_RE.match(word):
            index += 1
            continue
        if word == "&":
            index += 1
            continue
        low = _normalize_exe(word)
        if low in {"cd", "chdir", "pushd"}:
            return "", total
        if low == "start-process":
            exe, _ = _start_process_info(words, index + 1)
            if not exe:
                return "", total
            return _normalize_exe(exe), total
        if low in _WRAPPERS:
            index = _skip_wrapper(words, index + 1, low)
            continue
        if low in _PYTHON:
            script_base, script_at = _first_python_script(words, index + 1)
            if not script_base:
                return low, index + 1
            return script_base, script_at
        return low, index + 1
    return "", total


def _first_python_script(words: list[str], index: int) -> tuple[str, int]:
    total = len(words)
    while index < total:
        word = words[index]
        if _ASSIGN_RE.match(word):
            index += 1
            continue
        if word == "--":
            index += 1
            if index < total:
                return _basename(words[index]), index + 1
            return "", total
        low = word.lower()
        if low in {"-c", "-"}:
            return "", total
        if low == "-m":
            if index + 1 < total:
                return _basename(words[index + 1]), index + 2
            return "", total
        if low in _PYTHON_VALUE_OPTS:
            index += 2
            continue
        if any(low.startswith(opt) for opt in ("-w", "-x")):
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            continue
        return _basename(word), index + 1
    return "", total


def _skip_wrapper(words: list[str], index: int, wrapper: str) -> int:
    while index < len(words):
        word = words[index]
        if _ASSIGN_RE.match(word):
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            if wrapper == "env" and word in _ENV_VALUE_FLAGS and index < len(words):
                index += 1
            continue
        if wrapper in {"start", "call"} and word.startswith("/"):
            index += 1
            continue
        break
    return index


def _normalize_exe(token: str) -> str:
    cleaned = token.strip().strip("'\"")
    if cleaned == "&":
        return "&"
    base = _basename(cleaned)
    for ext in _STRIP_EXT:
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


def _basename(token: str) -> str:
    cleaned = token.strip().strip("'\"")
    return cleaned.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _opt(token: str) -> tuple[str | None, str | None]:
    if not token.startswith("-") or token == "-":
        return None, None
    if token.startswith("--"):
        if "=" in token:
            name, value = token.split("=", 1)
            return name.lower(), value
        return token.lower(), None
    head, sep, tail = token.partition(":")
    if sep and head[1:].replace("-", "").isalpha():
        return head.lower(), tail
    return token.lower(), None


def _lex(statement: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    text = statement
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch in " \t\r\n":
            index += 1
            continue
        redirect = _read_redirect(text, index)
        if redirect is not None:
            kind, value, index = redirect
            if kind in {"write", "read"} and value:
                tokens.append((kind, value))
            continue
        if text.startswith("<<", index):
            parsed = _parse_heredoc_op(text, index)
            if parsed is not None:
                index = parsed[2]
                continue
        if ch == "&":
            tokens.append(("word", "&"))
            index += 1
            continue
        if ch in "|;":
            index += 1
            continue
        word, index = _read_word(text, index)
        if word:
            tokens.append(("word", word))
        elif index < length and text[index] == ch:
            index += 1
    return tokens


def _read_redirect(text: str, index: int) -> tuple[str, str, int] | None:
    if text.startswith("<<", index):
        return None
    write = False
    if text.startswith("&>>", index):
        op_end = index + 3
        write = True
    elif text.startswith("&>", index):
        op_end = index + 2
        write = True
    else:
        matched = _REDIR_RE.match(text, index)
        if matched:
            op_end = matched.end()
            write = True
        elif text[index] == "<":
            op_end = index + 1
            write = False
        else:
            return None
    if op_end < len(text) and text[op_end] == "&":
        nxt = op_end + 1
        if nxt >= len(text) or text[nxt].isdigit() or text[nxt] == "-":
            while nxt < len(text) and (text[nxt].isdigit() or text[nxt] == "-"):
                nxt += 1
            return ("skip", "", nxt)
    cursor = op_end
    while cursor < len(text) and text[cursor] in " \t":
        cursor += 1
    if cursor >= len(text) or text[cursor] in "\r\n|;&":
        return ("skip", "", cursor)
    target, new_index = _read_word(text, cursor)
    kind = "write" if write else "read"
    if target:
        return (kind, target, new_index)
    return ("skip", "", new_index)


def _read_word(text: str, index: int) -> tuple[str, int]:
    parts: list[str] = []
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == "'":
            index += 1
            while index < length and text[index] != "'":
                parts.append(text[index])
                index += 1
            if index < length:
                index += 1
            continue
        if ch == '"':
            index += 1
            while index < length and text[index] != '"':
                if text[index] == "\\" and index + 1 < length:
                    nxt = text[index + 1]
                    parts.append(nxt if nxt in "\"\\$`" else text[index])
                    index += 2 if nxt in "\"\\$`" else 1
                    continue
                parts.append(text[index])
                index += 1
            if index < length:
                index += 1
            continue
        if ch == "\\" and index + 1 < length:
            nxt = text[index + 1]
            if nxt in " \t\r\n<>|&;'\"$":
                parts.append(nxt)
                index += 2
            else:
                parts.append("\\")
                index += 1
            continue
        if ch in " \t\r\n<>|&;":
            break
        parts.append(ch)
        index += 1
    return "".join(parts), index


def _strip_bodies(command: str) -> str:
    """Drop non-interpreter heredocs and here-strings. Keep interpreter heredocs."""
    out: list[str] = []
    index = 0
    length = len(command)
    pending: list[tuple[str, bool, bool]] = []
    in_single = False
    in_double = False
    escaped = False

    while index < length:
        ch = command[index]
        if escaped:
            out.append(ch)
            escaped = False
            index += 1
            continue
        if in_single:
            out.append(ch)
            if ch == "'":
                in_single = False
            index += 1
            continue
        if in_double:
            out.append(ch)
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
            index += 1
            continue
        if pending and ch == "\n":
            delim, strip_tabs, is_interp = pending.pop(0)
            index = _skip_newline(command, index)
            body_lines: list[str] = []
            while index < len(command):
                line, nxt = _take_line(command, index)
                check = line.lstrip("\t") if strip_tabs else line
                if check == delim:
                    index = nxt
                    break
                body_lines.append(line)
                index = nxt
            if is_interp:
                out.append("\x00" + "\x00".join(body_lines) + "\x00" + delim)
            else:
                out.append("\n")
            continue
        if ch == "\r":
            index += 1
            continue
        if command.startswith("<<", index):
            parsed = _parse_heredoc_op(command, index)
            if parsed is not None:
                delim, strip_tabs, op_end = parsed
                full_out = "".join(out)
                last_sep = max(
                    full_out.rfind("\n"),
                    full_out.rfind(";"),
                    full_out.rfind("&"),
                    full_out.rfind("|"),
                )
                header = full_out[last_sep + 1:].strip()
                hdr_words = [w for w in re.split(r"[ \t]+", header) if w]
                prog = ""
                for w in hdr_words:
                    if not _ASSIGN_RE.match(w):
                        prog = _normalize_exe(w)
                        break
                is_interp = prog in _INTERPRETERS
                out.append(command[index:op_end])
                pending.append((delim, strip_tabs, is_interp))
                index = op_end
                continue
        if ch == "@" and index + 1 < length and command[index + 1] in "'\"":
            end = _herestring_end(command, index)
            if end is not None:
                out.append("\n")
                index = end
                continue
        if ch == "\\":
            escaped = True
            out.append(ch)
            index += 1
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            index += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            index += 1
            continue
        out.append(ch)
        index += 1
    return "".join(out)


def _parse_heredoc_op(text: str, index: int) -> tuple[str, bool, int] | None:
    cursor = index + 2
    strip_tabs = False
    if cursor < len(text) and text[cursor] == "-":
        strip_tabs = True
        cursor += 1
    if cursor >= len(text):
        return None
    if text[cursor] in "'\"":
        quote = text[cursor]
        end = text.find(quote, cursor + 1)
        if end < 0 or "\n" in text[cursor + 1:end]:
            return None
        return text[cursor + 1:end], strip_tabs, end + 1
    if text[cursor] == "\\":
        cursor += 1
    matched = re.match(r"[A-Za-z_][A-Za-z0-9_]*", text[cursor:])
    if not matched:
        return None
    return matched.group(0), strip_tabs, cursor + matched.end()


def _herestring_end(text: str, index: int) -> int | None:
    quote = text[index + 1]
    cursor = index + 2
    if cursor < len(text) and text[cursor] == "\r":
        cursor += 1
    if cursor >= len(text) or text[cursor] != "\n":
        return None
    cursor += 1
    closer = quote + "@"
    while cursor < len(text):
        line, nxt = _take_line(text, cursor)
        if line == closer:
            return nxt
        if nxt >= len(text) and line != closer:
            return None
        cursor = nxt
    return None


def _take_line(text: str, index: int) -> tuple[str, int]:
    end = text.find("\n", index)
    if end < 0:
        return text[index:].rstrip("\r"), len(text)
    return text[index:end].rstrip("\r"), end + 1


def _skip_newline(text: str, index: int) -> int:
    if text.startswith("\r\n", index):
        return index + 2
    if index < len(text) and text[index] in "\r\n":
        return index + 1
    return index


def _launch_reason(statement: str) -> str:
    return (
        "R2 direct model launch denied: "
        f"\"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _unknown_job_reason(statement: str, job_id: str) -> str:
    shown = job_id if job_id else "(missing)"
    return (
        f"R2 lane-repair job {shown} is unknown: "
        f"\"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _depth_exceeded_reason(statement: str) -> str:
    return (
        f"R2 nested shell recursion depth limit ({_MAX_RECURSION_DEPTH}) exceeded: "
        f"\"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _encoded_ps_reason(statement: str) -> str:
    return (
        "R2 encoded powershell commands are denied: "
        f"\"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _git_config_reason(statement: str) -> str:
    return (
        f"R2 execution-bearing git config denied: \"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _mutate_reason(statement: str, kind: str) -> str:
    if kind == "guarded":
        name = "R3 guarded-path mutation denied"
    else:
        name = "R3 source-file mutation denied"
    return f"{name}: \"{_snippet(statement)}\". Send the change through {_ROUTER}."


def _supervisor_read_reason(statement: str) -> str:
    return (
        "R4 supervisor source read denied: "
        f"\"{_snippet(statement)}\". "
        f"Send source reading to `python D:/APPS/_shared/dispatch/dispatch.py lane diagnose --brief FILE`."
    )


def _snippet(statement: str) -> str:
    flat = statement.strip().replace("\r\n", "\n").replace("\n", " ")
    return flat[:160]


if __name__ == "__main__":
    raise SystemExit(main())
