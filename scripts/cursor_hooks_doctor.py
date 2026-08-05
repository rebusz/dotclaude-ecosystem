"""Death-detector for the Cursor ecosystem hook block (~/.cursor/hooks.json).

Cursor hooks are wired by install_cursor_session_lifecycle.py (CU3) -- sessionStart
and sessionEnd handlers that invoke cursor_session_adapter.py directly (no shell
wrapping; Cursor's hooks.json has no documented commandWindows field). Nothing
detected when that block went absent or drifted -- the same silent-death gap closed
for Claude (scripts/hooks_install.py) and Codex (scripts/codex_hooks_doctor.py).
This module is read-only detection only; it never writes ~/.cursor/hooks.json.

Detection is content-based: it confirms each required event has a handler whose
command references cursor_session_adapter.py directly (a plain substring check --
Cursor's documented schema uses `command` as a literal shell command string, not an
encoded wrapper). Every verdict is scoped to ~/.cursor/hooks.json and refers the
operator to the installer -- it never claims a hook is absent from the running
Cursor configuration (which, per
design/plans/2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md, is `UNPROVEN`
for the IDE surface and `preCompact`; this detector covers only the CLI-proven
sessionStart/sessionEnd wiring, matching CU3's deliberately narrow scope).
"""

from __future__ import annotations

import json
from pathlib import Path

ADAPTER = "cursor_session_adapter.py"
REQUIRED_EVENTS = ("sessionStart", "sessionEnd")

_BLOCK_INVALIDATING = frozenset({"MISSING", "NEVER_INSTALLED", "MALFORMED"})


def _references_adapter(command: object) -> bool:
    return isinstance(command, str) and ADAPTER in command


def _event_has_adapter(hooks: dict, event: str) -> bool:
    for handler in hooks.get(event, []) or []:
        if isinstance(handler, dict) and _references_adapter(handler.get("command")):
            return True
    return False


def cursor_hooks_status(home: Path) -> tuple[str, str]:
    """Return (verdict, detail). Verdicts: NOT_DEPLOYED (no ~/.cursor -> skip),
    NEVER_INSTALLED (Cursor present but no hooks.json), MALFORMED (unparseable or
    wrong version), MISSING (a required event lacks the adapter handler), OK."""
    cursor_dir = home / ".cursor"
    if not cursor_dir.exists():
        return ("NOT_DEPLOYED", "no ~/.cursor on this host")
    hooks_path = cursor_dir / "hooks.json"
    if not hooks_path.exists():
        return ("NEVER_INSTALLED", "~/.cursor present but hooks.json is absent")
    try:
        raw = json.loads(hooks_path.read_bytes())
    except (json.JSONDecodeError, OSError) as exc:
        return ("MALFORMED", f"~/.cursor/hooks.json unreadable: {exc}")
    if not isinstance(raw, dict) or raw.get("version") != 1:
        return ("MALFORMED", "~/.cursor/hooks.json is missing or has an unsupported version")
    hooks = raw.get("hooks")
    if not isinstance(hooks, dict):
        return ("MALFORMED", "~/.cursor/hooks.json has no hooks object")
    missing = [e for e in REQUIRED_EVENTS if not _event_has_adapter(hooks, e)]
    if missing:
        return ("MISSING", f"required event(s) lack the {ADAPTER} handler: {', '.join(missing)}")
    return ("OK", "")


def block_invalidated(verdict: str) -> bool:
    return verdict in _BLOCK_INVALIDATING


def deployed(home: Path) -> bool:
    return (home / ".cursor").exists()
