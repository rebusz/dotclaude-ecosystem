#!/usr/bin/env python3
"""Tests for the Cursor CLI-to-shared-lifecycle event adapter."""

from __future__ import annotations

import json
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import cursor_session_adapter as adapter  # noqa: E402
from session_state import RepositoryRegistration  # noqa: E402


def _registration(root: Path) -> RepositoryRegistration:
    return RepositoryRegistration(
        name="dotclaude-ecosystem",
        canonical_root=root,
        worktree_root=root,
        plan_paths=(),
        vision_paths=(),
        idea_paths=(),
    )


def _event(
    hook_event_name: str,
    *,
    root: Path,
    transcript_path: str | None,
    conversation_id: str = "019fa48d-3d90-7eb1-afd3-9fc06757c2c6",
) -> dict[str, object]:
    event: dict[str, object] = {
        "conversation_id": conversation_id,
        "generation_id": "019fa48d-5812-7130-9187-15d8717c095a",
        "hook_event_name": hook_event_name,
        "cursor_version": "2026.07.23-e383d2b",
        "workspace_roots": [str(root)],
        "transcript_path": transcript_path,
        "model": "gpt-5.6-sol",
    }
    if hook_event_name == "sessionEnd":
        event["reason"] = "completed"
    return event


class TestCursorSessionAdapter(unittest.TestCase):
    def test_main_emits_only_compact_cursor_context_json(self):
        stdout = io.StringIO()
        payload = json.dumps(
            {
                "hook_event_name": "sessionStart",
                "conversation_id": "native-id",
            }
        )
        with (
            mock.patch.object(sys, "stdin", io.StringIO(payload)),
            mock.patch.object(sys, "stdout", stdout),
            mock.patch.object(
                adapter,
                "handle_event",
                return_value={"additional_context": "context"},
            ) as handle,
        ):
            exit_code = adapter.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), '{"additional_context":"context"}\n')
        handle.assert_called_once_with(json.loads(payload))

    def test_valid_cli_start_delegates_normalized_event_and_emits_context_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            transcript = root / ".cursor" / "chat.jsonl"
            event = _event(
                "sessionStart",
                root=root,
                transcript_path=str(transcript),
            )
            shared_output = {
                "suppressOutput": True,
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "registered context",
                    "sessionTitle": "shared-only title",
                },
                "env": {"FORBIDDEN": "1"},
            }
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    return_value=shared_output,
                ) as start,
            ):
                output = adapter.handle_event(event, state_dir=root / "state")

            self.assertEqual(output, {"additional_context": "registered context"})
            delegated = start.call_args.args[0]
            self.assertEqual(delegated["hook_event_name"], "SessionStart")
            self.assertEqual(delegated["source"], "startup")
            self.assertEqual(delegated["cwd"], str(root))
            self.assertEqual(
                delegated["transcript_path"],
                str(transcript.resolve(strict=False)),
            )
            self.assertNotEqual(delegated["session_id"], event["conversation_id"])
            self.assertNotIn("env", output)

    def test_matching_cli_end_delegates_only_the_exact_existing_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            transcript = (root / ".cursor" / "chat.jsonl").resolve(strict=False)
            start_event = _event(
                "sessionStart",
                root=root,
                transcript_path=str(transcript),
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    return_value={},
                ) as start,
            ):
                adapter.handle_event(start_event, state_dir=root / "state")
            session_id = start.call_args.args[0]["session_id"]
            binding = {
                "session_id": session_id,
                "repo": "dotclaude-ecosystem",
                "worktree_root": str(root),
                "transcript_path": str(transcript),
            }
            end_event = _event(
                "sessionEnd",
                root=root,
                transcript_path=str(transcript),
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter,
                    "read_session_binding",
                    return_value=binding,
                ) as read_binding,
                mock.patch.object(
                    adapter.session_lifecycle,
                    "handle_event",
                ) as end,
            ):
                output = adapter.handle_event(end_event, state_dir=root / "state")

            self.assertEqual(output, {})
            read_binding.assert_called_once_with(
                session_id,
                state_dir=root / "state",
            )
            delegated = end.call_args.args[0]
            self.assertEqual(delegated["hook_event_name"], "SessionEnd")
            self.assertEqual(delegated["session_id"], session_id)
            self.assertEqual(delegated["cwd"], str(root))
            self.assertEqual(delegated["transcript_path"], str(transcript))
            self.assertEqual(delegated["reason"], "completed")

    def test_precompact_without_existing_binding_is_a_clean_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            event = _event(
                "preCompact",
                root=root,
                transcript_path=None,
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter,
                    "read_session_binding",
                    return_value=None,
                ) as read_binding,
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                ) as router,
            ):
                output = adapter.handle_event(event, state_dir=root / "state")

            self.assertEqual(output, {})
            read_binding.assert_called_once()
            router.assert_not_called()

    def test_precompact_reuses_exact_binding_without_changing_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            transcript = (root / ".cursor" / "chat.jsonl").resolve(strict=False)
            start_event = _event(
                "sessionStart",
                root=root,
                transcript_path=str(transcript),
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    return_value={},
                ) as start,
            ):
                adapter.handle_event(start_event, state_dir=root / "state")
            session_id = start.call_args.args[0]["session_id"]
            binding = {
                "session_id": session_id,
                "repo": "dotclaude-ecosystem",
                "worktree_root": str(root),
                "transcript_path": str(transcript),
            }
            event = _event(
                "preCompact",
                root=root,
                transcript_path=None,
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter,
                    "read_session_binding",
                    return_value=binding,
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    return_value={
                        "hookSpecificOutput": {
                            "additionalContext": "compact checkpoint"
                        }
                    },
                ) as router,
            ):
                output = adapter.handle_event(event, state_dir=root / "state")

            self.assertEqual(output, {"additional_context": "compact checkpoint"})
            delegated = router.call_args.args[0]
            self.assertEqual(delegated["session_id"], session_id)
            self.assertEqual(delegated["source"], "compact")
            self.assertEqual(delegated["transcript_path"], str(transcript))

    def test_null_start_is_lower_fidelity_noop_without_state_or_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state_dir = root / "state"
            event = _event(
                "sessionStart",
                root=root,
                transcript_path=None,
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                ) as router,
            ):
                output = adapter.handle_event(event, state_dir=state_dir)

            self.assertEqual(output, {})
            router.assert_not_called()
            self.assertFalse((state_dir / "hook_errors.log").exists())

    def test_zero_or_many_roots_never_guess_a_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for index, roots in enumerate(([], [str(root), str(root / "other")])):
                with self.subTest(roots=roots):
                    state_dir = root / f"state-{index}"
                    event = _event(
                        "sessionStart",
                        root=root,
                        transcript_path=str(root / "chat.jsonl"),
                    )
                    event["workspace_roots"] = roots
                    with (
                        mock.patch.object(adapter, "resolve_repository") as resolve,
                        mock.patch.object(
                            adapter.session_router,
                            "handle_event",
                        ) as router,
                    ):
                        output = adapter.handle_event(event, state_dir=state_dir)

                    self.assertEqual(output, {})
                    resolve.assert_not_called()
                    router.assert_not_called()
                    self.assertFalse((state_dir / "hook_errors.log").exists())

    def test_cli_adapter_rejects_ide_surface_and_unregistered_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            event = _event(
                "sessionStart",
                root=root,
                transcript_path=str(root / "chat.jsonl"),
            )
            ide_event = dict(event)
            ide_event["cursor_version"] = "3.13.25"
            with mock.patch.object(
                adapter.session_router,
                "handle_event",
            ) as router:
                self.assertEqual(
                    adapter.handle_event(ide_event, state_dir=root / "state"),
                    {},
                )
                router.assert_not_called()
            error = (root / "state" / "hook_errors.log").read_text(encoding="utf-8")
            self.assertIn("CURSOR_ADAPTER_UNSUPPORTED_SURFACE noop", error)
            self.assertNotIn("CURSOR_ADAPTER_FAILED", error)

            state_dir = root / "unregistered-state"
            with (
                mock.patch.object(adapter, "resolve_repository", return_value=None),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                ) as router,
            ):
                self.assertEqual(
                    adapter.handle_event(event, state_dir=state_dir),
                    {},
                )
                router.assert_not_called()
            self.assertFalse((state_dir / "hook_errors.log").exists())

    def test_end_path_mismatch_fails_closed_without_source_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            bound = (root / ".cursor" / "bound.jsonl").resolve(strict=False)
            supplied = (root / ".cursor" / "other.jsonl").resolve(strict=False)
            start_event = _event(
                "sessionStart",
                root=root,
                transcript_path=str(bound),
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    return_value={},
                ) as start,
            ):
                adapter.handle_event(start_event, state_dir=root / "state")
            session_id = start.call_args.args[0]["session_id"]
            binding = {
                "session_id": session_id,
                "repo": "dotclaude-ecosystem",
                "worktree_root": str(root),
                "transcript_path": str(bound),
            }
            event = _event(
                "sessionEnd",
                root=root,
                transcript_path=str(supplied),
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter,
                    "read_session_binding",
                    return_value=binding,
                ),
                mock.patch.object(
                    adapter.session_lifecycle,
                    "handle_event",
                ) as end,
            ):
                output = adapter.handle_event(event, state_dir=root / "state")

            self.assertEqual(output, {})
            end.assert_not_called()

    def test_precompact_path_mismatch_fails_closed_without_source_swap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            bound = (root / ".cursor" / "bound.jsonl").resolve(strict=False)
            supplied = (root / ".cursor" / "other.jsonl").resolve(strict=False)
            start_event = _event(
                "sessionStart",
                root=root,
                transcript_path=str(bound),
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    return_value={},
                ) as start,
            ):
                adapter.handle_event(start_event, state_dir=root / "state")
            session_id = start.call_args.args[0]["session_id"]
            binding = {
                "session_id": session_id,
                "repo": "dotclaude-ecosystem",
                "worktree_root": str(root),
                "transcript_path": str(bound),
            }
            event = _event(
                "preCompact",
                root=root,
                transcript_path=str(supplied),
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter,
                    "read_session_binding",
                    return_value=binding,
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                ) as router,
            ):
                output = adapter.handle_event(event, state_dir=root / "state")

            self.assertEqual(output, {})
            router.assert_not_called()

    def test_new_chat_identity_is_distinct_and_delegate_error_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            transcript = str(root / ".cursor" / "chat.jsonl")
            first = _event(
                "sessionStart",
                root=root,
                transcript_path=transcript,
            )
            second = _event(
                "sessionStart",
                root=root,
                transcript_path=transcript,
                conversation_id="019fa48d-3d90-7eb1-afd3-9fc06757c2c7",
            )
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    return_value={},
                ) as router,
            ):
                adapter.handle_event(first, state_dir=root / "state")
                adapter.handle_event(second, state_dir=root / "state")
            self.assertNotEqual(
                router.call_args_list[0].args[0]["session_id"],
                router.call_args_list[1].args[0]["session_id"],
            )

            state_dir = root / "state"
            hostile = dict(first)
            hostile["user_email"] = "private@example.invalid"
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    adapter.session_router,
                    "handle_event",
                    side_effect=RuntimeError("private transcript text"),
                ),
            ):
                self.assertEqual(
                    adapter.handle_event(hostile, state_dir=state_dir),
                    {},
                )
            error = (state_dir / "hook_errors.log").read_text(encoding="utf-8")
            self.assertIn("CURSOR_ADAPTER_FAILED RuntimeError", error)
            self.assertNotIn("private@example.invalid", error)
            self.assertNotIn("private transcript text", error)

    def test_real_shared_engine_start_repeat_and_end_preserve_one_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = (Path(tmp) / "repo").resolve()
            root.mkdir()

            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", "-C", str(root), *args],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=True,
                ).stdout.strip()

            git("init", "-b", "main")
            git("config", "user.name", "Cursor Adapter Tests")
            git("config", "user.email", "cursor-adapter@example.invalid")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "base")
            git("update-ref", "refs/remotes/origin/main", git("rev-parse", "HEAD"))

            state_dir = Path(tmp) / "state"
            registry = Path(tmp) / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": "session.registry.v1",
                        "repositories": [
                            {
                                "name": "repo",
                                "root": str(root),
                                "plan_paths": [],
                                "vision_paths": [],
                                "idea_paths": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            transcript = (Path(tmp) / "cursor-session.jsonl").resolve()
            transcript.write_text("", encoding="utf-8")
            start = _event(
                "sessionStart",
                root=root,
                transcript_path=str(transcript),
            )

            registration = _registration(root)
            with (
                mock.patch.object(
                    adapter,
                    "resolve_repository",
                    return_value=registration,
                ),
                mock.patch.object(
                    adapter.session_router,
                    "resolve_repository",
                    return_value=registration,
                ),
                mock.patch.object(
                    adapter.session_lifecycle,
                    "resolve_repository",
                    return_value=registration,
                ),
            ):
                first = adapter.handle_event(
                    start,
                    registry_path=registry,
                    state_dir=state_dir,
                )
                self.assertIn("additional_context", first)
                bindings = list(state_dir.glob("session_binding_*.json"))
                self.assertEqual(len(bindings), 1)
                binding_before = bindings[0].read_bytes()
                repeated = adapter.handle_event(
                    start,
                    registry_path=registry,
                    state_dir=state_dir,
                )
                self.assertIn("additional_context", repeated)
                self.assertEqual(bindings[0].read_bytes(), binding_before)

                compact = _event(
                    "preCompact",
                    root=root,
                    transcript_path=None,
                )
                compact_output = adapter.handle_event(
                    compact,
                    registry_path=registry,
                    state_dir=state_dir,
                )
                self.assertIn("additional_context", compact_output)
                self.assertEqual(bindings[0].read_bytes(), binding_before)
                self.assertEqual(
                    list(state_dir.glob("session_verdict_*.json")),
                    [],
                )

                end = _event(
                    "sessionEnd",
                    root=root,
                    transcript_path=str(transcript),
                )
                adapter.handle_event(
                    end,
                    registry_path=registry,
                    state_dir=state_dir,
                )

            self.assertEqual(bindings[0].read_bytes(), binding_before)
            self.assertEqual(len(list(state_dir.glob("session_verdict_*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
