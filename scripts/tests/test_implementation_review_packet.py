from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from implementation_review_packet import PacketError, build_packet  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class ImplementationReviewPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        _git(self.repo, "init")
        _git(self.repo, "config", "user.email", "test@example.com")
        _git(self.repo, "config", "user.name", "Packet Test")
        (self.repo / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
        _git(self.repo, "add", "sample.py")
        _git(self.repo, "commit", "-m", "base")
        self.start = _git(self.repo, "rev-parse", "HEAD")
        (self.repo / "sample.py").write_text("VALUE = 2\n", encoding="utf-8")
        _git(self.repo, "add", "sample.py")
        _git(self.repo, "commit", "-m", "head")
        self.end = _git(self.repo, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_packet_pins_identity_diff_and_validation(self) -> None:
        packet = build_packet(
            repo=self.repo,
            start_sha=self.start,
            end_sha=self.end,
            mode="IMPLEMENT",
            risk="R2",
            pr_url="https://github.com/acme/repo/pull/7",
            github_repo="https://github.com/acme/repo",
            validation="pytest: 12 passed",
            external_publication_approved=True,
        )

        self.assertIn(f"Base SHA: `{self.start}`", packet)
        self.assertIn(f"Head SHA: `{self.end}`", packet)
        self.assertIn("Draft PR: https://github.com/acme/repo/pull/7", packet)
        self.assertIn("pytest: 12 passed", packet)
        self.assertIn("Packet schema: `implementation-review/v1`", packet)
        self.assertIn("Repository label: `repo`", packet)
        self.assertNotIn(str(self.repo.resolve()), packet)
        self.assertIn("Transmission completeness: unverified", packet)
        self.assertIn(f"REVIEWED_HEAD: {self.end}", packet)
        self.assertIn("REVIEW_SOURCE: draft-pr OR transmitted-packet", packet)
        raw_diff = _git(self.repo, "diff", "--no-ext-diff", "--find-renames", "--find-copies", self.start, self.end)
        self.assertIn(sha256(raw_diff.encode("utf-8")).hexdigest(), packet)
        self.assertIn("-VALUE = 1", packet)
        self.assertIn("+VALUE = 2", packet)

    def test_packet_marks_truncated_diff(self) -> None:
        packet = build_packet(
            repo=self.repo,
            start_sha=self.start,
            end_sha=self.end,
            mode="EXECUTOR",
            risk="R1",
            max_diff_chars=20,
        )

        self.assertIn("Local packet diff truncated: true", packet)
        self.assertIn("DIFF TRUNCATED IN PACKET", packet)

    def test_truncation_boundary_is_exact(self) -> None:
        raw_diff = _git(self.repo, "diff", "--no-ext-diff", "--find-renames", "--find-copies", self.start, self.end)

        exact = build_packet(
            repo=self.repo,
            start_sha=self.start,
            end_sha=self.end,
            mode="IMPLEMENT",
            risk="R1",
            max_diff_chars=len(raw_diff),
        )
        over = build_packet(
            repo=self.repo,
            start_sha=self.start,
            end_sha=self.end,
            mode="IMPLEMENT",
            risk="R1",
            max_diff_chars=len(raw_diff) - 1,
        )

        self.assertIn("Local packet diff truncated: false", exact)
        self.assertIn("Local packet diff truncated: true", over)

    def test_r2_requires_external_publication_approval(self) -> None:
        with self.assertRaisesRegex(PacketError, "requires explicit operator approval"):
            build_packet(
                repo=self.repo,
                start_sha=self.start,
                end_sha=self.end,
                mode="IMPLEMENT",
                risk="R2",
            )

    def test_sensitive_path_is_rejected(self) -> None:
        (self.repo / ".env").write_text("TOKEN=placeholder\n", encoding="utf-8")
        _git(self.repo, "add", ".env")
        _git(self.repo, "commit", "-m", "sensitive")
        sensitive_head = _git(self.repo, "rev-parse", "HEAD")

        with self.assertRaisesRegex(PacketError, "sensitive path"):
            build_packet(
                repo=self.repo,
                start_sha=self.end,
                end_sha=sensitive_head,
                mode="IMPLEMENT",
                risk="R1",
            )

    def test_empty_range_is_rejected(self) -> None:
        with self.assertRaisesRegex(PacketError, "start_sha equals end_sha"):
            build_packet(
                repo=self.repo,
                start_sha=self.end,
                end_sha=self.end,
                mode="IMPLEMENT",
                risk="R1",
            )


class ExternalReviewWorkflowContractTests(unittest.TestCase):
    """The external-review gate, asserted as a contract rather than as prose.

    These assertions used to pin exact sentences in `master-agent/SKILL.md`.
    PR #112 turned that file into a router and moved the detail into
    `references/protocols/`, so 18 of 20 assertions broke at once and `main`
    went red on 2026-09-07 (audit P1-5). Pinning wording makes a legitimate
    refactor look like a regression, and the tempting repair — delete the
    assertions — would have silently dropped the gate.

    It nearly did: #112 also removed the only reference to
    `implementation_review_packet.py`, and it landed nowhere else, so the
    protocol said "build a canonical packet" while nothing pointed at the
    builder that rejects secrets fail-closed. Restored in `full-workflow.md`.

    So: search the whole skill tree for each contract element, and name the
    element, not the sentence.
    """

    SKILL_ROOT = ROOT / "skills" / "master-agent"

    def _skill_tree(self) -> str:
        return "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(self.SKILL_ROOT.rglob("*.md"))
        )

    def test_the_router_lives_in_master_agent_and_covers_every_risk_class(self) -> None:
        text = (self.SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("## Review Workflow Routing", text)
        self.assertIn("authoritative router", text)
        for risk in ("R0", "R1", "R2", "R3"):
            with self.subTest(risk=risk):
                self.assertRegex(text, rf"\|\s*{risk}\s*\|")
        # `core.md` calls the audit and matrix runners internal stages, so the
        # routing table must not advertise one as a public workflow topology.
        self.assertNotIn("CEO -> matrix ->", text)

    def test_the_external_review_gate_survives_somewhere_in_the_skill_tree(self) -> None:
        tree = self._skill_tree()

        for element in (
            "draft PR",                        # the review source, never a branch tip
            "implementation_review_packet",    # the builder that fails closed on secrets
            "packet",
            "exact-head",
            "SHIP-BLOCKING",
            "squash merge",
        ):
            with self.subTest(element=element):
                self.assertIn(element, tree, f"external-review contract lost: {element!r}")

    def test_the_packet_builder_named_by_the_contract_actually_exists(self) -> None:
        """The pairing is the point: a contract naming a tool that is gone, or a
        tool no contract names, are the same failure wearing different clothes."""
        self.assertIn("implementation_review_packet", self._skill_tree())
        self.assertTrue((ROOT / "scripts" / "implementation_review_packet.py").is_file())

    def test_superseded_workflow_surfaces_stay_retired(self) -> None:
        text = (self.SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

        for retired in ("/fw close", "`/audit`", "Launch the external panel",
                        "run LOCAL REVIEW + COMPOUND"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, text)

    def test_executor_delegates_to_master_agent_risk_router(self) -> None:
        text = (ROOT / "skills" / "executor" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("Review Workflow Routing", text)
        self.assertIn("executor work belongs to `/fwf` or `/fwp`", text)
        self.assertIn("invoke the `review` skill directly", text)
        self.assertIn("every `SHIP-BLOCKING` finding is fixed", text)
        self.assertIn("without another operator token", text)
        self.assertNotIn("/fw close", text)
        self.assertNotIn("the CDP-backed auditF panel", text)

    def test_installers_copy_shared_workflow_to_codex(self) -> None:
        powershell = (ROOT / "install" / "install.ps1").read_text(encoding="utf-8")
        shell = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")

        self.assertIn('$CodexSkills = @("master-agent", "executor", "ponytail-on-demand", "run-model-team", "coderpxG")', powershell)
        self.assertIn('Join-Path $CodexHome "skills\\$skill"', powershell)
        self.assertIn("CODEX_SKILLS=(master-agent executor ponytail-on-demand run-model-team coderpxG)", shell)
        self.assertIn('for skill in "${CODEX_SKILLS[@]}"', shell)
        self.assertIn('$CODEX_HOME/skills/$skill', shell)

    def test_global_policy_references_master_router_and_two_full_workflows(self) -> None:
        text = (ROOT / "agent-rules" / "core.md").read_text(encoding="utf-8")

        self.assertIn("Review Workflow Routing", text)
        self.assertIn("`/fwf` and `/fwp` own the R1/R2/R3 lifecycle", text)
        self.assertIn("blocking `review`", text)
        self.assertNotIn("/fw close", text)
        self.assertNotIn("`/audit`", text)
        self.assertNotIn("external implementation review for every non-empty code diff", text)

    def test_codex_overlay_keeps_runners_internal_to_two_workflows(self) -> None:
        text = (ROOT / "agent-rules" / "overlays" / "codex-global.md").read_text(encoding="utf-8")

        self.assertIn("Review Workflow Routing", text)
        self.assertIn("`/fwf` and `/fwp` are the only public full-workflow commands", text)
        self.assertIn("The only internal runner for R1/R2/R3 is `D:/APPS/_shared/audit/fuse.py`", text)
        self.assertIn("`--synthesizer gpt`", text)
        self.assertNotIn("/fw close", text)
        self.assertNotIn("`/audit`", text)
        self.assertNotIn("To audit a plan/design", text)

    def test_all_declared_skills_exist_on_disk(self) -> None:
        skills_dir = ROOT / "skills"
        agy_skills_dir = ROOT / "agy-skills"
        existing = {p.name for p in skills_dir.iterdir() if p.is_dir()}
        if agy_skills_dir.exists():
            existing.update(p.name for p in agy_skills_dir.iterdir() if p.is_dir())
        for skill in ("master-agent", "executor", "distill-repo", "ponytail-on-demand", "run-model-team", "coderpxC", "coderpxG", "fwa", "coderpxA"):
            self.assertIn(skill, existing, f"Declared skill {skill} does not exist on disk")


if __name__ == "__main__":
    unittest.main()
