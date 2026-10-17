"""One undiffable branch cannot abort the hygiene report (2026-10-17: a single
exit-128 `git diff base...branch` on Tsignal killed the whole dry-run)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import git_hygiene  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        check=True, capture_output=True,
    )


def test_an_orphan_branch_is_reported_unscanned_and_the_rest_still_scanned(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "design" / "plans").mkdir(parents=True)
    (repo / "design" / "plans" / "2026-10-17_only_here.md").write_text("# plan\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "plan")
    _git(repo, "checkout", "-q", "--orphan", "lonely")  # no merge base with main: diff exits 128
    _git(repo, "commit", "-q", "--allow-empty", "-m", "unrelated")
    _git(repo, "checkout", "-q", "main")

    unscanned: list[str] = []
    docs = git_hygiene.orphan_design_docs(str(repo), "main", unscanned)

    assert unscanned == ["lonely"]
    assert [d["file"] for d in docs] == ["design/plans/2026-10-17_only_here.md"]

    report = git_hygiene.analyze(str(repo), "main")
    assert any("ORPHAN DOC SCAN" in a and "lonely" in a for a in report.alarms)
