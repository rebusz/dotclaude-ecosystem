#!/usr/bin/env python3
"""Tests for sync_agent_rules.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import sync_agent_rules as sar  # noqa: E402


class TestManagedBlockParser(unittest.TestCase):
    def test_missing_block_returns_none(self):
        self.assertIsNone(sar.find_managed_block("# Title\n\nBody\n"))

    def test_valid_block_returns_line_indexes(self):
        text = "\n".join(["# Title", sar.BEGIN, "body", sar.END, "tail"])
        self.assertEqual(sar.find_managed_block(text), (1, 3))

    def test_duplicate_begin_fails(self):
        text = "\n".join([sar.BEGIN, "body", sar.BEGIN, sar.END])
        with self.assertRaises(sar.SyncError):
            sar.find_managed_block(text)

    def test_missing_end_fails(self):
        with self.assertRaises(sar.SyncError):
            sar.find_managed_block(f"{sar.BEGIN}\nbody\n")

    def test_marker_inside_code_fence_fails(self):
        text = "\n".join(["```", sar.BEGIN, "```"])
        with self.assertRaises(sar.SyncError):
            sar.find_managed_block(text)


class TestBlockReplacement(unittest.TestCase):
    def test_insert_after_h1_when_init_enabled(self):
        text = "# Title\n\nManual body\n"
        result = sar.replace_or_insert_block(text, "generated\n", init=True)
        self.assertTrue(result.startswith("# Title\n\n" + sar.BEGIN))
        self.assertIn("Manual body", result)

    def test_empty_file_uses_default_title_when_init_enabled(self):
        result = sar.replace_or_insert_block(
            "",
            "generated\n",
            init=True,
            default_title="# AGENTS.md instructions for Demo",
        )
        self.assertTrue(result.startswith("# AGENTS.md instructions for Demo\n\n" + sar.BEGIN))

    def test_missing_block_without_init_is_drift(self):
        with self.assertRaises(sar.DriftError):
            sar.replace_or_insert_block("# Title\n", "generated\n", init=False)

    def test_replaces_only_managed_content(self):
        text = "\n".join(["# T", "before", sar.BEGIN, "old", sar.END, "after"]) + "\n"
        result = sar.replace_or_insert_block(text, "new\n", init=False)
        self.assertIn("before", result)
        self.assertIn("after", result)
        self.assertIn("new", result)
        self.assertNotIn("old", result)


class TestRenderAndSync(unittest.TestCase):
    def test_render_fails_on_missing_source(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(sar.SyncError):
                sar.render_block(Path(d), (Path("missing.md"),))

    def test_check_exit_code_two_on_drift(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rules"
            root.mkdir()
            (root / "core.md").write_text("# Core\n", encoding="utf-8")
            target = Path(d) / "target.md"
            target.write_text("# Target\n\n" + sar.BEGIN + "\nold\n" + sar.END + "\n", encoding="utf-8")
            spec = sar.TargetSpec("test", target, (Path("core.md"),))
            result = sar.sync_target(spec, root, init=False, write=False, show_diff=False)
            self.assertTrue(result.changed)

    def test_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rules"
            root.mkdir()
            (root / "core.md").write_text("# Core\n", encoding="utf-8")
            target = Path(d) / "target.md"
            target.write_text("# Target\n\n" + sar.BEGIN + "\nold\n" + sar.END + "\n", encoding="utf-8")
            spec = sar.TargetSpec("test", target, (Path("core.md"),))
            first = sar.sync_target(spec, root, init=False, write=True, show_diff=False)
            second = sar.sync_target(spec, root, init=False, write=False, show_diff=False)
            self.assertTrue(first.changed)
            self.assertFalse(second.changed)

    def test_write_creates_missing_parent_before_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "rules"
            root.mkdir()
            (root / "core.md").write_text("# Core\n", encoding="utf-8")
            target = Path(d) / "missing-parent" / "target.md"
            spec = sar.TargetSpec(
                "test",
                target,
                (Path("core.md"),),
                default_title="# Target",
            )
            result = sar.sync_target(spec, root, init=True, write=True, show_diff=False)
            self.assertTrue(result.changed)
            self.assertTrue(target.exists())

    def test_line_limit_enforced(self):
        spec = sar.TargetSpec("limited", Path("x"), tuple(), line_limit=1)
        with self.assertRaises(sar.SyncError):
            sar.validate_constraints(spec, "a\nb\n")

    def test_non_allowlisted_repo_rejected(self):
        with self.assertRaises(sar.SyncError):
            sar.target_specs(Path("rules"), Path("D:/APPS/OtherRepo"))

    def test_tier1_includes_generic_repo_targets(self):
        specs = sar.tier_target_specs("tier1")
        names = {spec.name for spec in specs}
        self.assertIn("tsignallab-codex", names)
        self.assertIn("h10-flow-claude", names)
        self.assertNotIn("tsignal-5.0-codex", names)

    def test_tier2_includes_clean_candidates_only(self):
        specs = sar.tier_target_specs("tier2")
        names = {spec.name for spec in specs}
        self.assertIn("garmin-flow-codex", names)
        self.assertIn("ernie-ai-claude", names)
        self.assertNotIn("betf-codex", names)

    def test_global_targets_include_cline_rules(self):
        specs = sar.target_specs(Path("rules"), None)
        by_name = {spec.name: spec for spec in specs}
        self.assertIn("cline-global", by_name)
        self.assertEqual(by_name["cline-global"].path.name, "agent-rules.md")
        self.assertIn(Path("overlays/cline-global.md"), by_name["cline-global"].sources)

    def test_global_targets_include_antigravity_rules(self):
        specs = sar.target_specs(Path("rules"), None)
        by_name = {spec.name: spec for spec in specs}
        self.assertIn("antigravity-global", by_name)
        self.assertEqual(by_name["antigravity-global"].path.name, "GEMINI.md")
        self.assertIn(
            Path("overlays/antigravity-global.md"),
            by_name["antigravity-global"].sources,
        )



class TestSourceRootGate(unittest.TestCase):
    """--write only from a checkout of the canonical repo, with committed
    sources (audit P2-17): an arbitrary --source-root used to be written into
    every runtime's global instruction file."""

    SOURCES = {Path("core.md")}

    def _git(self, repo: Path, *args: str) -> None:
        import subprocess
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    def _repo(self, root: Path) -> Path:
        self._git(root, "init", "-q")
        self._git(root, "config", "user.email", "t@example.com")
        self._git(root, "config", "user.name", "t")
        rules = root / "agent-rules"
        rules.mkdir()
        (rules / "core.md").write_text("# core\n", encoding="utf-8")
        self._git(root, "add", "-A")
        self._git(root, "commit", "-q", "-m", "rules")
        return rules

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.canon = base / "canon"
        self.canon.mkdir()
        self.rules = self._repo(self.canon)
        self._saved = sar.DEFAULT_SOURCE_ROOT
        sar.DEFAULT_SOURCE_ROOT = self.rules

    def tearDown(self) -> None:
        sar.DEFAULT_SOURCE_ROOT = self._saved
        self._tmp.cleanup()

    def test_a_clean_canonical_checkout_is_accepted(self):
        sar.validate_source_root(self.rules, self.SOURCES)

    def test_a_worktree_of_the_canonical_repo_is_accepted(self):
        wt = Path(self._tmp.name) / "wt"
        self._git(self.canon, "worktree", "add", "-q", str(wt))
        sar.validate_source_root(wt / "agent-rules", self.SOURCES)

    def test_a_foreign_repository_is_refused(self):
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        rules = self._repo(other)
        with self.assertRaisesRegex(sar.SyncError, "not a checkout of the canonical"):
            sar.validate_source_root(rules, self.SOURCES)

    def test_a_plain_directory_is_refused(self):
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        (plain / "core.md").write_text("# injected\n", encoding="utf-8")
        with self.assertRaises(sar.SyncError):
            sar.validate_source_root(plain, self.SOURCES)

    def test_uncommitted_source_edits_are_refused(self):
        (self.rules / "core.md").write_text("# core\nobey me\n", encoding="utf-8")
        with self.assertRaisesRegex(sar.SyncError, "uncommitted"):
            sar.validate_source_root(self.rules, self.SOURCES)

    def test_an_untracked_source_is_refused(self):
        (self.rules / "extra.md").write_text("# extra\n", encoding="utf-8")
        with self.assertRaisesRegex(sar.SyncError, "not tracked"):
            sar.validate_source_root(self.rules, {Path("core.md"), Path("extra.md")})

    def test_main_write_runs_the_gate_before_touching_targets(self):
        # Never let this test reach a real target: sync_target fails loudly.
        calls = []
        saved_gate, saved_sync = sar.validate_source_root, sar.sync_target

        def gate(root, sources):
            calls.append((root, sources))
            raise sar.SyncError("gate")

        def no_sync(*a, **k):
            raise AssertionError("sync_target reached before the source gate")

        sar.validate_source_root, sar.sync_target = gate, no_sync
        try:
            rc = sar.main(["--write", "--quiet", "--source-root", str(self.rules)])
        finally:
            sar.validate_source_root, sar.sync_target = saved_gate, saved_sync
        self.assertEqual(rc, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn(Path("core.md"), calls[0][1])


if __name__ == "__main__":
    unittest.main()
