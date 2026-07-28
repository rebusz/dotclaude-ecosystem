#!/usr/bin/env python3
"""Translate proven Cursor Agent CLI events into the shared lifecycle engine."""

from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import session_lifecycle
import session_router
from session_state import (
    RepositoryRegistration,
    append_hook_error,
    read_session_binding,
    resolve_repository,
    validate_session_id,
)

_CURSOR_CLI_VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}-[A-Za-z0-9]+$")
_CURSOR_CLI_NAMESPACE = uuid.UUID("e39bec12-74f1-4d77-94e5-4c71ceae7ac4")


def _cursor_session_id(conversation_id: object) -> str:
    native_id = validate_session_id(conversation_id)
    return str(uuid.uuid5(_CURSOR_CLI_NAMESPACE, native_id))


def _registered_workspace(
    event: dict[str, Any],
    *,
    registry_path: Path | None,
    state_dir: Path | None,
) -> RepositoryRegistration | None:
    roots = event.get("workspace_roots")
    if (
        not isinstance(roots, list)
        or len(roots) != 1
        or not isinstance(roots[0], str)
        or not roots[0].strip()
    ):
        return None
    root = Path(roots[0]).expanduser()
    if not root.is_absolute():
        return None
    normalized_root = root.resolve(strict=False)
    registration = resolve_repository(
        normalized_root,
        registry_path=registry_path,
        state_dir=state_dir,
    )
    if (
        registration is None
        or registration.worktree_root.resolve(strict=False) != normalized_root
    ):
        return None
    return registration


def _absolute_transcript(value: object) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid Cursor transcript path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Cursor transcript path must be absolute")
    return path.resolve(strict=False)


def _cursor_context(shared_output: object) -> dict[str, str]:
    if not isinstance(shared_output, dict):
        return {}
    specific = shared_output.get("hookSpecificOutput")
    if not isinstance(specific, dict):
        return {}
    context = specific.get("additionalContext")
    return {"additional_context": context} if isinstance(context, str) else {}


def _normalized_start(
    event: dict[str, Any],
    *,
    registration: RepositoryRegistration,
    session_id: str,
    transcript_path: Path,
    source: str,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "transcript_path": str(transcript_path),
        "cwd": str(registration.worktree_root.resolve(strict=False)),
        "hook_event_name": "SessionStart",
        "source": source,
        "model": event.get("model"),
    }


def _binding_matches(
    binding: dict[str, Any] | None,
    *,
    registration: RepositoryRegistration,
    session_id: str,
    transcript_path: Path,
) -> bool:
    if (
        binding is None
        or binding.get("session_id") != session_id
        or binding.get("repo") != registration.name
    ):
        return False
    try:
        return (
            Path(binding["worktree_root"]).resolve(strict=False)
            == registration.worktree_root.resolve(strict=False)
            and Path(binding["transcript_path"]).resolve(strict=False)
            == transcript_path
        )
    except (KeyError, OSError, RuntimeError, TypeError):
        return False


def handle_event(
    event: dict[str, Any],
    *,
    registry_path: Path | None = None,
    state_dir: Path | None = None,
) -> dict[str, str]:
    """Handle one Cursor CLI event and fail open on invalid host input."""

    try:
        if not isinstance(event, dict):
            raise TypeError("Cursor event must be an object")
        if not _CURSOR_CLI_VERSION_RE.fullmatch(str(event.get("cursor_version") or "")):
            append_hook_error(
                "CURSOR_ADAPTER_UNSUPPORTED_SURFACE",
                "noop",
                state_dir=state_dir,
            )
            return {}
        event_name = event.get("hook_event_name")
        if event_name not in {"sessionStart", "sessionEnd", "preCompact"}:
            return {}
        session_id = _cursor_session_id(event.get("conversation_id"))
        registration = _registered_workspace(
            event,
            registry_path=registry_path,
            state_dir=state_dir,
        )
        if registration is None:
            return {}
        if event_name == "preCompact":
            binding = read_session_binding(session_id, state_dir=state_dir)
            if binding is None:
                return {}
            bound_transcript = _absolute_transcript(binding.get("transcript_path"))
            if bound_transcript is None or not _binding_matches(
                binding,
                registration=registration,
                session_id=session_id,
                transcript_path=bound_transcript,
            ):
                return {}
            event_transcript = _absolute_transcript(event.get("transcript_path"))
            if event_transcript is not None and event_transcript != bound_transcript:
                return {}
            return _cursor_context(
                session_router.handle_event(
                    _normalized_start(
                        event,
                        registration=registration,
                        session_id=session_id,
                        transcript_path=bound_transcript,
                        source="compact",
                    ),
                    registry_path=registry_path,
                    state_dir=state_dir,
                )
            )
        transcript_path = _absolute_transcript(event.get("transcript_path"))
        if transcript_path is None:
            return {}
        if event_name == "sessionEnd":
            binding = read_session_binding(session_id, state_dir=state_dir)
            if not _binding_matches(
                binding,
                registration=registration,
                session_id=session_id,
                transcript_path=transcript_path,
            ):
                return {}
            reason = event.get("reason")
            session_lifecycle.handle_event(
                {
                    "session_id": session_id,
                    "transcript_path": str(transcript_path),
                    "cwd": str(registration.worktree_root.resolve(strict=False)),
                    "hook_event_name": "SessionEnd",
                    "reason": reason if isinstance(reason, str) else "other",
                },
                registry_path=registry_path,
                state_dir=state_dir,
            )
            return {}
        binding = read_session_binding(session_id, state_dir=state_dir)
        if binding is None:
            source = "startup"
        elif _binding_matches(
            binding,
            registration=registration,
            session_id=session_id,
            transcript_path=transcript_path,
        ):
            source = "resume"
        else:
            return {}
        normalized = _normalized_start(
            event,
            registration=registration,
            session_id=session_id,
            transcript_path=transcript_path,
            source=source,
        )
        return _cursor_context(
            session_router.handle_event(
                normalized,
                registry_path=registry_path,
                state_dir=state_dir,
            )
        )
    except (TypeError, ValueError) as exc:
        append_hook_error(
            "CURSOR_ADAPTER_INVALID_INPUT",
            type(exc).__name__,
            state_dir=state_dir,
        )
        return {}
    except Exception as exc:  # noqa: BLE001 - host hooks must fail open
        append_hook_error(
            "CURSOR_ADAPTER_FAILED",
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
    if output:
        print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
