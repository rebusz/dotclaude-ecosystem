#!/usr/bin/env python3
"""PostToolUse hook — back a design doc up to the branch AND mirror it for everyone.

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

Both mechanisms are scoped to the one document being written. The commit carries
an explicit pathspec, so nothing else the operator had staged rides along, and a
protected trunk or a detached HEAD gets the mirror only — never a local commit
and never a push. Everything that touches the network runs inside one wall-clock
budget set at entry, and a failed push is reported rather than discarded.

Fail silently — never break the session. Set AUTOCOMMIT_DESIGN_NO_MAIN=1 to keep
the branch backup and skip the mirror.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# The PostToolUse harness kills this hook at 30s (templates/hooks.manifest.json).
# A SIGKILL skips `finally`, which is how the throwaway index used to be left
# behind. Everything that touches the network is therefore bounded by one
# wall-clock deadline set at entry, comfortably inside the harness ceiling.
HOOK_BUDGET_S = 20.0
GIT_CALL_CAP_S = 30.0
NETWORK_CALL_CAP_S = 10.0

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


def _remaining(deadline: float | None) -> float:
    """Seconds left on the hook budget. `None` means an unbounded caller (tests)."""
    if deadline is None:
        return GIT_CALL_CAP_S
    return deadline - time.monotonic()


def _git(
    args: list[str],
    cwd: str,
    *,
    deadline: float | None = None,
    cap: float = GIT_CALL_CAP_S,
) -> subprocess.CompletedProcess:
    timeout = min(cap, max(0.5, _remaining(deadline)))
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _current_branch(git_root: str, deadline: float | None = None) -> str:
    return _git(
        ["rev-parse", "--abbrev-ref", "HEAD"], cwd=git_root, deadline=deadline
    ).stdout.strip()


def _branch_accepts_backup_commit(branch: str) -> bool:
    """False when committing here would rewrite a shared trunk or go nowhere.

    A protected branch is the trunk a live trading stack runs from; an earlier
    version of this hook had no guard on the commit path at all (only on the
    amend path), so a design-doc write while on `main` produced a commit and a
    `git push origin HEAD` straight to the trunk. Detached HEAD is refused for a
    different reason: the commit would be unreferenced and the push errors out.
    In both cases the docs-branch mirror still runs and is the durable backup.
    """
    return bool(branch) and branch != "HEAD" and branch not in PROTECTED_BRANCHES


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
    if not _branch_accepts_backup_commit(_current_branch(git_root)):
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


def _mirror_to_docs_branch(
    git_root: str,
    rel_path: str,
    abs_path: str,
    subject: str,
    deadline: float | None = None,
) -> str:
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

    def g(args, cap: float = GIT_CALL_CAP_S):
        return subprocess.run(
            ["git"] + args, cwd=git_root, capture_output=True, text=True,
            timeout=min(cap, max(0.5, _remaining(deadline))), env=env,
        )

    try:
        blob = g(["hash-object", "-w", abs_path]).stdout.strip()
        if not blob:
            return "mirror failed: hash-object"

        # Three attempts: the trunk of a repo several sessions push to does move
        # under us, and a rejected fast-forward is the expected outcome, not an
        # error worth surfacing.
        for _ in range(3):
            # The retry exists for a trunk that moves under us, not for a remote
            # that is down. Stop retrying once the budget is spent so the harness
            # never has to SIGKILL us mid-plumbing.
            if _remaining(deadline) <= 1.0:
                return "mirror deadline"
            g(["fetch", "origin", "--quiet"], cap=NETWORK_CALL_CAP_S)
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

            push = g(
                ["push", "origin", f"{commit}:refs/heads/{branch}"],
                cap=NETWORK_CALL_CAP_S,
            )
            if push.returncode == 0:
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


def _push(git_root: str, amended: bool, deadline: float | None = None) -> str:
    """Bounded push whose failure is visible.

    This used to be a detached `shell=True` fire-and-forget with output sent to
    DEVNULL, so a rejected push, an auth prompt or a hung remote still reported
    "commit + push". It was detached because a slow remote once held PostToolUse
    for 8s — but the docs mirror below already does synchronous network work, so
    the honest fix is a short timeout inside one shared budget rather than
    hiding the result. An amend rewrites the tip, hence the lease-guarded
    fallback; `--force-with-lease` still refuses to clobber someone else's work.
    """
    if _remaining(deadline) <= 1.0:
        return "push skipped: deadline"
    result = _git(
        ["push", "origin", "HEAD"], cwd=git_root, deadline=deadline, cap=NETWORK_CALL_CAP_S
    )
    if result.returncode == 0:
        return "pushed"
    if amended and _remaining(deadline) > 1.0:
        lease = _git(
            ["push", "--force-with-lease", "origin", "HEAD"],
            cwd=git_root,
            deadline=deadline,
            cap=NETWORK_CALL_CAP_S,
        )
        if lease.returncode == 0:
            return "pushed (lease)"
        result = lease
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    return f"push FAILED: {detail[-1][:120]}" if detail else "push FAILED"


def main() -> None:
    deadline = time.monotonic() + HOOK_BUDGET_S
    try:
        # Read bytes, not text. `sys.stdin` is cp1252 with surrogateescape on a
        # default Windows Python, so a UTF-8 payload is silently mojibaked
        # rather than raising — which is how non-ASCII file paths stopped
        # resolving on disk without a single diagnostic.
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
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

    # Forward slashes everywhere: git pathspecs treat a backslash as an escape
    # character, and every path below is passed as a pathspec now, not just to
    # `git add` (which tolerated the Windows form).
    rel_path = _normalize(str(abs_path.relative_to(git_root)))

    fname = abs_path.name
    subject = f"docs: auto-backup {fname}"

    # A protected trunk or a detached HEAD never gets a local commit or a push;
    # the mirror below is the durable backup in that case.
    branch = _current_branch(git_root, deadline)
    if not _branch_accepts_backup_commit(branch):
        mirror = _mirror_to_docs_branch(
            git_root, rel_path, str(abs_path), subject, deadline
        )
        where = branch or "unknown"
        print(
            f"[autocommit] {fname} → no branch commit on '{where}', {mirror} ({git_root})",
            file=sys.stderr,
        )
        return

    # Stage the file
    _git(["add", "--", rel_path], cwd=git_root, deadline=deadline)

    # Is THIS path staged? The old check asked whether *anything* was staged,
    # and the commit below carried no pathspec, so an unrelated file the
    # operator had staged was swallowed into a "docs: auto-backup" commit and
    # pushed with it.
    diff = _git(
        ["diff", "--cached", "--quiet", "--", rel_path], cwd=git_root, deadline=deadline
    )
    if diff.returncode == 0:
        # Nothing new for the branch — but the trunk may still be missing this
        # file from an earlier run whose mirror was refused. Retrying here is
        # what makes the mirror self-healing: any later touch of the document
        # gets it another chance, instead of stranding it permanently on the
        # first bad race. A no-op when the trunk already has the blob.
        mirror = _mirror_to_docs_branch(
            git_root, rel_path, str(abs_path), subject, deadline
        )
        if mirror not in ("already on trunk", "mirror off"):
            print(f"[autocommit] {fname} → {mirror} ({git_root})", file=sys.stderr)
        return
    commit_msg = f"{subject}\n\nAuto-committed by PostToolUse hook (Write/Edit guard).\nFile: {rel_path}"

    # Collapse consecutive backups of the same file into a single commit instead
    # of one per edit — a long planning session used to leave 15+ identical
    # commits on the branch, which is noise the operator later has to untangle.
    amended = _can_amend(git_root, rel_path, subject)
    # `--` scopes the commit to this one path (implying --only), so whatever
    # else sits in the index stays there instead of riding along.
    args = ["commit", "-m", commit_msg] + (["--amend"] if amended else []) + ["--", rel_path]
    committed = _git(args, cwd=git_root, deadline=deadline)
    if committed.returncode != 0:
        detail = (committed.stderr or "").strip().splitlines()
        print(
            f"[autocommit] {fname} → commit FAILED: "
            f"{detail[-1][:120] if detail else 'unknown'} ({git_root})",
            file=sys.stderr,
        )
        return

    push = _push(git_root, amended, deadline)

    # The branch backup above is the crash guard and must stay first: if the
    # mirror fails for any reason the document is still safe on a pushed branch.
    mirror = _mirror_to_docs_branch(git_root, rel_path, str(abs_path), subject, deadline)

    # Print to stderr so Claude Code shows it as a system note
    verb = "amend" if amended else "commit"
    print(f"[autocommit] {fname} → git {verb}, {push}, {mirror} ({git_root})", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # fail silently
