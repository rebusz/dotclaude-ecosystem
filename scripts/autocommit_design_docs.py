#!/usr/bin/env python3
"""PostToolUse hook — auto-commit + push any Write/Edit to design/plans/, design/audits/, design/visions/.

Root cause this guards against: tool calls appear in JSONL transcript but the file
never lands on disk if context exhausts before session end. Git push is the only
guaranteed backup. Fail silently — never break the session.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

DESIGN_PATHS = ("design/plans/", "design/audits/", "design/visions/", "design/mockups/")

# Branches we must never rewrite history on, even by amend.
PROTECTED_BRANCHES = {"main", "master", "develop"}


def _normalize(p: str) -> str:
    return p.replace("\\", "/")


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _can_amend(git_root: str, rel_path: str, commit_msg_subject: str) -> bool:
    """True when HEAD is this hook's own backup commit for this same file.

    Collapsing consecutive backups keeps a session's plan history at ONE commit
    instead of one-per-keystroke. Guards, all of which must hold:
      * we are on a real branch, and it is not a protected/shared one;
      * HEAD's subject is exactly the backup subject for this same file;
      * HEAD touched exactly this one file (nothing else gets swallowed);
      * HEAD is not already reachable from a remote base ref (never rewrite
        something that has been merged or that another ref builds on).
    """
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=git_root).stdout.strip()
    if not branch or branch == "HEAD" or branch in PROTECTED_BRANCHES:
        return False

    head_subject = _git(["log", "-1", "--format=%s"], cwd=git_root).stdout.strip()
    if head_subject != commit_msg_subject:
        return False

    touched = _git(
        ["show", "--pretty=format:", "--name-only", "HEAD"], cwd=git_root
    ).stdout.split()
    if touched != [rel_path.replace("\\", "/")]:
        return False

    for base in ("origin/main", "origin/master"):
        if _git(["rev-parse", "--verify", "--quiet", base], cwd=git_root).returncode != 0:
            continue
        if _git(["merge-base", "--is-ancestor", "HEAD", base], cwd=git_root).returncode == 0:
            return False  # already on base — amending would rewrite shared history

    return True


def _push(git_root: str, amended: bool) -> None:
    """Best-effort push. An amend rewrites the tip, so the branch-local force
    (lease-guarded) is the only way to keep the remote backup in sync."""
    res = _git(["push", "origin", "HEAD"], cwd=git_root)
    if res.returncode == 0 or not amended:
        return
    _git(["push", "--force-with-lease", "origin", "HEAD"], cwd=git_root)


def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return

    tool_input = data.get("tool_input", {})
    file_path = _normalize(tool_input.get("file_path", ""))
    if not file_path:
        return

    if not any(p in file_path for p in DESIGN_PATHS):
        return

    # Resolve the file on disk (might be relative or absolute)
    abs_path = Path(file_path)
    if not abs_path.is_absolute():
        abs_path = Path.cwd() / file_path
    abs_path = abs_path.resolve()

    if not abs_path.exists():
        return

    # Find git root
    try:
        result = _git(["rev-parse", "--show-toplevel"], cwd=str(abs_path.parent))
        if result.returncode != 0:
            return
        git_root = result.stdout.strip()
    except Exception:
        return

    rel_path = str(abs_path.relative_to(git_root))

    # Stage the file
    _git(["add", rel_path], cwd=git_root)

    # Check if there is anything staged
    diff = _git(["diff", "--cached", "--quiet"], cwd=git_root)
    if diff.returncode == 0:
        return  # nothing new to commit

    fname = abs_path.name
    subject = f"docs: auto-backup {fname}"
    commit_msg = f"{subject}\n\nAuto-committed by PostToolUse hook (Write/Edit guard).\nFile: {rel_path}"

    # Collapse consecutive backups of the same file into a single commit instead
    # of one per edit — a long planning session used to leave 15+ identical
    # commits on the branch, which is noise the operator later has to untangle.
    amended = _can_amend(git_root, rel_path, subject)
    args = ["commit", "-m", commit_msg] + (["--amend"] if amended else [])
    _git(args, cwd=git_root)

    _push(git_root, amended)

    # Print to stderr so Claude Code shows it as a system note
    verb = "amend + push" if amended else "commit + push"
    print(f"[autocommit] {fname} → git {verb} ({git_root})", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail silently
