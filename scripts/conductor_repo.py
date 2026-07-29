"""Repository workspace boundary, worktree allocation, and dirty checkout safety for TruthDeck Conductor.

Prevents execution on dirty operator checkouts; allocates dedicated worktrees under ~/.conductor/worktrees.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import pathlib
import subprocess
from typing import Optional, Union


class ConductorRepo:
    """Safely manages repository checkouts and dedicated worktree allocations."""

    def __init__(self, repo_path: Union[str, pathlib.Path]):
        self.repo_path = pathlib.Path(repo_path).expanduser().resolve()

    def is_git_repo(self) -> bool:
        """Check if target path is a valid Git repository."""
        return (self.repo_path / ".git").exists()

    def is_worktree_clean(self) -> bool:
        """Return True if worktree has zero staged, unstaged, or untracked changes."""
        res = subprocess.run(
            ["git", "-C", str(self.repo_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode == 0 and len(res.stdout.strip()) == 0

    def get_head_sha(self) -> str:
        """Get current HEAD SHA."""
        res = subprocess.run(
            ["git", "-C", str(self.repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()

    def allocate_worktree(self, worktree_dir: pathlib.Path, branch_name: str, base_sha: Optional[str] = None) -> pathlib.Path:
        """Allocate a dedicated clean worktree for WorkItem attempt."""
        if not self.is_git_repo():
            raise ValueError(f"Path {self.repo_path} is not a valid Git repository")

        target_sha = base_sha or self.get_head_sha()
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)

        res = subprocess.run(
            ["git", "-C", str(self.repo_path), "worktree", "add", "-b", branch_name, str(worktree_dir), target_sha],
            capture_output=True,
            text=True,
            check=False,
        )

        if res.returncode != 0:
            raise RuntimeError(f"Failed to allocate worktree at {worktree_dir}: {res.stderr}")

        return worktree_dir.resolve()
