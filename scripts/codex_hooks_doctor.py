"""Death-detector for the Codex ecosystem hook block (~/.codex/hooks.json).

Codex hooks are wired by install_codex_session_lifecycle.py (SessionStart/SessionEnd
handlers that invoke codex_session_adapter.py through a base64 -EncodedCommand PowerShell
wrapper). Nothing detected when that block went absent or drifted -- the same silent-death
gap closed for Claude in scripts/hooks_install.py. This module is read-only detection only;
it never writes ~/.codex/hooks.json (install_codex_session_lifecycle.py owns wiring).

Detection is content-based and decode-based: it confirms each required event has a handler
whose command references codex_session_adapter.py (decoding the -EncodedCommand when present),
so it is robust to interpreter/path/sha differences and does not couple to the installer's
manifest location. Every verdict is scoped to ~/.codex/hooks.json and refers the operator to
the Codex installer -- it never claims a hook is absent from the running Codex configuration.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

ADAPTER = "codex_session_adapter.py"
REQUIRED_EVENTS = ("SessionStart", "SessionEnd")
_ENC_RE = re.compile(r"-Enc(?:odedCommand)?\s+([A-Za-z0-9+/=]{8,})", re.IGNORECASE)

# Verdicts that mean the Codex block is absent/broken on a host where Codex is deployed.
_BLOCK_INVALIDATING = frozenset({"MISSING", "NEVER_INSTALLED", "MALFORMED"})


def _references_adapter(command: object) -> bool:
    if not isinstance(command, str) or not command:
        return False
    if ADAPTER in command:
        return True  # plain (non-encoded) command
    m = _ENC_RE.search(command)
    if not m:
        return False
    try:
        decoded = base64.b64decode(m.group(1)).decode("utf-16-le", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return False
    return ADAPTER in decoded


def _event_has_adapter(hooks: dict, event: str) -> bool:
    for group in hooks.get(event, []) or []:
        if not isinstance(group, dict):
            continue
        for handler in group.get("hooks", []) or []:
            if not isinstance(handler, dict):
                continue
            if _references_adapter(handler.get("command")) or \
               _references_adapter(handler.get("commandWindows")):
                return True
    return False


def codex_hooks_status(home: Path) -> tuple[str, str]:
    """Return (verdict, detail). Verdicts: NOT_DEPLOYED (no ~/.codex -> skip), NEVER_INSTALLED
    (Codex present but no hooks file), MALFORMED (unparseable hooks.json), MISSING (a required
    event lacks the adapter handler), OK."""
    codex_dir = home / ".codex"
    if not codex_dir.exists():
        return ("NOT_DEPLOYED", "no ~/.codex on this host")
    hooks_path = codex_dir / "hooks.json"
    if not hooks_path.exists():
        return ("NEVER_INSTALLED", "~/.codex present but hooks.json is absent")
    try:
        raw = json.loads(hooks_path.read_bytes())
    except (json.JSONDecodeError, OSError) as exc:
        return ("MALFORMED", f"~/.codex/hooks.json unreadable: {exc}")
    hooks = raw.get("hooks") if isinstance(raw, dict) else None
    if not isinstance(hooks, dict):
        return ("MALFORMED", "~/.codex/hooks.json has no hooks object")
    missing = [e for e in REQUIRED_EVENTS if not _event_has_adapter(hooks, e)]
    if missing:
        return ("MISSING", f"required event(s) lack the {ADAPTER} handler: {', '.join(missing)}")
    return ("OK", "")


def block_invalidated(verdict: str) -> bool:
    return verdict in _BLOCK_INVALIDATING


def deployed(home: Path) -> bool:
    return (home / ".codex").exists()
