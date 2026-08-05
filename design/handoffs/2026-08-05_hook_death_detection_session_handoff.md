# Handoff — installer-managed hook death-detection across the ecosystem

**Written** 2026-08-05 | **Repo** `D:/dotclaude/dotclaude-ecosystem`, `main`, clean, pushed
(`16d77fc`, `main == origin/main`)

This session closed the idea-box gap *"modules present, hooks absent, nothing complains"*
across all three runtimes that actually have a hook surface (Claude, Codex, Cursor), plus
unrelated cleanup (TruthDeck probe registration, Conductor plan doc hygiene). Nine PRs
merged, all squash + fast-forwarded. No open branches, no dirty state.

## What shipped, in order

1. **#49** — registered `tsignal.dod_deck.v1` as a TruthDeck runtime probe (unrelated
   early-session task; also pinned `ruff==0.15.20` in CI after an unpinned-version drift
   broke it).
2. **#66–68** — TruthDeck Conductor R2 plan doc hygiene (frontmatter → `shipped`, pruned
   three stale present-tense lines). No code change.
3. **#69–70** — **installer-managed Claude hook block** (R2, full `/fwf`: CEO + matrix +
   eng review). `scripts/hooks_install.py` + `templates/hooks.manifest.json`: handler-level
   merge preserving foreign hooks, sidecar ownership, crash-recoverable, dry-run default.
   Migrated this operator's real `~/.claude/settings.json` live (10 hooks, 0 collisions).
4. **#71** — extended the death-detector to **Codex** (`~/.codex/hooks.json`).
   `scripts/codex_hooks_doctor.py`, read-only.
5. **#72–73** — **Cursor CU3** (idempotent install/rollback for `~/.cursor/hooks.json`),
   implementing an already-open slice of
   `design/plans/2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`.
   `scripts/install_cursor_session_lifecycle.py` + `scripts/cursor_hooks_doctor.py`.

Every installer wires into the daily janitor (`scripts/git_hygiene.py` →
`check_managed_hooks` / `check_codex_hooks` / `check_cursor_hooks`), each guarded (never
crashes the janitor), ASCII-safe, and scoped — none of them ever claims a hook is absent
from the *running* configuration, only from the one file each installer owns. That
reconciliation with the shipped `/curator` seven-source decision
(`2026-07-25_session_lifecycle_and_hook_hardening_r1.md`) is load-bearing; do not add a
detector that asserts absolute hook absence.

## Settled — do not re-litigate

- **Kimi and Antigravity have no hook surface.** Kimi (`~/.kimi-code`) is `config.toml` +
  `mcp.json` only. Antigravity has no proven session-event contract (Conductor's own
  `HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT`, already operator-reviewed). Do not build a hook
  installer for either without new discovery evidence that a hook surface now exists.
- **Cursor's `hooks.json` schema is FLAT**, not Claude/Codex's nested matcher-group shape —
  `hooks.<event>` is a list of handler dicts directly. Verified against
  `~/.cursor/skills-cursor/create-hook/SKILL.md`. Don't copy the Codex/Claude merge code
  verbatim if this is ever touched again.
- **Ownership detection must be anchored, never a bare substring match.** All three
  detectors/installers extract a quote-aware path token and require exact basename equality
  (`scripts/hooks_install._command_path_token`, reused everywhere). A bare `ADAPTER_NAME in
  command` check is a confirmed bug class — it both false-positives (drops a foreign hook
  that merely *mentions* the filename) and false-negatives-as-OK (the detector lies healthy).
  Found in Cursor's Stage-6 review, and the identical bug was independently already shipped
  in the Codex detector — fixed in the same round. If you add a fourth detector, anchor it
  from the start.
- **Installer test suites must never depend on a real local binary.** The Cursor CLI-version
  preflight (`_preflight_cli_version`) almost shipped with tests that silently passed only
  because this dev machine happens to have `cursor-agent` installed — would have broken
  every CI run. `skip_cli_preflight=True` + mocked `subprocess.run` tests are the pattern.
- **`/fwf` full lifecycle for R2** (Claude hooks): grill → plan → CEO → matrix
  (`fuse.py --mode free`) → eng → GO → implement → adversarial review → land. Each `/fwf`
  gate is real; the matrix run caught a load-bearing merge bug (group-level vs
  handler-level) before any code existed.
- **A "generic go" is not authorization for a plan's own named token.** The Cursor work sat
  inside an *existing*, already-CEO/matrix/eng-reviewed plan
  (`2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`) whose CU1–CU4 slices each
  require their own explicit operator phrase (mirrors Conductor's
  `GO CONDUCTOR HOST RESOURCE LEASE R2`). The operator's "go" for this session's Cursor work
  was interpreted as authorizing CU3 (build + test in temp homes) only; CU4 was deliberately
  left open pending its own explicit GO. Don't infer CU4 authorization from CU3's.

## What's open

**CU4 — real `~/.cursor/hooks.json` activation.** Not started. `cursor_hooks_doctor.py`
correctly reports `NEVER_INSTALLED` live on this machine right now — that's expected, not a
bug. To activate: `python scripts/install_cursor_session_lifecycle.py --apply` (dry-run
first, no `--apply`, to see the diff). The plan's own CU4 checklist item additionally wants
"exact IDE and CLI acceptance" run afterward — IDE is expected to land `HOLD DEGRADED`
per CU0-L evidence, not a failure.

**Cursor hook de-duplication** (noted, not done): the live `~/.claude/settings.json` still
carries two duplicate `Write`+`Edit` matcher-group pairs that `hooks_install.py`'s manifest
could collapse into one `Write|Edit` matcher each — recorded as an explicit deferred
expansion item in `design/plans/2026-08-04_installer_managed_hook_block_r2.md`, not touched
this session (decision B8: reproduce live behavior exactly, no de-dup as a side effect).

**No other open threads.** Every branch from this session is deleted; `main` is the only
live ref.

## Verification (if you pick this back up)

```powershell
python -m pytest -q scripts/tests/test_hooks_install.py scripts/tests/test_codex_hooks_doctor.py scripts/tests/test_install_cursor_session_lifecycle.py scripts/tests/test_cursor_hooks_doctor.py scripts/tests/test_hooks_janitor.py
python -m pytest -q scripts/tests/          # full suite: 499 passed, 11 subtests at last run
python scripts/hooks_install.py doctor --json
python scripts/git_hygiene.py --repo "D:/dotclaude/dotclaude-ecosystem" --json | python -c "import json,sys; print(json.load(sys.stdin).get('alarms'))"
```

Baseline at handoff: `499 passed, 11 subtests passed` on a quiet host. This same suite
showed 2–4 failures on a loaded host during this session (`session_router.py` 1.5s
subprocess-timeout signature, `WinError 32` tempdir races) — both pre-existing,
load-sensitive, and already documented in
`design/plans/2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md:946`. Not caused by
this session's diffs; don't chase them on a busy machine.
