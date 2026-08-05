---
title: Installer-Managed settings.json Hook Block
date: 2026-08-04
status: in-progress
status_detail: reviewed-ceo-matrix-eng-clear-awaiting-r2-go
risk: R2
phase: plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, installer, hooks, settings, drift-detection, janitor]
related:
  - design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md
  - design/plans/2026-07-22_truthdeck_agent_evidence_control_plane_r1.md
  - design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md
---

# Installer-Managed settings.json Hook Block

## Executive decision

Build a bounded installer that **wires the ecosystem's canonical Claude hook block into
`~/.claude/settings.json`** from a single declarative source of truth, with ownership
recorded in a sidecar manifest, drift/absence detection scoped to the file it manages,
and a passive alarm surfaced through the existing daily janitor.

The installer answers one question the ecosystem currently cannot:

> Are the ecosystem's hooks actually wired on this machine, or did the modules ship while
> the `settings.json` entries were never installed?

Today the answer is discovered only by accident. Installers (`truthdeck_install.py`,
`conductor_install.py`) copy `scripts/*.py` so modules ship, but no installer writes the
`settings.json` hook entries, so every machine wires hooks by hand and nothing detects a
machine that never did. That is the one failure mode where the system is structurally
incapable of reporting its own death: modules present, hooks absent, operator believes it
is live, nothing runs and nothing complains.

This plan does not reopen `2026-07-25_session_lifecycle_and_hook_hardening_r1.md`. That
plan shipped the hooks themselves and **explicitly recorded this installer/reinstall gap
as out of its scope** ("Fixes ... exist on one machine only and do not survive a reinstall.
Recorded so the gap is not mistaken for coverage."). This plan fills exactly that recorded
gap and nothing more.

## Consequence, downside, reversibility

- **Proposed action:** add a declarative hook manifest, an installer that renders it into a
  managed block in `~/.claude/settings.json`, a sidecar install-manifest recording exactly
  what was written, a `doctor`/`status` check, a passive janitor alarm, and the adoption of
  two currently home-only hook scripts into the repository.
- **Plausible downside if wrong:** a merge bug could clobber a foreign hook, double-fire a
  hook, or (the specific trap below) assert **false absence** for a hook that is actually
  live from another Claude Code hook source.
- **Reversibility:** fully reversible. Surgically remove the managed block (restore the
  timestamped `settings.json` backup), delete the sidecar manifest, revert the janitor edit.
  No application repo, TruthDeck snapshot, or session state is touched. Removing one managed
  entry degrades one capability and breaks nothing else (inherited invariant).
- **Risk grade:** **R2**. It mutates durable config that the harness itself executes, with a
  merge/ownership/drift contract and a scheduled-task alarm surface. It has no broker,
  order-path, live-trading, runtime, or generic-shell authority; it is not R3.

## Phase 0 - restatement and collision verdict

### Goal

One installer wires the canonical ecosystem Claude hook block into global
`~/.claude/settings.json` idempotently, records ownership, migrates an already-hand-wired
machine to the managed form without double-firing, and makes a machine that never wired the
block discoverable through the existing daily janitor.

### Collision check

The plan-context loader cannot catalog this repository (`D:/dotclaude`, not `D:/APPS`) - the
same known limitation recorded by the Conductor plan. A bounded manual fallback inspected the
repo, `IDEA_BOX.md`, and adjacent plans.

- **`2026-07-25_session_lifecycle_and_hook_hardening_r1.md` (SHIPPED, R1)** overlaps and is
  reconciled below. It (a) records the installer/reinstall gap as out of scope - this plan
  fills it; (b) decided in S4 (`/curator`, Stage 3b, Codex C9, verified) that a tool must
  **never assert a hook is absent from one settings file** because hooks resolve from seven
  sources (user/project/local settings, managed policy, plugin `hooks.json`, skill and agent
  frontmatter), so a single-file reader reports false absence. **This plan honors that
  decision** (see Invariant 5 and the reconciled detector).
- **`templates/settings.json.template`** exists but is orphaned (referenced only by README,
  consumed by no installer) and partial (3 of the 8 live hook entries, stale paths). Retired
  by this plan in favor of the declarative manifest.
- **`install_codex_session_lifecycle.py`** already implements owned-hook merge into a JSON
  config (`_render_hooks`, `_handler_is_owned`, `_without_owned_handlers`, backup +
  `atomic_write_bytes` + restore) for **Codex** hooks (`~/.codex`). Its merge machinery is
  the implementation reference; its surface (Codex) is explicitly out of scope here.

**Verdict: CREATE NEW PLAN, FILL THE RECORDED GAP.** Do not reopen the shipped session
lifecycle plan; do not re-own the Codex hook surface.

`PONYTAIL: NOT USED` - R2 config-persistence installer work is excluded from the
simplification checkpoint.

>> PHASE 0 COMPLETE

## Current-state evidence and reuse map

Baseline at plan creation (`main == origin/main`, worktree clean):

Live `~/.claude/settings.json` wires 8 hook entries the installer must adopt, in three tiers:

| Tier | Scripts | Live wiring | In repo? |
|---|---|---|---|
| A - standalone, shipped | `autocommit_design_docs`, `auto_sync_context_hook`, `plan_keyword_detector`, `answer_footer` | points at `~/.claude/scripts/` (copies) | yes, byte-identical |
| B - repo-relative deps | `session_router`, `session_lifecycle` | points at the repo checkout `scripts/` | yes |
| C - home-only | `repo_hygiene_nudge`, `memory_size_guard` | points at `~/.claude/scripts/` | **no - adopted by this plan** |

Key facts driving the design:

- `session_router.py` imports repo siblings (`_catalog_common`, `session_state`); it only runs
  with the repo `scripts/` dir on `sys.path`. This is why Tier B points at the checkout and why
  the canonical target is the checkout, not lone home copies.
- Tier A and Tier C scripts are pure-stdlib standalone.
- Interpreter and path drift already exist live (`py` vs `python`; `~/.claude/scripts` vs
  checkout), so any first install must migrate, not merely append.

Reuse map:

| Existing surface | Use here | Must not become |
|---|---|---|
| `truthdeck_install.py` install-manifest, ownership hashes, foreign-file refusal, `status` | sidecar-manifest + doctor pattern | a second installer idiom |
| `install_codex_session_lifecycle.py` JSON hook merge + backup/restore | settings.json merge machinery | a re-owned Codex surface |
| `git_hygiene.py` alarm mechanism + scheduled task | passive death-detector host | a cleanup authority over hooks |
| Claude Code built-in `/hooks` merged view | authoritative reference for the operator | reimplemented in Python |

## Frozen product contract

### Recorded decisions (from the 2026-08-04 grill)

- **D1 - full managed set.** The managed block is every ecosystem hook (Tiers A+B+C). The two
  Tier-C scripts are adopted into `scripts/` as part of this work so the manifest is complete;
  a detector blind to two hooks would reproduce the failure mode in miniature.
- **D2 - point at the checkout.** Managed hooks are written as absolute paths into the
  operator's primary repo checkout `scripts/` dir. This satisfies `session_router`'s sibling
  imports, eliminates repo/home copy drift, and reframes the installer as a wiring +
  verification tool, not a second file-copier. The checkout root is detected and pinned at
  install time; `doctor` fails closed if a target path no longer resolves.
- **D3 - sidecar-manifest ownership.** Ownership lives in a sidecar
  `~/.claude/hooks-install-manifest.json` recording the exact `(event, matcher, command)`
  tuples written (the `truthdeck_install` idiom). `settings.json` stays 100% standard schema;
  no in-band marker, no dependency on unknown-key tolerance.
- **D4 - replace-to-canonical.** Reconciliation identity is `(event, managed-script-basename)`.
  Any existing entry referencing a managed script is rewritten to canonical form and recorded;
  this migrates the hand-wired machine (fixing path/interpreter drift) without double-firing.
  Safety rails: always back up `settings.json` before mutation; **default to dry-run**, apply
  only with explicit `--apply`. Matchers for these hooks are ecosystem-canonical - customizing
  them is not supported; change the manifest.
- **D5 - detector reconciled with the seven-source truth.** `doctor` and the janitor assert
  only a claim they can prove: whether the **managed block this installer wrote** is present /
  absent / drifted **in `~/.claude/settings.json`**, versus the sidecar manifest. They never
  assert absolute hook absence. Any janitor alarm is scoped in wording and points at `/hooks`
  for the authoritative merged view.
- **D6 - dedicated manifest as SoT.** `templates/hooks.manifest.json` is the single source of
  truth; the orphaned `templates/settings.json.template` is retired and the README pointer
  updated.
- **D7 - interpreter resolved at install.** The manifest carries a logical interpreter; the
  installer resolves it per-OS (`py` on Windows, `python3` on POSIX) and `doctor` verifies it
  resolves.
- **D8 - global scope only.** v1 manages global `~/.claude/settings.json` Claude hooks. Project
  `.claude/settings.json`, `settings.local.json`, and Codex hooks are explicit non-goals; Codex
  parity is a deferred follow-up reusing the same manifest shape.

### Non-negotiable invariants

1. **The manifest is the single source of truth.** Live entries and the sidecar manifest are
   rendered from it; the installer never invents an entry not in the manifest.
2. **Ownership is explicit and surgical.** The installer touches only entries recorded in its
   sidecar manifest or matched to a managed script by `(event, basename)`. A foreign hook
   (command referencing a non-managed script) is never modified or removed.
3. **Never destroy without a backup.** Every `settings.json` mutation is preceded by a
   timestamped backup and performed by atomic write.
4. **Advisory only.** No hook this installer manages, and no part of the installer, returns
   `decision: block` or `continue: false`. Inherited from the shipped session-lifecycle
   contract.
5. **Never assert absolute hook absence.** Detection is scoped to "the managed block in
   `~/.claude/settings.json` versus the sidecar manifest." The operator is referred to `/hooks`
   for the merged, multi-source truth. This directly honors the shipped `/curator` decision.
6. **Every managed hook is independently removable.** Removing one entry degrades one
   capability and breaks nothing else.
7. **Dry-run by default.** Mutation requires explicit `--apply`.
8. **No new public workflow command, no daemon, no port, no network listener.**

### Explicit non-goals

- No management of project `.claude/settings.json`, `settings.local.json`, managed policy,
  plugin/skill/agent frontmatter hooks, or Codex hooks.
- No assertion that a hook is absent from the running merged configuration.
- No blocking hook, no forced behavior, no model call inside any hook.
- No automatic reaping of hook scripts, state files, or backups beyond the installer's own
  bounded backup rotation.
- No new scheduled task; the detector reuses the existing janitor task.
- No copying of Tier-B dependency closures into `~/.claude/scripts`.

## Domain model

### Canonical hook manifest - `templates/hooks.manifest.json`

Declarative, machine-agnostic. The installer resolves `{checkout_root}` and `{interpreter}`.

```json
{
  "schema_version": "dceco.hooks.manifest.v1",
  "entries": [
    {
      "event": "SessionStart",
      "matcher": "startup|resume|clear|compact",
      "script": "session_router.py",
      "interpreter": "python"
    },
    {
      "event": "PostToolUse",
      "matcher": "Write|Edit",
      "script": "autocommit_design_docs.py",
      "interpreter": "python"
    }
  ]
}
```

- `event` must be one of Claude Code's known hook events (validated against a code-owned
  allowlist).
- `script` is a basename resolved under `{checkout_root}/scripts/`; the installer verifies the
  file exists before writing the entry.
- `matcher` is copied verbatim into the rendered `settings.json` entry.
- No absolute path, interpreter path, or environment string lives in the manifest.

### Sidecar install-manifest - `~/.claude/hooks-install-manifest.json`

```json
{
  "schema_version": "dceco.hooks.install.v1",
  "checkout_root": "D:/dotclaude/dotclaude-ecosystem",
  "interpreter": "py",
  "installed_at_utc": "<RFC3339>",
  "manifest_sha256": "<digest of the source hooks.manifest.json>",
  "entries": [
    { "event": "SessionStart", "matcher": "startup|resume|clear|compact",
      "command": "py \"D:/dotclaude/dotclaude-ecosystem/scripts/session_router.py\"" }
  ],
  "settings_backup": "~/.claude/backups/settings.json.<ts>"
}
```

The sidecar records exactly what was written and where, so `doctor` can compare byte-for-byte
without guessing ownership from `settings.json` alone.

### Rendered settings.json entry

Standard Claude Code shape, no extra keys:

```json
{ "matcher": "Write|Edit",
  "hooks": [ { "type": "command", "command": "py \"<checkout>/scripts/autocommit_design_docs.py\"" } ] }
```

## Merge algorithm (replace-to-canonical)

> **Amended by Matrix B1-B5 (fwf Stage 2) - this is the frozen algorithm.** The original draft
> merged at group granularity, which the panel correctly flagged as able to delete a foreign
> handler sharing a matcher group with a managed one. Merge is at **handler** granularity, and all
> validation precedes any disk mutation.

On `install` (dry-run compute; `--apply` also mutates):

1. **Load and validate the manifest.** `schema_version` must equal the code-owned known value or
   fail closed naming the version. Resolve `{checkout_root}` (`--checkout` wins; else walk up from
   `__file__` to a dir containing both `.git` and `templates/hooks.manifest.json`) and
   `{interpreter}`.
2. **Verify every `script`** exists and canonicalizes inside `{checkout_root}/scripts/`; reject a
   `checkout_root` containing quotes/shell metacharacters. Any miss fails closed with **no backup
   and no write**.
3. **Load `settings.json`** (0-byte/whitespace-only -> treat as `{}`; non-empty unparseable ->
   fail closed, no write, report parse error + path).
4. **Compute the merge in memory, at handler granularity:** within each managed `(event, matcher)`
   group, remove only the individual command **handlers** whose resolved script basename **equals**
   (never substring) a managed script for that event and whose path is rooted in an allowlisted
   legacy root (`{checkout_root}/scripts/`, `~/.claude/scripts/`). Preserve foreign sibling
   handlers in place with every field (`timeout`, async options). Delete a matcher group only when
   its `hooks` array becomes empty. Then insert the canonical managed groups. A same-basename
   command outside allowlisted roots is `COLLISION` (no mutation); a command that cannot be
   quote-aware tokenized is `UNCLASSIFIED`, preserved verbatim, surfaced in the diff and `status`.
5. Preserve all non-hook keys and every foreign handler verbatim.
6. **Under `--apply` only:** take the timestamped backup, atomic-write `settings.json`
   (`os.replace` + `fsync` on temp file and dir), then finalize the sidecar. A no-op `--apply`
   writes no backup and no new timestamp.

Two-file crash safety (Matrix B3): write the sidecar first as `state: "pending"` with the backup
path and intended tuples, replace `settings.json`, then finalize the sidecar to `state:
"installed"`. A crash between writes leaves `INCOMPLETE_INSTALL`, which names its backup and alarms.

Comparison semantics (Matrix B5): rendering is deterministic (`Path.as_posix()`, one quoting rule,
round-trip-tested). Detection is structural - compare parsed `matcher`/`command` keyed by
`(event, basename)` as a multiset, ignoring JSON key order, group position, and array order. `OK`
means "command string equals the sidecar's," not "file bytes unchanged."

`install` without `--apply` performs steps 1-5 in memory and prints the `old -> new` per-entry diff
(matcher + interpreter pre-images; discarded hand-tuned matchers labelled, foreign commands
redacted), writing nothing - no backup, no timestamp.

## Doctor / status contract

`hooks_install.py status --json` (and the human render) report per managed entry:

- `OK` - present in `settings.json` and byte-equal to the sidecar entry;
- `MISSING` - recorded in the sidecar (or expected by the manifest on this pinned checkout) but
  absent from `settings.json`;
- `DRIFTED` - present but differing from the sidecar entry (path/interpreter/matcher);
- `UNRESOLVED_PATH` - the target script no longer exists at the pinned checkout path;
- `NEVER_INSTALLED` - no sidecar manifest exists and no managed block is present.

Plus two machine-level checks:

- `janitor_task_present` - the daily janitor scheduled task exists (watcher-of-the-watcher);
- `manifest_drift` - the pinned `manifest_sha256` differs from the current
  `templates/hooks.manifest.json` (re-install needed).

Every negative verdict's rendered text is scoped ("in ~/.claude/settings.json") and appends the
reference: "run `/hooks` for the authoritative merged view across all sources." No verdict claims
a hook is absent from the running configuration.

## Janitor integration (passive death-detector)

`git_hygiene.py` gains one bounded, read-only check per run: invoke the hooks `status` logic and,
when the verdict is `NEVER_INSTALLED`, `MISSING`, or `DRIFTED` for the managed block, append a
scoped alarm to the existing alarm list (`~/.claude/state/git_hygiene/`). The janitor reaps
nothing here and asserts nothing about the merged runtime; it surfaces "the ecosystem managed
hook block is not wired/observed in ~/.claude/settings.json on this machine - run /hooks to
confirm." Because the janitor is a scheduled task independent of Claude hooks, it catches the
exact "modules present, hooks absent" death a SessionStart self-check structurally cannot.

## CLI contract

```text
hooks_install.py install [--apply] [--home <path>] [--checkout <path>]
hooks_install.py status  [--json] [--home <path>]
hooks_install.py doctor  [--json] [--home <path>]
hooks_install.py uninstall [--apply] [--home <path>]
hooks_install.py version
```

`install`/`uninstall` default to dry-run; `--apply` mutates. `uninstall --apply` surgically
removes only sidecar-recorded entries, restores nothing else, and leaves foreign entries and all
non-hook keys intact.

## Adoption of Tier-C scripts

`repo_hygiene_nudge.py` and `memory_size_guard.py` are copied from `~/.claude/scripts/` into
`scripts/` under version control (pure-stdlib, standalone - verified). Their manifest entries then
point at the checkout like every other managed hook. This is a prerequisite slice; without it the
managed block cannot be complete.

## Failure modes and recovery

| Failure | Behavior | Evidence |
|---|---|---|
| `settings.json` missing | create `{}` skeleton, then install | backup of the empty/created state |
| `settings.json` malformed JSON | fail closed, no write | parse error + path |
| a managed `script` absent at checkout | `UNRESOLVED_PATH`, entry not written | resolved path |
| foreign hook shares an event group | preserved verbatim | basename non-match |
| existing hand-wired managed entry | replaced to canonical, recorded | pre-image in backup |
| sidecar manifest missing but block present | `doctor` reports unverified/`DRIFTED`, never silent trust | settings vs manifest diff |
| manifest changed since install | `manifest_drift`, prompt re-install | sha mismatch |
| janitor task absent | `doctor` `janitor_task_present=false` alarm | schtasks query |
| disk-full / failed atomic replace | fail closed, original intact | backup path |

No recovery path deletes a script, a state file, or a user hook. Backups rotate with a bounded
count.

## Security

- `settings.json` is operator-owned local config; the manifest is repo-owned and trusted, but
  the installer still validates every `event` against the code-owned allowlist and refuses any
  `script` that escapes `{checkout_root}/scripts/` after path canonicalization.
- Atomic writes and pre-mutation backups prevent partial-write corruption.
- No secret, token, or environment string is written into `settings.json` or the sidecar.
- The installer never executes a hook script; it only writes the command string.

## Implementation slices

### S0 - manifest schema, allowlist, fixtures
**Files:** `templates/hooks.manifest.json`, schema/allowlist fixtures, hostile settings.json
fixtures (foreign hooks, malformed JSON, drifted entries, empty file).
**Gate:** schema + event-allowlist validation and fixtures reviewed before mutation code.

### S1 - adopt Tier-C scripts
**Files:** `scripts/repo_hygiene_nudge.py`, `scripts/memory_size_guard.py` (+ existing tests if
any depend on them).
**Gate:** both run standalone from the checkout path; byte-parity recorded with the home copies.

### S2 - installer core (render + merge + sidecar)
**Files:** `scripts/hooks_install.py`, `scripts/tests/test_hooks_install.py`.
Deterministic render, replace-to-canonical merge, backup, atomic write, sidecar manifest,
dry-run vs `--apply`, uninstall.
**Gate:** foreign-hook preservation, double-fire prevention, dry-run purity, idempotent reinstall,
malformed-input fail-closed, uninstall surgical-removal tests pass in a fake home.

### S3 - doctor/status + janitor alarm
**Files:** `scripts/hooks_install.py` (status/doctor), `scripts/git_hygiene.py` (one alarm hook),
tests.
**Gate:** every verdict (`OK`/`MISSING`/`DRIFTED`/`UNRESOLVED_PATH`/`NEVER_INSTALLED`/
`manifest_drift`/`janitor_task_present`) has a fixture; alarm wording is scoped and references
`/hooks`; janitor check is read-only (before/after git status identical).

### S4 - retire orphaned template + docs
**Files:** delete `templates/settings.json.template`, update `README.md` pointer,
`skills`/runbook note on `hooks_install.py`.
**Gate:** no dangling reference to the retired template; README points at the manifest.

### S5 - exact-head review, landing, bounded live acceptance
- run focused + full `scripts/tests`, scoped `ruff`, `compileall`, `git diff --check`;
- `hooks_install.py install` (dry-run) against the **real** active home shows the correct
  migration diff for the 8 live entries;
- `--apply` on the operator's machine migrates the hand-wired block, `status` reports all `OK`,
  a deliberately deleted entry is caught as `MISSING` by `doctor` and the janitor, and `uninstall`
  restores cleanly;
- land through draft PR, one ready transition, CI, merge, and operator-checkout sync.
**Gate:** post-install `status` proves managed-block parity; janitor alarm fires on a simulated
absent block and clears on reinstall.

## Test plan

- **Merge:** foreign preservation; `(event, basename)` replace; double-fire prevention; empty and
  malformed `settings.json`; non-hook key preservation; idempotent reinstall byte-stability.
- **Ownership:** sidecar records exact tuples; uninstall removes only recorded entries; foreign
  entries survive uninstall.
- **Doctor:** each verdict fixture; scoped wording asserts no absolute-absence claim and includes
  the `/hooks` reference; `manifest_drift` on sha mismatch; `janitor_task_present` both ways.
- **Path/interpreter:** Windows `py` and POSIX `python3` resolution; `UNRESOLVED_PATH` on a moved
  checkout; script-escape rejection after canonicalization.
- **Janitor:** read-only (before/after git status identical); alarm text scoped; no reaping.
- **Dry-run:** `install` without `--apply` writes nothing; diff matches the applied result.
- **Adoption:** Tier-C scripts run from the checkout; parity with home copies.

### Proposed validation commands

```powershell
python -m pytest -q scripts/tests/test_hooks_install.py
python -m pytest -q scripts/tests/
python -m ruff check scripts/hooks_install.py scripts/tests/test_hooks_install.py scripts/git_hygiene.py
python scripts/hooks_install.py status --json
python scripts/hooks_install.py install            # dry-run diff, no write
git diff --check
```

A test is reported passed only when exit code is zero and the intended target actually ran.

## Definition of Done

- [ ] `templates/hooks.manifest.json` is the single source of truth; `settings.json.template`
      retired and README updated.
- [ ] The managed block covers all three tiers; Tier-C scripts are under version control.
- [ ] Install renders the manifest into `~/.claude/settings.json` idempotently, points hooks at
      the pinned checkout, and records a sidecar manifest.
- [ ] First install migrates the hand-wired machine with no double-firing and a restorable backup.
- [ ] Dry-run is the default; mutation requires `--apply`.
- [ ] Foreign hooks and non-hook keys are never modified or removed.
- [ ] `doctor`/`status` report managed-block state scoped to `settings.json`, never assert
      absolute hook absence, and reference `/hooks`.
- [ ] The daily janitor raises a scoped alarm when the managed block is absent/drifted, reaping
      nothing.
- [ ] `doctor` verifies the janitor task itself exists (watcher-of-the-watcher).
- [ ] Uninstall surgically removes only recorded entries and restores cleanly.
- [ ] Exact-head review, CI, merge, main sync, and a bounded active-home acceptance are proven.

## Rollback and emergency off

1. `hooks_install.py uninstall --apply` removes only the managed block.
2. Restore the timestamped `settings.json` backup if any customization was lost.
3. Revert the janitor edit and the merged commit.
4. Preserve backups and the sidecar manifest for diagnosis.

Rollback deletes no hook script, state file, or user hook. Destructive cleanup requires a separate
explicit operator action.

## Open risks for review

1. **Seven-source false absence (primary).** The detector must never claim a hook is absent from
   the merged runtime. Invariant 5 scopes every claim to `settings.json` and defers to `/hooks`;
   the tests assert the wording. This is the load-bearing reconciliation with the shipped
   `/curator` decision.
2. **Checkout-path pinning.** Pointing at the checkout is fragile if the operator moves the repo.
   `UNRESOLVED_PATH` makes a move discoverable; re-install re-pins. Copy-to-home was rejected in
   the grill to avoid a dependency-closure and repo/home drift.
3. **Matcher canonicalization.** Replace-to-canonical discards hand-customized matchers on managed
   hooks. Backups are the escape hatch; the manifest is the supported customization point.
4. **Janitor as root of trust.** If the janitor task itself is absent, only a manual `doctor` (or
   any installer run) catches it. Accepted; the two watchdogs cross-check.

## CEO review (fwf Stage 1, 2026-08-04, agent-resolved R2)

**Mode: HOLD SCOPE.** The scope was already pinned tight by the 2026-08-04 grill (global
`settings.json` only, eight named hooks, no Codex/project surfaces). The complexity smell (a new
installer) is answered by the alternatives below and by heavy reuse of shipped patterns, not by
expansion. Reviewer: Claude, agent-resolved per the R2 `/fwf` contract.

### Premise verdict

Real problem, not proxy. Evidence: (a) the idea-box entry names the exact structural blind spot;
(b) this very session demonstrated it - the PostToolUse auto-backup hook fired repeatedly, yet no
installer wires it; (c) the shipped `2026-07-25` plan already recorded the hard evidence - "12 of
36 scripts in `~/.claude/scripts` were absent from the repo ... fixes exist on one machine only and
do not survive a reinstall." Doing nothing keeps a machine able to run with modules present and
hooks absent while the operator believes it is live. This is the one failure the system cannot
self-report. Confirmed real.

### Alternatives considered (0C-bis)

- **A - dedicated installer + declarative manifest + sidecar + janitor alarm (selected):** the
  ideal-architecture path. Only variant that both *wires* the block and *detects* its absence, with
  a single source of truth and reuse of the truthdeck-install / codex-lifecycle-merge / git-hygiene
  patterns. Blast radius ~8 files, bounded.
- **B - fold hook-wiring into `truthdeck_install.py`, no separate manifest:** smaller diff, but
  couples an unrelated installer to the whole ecosystem hook set, has no single source of truth, and
  makes the detector a side effect of running the TruthDeck installer. Rejected - wrong ownership.
- **C - detector only, no wiring:** smallest; a janitor alarm points at `/hooks` when scripts are
  present but the block is absent. Rejected - solves only half the idea; the operator still
  hand-wires every machine, which is the root cause.

**Decision: A.** Reuse over invention; wire and detect in one owner.

### Binding decisions

- **C1 (janitor-fragility guard, P1).** Retrospective: the three commits immediately preceding this
  plan are all `git_hygiene.py` silent-death fixes (cp1252 crash, over-broad gate skipping 9 days,
  blind to the session store). A detector added to a recently-silent watchdog can inherit the exact
  silent-death it exists to catch. S3 must (a) wrap the hook-status check in its own try/except so a
  check error becomes a visible alarm, never an unhandled crash that kills the janitor run; (b) add a
  test that a raising hook-status check still lets the janitor complete and surfaces the failure; (c)
  encode all alarm text ASCII-safe (the cp1252 lesson).
- **C2 (positive trigger, P1).** `NEVER_INSTALLED` must not false-alarm on a machine that simply
  does not use the ecosystem. The janitor alarm fires only when the ecosystem is demonstrably
  deployed on this host - `git_hygiene.py` is itself the ecosystem's janitor, so its own resolved
  repo root is the positive signal. Absence of the managed block is alarmed only relative to "this
  host runs the ecosystem," never as a global claim.
- **C3 (two-way door).** Mutating `settings.json` is reversible (backup + surgical uninstall) and
  low-magnitude. Move fast: no staged rollout, no soak. Ship enabled after tests per ecosystem
  default; `--apply` remains an explicit operator step because it edits live config.
- **C4 (Invariant 5 is load-bearing).** The seven-source false-absence reconciliation with the
  shipped `/curator` decision is the one place this plan could regress a reviewed choice. It is an
  invariant, not prose: S3 tests assert every negative verdict is worded scoped-to-`settings.json`
  and carries the `/hooks` reference, and that no code path emits an absolute "hook absent" claim.

### Expansion opportunities (recorded, NOT in scope - operator may cherry-pick at GO)

1. Codex hook parity: a second manifest consumed by `install_codex_session_lifecycle.py` reusing
   the same `hooks.manifest.json` shape (deferred by D8; keep deferred).
2. `settings.json` hook de-duplication: the live config has two duplicate `Write`+`Edit` matcher
   pairs that could each be one `Write|Edit` matcher (noted in the 2026-07-25 plan). The manifest
   already expresses the collapsed form; adopting it cleans the live file as a side effect. Small,
   low-risk, but out of this plan's stated scope - record only.
3. POSIX activation path: the janitor is a Windows scheduled task; a POSIX cron/systemd equivalent
   for the detector is a separate installer path (deferred).

## Matrix review record (fwf Stage 2, free basket, 2026-08-04, judge: Claude)

**Panel honesty:** 12 lanes launched; **11 OK, 1 degenerate** (Ling 3.0 Flash, truncated). The
frontier cross-check that prevents self-grading **ran**: GPT frontier via `codex exec` (194s) and
Kimi K3 CLI (136s) both returned substantive positions; Gemini CDP returned. Only the Perplexity Pro
CDP roster failed (900s per-provider timeout, 1322s total). Cross-check tournament completed (L2 x4
batches -> L3 merge). Confidence: **MEDIUM-HIGH** - real frontier coverage, one CDP lane down. Run:
`C:\Users\dszub\.claude\fusion_runs\2026-08-04_233807_title-installer-managed-settings-json-ho`.

**Consensus verdict:** architecture approved; premise real; alternative A is the right owner; scope,
D1-D8, sidecar ownership, dry-run default, surgical uninstall, and the R2 grade all stand; **no
boundary violation** (no broker/order/generic-shell reach). Invariant 5 / C1 / C2 confirmed correctly
reconciled and binding. One load-bearing defect blocked coding and is now fixed in the merge section.

**Blocking freezes B1-B8 (folded; B1-B5 rewrote the merge algorithm above):**

- **B1 - handler-granular merge (load-bearing).** A `{matcher, hooks:[...]}` group can mix a managed
  and a foreign handler; group-level removal would delete the foreign sibling, violating Invariant 2.
  Fixed above: remove only matching handlers, preserve foreign siblings in place, delete a group only
  when empty. Fixture: `{matcher:"Write|Edit", hooks:[managed, foreign]}` -> foreign survives.
- **B2 - narrow ownership predicate, fail closed.** basename-equals not substring; command path must
  root in an allowlisted legacy root; else `COLLISION`/`UNCLASSIFIED`, no silent mutation. Folded above.
- **B3 - crash-recoverable pair.** sidecar `pending` -> settings -> sidecar `installed`;
  `INCOMPLETE_INSTALL` on a crash between writes. Folded above and into the state machine.
- **B4 - validate before mutate.** No backup/write until manifest, checkout, and every script path
  validate; no-op `--apply` writes nothing. Folded above.
- **B5 - comparison semantics.** deterministic render vs structural detect; `OK` = command-string
  equal; multiset compare so a duplicated managed handler is `DRIFTED`. Folded above.
- **B6 - complete the state machine + widen the janitor trigger.** Verdicts are now: `OK`, `MISSING`,
  `DRIFTED`, `UNRESOLVED_PATH`, `NEVER_INSTALLED`, `UNVERIFIED_PRESENT` (block present, no sidecar -
  split out of `DRIFTED`), `INCOMPLETE_INSTALL`, `COLLISION`, `SOURCE_MANIFEST_UNREADABLE`. The
  janitor alarms on **every block-invalidating state**, explicitly including `UNRESOLVED_PATH` and
  `INCOMPLETE_INSTALL` (a moved checkout is exactly the silent death this plan exists to catch).
  Stable JSON field names and exit codes are specified; on POSIX `janitor_task_present` is
  `NOT_APPLICABLE`, not `false`. **This supersedes the five-verdict list in the Doctor section above.**
- **B7 - manifest from evidence, not invention.** All eight entries are transcribed verbatim from the
  live `~/.claude/settings.json` pre-image (recorded in S0 with every matcher and handler option).
  Each `event` validates against a code-owned constant (`SessionStart, SessionEnd, PreToolUse,
  PostToolUse, UserPromptSubmit, Notification, Stop, SubagentStop, PreCompact`) checked against the
  installed Claude Code version at S0; `PreToolUse`/`PostToolUse` matchers validate against real tool
  names. A hook wired to a non-existent event that still reports `OK` is the worst possible
  regression; S0's gate rejects it.
- **B8 - resolve the `Write|Edit` contradiction. DECISION: reproduce current live behavior.** The
  manifest mirrors the live pre-image exactly (including the two duplicate `Write`+`Edit` matcher
  pairs), so v1 is a pure zero-behavior-change migration. Hook de-duplication stays the deferred
  expansion item; the manifest is not collapsed. This keeps B7 (evidence-derived) and B8 consistent.

**Required conditions (non-blocking; bound to slices):**

- S2/S3: janitor invocation is path-pinned (`{interpreter} "{checkout}/scripts/hooks_install.py"
  status --json`, checkout read from the sidecar); runs only when `git_hygiene.py` resolves its own
  ecosystem repo root, else skips silently (C2); `janitor_task_present` checks **liveness**
  (`LastRunTime`/`LastTaskResult`), alarming on stale-or-failing, not merely absent (strengthens Open
  Risk 4); alarm keyed to one stable id - re-fire updates, a clean run clears it.
- S2: dry-run prints `old -> new` pre-images with foreign commands redacted; `uninstall --apply`
  removes only exact recorded occurrences, returns `PARTIAL_UNINSTALL` on drift, restores nothing
  (points at the backup); empty-vs-malformed split as above; missing/empty `matcher` is first-class.
- Security: backups go to `~/.claude/backups/` owner-only, retention last 10 (backups copy whatever
  `settings.json` holds, incl. `env`/`apiKeyHelper` - so permissions matter); corrected from the
  original "no secret written" claim, which was true only of what the installer authors.
- Code-level: `datetime.now(timezone.utc)`; `os.replace` + `fsync` on temp file and its dir; `status`
  *reports* `UNRESOLVED_PATH` rather than raising (raising is for `install` only); `doctor` verifies
  the interpreter via `shutil.which`; human render carries the "takes effect in new sessions" caveat.
- S2 test: one cwd-independence test invoking `session_router.py` by absolute path from an unrelated
  cwd asserting exit 0 (its sibling imports rely on CPython `sys.path[0]`; `-P`/`PYTHONSAFEPATH` would
  disable it - keep as a regression guard, not a correctness claim).

**Rejected (judge-discarded, correctly):** interpreter/PATH false-`DRIFTED` (comparison is of the
command string); matcher canonicalization as a defect (recorded D4/Open Risk 3, only visibility was
missing - added); checkout fragility as new (already Open Risk 2 with `UNRESOLVED_PATH`); Tier-B
`sys.path` as a bug (it is not - keep only the regression test); any manifest entry not traceable to
the live pre-image; two-clones-on-one-machine (equivalent to accepted-risk 2, no v1 machinery).

**DoD additions:** handler-granular foreign survival across install/reinstall/uninstall;
crash-recoverable pair with `INCOMPLETE_INSTALL` naming its backup; janitor alarms on every
block-invalidating state, deduplicated, clears on healthy run; every manifest entry traceable to the
recorded pre-image and validated against the event allowlist + real tool names; dry-run shows
matcher/interpreter pre-images and writes nothing including no backup.

**Verdict: MATRIX_CLEAR_CONDITIONAL_B1-B8.** All eight freezes are now in plan text; architecture and
scope unchanged.

## Engineering review (fwf Stage 3, 2026-08-04, agent-resolved R2)

Reviewer: Claude. Scope settled in Stage 1 (HOLD SCOPE), correctness settled in Stage 2; this pass
owns ownership, dependency order, reuse, and worktree lanes. Findings fold into the slices.

### Architecture

- **E1 [reuse, confidence 9/10] The handler-granular merge already exists and is tested.**
  `install_codex_session_lifecycle.py` ships `_without_owned_handlers` and `_merge_hooks` operating
  at exactly the handler granularity Matrix B1 requires, plus `_handler_is_owned`, backup/restore,
  and `_validate_registry` - covered by `test_install_codex_session_lifecycle.py`. `hooks_install.py`
  **reuses the shared low-level utilities** `atomic_write_bytes` and `resolve_repository` from
  `session_state.py`, and **models its merge on** the codex functions, but keys ownership off the
  sidecar manifest (D3) rather than the codex in-band `_handler_is_owned` check. **Decision: do not
  refactor the shipped Codex installer to extract a shared module in v1** - that would destabilize
  tested, landed code for a DRY win. The merge logic is duplicated deliberately and bounded;
  "extract a shared `hook_merge.py` consumed by both installers" is a recorded follow-up, not v1
  scope. This is the same "don't invent a second idiom, but don't destabilize a shipped one either"
  call the Conductor E1 finding made about installer reuse.
- **E2 [confidence 8/10] The janitor edit is the only shared-file touch; isolate it.** `git_hygiene.py`
  is the one file this plan edits that another system (the scheduled task) executes, and its three
  most recent commits are silent-death fixes (CEO C1). The added check is a single call site guarded
  by its own try/except (C1) that resolves the ecosystem repo root the janitor already computes (C2
  is feasible - `git_hygiene.py` operates on a resolved `repo`). No other janitor logic changes. This
  keeps the blast radius on the fragile file to one guarded, tested call.
- **No further architecture findings.** Layering (manifest -> installer -> sidecar -> doctor ->
  janitor), the merge/state-machine correctness, and the seven-source reconciliation were pressure-
  tested by Stages 1-2; the failure table plus Matrix B6 cover every integration point with a visible
  state and no silent path.

### Ownership and dependency order

| Slice | Depends on | Owns |
|---|---|---|
| S0 manifest/allowlist/fixtures | - | `templates/hooks.manifest.json`, event allowlist constant, fixtures |
| S1 adopt Tier-C | - | `scripts/repo_hygiene_nudge.py`, `scripts/memory_size_guard.py` |
| S2 installer core | S0, S1 | `scripts/hooks_install.py`, `scripts/tests/test_hooks_install.py` |
| S3 doctor/status + janitor | S2 | `hooks_install.py` (status/doctor), `git_hygiene.py` (one guarded call) |
| S4 retire template + docs | S2 | delete `settings.json.template`, `README.md` |
| S5 review + land | S2-S4 | PR/CI/merge/checkout-sync |

S0 and S1 are independent and may run in parallel worktrees (disjoint files: `templates/` + fixtures
vs two `scripts/*.py`). S2 is the join; S3/S4 are a short sequential tail on S2. The spine is small
enough that single-lane execution is fine; parallelizing S0/S1 saves little.

### Tests, failure modes, rollback

Matrix B1-B8 and the required conditions already enumerate the fixtures (handler preservation,
crash-between-writes -> `INCOMPLETE_INSTALL`, formatter round-trip -> `OK`, coincidental-basename
`COLLISION`, cwd-independence regression, per-state doctor fixtures, C1 raising-check, C4 wording).
Failure table plus Matrix B6 state machine are complete; rollback is surgical uninstall + backup with
no deletion. No eng-level gaps remain.

### Outside voice

Owned by the `/fwf` workflow itself: Stage 2 matrix was the cross-model pass (11/12 lanes, frontier
GPT+Kimi returned, recorded honestly above). No separate subagent pass run.

**Eng verdict: CLEAR.** Implementation-ready for the R2 standing gate. Dependency order and ownership
are fixed; E1/E2 are folded above; no blocking finding remains.
