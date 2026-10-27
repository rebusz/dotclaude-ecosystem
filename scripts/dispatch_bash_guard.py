#!/usr/bin/env python3
"""PreToolUse guard for Bash and PowerShell (rules R2 and R3).

Models are reachable only through ``python D:/APPS/_shared/dispatch/dispatch.py``.
Direct launches of codex, glm, kimi, cursor-agent, agy, opencode, claude -p/--print,
and the CDP/audit scripts are denied. Bash and PowerShell may not write guarded
paths, source files, or script files (.sh .cmd .bat .ps1 .psm1 .vbs). The
supervisor may not read source files or non-allowlisted source directories with
shell utilities. Nested shells are unwrapped up to recursion depth 4; command
substitutions $(...)/backticks, subshell and group wrappers, PowerShell script
blocks, and function-definition bodies (POSIX f() and PowerShell function f) are
scanned as nested statements. Shells fed from stdin or pointed at a script
outside a tracked git repository are denied. POSIX shell option clusters
containing c (bash -lc, -ic, -xc) are treated as command strings. PowerShell
EncodedCommand prefixes (-ec, -en, -enc, ...) are denied. Shell builtins
command, builtin, exec, and eval are unwrapped; ANSI-C $'...' quoting is
decoded. Inline code in python -c, node -e, perl -e, ruby -e, and php -r is
scanned for launches and source/guarded-path mutations. git stays allowed by
default except for execution-bearing config and alias/core writes (both tiers),
source reads via show/grep/log -p/blame/cat-file -p (supervisor), and
apply/am/restore/checkout -- source mutations (both tiers). Scratch and temp
exemptions are anchored to the canonical scratch root and the system temp
directory, never to a bare path component.

Honest boundary note: hooks stop accidental and rationalised bypass; they are
not a security boundary against an agent that deliberately uses the operator OS
credentials. Inline/heredoc mutation checks provide a heuristic speed bump, not
an airtight sandbox. Running python scripts that live in scratch/tmp directories
stays allowed as an accepted limitation.

decide() is pure. main() prints one JSON object or nothing.
Importing this module creates no files.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_guard_common import (  # noqa: E402 - sibling import, same pattern as other hooks
    GUARDED_PATH_PATTERNS,
    SOURCE_EXTS,
    deny,
    is_allowlisted_read,
    is_scratch_root_path,
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
_WRAPPERS = frozenset({
    "env", "time", "nohup", "call", "start",
    "command", "builtin", "exec", "eval",
})
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
    "bash", "sh", "zsh", "dash", "pwsh", "powershell",
    "node", "nodejs", "perl", "ruby", "php",
})
_INLINE_FLAGS: dict[str, tuple[str, ...]] = {
    "python": ("-c",),
    "python3": ("-c",),
    "py": ("-c",),
    "pythonw": ("-c",),
    "node": ("-e", "--eval", "-p", "--print"),
    "nodejs": ("-e", "--eval", "-p", "--print"),
    "perl": ("-e", "-E"),
    "ruby": ("-e",),
    "php": ("-r",),
}
_INLINE_INTERPRETERS = frozenset(_INLINE_FLAGS.keys())
_READ_CMDS = frozenset({
    "cat", "head", "tail", "type", "more", "less",
    "get-content", "gc", "awk", "rg", "grep",
    "select-string", "findstr",
})
_PYTHON_VALUE_OPTS = frozenset({"-w", "-x", "--check-hash-based-pycs"})
_INLINE_EXEC_RE = re.compile(
    r"\b(?:subprocess|os\.system|Popen|spawn|spawnSync|"
    r"child_process|exec|execSync|system|passthru|shell_exec|proc_open)\b|`"
)
_PY_EXEC_RE = _INLINE_EXEC_RE
_PY_LAUNCHER_RE = re.compile(
    r"\b(?:codex|glm|kimi|cursor-agent|cursor_agent|agy|opencode|cdp_[A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
_INLINE_WRITE_RE = re.compile(
    r"\b(?:write_text|write_bytes|shutil\.copy\w*|shutil\.move|os\.replace|os\.rename|"
    r"writeFile|writeFileSync|createWriteStream|copyFile|copyFileSync|"
    r"file_put_contents|fwrite)\b|"
    r"\b(?:open|fopen|File\.open|File\.write|IO\.write)\s*\([^)]*['\"][wax\+>]",
    re.IGNORECASE,
)
_PY_WRITE_RE = _INLINE_WRITE_RE
_PY_SPECIAL_STRINGS_RE = re.compile(
    r"\b(?:dispatch_guard_common|lane_authorize|write_override|"
    r"load_or_create_key|dispatch_override)\b"
)
_SOURCE_EXT_STR_RE = re.compile(
    r"['\"][^'\"]*?\.(?:py|ts|tsx|js|jsx|mjs|cjs)['\"]",
    re.IGNORECASE,
)
_SCRIPT_FILE_EXTS = (".sh", ".cmd", ".bat", ".ps1", ".psm1", ".vbs")
_DENIED_WRITE_EXTS = SOURCE_EXTS + _SCRIPT_FILE_EXTS
_POSIX_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
_PS_SHELLS = frozenset({"powershell", "pwsh"})
_POSIX_SHELL_VALUE_FLAGS = frozenset({"--rcfile", "--init-file", "-o", "-O"})
_PS_SHELL_VALUE_FLAGS = frozenset({
    "-executionpolicy", "-outputformat", "-o", "-inputformat",
    "-windowstyle", "-workingdirectory", "-custompipename",
    "-configurationname", "-settingsfile",
})
_GIT_VALUE_FLAGS = frozenset({
    "-c", "-C", "--git-dir", "--work-tree", "--namespace",
    "--exec-path", "--super-prefix",
})
_GIT_READ_SUBS = frozenset({"show", "grep", "log", "blame", "cat-file"})
_GIT_MUTATE_SUBS = frozenset({"apply", "am", "restore", "checkout"})
_FUNC_DEF_PREFIX_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\)\s*\{|"
    r"(?:function|filter)\s+[A-Za-z_][A-Za-z0-9_:\-]*\s*(?:\([^)]*\)\s*)?\{)",
    re.IGNORECASE,
)
_ROUTER_CANONICAL = "d:/apps/_shared/dispatch/dispatch.py"


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
    in_ansi = False
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
        if in_ansi:
            buf.append(ch)
            if ch == "\\" and i + 1 < n:
                buf.append(text[i + 1])
                i += 2
                continue
            if ch == "'":
                in_ansi = False
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
        if ch == "$" and i + 1 < n and text[i + 1] == "'":
            in_ansi = True
            buf.append(ch)
            buf.append("'")
            i += 2
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

    reason = _command_text_reason(command, env, 0, effective_cwd, tier2, set())
    if reason is not None:
        return deny(reason)
    return None


def main() -> int:
    """Read one hook payload from stdin and apply decide() under run_guarded."""

    def _from_stdin() -> dict | None:
        return decide(read_payload())

    return run_guarded(_HOOK_FILE, _from_stdin)


def _command_text_reason(
    text: str,
    env: Mapping[str, str] | None,
    depth: int,
    effective_cwd: str,
    is_tier2_caller: bool,
    banned_git_aliases: set[str] | None,
) -> str | None:
    cwd = effective_cwd
    for stmt in split_statements(text):
        reason = _statement_reason(
            statement=stmt,
            env=env,
            depth=depth,
            effective_cwd=cwd,
            is_tier2_caller=is_tier2_caller,
            banned_git_aliases=banned_git_aliases,
        )
        if reason is not None:
            return reason
        cwd = _update_cwd(cwd, stmt)
    return None


def _statement_reason(
    statement: str,
    env: Mapping[str, str] | None,
    depth: int = 0,
    effective_cwd: str = "",
    is_tier2_caller: bool = False,
    banned_git_aliases: set[str] | None = None,
) -> str | None:
    if depth >= _MAX_RECURSION_DEPTH:
        return _depth_exceeded_reason(statement)
    if banned_git_aliases is None:
        banned_git_aliases = set()

    # 1. Inspect substitutions before stripping group suffixes: an assignment
    # such as RESULT=$(codex exec hi) also ends in ")" but is not a group.
    pieces, rewritten = _extract_command_substitutions(statement)
    for piece in pieces:
        piece_reason = _command_text_reason(
            piece, env, depth + 1, effective_cwd, is_tier2_caller, banned_git_aliases,
        )
        if piece_reason is not None:
            return piece_reason
    head = _head_word(rewritten)
    if "$(" in head or "`" in head:
        return _substitution_reason(statement)

    # 2. Subshell / group / function-definition wrappers must not hide the program
    inner = _ungroup(statement)
    if inner != statement:
        return _command_text_reason(
            inner, env, depth + 1, effective_cwd, is_tier2_caller, banned_git_aliases,
        )

    parsed = _parse(statement)

    # 3. Check outer statement redirections
    for path in parsed.redirs:
        kind = _write_kind(path, effective_cwd, env)
        if kind is not None:
            return _mutate_reason(statement, kind)

    # 4. Check wrapper unwrapping
    err_reason, inner_cmd = _unwrap_statement(statement, parsed, effective_cwd, env)
    if err_reason is not None:
        return err_reason
    if inner_cmd is not None:
        return _command_text_reason(
            inner_cmd, env, depth + 1, effective_cwd, is_tier2_caller, banned_git_aliases,
        )

    # 5. Inline code / script inspection (python, node, perl, ruby, php)
    if parsed.program in _INLINE_INTERPRETERS:
        inline_reason = _inline_code_check(statement, parsed, effective_cwd, env)
        if inline_reason is not None:
            return inline_reason

    # 6. Git: allowed by default with specific denies
    if parsed.program == "git":
        git_reason = _git_check(statement, parsed, banned_git_aliases)
        if git_reason is not None:
            return git_reason
        sub = _git_subcommand(parsed)
        if sub is not None and sub in banned_git_aliases:
            return _git_alias_reason(statement)
        if not is_tier2_caller:
            read_reason = _git_supervisor_read_check(statement, parsed, effective_cwd, env)
            if read_reason is not None:
                return read_reason
        mut_reason = _git_mutation_check(statement, parsed, effective_cwd, env)
        if mut_reason is not None:
            return mut_reason
        return None

    # 7. Direct launch check
    if not _is_router(parsed, effective_cwd) and _is_direct(parsed) and not _introspects(parsed):
        job_id = _repair_job(parsed.args)
        if job_id is None:
            return _launch_reason(statement)
        if not lane_repair_job_exists(job_id, env):
            return _unknown_job_reason(statement, job_id)

    # 8. Shell script operands and direct script runs
    raw_head = _raw_head_word(parsed)
    if raw_head is not None and raw_head.lower().endswith(_SCRIPT_FILE_EXTS):
        script_reason = _script_operand_reason(raw_head, statement, effective_cwd, env)
        if script_reason is not None:
            return script_reason

    # 9. Supervisor read rule
    if not is_tier2_caller and _is_read_cmd(parsed):
        read_reason = _supervisor_read_check(statement, parsed, effective_cwd, env)
        if read_reason is not None:
            return read_reason

    # 10. Mutation checks for other commands (cp, mv, sed, tee, rm, set-content, etc.)
    for path in _write_paths(parsed, effective_cwd):
        kind = _write_kind(path, effective_cwd, env)
        if kind is not None:
            return _mutate_reason(statement, kind)

    return None


def _ungroup(statement: str) -> str:
    """Strip subshell/group wrappers and function-definition prefixes.

    Removes leading "(" / "{" (including the PowerShell "& {" call form and
    "name(){ ... }" function definitions) and trailing ")" / "}" so wrappers
    cannot hide the program word. Returns the original statement when nothing
    was stripped.
    """
    s = statement.strip()
    changed = s != statement
    while s:
        if s.startswith("&"):
            tail = s[1:].lstrip()
            if tail.startswith("{"):
                s = tail
                changed = True
                continue
            break
        m = _FUNC_DEF_PREFIX_RE.match(s)
        if m:
            s = s[m.end():].lstrip()
            changed = True
            continue
        if s[0] in "({":
            s = s[1:].lstrip()
            changed = True
            continue
        if s[-1] in ")}":
            s = s[:-1].rstrip()
            changed = True
            continue
        break
    return s if changed else statement


def _extract_command_substitutions(text: str) -> tuple[list[str], str]:
    """Extract $(...) and backtick command substitutions outside single quotes.

    Returns the inner texts and the statement with each substitution span
    replaced by a placeholder, so an unbalanced "$(" or backtick left in the
    program word can be detected. Arithmetic $((...)) spans are skipped.
    """
    pieces: list[str] = []
    out: list[str] = []
    i = 0
    n = len(text)
    in_single = False
    in_double = False
    in_ansi = False
    while i < n:
        ch = text[i]
        if ch == "\\" and not in_single and not in_ansi:
            out.append(ch)
            if i + 1 < n:
                out.append(text[i + 1])
                i += 1
            i += 1
            continue
        if in_ansi:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == "'":
                in_ansi = False
            i += 1
            continue
        if ch == "'" and not in_double:
            out.append(ch)
            in_single = not in_single
            i += 1
            continue
        if ch == '"' and not in_single:
            out.append(ch)
            in_double = not in_double
            i += 1
            continue
        if ch == "$" and not in_single and not in_double and i + 1 < n and text[i + 1] == "'":
            in_ansi = True
            out.append(ch)
            out.append("'")
            i += 2
            continue
        if ch == "$" and not in_single and i + 1 < n and text[i + 1] == "(":
            if i + 2 < n and text[i + 2] == "(":
                end = _skip_arithmetic(text, i + 2)
                out.append(text[i:end])
                i = end
                continue
            inner, end = _match_paren(text, i + 2)
            if inner is None:
                out.append(ch)
                i += 1
                continue
            pieces.append(inner)
            out.append("X")
            i = end
            continue
        if ch == "`" and not in_single:
            close = text.find("`", i + 1)
            if close < 0:
                out.append(ch)
                i += 1
                continue
            pieces.append(text[i + 1:close])
            out.append("X")
            i = close + 1
            continue
        out.append(ch)
        i += 1
    return pieces, "".join(out)


def _match_paren(text: str, start: int) -> tuple[str | None, int]:
    depth = 1
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            j = text.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"':
                    break
                j += 1
            i = n if j >= n else j + 1
            continue
        if ch == "\\":
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    return None, start


def _skip_arithmetic(text: str, start: int) -> int:
    depth = 2
    i = start
    n = len(text)
    while i < n:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _head_word(text: str) -> str:
    for token in text.split():
        if token == "&":
            continue
        if _ASSIGN_RE.match(token):
            continue
        return token
    return ""


def _raw_head_word(parsed: _Cmd) -> str | None:
    for word in parsed.words:
        if word == "&":
            continue
        if _ASSIGN_RE.match(word):
            continue
        if _normalize_exe(word) in _WRAPPERS:
            continue
        return word
    return None


def _is_ps_encoded_flag(token: str) -> bool:
    low = token.lower()
    if not (low.startswith("-") or low.startswith("/")):
        return False
    opt = low.lstrip("-/")
    opt_name = opt.split(":", 1)[0].split("=", 1)[0]
    if opt_name in {"ec", "e"}:
        return True
    if opt_name.startswith("ec"):
        return True
    if len(opt_name) >= 2 and "encodedcommand".startswith(opt_name):
        return True
    return False


def _strip_surrounding_quotes(s: str) -> str:
    s = s.strip()
    while len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        s = s[1:-1].strip()
    return s


def _unwrap_statement(
    statement: str,
    parsed: _Cmd,
    effective_cwd: str,
    env: Mapping[str, str] | None,
) -> tuple[str | None, str | None]:
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
            if _normalize_exe(exe) == "cmd":
                clean_arg = arg_list.strip()
                if clean_arg.startswith("@(") and clean_arg.endswith(")"):
                    clean_arg = clean_arg[2:-1].strip()
                clean_arg = _strip_surrounding_quotes(clean_arg)
                if (
                    len(clean_arg) > 2
                    and clean_arg[:2].lower() in {"/c", "-c", "/k", "-k"}
                ):
                    inner = _strip_surrounding_quotes(clean_arg[2:])
                    if inner:
                        return None, inner
            inner = f"{exe} {arg_list}".strip()
            return None, inner
        return None, None

    # cmd / cmd.exe
    if head_low == "cmd":
        for i, w in enumerate(words[first_non_assign + 1:], start=first_non_assign + 1):
            w_low = w.lower()
            if w_low in {"/c", "-c", "/k", "-k"}:
                if i + 1 < len(words):
                    inner = " ".join(words[i + 1:]).strip()
                    if inner:
                        return None, inner
                return None, None
            if len(w) > 2 and w[:2].lower() in {"/c", "-c", "/k", "-k"}:
                rem = _strip_surrounding_quotes(w[2:])
                if i + 1 < len(words):
                    inner = f"{rem} {' '.join(words[i + 1:])}".strip()
                else:
                    inner = rem
                if inner:
                    return None, inner
                return None, None
        return None, None

    # bash, sh, zsh, dash
    if head_low in _POSIX_SHELLS:
        args = words[first_non_assign + 1:]
        c_set = False
        cmd_words: list[str] = []
        operand: str | None = None
        i = 0
        while i < len(args):
            arg = args[i]
            if arg == "--":
                if i + 1 < len(args):
                    operand = args[i + 1]
                break
            if arg in _POSIX_SHELL_VALUE_FLAGS:
                i += 2
                continue
            if arg.startswith("--"):
                i += 1
                continue
            if arg.startswith("-") and len(arg) > 1:
                cluster = arg[1:]
                if "c" in cluster:
                    c_set = True
                    idx = cluster.find("c")
                    attached = cluster[idx + 1:]
                    if attached:
                        cmd_words.append(attached)
                    cmd_words.extend(args[i + 1:])
                    break
                i += 1
                continue
            operand = arg
            break

        if c_set:
            inner = " ".join(cmd_words).strip()
            if inner:
                return None, inner
            return None, ""

        if operand is None:
            return _stdin_shell_reason(statement), None
        bad = _script_operand_reason(operand, statement, effective_cwd, env)
        if bad is not None:
            return bad, None
        return None, None

    # powershell, pwsh
    if head_low in _PS_SHELLS:
        args = words[first_non_assign + 1:]
        for w in args:
            if _is_ps_encoded_flag(w):
                return _encoded_ps_reason(statement), None
        idx = -1
        for i, w in enumerate(args):
            w_low = w.lower()
            if w_low in {"-c", "-command", "/c", "/command", "--command"}:
                idx = i
                break
            if w_low.startswith("-c:") or w_low.startswith("-command:"):
                return None, w.split(":", 1)[1]
        if idx >= 0 and idx + 1 < len(args):
            inner = " ".join(args[idx + 1:])
            return None, inner
        operand = _ps_shell_operand(args)
        if operand is None:
            return _stdin_shell_reason(statement), None
        bad = _script_operand_reason(operand, statement, effective_cwd, env)
        if bad is not None:
            return bad, None
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

    # command, builtin, exec
    if head_low in {"command", "builtin", "exec"}:
        rem = _skip_wrapper(words, first_non_assign + 1, head_low)
        if rem < len(words):
            return None, " ".join(words[rem:])
        return None, None

    # eval
    if head_low == "eval":
        args = words[first_non_assign + 1:]
        if args:
            return None, " ".join(args)
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


def _inline_code_check(
    statement: str,
    parsed: _Cmd,
    effective_cwd: str,
    env: Mapping[str, str] | None,
) -> str | None:
    prog = parsed.program
    flags = _INLINE_FLAGS.get(prog, ("-c",))
    code_pieces: list[str] = []

    args = parsed.args
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in flags:
            if i + 1 < len(args):
                code_pieces.append(args[i + 1])
                i += 2
            else:
                i += 1
        elif any(arg.startswith(f) and len(arg) > len(f) for f in flags if len(f) == 2):
            for f in flags:
                if len(f) == 2 and arg.startswith(f) and len(arg) > len(f):
                    code_pieces.append(arg[len(f):])
                    break
            i += 1
        else:
            i += 1

    if "<<" in statement:
        code_pieces.append(statement)

    prog_title = "PHP" if prog == "php" else prog.title()

    for code in code_pieces:
        if _INLINE_EXEC_RE.search(code) and _PY_LAUNCHER_RE.search(code):
            return (
                f"R2 direct model launch via {prog_title} denied: "
                f"\"{_snippet(statement)}\". "
                f"Reach the model only through {_ROUTER}."
            )
        # Mentioning the override/guard machinery is denied on its own: inline
        # code that even references it is presumed tampering (R2-1).
        if _PY_SPECIAL_STRINGS_RE.search(code):
            return (
                f"R3 guarded-path mutation via {prog_title} denied (heuristic speed bump): "
                f"\"{_snippet(statement)}\". "
                f"Send the change through {_ROUTER}."
            )
        if _INLINE_WRITE_RE.search(code):
            if _SOURCE_EXT_STR_RE.search(code):
                return (
                    f"R3 source-file mutation via {prog_title} denied (heuristic speed bump): "
                    f"\"{_snippet(statement)}\". "
                    f"Send the change through {_ROUTER}."
                )
            for literal in re.findall(r"['\"]([^'\"]+)['\"]", code):
                if _is_guarded(literal, effective_cwd, env):
                    return (
                        f"R3 guarded-path mutation via {prog_title} denied (heuristic speed bump): "
                        f"\"{_snippet(statement)}\". "
                        f"Send the change through {_ROUTER}."
                    )
                if _is_source_target(literal, effective_cwd, env):
                    return (
                        f"R3 source-file mutation via {prog_title} denied (heuristic speed bump): "
                        f"\"{_snippet(statement)}\". "
                        f"Send the change through {_ROUTER}."
                    )

    return None


def _python_check(
    statement: str,
    parsed: _Cmd,
    effective_cwd: str,
    env: Mapping[str, str] | None,
) -> str | None:
    return _inline_code_check(statement, parsed, effective_cwd, env)


def _git_check(
    statement: str,
    parsed: _Cmd,
    banned_git_aliases: set[str] | None = None,
) -> str | None:
    if banned_git_aliases is None:
        banned_git_aliases = set()
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

    # "git config" writing alias.* or core.* is denied; aliases registered in
    # this command are remembered so later "git <alias>" statements are denied.
    if _git_subcommand(parsed) == "config":
        positionals = _git_config_positionals(args)
        if positionals:
            key = positionals[0].lower()
            if key.startswith("alias.") or key.startswith("core."):
                if len(positionals) >= 2:
                    if key.startswith("alias."):
                        banned_git_aliases.add(key[len("alias."):].strip())
                    return _git_config_reason(statement)
    return None


def _git_subcommand(parsed: _Cmd) -> str | None:
    i = 0
    args = parsed.args
    while i < len(args):
        arg = args[i]
        if arg in _GIT_VALUE_FLAGS:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        return arg.lower()
    return None


def _git_config_positionals(args: list[str]) -> list[str]:
    start = -1
    for i, arg in enumerate(args):
        if arg.lower() == "config":
            start = i + 1
            break
    if start < 0:
        return []
    positionals: list[str] = []
    i = start
    while i < len(args):
        arg = args[i]
        if arg in {"-f", "--file"}:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        positionals.append(arg)
        i += 1
    return positionals


def _git_supervisor_read_check(
    statement: str,
    parsed: _Cmd,
    effective_cwd: str,
    env: Mapping[str, str] | None,
) -> str | None:
    sub = _git_subcommand(parsed)
    if sub is None or sub not in _GIT_READ_SUBS:
        return None
    args = parsed.args
    if sub == "log":
        patchlike = any(
            a in {"-p", "-u", "--patch"} or a.lower().startswith("--patch")
            for a in args
        )
        if not patchlike:
            return None
    if sub == "cat-file" and "-p" not in args:
        return None
    for target in args:
        if not isinstance(target, str) or target.startswith("-"):
            continue
        candidates = [target]
        if ":" in target:
            candidates.append(target.split(":", 1)[1])
        for cand in candidates:
            if _is_non_allowlisted_source(cand, effective_cwd, env):
                return _supervisor_read_reason(statement)
    return None


def _git_mutation_check(
    statement: str,
    parsed: _Cmd,
    effective_cwd: str,
    env: Mapping[str, str] | None,
) -> str | None:
    sub = _git_subcommand(parsed)
    if sub is None or sub not in _GIT_MUTATE_SUBS:
        return None
    args = parsed.args
    if sub in {"apply", "am"}:
        # Patches can rewrite any source file wholesale; the argv cannot prove
        # otherwise, so fail closed for both tiers.
        return _git_mutation_reason(statement)
    if "--" in args:
        targets = args[args.index("--") + 1:]
    elif sub == "checkout":
        # Only the "checkout -- <path>" form carries paths.
        return None
    else:
        targets = args
    for target in targets:
        if not isinstance(target, str) or target.startswith("-"):
            continue
        if _is_source_target(target, effective_cwd, env):
            return _git_mutation_reason(statement)
    return None


def _is_direct(parsed: _Cmd) -> bool:
    program = parsed.program
    if program in _DIRECT:
        return True
    if program == "claude":
        return "-p" in parsed.args or "--print" in parsed.args
    return _SCRIPT_RE.fullmatch(program) is not None


def _is_router(parsed: _Cmd, cwd: str = "") -> bool:
    if parsed.program != "dispatch.py" or not parsed.args:
        return False
    first = parsed.args[0].lower()
    if not (first in _ROUTER_CMDS or first.endswith(".md")):
        return False
    raw = next((w for w in parsed.words if _basename(w) == "dispatch.py"), None)
    if raw is None:
        return False
    folded = raw.replace("\\", "/").lower()
    if folded == _ROUTER_CANONICAL or "/_shared/dispatch/" in folded:
        return True
    if not folded.endswith("/dispatch/dispatch.py"):
        return False
    # Worktree form: only a dispatch.py inside a "dispatch/" directory of a
    # tracked git repository is the router, never a scratch path.
    try:
        resolved = _canonical_path(raw, cwd or os.getcwd())
    except Exception:
        return False
    return _in_tracked_repo(resolved)


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


def _supervisor_read_check(
    statement: str,
    parsed: _Cmd,
    effective_cwd: str,
    env: Mapping[str, str] | None,
) -> str | None:
    # Check input redirections
    for r in parsed.input_redirs:
        if _is_non_allowlisted_source(r, effective_cwd, env) or _is_non_allowlisted_dir(r, effective_cwd, env):
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
        if _is_non_allowlisted_source(t, effective_cwd, env) or _is_non_allowlisted_dir(t, effective_cwd, env):
            return _supervisor_read_reason(statement)
    return None


def _is_non_allowlisted_source(
    path: str, cwd: str, env: Mapping[str, str] | None,
) -> bool:
    if is_allowlisted_read(path, env=env, cwd=cwd):
        return False
    if is_scratch_root_path(path, env=env, cwd=cwd):
        return False
    try:
        resolved = _canonical_path(path, cwd)
        if is_allowlisted_read(str(resolved), env=env, cwd=cwd):
            return False
        if is_scratch_root_path(str(resolved), env=env, cwd=cwd):
            return False
        if is_source_path(str(resolved)) or is_source_path(path):
            return True
    except Exception:
        if is_source_path(path):
            return True
    return False


def _is_non_allowlisted_dir(
    path: str, cwd: str, env: Mapping[str, str] | None,
) -> bool:
    if is_allowlisted_read(path, env=env, cwd=cwd):
        return False
    if is_scratch_root_path(path, env=env, cwd=cwd):
        return False
    try:
        resolved = _canonical_path(path, cwd)
        if is_allowlisted_read(str(resolved), env=env, cwd=cwd):
            return False
        if is_scratch_root_path(str(resolved), env=env, cwd=cwd):
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


def _in_tracked_repo(resolved: Path) -> bool:
    try:
        for parent in resolved.parents:
            if (parent / ".git").exists():
                return True
    except OSError:
        return False
    return False


def _script_operand_reason(
    operand: str,
    statement: str,
    cwd: str,
    env: Mapping[str, str] | None,
) -> str | None:
    cleaned = operand.strip().strip("'\"")
    if not cleaned:
        return None
    if "*" in cleaned or "?" in cleaned:
        return _script_operand_deny(statement, operand)
    if is_scratch_root_path(cleaned, env=env, cwd=cwd):
        return _script_operand_deny(statement, operand)
    try:
        resolved = _canonical_path(cleaned, cwd)
    except Exception:
        return _script_operand_deny(statement, operand)
    if not _in_tracked_repo(resolved):
        return _script_operand_deny(statement, operand)
    return None


def _posix_shell_operand(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if arg in _POSIX_SHELL_VALUE_FLAGS:
            i += 2
            continue
        if arg.startswith("--"):
            i += 1
            continue
        if arg.startswith("-") and len(arg) > 1:
            if "c" in arg[1:]:
                return None
            i += 1
            continue
        return arg
    return None


def _ps_shell_operand(args: list[str]) -> str | None:
    i = 0
    while i < len(args):
        arg = args[i]
        low = arg.lower()
        if _is_ps_encoded_flag(arg):
            if ":" not in arg and "=" not in arg and i + 1 < len(args):
                i += 2
            else:
                i += 1
            continue
        if low == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if low in {"-file", "-f", "--file"}:
            return args[i + 1] if i + 1 < len(args) else None
        if low.startswith("-file:") or low.startswith("-f:"):
            return arg.split(":", 1)[1]
        if low in _PS_SHELL_VALUE_FLAGS:
            i += 2
            continue
        if low.startswith("-") or low.startswith("/"):
            i += 1
            continue
        return arg
    return None


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


def _is_source_target(
    path: str, cwd: str, env: Mapping[str, str] | None,
) -> bool:
    cleaned = path.strip().strip("'\"")
    if is_scratch_root_path(cleaned, env=env, cwd=cwd):
        return False
    if _has_denied_write_ext(cleaned):
        return True
    if "*" in cleaned or "?" in cleaned:
        folded = cleaned.lower()
        if any(folded.endswith(ext) for ext in _DENIED_WRITE_EXTS):
            return True
        if cleaned.endswith("*") or cleaned.endswith("/*") or cleaned.endswith(r"\*"):
            return True
    return False


def _has_denied_write_ext(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.endswith(_DENIED_WRITE_EXTS)


def _write_kind(path: str, cwd: str, env: Mapping[str, str] | None) -> str | None:
    if _is_guarded(path, cwd, env):
        return "guarded"
    if _is_source_target(path, cwd, env):
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
            if wrapper in {"exec", "command"} and word in {"-a"} and index < len(words):
                index += 1
            continue
        if wrapper in {"start", "call"} and word.startswith("/"):
            index += 1
            continue
        break
    return index


def _normalize_exe(token: str) -> str:
    cleaned = token.strip().strip("'\"")
    if cleaned.startswith("$'") and cleaned.endswith("'"):
        cleaned = cleaned[2:-1]
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
        if ch == "$" and index + 1 < length and text[index + 1] == "'":
            index += 2
            while index < length and text[index] != "'":
                if text[index] == "\\" and index + 1 < length:
                    nxt = text[index + 1]
                    if nxt == "n":
                        parts.append("\n")
                        index += 2
                    elif nxt == "r":
                        parts.append("\r")
                        index += 2
                    elif nxt == "t":
                        parts.append("\t")
                        index += 2
                    elif nxt == "a":
                        parts.append("\a")
                        index += 2
                    elif nxt == "b":
                        parts.append("\b")
                        index += 2
                    elif nxt == "f":
                        parts.append("\f")
                        index += 2
                    elif nxt == "v":
                        parts.append("\v")
                        index += 2
                    elif nxt in {"e", "E"}:
                        parts.append("\x1b")
                        index += 2
                    elif nxt in "'\"\\":
                        parts.append(nxt)
                        index += 2
                    elif nxt == "x" and index + 3 < length:
                        hex_str = text[index + 2:index + 4]
                        try:
                            parts.append(chr(int(hex_str, 16)))
                            index += 4
                        except ValueError:
                            parts.append(nxt)
                            index += 2
                    elif nxt in "01234567":
                        oct_digits = ""
                        j = index + 1
                        while j < length and j < index + 4 and text[j] in "01234567":
                            oct_digits += text[j]
                            j += 1
                        parts.append(chr(int(oct_digits, 8)))
                        index = j
                    else:
                        parts.append(nxt)
                        index += 2
                    continue
                parts.append(text[index])
                index += 1
            if index < length and text[index] == "'":
                index += 1
            continue
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
    in_ansi = False
    escaped = False

    while index < length:
        ch = command[index]
        if escaped:
            out.append(ch)
            escaped = False
            index += 1
            continue
        if in_ansi:
            out.append(ch)
            if ch == "\\" and index + 1 < length:
                out.append(command[index + 1])
                index += 2
                continue
            if ch == "'":
                in_ansi = False
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
        if ch == "$" and index + 1 < length and command[index + 1] == "'":
            in_ansi = True
            out.append(ch)
            out.append("'")
            index += 2
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


def _git_alias_reason(statement: str) -> str:
    return (
        f"R2 git alias registered in this command denied: \"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _git_mutation_reason(statement: str) -> str:
    return (
        f"R3 source mutation via git denied: \"{_snippet(statement)}\". "
        f"Send the change through {_ROUTER}."
    )


def _substitution_reason(statement: str) -> str:
    return (
        "R2 unbalanced command substitution in the program word denied: "
        f"\"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _stdin_shell_reason(statement: str) -> str:
    return (
        "R2 stdin-fed shell denied (no -c/-Command and no tracked script operand): "
        f"\"{_snippet(statement)}\". "
        f"Reach the model only through {_ROUTER}."
    )


def _script_operand_deny(statement: str, operand: str) -> str:
    return (
        "R2 shell script execution denied: scripts must live in a tracked git "
        f"repository outside scratch/tmp roots: \"{_snippet(operand)}\" in "
        f"\"{_snippet(statement)}\". Reach the model only through {_ROUTER}."
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
