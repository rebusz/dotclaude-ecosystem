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
    commit_msg = f"docs: auto-backup {fname}\n\nAuto-committed by PostToolUse hook (Write/Edit guard).\nFile: {rel_path}"
    _git(["commit", "-m", commit_msg], cwd=git_root)

    # Push — best-effort, no-op if no remote or no tracking branch
    _git(["push", "origin", "HEAD"], cwd=git_root)

    # Print to stderr so Claude Code shows it as a system note
    print(f"[autocommit] {fname} → git commit + push ({git_root})", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail silently
