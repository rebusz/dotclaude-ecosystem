#!/usr/bin/env python3
"""Tests for the shared session lifecycle state contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import session_state as state  # noqa: E402


def _plan(session_id: str = "session-a", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": state.SESSION_PLAN_SCHEMA,
        "session_id": session_id,
        "goal": "Implement the lifecycle core",
        "chain": ["tdd", "review"],
        "persona": "production engineer",
        "risk": "R1",
        "repo": "dotclaude-ecosystem",
        "start_sha": "a" * 40,
        "transcript_path": "D:/tmp/session-a.jsonl",
        "checkpoints": [],
        "claims": [],
        "created_at": "2026-07-25T12:00:00Z",
        "updated_at": "2026-07-25T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def _registry(root: Path) -> dict[str, object]:
    return {
        "schema_version": state.SESSION_REGISTRY_SCHEMA,
        "repositories": [
            {
                "name": "dotclaude-ecosystem",
                "root": root.as_posix(),
                "plan_paths": ["design/plans"],
                "vision_paths": ["design/visions"],
                "idea_paths": ["IDEA_BOX.md"],
            }
        ],
    }


def _binding(root: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": state.SESSION_BINDING_SCHEMA,
        "session_id": "session-a",
        "repo": "dotclaude-ecosystem",
        "worktree_root": str(root.resolve(strict=False)),
        "start_sha": "a" * 40,
        "transcript_path": str((root / "session.jsonl").resolve(strict=False)),
        "start_branch": "codex/session-lifecycle-core",
        "start_dirty_paths": ["operator notes\tline\nbreak.txt"],
        "created_at": "2026-07-25T12:00:00Z",
    }
    payload.update(overrides)
    return payload


class TestSessionState(unittest.TestCase):
    def test_resolve_repository_matches_canonical_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dotclaude-ecosystem"
            root.mkdir()
            registry_path = Path(tmp) / "session_registry.json"
            registry_path.write_text(json.dumps(_registry(root)), encoding="utf-8")
            git_result = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{root.as_posix()}\n{(root / '.git').as_posix()}\n",
                stderr="",
            )

            with mock.patch.object(state.subprocess, "run", return_value=git_result) as run:
                resolved = state.resolve_repository(root, registry_path=registry_path)

            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.name, "dotclaude-ecosystem")
            self.assertEqual(resolved.worktree_root, root.resolve())
            self.assertEqual(run.call_count, 1, "repository resolution owns exactly one git spawn")

    def test_resolve_repository_matches_linked_worktree_via_common_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            canonical = Path(tmp) / "dotclaude-ecosystem"
            worktree = Path(tmp) / "wt-session"
            canonical.mkdir()
            worktree.mkdir()
            registry_path = Path(tmp) / "session_registry.json"
            registry_path.write_text(json.dumps(_registry(canonical)), encoding="utf-8")
            git_result = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{worktree.as_posix()}\n{(canonical / '.git').as_posix()}\n",
                stderr="",
            )

            with mock.patch.object(state.subprocess, "run", return_value=git_result):
                resolved = state.resolve_repository(worktree, registry_path=registry_path)

            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.worktree_root, worktree.resolve())

    def test_registry_miss_and_non_repo_are_clean_minimal_branches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "unregistered"
            root.mkdir()
            registry_path = Path(tmp) / "session_registry.json"
            registry_path.write_text(json.dumps(_registry(Path(tmp) / "elsewhere")), encoding="utf-8")

            missing = subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="not a repo")
            with mock.patch.object(state.subprocess, "run", return_value=missing):
                self.assertIsNone(state.resolve_repository(root, registry_path=registry_path))

            valid = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{root.as_posix()}\n{(root / '.git').as_posix()}\n",
                stderr="",
            )
            with mock.patch.object(state.subprocess, "run", return_value=valid):
                self.assertIsNone(state.resolve_repository(root, registry_path=registry_path))

    def test_malformed_registry_fails_open_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path = root / "session_registry.json"
            registry_path.write_text('{"schema_version":', encoding="utf-8")

            self.assertIsNone(
                state.resolve_repository(
                    root,
                    registry_path=registry_path,
                    state_dir=root / "state",
                )
            )
            log = (root / "state" / "hook_errors.log").read_text(encoding="utf-8")
            self.assertIn("REGISTRY_INVALID", log)

    def test_registry_rejects_paths_that_escape_the_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            registry = _registry(root)
            repositories = registry["repositories"]
            assert isinstance(repositories, list)
            repositories[0]["plan_paths"] = ["../secrets"]
            registry_path = Path(tmp) / "session_registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            git_result = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{root.as_posix()}\n{(root / '.git').as_posix()}\n",
                stderr="",
            )

            with mock.patch.object(state.subprocess, "run", return_value=git_result):
                self.assertIsNone(
                    state.resolve_repository(
                        root,
                        registry_path=registry_path,
                        state_dir=Path(tmp) / "state",
                    )
                )

    def test_registry_rejects_relative_repository_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = _registry(root)
            repositories = registry["repositories"]
            assert isinstance(repositories, list)
            repositories[0]["root"] = "relative/repo"
            registry_path = root / "session_registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            git_result = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=f"{root.as_posix()}\n{(root / '.git').as_posix()}\n",
                stderr="",
            )

            with mock.patch.object(state.subprocess, "run", return_value=git_result):
                self.assertIsNone(
                    state.resolve_repository(
                        root,
                        registry_path=registry_path,
                        state_dir=root / "state",
                    )
                )

    def test_atomic_round_trip_preserves_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            written = state.write_session_plan("session-a", _plan(), state_dir=state_dir)
            loaded = state.read_session_plan("session-a", state_dir=state_dir)

            self.assertEqual(written, state_dir / "session_plan_session-a.json")
            self.assertEqual(loaded, _plan())
            self.assertFalse(list(state_dir.glob("*.tmp")))

    def test_session_binding_is_write_once_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            root = Path(tmp) / "repo"
            root.mkdir()
            original = _binding(root)

            path = state.write_session_binding(
                "session-a",
                original,
                state_dir=state_dir,
            )
            state.write_session_binding("session-a", original, state_dir=state_dir)

            self.assertEqual(path, state_dir / "session_binding_session-a.json")
            self.assertEqual(
                state.read_session_binding("session-a", state_dir=state_dir),
                original,
            )
            with self.assertRaisesRegex(ValueError, "write-once"):
                state.write_session_binding(
                    "session-a",
                    _binding(root, start_sha="b" * 40),
                    state_dir=state_dir,
                )
            self.assertEqual(
                state.read_session_binding("session-a", state_dir=state_dir),
                original,
            )

    def test_malformed_existing_binding_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()
            root = Path(tmp) / "repo"
            root.mkdir()
            path = state_dir / "session_binding_session-a.json"
            original = b'{"schema_version":'
            path.write_bytes(original)

            with self.assertRaisesRegex(ValueError, "existing write-once"):
                state.write_session_binding(
                    "session-a",
                    _binding(root),
                    state_dir=state_dir,
                )

            self.assertEqual(path.read_bytes(), original)

    def test_concurrent_binding_creators_cannot_overwrite_each_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            root = Path(tmp) / "repo"
            root.mkdir()
            barrier = threading.Barrier(2)
            payloads = [
                _binding(root, start_sha="a" * 40),
                _binding(root, start_sha="b" * 40),
            ]

            def create(payload: dict[str, object]) -> str:
                barrier.wait()
                try:
                    state.write_session_binding(
                        "session-a",
                        payload,
                        state_dir=state_dir,
                    )
                    return "created"
                except ValueError:
                    return "rejected"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(create, payloads))

            self.assertCountEqual(outcomes, ["created", "rejected"])
            loaded = state.read_session_binding("session-a", state_dir=state_dir)
            assert loaded is not None
            self.assertIn(loaded["start_sha"], {"a" * 40, "b" * 40})

    def test_git_nul_parsers_preserve_control_characters_and_rename_target(self):
        status = "\0".join(
            [
                "# branch.oid " + "a" * 40,
                "# branch.head feature",
                "1 M. N... 100644 100644 100644 " + "b" * 40 + " " + "c" * 40
                + " tab\tand\nnewline.txt",
                "2 R. N... 100644 100644 100644 "
                + "d" * 40
                + " "
                + "e" * 40
                + " R100 renamed target.txt",
                "old target.txt",
                "? untracked ünicode.txt",
                "",
            ]
        )

        branch, head, paths = state.parse_git_status_v2_z(status)

        self.assertEqual(branch, "feature")
        self.assertEqual(head, "a" * 40)
        self.assertEqual(
            paths,
            (
                "tab\tand\nnewline.txt",
                "renamed target.txt",
                "untracked ünicode.txt",
            ),
        )
        self.assertEqual(
            state.parse_nul_paths("one\nfile\0tab\tfile\0one\nfile\0"),
            ("one\nfile", "tab\tfile"),
        )

    def test_malformed_truncated_and_wrong_version_are_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = state_dir / "session_plan_session-a.json"

            for broken in ("", '{"schema_version":', "[]"):
                path.write_text(broken, encoding="utf-8")
                self.assertIsNone(state.read_session_plan("session-a", state_dir=state_dir))

            path.write_text(
                json.dumps(_plan(schema_version="session.plan.v999")),
                encoding="utf-8",
            )
            self.assertIsNone(state.read_session_plan("session-a", state_dir=state_dir))
            log = (state_dir / "hook_errors.log").read_text(encoding="utf-8")
            self.assertIn("UNRECOGNIZED_VERSION", log)

    def test_missing_transcript_path_remains_readable_for_curator_degradation(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            payload = _plan()
            payload.pop("transcript_path")
            (state_dir / "session_plan_session-a.json").write_text(
                json.dumps(payload),
                encoding="utf-8",
            )

            loaded = state.read_session_plan("session-a", state_dir=state_dir)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertIsNone(loaded["transcript_path"])

    def test_schema_validation_rejects_omitted_required_fields_and_wrong_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = state_dir / "session_plan_session-a.json"

            missing_goal = _plan()
            missing_goal.pop("goal")
            path.write_text(json.dumps(missing_goal), encoding="utf-8")
            self.assertIsNone(state.read_session_plan("session-a", state_dir=state_dir))

            path.write_text(json.dumps(_plan(chain="tdd")), encoding="utf-8")
            self.assertIsNone(state.read_session_plan("session-a", state_dir=state_dir))

            path.write_text(json.dumps(_plan(session_id="different")), encoding="utf-8")
            self.assertIsNone(state.read_session_plan("session-a", state_dir=state_dir))

    def test_failed_replace_keeps_previous_good_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            original = _plan(goal="original")
            state.write_session_plan("session-a", original, state_dir=state_dir)

            with mock.patch.object(state.os, "replace", side_effect=PermissionError("held")):
                with self.assertRaises(PermissionError):
                    state.write_session_plan(
                        "session-a",
                        _plan(goal="replacement"),
                        state_dir=state_dir,
                    )

            self.assertEqual(state.read_session_plan("session-a", state_dir=state_dir), original)
            self.assertFalse(list(state_dir.glob("*.tmp")))

    def test_concurrent_writers_never_leave_partial_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            def write(index: int) -> None:
                state.write_session_plan(
                    "session-a",
                    _plan(goal=f"writer-{index}"),
                    state_dir=state_dir,
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(write, range(32)))

            loaded = state.read_session_plan("session-a", state_dir=state_dir)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertTrue(str(loaded["goal"]).startswith("writer-"))
            self.assertFalse(list(state_dir.glob("*.tmp")))

    def test_unsafe_session_identifier_cannot_escape_state_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            for session_id in ("../escape", "..\\escape", "", "a/b"):
                with self.assertRaises(ValueError):
                    state.write_session_plan(
                        session_id,
                        _plan(session_id=session_id),
                        state_dir=state_dir,
                    )

    def test_size_bounds_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            path = state_dir / "session_plan_session-a.json"
            path.write_bytes(b"{" + b"x" * state.MAX_SESSION_PLAN_BYTES)
            self.assertIsNone(state.read_session_plan("session-a", state_dir=state_dir))

            oversized = _plan(goal="x" * state.MAX_SESSION_PLAN_BYTES)
            with self.assertRaises(ValueError):
                state.write_session_plan("session-a", oversized, state_dir=state_dir)

    def test_error_log_is_line_and_file_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            for _ in range(300):
                state.append_hook_error("TEST", "x" * 5000, state_dir=state_dir)

            log_path = state_dir / "hook_errors.log"
            self.assertLessEqual(log_path.stat().st_size, state.MAX_ERROR_LOG_BYTES)
            self.assertTrue(
                all(len(line) <= state.MAX_ERROR_LINE_CHARS for line in log_path.read_text().splitlines())
            )


if __name__ == "__main__":
    unittest.main()
