#!/usr/bin/env python3
"""PreToolUse guard for Agent, Task, and start_session spawns (rule R1).

An Agent, Task, or mcp__ccd_session__start_session call is allowed only when
every check below passes. decide() is pure: it returns a deny object or None
and does not print. main() reads one UTF-8 JSON payload from stdin (via
dispatch_guard_common.read_payload, which uses hook_stdio) and prints either
that one object or nothing.

Checks, in order:

1. override_active("workers") allows the call. A hooks_off token counts,
   because that scope lifts every rule. A plain allow_claude_workers file
   does not.
2. is_tier2 denies. A subagent (non-empty agent_id), a session marked by
   dispatch_tier_marker, or DISPATCH_GUARD_TIER=tier2 cannot spawn further
   agents or sessions. DISPATCH_GUARD_TIER=supervisor forces the supervisor
   path. Max depth is 1.
3. tool_input.model must be a non-empty string. Lowercased, it must not
   contain "opus" or "fable", and it must contain "sonnet" or "haiku".
4. The brief must contain both "tier-2 coordinator" and a lane/lanes word.
   The brief is tool_input.prompt, plus tool_input.background when the tool
   is mcp__ccd_session__start_session. Matching is case-insensitive after
   whitespace is collapsed to single spaces.
5. Every deny reason ends with a corrected-call hint: the same tool_input
   as compact JSON, model set to "sonnet", coordinator line prepended to
   the prompt.

Fail closed: a crash or an unreadable payload becomes a deny naming this
file. Importing this module creates no files and writes nothing.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dispatch_guard_common import (  # noqa: E402 - sibling import, same pattern as other scripts
    COORDINATOR_LINE,
    deny,
    is_tier2,
    override_active,
    read_payload,
    run_guarded,
)

HOOK_FILE = "claude_worker_guard.py"
_START_SESSION = "mcp__ccd_session__start_session"
_DEPTH_REASON = (
    "max agent depth is 1: a Tier-2 coordinator cannot spawn agents or sessions; "
    "send the work to `python D:/APPS/_shared/dispatch/dispatch.py lane <role> --brief FILE`"
)
_TIER2_MARK = re.compile(r"tier-2 coordinator", re.IGNORECASE)
_LANE_MARK = re.compile(r"\blanes?\b", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")


def decide(payload: dict, env: Mapping[str, str] | None = None) -> dict | None:
    """Return a PreToolUse deny object, or None when the spawn may proceed."""
    if override_active("workers", env):
        return None
    tool_input = _tool_input(payload)
    if is_tier2(payload, env):
        return _deny(_DEPTH_REASON, tool_input)
    model_reason = _model_reason(tool_input.get("model"))
    if model_reason is not None:
        return _deny(model_reason, tool_input)
    if not _brief_ok(payload, tool_input):
        return _deny(
            "brief must contain the Tier-2 coordinator contract "
            "(tier-2 coordinator and a lane)",
            tool_input,
        )
    return None


def main() -> int:
    """Read one hook payload from stdin and apply decide() under run_guarded."""

    def _from_stdin() -> dict | None:
        return decide(read_payload())

    return run_guarded(HOOK_FILE, _from_stdin)


def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input")
    if isinstance(raw, dict):
        return raw
    return {}


def _model_reason(model: object) -> str | None:
    if not isinstance(model, str) or not model.strip():
        return "model is missing or empty; an explicit sonnet or haiku model is required"
    folded = model.lower()
    if "opus" in folded or "fable" in folded:
        return f"model {model!r} is denied; opus and fable are not allowed"
    if "sonnet" not in folded and "haiku" not in folded:
        return f"model {model!r} is denied; the model must contain sonnet or haiku"
    return None


def _brief_ok(payload: dict, tool_input: dict) -> bool:
    collapsed = _WHITESPACE.sub(" ", _brief_text(payload, tool_input)).strip()
    return (
        _TIER2_MARK.search(collapsed) is not None
        and _LANE_MARK.search(collapsed) is not None
    )


def _brief_text(payload: dict, tool_input: dict) -> str:
    parts: list[str] = []
    prompt = tool_input.get("prompt")
    if isinstance(prompt, str):
        parts.append(prompt)
    if payload.get("tool_name") == _START_SESSION:
        background = tool_input.get("background")
        if isinstance(background, str):
            parts.append(background)
    return "\n".join(parts)


def _deny(reason: str, tool_input: dict) -> dict:
    hint = json.dumps(_corrected_call(tool_input), separators=(",", ":"), ensure_ascii=False)
    return deny(f"{reason}. Corrected call: {hint}")


def _corrected_call(tool_input: dict) -> dict:
    """Same tool_input, model forced to sonnet, coordinator line prepended."""
    corrected = dict(tool_input)
    prompt = corrected.get("prompt")
    body = prompt if isinstance(prompt, str) else ""
    corrected["model"] = "sonnet"
    corrected["prompt"] = f"{COORDINATOR_LINE}\n{body}" if body else COORDINATOR_LINE
    return corrected


if __name__ == "__main__":
    raise SystemExit(main())
