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
    def test_master_agent_owns_risk_aware_review_routing(self) -> None:
        text = (ROOT / "skills" / "master-agent" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("## Review Workflow Routing", text)
        self.assertIn("| R3 | `/fwf` or `/fwp`: CEO -> matrix -> eng -> implementation -> review", text)
        self.assertIn("| R2 | `/fwf` or `/fwp`: CEO -> matrix -> eng -> implementation -> review", text)
        self.assertIn("| R1 | `/fwf` or `/fwp`: CEO -> audit -> eng -> implementation -> review", text)
        self.assertIn("There is no separate closeout command", text)
        self.assertIn("Codex always passes\n`--synthesizer gpt`", text)
        self.assertIn("draft PR", text)
        self.assertIn("implementation_review_packet.py", text)
        self.assertIn("older head is stale", text.lower())
        self.assertIn("external-publication consent", text)
        self.assertIn("Every `SHIP-BLOCKING` finding must be", text)
        self.assertIn("standing authorization", text)
        self.assertIn("exact-head publication token", text)
        self.assertIn("continues through ready, CI, merge", text)
        self.assertNotIn("/fw close", text)
        self.assertNotIn("`/audit`", text)
        self.assertNotIn("Launch the external panel", text)
        self.assertNotIn("run LOCAL REVIEW + COMPOUND", text)

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

        self.assertIn('$CodexSkills = @("master-agent", "executor", "ponytail-on-demand")', powershell)
        self.assertIn('Join-Path $CodexHome "skills\\$skill"', powershell)
        self.assertIn("CODEX_SKILLS=(master-agent executor ponytail-on-demand)", shell)
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
        self.assertIn("R1 uses `auditf.py`; R2/R3 use `fuse.py`", text)
        self.assertIn("`--synthesizer gpt`", text)
        self.assertNotIn("/fw close", text)
        self.assertNotIn("`/audit`", text)
        self.assertNotIn("To audit a plan/design", text)


if __name__ == "__main__":
    unittest.main()
