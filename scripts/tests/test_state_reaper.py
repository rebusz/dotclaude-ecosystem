#!/usr/bin/env python3
"""Tests for bounded lifecycle state cleanup."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import state_reaper as reaper  # noqa: E402
import session_state as state  # noqa: E402


NOW = datetime(2026, 7, 25, 18, 0, tzinfo=UTC)


def _old(path: Path, *, days: int) -> None:
    timestamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def _verdict(
    path: Path,
    *,
    session_id: str,
    created_days_ago: int,
    surfaced_at: str | None = None,
    consumed_at: str | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "session.verdict.v1",
                "session_id": session_id,
                "repo": "repo",
                "verdict": "CHECKPOINT",
                "created_at": (
                    NOW - timedelta(days=created_days_ago)
                ).isoformat().replace("+00:00", "Z"),
                "surfaced_at": surfaced_at,
                "consumed_at": consumed_at,
            }
        ),
        encoding="utf-8",
    )
    _old(path, days=created_days_ago)


class TestStateReaper(unittest.TestCase):
    def test_reaps_only_owned_old_non_live_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_counter = root / "turn_counter_dead"
            old_plan = root / "session_plan_dead.json"
            own_plan = root / "session_plan_current.json"
            live_plan = root / "session_plan_live.json"
            fresh_counter = root / "turn_counter_fresh"
            unrelated = root / "operator-note.txt"
            for path in (old_counter, old_plan, own_plan, live_plan, fresh_counter, unrelated):
                path.write_text("1", encoding="utf-8")
            for path in (old_counter, old_plan, own_plan, live_plan, unrelated):
                _old(path, days=30)

            summary = reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids={"live"},
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertFalse(old_counter.exists())
            self.assertFalse(old_plan.exists())
            self.assertTrue(own_plan.exists())
            self.assertTrue(live_plan.exists())
            self.assertTrue(fresh_counter.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(summary["deleted"], 2)

    def test_unconsumed_and_only_surfaced_verdicts_survive_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unconsumed = root / "session_verdict_unconsumed.json"
            surfaced = root / "session_verdict_surfaced.json"
            _verdict(unconsumed, session_id="unconsumed", created_days_ago=30)
            _verdict(
                surfaced,
                session_id="surfaced",
                created_days_ago=30,
                surfaced_at="2026-07-24T00:00:00Z",
            )

            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertTrue(unconsumed.exists())
            self.assertTrue(surfaced.exists())

    def test_consumed_verdict_is_reapable_after_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session_verdict_consumed.json"
            _verdict(
                path,
                session_id="consumed",
                created_days_ago=30,
                consumed_at="2026-07-01T00:00:00Z",
            )

            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertFalse(path.exists())

    def test_unconsumed_verdict_past_hard_outer_bound_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session_verdict_abandoned.json"
            _verdict(
                path,
                session_id="abandoned",
                created_days_ago=reaper.VERDICT_OUTER_BOUND_DAYS + 1,
            )

            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertFalse(path.exists())

    def test_recent_surface_mtime_cannot_extend_verdict_outer_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session_verdict_ancient.json"
            _verdict(
                path,
                session_id="ancient",
                created_days_ago=reaper.VERDICT_OUTER_BOUND_DAYS + 1,
                surfaced_at="2026-07-25T17:00:00Z",
            )
            recent = NOW.timestamp()
            os.utime(path, (recent, recent))

            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertFalse(path.exists())

    def test_killed_session_without_session_end_is_reaped_on_next_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            abandoned = root / "session_plan_killed.json"
            abandoned.write_text("{}", encoding="utf-8")
            _old(abandoned, days=reaper.RETENTION_DAYS + 1)

            reaper.reap_state(
                state_dir=root,
                current_session_id="next-session",
                live_session_ids={"next-session"},
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertFalse(abandoned.exists())

    def test_fresh_bound_transcript_protects_a_live_session_without_explicit_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "live.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            os.utime(transcript, (NOW.timestamp(), NOW.timestamp()))
            plan = root / "session_plan_live.json"
            plan.write_text("{}", encoding="utf-8")
            state.write_session_binding(
                "live",
                {
                    "schema_version": state.SESSION_BINDING_SCHEMA,
                    "session_id": "live",
                    "repo": "repo",
                    "worktree_root": str(root.resolve()),
                    "start_sha": "a" * 40,
                    "transcript_path": str(transcript.resolve()),
                    "start_branch": "main",
                    "start_dirty_paths": [],
                    "created_at": "2026-07-01T00:00:00Z",
                },
                state_dir=root,
            )
            binding = root / "session_binding_live.json"
            _old(plan, days=30)
            _old(binding, days=30)

            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertTrue(plan.exists())
            self.assertTrue(binding.exists())

            _old(transcript, days=30)
            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )
            self.assertFalse(plan.exists())
            self.assertFalse(binding.exists())

    def test_live_session_cannot_extend_verdict_hard_outer_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transcript = root / "live.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            os.utime(transcript, (NOW.timestamp(), NOW.timestamp()))
            plan = root / "session_plan_live.json"
            plan.write_text("{}", encoding="utf-8")
            state.write_session_binding(
                "live",
                {
                    "schema_version": state.SESSION_BINDING_SCHEMA,
                    "session_id": "live",
                    "repo": "repo",
                    "worktree_root": str(root.resolve()),
                    "start_sha": "a" * 40,
                    "transcript_path": str(transcript.resolve()),
                    "start_branch": "main",
                    "start_dirty_paths": [],
                    "created_at": "2026-07-01T00:00:00Z",
                },
                state_dir=root,
            )
            binding = root / "session_binding_live.json"
            verdict = root / "session_verdict_live.json"
            _verdict(
                verdict,
                session_id="live",
                created_days_ago=reaper.VERDICT_OUTER_BOUND_DAYS + 1,
            )
            _old(plan, days=30)
            _old(binding, days=30)

            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertTrue(plan.exists())
            self.assertTrue(binding.exists())
            self.assertFalse(verdict.exists())

    def test_scan_loop_honors_time_budget_before_enumerating_backlog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(50):
                (root / f"turn_counter_dead-{index}").write_text("1", encoding="utf-8")

            with mock.patch.object(
                reaper.time,
                "perf_counter",
                side_effect=[0.0, 0.002],
            ):
                summary = reaper.reap_state(
                    state_dir=root,
                    current_session_id="current",
                    live_session_ids=set(),
                    now=NOW,
                    max_files=200,
                    time_budget_s=0.001,
                )

            self.assertTrue(summary["time_budget_hit"])
            self.assertEqual(summary["scanned"], 0)

    def test_truncated_scan_checks_each_candidates_exact_binding_lease(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = root / "session_plan_live.json"
            plan.write_text("{}", encoding="utf-8")
            _old(plan, days=30)
            transcript = root / "live.jsonl"
            transcript.write_text("{}\n", encoding="utf-8")
            os.utime(transcript, (NOW.timestamp(), NOW.timestamp()))
            state.write_session_binding(
                "live",
                {
                    "schema_version": state.SESSION_BINDING_SCHEMA,
                    "session_id": "live",
                    "repo": "repo",
                    "worktree_root": str(root.resolve()),
                    "start_sha": "a" * 40,
                    "transcript_path": str(transcript.resolve()),
                    "start_branch": "main",
                    "start_dirty_paths": [],
                    "created_at": "2026-07-01T00:00:00Z",
                },
                state_dir=root,
            )

            with (
                mock.patch.object(reaper, "MAX_SCAN_FILES", 1),
                mock.patch.object(
                    reaper,
                    "_binding_transcript_is_fresh",
                    wraps=reaper._binding_transcript_is_fresh,
                ) as lease,
            ):
                summary = reaper.reap_state(
                    state_dir=root,
                    current_session_id="current",
                    live_session_ids=set(),
                    now=NOW,
                    max_files=200,
                    time_budget_s=1.0,
                )

            self.assertTrue(summary["file_limit_hit"])
            self.assertTrue(plan.exists())
            lease.assert_called_with(
                "live",
                state_dir=root,
                retention_cutoff=NOW - timedelta(days=reaper.RETENTION_DAYS),
            )

    def test_max_files_bounds_deletions_per_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(20):
                path = root / f"turn_counter_dead-{index}"
                path.write_text("1", encoding="utf-8")
                _old(path, days=30)

            summary = reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=5,
                time_budget_s=1.0,
            )

            self.assertEqual(summary["deleted"], 5)
            self.assertEqual(len(list(root.glob("turn_counter_*"))), 15)

    def test_fresh_consumed_verdict_survives_until_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "session_verdict_recent.json"
            _verdict(
                path,
                session_id="recent",
                created_days_ago=1,
                consumed_at="2026-07-25T17:00:00Z",
            )

            reaper.reap_state(
                state_dir=root,
                current_session_id="current",
                live_session_ids=set(),
                now=NOW,
                max_files=200,
                time_budget_s=1.0,
            )

            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
