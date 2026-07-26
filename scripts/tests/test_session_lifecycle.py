#!/usr/bin/env python3
"""Tests for persisted, session-attributed SessionEnd verdicts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import session_lifecycle as lifecycle  # noqa: E402
import session_state as state  # noqa: E402


NOW = datetime(2026, 7, 25, 19, 0, tzinfo=UTC)


def _registration(root: Path) -> state.RepositoryRegistration:
    return state.RepositoryRegistration(
        name="dotclaude-ecosystem",
        canonical_root=root,
        worktree_root=root,
        plan_paths=("design/plans",),
        vision_paths=(),
        idea_paths=("IDEA_BOX.md",),
    )


def _plan(session_id: str = "session-a", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": state.SESSION_PLAN_SCHEMA,
        "session_id": session_id,
        "goal": "Implement lifecycle",
        "chain": ["executor", "review"],
        "persona": "production engineer",
        "risk": "R1",
        "repo": "dotclaude-ecosystem",
        "start_sha": "a" * 40,
        "transcript_path": "D:/tmp/session-a.jsonl",
        "checkpoints": [],
        "claims": [],
        "created_at": "2026-07-25T18:00:00Z",
        "updated_at": "2026-07-25T18:00:00Z",
        "start_branch": "codex/session-lifecycle-core",
        "start_dirty_paths": [],
    }
    payload.update(overrides)
    return payload


def _evidence(**overrides: object) -> lifecycle.SessionEvidence:
    values: dict[str, object] = {
        "git_ok": True,
        "head": "b" * 40,
        "branch": "codex/session-lifecycle-core",
        "dirty_paths": (),
        "commit_shas": ("b" * 40,),
        "committed_paths": ("scripts/session_lifecycle.py",),
        "transcript_written_paths": (),
        "transcript_complete": True,
        "work_reached_trunk": True,
    }
    values.update(overrides)
    return lifecycle.SessionEvidence(**values)


def _binding(root: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": state.SESSION_BINDING_SCHEMA,
        "session_id": "session-a",
        "repo": "dotclaude-ecosystem",
        "worktree_root": str(root.resolve(strict=False)),
        "start_sha": "a" * 40,
        "transcript_path": "D:/tmp/session-a.jsonl",
        "start_branch": "codex/session-lifecycle-core",
        "start_dirty_paths": [],
        "created_at": "2026-07-25T18:00:00Z",
    }
    payload.update(overrides)
    return payload


class TestVerdictRules(unittest.TestCase):
    def test_clean_session_that_changes_nothing_is_no_op(self):
        result = lifecycle.decide_verdict(
            _plan(),
            _evidence(commit_shas=(), committed_paths=(), head="a" * 40),
        )
        self.assertEqual(result.verdict, "NO-OP")
        self.assertEqual(result.attributable_paths, ())

    def test_unproven_preexisting_dirt_fails_closed_instead_of_handoff(self):
        plan = _plan(start_dirty_paths=["operator-notes.md"])
        evidence = _evidence(
            commit_shas=(),
            committed_paths=(),
            dirty_paths=("operator-notes.md",),
            transcript_complete=False,
            head="a" * 40,
        )
        result = lifecycle.decide_verdict(plan, evidence)
        self.assertEqual(result.verdict, "UNKNOWN")

    def test_disappeared_preexisting_dirt_can_never_be_reported_as_no_op(self):
        plan = _plan(start_dirty_paths=["operator-notes.md"])
        evidence = _evidence(
            commit_shas=(),
            committed_paths=(),
            dirty_paths=(),
            transcript_complete=False,
            head="a" * 40,
        )

        result = lifecycle.decide_verdict(plan, evidence)

        self.assertEqual(result.verdict, "UNKNOWN")
        self.assertIn("operator-notes.md", result.attributable_paths)
        self.assertIn("disappeared", result.reason)

    def test_transcript_write_to_preexisting_dirty_path_is_attributable(self):
        plan = _plan(start_dirty_paths=["shared.py"])
        evidence = _evidence(
            commit_shas=(),
            committed_paths=(),
            dirty_paths=("shared.py",),
            transcript_written_paths=("shared.py",),
            head="a" * 40,
            work_reached_trunk=False,
        )
        result = lifecycle.decide_verdict(plan, evidence)
        self.assertEqual(result.verdict, "CHECKPOINT")
        self.assertEqual(result.attributable_paths, ("shared.py",))

    def test_dirty_only_work_is_checkpoint_even_when_head_is_on_trunk(self):
        result = lifecycle.decide_verdict(
            _plan(),
            _evidence(
                commit_shas=(),
                committed_paths=(),
                dirty_paths=("new.py",),
                head="a" * 40,
                work_reached_trunk=True,
            ),
        )
        self.assertEqual(result.verdict, "CHECKPOINT")

    def test_unmerged_commits_are_checkpoint(self):
        result = lifecycle.decide_verdict(
            _plan(),
            _evidence(work_reached_trunk=False),
        )
        self.assertEqual(result.verdict, "CHECKPOINT")

    def test_merged_clean_work_is_archive_ok(self):
        result = lifecycle.decide_verdict(_plan(), _evidence())
        self.assertEqual(result.verdict, "ARCHIVE-OK")

    def test_merged_work_with_open_checkpoint_is_handoff(self):
        plan = _plan(checkpoints=[{"text": "enable hooks", "status": "open"}])
        result = lifecycle.decide_verdict(plan, _evidence())
        self.assertEqual(result.verdict, "HANDOFF")
        self.assertEqual(result.open_items, ("enable hooks",))

    def test_merged_commit_with_attributable_dirty_work_is_handoff(self):
        result = lifecycle.decide_verdict(
            _plan(),
            _evidence(dirty_paths=("scripts/followup.py",)),
        )
        self.assertEqual(result.verdict, "HANDOFF")

    def test_incomplete_transcript_prevents_false_no_op(self):
        result = lifecycle.decide_verdict(
            _plan(start_dirty_paths=["shared.py"]),
            _evidence(
                commit_shas=(),
                committed_paths=(),
                dirty_paths=("shared.py",),
                transcript_complete=False,
                head="a" * 40,
            ),
        )
        self.assertEqual(result.verdict, "UNKNOWN")

    def test_git_failure_is_unknown(self):
        result = lifecycle.decide_verdict(_plan(), _evidence(git_ok=False))
        self.assertEqual(result.verdict, "UNKNOWN")


class TestTranscriptAttribution(unittest.TestCase):
    def test_extracts_only_write_like_tool_paths_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            transcript = Path(tmp) / "session.jsonl"
            records = [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Write",
                                "input": {
                                    "file_path": str(root / "src" / "new.py"),
                                    "content": "API_KEY=must-not-leak",
                                },
                            },
                            {
                                "type": "tool_use",
                                "name": "Read",
                                "input": {"file_path": str(root / "secret.env")},
                            },
                        ]
                    },
                }
            ]
            transcript.write_text(
                "\n".join(json.dumps(record) for record in records),
                encoding="utf-8",
            )

            paths, complete = lifecycle.transcript_written_paths(transcript, repo_root=root)

            self.assertTrue(complete)
            self.assertEqual(paths, ("src/new.py",))

    def test_oversized_transcript_is_marked_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "large.jsonl"
            transcript.write_bytes(b"x" * (lifecycle.MAX_TRANSCRIPT_SCAN_BYTES + 1))

            paths, complete = lifecycle.transcript_written_paths(transcript, repo_root=root)

            self.assertEqual(paths, ())
            self.assertFalse(complete)

    def test_collect_evidence_recognizes_squash_equivalent_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()

            def git(*args: str, input_text: str | None = None) -> str:
                result = subprocess.run(
                    ["git", "-C", str(root), *args],
                    input=input_text,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=True,
                )
                return result.stdout.strip()

            git("init", "-b", "main")
            git("config", "user.name", "Session Lifecycle Tests")
            git("config", "user.email", "session-lifecycle@example.invalid")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            git("update-ref", "refs/remotes/origin/main", base)

            git("checkout", "-b", "feature")
            (root / "tracked.txt").write_text("base\nfeature\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "feature one")
            feature_one = git("rev-parse", "HEAD")
            (root / "second ünicode.txt").write_text("second\n", encoding="utf-8")
            git("add", "second ünicode.txt")
            git("commit", "-m", "feature two")
            feature_two = git("rev-parse", "HEAD")
            tree = git("rev-parse", f"{feature_two}^{{tree}}")
            landed = git("commit-tree", tree, "-p", base, "-m", "squash landing")
            git("update-ref", "refs/remotes/origin/main", landed)

            transcript = Path(tmp) / "session.jsonl"
            transcript.write_text("", encoding="utf-8")
            evidence = lifecycle.collect_evidence(
                registration=_registration(root),
                plan=_plan(start_sha=base),
                transcript_path=transcript,
                state_dir=Path(tmp) / "state",
                deadline_s=3.0,
            )

            self.assertTrue(evidence.git_ok)
            self.assertEqual(evidence.commit_shas, (feature_two, feature_one))
            self.assertEqual(
                evidence.committed_paths,
                ("second ünicode.txt", "tracked.txt"),
            )
            self.assertTrue(evidence.work_reached_trunk)
            self.assertFalse(evidence.transcript_complete)


class TestLifecyclePersistence(unittest.TestCase):
    def test_session_end_persists_verdict_and_emits_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            state.write_session_plan("session-a", _plan(), state_dir=state_dir)
            state.write_session_binding(
                "session-a",
                _binding(root),
                state_dir=state_dir,
            )
            event = {
                "session_id": "session-a",
                "transcript_path": "D:/tmp/session-a.jsonl",
                "cwd": str(root),
                "hook_event_name": "SessionEnd",
                "reason": "other",
            }
            with (
                mock.patch.object(
                    lifecycle,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    lifecycle,
                    "collect_evidence",
                    return_value=_evidence(),
                ),
                mock.patch.object(lifecycle, "_run_reaper"),
            ):
                result = lifecycle.handle_event(event, state_dir=state_dir, now=NOW)

            self.assertIsNone(result)
            verdict = lifecycle.read_verdict(
                state_dir / "session_verdict_session-a.json"
            )
            assert verdict is not None
            self.assertEqual(verdict["verdict"], "ARCHIVE-OK")
            self.assertIsNone(verdict["surfaced_at"])
            self.assertIsNone(verdict["consumed_at"])
            self.assertEqual(verdict["start_sha"], "a" * 40)

    def test_session_end_ignores_tampered_scratch_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            state.write_session_plan(
                "session-a",
                _plan(
                    start_sha="f" * 40,
                    start_dirty_paths=["attacker-controlled.txt"],
                    transcript_path="D:/tmp/attacker.jsonl",
                ),
                state_dir=state_dir,
            )
            state.write_session_binding(
                "session-a",
                _binding(root, start_dirty_paths=["operator-owned.txt"]),
                state_dir=state_dir,
            )
            event = {
                "session_id": "session-a",
                "transcript_path": "D:/tmp/session-a.jsonl",
                "cwd": str(root),
                "hook_event_name": "SessionEnd",
                "reason": "other",
            }
            with (
                mock.patch.object(
                    lifecycle,
                    "resolve_repository",
                    return_value=_registration(root),
                ),
                mock.patch.object(
                    lifecycle,
                    "collect_evidence",
                    return_value=_evidence(),
                ) as collect,
                mock.patch.object(lifecycle, "_run_reaper"),
            ):
                lifecycle.handle_event(event, state_dir=state_dir, now=NOW)

            effective = collect.call_args.kwargs["plan"]
            self.assertEqual(effective["start_sha"], "a" * 40)
            self.assertEqual(effective["start_dirty_paths"], ["operator-owned.txt"])
            self.assertNotIn("attacker-controlled.txt", effective["start_dirty_paths"])

    def test_verdict_schema_rejects_unknown_enum_and_inconsistent_handoff_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "verdict value"):
                lifecycle.write_verdict(
                    {
                        "schema_version": lifecycle.VERDICT_SCHEMA,
                        "session_id": "bad",
                        "repo": "repo",
                        "verdict": "MAYBE",
                    },
                    state_dir=root,
                )
            with self.assertRaisesRegex(ValueError, "handoff"):
                lifecycle.write_verdict(
                    {
                        "schema_version": lifecycle.VERDICT_SCHEMA,
                        "session_id": "bad",
                        "repo": "repo",
                        "verdict": "UNKNOWN",
                        "handoff_draft": {"required": False},
                    },
                    state_dir=root,
                )

    def test_newest_pending_verdict_is_found_beyond_four_hundred_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base_timestamp = NOW.timestamp() - 1000
            for index in range(450):
                lifecycle.write_verdict(
                    {
                        "schema_version": lifecycle.VERDICT_SCHEMA,
                        "session_id": f"previous-{index}",
                        "repo": "repo",
                        "verdict": "CHECKPOINT",
                        "created_at": f"2026-07-25T17:{index % 60:02d}:00Z",
                        "surfaced_at": None,
                        "consumed_at": None,
                    },
                    state_dir=root,
                )
                path = root / f"session_verdict_previous-{index}.json"
                timestamp = base_timestamp + index
                os.utime(path, (timestamp, timestamp))

            pending = lifecycle.pending_verdict(
                repo="repo",
                current_session_id="current",
                state_dir=root,
            )

            assert pending is not None
            self.assertEqual(pending["session_id"], "previous-449")

    def test_surface_and_consume_are_distinct_idempotent_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lifecycle.write_verdict(
                {
                    "schema_version": lifecycle.VERDICT_SCHEMA,
                    "session_id": "previous",
                    "repo": "repo",
                    "verdict": "HANDOFF",
                    "created_at": "2026-07-25T17:00:00Z",
                    "surfaced_at": None,
                    "consumed_at": None,
                },
                state_dir=root,
            )

            surfaced = lifecycle.surface_pending_verdict(
                repo="repo",
                current_session_id="current",
                state_dir=root,
                surfaced_at="2026-07-25T18:00:00Z",
            )
            assert surfaced is not None
            self.assertEqual(surfaced["surfaced_at"], "2026-07-25T18:00:00Z")
            self.assertIsNone(surfaced["consumed_at"])

            surfaced_again = lifecycle.surface_pending_verdict(
                repo="repo",
                current_session_id="current",
                state_dir=root,
                surfaced_at="2026-07-25T18:30:00Z",
            )
            assert surfaced_again is not None
            self.assertEqual(surfaced_again["surfaced_at"], "2026-07-25T18:00:00Z")

            consumed = lifecycle.consume_pending_verdict(
                repo="repo",
                current_session_id="current",
                state_dir=root,
                consumed_at="2026-07-25T19:00:00Z",
            )
            assert consumed is not None
            self.assertEqual(consumed["consumed_at"], "2026-07-25T19:00:00Z")

    def test_surface_and_consume_serialize_without_losing_consumed_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lifecycle.write_verdict(
                {
                    "schema_version": lifecycle.VERDICT_SCHEMA,
                    "session_id": "previous",
                    "repo": "repo",
                    "verdict": "HANDOFF",
                    "created_at": "2026-07-25T17:00:00Z",
                    "surfaced_at": None,
                    "consumed_at": None,
                },
                state_dir=root,
            )
            original_write = lifecycle.write_verdict
            active_writers = 0
            max_active_writers = 0
            counter_lock = threading.Lock()
            start = threading.Barrier(2)

            def delayed_write(
                payload: dict[str, object],
                *,
                state_dir: Path,
            ) -> Path:
                nonlocal active_writers, max_active_writers
                with counter_lock:
                    active_writers += 1
                    max_active_writers = max(max_active_writers, active_writers)
                try:
                    time.sleep(0.02)
                    return original_write(payload, state_dir=state_dir)
                finally:
                    with counter_lock:
                        active_writers -= 1

            def surface() -> dict[str, object] | None:
                start.wait()
                return lifecycle.surface_pending_verdict(
                    repo="repo",
                    current_session_id="current",
                    state_dir=root,
                    surfaced_at="2026-07-25T18:00:00Z",
                )

            def consume() -> dict[str, object] | None:
                start.wait()
                return lifecycle.consume_pending_verdict(
                    repo="repo",
                    current_session_id="current",
                    state_dir=root,
                    consumed_at="2026-07-25T19:00:00Z",
                    expected_session_id="previous",
                    expected_created_at="2026-07-25T17:00:00Z",
                )

            with (
                mock.patch.object(lifecycle, "write_verdict", side_effect=delayed_write),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                futures = [pool.submit(surface), pool.submit(consume)]
                for future in futures:
                    future.result(timeout=2)

            verdict = lifecycle.read_verdict(
                root / "session_verdict_previous.json"
            )
            assert verdict is not None
            self.assertEqual(max_active_writers, 1)
            self.assertEqual(verdict["consumed_at"], "2026-07-25T19:00:00Z")

            self.assertIsNone(
                lifecycle.surface_pending_verdict(
                    repo="repo",
                    current_session_id="current",
                    state_dir=root,
                    surfaced_at="2026-07-25T20:00:00Z",
                )
            )


if __name__ == "__main__":
    unittest.main()
