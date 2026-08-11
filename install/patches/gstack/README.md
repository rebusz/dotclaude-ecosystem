# Local gstack patches (Windows)

gstack is a **third-party upstream** checkout — `https://github.com/garrytan/gstack.git`
cloned into `~/.claude/skills/gstack`. We do not own it and cannot push to it, so
Windows-only fixes live here as patches and are re-applied after every upgrade.

## Why these live OUTSIDE the gstack clone

`/gstack-upgrade` runs (see `gstack-upgrade/SKILL.md`):

```
git stash
git fetch origin
git reset --hard origin/main
```

That has two consequences worth stating plainly:

- **A local commit in the gstack clone is destroyed.** `reset --hard` discards it, and
  because the tree was clean the preceding `git stash` saved nothing — so the fix
  disappears with **no warning at all**. Committing locally is the one option that
  looks safest and is actually the most dangerous.
- **Uncommitted changes survive only as a stash**, and only if the operator remembers
  the "run `git stash pop`" hint. After a large upstream jump that pop can conflict.

So the durable copy is here, in a repo we own and version.

## Applying after an upgrade

From the gstack skill directory:

```bash
cd ~/.claude/skills/gstack
git apply D:/dotclaude/dotclaude-ecosystem/install/patches/gstack/2026-07-24_windows-console-and-liveness.patch
```

Check first with `git apply --check <patch>`; if it reports a conflict, upstream has
touched the same lines — re-derive the fix rather than forcing it. Verified
2026-07-24: the patch applies cleanly onto `origin/main`, 33 commits ahead of the
then-local HEAD, because upstream has not touched either file.

`browse/dist/` is an untracked local build, so a rebuild from unpatched `src/` silently
reverts the runtime behaviour even when `dist/` still looks correct. Re-apply the patch
**before** rebuilding.

## 2026-07-24_windows-console-and-liveness.patch

Two Windows-only defects in the `browse` daemon. Neither exists upstream (verified:
zero occurrences of `windowsHide` / `EPERM` on `origin/main`).

**`browse/src/bun-polyfill.cjs` — flashing console windows.**
The polyfill maps `Bun.spawn`/`Bun.spawnSync` onto Node's `child_process`. Node defaults
to `windowsHide: false`, so every probe (including the `tasklist` liveness check) popped
a visible console window; real Bun never shows one. Adds `windowsHide: true` to both.
This is what keeps the tooling silent by default on Windows.

**`browse/src/error-handling.ts` — watchdog leaked live agents.**
`isProcessAlive()` shelled out to `tasklist`. Under load its 3s timeout returned an empty
buffer, which the caller read as "process dead" — so the watchdog respawned an agent that
was still running and leaked the original. The patch tries `process.kill(pid, 0)` first: a
synchronous existence probe that spawns nothing, treats `EPERM` as alive (exists, other
user) and `ESRCH` as gone, and falls through to the old `tasklist` path on anything else.
Also removes the measured ~230 ms per-probe spawn cost.

Origin: session `c000451b-386f-4c7d-8fa6-447dbb2f4d18`, VAVO-website worktree, 2026-07-24.

## Upstreaming

These are general Windows correctness fixes, not local preferences — the liveness bug
would bite any Windows user. Sending them to `garrytan/gstack` would retire this
directory. That is an outward-facing action on a third-party public repo, so it needs
the operator's explicit go-ahead.
