#!/usr/bin/env python3
"""Tests for intent_layer_audit.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).parent.parent
sys.path.insert(0, str(_SCRIPTS))

import intent_layer_audit as ila


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestIntentLayerAudit(unittest.TestCase):
    def test_counts_managed_and_manual_lines(self):
        text = "\n".join(
            [
                "# Root",
                "",
                ila.BEGIN,
                "managed",
                ila.END,
                "",
                "manual",
            ]
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "AGENTS.md"
            write(path, text)
            audit = ila.audit_file(path, max_root_lines=20, max_manual_lines=10)
            self.assertTrue(audit.exists)
            self.assertTrue(audit.has_managed_block)
            self.assertEqual(audit.managed_lines, 3)
            self.assertEqual(audit.manual_lines, 4)

    def test_flags_oversized_root_and_manual_sections(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "CLAUDE.md"
            write(path, "\n".join(f"line {i}" for i in range(8)))
            audit = ila.audit_file(path, max_root_lines=5, max_manual_lines=5)
            self.assertIn("oversized_root", audit.flags)
            self.assertIn("oversized_manual", audit.flags)

    def test_repo_flags_missing_refs_dir_and_file_findings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root / "AGENTS.md", "# A\n")
            write(root / "CLAUDE.md", "\n".join(f"line {i}" for i in range(8)))
            audit = ila.audit_repo(root, max_root_lines=5, max_manual_lines=20)
            self.assertIn("missing_refs_dir", audit.flags)
            self.assertIn("CLAUDE.md:oversized_root", audit.flags)

    def test_refs_dir_without_root_pointer_is_flagged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".claude" / "refs").mkdir(parents=True)
            write(root / "AGENTS.md", "# A\n")
            write(root / "CLAUDE.md", "# C\n")
            audit = ila.audit_repo(root, max_root_lines=20, max_manual_lines=20)
            self.assertIn("missing_refs_pointer", audit.flags)

    def test_refs_pointer_clears_pointer_flag(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".claude" / "refs").mkdir(parents=True)
            write(root / "AGENTS.md", "See `.claude/refs/runtime.md`.\n")
            write(root / "CLAUDE.md", "# C\n")
            audit = ila.audit_repo(root, max_root_lines=20, max_manual_lines=20)
            self.assertNotIn("missing_refs_pointer", audit.flags)

    def test_cli_json_and_fail_on_findings(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root / "AGENTS.md", "# A\n")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(_SCRIPTS / "intent_layer_audit.py"),
                    "--format",
                    "json",
                    "--fail-on-findings",
                    str(root),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 1)
            data = json.loads(proc.stdout)
            self.assertEqual(data[0]["files"][0]["file"], "AGENTS.md")

    def test_markdown_contains_table(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root / "AGENTS.md", "# A\n")
            write(root / "CLAUDE.md", "# C\n")
            audit = ila.audit_repo(root, max_root_lines=20, max_manual_lines=20)
            markdown = ila.render_markdown([audit])
            self.assertIn("| Repo | File | Lines |", markdown)
            self.assertIn("## Repo Flags", markdown)


if __name__ == "__main__":
    unittest.main()
