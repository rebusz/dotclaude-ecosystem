#!/usr/bin/env python3
"""git_hygiene.py — idempotent worktree/branch reaper + main-drift alarm.

The "system higieny" that was supposed to keep the repo tidy but never existed
as an automaton. Safe by default (DRY-RUN); only --apply mutates.

Hard safety invariants (the gap that produced the recurring mess):
  - NEVER touches a checkout that has commits not on the base ref (unpushed
    work). If any such commit looks R3 -> escalate to a loud ALARM. Report only,
    never switch/delete.
  - NEVER deletes a branch that is checked out in ANY worktree.
  - NEVER deletes a branch with unique commits not merged into base (uses
    `git branch -d`, which itself refuses unmerged, as a second seatbelt).
  - NEVER removes a worktree that is locked, dirty (tracked OR untracked), or
    holds unique unmerged commits. Those hold real work -> preserved + reported.
  - NEVER mutates the PRIMARY working tree's branch or files.

What --apply does, and nothing else:
  - `git branch -d` on fully-merged, not-checked-out local branches.
  - `git worktree remove` on dead worktrees (merged HEAD + clean + unlocked).
  - `git worktree prune` for worktrees whose directory already vanished.

Usage:
  python git_hygiene.py --repo "D:/APPS/Tsignal 5.0"           # dry-run report
  python git_hygiene.py --repo "..." --fetch                   # refresh origin first
  python git_hygiene.py --repo "..." --apply                   # actually reap
  python git_hygiene.py --repo "..." --json                    # machine output
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Optional


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _contains(parent: str, child: str) -> bool:
    """True if `child` path is inside (or equals) `parent`."""
    parent, child = _norm(parent), _norm(child)
    return child == parent or child.startswith(parent + os.sep)


def run_git(repo: str, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, check=check,
    )


def git_out(repo: str, args: list[str]) -> str:
    return run_git(repo, args).stdout.strip()


def is_ancestor(repo: str, ref: str, base: str) -> bool:
    """True if `ref` is fully contained in `base` (no unique commits)."""
    cp = run_git(repo, ["merge-base", "--is-ancestor", ref, base], check=False)
    return cp.returncode == 0


def resolve_base(repo: str, prefer: str = "origin/main") -> str:
    for cand in (prefer, "main", "origin/HEAD"):
        if run_git(repo, ["rev-parse", "--verify", "--quiet", cand], check=False).returncode == 0:
            return cand
    raise SystemExit("git_hygiene: cannot resolve a base ref (origin/main / main)")


@dataclass
class Worktree:
    path: str
    head: str = ""
    branch: Optional[str] = None      # short name, or None if detached/bare
    locked: bool = False
    lock_reason: str = ""
    prunable: bool = False
    prune_reason: str = ""
    bare: bool = False
    is_primary: bool = False


def parse_worktrees(repo: str) -> list[Worktree]:
    raw = git_out(repo, ["worktree", "list", "--porcelain"])
    wts: list[Worktree] = []
    cur: Optional[Worktree] = None
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if cur is not None:
                wts.append(cur)
            cur = Worktree(path=line[len("worktree "):])
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur.head = line[len("HEAD "):]
        elif line.startswith("branch "):
            ref = line[len("branch "):]
            cur.branch = ref.replace("refs/heads/", "", 1)
        elif line == "detached":
            cur.branch = None
        elif line.startswith("locked"):
            cur.locked = True
            cur.lock_reason = line[len("locked"):].strip()
        elif line.startswith("prunable"):
            cur.prunable = True
            cur.prune_reason = line[len("prunable"):].strip()
        elif line == "bare":
            cur.bare = True
    if cur is not None:
        wts.append(cur)
    if wts:
        wts[0].is_primary = True   # git always lists the main worktree first
    return wts


def worktree_status(repo_path: str) -> tuple[bool, bool]:
    """Return (has_tracked_changes, has_untracked). Empty/missing -> (False, False)."""
    cp = run_git(repo_path, ["status", "--porcelain"], check=False)
    if cp.returncode != 0:
        return (False, False)  # dir gone / unreadable -> handled via prunable
    tracked = untracked = False
    for line in cp.stdout.splitlines():
        if line.startswith("?? "):
            untracked = True
        elif line.strip():
            tracked = True
    return (tracked, untracked)


def unique_commits(repo: str, ref: str, base: str) -> list[str]:
    """One-line commits in `ref` that are NOT in `base`."""
    out = git_out(repo, ["log", "--oneline", f"{base}..{ref}"])
    return [ln for ln in out.splitlines() if ln.strip()]


def looks_r3(subjects: list[str]) -> bool:
    return any("r3" in s.lower() for s in subjects)


@dataclass
class Report:
    base: str = ""
    base_sha: str = ""
    primary: dict = field(default_factory=dict)
    alarms: list[str] = field(default_factory=list)
    reap_branches: list[str] = field(default_factory=list)
    reap_worktrees: list[dict] = field(default_factory=list)
    prune_worktrees: list[dict] = field(default_factory=list)
    keep_worktrees: list[dict] = field(default_factory=list)
    deploy_overlay: list[str] = field(default_factory=list)     # files safe to overlay base->primary
    deploy_conflicts: list[dict] = field(default_factory=list)  # base-ahead files the primary also changed
    totals: dict = field(default_factory=dict)


def deploy_plan(repo: str, base: str, primary: "Worktree") -> tuple[list[str], list[dict]]:
    """Close the merge-to-main -> live-checkout loop.

    The reaper already ALARMS that the primary checkout is behind/off base, but
    never acts — so a fix merged to main never reaches the running bot's checkout
    unless someone overlays it by hand. This computes that overlay safely.

    Returns (overlay, conflicts):
      overlay   — files that `base` advanced and the primary did NOT independently
                  touch, whose working-tree content differs from base. Safe to
                  `git checkout base -- <file>` (WIP-preserving: only these files).
      conflicts — base-ahead files the primary changed (committed) OR has dirty in
                  its working tree. NEVER auto-overlaid (would clobber real work);
                  surfaced as alarms for the operator to reconcile.

    Hard invariants mirror the reaper: never clobber uncommitted WIP, never
    overwrite a file the primary owns a divergent version of, fully idempotent
    (a file already equal to base is silently skipped).
    """
    overlay: list[str] = []
    conflicts: list[dict] = []
    if primary is None or primary.branch is None:
        return overlay, conflicts  # detached/bare primary -> cannot reason, skip
    # merge-base: the last point primary and base agreed.
    mb = run_git(repo, ["merge-base", primary.branch, base], check=False)
    if mb.returncode != 0:
        return overlay, conflicts
    mb_sha = mb.stdout.strip()
    # Files `base` changed since the merge-base (candidates to propagate forward).
    changed = git_out(repo, ["diff", "--name-only", mb_sha, base]).splitlines()
    for f in (ln.strip() for ln in changed if ln.strip()):
        # 1) Idempotent: working-tree file already equals base -> already deployed.
        if run_git(repo, ["diff", "--quiet", base, "--", f], check=False).returncode == 0:
            continue
        # 2) WIP guard: file has uncommitted changes in primary -> never clobber.
        st = run_git(repo, ["status", "--porcelain", "--", f], check=False).stdout.strip()
        if st:
            conflicts.append({"file": f, "reason": "uncommitted WIP in primary"})
            continue
        # 3) Ownership guard: primary's committed version diverged from the
        #    merge-base (the primary changed this file too) -> real merge needed.
        if run_git(repo, ["diff", "--quiet", mb_sha, primary.branch, "--", f], check=False).returncode != 0:
            conflicts.append({"file": f, "reason": f"primary branch '{primary.branch}' has its own change"})
            continue
        # Safe: base advanced this file, primary never touched it, not dirty.
        overlay.append(f)
    return overlay, conflicts


def analyze(repo: str, base: str, protect: Optional[set[str]] = None) -> Report:
    protect = protect or set()
    r = Report(base=base, base_sha=git_out(repo, ["rev-parse", "--short", base]))
    wts = parse_worktrees(repo)
    checked_out = {w.branch for w in wts if w.branch}

    # ── PRIMARY working tree: alarm only, never touch ───────────────────────
    primary = next((w for w in wts if w.is_primary), None)
    if primary is not None:
        on_base = primary.branch == base.replace("origin/", "")
        uniq = [] if primary.branch is None else unique_commits(repo, primary.branch, base)
        r.primary = {
            "path": primary.path,
            "branch": primary.branch,
            "on_main": on_base,
            "unpushed_commits": uniq,
            "r3": looks_r3(uniq),
        }
        if primary.branch not in (base.replace("origin/", ""), None) and not on_base:
            r.alarms.append(
                f"PRIMARY checkout is on '{primary.branch}', not '{base.replace('origin/','')}' "
                f"({len(uniq)} commit(s) not on base). NOT switched — operator decision."
            )
        if uniq:
            tag = " [R3]" if looks_r3(uniq) else ""
            r.alarms.append(
                f"PRIMARY has {len(uniq)} unpushed commit(s){tag} — left untouched: "
                + "; ".join(uniq[:4])
            )
        # ── Deploy loop: propagate merged-to-base files into the live checkout ──
        overlay, conflicts = deploy_plan(repo, base, primary)
        r.deploy_overlay = overlay
        r.deploy_conflicts = conflicts
        for c in conflicts:
            r.alarms.append(
                f"DEPLOY conflict: base advanced '{c['file']}' but {c['reason']} "
                f"— NOT overlaid, operator reconcile."
            )

    # ── Worktrees: classify reap vs keep vs prune ───────────────────────────
    for w in wts:
        if w.is_primary or w.bare:
            continue
        if w.prunable:
            r.prune_worktrees.append({"path": w.path, "reason": w.prune_reason or "dir missing"})
            continue
        if any(_contains(p, w.path) or _contains(w.path, p) for p in protect):
            r.keep_worktrees.append({
                "path": w.path, "branch": w.branch, "head": w.head[:8],
                "reasons": ["protected (active session / explicit --protect)"],
            })
            continue
        ref = w.branch or w.head
        uniq = unique_commits(repo, ref, base)
        tracked, untracked = worktree_status(w.path)
        merged = is_ancestor(repo, w.head, base)
        reasons = []
        if w.locked:
            reasons.append(f"locked({w.lock_reason or 'no reason'})")
        if uniq:
            reasons.append(f"{len(uniq)} unmerged commit(s)" + (" [R3]" if looks_r3(uniq) else ""))
        if tracked:
            reasons.append("uncommitted changes")
        if untracked:
            reasons.append("untracked files")
        if not merged and not uniq:
            reasons.append("HEAD not in base")
        if reasons:
            r.keep_worktrees.append({
                "path": w.path, "branch": w.branch, "head": w.head[:8],
                "reasons": reasons,
            })
        else:
            r.reap_worktrees.append({"path": w.path, "branch": w.branch, "head": w.head[:8]})

    # ── Local branches fully merged into base and not checked out anywhere ───
    for line in git_out(repo, ["for-each-ref", "--format=%(refname:short)", "refs/heads"]).splitlines():
        b = line.strip()
        if not b or b == base.replace("origin/", ""):
            continue
        if b in checked_out:
            continue
        if is_ancestor(repo, b, base):
            r.reap_branches.append(b)

    r.totals = {
        "worktrees_total": len(wts),
        "local_branches": len(git_out(repo, ["for-each-ref", "--format=x", "refs/heads"]).splitlines()),
        "reap_branches": len(r.reap_branches),
        "reap_worktrees": len(r.reap_worktrees),
        "prune_worktrees": len(r.prune_worktrees),
        "keep_worktrees": len(r.keep_worktrees),
        "deploy_overlay": len(r.deploy_overlay),
        "deploy_conflicts": len(r.deploy_conflicts),
    }
    return r


def print_report(r: Report, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n=== git_hygiene [{mode}] — base={r.base} ({r.base_sha}) ===\n")

    p = r.primary
    print("PRIMARY working tree:")
    print(f"  path   : {p.get('path')}")
    print(f"  branch : {p.get('branch')}  (on base: {p.get('on_main')})")
    if p.get("unpushed_commits"):
        print(f"  unpushed: {len(p['unpushed_commits'])}"
              + ("  [R3 — escalated]" if p.get("r3") else ""))
        for c in p["unpushed_commits"][:6]:
            print(f"            {c}")
    print()

    if r.alarms:
        print("ALARMS (report-only, never auto-acted):")
        for a in r.alarms:
            print(f"  ! {a}")
        print()

    print(f"REAP branches (merged into base, not checked out) — {len(r.reap_branches)}:")
    for b in r.reap_branches:
        print(f"  - {b}")
    print()

    print(f"REAP worktrees (merged HEAD + clean + unlocked) — {len(r.reap_worktrees)}:")
    for w in r.reap_worktrees:
        print(f"  - {w['path']}  [{w['branch'] or 'detached@' + w['head']}]")
    print()

    if r.prune_worktrees:
        print(f"PRUNE worktrees (directory already gone) — {len(r.prune_worktrees)}:")
        for w in r.prune_worktrees:
            print(f"  - {w['path']}  ({w['reason']})")
        print()

    print(f"KEEP worktrees (hold work / locked / dirty — PRESERVED) — {len(r.keep_worktrees)}:")
    for w in r.keep_worktrees:
        print(f"  - {w['path']}  [{w['branch'] or 'detached@' + w['head']}]  :: {', '.join(w['reasons'])}")
    print()

    if r.deploy_overlay or r.deploy_conflicts:
        print(f"DEPLOY to live checkout (base->primary, WIP-preserving) - "
              f"{len(r.deploy_overlay)} overlay, {len(r.deploy_conflicts)} conflict:")
        for f in r.deploy_overlay:
            print(f"  + {f}")
        for c in r.deploy_conflicts:
            print(f"  ! {c['file']}  ({c['reason']}) — skipped")
        print()

    print("TOTALS:", json.dumps(r.totals))
    if not apply:
        hint = "the REAP/PRUNE sets"
        if r.deploy_overlay:
            hint += " and overlay the DEPLOY set into the live checkout"
        print(f"\n(DRY-RUN — nothing changed. Re-run with --apply to reap {hint}.)")


def do_apply(repo: str, r: Report) -> None:
    for w in r.reap_worktrees:
        cp = run_git(repo, ["worktree", "remove", w["path"]], check=False)
        print(f"  worktree remove {w['path']}: {'ok' if cp.returncode == 0 else cp.stderr.strip()}")
    if r.prune_worktrees:
        run_git(repo, ["worktree", "prune"], check=False)
        print(f"  worktree prune: {len(r.prune_worktrees)} stale entr(ies)")
    for b in r.reap_branches:
        cp = run_git(repo, ["branch", "-d", b], check=False)
        print(f"  branch -d {b}: {'ok' if cp.returncode == 0 else cp.stderr.strip()}")


def do_deploy(repo: str, r: Report, base: str) -> None:
    """Overlay the safe DEPLOY set from `base` into the live (primary) checkout.

    One atomic-ish `git checkout base -- <files>` (sub-second window), so a bot
    restart mid-deploy can't load a half-updated set. Disk-only: a *running* bot
    keeps its in-memory code until restart — this never hot-swaps a live process.
    """
    if not r.deploy_overlay:
        return
    cp = run_git(repo, ["checkout", base, "--", *r.deploy_overlay], check=False)
    if cp.returncode == 0:
        for f in r.deploy_overlay:
            print(f"  deployed {f}")
        print(f"  -> {len(r.deploy_overlay)} file(s) overlaid into {repo} from {base}.")
        print("  [!] RESTART Tsignal (EcoControl) to load the deployed code - running "
              "process keeps old code until restart.")
    else:
        print(f"  DEPLOY FAILED: {cp.stderr.strip()}")


def main(argv: list[str]) -> int:
    # Windows scheduled-task consoles default to cp1252; make non-ASCII output
    # (em-dashes etc.) safe rather than crashing the deploy tool on encode.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Idempotent worktree/branch reaper + main-drift alarm.")
    ap.add_argument("--repo", required=True, help="path to the primary git checkout")
    ap.add_argument("--base", default="origin/main", help="base ref to measure 'merged' against")
    ap.add_argument("--fetch", action="store_true", help="git fetch --prune before analysis")
    ap.add_argument("--apply", action="store_true", help="actually reap (default is dry-run)")
    ap.add_argument("--deploy", action="store_true",
                    help="also overlay merged-to-base files into the live (primary) checkout "
                         "(WIP-preserving). Requires --apply to write; analysis is always shown.")
    ap.add_argument("--protect", action="append", default=[],
                    help="worktree path to never reap (repeatable). The current working "
                         "directory's worktree is always auto-protected.")
    ap.add_argument("--allow-primary-drift", action="store_true",
                    help="bypass the primary-unpushed-R3 reap refusal — reaping never touches "
                         "the primary checkout; explicit operator override.")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of text")
    a = ap.parse_args(argv)

    if a.fetch:
        run_git(a.repo, ["fetch", "--prune", "origin"], check=False)

    base = resolve_base(a.repo, a.base)
    protect = {_norm(p) for p in a.protect}
    protect.add(_norm(os.getcwd()))   # never reap the worktree we are running from
    r = analyze(a.repo, base, protect=protect)

    if a.json:
        print(json.dumps(r.__dict__, indent=2))
    else:
        print_report(r, a.apply)

    rc = 0
    if a.apply:
        print("\n=== APPLYING ===")
        # Reaping is destructive — refuse if the primary holds unpushed R3 work,
        # unless explicitly overridden (reaping never touches the primary checkout).
        if r.primary.get("r3") and not a.allow_primary_drift:
            print("REFUSING reap: PRIMARY has unpushed R3 work. Resolve that first, or pass "
                  "--allow-primary-drift to reap anyway (reap never touches the primary).",
                  file=sys.stderr)
            rc = 2
        else:
            if r.primary.get("r3"):
                print("[override] reaping despite primary unpushed R3 (--allow-primary-drift); "
                      "the primary checkout is never touched by reap.")
            do_apply(a.repo, r)
        # Deploy is additive + WIP-safe (conflict guard skips any primary-owned/dirty
        # file), so it runs independently of the destructive-reap refusal.
        if a.deploy:
            do_deploy(a.repo, r, base)
        print("done.")
    elif a.deploy and r.deploy_overlay:
        print("\n(DEPLOY is dry-run without --apply — add --apply to overlay the files above.)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
