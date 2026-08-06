#!/usr/bin/env python3
"""Tests for the advisory SessionStart router."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import session_router as router  # noqa: E402
import session_state as state  # noqa: E402
import session_lifecycle as lifecycle  # noqa: E402


NOW = datetime(2026, 7, 25, 18, 30, tzinfo=UTC)


def _registration(root: Path) -> state.RepositoryRegistration:
    return state.RepositoryRegistration(
        name="dotclaude-ecosystem",
        canonical_root=root,
        worktree_root=root,
        plan_paths=("design/plans",),
        vision_paths=(),
        idea_paths=("IDEA_BOX.md",),
    )


def _event(
    session_id: str = "session-a",
    source: str = "startup",
    *,
    cwd: Path,
    transcript_path: str = "D:/tmp/session-a.jsonl",
) -> dict[str, object]:
    return {
        "session_id": session_id,
        "transcript_path": transcript_path,
        "cwd": str(cwd),
        "hook_event_name": "SessionStart",
        "source": source,
        "model": "claude-opus-5",
    }


def _context(output: dict[str, object]) -> str:
    hook_output = output.get("hookSpecificOutput")
    assert isinstance(hook_output, dict)
    value = hook_output.get("additionalContext")
    assert isinstance(value, str)
    return value


class TestSessionRouter(unittest.TestCase):
    def test_registered_startup_creates_scaffold_and_full_bounded_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dotclaude-ecosystem"
            state_dir = Path(tmp) / "state"
            (root / "design" / "plans").mkdir(parents=True)
            (root / "design" / "handoffs").mkdir(parents=True)
            (root / "design" / "plans" / "active.md").write_text(
                "---\ntitle: Lifecycle\nstatus: in-progress\nrisk: R1\n---\n# Lifecycle\n",
                encoding="utf-8",
            )
            (root / "design" / "handoffs" / "latest.md").write_text(
                "# Continue lifecycle\n",
                encoding="utf-8",
            )
            (root / "IDEA_BOX.md").write_text(
                "# Ideas\n- [P2][S] Installer-managed hook block\n",
                encoding="utf-8",
            )
            facts = router.GitFacts(
                branch="codex/session-lifecycle-core",
                head="a" * 40,
                dirty_paths=("scripts/new.py",),
                ahead=2,
                behind=0,
            )

            with (
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(router, "_git_facts", return_value=facts),
                mock.patch.object(router, "_record_worktree_start") as record_start,
            ):
                output = router.handle_event(
                    _event(cwd=root),
                    state_dir=state_dir,
                    now=NOW,
                    run_maintenance=False,
                    owner_runtime="codex",
                )

            self.assertEqual(record_start.call_count, 1)
            self.assertEqual(record_start.call_args.kwargs["session_id"], "session-a")
            self.assertEqual(record_start.call_args.kwargs["facts"], facts)
            self.assertEqual(record_start.call_args.kwargs["owner_runtime"], "codex")

            loaded = state.read_session_plan("session-a", state_dir=state_dir)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded["goal"], "")
            self.assertEqual(loaded["chain"], [])
            self.assertEqual(loaded["risk"], "")
            self.assertEqual(loaded["repo"], "dotclaude-ecosystem")
            self.assertEqual(loaded["start_sha"], "a" * 40)
            self.assertEqual(loaded["transcript_path"], "D:/tmp/session-a.jsonl")
            self.assertEqual(loaded["start_dirty_paths"], ["scripts/new.py"])
            binding = state.read_session_binding("session-a", state_dir=state_dir)
            self.assertIsNotNone(binding)
            assert binding is not None
            self.assertEqual(binding["start_sha"], "a" * 40)
            self.assertEqual(binding["transcript_path"], "D:\\tmp\\session-a.jsonl")

            context = _context(output)
            self.assertIn("Lifecycle", context)
            self.assertIn("Installer-managed hook block", context)
            self.assertIn("latest.md", context)
            self.assertIn("model chooses", context)
            self.assertLessEqual(len(context), router.FULL_CONTEXT_MAX_CHARS)
            hook_output = output["hookSpecificOutput"]
            assert isinstance(hook_output, dict)
            self.assertEqual(
                hook_output["sessionTitle"],
                "dotclaude 25 JUL session lifecycle core",
            )

    def test_output_is_advisory_and_contains_no_stop_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(router, "resolve_repository", return_value=None):
                output = router.handle_event(
                    _event(cwd=root),
                    state_dir=root / "state",
                    now=NOW,
                    run_maintenance=False,
                )

            rendered = json.dumps(output)
            self.assertNotIn('"decision"', rendered)
            self.assertNotIn('"continue"', rendered)
            self.assertNotIn('"stopReason"', rendered)

    def test_unregistered_and_non_repo_use_one_bounded_line_and_write_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            with mock.patch.object(router, "resolve_repository", return_value=None):
                output = router.handle_event(
                    _event(cwd=root),
                    state_dir=state_dir,
                    now=NOW,
                    run_maintenance=False,
                )

            context = _context(output)
            self.assertEqual(len(context.splitlines()), 1)
            self.assertLessEqual(len(context), router.MINIMAL_CONTEXT_MAX_CHARS)
            self.assertFalse(state_dir.exists())

    def test_resume_reads_existing_plan_without_clobbering_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            router.create_scaffold(
                session_id="session-a",
                registration=_registration(root),
                facts=router.GitFacts("main", "b" * 40, (), 0, 0),
                transcript_path="D:/tmp/original.jsonl",
                state_dir=state_dir,
                now=NOW,
            )
            path = state_dir / "session_plan_session-a.json"
            original = json.loads(path.read_text(encoding="utf-8"))
            original["goal"] = "Preserve this goal"
            original["chain"] = ["executor"]
            state.write_session_plan("session-a", original, state_dir=state_dir)
            before = path.read_bytes()

            with (
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(
                    router,
                    "_git_facts",
                    return_value=router.GitFacts("main", "c" * 40, ("new-dirt",), 0, 0),
                ),
            ):
                output = router.handle_event(
                    _event(
                        source="resume",
                        cwd=root,
                        transcript_path="D:/tmp/replacement.jsonl",
                    ),
                    state_dir=state_dir,
                    now=NOW,
                    run_maintenance=False,
                )

            self.assertEqual(path.read_bytes(), before)
            self.assertIn("Preserve this goal", _context(output))
            loaded = state.read_session_plan("session-a", state_dir=state_dir)
            assert loaded is not None
            self.assertEqual(loaded["transcript_path"], "D:/tmp/original.jsonl")

    def test_compact_reinjects_goal_and_updated_at_without_clobber(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            router.create_scaffold(
                session_id="session-a",
                registration=_registration(root),
                facts=router.GitFacts("main", "d" * 40, (), 0, 0),
                transcript_path="D:/tmp/session-a.jsonl",
                state_dir=state_dir,
                now=NOW,
            )
            path = state_dir / "session_plan_session-a.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["goal"] = "Survive compaction"
            payload["updated_at"] = "2026-07-25T18:45:00Z"
            state.write_session_plan("session-a", payload, state_dir=state_dir)
            before = path.read_bytes()

            with mock.patch.object(router, "resolve_repository", return_value=_registration(root)):
                output = router.handle_event(
                    _event(source="compact", cwd=root),
                    state_dir=state_dir,
                    now=NOW,
                    run_maintenance=False,
                )

            context = _context(output)
            self.assertIn("Survive compaction", context)
            self.assertIn("2026-07-25T18:45:00Z", context)
            self.assertLessEqual(len(context), router.COMPACT_CONTEXT_MAX_CHARS)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("sessionTitle", output["hookSpecificOutput"])

    def test_compact_surfaces_but_does_not_consume_previous_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            router.create_scaffold(
                session_id="session-a",
                registration=_registration(root),
                facts=router.GitFacts("main", "d" * 40, (), 0, 0),
                transcript_path="D:/tmp/session-a.jsonl",
                state_dir=state_dir,
                now=NOW,
            )
            lifecycle.write_verdict(
                {
                    "schema_version": lifecycle.VERDICT_SCHEMA,
                    "session_id": "previous",
                    "repo": "dotclaude-ecosystem",
                    "verdict": "CHECKPOINT",
                    "created_at": "2026-07-25T17:00:00Z",
                    "surfaced_at": None,
                    "consumed_at": None,
                },
                state_dir=state_dir,
            )

            with mock.patch.object(router, "resolve_repository", return_value=_registration(root)):
                output = router.handle_event(
                    _event(source="compact", cwd=root),
                    state_dir=state_dir,
                    now=NOW,
                    run_maintenance=True,
                )

            self.assertIn("Previous unconsumed verdict: CHECKPOINT", _context(output))
            verdict = lifecycle.read_verdict(
                state_dir / "session_verdict_previous.json"
            )
            assert verdict is not None
            self.assertEqual(verdict["surfaced_at"], "2026-07-25T18:30:00Z")
            self.assertIsNone(verdict["consumed_at"])

    def test_resume_with_unseen_session_id_bootstraps_fork_without_parent_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            router.create_scaffold(
                session_id="parent",
                registration=_registration(root),
                facts=router.GitFacts("main", "e" * 40, (), 0, 0),
                transcript_path="D:/tmp/parent.jsonl",
                state_dir=state_dir,
                now=NOW,
            )
            parent_path = state_dir / "session_plan_parent.json"
            parent = json.loads(parent_path.read_text(encoding="utf-8"))
            parent["goal"] = "Parent-only goal"
            state.write_session_plan("parent", parent, state_dir=state_dir)
            parent_before = parent_path.read_bytes()

            with (
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(
                    router,
                    "_git_facts",
                    return_value=router.GitFacts("feature/fork", "f" * 40, (), 0, 0),
                ),
                mock.patch.object(router, "read_session_plan", wraps=state.read_session_plan) as read,
            ):
                output = router.handle_event(
                    _event(
                        session_id="forked",
                        source="resume",
                        cwd=root,
                        transcript_path="D:/tmp/forked.jsonl",
                    ),
                    state_dir=state_dir,
                    now=NOW,
                    run_maintenance=False,
                )

            forked = state.read_session_plan("forked", state_dir=state_dir)
            assert forked is not None
            self.assertEqual(forked["goal"], "")
            self.assertEqual(forked["transcript_path"], "D:/tmp/forked.jsonl")
            self.assertEqual(parent_path.read_bytes(), parent_before)
            self.assertFalse(any(call.args[0] == "parent" for call in read.call_args_list))
            self.assertNotIn("Parent-only goal", _context(output))
            self.assertIn("Best-effort declaration", _context(output))

    def test_undocumented_fork_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            output = router.handle_event(
                _event(source="fork", cwd=root),
                state_dir=root / "state",
                now=NOW,
                run_maintenance=False,
            )

            self.assertEqual(output, {})
            self.assertIn(
                "ROUTER_INVALID_INPUT",
                (root / "state" / "hook_errors.log").read_text(encoding="utf-8"),
            )

    def test_clear_creates_fresh_plan_but_does_not_emit_ignored_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(
                    router,
                    "_git_facts",
                    return_value=router.GitFacts("main", "1" * 40, (), 0, 0),
                ),
            ):
                output = router.handle_event(
                    _event(source="clear", cwd=root),
                    state_dir=root / "state",
                    now=NOW,
                    run_maintenance=False,
                )

            self.assertIsNotNone(state.read_session_plan("session-a", state_dir=root / "state"))
            self.assertNotIn("sessionTitle", output["hookSpecificOutput"])

    def test_existing_user_title_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = _event(source="startup", cwd=root)
            event["session_title"] = "Operator title"
            with (
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(
                    router,
                    "_git_facts",
                    return_value=router.GitFacts("main", "2" * 40, (), 0, 0),
                ),
            ):
                output = router.handle_event(
                    event,
                    state_dir=root / "state",
                    now=NOW,
                    run_maintenance=False,
                )

            self.assertNotIn("sessionTitle", output["hookSpecificOutput"])

    def test_registered_session_exports_exact_binding_for_explicit_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / "claude-env.sh"
            with (
                mock.patch.dict(os.environ, {"CLAUDE_ENV_FILE": str(env_file)}),
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(
                    router,
                    "_git_facts",
                    return_value=router.GitFacts("main", "2" * 40, (), 0, 0),
                ),
            ):
                router.handle_event(
                    _event(cwd=root),
                    state_dir=root / "state",
                    now=NOW,
                    run_maintenance=True,
                )

            self.assertEqual(
                env_file.read_text(encoding="utf-8"),
                "export CLAUDE_SESSION_PLAN_ID=session-a\n",
            )

    def test_full_and_minimal_character_budgets_are_hard_assertions(self):
        self.assertEqual(router.FULL_CONTEXT_MAX_CHARS, 2000)
        self.assertEqual(router.COMPACT_CONTEXT_MAX_CHARS, 1500)
        self.assertEqual(router.MINIMAL_CONTEXT_MAX_CHARS, 120)
        self.assertEqual(router.FULL_RUN_P95_TARGET_MS, 350)
        self.assertEqual(router.GENEROUS_WALL_TIME_CEILING_S, 1.5)

    def test_registered_run_stays_inside_generous_wall_time_ceiling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = time.perf_counter()
            with (
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(
                    router,
                    "_git_facts",
                    return_value=router.GitFacts("main", "3" * 40, (), 0, 0),
                ),
            ):
                router.handle_event(
                    _event(cwd=root),
                    state_dir=root / "state",
                    now=NOW,
                    run_maintenance=False,
                )
            elapsed = time.perf_counter() - started

            self.assertLess(elapsed, router.GENEROUS_WALL_TIME_CEILING_S)

    def test_registry_symlink_cannot_surface_content_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            plans = root / "design" / "plans"
            plans.mkdir(parents=True)
            outside = Path(tmp) / "outside.md"
            outside.write_text(
                "---\ntitle: ATTACKER INSTRUCTION\nstatus: in-progress\n---\n",
                encoding="utf-8",
            )
            link = plans / "outside.md"
            try:
                link.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            active = router._active_plans(_registration(root))

            self.assertEqual(active, [])

    def test_real_cli_startup_with_maintenance_stays_bounded_and_reaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()

            def git(*args: str) -> str:
                result = subprocess.run(
                    ["git", "-C", str(root), *args],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    check=True,
                )
                return result.stdout.strip()

            git("init", "-b", "main")
            git("config", "user.name", "Session Router Tests")
            git("config", "user.email", "session-router@example.invalid")
            (root / "tracked.txt").write_text("base\n", encoding="utf-8")
            git("add", "tracked.txt")
            git("commit", "-m", "base")
            git("update-ref", "refs/remotes/origin/main", git("rev-parse", "HEAD"))

            state_dir = Path(tmp) / "state"
            state_dir.mkdir()
            old = time.time() - 10 * 24 * 60 * 60
            for index in range(200):
                counter = state_dir / f"turn_counter_old-{index}"
                counter.write_text("1", encoding="utf-8")
                os.utime(counter, (old, old))
            registry = Path(tmp) / "registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": state.SESSION_REGISTRY_SCHEMA,
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
            event = _event(
                cwd=root,
                transcript_path=str((Path(tmp) / "session.jsonl").resolve()),
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "CLAUDE_SESSION_REGISTRY": str(registry),
                    "CLAUDE_SESSION_STATE_DIR": str(state_dir),
                    "CLAUDE_ENV_FILE": str(Path(tmp) / "claude-env.sh"),
                }
            )

            started = time.perf_counter()
            result = subprocess.run(
                [sys.executable, str(_SCRIPTS / "session_router.py")],
                input=json.dumps(event),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=router.GENEROUS_WALL_TIME_CEILING_S,
                check=False,
                env=environment,
            )
            elapsed = time.perf_counter() - started

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("hookSpecificOutput", json.loads(result.stdout))
            self.assertLess(elapsed, router.GENEROUS_WALL_TIME_CEILING_S)
            self.assertLess(len(list(state_dir.glob("turn_counter_old-*"))), 200)

    def test_invalid_event_fails_open_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            output = router.handle_event(
                {"hook_event_name": "SessionStart"},
                state_dir=state_dir,
                now=NOW,
                run_maintenance=False,
            )
            self.assertEqual(output, {})
            self.assertIn(
                "ROUTER_INVALID_INPUT",
                (state_dir / "hook_errors.log").read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
