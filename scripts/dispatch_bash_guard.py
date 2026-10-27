#!/usr/bin/env python3
"""PreToolUse guard for Bash and PowerShell (rules R2 and R3).

Models are reachable only through ``python D:/APPS/_shared/dispatch/dispatch.py``.
Direct launches of codex, glm, kimi, cursor-agent, agy, opencode, claude -p/--print,
and the CDP/audit scripts are denied. Bash and PowerShell may not write guarded
paths or source files. decide() is pure. main() prints one JSON object or nothing.

Importing this module creates no files.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_guard_common import (  # noqa: E402 - sibling import, same pattern as other hooks
    GUARDED_PATH_PATTERNS,
    deny,
    is_source_path,
    lane_repair_job_exists,
    norm_path,
    override_active,
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
_DEST_CMDS = frozenset({"cp", "mv", "copy", "move", "copy-item", "move-item"})
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
    r"^(?:cdp_.*\.py|auditgpt\.py|coderpx\.py|perplexity_audit\.py)$",
    re.IGNORECASE,
)
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_REDIR_RE = re.compile(r"(\d*)(>>|>)")


class _Cmd(NamedTuple):
    program: str
    args: list[str]
    words: list[str]
    redirs: list[str]


def split_statements(command: str) -> list[str]:
    """Split a Bash or PowerShell command into statements.

    Heredoc bodies (``<<EOF``, ``<<'EOF'``, ``<<-EOF``) and PowerShell
    here-strings (``@'...'@``, ``@"..."@``) are removed first. Separators are
    newlines, ``;``, ``&&``, ``||``, ``|``, and a lone ``&``. A separator
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
        piece = "".join(buf).strip()
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
    for statement in split_statements(command):
        reason = _statement_reason(statement, env)
        if reason is not None:
            return deny(reason)
    return None


def main() -> int:
    """Read one hook payload from stdin and apply decide() under run_guarded."""

    def _from_stdin() -> dict | None:
        return decide(read_payload())

    return run_guarded(_HOOK_FILE, _from_stdin)


def _statement_reason(statement: str, env: Mapping[str, str] | None) -> str | None:
    parsed = _parse(statement)
    if not _is_router(parsed) and _is_direct(parsed) and not _introspects(parsed):
        job_id = _repair_job(parsed.args)
        if job_id is None:
            return _launch_reason(statement)
        if not lane_repair_job_exists(job_id, env):
            return _unknown_job_reason(statement, job_id)
    if parsed.program == "git":
        return None
    for path in _write_paths(parsed):
        kind = _write_kind(path)
        if kind is not None:
            return _mutate_reason(statement, kind)
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
    for word in parsed.words:
        flag = word.split("=", 1)[0] if word.startswith("--") else word
        if flag in _INTROSPECTION:
            return True
    return False


def _repair_job(args: list[str]) -> str | None:
    for index, arg in enumerate(args):
        if arg == "--lane-repair":
            if index + 1 < len(args):
                return args[index + 1]
            return ""
        if arg.startswith("--lane-repair="):
            return arg.split("=", 1)[1]
    return None


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


def _mutate_reason(statement: str, kind: str) -> str:
    if kind == "guarded":
        name = "R3 guarded-path mutation denied"
    else:
        name = "R3 source-file mutation denied"
    return f"{name}: \"{_snippet(statement)}\". Send the change through {_ROUTER}."


def _snippet(statement: str) -> str:
    flat = statement.strip().replace("\r\n", "\n").replace("\n", " ")
    return flat[:160]


def _write_kind(path: str) -> str | None:
    if _is_guarded(path):
        return "guarded"
    if is_source_path(path) and not _under_scratch_or_tmp(path):
        return "source"
    return None


def _is_guarded(path: str) -> bool:
    try:
        normalized = norm_path(path)
    except (OSError, ValueError):
        normalized = path
    for candidate in (path, normalized):
        folded = candidate.replace("\\", "/")
        if any(pattern.search(folded) for pattern in GUARDED_PATH_PATTERNS):
            return True
    return False


def _under_scratch_or_tmp(path: str) -> bool:
    try:
        normal = norm_path(path).replace("\\", "/").lower()
    except (OSError, ValueError):
        normal = path.replace("\\", "/").lower()
    return "/scratchpad/" in normal or "/tmp/" in normal


def _write_paths(parsed: _Cmd) -> list[str]:
    if parsed.program == "git":
        return []
    paths = list(parsed.redirs)
    program = parsed.program
    if program == "sed":
        paths.extend(_sed_files(parsed.args))
    elif program == "tee":
        paths.extend(_collect(parsed.args, "tee"))
    elif program in _DEST_CMDS:
        paths.extend(_collect(parsed.args, "dest"))
    elif program in _WRITE_CMDS:
        paths.extend(_collect(parsed.args, "all"))
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


def _collect(args: list[str], mode: str) -> list[str]:
    found: list[str] = []
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positional.extend(args[index + 1:])
            break
        name, inline = _opt(arg)
        if name is not None:
            takes_value = name in _VALUE_OPTS or name in _DEST_OPTS or name in _PATH_OPTS
            value = inline
            if takes_value and value is None and index + 1 < len(args):
                value = args[index + 1]
                index += 1
            if value is not None and (
                (mode == "dest" and name in _DEST_OPTS)
                or (mode == "all" and name in _PATH_OPTS)
            ):
                found.append(value)
            index += 1
            continue
        positional.append(arg)
        index += 1
    if mode == "dest":
        if positional:
            found.append(positional[-1])
    elif mode in {"all", "tee"}:
        found.extend(positional)
    return found


def _parse(statement: str) -> _Cmd:
    words: list[str] = []
    redirs: list[str] = []
    for kind, text in _lex(statement):
        if kind == "write":
            redirs.append(text)
        elif text:
            words.append(text)
    program, arg_at = _head(words)
    return _Cmd(program, words[arg_at:], words, redirs)


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
        if low in {"cd", "pushd"}:
            return "", total
        if low == "start-process":
            exe, index = _start_exe(words, index + 1)
            if not exe:
                return "", total
            return _normalize_exe(exe), index
        if low in _WRAPPERS:
            index = _skip_wrapper(words, index + 1, low)
            continue
        if low in _PYTHON:
            script_at = _first_positional(words, index + 1)
            if script_at is None:
                return low, index + 1
            return _basename(words[script_at]), script_at + 1
        return low, index + 1
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


def _start_exe(words: list[str], index: int) -> tuple[str, int]:
    while index < len(words):
        name, inline = _opt(words[index])
        if name in {"-filepath", "-filename"}:
            if inline is not None:
                return inline, index + 1
            if index + 1 < len(words):
                return words[index + 1], index + 2
            return "", len(words)
        if name is not None:
            index += 1
            continue
        return words[index], index + 1
    return "", len(words)


def _first_positional(words: list[str], index: int) -> int | None:
    while index < len(words):
        word = words[index]
        if _ASSIGN_RE.match(word):
            index += 1
            continue
        if word == "--":
            index += 1
            return index if index < len(words) else None
        if word.startswith("-"):
            index += 1
            continue
        return index
    return None


def _normalize_exe(token: str) -> str:
    if token == "&":
        return "&"
    base = _basename(token)
    for ext in _STRIP_EXT:
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


def _basename(token: str) -> str:
    return token.replace("\\", "/").rsplit("/", 1)[-1].lower()


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
            if kind == "write" and value:
                tokens.append(("write", value))
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
    if write and target:
        return ("write", target, new_index)
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
            parts.append(text[index + 1])
            index += 2
            continue
        if ch in " \t\r\n<>|&;":
            break
        parts.append(ch)
        index += 1
    return "".join(parts), index


def _strip_bodies(command: str) -> str:
    """Drop heredoc and here-string bodies. Leave the operators in place."""
    out: list[str] = []
    index = 0
    length = len(command)
    pending: list[tuple[str, bool]] = []
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
            index = _consume_heredoc(command, index, pending.pop(0))
            out.append("\n")
            continue
        if ch == "\r":
            index += 1
            continue
        if command.startswith("<<", index):
            parsed = _parse_heredoc_op(command, index)
            if parsed is not None:
                delim, strip_tabs, op_end = parsed
                out.append(command[index:op_end])
                pending.append((delim, strip_tabs))
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


def _consume_heredoc(text: str, index: int, spec: tuple[str, bool]) -> int:
    delim, strip_tabs = spec
    index = _skip_newline(text, index)
    while index < len(text):
        line, nxt = _take_line(text, index)
        check = line.lstrip("\t") if strip_tabs else line
        if check == delim:
            return nxt
        index = nxt
    return len(text)


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


if __name__ == "__main__":
    raise SystemExit(main())
