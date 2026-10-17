"""Repo detection asks git, so worktrees and repos outside D:/APPS resolve
(Slice F item 5)."""

from __future__ import annotations

import io
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import plan_context_loader as loader  # noqa: E402
import steer_context as sc  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _repo(root: Path) -> Path:
    repo = root / "Somewhere Else" / "eco"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_a_repo_outside_apps_resolves_from_a_subdirectory(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "scripts").mkdir()
    assert loader.detect_repo(repo / "scripts") == repo.resolve()


def test_a_worktree_resolves_to_its_main_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    worktree = repo / ".claude" / "worktrees" / "brave"
    _git(repo, "worktree", "add", "-q", str(worktree))
    assert loader.detect_repo(worktree) == repo.resolve()
    assert sc._detect_repo(worktree) == repo.resolve()  # one rule for both hooks


def test_outside_any_checkout_detection_fails_loud(tmp_path: Path, monkeypatch) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert loader.detect_repo(plain) is None
    monkeypatch.setattr(sys, "argv", ["plan_context_loader.py", "--cwd", str(plain)])
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        assert loader.main() == 0
    assert "could not detect repo" in out.getvalue()
    assert "could not resolve a repository" in err.getvalue()
