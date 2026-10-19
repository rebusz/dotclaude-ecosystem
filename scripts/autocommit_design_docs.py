#!/usr/bin/env python3
"""PostToolUse hook — back a design doc up to the branch AND land it on main.

Two failure modes, two mechanisms.

1. A tool call appears in the JSONL transcript but the file never lands on disk
   when context exhausts before session end. Guard: commit + push to whatever
   branch is checked out. Unchanged since 2026-06.

2. That backup then never reaches `main`. A scan of 1074 branches on 2026-09-01
   found 132 design documents that existed on a branch and nowhere else — 19
   handoffs, 8 plans, 84 audits. The authoring session reports "committed +
   pushed", which is true and reads as delivered, and the document is invisible
   to every other checkout. #1568 rescued 112 such documents on 2026-08-31 and
   #1577 rescued 27 more the next day, so this recurs on a scale of days.
   Guard: mirror the file onto `main` as its own commit.

The mirror is pure plumbing — `hash-object` / `read-tree` into a temporary index
/ `commit-tree` / `push <sha>:refs/heads/docs/auto-backup`. It never touches any working
tree, index, or checked-out branch. That matters: `main` is a concurrently
written trunk with a live trading bot running from it, and an earlier attempt to
land docs by editing main's working tree had a parallel session swallow the
half-finished edit into an unrelated commit.

Fail silently — never break the session. Set AUTOCOMMIT_DESIGN_NO_MAIN=1 to keep
the branch backup and skip the mirror.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# `design/handoffs/` was missing until 2026-09-01, which is why handoffs were the
# largest stranded category (19 of 27 rescued in #1577): the hook never saw them
# at all, and sessions committed them by hand onto their own branch.
DESIGN_PATHS = (
    "design/plans/",
    "design/audits/",
    "design/visions/",
    "design/mockups/",
    "design/handoffs/",
    "design/runbooks/",
)

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


# One collecting branch for every auto-backed-up design document. Deliberately
# NOT the trunk: see the 2026-09-01 outage note in the module docstring.
DOCS_BRANCH = "docs/auto-backup"


def _base_ref(git_root: str) -> str | None:
    """The trunk this repo actually uses. Not every repo here calls it `main`."""
    for ref in ("origin/main", "origin/master"):
        if _git(["rev-parse", "--verify", "--quiet", ref], cwd=git_root).returncode == 0:
            return ref
    return None


def _mirror_to_docs_branch(git_root: str, rel_path: str, abs_path: str, subject: str) -> str:
    """Land this one file on the trunk as its own commit, touching nothing else.

    Plumbing only. The tree is built in a throwaway index (GIT_INDEX_FILE), so
    the caller's working tree, staging area and checked-out branch are never
    read or written. The commit's sole parent is the freshly fetched tip of the
    docs branch (or the trunk, the first time that branch does not exist), so
    the push is a fast-forward or it is refused — it can never clobber, and it
    never moves the trunk.

    Returns a short status string for the log line.
    """
    if os.environ.get("AUTOCOMMIT_DESIGN_NO_MAIN"):
        return "mirror off"

    # Plumbing takes repo-relative paths with forward slashes on every platform.
    # `rel_path` arrives from pathlib and is backslashed on Windows; `git add`
    # tolerates that, `update-index --cacheinfo` does not.
    rel_path = rel_path.replace(chr(92), "/")

    tmp_index = os.path.join(
        tempfile.gettempdir(), f"autocommit-idx-{os.getpid()}-{abs(hash(rel_path)) % 10**8}"
    )
    env = dict(os.environ, GIT_INDEX_FILE=tmp_index)

    def g(args):
        return subprocess.run(
            ["git"] + args, cwd=git_root, capture_output=True, text=True,
            timeout=60, env=env,
        )

    try:
        blob = g(["hash-object", "-w", abs_path]).stdout.strip()
        if not blob:
            return "mirror failed: hash-object"

        # Three attempts: the trunk of a repo several sessions push to does move
        # under us, and a rejected fast-forward is the expected outcome, not an
        # error worth surfacing.
        for _ in range(3):
            g(["fetch", "origin", "--quiet"])
            # Collect onto the docs branch; fall back to the trunk only as the
            # PARENT for the branch's very first commit. `branch` is always the
            # docs branch, so the trunk is never the push target.
            branch = DOCS_BRANCH
            base = f"origin/{DOCS_BRANCH}"
            if g(["rev-parse", "--verify", "--quiet", base]).returncode != 0:
                base = _base_ref(git_root)
                if base is None:
                    return "mirror skipped: no base ref"

            existing = g(["rev-parse", "--verify", "--quiet", f"{base}:{rel_path}"])
            if existing.returncode == 0 and existing.stdout.strip() == blob:
                return "already on trunk"

            if os.path.exists(tmp_index):
                os.unlink(tmp_index)
            if g(["read-tree", base]).returncode != 0:
                return "mirror failed: read-tree"
            if g(["update-index", "--add", "--cacheinfo",
                  f"100644,{blob},{rel_path}"]).returncode != 0:
                return "mirror failed: update-index"
            tree = g(["write-tree"]).stdout.strip()
            if not tree:
                return "mirror failed: write-tree"

            message = (
                f"{subject}\n\n"
                "Mirrored onto the docs collecting branch by the design-doc "
                "PostToolUse hook so the document is findable from any checkout, "
                "the branch that happened to be current.\n"
                f"File: {rel_path}\n"
            )
            commit = g(["commit-tree", tree, "-p", base, "-m", message]).stdout.strip()
            if not commit:
                return "mirror failed: commit-tree"

            if g(["push", "origin", f"{commit}:refs/heads/{branch}"]).returncode == 0:
                return f"mirrored -> {branch}"

        return "mirror refused: docs branch moved"
    except Exception:
        return "mirror failed"
    finally:
        try:
            if os.path.exists(tmp_index):
                os.unlink(tmp_index)
        except OSError:
            pass


def _push(git_root: str, amended: bool) -> None:
    """Best-effort push, DETACHED — network must not block the tool-call loop
    (a slow remote used to hold PostToolUse for up to 8s). An amend rewrites
    the tip, so the lease-guarded force fallback keeps the remote in sync."""
    cmd = "git push origin HEAD"
    if amended:
        cmd += " || git push --force-with-lease origin HEAD"
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.Popen(
        cmd, shell=True, cwd=git_root,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags,
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

    fname = abs_path.name
    subject = f"docs: auto-backup {fname}"

    # Stage the file
    _git(["add", rel_path], cwd=git_root)

    # Check if there is anything staged
    diff = _git(["diff", "--cached", "--quiet"], cwd=git_root)
    if diff.returncode == 0:
        # Nothing new for the branch — but the trunk may still be missing this
        # file from an earlier run whose mirror was refused. Retrying here is
        # what makes the mirror self-healing: any later touch of the document
        # gets it another chance, instead of stranding it permanently on the
        # first bad race. A no-op when the trunk already has the blob.
        mirror = _mirror_to_docs_branch(git_root, rel_path, str(abs_path), subject)
        if mirror not in ("already on trunk", "mirror off"):
            print(f"[autocommit] {fname} → {mirror} ({git_root})", file=sys.stderr)
        return
    commit_msg = f"{subject}\n\nAuto-committed by PostToolUse hook (Write/Edit guard).\nFile: {rel_path}"

    # Collapse consecutive backups of the same file into a single commit instead
    # of one per edit — a long planning session used to leave 15+ identical
    # commits on the branch, which is noise the operator later has to untangle.
    amended = _can_amend(git_root, rel_path, subject)
    args = ["commit", "-m", commit_msg] + (["--amend"] if amended else [])
    _git(args, cwd=git_root)

    _push(git_root, amended)

    # The branch backup above is the crash guard and must stay first: if the
    # mirror fails for any reason the document is still safe on a pushed branch.
    mirror = _mirror_to_docs_branch(git_root, rel_path, str(abs_path), subject)

    # Print to stderr so Claude Code shows it as a system note
    verb = "amend + push" if amended else "commit + push"
    print(f"[autocommit] {fname} → git {verb}, {mirror} ({git_root})", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail silently
