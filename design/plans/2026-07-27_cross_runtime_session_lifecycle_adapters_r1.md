---
title: Cross-Runtime Session Lifecycle Adapters - Codex Shipped, Cursor Discovery
date: 2026-07-27
status: active
status_detail: cursor-cu3-installer-shipped-pr72-cu4-activation-awaiting-operator-go
risk: R1
phase: landing
repos: [dotclaude-ecosystem]
tags: [agent-tooling, hooks, session-lifecycle, cursor, codex]
related:
  - design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md
  - design/plans/2026-06-27_global_agent_workflow_os.md
  - design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md
---

# Cross-Runtime Session Lifecycle Adapters — Codex Shipped, Cursor Discovery

**Date:** 2026-07-27; amended 2026-07-28
**Status:** ACTIVE — Codex shipped and live; Cursor CLI CU1 implementation complete, landing gated by exact-head review; IDE degraded
**Risk:** R1 (advisory local tooling; no broker, order-path, or live-state writes)
**Workflow:** `/fwp`
**Owner:** `dotclaude-ecosystem`

## Decision and collision verdict

**CREATE NEW LINKED PLAN.** Do not reopen the shipped
`2026-07-25_session_lifecycle_and_hook_hardening_r1.md`: that plan implemented
Claude Code's native hook contract and remains the lifecycle engine source of truth.
Do not add runtime dispatch to the R2 Conductor work-queue plan: this adapter only
normalizes host lifecycle events into the existing advisory engine.

Linked predecessors:

- `design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md`
- `design/plans/2026-06-27_global_agent_workflow_os.md`
- `design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md`

Runtime rollout order is frozen:

1. Claude Code — shipped and active.
2. Codex — shipped and active.
3. Cursor — discovery complete; bounded adapter slice is next.
4. Antigravity — discovery and adapter slice after Cursor acceptance.
5. Kimi — discovery and adapter slice after Antigravity acceptance.

## Why

The lifecycle engine currently starts only when Claude Code emits
`SessionStart`/`SessionEnd`. The operator expects the same advisory continuity in
every new session, independent of host. Duplicating lifecycle policy inside each
host would create divergent verdicts and maintenance. Each host therefore gets the
smallest native adapter necessary to feed the existing engine.

## Definition of done — Codex slice

- A user-level Codex hook is active for every new Codex session.
- A persisted Codex session in a registered repository creates the same
  `session.plan.v1` and `session.binding.v1` state as Claude Code.
- Codex `SessionEnd` persists one of the existing coarse lifecycle verdicts.
- Codex transcript records are understood by the optional Curator path without
  weakening fail-closed claim verification.
- Ephemeral Codex sessions with `transcript_path: null` are deliberate no-ops:
  no fabricated binding and no error-log flood.
- Unregistered repositories receive a short advisory/minimal context and never
  cause a blocking hook failure.
- Existing Claude Code behavior and schemas remain backward compatible.
- Installation is idempotent, validates the generated hook configuration, keeps
  a restorable backup, and has a documented emergency-off path.
- A brand-new persisted Codex session proves the live user-level hook, state
  creation, injected context, and close verdict.

The Codex slice met this definition on 2026-07-27 through PRs #55-#57. The
machine-local hook and registry remain active at the exact hashes recorded below.

## Definition of done — Cursor slice

- Cursor IDE and Cursor Agent CLI are treated as separate host surfaces. Each
  surface is claimed only after its own native live acceptance; success on one
  does not imply success on the other.
- A native `sessionStart` event supplies a `conversation_id`, explicit
  workspace roots, and an explicit `transcript_path` or `null`. Identity
  stability is proven only within one host surface and one conversation across
  start/resume/preCompact/end; IDE and CLI identities are never compared or
  assumed globally collision-free.
- Full lifecycle state is allowed only for exactly one canonical, registered Git
  root. Zero, multiple, non-Git, invalid, or unregistered roots remain a bounded
  no-state/degraded path; the adapter never guesses among roots.
- The adapter maps only the proven host identity into the existing write-once
  lifecycle binding. A later event with a different transcript path fails closed
  and cannot replace the start-time binding.
- A native `sessionEnd` event for the same conversation delegates to the
  existing coarse close evaluator. Missing end on crash remains reaper-owned;
  no synthetic close event is fabricated.
- Resume preserves the existing conversation identity and does not create a
  second binding. New chat creates a new identity. `preCompact` records a
  checkpoint against the same identity and never creates a new session; a
  `preCompact` without a valid existing binding is a bounded no-op.
- `transcript_path: null` is a deliberate lower-fidelity/no-op path. A non-null
  path is parsed only after its real format and stability are captured in a
  sanitized fixture; there is no SQLite scraping, chat-directory scanning, or
  recency lookup.
- Cursor `sessionStart` context injection is accepted only when a live probe
  proves the model received the exact nonce. Hook execution without delivered
  context is recorded as event-only evidence and context parity fails. The
  probe nonce is random, stored only in its Temp manifest, returned through the
  probe-owned `additional_context`, and exact-matched against the model response;
  it never enters lifecycle persistence. The probe and adapter never emit
  Cursor's `env` output field.
- User-level installation preserves unknown hooks, validates the merged config,
  keeps exact pre-activation bytes and SHA-256, supports emergency-off, and is a
  semantic no-op when repeated.
- Claude Code and Codex schemas, adapters, activation, and regression tests
  remain unchanged.
- Normal IDE start/end, normal CLI start/end, resume, new chat, compaction,
  abrupt CLI termination, null transcript, and unregistered workspace each have
  explicit evidence or an honest unsupported verdict.

## Verified current state

- Repository head at planning start:
  `e2397edce91221e0df0987eaecd381183192dd8c`.
- `codex-cli 0.145.0` reports stable `hooks`.
- Codex documents user hooks at `~/.codex/hooks.json`, with
  `SessionStart` matchers `startup|resume|clear|compact` and a `SessionEnd` event.
- A trusted disposable prototype proved that Codex injects the existing Claude
  `hookSpecificOutput.additionalContext` shape into model context.
- A persisted prototype supplied `session_id`, absolute `transcript_path`, `cwd`,
  and `source`/`reason`; an ephemeral prototype supplied `transcript_path: null`.
- Existing `session_router.py` and `session_lifecycle.py` accept the persisted
  Codex payload shape directly.
- Existing transcript readers only recognize Claude records (`type=assistant`,
  `message.content[].type=tool_use`). Codex stores
  `type=response_item` with payload types `message`, `function_call`, and
  `function_call_output`; this is the only proven parser gap.
- The active registry template currently covers only `dotclaude-ecosystem`, so
  global hook activation alone would not provide full ecosystem context.

### Codex closeout evidence — 2026-07-27

- `main == origin/main == 8fc7ac547221bb48d57e2d7a43fb7b3550dab6bd`.
- PR #55 added the adapter, PR #56 repaired Windows PowerShell invocation, and
  PR #57 repaired strict `SessionStart` output.
- `C:/Users/dszub/.codex/hooks.json` is active with SHA-256
  `AD03F5F7F854628BAD1A71F818452F25381D7C52E048F91D011D46AFFDB5B59A`.
- `C:/Users/dszub/.claude/session_registry.json` is active with SHA-256
  `B6712F9EFDBE26F81DBA0D8C8D4DB616FA57305036D502CBFC7A8459D3F2FD35`
  and ten verified ecosystem roots.
- Native persisted and ephemeral smokes passed; the final validation record is
  354 tests plus 9 subtests. Measured p95 was 565 ms for start and 777 ms for
  end, below the hard 2 s/3 s timeouts but slightly above the aspirational
  500 ms/750 ms targets.

### Cursor discovery evidence — 2026-07-28

- Installed Cursor IDE: `3.13.21`, commit
  `55434bd8062ece6fee083b82beed2aee42d253f0`, built
  `2026-07-27T03:26:14.573Z`.
- Installed Cursor Agent CLI: `2026.07.23-e383d2b` on Windows x64.
- No user-level Cursor hook config exists at `~/.cursor/hooks.json`,
  `~/.cursor/hook.json`, or `%APPDATA%/Cursor/User/hooks.json`. No activation
  occurred during discovery.
- Current primary Cursor hook documentation defines `sessionStart`,
  `sessionEnd`, and `preCompact`. Common input includes `conversation_id`,
  `generation_id`, model fields, `hook_event_name`, `cursor_version`,
  `workspace_roots`, `user_email`, and nullable `transcript_path`.
- The documentation calls `conversation_id` stable. `sessionStart` fires when a
  new composer conversation is created and is fail-open/fire-and-forget for
  blocking behavior while allowing `env` and `additional_context` output.
  `sessionEnd` fires when a composer conversation ends; its response is logged
  but not used.
- Cloud agents do not expose the same lifecycle: `sessionEnd` is tied to the IDE
  session rather than a cloud chat, and cloud `sessionStart` is not a truthful
  pre-write boundary. Cloud agents are therefore outside this Cursor slice.
- Local chats are stored under
  `~/.cursor/chats/<workspace-hash>/<conversation-uuid>/store.db` with
  `meta.json` containing `schemaVersion`, timestamps, `hasConversation`, and
  `cwd`. This is not a stable JSONL contract and must not be reverse-engineered
  as a transcript fallback.
- A disposable trusted CLI Ask-mode probe used a project-level
  `.cursor/hooks.json` with `sessionStart`, `sessionEnd`, and `preCompact`.
  Two successful conversations persisted stable UUID chat directories, but zero
  hook events were observed. The first model answer (`CONTEXT_SEEN`) was rejected
  as a false positive because no physical hook event existed; the second
  returned `UNKNOWN`.
- The installed CLI bundle contains validators and merge logic for
  `sessionStart`, `sessionEnd`, `preCompact`, `additional_context`, Claude hook
  name mapping, and exact call/result identity. This proves schema presence, not
  project-hook activation.
- **Discovery verdict:** native Cursor lifecycle support exists, but
  project-level CLI hook loading and IDE/CLI context delivery are `UNPROVEN` on
  this machine. User-level activation was deliberately not tested while Cursor
  was running.

Primary sources:

- Cursor Hooks reference: <https://cursor.com/docs/hooks>
- Cursor CLI output/session identity reference:
  <https://docs.cursor.com/en/cli/reference/output-format>
- Cursor 1.7 hooks introduction: <https://cursor.com/changelog/1-7>
- Cursor 2.4 lifecycle-hook expansion:
  <https://cursor.com/changelog/2-4>

## Frozen boundaries

- Advisory/best-effort only, preserving the operator's accepted C11/C14 posture.
- No broker API, order path, execution authority, live decision state, or
  production deployment.
- No new lifecycle policy, verdict vocabulary, persistence schema, or second
  registry owner.
- No transcript globbing or fallback to another session.
- No Cursor chat-database scraping, conversation-directory scanning, synthetic
  identity, or recency inference.
- No assumption that IDE, CLI, cloud agents, or project/user hook scopes behave
  identically.
- No user-level Cursor activation before reviewed source lands and exact
  pre-activation bytes are captured.
- No assumptions about Antigravity or Kimi hook contracts during the Cursor
  slice.
- No installer rewrite beyond the smallest idempotent activation path required
  for the current host.

## Architecture

```text
~/.codex/hooks.json
        |
        v
codex_session_adapter.py
  | persisted transcript             | transcript_path = null
  v                                  v
session_router.py / session_lifecycle.py     clean no-op
        |
        v
existing ~/.claude/state lifecycle files

Codex rollout JSONL
        |
        v
format-aware projection in existing transcript readers
        |
        v
unchanged fail-closed Curator verification
```

The `.claude/state` name is retained as the existing cross-host lifecycle store.
Renaming or migrating it would add no user value to this slice and would turn an
R1 adapter into a persistence migration.

## Implementation slices

### C0 — Contract fixtures and red tests

Add sanitized Codex `SessionStart`, `SessionEnd`, and rollout JSONL fixtures.
Cover persisted and ephemeral payloads, assistant text, write-tool attribution,
and command-result pairing. Fixture headers pin their observed producer to
`codex-cli 0.145.0`; install preflight requires stable hook support and records
the installed version, but the hot-path hook does not spawn `codex --version`.

The start matrix covers `startup`, `resume`, `clear`, and `compact`, including a
repeated start for one session ID. The close matrix covers a normal end, an
orphan end, and an end whose event transcript is null after a persisted start.
Relative transcript paths are invalid by contract and fail open; they are never
resolved against an attacker-controlled `cwd`.

**Verify:** focused tests fail only on absent Codex compatibility.

### C1 — Thin Codex event adapter

Add `scripts/codex_session_adapter.py`.

- Read one JSON event from stdin.
- Allow only `SessionStart` and `SessionEnd`.
- `handle_event(event, *, registry_path=None, state_dir=None)` is the importable
  test seam; `main()` reads stdin once and prints only the returned start output.
- Delegate a persisted `SessionStart` directly to
  `session_router.handle_event`; `startup|clear` create/refresh state,
  unseen-ID `resume` creates state, existing-ID `resume` reuses it, and
  `compact` reinjects compact context without replacing the write-once binding.
- Treat a null/empty `SessionStart.transcript_path` as an intentional no-op.
- Delegate `SessionEnd` directly to `session_lifecycle.handle_event`. If its
  transcript is null but the exact session has a valid write-once binding, copy
  that binding's transcript path into the delegated event so a degraded close
  can still persist a coarse verdict. Without a valid binding, no-op and log one
  bounded reason.
- Unsupported events are successful no-ops with no lifecycle state write.
- Preserve current stdout semantics: context for start, silence for end.
- The adapter owns only `CODEX_ADAPTER_*` validation/delegation reason codes.
  Router/lifecycle owners retain their existing internal reason codes; the
  adapter does not duplicate them.
- Fail open without transcript contents or credentials in logs.

**Verify:** adapter tests plus all existing lifecycle tests.

### C2 — Dual-format transcript projection

Add one shared, policy-free `scripts/transcript_projection.py` and make both
existing transcript consumers use it:

- Claude format remains unchanged.
- Codex assistant messages map from
  `response_item.payload.type=message`, `role=assistant`,
  `content[].type=output_text`.
- Codex function calls/results pair only by exact `call_id`.
- Write attribution recognizes only the same allowlisted write tools and extracts
  paths from parsed argument objects.
- Duplicate or non-string `call_id` values drop all evidence for that ID.
- Per-record structural detection allows a mixed-format file to project valid
  records from both formats. Mixed format alone is not an error; malformed
  records, unmatched results, oversized sources, and unknown evidence-bearing
  shapes mark coverage incomplete/unverified.
- The existing 4 MiB source/scan bounds remain authoritative. Readers tail or
  reject within those bounds and tolerate a trailing partial JSONL line.

**Verify:** old Claude fixtures remain green; new Codex fixtures prove parity and
fail-closed behavior, including that Codex records cannot create a false verified
claim.

### C3 — Global hook template and activation

Add `templates/codex_hooks.json.template` and
`scripts/install_codex_session_lifecycle.py`. On this Windows-first machine the
installer renders the absolute `sys.executable` and adapter path into
`commandWindows`; cross-OS activation is deferred until a non-Windows operator
requests it.

The owned hook shape is:

```json
{
  "hooks": {
    "SessionStart": [{
      "matcher": "startup|resume|clear|compact",
      "hooks": [{
        "type": "command",
        "commandWindows": "\"<python>\" \"<adapter>\"",
        "timeout": 2
      }]
    }],
    "SessionEnd": [{
      "hooks": [{
        "type": "command",
        "commandWindows": "\"<python>\" \"<adapter>\"",
        "timeout": 3
      }]
    }]
  }
}
```

Codex runs command hooks synchronously as a process per event; async command
hooks are not supported. The installer:

1. validates the template and target JSON;
2. probes installed Codex hook support and records its version;
3. backs up and hashes both the existing user hook file and active shared
   lifecycle registry before changing either;
4. merges only uniquely identifiable owned lifecycle matcher groups and refuses
   ambiguous/unknown ownership collisions;
5. writes temp files, fsyncs, and atomically replaces targets; any partial
   failure restores both pre-activation bytes before returning nonzero;
6. expands the active registry through `session_state.py` validation to the
   verified ecosystem repositories, deduplicated by canonical resolved Git root;
7. records installed hashes, backup paths, and one exact emergency-off command.

The activation tool must never copy secrets, transcripts, or machine credentials
into the repository.

**Verify:** temp-home install, repeat install, conflict refusal, rollback, and
machine-local activation. Tests pass explicit hook/registry/state paths and never
depend on patching `HOME` alone.

### C4 — Exact live acceptance

From a clean registered repository, start a new persisted Codex session after
normal hook trust is established. Prove:

- hook discovery is user-level;
- `SessionStart` injected lifecycle context;
- binding/plan identifiers match the Codex session;
- the recorded transcript path is the same session's path;
- close writes a valid persisted verdict;
- a second ephemeral run leaves no binding and no new hook error.
- `startup -> compact` retains exactly one write-once binding;
- a registered repository whose path contains a space resolves correctly;
- a forced delegate failure leaves Codex usable and writes exactly one bounded
  adapter reason.

Before deleting the explicitly created disposable test session, capture a
redacted acceptance artifact containing hook/registry hashes, session ID,
binding/plan/verdict paths, transcript-path equality, elapsed times, and the
bounded hook-error window. Leave the tested hook and shared registry active.

## Repository registry scope

The Codex slice intentionally expands the shared lifecycle registry used by both
Claude Code and Codex. This is desired global ecosystem behavior, not a
Codex-private setting. It changes Claude sessions in those repositories from the
unregistered minimal branch to full advisory lifecycle context; schemas and
policy remain unchanged.

The installer registers only existing Git roots verified on this machine.
Candidate roots, subject to existence and canonical plan-path checks:

- `D:/dotclaude/dotclaude-ecosystem`
- `D:/APPS/TSU`
- `D:/APPS/Tsignal 5.0`
- `D:/APPS/EcosystemControl`
- `D:/APPS/WatchF`
- `D:/APPS/TsignalLAB`
- `D:/APPS/Obsidian Flow`
- `D:/APPS/Hue Flow`
- `D:/APPS/ViF`
- `D:/APPS/Vavo OS`

Unknown or non-Git directories are not silently added.

Eligibility is deliberately mechanical: the path exists, `git rev-parse
--show-toplevel` resolves to the same canonical root, and every configured
plan/vision/idea path stays below that root. No activity threshold or heuristic
discovery is permitted. Windows matching uses resolved absolute paths,
case-insensitive drive letters, normalized separators, and no prefix-only
comparison.

## Failure map and rollback

| Failure | Safe behavior | Evidence |
|---|---|---|
| Hook is untrusted or trust is revoked mid-session | Codex may skip the event; stale state is owned by the existing reaper; no bypass claimed as activation | live normal-start smoke + documented degraded close |
| `transcript_path` is null | no-op, no binding, exit 0 | ephemeral fixture + live smoke |
| Repo is unregistered | minimal advisory context, no state mutation | adapter test |
| Codex transcript record is malformed | ignored and coverage marked incomplete | parser test |
| Call result has no exact matching call | no command evidence | parser test |
| Existing global hook has unknown owners | activation refuses replacement and preserves bytes | installer test |
| Adapter exceeds timeout or raises | host continues; bounded error code only; start budget 2 s, end budget 3 s | timeout/error test |
| Regression in Claude behavior | block landing | full lifecycle regression suite |

Emergency off:

1. run the install manifest's exact rollback command;
2. atomically restore both pre-activation `~/.codex/hooks.json` and
   `~/.claude/session_registry.json` bytes, or remove only the owned hook groups
   if no prior hook file existed;
3. leave lifecycle state files intact for diagnosis;
4. rerun normal Claude and Codex sessions and verify pre-activation routing;
5. revert the merged source change only if the adapter itself is faulty.

## Validation and landing gate

Focused:

```powershell
python -m pytest -q `
  scripts/tests/test_codex_session_adapter.py `
  scripts/tests/test_session_router.py `
  scripts/tests/test_session_lifecycle.py `
  scripts/tests/test_curator_claims.py
```

Regression:

```powershell
python -m pytest -q scripts/tests
python scripts/sync_agent_rules.py --check
```

Landing follows the R1 lifecycle:

`branch -> local validation -> draft PR -> exact-head review -> ready once -> CI -> squash merge -> fast-forward main checkout`.

## Cursor adapter boundary and delivery slices

```text
Cursor IDE / Cursor Agent CLI
        |
        | native sessionStart | sessionEnd | preCompact
        | explicit conversation_id + workspace_roots + transcript_path?
        v
cursor_session_adapter.py
        |
        | normalized existing router/lifecycle inputs only
        v
session_router.py / session_lifecycle.py / existing reaper
        |
        v
existing session.plan.v1 / session.binding.v1 / verdict state
```

The adapter owns only Cursor payload validation, event-name normalization,
nullable transcript handling, and bounded host diagnostics. It does not decide
intent, verdicts, repository registration, claim truth, or reaper policy.
Transcript support remains behind the existing projection boundary and is added
only if a native non-null fixture proves a stable format.

**PONYTAIL: NOT USED — no concrete simplification candidate.** The proposed
adapter, conditional projection, installer, and live acceptance each own a
different failure boundary; combining them would mix hot-path dispatch,
format policy, machine mutation, and operator evidence.

### CU0 — Native contract fixtures and executable probe

- Capture sanitized IDE and CLI payloads for `sessionStart`, `sessionEnd`, and
  `preCompact`, including null/non-null transcript cases.
- The probe writes only field names, reason classes, non-secret IDs, paths under
  its disposable workspace, and timing. It never records prompt or transcript
  contents.
- Prove project scope and user scope separately. A scope that does not fire is
  an explicit unsupported/degraded result.
- Verify new chat, resume, compaction, normal close, and abrupt termination.

**Gate:** do not write the adapter until at least one local surface provides a
matching start/end pair with stable identity and workspace root.

### CU1 — Thin Cursor adapter

Proposed production file: `scripts/cursor_session_adapter.py`, with focused
fixtures and `scripts/tests/test_cursor_session_adapter.py`.

- `sessionStart`: validate stable identity and registered workspace, then
  delegate to `session_router.handle_event`.
- `sessionEnd`: delegate only when the exact existing binding is valid.
- `preCompact`: delegate to the existing checkpoint/start-context recovery seam
  without changing identity. If no valid binding exists, return the bounded
  degraded no-op without calling the router, because the router persists a
  binding before handling `source=compact`.
- Accept full-state events only when `workspace_roots` resolves to exactly one
  canonical registered Git root. Never choose among multiple roots or compare
  `conversation_id` values across IDE and CLI.
- Emit only `additional_context` when proven and needed; never emit Cursor's
  `env` field.
- Null transcript, malformed input, unsupported event, unregistered workspace,
  transcript-path mismatch, and delegate failure remain bounded fail-open paths.

**Gate:** no new lifecycle policy or persistence schema; Claude and Codex
regressions remain byte/behavior compatible.

### CU2 — Cursor transcript projection, conditional

This slice exists only if CU0 captures a stable, explicit, readable native
`transcript_path`. "Stable" means sanitized evidence from at least two new
conversations plus resume and compaction shows the same path schema, record
semantics, and append behavior; tool calls and results expose exact native IDs.

- Add sanitized records and structural projection without reading `store.db` by
  guessed location.
- Pair tool calls/results only by exact native IDs.
- Preserve existing byte limits, redaction, repository checks, and incomplete
  coverage semantics.
- If Cursor supplies `null`, an opaque database, or an unstable path, defer
  Curator parity and document lower fidelity. Do not invent a parser.
- A start-time path may not yet exist, so CU1 can retain only the write-once
  absolute binding after root validation; CU2 must not parse until the exact
  bound path exists and is readable. End-time path mismatch, replacement, or
  unreadability fails closed rather than switching sources.

### CU3 — Idempotent user-level activation and rollback

Proposed files:

- `scripts/install_cursor_session_lifecycle.py`
- `templates/cursor_hooks.json.template`
- focused installer tests using a temporary home only

The installer must:

1. preflight installed IDE and CLI versions and reject unsupported schema;
2. capture exact target bytes, SHA-256, permissions, and absence state;
3. preserve unknown hook entries and refuse malformed/ambiguous ownership;
4. render absolute Windows-safe commands to the checked-out merged source;
5. validate the merged config before atomic replacement;
6. restore exact bytes on any failure across all owned targets;
7. make repeated installation a semantic no-op;
8. print an emergency-off command that removes only owned entries.

Activation remains a post-merge machine-local step. It must not run while an
unrelated Cursor session could rewrite the same user config.

### CU4 — Exact live acceptance

Run IDE and CLI acceptance separately:

- normal new conversation: one start event, matching conversation/binding ID,
  exact workspace root, transcript classification, and nonce-proven context;
- normal close: one end event and one coarse verdict;
- resume: same identity, no duplicate binding;
- new chat: new identity;
- compaction: same identity and one checkpoint path;
- abrupt CLI termination: no fabricated end; stale state is reaper-owned;
- null/opaque transcript: bounded no-op or explicitly degraded close;
- unregistered workspace: minimal advisory behavior only;
- repeated install: no target-byte or semantic change.

No surface is marked live until evidence is captured from a normal invocation
without trust/config bypass.

## Deferred runtime slices

Cursor CLI CU1 is implemented but not activated; exact-head review and landing
remain pending. Cursor IDE remains degraded and excluded.
Antigravity and Kimi remain `NOT STARTED` and out of scope. Each later slice
begins with native lifecycle-contract discovery and a disposable prototype. A
host without reliable start/end events receives an honest lower-fidelity
adapter; this plan will not claim parity by polling or fabricating identity.

## CEO decisions — Codex slice (historical)

- **Scope mode at the 2026-07-27 review:** HOLD SCOPE. Cross-runtime parity is
  the product, but only the Codex slice was authorized at that point.
- **Product consequence:** activating a faulty user-level hook could affect
  every Codex session; the change is reversible through the owned backup and
  is protected by fail-open/no-op behavior.
- **Completeness choice:** include Curator rollout parsing now. Omitting it would
  make "lifecycle works in Codex" materially false.
- **State choice:** reuse the existing lifecycle store and schemas; do not add a
  cross-host migration.
- **Activation choice:** normal trusted hook behavior is required. A
  one-command trust bypass is smoke evidence only, never proof of global
  activation.
- **Verdict:** CONTINUE.

## CEO review — HOLD SCOPE

### System audit

- Base branch is `main`; GitHub is the hosting platform.
- The feature branch began clean at `e2397ed`; the only branch change at review
  time is this plan.
- One unrelated stash exists (`park generated operator playbook pdf`) and is not
  touched.
- Recent history is concentrated in the predecessor lifecycle plan and its two
  merged implementation/activation PRs. This slice therefore treats backward
  compatibility with those contracts as a ship blocker.
- No UI scope was detected. Section 11 is explicitly skipped.
- The carved skill's referenced `sections/review-sections.md` was not present in
  either installed Codex or Claude skill tree; the complete embedded 11-section
  source in `SKILL.md` was used.

### Premise, outcome, and alternatives

The real outcome is not "run a Python script from Codex." It is continuity that
is host-independent while lifecycle policy has one owner. Doing nothing leaves
every new Codex session outside the shipped continuity contract.

**Approach A — direct hook commands (minimal viable).** Point Codex directly at
the existing router and lifecycle scripts. Effort S, risk medium, completeness
6/10. It reuses nearly everything, but emits noisy failures for ephemeral
sessions and leaves Curator blind to Codex transcripts.

**Approach B — thin host adapter plus dual-format projection (selected).** Add
one event normalizer, keep policy in the current engine, and extend the two
existing transcript projections. Effort M, risk low, completeness 10/10. It
adds the smallest code needed for honest parity and preserves current schemas.

**Approach C — host-neutral lifecycle framework rewrite (idealized but
rejected).** Rename state, add provider classes, and migrate Claude through a
new abstraction. Effort L, risk high, completeness 10/10. It is aesthetically
general but solves no current behavior gap and needlessly endangers the shipped
Claude path.

**Decision:** Approach B. Approach A is not complete enough for the user's stated
global expectation; Approach C violates surgical scope.

### What already exists

| Sub-problem | Existing owner | Reuse decision |
|---|---|---|
| Repository resolution | `scripts/session_state.py` | Reuse unchanged; no second registry parser |
| Start context and state scaffold | `scripts/session_router.py` | Delegate persisted Codex starts |
| Close verdict | `scripts/session_lifecycle.py` | Delegate persisted Codex ends |
| Scratch retention | `scripts/state_reaper.py` | Reuse unchanged |
| Verified close | `scripts/curator_claims.py` | Extend projection, not verification policy |
| User-level hook contract | Codex `~/.codex/hooks.json` | Generate from canonical template |
| Claude activation | shipped predecessor plan | Regression-test; do not rewrite |

### Dream-state delta

```text
CURRENT                         CODEX SLICE                     12-MONTH IDEAL
Claude-only lifecycle    --->  one engine + Codex adapter ---> native adapter per host,
host-specific transcript       dual transcript projection     one advisory policy owner
```

### Architecture and four-path flow

```text
Codex event
  |
  +-- persisted, registered --> adapter --> existing engine --> state/context/verdict
  |
  +-- persisted, unregistered -> adapter --> existing minimal advisory context
  |
  +-- transcript null/empty ---> adapter --> successful no-op
  |
  +-- malformed/error ---------> bounded reason code, exit 0, host continues

Codex rollout
  |
  +-- message/output_text -----> assistant projection
  +-- function_call + exact result call_id -> command evidence
  +-- malformed/unmatched -----> ignored + incomplete coverage
```

There is no new state machine. The adapter is a two-event dispatcher; the
existing lifecycle schemas and verdict state machine remain authoritative.
At 10x/100x session volume the first pressure is local JSONL/state-file I/O,
already bounded by transcript scan limits and the reaper. No network or shared
service is introduced.

### Error and rescue registry

| Method/codepath | Failure | Exception/reason | Rescue | Operator/host sees |
|---|---|---|---|---|
| adapter input | invalid JSON or non-object | `JSONDecodeError` / `CODEX_ADAPTER_INVALID_INPUT` | bounded log, exit 0 | session continues |
| adapter dispatch | unsupported event | `CODEX_ADAPTER_UNSUPPORTED_EVENT` | no-op, exit 0 | nothing |
| adapter dispatch | null/empty transcript | `CODEX_ADAPTER_EPHEMERAL_NOOP` | no state write, exit 0 | nothing |
| router/lifecycle delegate | expected validation failure | `ValueError` reason from existing owner | bounded log, exit 0 | session continues |
| router/lifecycle delegate | unexpected failure | `OSError`/runtime reason class only | bounded log, exit 0 | session continues |
| rollout projection | malformed JSON line | `JSONDecodeError` | skip record, mark incomplete | Curator says unverified/incomplete |
| function arguments | malformed/non-object JSON | projection-invalid | ignore call evidence | no false verification |
| hook activation | invalid target/template JSON | `ValueError` | refuse before replacement | actionable installer error |
| hook activation | unknown existing owner | ownership conflict | preserve bytes, refuse | actionable installer error |
| hook activation | write/replace failure | `OSError` | keep backup, nonzero install | actionable installer error |

Catch-all protection remains only at the host boundary where fail-open behavior
is the contract; logs contain reason classes and session identifiers, never
transcript contents or credentials.

### Security and threat model

| Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Hook arguments execute through a shell | medium | high | fixed absolute command, no payload interpolation |
| Host payload supplies an arbitrary transcript path | low | medium | binding/session/repo cross-checks remain mandatory |
| Malicious function arguments claim a write outside repo | medium | medium | canonical repo-relative path filter |
| Mismatched result is attributed to a command | medium | high | exact unique `call_id` pairing only |
| Installer overwrites unrelated hooks | medium | high | owned-entry merge or conflict refusal plus backup |
| Transcript leaks through logs | low | high | log reason codes/classes only |

No new dependency, credential, endpoint, authorization role, or data class is
introduced.

### Data, quality, and edge cases

- Nil transcript, empty string, whitespace string, relative path, missing file,
  oversized file, malformed JSONL, mixed Claude/Codex records, duplicate
  `call_id`, unmatched result, malformed arguments, non-string output, and
  unregistered worktree all receive explicit fixtures.
- Provider detection is structural per record; no global provider flag or
  persistence schema is added.
- The same redaction and claim-verification stages run after projection.
- Adapter branching is limited to event kind and transcript availability;
  lifecycle policy branches stay in their existing owners.
- No duplicate install or registry owner is allowed.

### Test diagram

```text
UNIT
  adapter: persisted | ephemeral | invalid | unsupported | delegate failure
  projection: Claude unchanged | Codex message | call/result | malformed/mismatch
  installer: fresh | repeat | conflict | rollback
       |
       v
INTEGRATION
  event -> adapter -> real router/lifecycle -> temp state/registry
       |
       v
LIVE ACCEPTANCE
  normal trusted new Codex session -> context + binding -> SessionEnd verdict
  ephemeral Codex run -> no binding and no new error
```

The hostile test supplies an attacker transcript path and mismatched result ID.
The chaos test interrupts installation between backup and replacement and proves
the backup remains restorable. Tests use temporary homes/state and no network.

### Performance, observability, deployment, and future

- Existing transcript byte limits remain the performance boundary; no full
  history glob or repo scan is added to hooks.
- Expected adapter overhead is local process startup plus the already measured
  router/lifecycle work. Live acceptance records elapsed time and enforces the
  configured hook timeout.
- Diagnostics are the existing `hook_errors.log`, install manifest/hashes, and
  persisted session state. No dashboard or alert service is warranted for
  machine-local advisory tooling.
- Deployment is source merge first, machine-local activation second, normal
  trust confirmation third, live smoke fourth. A bypassed-trust smoke cannot
  satisfy activation.
- Reversibility is 5/5: restore the exact pre-activation hook backup. State is
  retained for diagnosis.
- Provider-specific parsing is deliberately isolated at the projection boundary,
  leaving later host adapters free to add their own normalized projections
  without changing lifecycle policy.

### Failure modes registry

| Codepath | Failure mode | Rescued? | Test? | Host/operator sees | Logged? |
|---|---|---:|---:|---|---:|
| SessionStart | ephemeral transcript | yes | yes | clean no-op | optional metric only |
| SessionStart | unregistered repo | yes | yes | minimal context | yes, bounded |
| SessionEnd | missing binding | yes | yes | session closes | yes, bounded |
| Projection | malformed record | yes | yes | incomplete/unverified | no content |
| Projection | false call/result pair | prevented | yes | no false claim | no |
| Activation | unknown hook collision | yes | yes | install refusal | yes |
| Activation | trust not established | yes | live | Codex trust notice | Codex-owned |
| Existing Claude path | regression | no ship | full suite | PR blocked | test output |

There are zero rows with `Rescued=no`, `Test=no`, and silent user impact.

### NOT in scope — Codex review baseline

- Cursor, Antigravity, and Kimi implementation were outside the reviewed Codex
  slice. The 2026-07-28 amendment opens only Cursor discovery and its bounded
  future slice; Antigravity and Kimi remain out of scope.
- State-directory rename or schema/provider migration — no behavior value here.
- Central daemon, polling, or synthetic session IDs — would reduce truthfulness.
- Broker, trading runtime, live deployment, and order-path work — prohibited.
- New UI, dashboard, notifications, or remote telemetry — unnecessary for local
  advisory hooks.

### Stale diagram audit

The existing predecessor lifecycle diagrams remain accurate because the adapter
feeds their documented boundary and does not change their internal state flow.
This plan's diagrams are the only new cross-host diagrams.

## Implementation Tasks

- [x] **T1 (P1, human ~1h / Codex ~10m)** — fixtures/tests — add red contract tests
  - Surfaced by: parser gap and four-path review.
  - Files: `scripts/tests/fixtures/`, `scripts/tests/test_codex_session_adapter.py`,
    existing transcript test modules.
  - Verify: focused tests fail before implementation and pass after it.
- [x] **T2 (P1, human ~1h / Codex ~10m)** — adapter — normalize Codex lifecycle events
  - Surfaced by: ephemeral null and host-boundary error map.
  - Files: `scripts/codex_session_adapter.py`, focused tests.
  - Verify: persisted parity, ephemeral no-op, bounded fail-open.
- [x] **T3 (P1, human ~2h / Codex ~20m)** — transcript projection — support Codex rollout
  - Surfaced by: verified parser incompatibility.
  - Files: `scripts/transcript_projection.py`, `scripts/curator_claims.py`,
    `scripts/session_lifecycle.py`, tests.
  - Verify: dual-format parity and exact-ID negative tests.
- [x] **T4 (P1, human ~2h / Codex ~20m)** — activation — install user hook safely
  - Surfaced by: global scope, ownership conflict, and rollback review.
  - Files: canonical template, activation script, registry template, tests.
  - Verify: fresh/repeat/conflict/rollback in temp home.
- [x] **T5 (P1, human ~1h / Codex ~15m)** — live acceptance — prove a normal new session
  - Surfaced by: trust cannot be inferred from bypassed smoke.
  - Files: machine-local hook/registry/state evidence only.
  - Verify: start context, exact binding, close verdict, ephemeral no-op.
- [x] **CU0-D (P1, discovery)** — inspect installed Cursor contracts and run a
  disposable project-hook probe.
  - Evidence: IDE `3.13.21`, CLI `2026.07.23-e383d2b`, official hook schema,
    local chat storage shape, two zero-event CLI project-hook runs.
  - Verdict: native schema present; project-hook CLI activation and context
    delivery remain `UNPROVEN`.
- [x] **CU0-L (P1, live contract capture)** — capture sanitized native IDE and
  CLI start/end/preCompact payloads without changing shared lifecycle state.
  - Authorization: requires the literal operator token
    `GO CURSOR CU0-L LIVE CONTRACT CAPTURE`; this `/fwp` review does not grant it.
  - Preconditions: all Cursor IDE and Agent CLI processes are closed; the exact
    user hook target bytes, absence state, permissions, and SHA-256 are captured.
    The probe enforces this with a process check, aborts when Cursor is running,
    and re-reads/re-hashes the target immediately before replacement.
  - Method: install only a probe-owned temporary user-level hook block, validate
    the merged JSON, run IDE and CLI as separate experiments, and restore the
    exact pre-probe state after each surface before testing the next.
  - Evidence boundary: record event name, stable non-secret identity, workspace
    root, transcript classification, timing, and nonce result only. Never record
    prompts, transcript contents, `user_email`, credentials, or unrelated hook
    payload fields.
  - Context proof: generate a cryptographically random nonce, keep it only in a
    Temp probe manifest, return it in probe-owned `additional_context`, and
    exact-match the model response to that manifest. A hook event without the
    exact returned nonce is event-only evidence and a context-parity failure;
    no lifecycle schema or state stores the nonce, and the probe emits no `env`.
  - Differential diagnosis: a zero-event run is recorded against config scope
    and precedence, trust/allowlist state, host version, invocation mode, and
    surface. Do not collapse those causes into "hooks unsupported."
  - Verify: exact matching identity/workspace, transcript classification,
    context nonce, normal close, resume/new-chat/compact/crash matrix, bounded
    event counts, single-root and multi-root cases, exact post-restore
    bytes/absence state, and no probe process left running. Record timing and
    overlapping-session behavior so CU1 budgets are derived from evidence; do
    not guess a production timeout from CU0-L alone.
  - Promotion rule: IDE and CLI pass independently. CU1 may target only a
    surface with a proven matching start/end pair; the other remains explicitly
    unsupported/degraded.
  - Result (2026-07-28): CLI passed two independent matching start/end captures,
    resume identity continuity, new-chat identity separation, exact Temp-only
    context nonce delivery, an absolute existing `.jsonl` end transcript, and
    abrupt-termination behavior without a synthetic end. IDE delivered the
    exact context nonce and distinct starts but emitted no matching end on New
    Agent or application close, so it remains degraded. `preCompact` remains
    unproven on both surfaces. Sanitized evidence:
    `design/audits/2026-07-28_cursor_cu0l_live_contract_capture/`.
- [x] **CU1 (P1)** — implement the thin Cursor adapter after CU0-L passes.
  - Authorization boundary: only the CLI surface is eligible. Implementation
    requires `GO CURSOR CU1 CLI ADAPTER IMPLEMENTATION`; CU0-L authorization
    does not grant it. IDE remains excluded until a matching start/end pair is
    proven.
  - Result (2026-07-28): `scripts/cursor_session_adapter.py` maps only the proven
    captured Agent CLI version shape into deterministic runtime-namespaced
    shared session IDs, requires one exact registered root, preserves write-once
    path equality, emits only `additional_context`, and treats native null-start
    transcripts as the documented lower-fidelity no-op. Repeated matching starts
    map to `resume`; mismatches and unbound `preCompact` fail closed without
    changing shared schemas or policy. CU0-L exposed no second surface marker,
    so version-shape drift remains observable through
    `CURSOR_ADAPTER_UNSUPPORTED_SURFACE` rather than being presented as stronger
    IDE/CLI proof.
  - Validation: `16 passed, 2 subtests` focused adapter; `109 passed, 9
    subtests` lifecycle-focused regression; `370 passed, 11 subtests` full
    `scripts/tests`; Ruff, compileall, and `sync_agent_rules.py --check` passed.
    No installer, user hook, machine activation, IDE, Antigravity, or Kimi
    change occurred.
  - Verify: focused contract tests including preCompact-without-binding,
    cross-surface ID isolation, root cardinality, write-once path mismatch, no
    `env`, and full Claude/Codex lifecycle regression.
- [ ] **CU2 (P2, conditional)** — add transcript projection only for a proven
  stable native format.
  - Verify: two-new-chat plus resume/compact append stability, exact-ID pairing,
    malformed/incomplete behavior, bound-path mismatch, and no database scan.
- [x] **CU3 (P1)** — implement and test idempotent user-level install/rollback.
  - Verify: fresh/repeat/conflict/interruption/rollback against temporary homes.
  - Result (2026-08-05): PR #72 (`281ffdf`), 78 focused tests (installer +
    doctor + janitor). Adversarial review found and fixed 3 ship-blockers before
    landing: missing CLI-version preflight (requirement 1), an unanchored
    substring ownership match able to drop a foreign handler and produce a false
    doctor `OK` (requirement 3) — the identical bug was independently present in
    the already-shipped Codex detector and fixed in the same round. All CU3
    verify categories (fresh/repeat/conflict/interruption/rollback) covered
    against temporary homes only; never touched the real `~/.cursor/hooks.json`.
    Full `scripts/tests`: 499 passed, 11 subtests, 0 failures.
- [ ] **CU4 (P1)** — merge first, activate second, then run exact IDE and CLI
  acceptance.
  - Verify: all required live flows or explicit per-surface degraded verdicts.
  - Gate: separate explicit operator authorization (per this plan's own per-slice
    token discipline), matching the --apply pattern already used for Claude/Codex.
    Real `~/.cursor/hooks.json` activation is deliberately NOT part of CU3.

### Implementation review fixes

The pre-landing review found and fixed eleven concrete gaps before commit:
ambiguous Claude multi-result pairing, legacy Claude plain-text projection,
malformed Codex coverage reporting, non-object adapter input, duplicate adapter
groups, mixed-group handler preservation, concurrent target overwrite checks,
interrupt recovery, rollback target/backup confinement, shell-safe Windows
command quoting, and registry duplicate/path/schema validation.

Validation at this point:

- focused lifecycle/Curator tests: 96 passed plus 7 subtests across split runs;
- installer/adapter/projection tests: 31 passed plus 3 subtests;
- Ruff: all changed Python files passed;
- canonical 10-repository temp install: changed on first run, exact semantic no-op
  on the second run;
- the broad test run exposed pre-existing load-sensitive 0.5 s Git subprocess
  timeouts in three lifecycle tests; those are recorded as non-green and are
  not represented as a passing full-suite result.

## Paid audit synthesis

Clean rerun artifacts:
`design/audits/2026-07-27_2026-07-27_cross_runtime_session_lifecycle_adapters_r1/`.
The earlier duplicate-run directory was quarantined outside the repository and
is not evidence.

Panel status:

- OpenRouter paid: 4/4 returned, 35,777 reported tokens.
- Perplexity CDP: 3/3 returned; web UI did not expose token counts.
- Isolated Claude Opus CLI: returned; token count not exposed.
- Gemini CDP: failed after a 180-second response timeout.
- Kimi CDP: failed before model execution because WatchF could not import
  `KIMI_CDP_MODEL_LABEL`; the distinct Kimi-via-Perplexity lane did return.
- Confidence: medium-high on the applied findings; the panel is explicitly
  partial because two configured lanes failed.

Applied findings:

1. **Adapter seam/process model.** C1 now defines the importable signature,
   direct delegates, source semantics, log ownership, process-per-event model,
   and explicit timeouts.
2. **Projection ownership.** C2 now has one policy-free normalization owner,
   exact duplicate-ID behavior, per-record mixed-format semantics, and the
   existing 4 MiB bounds.
3. **Asymmetric/degraded close.** A null transcript at start remains a no-op;
   a null transcript at end reuses only the exact valid write-once binding so a
   coarse close can still persist.
4. **Shared registry blast radius.** Registry expansion is now explicitly an
   intended Claude+Codex behavior change, validated by the single existing
   registry owner, backed up, hashed, rolled back atomically, and live-tested.
5. **Activation atomicity/trust.** C3 now specifies the exact hook shape,
   interpreter rendering, version preflight, atomic dual-target install,
   restore-on-failure, normal trust proof, and no real-home writes in tests.
6. **Acceptance evidence.** C4 now captures redacted evidence before deleting
   the disposable session and adds compact/repeated-start, space-path,
   degraded-delegate, and shared-registry checks.

Discarded or corrected findings:

- Generic state corruption from concurrent sessions: existing state is
  session-ID namespaced, bindings are write-once, writes use fsync plus atomic
  replace/create, and verdicts have per-session locks. Back-to-back and repeated
  event tests are still added, but no new global lock is justified.
- Cross-OS installer requirement: this ecosystem and approved slice are
  Windows-first. Adding untested Linux/macOS commands would expand scope.
- Runtime `codex --version` on every event: installer preflight and pinned
  fixtures catch known contract drift without adding a subprocess to every
  session hot path.
- New `AdapterBase`/provider persistence schema: future host contracts are
  explicitly unknown. Freezing a speculative abstraction contradicts the
  thin-adapter boundary.
- SessionEnd reason-to-verdict mapping: existing verdicts derive from Git,
  binding, transcript, and checkpoint evidence; host end reason is recorded as
  metadata and must not make a verdict more favorable.
- Claims that the persistence model or DoD were absent resulted from compacted
  reviewer transmission; the source plan already names the existing
  `session.plan.v1`, `session.binding.v1`, verdict, and reaper contracts.

## Engineering review

**Mode:** FULL REVIEW, scope accepted as-is. The plan touches more than eight
files and adds three production modules, so the complexity smell gate triggered.
Reduction was rejected automatically under the `/fwp` R1 contract:

- folding installation into the hot-path adapter would mix mutation/rollback
  logic with per-session dispatch;
- duplicating format detection in both consumers would save one file but create
  a new DRY failure for every later host;
- dropping installer tests or live acceptance would make global activation
  unverifiable.

### Architecture review — 3 issues, all folded

1. **P1, confidence 10/10 — registry activation is a shared Claude+Codex behavior
   change.** The plan now names the blast radius, uses the existing schema
   validator, backs up both targets, and rolls both back atomically.
2. **P1, confidence 9/10 — the adapter seam and event asymmetry needed an exact
   contract.** C1 now specifies callable signatures, source semantics, null-start
   versus null-end behavior, log ownership, and timeout budgets.
3. **P2, confidence 9/10 — format normalization needed one owner.** C2 now adds
   a policy-free normalization module; verification policy stays in its existing
   consumers.

Final dependency graph:

```text
transcript_projection.py
      |                 \
      v                  v
curator_claims.py   session_lifecycle.py
                           ^
                           |
session_router.py <- codex_session_adapter.py
                           ^
                           |
        rendered ~/.codex/hooks.json
                           ^
                           |
install_codex_session_lifecycle.py
      |                    |
      v                    v
hooks template      registry template + session_state validation
```

`transcript_projection.py` owns structural conversion only:

```python
def project_record(record: dict[str, object]) -> tuple[ProjectedItem, ...]: ...
```

Normalized item kinds are `assistant_text`, `tool_call`, and `tool_result`.
They retain exact IDs, names, parsed argument objects, exit status, bounded
output, and timestamp. They do not redact, resolve repository paths, decide
verdicts, or verify claims. Each consumer keeps its pre-existing byte-window,
redaction, repository, and policy rules.

### Code quality review — 2 issues, all folded

1. **P2, confidence 9/10 — catch-all logging could duplicate errors.** Adapter
   codes are now limited to adapter validation/delegation boundaries; existing
   router/lifecycle codes remain authoritative for their internals.
2. **P2, confidence 8/10 — owned hook detection was too vague.** The installer
   identifies owned groups by the fully rendered adapter command, preserves all
   unknown groups byte-for-structure, replaces only divergent owned groups, and
   refuses malformed target JSON. An unknown group using the same event/matcher
   is not a collision because Codex intentionally runs all matching groups.

No inline code diagram is warranted for the two-branch adapter or record
projection. The dual-target atomic transaction in the installer receives a
short code comment diagram because its restore ordering is non-obvious.

### Test review — coverage contract

```text
CODE PATHS                                      LIVE OPERATOR FLOWS
[+] adapter                                     [+] New persisted Codex session [integration/live]
  +-- persisted start -> router                   +-- context injected
  +-- startup/resume/clear/compact                +-- exact binding/plan
  +-- null start -> clean no-op                    +-- close verdict
  +-- persisted end -> lifecycle
  +-- null end + valid binding -> lifecycle      [+] Ephemeral Codex run [live]
  +-- null end/no binding -> bounded no-op         +-- no binding
  +-- invalid/unsupported/delegate error           +-- no new error

[+] projection                                  [+] Trust and activation [integration/live]
  +-- Claude assistant/tool/result unchanged      +-- normal trust, no bypass
  +-- Codex output_text/function call/result       +-- repeated install is no-op
  +-- duplicate/non-string/unmatched call ID       +-- rollback restores exact bytes
  +-- malformed/mixed/trailing partial/oversized   +-- path with spaces resolves
  +-- false-positive claim rejection

[+] installer
  +-- new hooks/new registry
  +-- preserve unknown groups
  +-- replace divergent owned group
  +-- malformed target refusal
  +-- duplicate repo canonicalization
  +-- interruption before/during either replace
  +-- automatic dual-target restore
  +-- explicit test paths never operator HOME
```

All diagram branches are required tests. Unit tests cover adapter/projection
branches; integration tests run the real existing handlers and installer
against temp paths; only native hook discovery, trust, and session close require
the live smoke. There is no LLM prompt or eval scope.

Regression requirements:

- every existing Claude lifecycle/Curator test remains unchanged and green;
- a pure Claude transcript projects byte-for-byte-equivalent assistant messages,
  write paths, command evidence, tail timestamp, and completeness;
- existing 4 MiB behavior and write-once binding semantics do not change;
- an expanded active registry is proved in both a Claude-style router event and
  a Codex adapter event.

### Performance review — 2 measured gates

1. Adapter `SessionStart` and `SessionEnd` are synchronous local subprocesses.
   Record cold and warm p50/p95 over at least 20 temp-state invocations. Each
   invocation must remain below its configured 2 s/3 s timeout; the target is
   below 500 ms p95 for start and below 750 ms p95 for end.
2. Projection never reads beyond the existing 4 MiB consumer limit and never
   invokes Git, Codex, network, or recursive filesystem discovery. Installer
   probes may invoke Codex/Git because they are outside the hook hot path.

### Failure ownership and distribution

This is a source-script plus user configuration, not a published package.
Distribution is the repository landing plus the idempotent local installer.
No artifact registry or cross-platform release pipeline is required.

The existing reaper owns missing `SessionEnd` and trust-revocation leftovers.
The adapter owns malformed/null host boundaries. The installer owns hook and
registry transaction recovery. Projection consumers own incomplete evidence.
No failure row remains silent without either a test or a bounded diagnostic.

### Sequential implementation order

The modules share core tests and state contracts, so parallel worktrees would
create more merge/review risk than latency benefit.

| Step | Modules | Depends on |
|---|---|---|
| E1 | fixtures/tests | reviewed plan |
| E2 | transcript projection + consumers | E1 |
| E3 | Codex adapter | E1, existing handlers |
| E4 | installer/templates/registry | E3 |
| E5 | regression + performance | E2-E4 |
| E6 | machine activation + live evidence | E5 and merged/checked-out source |

**Strategy:** sequential implementation, no parallelization opportunity.

### Engineering completion summary

- Scope challenge: accepted as-is; three production modules are irreducible
  without mixing responsibilities or duplicating format logic.
- Architecture: 3 issues found, 3 folded, 0 unresolved.
- Code quality: 2 issues found, 2 folded, 0 unresolved.
- Test review: coverage diagram produced; 32 named branch/flow obligations,
  all assigned to unit, integration, or live acceptance.
- Performance: 2 measured gates added.
- NOT in scope and existing reuse: present.
- TODO proposals: 0; later host slices already live in this authoritative plan.
- Failure modes: 0 critical gaps after amendments.
- Outside voice: paid audit used; 8 reviews returned, 2 configured lanes failed.
- Parallelization: 1 sequential lane.
- Completeness decisions: 5/5 selected the complete option.

## Cursor amendment review status — 2026-07-28

- Operator authorization covers Cursor discovery and amendment of this existing
  plan only. It does not authorize adapter implementation or user-level
  activation.
- CU0-D is complete. CU0-L is the next gate because project-level CLI hooks did
  not fire and user-level/IDE behavior remains unproven.
- The historical Codex review sections remain evidence for that shipped slice.
  This amendment adds a separate Cursor review result below; it authorizes
  neither CU1-CU4 implementation nor persistent activation.
- No Antigravity or Kimi discovery, code, configuration, or activation is
  authorized by this amendment.

**Current verdict:** DISCOVERY COMPLETE; CURSOR IMPLEMENTATION HOLD AT CU0-L.

## Cursor amendment CEO review — HOLD SCOPE

### Vision, collision, and consequence

The relevant vision is host-independent advisory continuity with one lifecycle
policy owner. Its Definition of Done is evidence-based parity per native host
surface, not a shared adapter that merely appears to run. This remains an
amendment to the existing cross-runtime plan: the shipped Claude lifecycle plan
stays the engine authority, and the R2 Conductor plan stays outside runtime
lifecycle dispatch.

The next proposed action is only CU0-L contract capture. If its temporary
user-level probe is wrong, Cursor could fail to load hooks or an unrelated hook
could be lost. The action is reversible only if Cursor is stopped first and the
exact pre-probe bytes or absence state are restored and hash-verified. CU1-CU4,
Antigravity, and Kimi remain outside this review authorization.

### Premise and alternatives

| Approach | Completeness | Effort | Risk | Verdict |
|---|---:|---:|---:|---|
| A. Treat official docs and bundled validators as the contract | 5/10 | S | medium | Reject: cannot prove user-scope loading, context delivery, or end pairing |
| B. Temporary user-level probe with exact backup/restore, IDE and CLI separated | 10/10 | M | low-medium | Selected: smallest route to physical evidence without shared lifecycle writes |
| C. Implement CU1 from documentation before live capture | 7/10 | M | high | Reject: turns unproven host behavior into production code |

### Eleven-section review result

| Section | Result |
|---|---|
| 1. Architecture | CLEAR after making CU0-L a probe-only predecessor and keeping IDE/CLI promotion independent |
| 2. Error/rescue | CLEAR after naming malformed config, hook-not-fired, nonce-missed, missing end, crash, restore failure, and leftover-process outcomes |
| 3. Security | CLEAR after excluding prompt/transcript contents, `user_email`, credentials, and unrelated payload fields from evidence |
| 4. Data/interaction | CLEAR with explicit null/empty/invalid payload, resume, new-chat, compact, normal close, and abrupt termination branches |
| 5. Code quality | N/A for CU0-L; no production adapter code is authorized |
| 6. Tests | CLEAR when each surface produces an exact event/evidence matrix and post-restore proof |
| 7. Performance | CLEAR; record hook timing, but do not set production budgets from the probe alone |
| 8. Observability | CLEAR with bounded probe logs, explicit zero-event failure, and physical nonce evidence |
| 9. Deployment | CLEAR only as a temporary reversible probe; no persistent activation or source deployment |
| 10. Trajectory | CLEAR; evidence can unlock a thin adapter without freezing a speculative cross-host abstraction |
| 11. Design/UX | SKIPPED; no UI scope |

CEO decisions are agent-resolved under the R1 `/fwp` contract: HOLD SCOPE,
select Approach B, preserve CU0-L as the next gate, and do not infer a Cursor
implementation GO from this review. There are no new TODO proposals and no
unresolved product decisions.

## Paid Cursor amendment audit synthesis — 2026-07-28

This was a custom paid panel constrained by the operator's explicit
`NO ANTIGRAVITY/KIMI` boundary. Antigravity was not invoked. Standalone Kimi and
Perplexity Kimi were omitted rather than substituted. Four OpenRouter paid
models and the isolated Claude Opus CLI returned reviews. Gemini timed out after
180 seconds, and Perplexity best/sonar was blocked because `chrome_ppl` was busy.
The result is therefore a transparent partial panel, not a claim that every
stock `/fwp` lane passed.

Applied consensus and independently valid findings:

1. **Nonce proof had no executable mechanism.** CU0-L now generates a random
   nonce into a Temp-only manifest, returns it in probe-owned
   `additional_context`, exact-matches the response, writes no lifecycle state,
   and treats a missed nonce as event-only evidence and parity failure.
2. **Identity and workspace cardinality were ambiguous.** Stability is scoped
   within one surface/conversation; IDE and CLI IDs are not compared. Only one
   canonical registered Git root may create full state.
3. **`preCompact` could accidentally create state.** CU1 must stop before the
   router when no exact valid binding exists, because the existing router
   persists the binding before its compact branch.
4. **Transcript promotion was underspecified.** CU2 now requires two new
   conversations plus resume/compact stability, readable append semantics, and
   exact native tool IDs. A changed/unreadable end path cannot replace the
   write-once start path.
5. **Probe activation relied too much on operator discipline.** CU0-L now
   enforces the stopped-process precondition and re-hashes immediately before
   replacement, records differential zero-event causes, and restores each
   surface before the next run.
6. **Cursor hook output was broader than needed.** The probe/adapter may emit
   only proven `additional_context`; `env` is explicitly forbidden.
7. **Production timing could be guessed from old Codex numbers.** CU0-L records
   per-event and overlap timing; CU1 derives its hard budget from Cursor evidence
   and host limits rather than copying the historical 2 s/3 s values.

Discarded or deferred findings:

- Treating the literal operator GO phrase as a credential requiring ownership,
  revocation, and security audit logging is a category error.
- A stale-Claude-state sweep, registry redesign, Codex reaper redesign, and
  changes to the shipped emergency-off path are outside this Cursor amendment
  and were not shown to be Cursor blockers.
- Historical Codex performance targets and superseded load-sensitive test notes
  do not establish a current Cursor defect. The Cursor slice receives its own
  regression and measured timing gates before implementation can land.
- Process pools, async dispatch, and a universal cross-host abstraction are
  premature before CU0-L supplies the native contract.

**Audit verdict:** CLEAR FOR THE DOCUMENTED CU0-L GATE, PARTIAL PANEL. No
external P1 remains against the probe-only next step after these amendments.
The panel does not authorize the live probe or implementation.

## Cursor amendment engineering review

### Existing seams and ownership

The production-shaped design reuses the current policy owner:

- `session_router.handle_event` owns normalized dispatch. Its compact branch
  reads/checkpoints the existing plan, but binding persistence happens before
  that branch; therefore the Cursor adapter must reject an unbound
  `preCompact` before delegation.
- `session_lifecycle._binding_matches_event` already requires exact
  repository/worktree/transcript equality. CU1 must preserve that fail-closed
  contract and must never repair an end mismatch by switching paths.
- `session_state.write_session_binding` is already write-once and idempotent for
  identical content. Cursor receives no new identity or persistence schema.
- `resolve_repository` already performs bounded canonical Git-root resolution.
  The adapter adds only the host-specific rule that exactly one explicit root is
  eligible for full state.

No shared engine edit is justified by discovery. The proposed adapter remains a
host-boundary translator; conditional projection owns format parsing; the
installer owns machine mutation; acceptance owns physical evidence.

### Branch and failure contract

```text
native Cursor event
  |
  +-- malformed / unsupported / zero-or-many roots --> bounded no-state result
  |
  +-- sessionStart
  |     +-- null transcript ------------------------> explicit lower fidelity
  |     `-- valid identity + one root + path? ------> write-once delegation
  |
  +-- preCompact
  |     +-- no exact binding -----------------------> no-op; do not call router
  |     `-- exact binding --------------------------> existing checkpoint seam
  |
  `-- sessionEnd
        +-- identity/root/path mismatch ------------> fail closed; no source swap
        `-- exact binding --------------------------> existing close evaluator
```

The adapter returns bounded host diagnostics and never fabricates an end event.
Crash recovery remains reaper-owned. A missing start, repeated start, late hook,
nonce miss, malformed payload, multi-root workspace, and overlapping sessions
all have explicit CU0-L evidence obligations before the corresponding surface
can be promoted.

### Test and performance gate

CU1 red tests must cover valid start/end, repeat/resume idempotency, new-chat
identity, `preCompact` with and without a binding, null and not-yet-readable
paths, end-path mismatch, zero/one/many roots, IDE/CLI namespace isolation,
unsupported events, delegate failure, no `env`, and bounded diagnostics. CU2
adds two-conversation schema stability, resume/compact append behavior, exact
call/result IDs, duplicates, malformed/incomplete records, byte caps, and
redaction. CU3 uses only temporary homes for fresh/repeat/conflict/concurrent
rewrite/interruption/rollback tests. CU4 remains separate per surface.

CU0-L records host timing and overlap behavior. CU1 then sets a blocking timeout
below the measured host limit with explicit headroom and a separately tracked
non-blocking p95 target. No Cursor budget is copied from Codex. Any timeout,
unexpected shared-engine edit, Claude/Codex regression, or missing exact-head
review blocks landing.

### Sequential delivery

| Order | Slice | Entry gate | Exit gate |
|---|---|---|---|
| 1 | CU0-L live capture | literal CU0-L GO; Cursor stopped; reversible probe | per-surface contract/evidence and exact restore |
| 2 | CU1 adapter | at least one proven start/end surface | focused red/green tests plus shared regressions |
| 3 | CU2 projection, if eligible | stable readable native format | structural/negative projection tests |
| 4 | CU3 installer | adapter/projection contract frozen | temporary-home rollback matrix |
| 5 | CU4 acceptance | merged exact head and machine-local activation GO | independent IDE/CLI live verdicts |

Parallel implementation is rejected because each slice consumes the previous
slice's frozen evidence. This review found seven Cursor contract gaps; all seven
are folded above. There are zero unresolved engineering decisions and zero
authorized production edits.

## Cursor CU0-L live contract capture — 2026-07-28

The operator authorized only the reversible live-capture gate with
`GO CURSOR CU0-L LIVE CONTRACT CAPTURE`. The temporary user hook was restored
to its exact pre-state after each surface; the target was absent both before and
after capture, parent ACL matched, and final readback found zero Cursor and
probe processes.

| Surface | Context delivery | Lifecycle pairing | Transcript/root evidence | Promotion |
|---|---|---|---|---|
| Agent CLI `2026.07.23-e383d2b` | exact Temp-only nonce on two new chats and resume | two matching new-chat start/end pairs; resume kept identity without a second start; abrupt stop had no synthetic end | one exact workspace root; start transcript null; end path absolute, existing, `.jsonl` | **PROMOTE TO CU1** |
| IDE `3.13.21` | exact Temp-only nonce | two distinct starts; no end on New Agent or application close | second start reported one root, but canonical equality/encoding remains unproven; transcript null | **HOLD DEGRADED** |

`preCompact` remains `UNPROVEN_NO_DETERMINISTIC_TRIGGER` for both surfaces.
The contaminated initial preflight is retained only as non-promotable diagnostic
evidence. The sanitized aggregate is canonical at
`design/audits/2026-07-28_cursor_cu0l_live_contract_capture/evidence.json`;
raw Temp material is intentionally not committed.

CU0-L is complete per surface. It authorizes no production code or persistent
activation. The next smallest eligible slice is CLI-only and requires
`GO CURSOR CU1 CLI ADAPTER IMPLEMENTATION`.

## GSTACK REVIEW REPORT

| Review | Trigger | Runs | Status | Findings |
|---|---|---:|---|---|
| CEO Review | Cursor amendment `/fwp` | 1 | CLEAR | HOLD SCOPE; reversible CU0-L probe is the only credible next step |
| Paid cross-model audit | custom paid, no Antigravity/Kimi | 5 returned, 2 unavailable | CLEAR/PARTIAL | 7 valid contract gaps folded; unavailable lanes disclosed |
| Eng Review | Cursor amendment `/plan-eng-review` | 1 | CLEAR | 7 issues folded; sequential CU0-L through CU4 gates pinned |
| CU0-L live capture | native IDE and CLI | 2 surfaces | CLEAR/PARTIAL | CLI promoted; IDE degraded; `preCompact` unproven |
| Implementation Review | exact-head diff review | 2+ | CLEAR | Independent reviews found no ship-blocking findings; actionable in-scope items were folded and only the final attested head may land |
| Design Review | UI/UX | 0 | N/A | No UI scope |

- **BOUNDARY:** CLI adapter source and tests only; no shared lifecycle schema or
  policy edit, installer, user hook, persistent activation, IDE, Antigravity,
  or Kimi action occurred.
- **NEXT GATE:** complete R1 landing only after the final exact head passes
  independent review; no new operator token is required.
- **VERDICT:** CU1 IMPLEMENTATION COMPLETE; LAND ONLY THE INDEPENDENTLY
  ATTESTED EXACT HEAD; IDE HELD DEGRADED.

NO UNRESOLVED DECISIONS
