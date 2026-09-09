#!/usr/bin/env python3
"""UTF-8 stdin for hook and adapter entry points.

Every host in this ecosystem — Claude Code, Codex, Cursor — hands a hook its
event as UTF-8 JSON on stdin. Python does not read it that way by default on
Windows: `sys.stdin` arrives as cp1252 with `errors="surrogateescape"`, so a
UTF-8 payload never raises. It mojibakes.

Measured on the operator's box (audit 2026-09-09, P1-14):

    sys.stdin.encoding == "cp1252"
    "nowy modul".encode("utf-8").decode("cp1252")  ->  "nowy moduA,"

which is why half the documented Polish triggers in the global CLAUDE.md never
fired, and why a non-ASCII `tool_input.file_path` failed `Path.exists()` and was
silently skipped. There was no diagnostic for either: the hooks fail open by
contract, so a corrupted payload looks exactly like "nothing to do".

Deliberately dependency-free and side-effect-free at import: these run inside
the operator's live sessions, so this module must not be able to break one.
"""

from __future__ import annotations

import sys


def read_stdin_text() -> str:
    """Return stdin decoded as UTF-8, whatever the console codepage claims.

    Falls back to the text stream when `.buffer` is unavailable — a test that
    replaces `sys.stdin` with `io.StringIO` has already decoded for us, and a
    host that hands us a text stream directly is not a reason to raise inside a
    hook. Undecodable bytes are replaced rather than raising, for the same
    reason: a hook that dies is worse than a hook that sees one bad character.
    """
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        return sys.stdin.read()
    return buffer.read().decode("utf-8", errors="replace")
