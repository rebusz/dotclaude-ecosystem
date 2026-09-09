#!/usr/bin/env python3
"""Contract tests for the explicit-only Ponytail-derived skill."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "ponytail-on-demand" / "SKILL.md"
OPENAI = ROOT / "skills" / "ponytail-on-demand" / "agents" / "openai.yaml"


class TestPonytailOnDemand(unittest.TestCase):
    def test_skill_is_bounded_to_operator_or_orchestrator_selected_r0_r1_work(self) -> None:
        text = SKILL.read_text(encoding="utf-8")

        self.assertIn("name: ponytail-on-demand", text)
        self.assertIn("R0/R1", text)
        self.assertIn("ARCHITECT workflow selected the checkpoint", text)
        self.assertIn("Stop using this skill for audit, review, security, QUANT", text)
        self.assertIn("Do not inject this skill into subagents", text)

    def test_master_agent_architect_decides_without_operator_flag(self) -> None:
        """Asserted as a contract, not as prose.

        This used to pin seven exact sentences in `master-agent/SKILL.md`. PR
        #112 rewrote that file as a router and the assertions broke together
        (audit P1-5), even though the contract itself survived — split between
        the router and the ARCHITECT protocol. What matters is that the
        checkpoint is ARCHITECT's own decision, is bounded to R0/R1, and is
        excluded from the risk classes where a shortcut is not acceptable.
        """
        skill_root = ROOT / "skills" / "master-agent"
        tree = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(skill_root.rglob("*.md"))
        )
        router = (skill_root / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Ponytail", router, "ARCHITECT's own router must carry the checkpoint")
        self.assertIn("R0/R1", router)
        # The exclusions are the load-bearing half: a simplification pass has no
        # business in an audit, in QUANT, or anywhere near the live path.
        for excluded in ("audit", "QUANT", "R2/R3"):
            with self.subTest(excluded=excluded):
                self.assertIn(excluded, router)
        self.assertIn("Ponytail", tree)
        self.assertTrue((ROOT / "skills" / "ponytail-on-demand" / "SKILL.md").is_file())

    def test_skill_has_no_lifecycle_hook_surface(self) -> None:
        skill_dir = SKILL.parent

        self.assertFalse((skill_dir / "hooks").exists())
        self.assertNotIn("UserPromptSubmit", SKILL.read_text(encoding="utf-8"))
        self.assertNotIn("SubagentStart", SKILL.read_text(encoding="utf-8"))

    def test_codex_metadata_disables_implicit_invocation(self) -> None:
        text = OPENAI.read_text(encoding="utf-8")

        self.assertIn('default_prompt: "Use $ponytail-on-demand', text)
        self.assertIn("allow_implicit_invocation: false", text)

    def test_readme_distinguishes_orchestrator_selection_from_implicit_invocation(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("operator or ARCHITECT selected", text)
        self.assertNotIn("explicit-only Ponytail skill", text)

    def test_installers_copy_the_skill_without_registering_hooks(self) -> None:
        for relative in ("install/install.ps1", "install/install.sh"):
            with self.subTest(installer=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("ponytail-on-demand", text)
                self.assertNotIn("SubagentStart", text)
                self.assertNotIn("UserPromptSubmit", text)


if __name__ == "__main__":
    unittest.main()
