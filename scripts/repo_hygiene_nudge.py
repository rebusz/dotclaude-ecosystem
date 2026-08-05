#!/usr/bin/env python3
"""Stop-hook: gentle repo-divergence nudge.

Read-only, throttled, fail-silent. NEVER fetches, NEVER merges, NEVER pushes.
Purpose: surface when a branch has drifted far from the trunk so a big-bang
merge never sneaks up again. Integrate small and often.

Registered as a Stop hook in ~/.claude/settings.json. Output (when any branch
is far ahead of trunk) is appended to the turn footer at most once per repo
every few hours.
"""
import json
import os
import pathlib
import subprocess
import time

THROTTLE_SECONDS = 3 * 3600      # at most one report per repo every 3h
WARN_THRESHOLD = 50              # commits a branch is ahead of trunk before nudging
MAX_LINES = 5
STATE_DIR = pathlib.Path.home() / ".claude" / "state"
STATE_FILE = STATE_DIR / "repo_hygiene_nudge.json"


def git(args, cwd):
    return subprocess.run(
        ["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=8
    )


def main():
    cwd = os.getcwd()
    top = git(["rev-parse", "--show-toplevel"], cwd)
    if top.returncode != 0:
        return
    root = top.stdout.strip()

    # per-repo throttle
    now = time.time()
    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        state = {}
    if now - float(state.get(root, 0)) < THROTTLE_SECONDS:
        return

    # resolve trunk (default branch)
    trunk = None
    sym = git(["symbolic-ref", "refs/remotes/origin/HEAD"], root)
    if sym.returncode == 0 and sym.stdout.strip():
        trunk = sym.stdout.strip().rsplit("/", 1)[-1]
    if not trunk:
        for cand in ("master", "main"):
            if git(["rev-parse", "--verify", "--quiet", "origin/" + cand], root).returncode == 0:
                trunk = cand
                break
    if not trunk:
        return
    base = "origin/" + trunk
    if git(["rev-parse", "--verify", "--quiet", base], root).returncode != 0:
        return

    # Record the check BEFORE the scan: if the scan is killed by the hook
    # timeout, an unwritten throttle state makes it retry on every Stop —
    # that chronic-retry loop is exactly what produced 72 straight timeouts.
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        state[root] = now
        STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass

    # divergence of every remote branch vs trunk, using local refs (no fetch).
    # ONE batched for-each-ref (git >= 2.41 %(ahead-behind:)) — a per-branch
    # rev-list blew past the 10s hook timeout at 420 remote branches.
    refs = git(
        ["for-each-ref", "--format=%(refname:short) %(ahead-behind:" + base + ")",
         "refs/remotes/origin"],
        root,
    )
    worst = []
    for line in refs.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3:
            continue
        b = parts[0]
        if b == base or b == "origin" or "/" not in b or b.endswith("/HEAD"):
            continue
        try:
            ahead = int(parts[1])  # commits on branch not on trunk
        except ValueError:
            continue
        if ahead >= WARN_THRESHOLD:
            worst.append((ahead, b))

    if worst:
        worst.sort(reverse=True)
        lines = ["  - {1}: {0} commits ahead of {2}".format(n, b, trunk) for n, b in worst[:MAX_LINES]]
        print(
            "[repo-hygiene] branches drifting from `{0}` "
            "(integrate small & often; a fast-forward is safe, a diverged merge is where things break):\n{1}".format(
                trunk, "\n".join(lines)
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never disrupt the session
