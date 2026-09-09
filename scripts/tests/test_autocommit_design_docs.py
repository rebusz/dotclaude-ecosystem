#!/usr/bin/env python3
"""Regression tests for the 2026-09-09 audit findings P1-2, P1-3 and P1-14.

The hook that commits and pushes was the one hook in the tree with no test file
at all, which is how three defects survived in it at once:

  1. `git commit -m <msg>` carried no pathspec, so anything the operator had
     staged was swallowed into a "docs: auto-backup" commit and pushed with it.
     Live at audit time: three `agent-rules/` files sat staged in the primary
     checkout waiting for the next design-doc write.
  2. `PROTECTED_BRANCHES` was consulted only by `_can_amend`, so a design doc
     written while on `main` produced a commit and a `git push origin HEAD`
     onto the trunk the live trading stack runs from.
  3. Hook stdin was decoded as cp1252 on a default Windows Python, so any
     non-ASCII path arrived mojibaked and silently failed to resolve on disk.

These drive the real script as the harness does — a subprocess fed JSON on
stdin, against real git repositories with a real local bare origin. Nothing is
mocked; a test that stubbed out the commit would pass while the bug was live.
The mirror is disabled via AUTOCOMMIT_DESIGN_NO_MAIN so the tests stay offline;
the mirror path has its own bounded-deadline unit test below.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import autocommit_design_docs as hook  # noqa: E402  (sys.path must be set first)

_HOOK = _SCRIPTS / "autocommit_design_docs.py"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    # Decode explicitly: bare `text=True` uses the locale encoding (cp1252 on
    # this box), which would mojibake git's output and make the UTF-8
    # assertions below fail against a correct commit.
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def _run_hook(repo: Path, doc: Path, *, mirror: bool = False) -> subprocess.CompletedProcess:
    """Invoke the hook exactly as the PostToolUse harness does."""
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(doc)}}
    ).encode("utf-8")
    env = dict(os.environ)
    if not mirror:
        env["AUTOCOMMIT_DESIGN_NO_MAIN"] = "1"
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=payload,
        cwd=repo,
        capture_output=True,
        timeout=120,
        env=env,
        check=False,
    )


class _Repo:
    """A real repo with a real bare origin, on a non-protected branch."""

    def __init__(self, stack: tempfile.TemporaryDirectory, branch: str = "work") -> None:
        root = Path(stack.name)
        self.origin = root / "origin.git"
        self.repo = root / "repo"
        subprocess.run(
            ["git", "init", "--bare", "-q", str(self.origin)], check=True, timeout=60
        )
        subprocess.run(
            ["git", "clone", "-q", str(self.origin), str(self.repo)], check=True, timeout=60
        )
        _git(self.repo, "config", "user.email", "test@example.invalid")
        _git(self.repo, "config", "user.name", "Test")
        _git(self.repo, "config", "commit.gpgsign", "false")
        # Without this git renders a non-ASCII path as "...modu\305\202.md",
        # which would make the UTF-8 assertions below compare quoting, not paths.
        _git(self.repo, "config", "core.quotePath", "false")
        (self.repo / "design" / "plans").mkdir(parents=True)
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        _git(self.repo, "add", "README.md")
        _git(self.repo, "commit", "-qm", "seed")
        _git(self.repo, "branch", "-M", "main")
        _git(self.repo, "push", "-q", "-u", "origin", "main")
        if branch != "main":
            _git(self.repo, "checkout", "-qb", branch)

    def head_paths(self) -> list[str]:
        out = _git(self.repo, "show", "--pretty=format:", "--name-only", "HEAD").stdout
        return sorted(p for p in out.split() if p)

    def head_subject(self) -> str:
        return _git(self.repo, "log", "-1", "--format=%s").stdout.strip()

    def staged(self) -> list[str]:
        return sorted(
            p for p in _git(self.repo, "diff", "--cached", "--name-only").stdout.split() if p
        )

    def count(self, ref: str = "HEAD") -> int:
        out = _git(self.repo, "rev-list", "--count", ref).stdout.strip()
        return int(out or 0)


class CommitScopeTests(unittest.TestCase):
    """P1-2 — the commit must contain the design doc and nothing else."""

    def setUp(self) -> None:
        self.stack = tempfile.TemporaryDirectory()
        self.addCleanup(self.stack.cleanup)
        self.r = _Repo(self.stack)

    def test_unrelated_staged_file_is_not_swallowed(self) -> None:
        (self.r.repo / "secrets.env").write_text("TOKEN=must-not-leak\n", encoding="utf-8")
        _git(self.r.repo, "add", "secrets.env")
        self.assertEqual(self.r.staged(), ["secrets.env"], "precondition")

        doc = self.r.repo / "design" / "plans" / "p.md"
        doc.write_text("# plan\n", encoding="utf-8")
        result = _run_hook(self.r.repo, doc)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.r.head_paths(), ["design/plans/p.md"])
        self.assertEqual(self.r.head_subject(), "docs: auto-backup p.md")
        # The operator's staged work is still staged, untouched.
        self.assertEqual(self.r.staged(), ["secrets.env"])

    def test_unrelated_unstaged_file_is_not_committed(self) -> None:
        (self.r.repo / "scratch.txt").write_text("wip\n", encoding="utf-8")
        doc = self.r.repo / "design" / "plans" / "p.md"
        doc.write_text("# plan\n", encoding="utf-8")

        _run_hook(self.r.repo, doc)

        self.assertEqual(self.r.head_paths(), ["design/plans/p.md"])

    def test_consecutive_backups_of_one_file_collapse_to_one_commit(self) -> None:
        doc = self.r.repo / "design" / "plans" / "p.md"
        doc.write_text("# v1\n", encoding="utf-8")
        _run_hook(self.r.repo, doc)
        after_first = self.r.count()

        doc.write_text("# v2\n", encoding="utf-8")
        _run_hook(self.r.repo, doc)

        self.assertEqual(self.r.count(), after_first, "second backup should amend")
        self.assertEqual(self.r.head_paths(), ["design/plans/p.md"])

    def test_amend_does_not_swallow_the_index_either(self) -> None:
        """`commit --amend -- <path>` rebuilds from HEAD's parent plus the named
        paths, which is different enough from the plain form to need its own
        guard: this is the branch that rewrites history."""
        doc = self.r.repo / "design" / "plans" / "p.md"
        doc.write_text("# v1\n", encoding="utf-8")
        _run_hook(self.r.repo, doc)

        (self.r.repo / "secrets.env").write_text("TOKEN=must-not-leak\n", encoding="utf-8")
        _git(self.r.repo, "add", "secrets.env")
        doc.write_text("# v2\n", encoding="utf-8")
        _run_hook(self.r.repo, doc)

        self.assertEqual(self.r.head_paths(), ["design/plans/p.md"])
        self.assertEqual(self.r.staged(), ["secrets.env"])


class ProtectedBranchTests(unittest.TestCase):
    """P1-3 — never commit or push onto a shared trunk from a tool-call hook."""

    def setUp(self) -> None:
        self.stack = tempfile.TemporaryDirectory()
        self.addCleanup(self.stack.cleanup)

    def test_no_commit_and_no_push_on_main(self) -> None:
        r = _Repo(self.stack, branch="main")
        before_local = r.count()
        before_remote = _git(r.repo, "rev-parse", "origin/main").stdout.strip()

        doc = r.repo / "design" / "plans" / "p.md"
        doc.write_text("# plan\n", encoding="utf-8")
        result = _run_hook(r.repo, doc)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(r.count(), before_local, "main must not gain a commit")
        _git(r.repo, "fetch", "-q", "origin")
        self.assertEqual(
            _git(r.repo, "rev-parse", "origin/main").stdout.strip(),
            before_remote,
            "the trunk must not move",
        )
        self.assertIn("no branch commit on 'main'", result.stderr.decode("utf-8", "replace"))

    def test_no_commit_on_detached_head(self) -> None:
        r = _Repo(self.stack)
        _git(r.repo, "checkout", "-q", "--detach")
        before = _git(r.repo, "rev-parse", "HEAD").stdout.strip()

        doc = r.repo / "design" / "plans" / "p.md"
        doc.write_text("# plan\n", encoding="utf-8")
        result = _run_hook(r.repo, doc)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_git(r.repo, "rev-parse", "HEAD").stdout.strip(), before)

    def test_branch_predicate_covers_every_refusal(self) -> None:
        for branch, ok in (
            ("work", True),
            ("claude/audit", True),
            ("main", False),
            ("master", False),
            ("develop", False),
            ("HEAD", False),
            ("", False),
        ):
            with self.subTest(branch=branch):
                self.assertIs(hook._branch_accepts_backup_commit(branch), ok)


class StdinDecodingTests(unittest.TestCase):
    """P1-14 — hook stdin is UTF-8, whatever the console codepage says."""

    def setUp(self) -> None:
        self.stack = tempfile.TemporaryDirectory()
        self.addCleanup(self.stack.cleanup)
        self.r = _Repo(self.stack)

    def test_non_ascii_path_survives_a_cp1252_console(self) -> None:
        name = "plan-wykonawczy-moduł.md"
        doc = self.r.repo / "design" / "plans" / name
        doc.write_text("# plan\n", encoding="utf-8")

        env_result = _run_hook(self.r.repo, doc)

        self.assertEqual(env_result.returncode, 0, env_result.stderr)
        self.assertEqual(self.r.head_paths(), [f"design/plans/{name}"])

    def test_forced_cp1252_stdio_still_commits(self) -> None:
        """The failure mode was environmental, so pin the environment too."""
        name = "notatka-moduł.md"
        doc = self.r.repo / "design" / "plans" / name
        doc.write_text("# plan\n", encoding="utf-8")

        payload = json.dumps(
            {"tool_name": "Write", "tool_input": {"file_path": str(doc)}}
        ).encode("utf-8")
        env = dict(os.environ, AUTOCOMMIT_DESIGN_NO_MAIN="1", PYTHONIOENCODING="cp1252")
        env.pop("PYTHONUTF8", None)
        result = subprocess.run(
            [sys.executable, str(_HOOK)],
            input=payload,
            cwd=self.r.repo,
            capture_output=True,
            timeout=120,
            env=env,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.r.head_paths(), [f"design/plans/{name}"])


class PushReportingTests(unittest.TestCase):
    """A push that fails must say so instead of reporting 'commit + push'."""

    def setUp(self) -> None:
        self.stack = tempfile.TemporaryDirectory()
        self.addCleanup(self.stack.cleanup)
        self.r = _Repo(self.stack)

    def test_failed_push_is_reported_and_the_hook_still_fails_open(self) -> None:
        _git(self.r.repo, "remote", "set-url", "origin", str(Path(self.stack.name) / "gone.git"))
        doc = self.r.repo / "design" / "plans" / "p.md"
        doc.write_text("# plan\n", encoding="utf-8")

        result = _run_hook(self.r.repo, doc)

        self.assertEqual(result.returncode, 0, "hooks must never break the session")
        self.assertIn("push FAILED", result.stderr.decode("utf-8", "replace"))
        # The local backup — the whole point of the hook — still happened.
        self.assertEqual(self.r.head_paths(), ["design/plans/p.md"])

    def test_amended_push_uses_force_with_lease_not_force(self) -> None:
        doc = self.r.repo / "design" / "plans" / "p.md"
        doc.write_text("# v1\n", encoding="utf-8")
        first = _run_hook(self.r.repo, doc)
        self.assertIn("pushed", first.stderr.decode("utf-8", "replace"))

        # The amend rewrites the already-pushed tip, so the plain push is
        # rejected and the lease-guarded fallback is what actually lands it.
        doc.write_text("# v2\n", encoding="utf-8")
        second = _run_hook(self.r.repo, doc)

        self.assertIn("pushed (lease)", second.stderr.decode("utf-8", "replace"))
        self.assertEqual(
            _git(self.r.repo, "rev-parse", "HEAD").stdout.strip(),
            _git(self.r.repo, "rev-parse", "origin/work").stdout.strip(),
        )
        source = (_SCRIPTS / "autocommit_design_docs.py").read_text(encoding="utf-8")
        self.assertNotIn(
            '"--force"', source,
            "a bare --force would discard a parallel session's work",
        )

    def test_successful_push_reaches_the_remote(self) -> None:
        doc = self.r.repo / "design" / "plans" / "p.md"
        doc.write_text("# plan\n", encoding="utf-8")

        result = _run_hook(self.r.repo, doc)

        self.assertIn("pushed", result.stderr.decode("utf-8", "replace"))
        self.assertEqual(
            _git(self.r.repo, "rev-parse", "HEAD").stdout.strip(),
            _git(self.r.repo, "rev-parse", "origin/work").stdout.strip(),
        )


class DeadlineTests(unittest.TestCase):
    """The 30s PostToolUse ceiling is enforced by us, not by SIGKILL."""

    def test_expired_budget_skips_the_push_instead_of_blocking(self) -> None:
        self.assertEqual(
            hook._push("unused", False, time.monotonic() - 1), "push skipped: deadline"
        )

    def test_expired_budget_stops_the_mirror_retry_loop(self) -> None:
        stack = tempfile.TemporaryDirectory()
        self.addCleanup(stack.cleanup)
        r = _Repo(stack)
        doc = r.repo / "design" / "plans" / "p.md"
        doc.write_text("# plan\n", encoding="utf-8")
        _git(r.repo, "add", "--", "design/plans/p.md")
        _git(r.repo, "commit", "-qm", "seed doc")

        status = hook._mirror_to_docs_branch(
            str(r.repo), "design/plans/p.md", str(doc), "subject", time.monotonic() - 1
        )

        self.assertEqual(status, "mirror deadline")

    def test_a_git_timeout_is_a_failed_call_not_an_exception(self) -> None:
        """Letting TimeoutExpired escape would abort main() wherever it landed,
        and the module-level `except Exception: pass` would hide it — leaving
        the document staged with no commit and no message."""
        stack = tempfile.TemporaryDirectory()
        self.addCleanup(stack.cleanup)
        r = _Repo(stack)
        # cap=0 floors the timeout at 0.5s. `git log -S` with a regex over the
        # whole history is slow enough to trip it and cannot mutate anything.
        result = hook._git(
            ["log", "--all", "-S", "x", "--pickaxe-regex", "--", "."],
            cwd=str(r.repo),
            cap=0.0,
        )
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertIn(result.returncode, (0, 124))

    def test_timeout_result_is_reported_as_a_failure(self) -> None:
        timed_out = hook._timed_out(["commit", "-m", "x"])
        self.assertNotEqual(timed_out.returncode, 0)
        self.assertIn("timed out", timed_out.stderr)

    def test_remaining_is_unbounded_for_callers_that_pass_no_deadline(self) -> None:
        self.assertEqual(hook._remaining(None), hook.GIT_CALL_CAP_S)


if __name__ == "__main__":
    unittest.main()
