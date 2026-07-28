# Cross-Runtime Session Lifecycle Adapters — Codex First

**Date:** 2026-07-27
**Status:** ACTIVE — Codex slice in implementation workflow
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
2. Codex — this implementation slice.
3. Cursor — discovery and adapter slice after Codex acceptance.
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

## Frozen boundaries

- Advisory/best-effort only, preserving the operator's accepted C11/C14 posture.
- No broker API, order path, execution authority, live decision state, or
  production deployment.
- No new lifecycle policy, verdict vocabulary, persistence schema, or second
  registry owner.
- No transcript globbing or fallback to another session.
- No assumptions about Cursor, Antigravity, or Kimi hook contracts during the
  Codex slice.
- No installer rewrite beyond the smallest idempotent activation path required
  for Codex.

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

## Deferred runtime slices

Cursor, Antigravity, and Kimi remain `NOT STARTED`. Each next slice begins with
native lifecycle-contract discovery and a disposable prototype. A host without
reliable start/end events will receive an honest lower-fidelity adapter; this
plan will not claim parity by polling or fabricating session identity.

## CEO decisions

- **Scope mode:** HOLD SCOPE. Cross-runtime parity is the product, but only the
  Codex slice is authorized now.
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

### NOT in scope

- Cursor, Antigravity, and Kimi implementation — sequenced after Codex acceptance.
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
- [ ] **T5 (P1, human ~1h / Codex ~15m)** — live acceptance — prove a normal new session
  - Surfaced by: trust cannot be inferred from bypassed smoke.
  - Files: machine-local hook/registry/state evidence only.
  - Verify: start context, exact binding, close verdict, ephemeral no-op.

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

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope and strategy | 1 | CLEAR | HOLD SCOPE; Codex parity requires transcript projection and normal trust |
| Codex Review | `/codex review` | Independent exact-head review | 0 | PENDING | Runs after implementation |
| Eng Review | `/plan-eng-review` | Architecture and tests | 1 | CLEAR | 7 issues/gates found, all folded; 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | N/A | No UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | N/A | Installer behavior covered by engineering gate |

- **CROSS-MODEL:** Eight returned reviews converged on adapter seam, activation atomicity, repeated/degraded events, and registry rollback; two configured lanes failed.
- **VERDICT:** CEO + ENG CLEAR; paid audit synthesized; ready to implement.

NO UNRESOLVED DECISIONS
