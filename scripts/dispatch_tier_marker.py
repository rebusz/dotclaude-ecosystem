#!/usr/bin/env python3
"""UserPromptSubmit hook: mark a session as Tier-2 from its first prompt.

A Tier-2 started through start_session has no agent_id on later hook payloads.
The first prompt carries the coordinator line. When the normalised prompt
contains "tier-2 coordinator", the session id is recorded so later hooks treat
that session as Tier-2. This hook never denies: it only adds a marker. A bad
payload or a write failure is logged to stderr and the process exits 0.
Importing this module creates no files.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping

from dispatch_guard_common import mark_tier2_session, read_payload, run_guarded

HOOK_FILE = "dispatch_tier_marker.py"
_TIER2_MARK = re.compile(r"tier-2 coordinator", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def decide(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """Mark session_id when the normalised prompt contains the coordinator line.

    Normalisation collapses whitespace and matches case-insensitively. Always
    returns None. Marker failures are logged to stderr.
    """
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return None
    normalised = _WHITESPACE.sub(" ", prompt).strip()
    if _TIER2_MARK.search(normalised) is None:
        return None
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        _log(ValueError("session_id must be a non-empty string"))
        return None
    try:
        mark_tier2_session(session_id, env)
    except Exception as exc:
        _log(exc)
    return None


def main() -> int:
    """Read one UserPromptSubmit payload and mark it inside run_guarded."""

    def _from_stdin() -> dict | None:
        try:
            return decide(read_payload())
        except Exception as exc:
            _log(exc)
            return None

    return run_guarded(HOOK_FILE, _from_stdin, "UserPromptSubmit")


def _log(exc: BaseException) -> None:
    print(f"{HOOK_FILE}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
