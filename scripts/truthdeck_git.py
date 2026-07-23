"""Narrow read-only Git collector; deliberately independent of git_hygiene mutations."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from truthdeck_collectors import CollectorError, CollectorResult, run_bounded
from truthdeck_model import CollectorRun, FactState, make_fact


def collect_git(repo: Path, *, base_ref: str, observed_at_utc: str, deadline: float,
                command_timeout_s: float = 5.0, max_output_bytes: int = 1_048_576) -> CollectorResult:
    started = time.monotonic()
    def command(cwd: Path, *args: str) -> str:
        return _git(cwd, deadline, command_timeout_s, max_output_bytes, *args)

    def optional(cwd: Path, *args: str) -> str:
        return _git_optional(cwd, deadline, command_timeout_s, max_output_bytes, *args)

    def code(cwd: Path, *args: str) -> int:
        return _git_code(cwd, deadline, command_timeout_s, max_output_bytes, *args)
    root = Path(command(repo, "rev-parse", "--show-toplevel")).resolve()
    common = Path(command(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    head = command(root, "rev-parse", "HEAD")
    base = optional(root, "rev-parse", "--verify", base_ref)
    status = command(root, "status", "--porcelain=v1", "--untracked-files=normal")
    merge_code = code(root, "merge-base", "--is-ancestor", head, base) if base else None
    if merge_code not in {None, 0, 1}:
        base = ""
        merge_code = None
    origin = optional(root, "remote", "get-url", "origin")
    repo_id = _repo_id(origin, common)
    locator = f"git:{repo_id}"
    facts = (
        make_fact("git.head", head, source_type="git", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("implementation.head", head, source_type="git", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("git.base", base or None, state=FactState.OBSERVED if base else FactState.UNAVAILABLE,
                  source_type="git", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("git.clean", not bool(status), source_type="git", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
        make_fact("git.merged", merge_code == 0 if merge_code is not None else None,
                  state=FactState.OBSERVED if merge_code is not None else FactState.UNAVAILABLE,
                  source_type="git", source_locator=locator,
                  observed_at_utc=observed_at_utc, repo_id=repo_id),
    )
    return CollectorResult("git", facts, CollectorRun("git", "1", int((time.monotonic() - started) * 1000), 0, repo_id=repo_id))


def _git(repo: Path, deadline: float, timeout_s: float, max_bytes: int, *args: str) -> str:
    result = run_bounded(("git", "-C", str(repo), *args), cwd=repo,
                         deadline=min(deadline, time.monotonic() + timeout_s), max_output_bytes=max_bytes)
    if result.returncode:
        raise CollectorError(f"git command failed: {' '.join(args)}: {result.stderr[:200]}")
    return result.stdout.strip()


def _git_code(repo: Path, deadline: float, timeout_s: float, max_bytes: int, *args: str) -> int:
    return run_bounded(("git", "-C", str(repo), *args), cwd=repo,
                       deadline=min(deadline, time.monotonic() + timeout_s), max_output_bytes=max_bytes).returncode


def _git_optional(repo: Path, deadline: float, timeout_s: float, max_bytes: int, *args: str) -> str:
    result = run_bounded(("git", "-C", str(repo), *args), cwd=repo,
                         deadline=min(deadline, time.monotonic() + timeout_s), max_output_bytes=max_bytes)
    return result.stdout.strip() if result.returncode == 0 else ""


def _repo_id(origin: str, common: Path) -> str:
    normalized = origin.replace("\\", "/").removesuffix(".git")
    if normalized:
        tail = normalized.split(":", 1)[-1].split("github.com/", 1)[-1].strip("/")
        if "/" in tail:
            return tail.lower()
    return f"local-{hashlib.sha256(str(common).lower().encode()).hexdigest()[:16]}"
