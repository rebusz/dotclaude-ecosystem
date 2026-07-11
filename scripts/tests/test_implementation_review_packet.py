from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
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
        )

        self.assertIn(f"Base SHA: `{self.start}`", packet)
        self.assertIn(f"Head SHA: `{self.end}`", packet)
        self.assertIn("Draft PR: https://github.com/acme/repo/pull/7", packet)
        self.assertIn("pytest: 12 passed", packet)
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

        self.assertIn("Packet diff truncated: true", packet)
        self.assertIn("DIFF TRUNCATED IN PACKET", packet)

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
    def test_master_agent_requires_exact_head_external_review(self) -> None:
        text = (ROOT / "skills" / "master-agent" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("EXTERNAL IMPLEMENTATION REVIEW GATE", text)
        self.assertIn("draft PR", text)
        self.assertIn("implementation_review_packet.py", text)
        self.assertIn("_auditf_meta.json", text)
        self.assertIn("GitHub-grounded Perplexity CDP lane must succeed", text)
        self.assertIn("verdict against an older head is stale", text)

    def test_executor_delegates_external_gate_to_parent(self) -> None:
        text = (ROOT / "skills" / "executor" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("EXTERNAL IMPLEMENTATION REVIEW GATE", text)
        self.assertIn("--mode EXECUTOR", text)
        self.assertIn("every `SHIP-BLOCKING` finding is fixed", text)

    def test_installers_copy_shared_workflow_to_codex(self) -> None:
        powershell = (ROOT / "install" / "install.ps1").read_text(encoding="utf-8")
        shell = (ROOT / "install" / "install.sh").read_text(encoding="utf-8")

        self.assertIn("foreach ($skill in $BundledSkills)", powershell)
        self.assertIn('Join-Path $CodexHome "skills\\$skill"', powershell)
        self.assertIn('for skill in "${BUNDLED_SKILLS[@]}"', shell)
        self.assertIn('$CODEX_HOME/skills/$skill', shell)


if __name__ == "__main__":
    unittest.main()
