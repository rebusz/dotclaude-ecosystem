#!/usr/bin/env python3
"""Contract tests for the explicit-only Ponytail-derived skill."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "ponytail-on-demand" / "SKILL.md"
OPENAI = ROOT / "skills" / "ponytail-on-demand" / "agents" / "openai.yaml"


class TestPonytailOnDemand(unittest.TestCase):
    def test_skill_is_bounded_to_explicit_r0_r1_work(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        self.assertIn("name: ponytail-on-demand", text)
        self.assertIn("R0/R1", text)
        self.assertIn("Stop using this skill for audit, review, security, QUANT", text)
        self.assertIn("Do not inject this skill into subagents", text)

    def test_skill_has_no_lifecycle_hook_surface(self) -> None:
        skill_dir = SKILL.parent

        self.assertFalse((skill_dir / "hooks").exists())
        self.assertNotIn("UserPromptSubmit", SKILL.read_text(encoding="utf-8"))
        self.assertNotIn("SubagentStart", SKILL.read_text(encoding="utf-8"))

    def test_codex_metadata_disables_implicit_invocation(self) -> None:
        text = OPENAI.read_text(encoding="utf-8")

        self.assertIn('default_prompt: "Use $ponytail-on-demand', text)
        self.assertIn("allow_implicit_invocation: false", text)

    def test_installers_copy_the_skill_without_registering_hooks(self) -> None:
        for relative in ("install/install.ps1", "install/install.sh"):
            with self.subTest(installer=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("ponytail-on-demand", text)
                self.assertNotIn("SubagentStart", text)
                self.assertNotIn("UserPromptSubmit", text)


if __name__ == "__main__":
    unittest.main()
