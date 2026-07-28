#!/usr/bin/env python3
"""Translate Codex lifecycle events into the shared advisory session engine."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import session_lifecycle
import session_router
from session_state import (
    append_hook_error,
    read_session_binding,
    validate_session_id,
)

_CODEX_UNIVERSAL_OUTPUT_TYPES = {
    "continue": bool,
    "stopReason": str,
    "suppressOutput": bool,
    "systemMessage": str,
}


def _codex_session_start_output(shared_output: object) -> dict[str, Any]:
    if not isinstance(shared_output, dict):
        return {}
    output = {
        key: shared_output[key]
        for key, expected_type in _CODEX_UNIVERSAL_OUTPUT_TYPES.items()
        if isinstance(shared_output.get(key), expected_type)
    }
    shared_specific = shared_output.get("hookSpecificOutput")
    if not isinstance(shared_specific, dict):
        return output
    specific: dict[str, Any] = {"hookEventName": "SessionStart"}
    additional_context = shared_specific.get("additionalContext")
    if isinstance(additional_context, str):
        specific["additionalContext"] = additional_context
    output["hookSpecificOutput"] = specific
    return output


def handle_event(
    event: dict[str, Any],
    *,
    registry_path: Path | None = None,
    state_dir: Path | None = None,
) -> dict[str, Any]:
    """Handle one Codex hook event without blocking the host on bad input."""

    try:
        if event.get("hook_event_name") == "SessionStart":
            if not event.get("transcript_path"):
                return {}
            return _codex_session_start_output(
                session_router.handle_event(
                    event,
                    registry_path=registry_path,
                    state_dir=state_dir,
                )
            )
        if event.get("hook_event_name") == "SessionEnd":
            delegated_event = event
            if not event.get("transcript_path"):
                try:
                    session_id = validate_session_id(event.get("session_id"))
                except (TypeError, ValueError):
                    append_hook_error(
                        "CODEX_ADAPTER_INVALID_SESSION_ID",
                        "ValueError",
                        state_dir=state_dir,
                    )
                    return {}
                binding = read_session_binding(
                    session_id,
                    state_dir=state_dir,
                )
                if binding is None:
                    append_hook_error(
                        "CODEX_ADAPTER_END_WITHOUT_BINDING",
                        str(event.get("session_id") or ""),
                        state_dir=state_dir,
                    )
                    return {}
                delegated_event = dict(event)
                delegated_event["transcript_path"] = binding["transcript_path"]
            session_lifecycle.handle_event(
                delegated_event,
                registry_path=registry_path,
                state_dir=state_dir,
            )
        return {}
    except Exception as exc:  # noqa: BLE001 - host lifecycle hooks must fail open
        append_hook_error(
            "CODEX_ADAPTER_DELEGATE_FAILED",
            type(exc).__name__,
            state_dir=state_dir,
        )
        return {}


def main() -> int:
    try:
        raw = sys.stdin.read()
        parsed = json.loads(raw) if raw.strip() else {}
        event = parsed if isinstance(parsed, dict) else {}
    except (OSError, json.JSONDecodeError):
        event = {}
    output = handle_event(event)
    if event.get("hook_event_name") == "SessionStart":
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
