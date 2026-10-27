#!/usr/bin/env python3
"""Tests for supervisor-contract injection and the SessionStart lane probe."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import session_router as router  # noqa: E402
import session_state as state  # noqa: E402


NOW = datetime(2026, 7, 25, 18, 30, tzinfo=UTC)
_DISPATCH = "D:/APPS/_shared/dispatch/dispatch.py"
_MISSING = (
    "SUPERVISOR CONTRACT MISSING: install ~/.claude/refs/supervisor-contract.md "
    "(see dotclaude-ecosystem templates/supervisor-contract.md). "
    "Do not route work to Claude workers."
)
_CONTRACT_TEXT = (
    "Supervisor contract (binding, enforced by hooks)\n"
    "Tier 2 coordinator sentinel for verbatim injection.\n"
)
_COORDINATOR_LINE = (
    "You are a Tier-2 coordinator: all code, tests, reviews and diagnosis go "
    "through `dispatch.py lane`; you only relay, commit and glue."
)
_DOOR = (
    "python D:/APPS/_shared/dispatch/dispatch.py lane "
    "<impl|review|grill|plan|diagnose> --brief FILE "
    "[--repo R --ref SHA --pr N --worktree PATH --author-family F "
    "--risk R0..R3 --verify-cmd CMD]"
)
_HARD_RULES = (
    "The supervisor writes no code, does no review and no diagnosis",
    "NEVER fall back to Claude",
    "Free lanes before quota lanes",
    "Every quota hit or DOWN lane is reported to the operator in the same turn, one line.",
    "overrides only via the operator-run `lane_authorize.py --interactive`",
)
_ROLE_LINES = (
    "- impl = ",
    "- review = ",
    "- grill = ",
    "- plan / top decision = ",
    "- diagnose = ",
)


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


@contextmanager
def _dispatch_present():
    """Treat the lane door as installed so probe tests reach Popen."""

    original = Path.is_file

    def is_file(self: Path, *args: object, **kwargs: object) -> bool:
        normalized = os.fspath(self).replace("\\", "/").lower()
        if normalized == "d:/apps/_shared/dispatch/dispatch.py":
            return True
        return original(self, *args, **kwargs)

    with mock.patch.object(Path, "is_file", is_file):
        yield


def _probe_env(state_dir: Path, **extra: str) -> dict[str, str]:
    env = {
        "CLAUDE_SESSION_STATE_DIR": str(state_dir),
        "SESSION_ROUTER_NO_PROBE": "",
    }
    env.update(extra)
    return env


def _run_main(
    source: str,
    state_dir: Path,
    env: dict[str, str],
    *,
    popen_side_effect: BaseException | None = None,
) -> tuple[int, str, mock.MagicMock]:
    root = state_dir.parent
    event = _event(source=source, cwd=root)
    stdout = io.StringIO()
    with (
        mock.patch.dict(os.environ, env, clear=False),
        mock.patch.object(router, "resolve_repository", return_value=None),
        mock.patch.object(router, "read_stdin_text", return_value=json.dumps(event)),
        _dispatch_present(),
        mock.patch.object(router.subprocess, "Popen") as popen,
        redirect_stdout(stdout),
    ):
        if popen_side_effect is not None:
            popen.side_effect = popen_side_effect
        code = router.main()
    return code, stdout.getvalue(), popen


def _assert_probe_spawn(testcase: unittest.TestCase, popen: mock.MagicMock) -> None:
    testcase.assertEqual(popen.call_count, 1)
    args, kwargs = popen.call_args
    testcase.assertEqual(args[0], ["py", _DISPATCH, "lane", "probe", "--all"])
    testcase.assertIs(kwargs["stdin"], subprocess.DEVNULL)
    testcase.assertIs(kwargs["stdout"], subprocess.DEVNULL)
    testcase.assertIs(kwargs["stderr"], subprocess.DEVNULL)
    testcase.assertTrue(kwargs["close_fds"])
    if sys.platform == "win32":
        testcase.assertEqual(
            kwargs["creationflags"],
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    popen.return_value.wait.assert_not_called()


class TestSessionRouterContract(unittest.TestCase):
    def setUp(self) -> None:
        router._contract_cache.clear()

    def tearDown(self) -> None:
        router._contract_cache.clear()

    def test_additional_context_starts_with_contract_for_every_source(self) -> None:
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / "repo"
                    root.mkdir()
                    contract_path = root / "supervisor-contract.md"
                    contract_path.write_bytes(_CONTRACT_TEXT.encode("utf-8"))
                    state_dir = root / "state"
                    with (
                        mock.patch.dict(
                            os.environ,
                            {"SUPERVISOR_CONTRACT_PATH": str(contract_path)},
                        ),
                        mock.patch.object(
                            router,
                            "resolve_repository",
                            return_value=_registration(root),
                        ),
                        mock.patch.object(
                            router,
                            "_git_facts",
                            return_value=router.GitFacts("main", "a" * 40, (), 0, 0),
                        ),
                        mock.patch.object(router, "_record_worktree_start"),
                    ):
                        router._contract_cache.clear()
                        output = router.handle_event(
                            _event(source=source, cwd=root),
                            state_dir=state_dir,
                            now=NOW,
                            run_maintenance=False,
                        )

                context = _context(output)
                self.assertTrue(context.startswith(_CONTRACT_TEXT))
                rest = context[len(_CONTRACT_TEXT) :]
                if source == "compact":
                    self.assertIn(
                        "No valid session scratch file survived compaction.",
                        rest,
                    )
                else:
                    self.assertIn("model chooses", rest)

    def test_missing_contract_keeps_missing_line_and_the_rest_of_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            missing = root / "no-such-supervisor-contract.md"
            with (
                mock.patch.dict(os.environ, {"SUPERVISOR_CONTRACT_PATH": str(missing)}),
                mock.patch.object(router, "resolve_repository", return_value=_registration(root)),
                mock.patch.object(
                    router,
                    "_git_facts",
                    return_value=router.GitFacts("main", "b" * 40, (), 0, 0),
                ),
                mock.patch.object(router, "_record_worktree_start"),
            ):
                router._contract_cache.clear()
                output = router.handle_event(
                    _event(cwd=root),
                    state_dir=root / "state",
                    now=NOW,
                    run_maintenance=False,
                )

        context = _context(output)
        self.assertTrue(context.startswith(_MISSING + "\n"))
        self.assertIn("model chooses", context[len(_MISSING) :])

    def test_repo_contract_stays_within_40_lines_and_required_clauses(self) -> None:
        path = _SCRIPTS.parent / "templates" / "supervisor-contract.md"
        text = path.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 40)
        for rule in _HARD_RULES:
            self.assertIn(rule, text)
        self.assertIn(_COORDINATOR_LINE, text)
        self.assertIn(_DOOR, text)
        for line in _ROLE_LINES:
            self.assertIn(line, text)

    def test_probe_skipped_when_no_probe_env_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            code, stdout, popen = _run_main(
                "startup",
                state_dir,
                _probe_env(state_dir, SESSION_ROUTER_NO_PROBE="1"),
            )
        self.assertEqual(code, 0)
        json.loads(stdout)
        self.assertEqual(popen.call_count, 0)

    def test_probe_skipped_when_debounce_file_is_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            state_dir.mkdir()
            (state_dir / "lane_probe_last.txt").write_bytes(b"fresh\n")
            code, stdout, popen = _run_main("resume", state_dir, _probe_env(state_dir))
        self.assertEqual(code, 0)
        json.loads(stdout)
        self.assertEqual(popen.call_count, 0)

    def test_probe_attempted_for_startup_and_resume(self) -> None:
        for source in ("startup", "resume"):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as tmp:
                    state_dir = Path(tmp) / "state"
                    code, stdout, popen = _run_main(source, state_dir, _probe_env(state_dir))
                self.assertEqual(code, 0)
                json.loads(stdout)
                _assert_probe_spawn(self, popen)

    def test_probe_never_spawned_for_compact_or_clear(self) -> None:
        for source in ("compact", "clear"):
            with self.subTest(source=source):
                with tempfile.TemporaryDirectory() as tmp:
                    state_dir = Path(tmp) / "state"
                    code, _stdout, popen = _run_main(source, state_dir, _probe_env(state_dir))
                self.assertEqual(code, 0)
                self.assertEqual(popen.call_count, 0)

    def test_probe_popen_failure_is_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            code, stdout, popen = _run_main(
                "startup",
                state_dir,
                _probe_env(state_dir),
                popen_side_effect=OSError("spawn failed"),
            )
        self.assertEqual(code, 0)
        self.assertEqual(popen.call_count, 1)
        json.loads(stdout)

    def test_handle_event_does_not_spawn_the_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                mock.patch.object(router, "resolve_repository", return_value=None),
                mock.patch.object(router.subprocess, "Popen") as popen,
            ):
                for source in ("startup", "resume", "clear", "compact"):
                    router.handle_event(
                        _event(source=source, cwd=root),
                        state_dir=root / "state",
                        now=NOW,
                        run_maintenance=False,
                    )
        self.assertEqual(popen.call_count, 0)

    def test_unset_contract_path_with_empty_home_resolves_template(self) -> None:
        template = (_SCRIPTS.parent / "templates" / "supervisor-contract.md").read_text(
            encoding="utf-8"
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            ref = home / ".claude" / "refs" / "supervisor-contract.md"
            self.assertFalse(ref.exists())
            with mock.patch.dict(os.environ):
                os.environ.pop("SUPERVISOR_CONTRACT_PATH", None)
                router._contract_cache.clear()
                self.assertNotIn("SUPERVISOR_CONTRACT_PATH", os.environ)
                resolved = router._supervisor_contract(home=home)
            self.assertFalse(ref.exists())
            self.assertEqual(resolved, template)

    def test_debounce_marker_is_written_before_popen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            marker = state_dir / "lane_probe_last.txt"
            self.assertFalse(marker.exists())
            seen: dict[str, int] = {}

            def tracking_popen(*_args: object, **_kwargs: object) -> mock.MagicMock:
                # Recorded here and asserted after main(); the probe swallows exceptions.
                seen["size"] = marker.stat().st_size if marker.exists() else 0
                return mock.MagicMock()

            root = state_dir.parent
            event = _event(source="startup", cwd=root)
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, _probe_env(state_dir), clear=False),
                mock.patch.object(router, "resolve_repository", return_value=None),
                mock.patch.object(router, "read_stdin_text", return_value=json.dumps(event)),
                _dispatch_present(),
                mock.patch.object(
                    router.subprocess, "Popen", side_effect=tracking_popen
                ) as popen,
                redirect_stdout(stdout),
            ):
                code = router.main()
        self.assertEqual(code, 0)
        json.loads(stdout.getvalue())
        self.assertGreater(seen["size"], 0)
        _assert_probe_spawn(self, popen)

    def test_main_startup_error_path_injects_contract_and_empty_event_prints_empty(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            contract_path = Path(tmp) / "supervisor-contract.md"
            contract_path.write_bytes(_CONTRACT_TEXT.encode("utf-8"))
            env = {
                "SUPERVISOR_CONTRACT_PATH": str(contract_path),
                "SESSION_ROUTER_NO_PROBE": "1",
            }

            # Startup payload that makes handle_event raise internally (bad transcript_path / missing fields)
            bad_event = {"source": "startup", "transcript_path": 123}
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env, clear=False),
                mock.patch.object(
                    router, "read_stdin_text", return_value=json.dumps(bad_event)
                ),
                redirect_stdout(stdout),
            ):
                router._contract_cache.clear()
                code = router.main()
            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertTrue(_context(output).startswith(_CONTRACT_TEXT))

            # Startup payload where resolve_repository raises inside handle_event
            root = Path(tmp) / "repo"
            root.mkdir()
            event = _event(source="startup", cwd=root)
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env, clear=False),
                mock.patch.object(
                    router,
                    "resolve_repository",
                    side_effect=RuntimeError("resolve failed"),
                ),
                mock.patch.object(
                    router, "read_stdin_text", return_value=json.dumps(event)
                ),
                redirect_stdout(stdout),
            ):
                router._contract_cache.clear()
                code = router.main()
            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertTrue(_context(output).startswith(_CONTRACT_TEXT))

            # Startup payload with handle_event monkeypatched to return empty output
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env, clear=False),
                mock.patch.object(router, "handle_event", return_value={}),
                mock.patch.object(
                    router,
                    "read_stdin_text",
                    return_value=json.dumps({"source": "startup"}),
                ),
                redirect_stdout(stdout),
            ):
                router._contract_cache.clear()
                code = router.main()
            self.assertEqual(code, 0)
            output = json.loads(stdout.getvalue())
            self.assertTrue(_context(output).startswith(_CONTRACT_TEXT))

            # Empty event still prints {}
            stdout = io.StringIO()
            with (
                mock.patch.dict(os.environ, env, clear=False),
                mock.patch.object(router, "read_stdin_text", return_value="{}"),
                redirect_stdout(stdout),
            ):
                router._contract_cache.clear()
                code = router.main()
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue()), {})
            self.assertEqual(stdout.getvalue().strip(), "{}")

