#!/usr/bin/env python3
"""Tests for sync_agent_rules.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import sync_agent_rules as sar


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

    def test_line_limit_enforced(self):
        spec = sar.TargetSpec("limited", Path("x"), tuple(), line_limit=1)
        with self.assertRaises(sar.SyncError):
            sar.validate_constraints(spec, "a\nb\n")

    def test_non_allowlisted_repo_rejected(self):
        with self.assertRaises(sar.SyncError):
            sar.target_specs(Path("rules"), Path("D:/APPS/OtherRepo"))


if __name__ == "__main__":
    unittest.main()
