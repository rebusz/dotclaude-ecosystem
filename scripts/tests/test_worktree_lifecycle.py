from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import worktree_lifecycle as lifecycle  # noqa: E402


NOW = datetime(2026, 8, 6, 15, 30, tzinfo=UTC)


def _metadata(root: Path, **overrides: object) -> lifecycle.WorktreeMetadata:
    values: dict[str, object] = {
        "root": str(root.resolve(strict=False)),
        "head": "a" * 40,
        "branch": "feature",
        "primary": False,
        "locked": False,
        "lock_reason": "",
        "prunable": False,
        "prune_reason": "",
    }
    values.update(overrides)
    return lifecycle.WorktreeMetadata(**values)  # type: ignore[arg-type]


class TestWorktreePorcelain(unittest.TestCase):
    def test_parse_preserves_primary_detached_lock_and_prunable_metadata(self):
        payload = "\n".join(
            [
                "worktree D:/repo",
                f"HEAD {'a' * 40}",
                "branch refs/heads/main",
                "",
                "worktree D:/repo-wt",
                f"HEAD {'b' * 40}",
                "detached",
                "locked active-session",
                "prunable gitdir file points to non-existent location",
                "",
            ]
        )

        entries = lifecycle.parse_worktree_porcelain(payload)

        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[0].primary)
        self.assertEqual(entries[0].branch, "main")
        self.assertFalse(entries[1].primary)
        self.assertIsNone(entries[1].branch)
        self.assertTrue(entries[1].locked)
        self.assertEqual(entries[1].lock_reason, "active-session")
        self.assertTrue(entries[1].prunable)

    def test_current_metadata_uses_direct_git_dirs_and_lock_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "linked"
            git_dir = Path(tmp) / "common" / ".git" / "worktrees" / "linked"
            common_dir = Path(tmp) / "common" / ".git"
            root.mkdir()
            git_dir.mkdir(parents=True)
            (git_dir / "locked").write_text("active-session", encoding="utf-8")
            completed = mock.Mock(
                returncode=0,
                stdout=f"{git_dir}\n{common_dir}\n",
                stderr="",
            )
            with mock.patch.object(lifecycle, "_run_git", return_value=completed) as run_git:
                metadata = lifecycle.read_current_worktree_metadata(
                    root,
                    head="b" * 40,
                    branch="feature",
                )

            self.assertFalse(metadata.primary)
            self.assertTrue(metadata.locked)
            self.assertEqual(metadata.lock_reason, "active-session")
            self.assertEqual(metadata.branch, "feature")
            self.assertEqual(
                run_git.call_args.args[1],
                ["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"],
            )

    def test_current_metadata_recognizes_primary_and_detached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "primary"
            git_dir = root / ".git"
            git_dir.mkdir(parents=True)
            completed = mock.Mock(
                returncode=0,
                stdout=f"{git_dir}\n{git_dir}\n",
                stderr="",
            )
            with mock.patch.object(lifecycle, "_run_git", return_value=completed):
                metadata = lifecycle.read_current_worktree_metadata(
                    root,
                    head="b" * 40,
                    branch="(detached)",
                )

            self.assertTrue(metadata.primary)
            self.assertIsNone(metadata.branch)


class TestTerminalClassification(unittest.TestCase):
    def test_fail_closed_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ordinary = _metadata(root)
            cases = [
                (
                    dict(
                        git_ok=False,
                        dirty_paths=(),
                        work_reached_trunk=True,
                        metadata=ordinary,
                    ),
                    lifecycle.UNKNOWN_PRESERVE,
                ),
                (
                    dict(
                        git_ok=True,
                        dirty_paths=(),
                        work_reached_trunk=True,
                        metadata=_metadata(root, primary=True),
                    ),
                    lifecycle.PRESERVE_PRIMARY,
                ),
                (
                    dict(
                        git_ok=True,
                        dirty_paths=(),
                        work_reached_trunk=True,
                        metadata=_metadata(root, locked=True),
                    ),
                    lifecycle.LOCKED_CUSTODY,
                ),
                (
                    dict(
                        git_ok=True,
                        dirty_paths=("operator.txt",),
                        work_reached_trunk=True,
                        metadata=ordinary,
                    ),
                    lifecycle.DIRTY_CUSTODY,
                ),
                (
                    dict(
                        git_ok=True,
                        dirty_paths=(),
                        work_reached_trunk=False,
                        metadata=ordinary,
                    ),
                    lifecycle.COMMITTED_UNMERGED_CUSTODY,
                ),
                (
                    dict(
                        git_ok=True,
                        dirty_paths=(),
                        work_reached_trunk=True,
                        metadata=ordinary,
                    ),
                    lifecycle.ELIGIBLE_MERGED_REMOVE,
                ),
                (
                    dict(
                        git_ok=True,
                        dirty_paths=(),
                        work_reached_trunk=True,
                        metadata=_metadata(root, branch=None),
                    ),
                    lifecycle.ELIGIBLE_DETACHED_REMOVE,
                ),
            ]
            for kwargs, expected in cases:
                with self.subTest(expected=expected):
                    self.assertEqual(lifecycle.classify_terminal(**kwargs), expected)


class TestCustodyRecords(unittest.TestCase):
    def test_close_record_is_bounded_hashed_and_updates_current_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo-wt"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            with mock.patch.object(
                lifecycle,
                "read_current_worktree_metadata",
                return_value=_metadata(root),
            ):
                path = lifecycle.record_session_close(
                    session_id="session-a",
                    repo="repo",
                    worktree_root=root,
                    head="a" * 40,
                    branch="feature",
                    dirty_paths=(),
                    work_reached_trunk=True,
                    git_ok=True,
                    owner_runtime="codex",
                    lifecycle_verdict="ARCHIVE-OK",
                    state_dir=state_dir,
                    now=NOW,
                )

            self.assertIsNotNone(path)
            assert path is not None
            payload = lifecycle.load_receipt(path)
            self.assertEqual(payload["disposition"], lifecycle.ELIGIBLE_MERGED_REMOVE)
            self.assertEqual(payload["receipt_sha256"], lifecycle.receipt_sha256(payload))
            projections = list((state_dir / "worktree_lifecycle").glob("worktree_*.json"))
            self.assertEqual(len(projections), 1)
            self.assertEqual(json.loads(projections[0].read_text()), payload)

    def test_recorder_fails_open_when_metadata_capture_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            with mock.patch.object(
                lifecycle,
                "read_current_worktree_metadata",
                side_effect=RuntimeError("boom"),
            ):
                result = lifecycle.record_session_start(
                    session_id="session-a",
                    repo="repo",
                    worktree_root=Path(tmp),
                    head="a" * 40,
                    branch="main",
                    dirty_paths=(),
                    owner_runtime="codex",
                    state_dir=state_dir,
                    now=NOW,
                )
            self.assertIsNone(result)
            errors = (state_dir / "hook_errors.log").read_text(encoding="utf-8")
            self.assertIn("WORKTREE_START_RECORD_FAILED", errors)

    def test_hook_metadata_capture_uses_bounded_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo-wt"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            with mock.patch.object(
                lifecycle,
                "read_current_worktree_metadata",
                return_value=_metadata(root),
            ) as read_metadata:
                lifecycle.record_session_start(
                    session_id="session-a",
                    repo="repo",
                    worktree_root=root,
                    head="a" * 40,
                    branch="feature",
                    dirty_paths=(),
                    owner_runtime="codex",
                    state_dir=state_dir,
                    now=NOW,
                )

            self.assertEqual(
                read_metadata.call_args.kwargs["timeout_s"],
                lifecycle.HOOK_GIT_TIMEOUT_S,
            )
            self.assertEqual(read_metadata.call_args.kwargs["head"], "a" * 40)
            self.assertEqual(read_metadata.call_args.kwargs["branch"], "feature")


class TestExactGatedApply(unittest.TestCase):
    def _eligible_receipt(self, root: Path, state_dir: Path) -> Path:
        with mock.patch.object(
            lifecycle,
            "read_current_worktree_metadata",
            return_value=_metadata(root),
        ):
            receipt = lifecycle.record_session_close(
                session_id="session-a",
                repo="repo",
                worktree_root=root,
                head="a" * 40,
                branch="feature",
                dirty_paths=(),
                work_reached_trunk=True,
                git_ok=True,
                owner_runtime="codex",
                lifecycle_verdict="ARCHIVE-OK",
                state_dir=state_dir,
                now=NOW,
            )
        assert receipt is not None
        return receipt

    def test_apply_rejects_wrong_authorization_before_git_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "target"
            root.mkdir()
            receipt = self._eligible_receipt(root, Path(tmp) / "state")
            with (
                mock.patch.object(lifecycle, "capture_fresh_snapshot") as capture,
                self.assertRaises(PermissionError),
            ):
                lifecycle.apply_receipt(receipt, authorization="GO WORKTREE APPLY WRONG")
            capture.assert_not_called()

    def test_apply_rejects_stale_dirty_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "target"
            root.mkdir()
            receipt = self._eligible_receipt(root, Path(tmp) / "state")
            payload = lifecycle.load_receipt(receipt)
            fresh = lifecycle.FreshSnapshot(
                root=str(root.resolve()),
                head="a" * 40,
                branch="feature",
                dirty_paths=("new.txt",),
                metadata=_metadata(root),
                base_ref="origin/main",
                work_reached_trunk=True,
                git_ok=True,
            )
            with (
                mock.patch.object(lifecycle, "capture_fresh_snapshot", return_value=fresh),
                self.assertRaisesRegex(RuntimeError, "stale receipt disposition"),
            ):
                lifecycle.apply_receipt(
                    receipt,
                    authorization=f"GO WORKTREE APPLY {payload['receipt_sha256']}",
                )

    def test_apply_removes_only_exact_worktree_and_merged_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "target"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            receipt = self._eligible_receipt(root, state_dir)
            payload = lifecycle.load_receipt(receipt)
            fresh = lifecycle.FreshSnapshot(
                root=str(root.resolve()),
                head="a" * 40,
                branch="feature",
                dirty_paths=(),
                metadata=_metadata(root),
                base_ref="origin/main",
                work_reached_trunk=True,
                git_ok=True,
            )
            completed = mock.Mock(returncode=0, stdout="", stderr="")
            common = Path(tmp) / "repo"
            common.mkdir()
            with (
                mock.patch.object(lifecycle, "capture_fresh_snapshot", return_value=fresh),
                mock.patch.object(lifecycle, "_common_repo_root", return_value=common),
                mock.patch.object(lifecycle, "_run_git", return_value=completed) as run_git,
            ):
                mutation = lifecycle.apply_receipt(
                    receipt,
                    authorization=f"GO WORKTREE APPLY {payload['receipt_sha256']}",
                    mutation_dir=Path(tmp) / "mutations",
                    now=NOW,
                )

            self.assertTrue(mutation.exists())
            self.assertEqual(
                [call.args[1] for call in run_git.call_args_list],
                [
                    ["worktree", "remove", "--", str(root.resolve())],
                    ["branch", "-d", "--", "feature"],
                ],
            )
            mutation_payload = json.loads(mutation.read_text(encoding="utf-8"))
            self.assertEqual(mutation_payload["status"], "APPLIED")
            self.assertTrue(mutation_payload["worktree_removed"])
            self.assertTrue(mutation_payload["branch_deleted"])
            self.assertIsNone(mutation_payload["branch_delete_error"])
            self.assertEqual(mutation_payload["source_receipt_sha256"], payload["receipt_sha256"])

    def test_apply_persists_partial_mutation_when_branch_delete_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "target"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            mutation_dir = Path(tmp) / "mutations"
            receipt = self._eligible_receipt(root, state_dir)
            payload = lifecycle.load_receipt(receipt)
            fresh = lifecycle.FreshSnapshot(
                root=str(root.resolve()),
                head="a" * 40,
                branch="feature",
                dirty_paths=(),
                metadata=_metadata(root),
                base_ref="origin/main",
                work_reached_trunk=True,
                git_ok=True,
            )
            success = mock.Mock(returncode=0, stdout="", stderr="")
            failure = mock.Mock(returncode=1, stdout="", stderr="branch busy")
            common = Path(tmp) / "repo"
            common.mkdir()
            with (
                mock.patch.object(lifecycle, "capture_fresh_snapshot", return_value=fresh),
                mock.patch.object(lifecycle, "_common_repo_root", return_value=common),
                mock.patch.object(lifecycle, "_run_git", side_effect=[success, failure]),
                self.assertRaisesRegex(RuntimeError, "worktree removed but branch deletion failed"),
            ):
                lifecycle.apply_receipt(
                    receipt,
                    authorization=f"GO WORKTREE APPLY {payload['receipt_sha256']}",
                    mutation_dir=mutation_dir,
                    now=NOW,
                )

            mutations = list(mutation_dir.glob("mutation_*.json"))
            self.assertEqual(len(mutations), 1)
            mutation_payload = json.loads(mutations[0].read_text(encoding="utf-8"))
            self.assertEqual(mutation_payload["status"], "PARTIAL_BRANCH_RETAINED")
            self.assertTrue(mutation_payload["worktree_removed"])
            self.assertFalse(mutation_payload["branch_deleted"])
            self.assertEqual(mutation_payload["branch_delete_error"], "branch busy")

    def test_apply_persists_failed_remove_before_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "target"
            root.mkdir()
            state_dir = Path(tmp) / "state"
            mutation_dir = Path(tmp) / "mutations"
            receipt = self._eligible_receipt(root, state_dir)
            payload = lifecycle.load_receipt(receipt)
            fresh = lifecycle.FreshSnapshot(
                root=str(root.resolve()),
                head="a" * 40,
                branch="feature",
                dirty_paths=(),
                metadata=_metadata(root),
                base_ref="origin/main",
                work_reached_trunk=True,
                git_ok=True,
            )
            failure = mock.Mock(returncode=1, stdout="", stderr="target busy")
            common = Path(tmp) / "repo"
            common.mkdir()
            with (
                mock.patch.object(lifecycle, "capture_fresh_snapshot", return_value=fresh),
                mock.patch.object(lifecycle, "_common_repo_root", return_value=common),
                mock.patch.object(lifecycle, "_run_git", return_value=failure),
                self.assertRaisesRegex(RuntimeError, "worktree removal failed"),
            ):
                lifecycle.apply_receipt(
                    receipt,
                    authorization=f"GO WORKTREE APPLY {payload['receipt_sha256']}",
                    mutation_dir=mutation_dir,
                    now=NOW,
                )

            mutations = list(mutation_dir.glob("mutation_*.json"))
            self.assertEqual(len(mutations), 1)
            mutation_payload = json.loads(mutations[0].read_text(encoding="utf-8"))
            self.assertEqual(mutation_payload["status"], "FAILED_REMOVE")
            self.assertFalse(mutation_payload["worktree_removed"])
            self.assertEqual(mutation_payload["remove_error"], "target busy")


class TestRealLinkedWorktreeAcceptance(unittest.TestCase):
    def test_real_merged_worktree_receipt_removes_exact_target(self):
        def git(repo: Path, *args: str) -> str:
            result = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            if result.returncode != 0:
                self.fail(f"git {' '.join(args)} failed: {result.stderr}")
            return result.stdout

        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            primary = temp_root / "primary"
            linked = temp_root / "linked"
            state_dir = temp_root / "state"
            mutation_dir = temp_root / "mutations"
            primary.mkdir()
            git(primary, "init", "-b", "main")
            git(primary, "config", "user.email", "codex-accept@example.invalid")
            git(primary, "config", "user.name", "Codex Acceptance")
            git(primary, "commit", "--allow-empty", "-m", "baseline")
            git(primary, "worktree", "add", "-b", "feature", str(linked), "main")
            git(linked, "commit", "--allow-empty", "-m", "feature")
            git(primary, "merge", "--ff-only", "feature")

            snapshot = lifecycle.capture_fresh_snapshot(linked)
            self.assertTrue(snapshot.git_ok)
            self.assertTrue(snapshot.work_reached_trunk)
            receipt = lifecycle.record_session_close(
                session_id="acceptance-a",
                repo="acceptance",
                worktree_root=linked,
                head=snapshot.head,
                branch=snapshot.branch,
                dirty_paths=snapshot.dirty_paths,
                work_reached_trunk=snapshot.work_reached_trunk,
                git_ok=snapshot.git_ok,
                owner_runtime="acceptance",
                lifecycle_verdict="ARCHIVE-OK",
                state_dir=state_dir,
                now=NOW,
            )
            self.assertIsNotNone(receipt)
            assert receipt is not None
            payload = lifecycle.load_receipt(receipt)
            self.assertEqual(payload["disposition"], lifecycle.ELIGIBLE_MERGED_REMOVE)

            mutation = lifecycle.apply_receipt(
                receipt,
                authorization=f"GO WORKTREE APPLY {payload['receipt_sha256']}",
                mutation_dir=mutation_dir,
                now=NOW,
            )

            self.assertFalse(linked.exists())
            self.assertEqual(git(primary, "branch", "--list", "feature").strip(), "")
            mutation_payload = json.loads(mutation.read_text(encoding="utf-8"))
            self.assertEqual(mutation_payload["status"], "APPLIED")
            self.assertTrue(mutation_payload["worktree_removed"])
            self.assertTrue(mutation_payload["branch_deleted"])


if __name__ == "__main__":
    unittest.main()
