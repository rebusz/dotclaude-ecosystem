# GRILL: Conductor process ownership and memory prevention

R2; operator GO 2026-10-13. Written after the Phase 0 plan and before code.

## Challenge the premise

1. **Are the 42 processes ours?** Not proven. Legacy Python, session 0 and large
   RSS do not establish ownership. The first real report must KEEP unidentified
   processes, even if that means freeing zero memory today. Prevention is the
   immediate deliverable; old-process cleanup cannot be guessed into authority.
2. **Does lease expiry prove a process is stale?** No. A paused owner, inaccessible
   owner and SUBMIT_UNCONFIRMED attempt retain custody. Store launcher identity
   separately from child identity; require positive terminal/dead-owner evidence.
3. **Does killing the parent free the tree?** No. The existing bounded pytest loop
   terminates only its Popen child. A Windows Job or identity-aware tree boundary
   must encompass helpers, including success-path leftovers. Failure to establish
   containment must stop payload execution and preserve recovery evidence.
4. **Does source capacity solve RAM pressure?** No. Counts and memory are separate
   constraints. Use the same durable transaction to reserve lane budgets; never
   create a second host:heavy pool or make CDP wait for the heavy pytest slot.
5. **Does a process list authorize termination?** No. Read-only table collection
   is for diagnostics/reaper qualification, never a replacement for the retained
   Popen handle in bounded pytest supervision. PID reuse and TOCTOU matter.

## Existing seams to unify

- ConductorStore owns SQLite schema migrations, transactions and persistence.
  Add registry/reservations there; do not create JSON sidecar authority.
- HostResourceManager.request/release/reconcile and its bounded pytest consumer
  are the admission boundary. Extend these instead of writing another scheduler.
- ConductorScheduler already sorts numeric priority and dependencies; introduce
  named lane priorities there and in launch arguments, retaining deterministic
  ordering and authority checks.
- Claude/Kimi dispatch adapters currently use subprocess.run and unbounded
  captured output. Route their bounded invocations through the same registered
  process helper. TruthDeck's Python helpers are additional launch seams; short
  git/availability probes need time bounds and must not imply model availability.
- conductorctl is the operator API; process-report/status belongs here. Reaper
  logic is a pure classifier plus a separately gated actuator, not a daemon.

## Risks and decisions

| Risk | Decision / acceptance evidence |
| --- | --- |
| PID reuse or concurrent exit | Exact creation identity and session; pinned handle at actuation; mocked races |
| Job assignment race/nested jobs | Establish containment before payload execution or fail closed; no global taskkill |
| SYSTEM/other sessions | Always KEEP; no privilege escalation, session-0 cleanup or task takeover |
| Secret command arguments | Only a command hash persists; denylist sees arguments transiently; no environment dumps |
| Caller disables timeout | Dedicated finite per-test timer enforced by Conductor plugin, plus parent wall deadline |
| Registry corruption/missing metadata | Refuse spawn/kill; explicit report error rather than an empty healthy report |
| Failed cleanup releases capacity | Keep RECOVERY_REQUIRED and memory reservation until positive terminal evidence |
| Live RAM makes tests nondeterministic | Inject telemetry for policy tests; real host gate still applies to full-suite launch |
| Test launches accidentally kill processes | Destructive tests use fake handles/tables; no real reaper --kill invocation |
| Public CI touches trading workstation | Keep draft; preserve isolated self-hosted route; do not dispatch CI |

Priority options > CCTV > BOS > runtime governs new work only. It never grants
permission to kill any runtime. Memory estimates are reservations, not claims of
actual per-process RSS limits. Use conservative remaining headroom rather than
subtracting already-resident RSS twice. Hysteresis and bounded trend samples must
survive a coordinator restart; unknown telemetry blocks new admissions.

## Alternatives rejected or limited

- Process-name/parent-age reaping: insufficient ownership, rejected.
- WMI-driven pytest supervision: violates retained-handle authority, rejected.
- Periodic working-set trimming/empty-standby-list: hides pressure without fixing
  lifetime and can hurt live workloads, rejected.
- Separate supervisor/registry/scheduler service: duplicates admission, rejected.
- pytest-timeout as an undeclared optional dependency: silent coverage gaps,
  rejected; use an explicit bundled plugin or validate a required dependency.
- Immediate scheduled kill task or rollout installation: outside this worktree
  assignment. Provide a dry-run routine/command and document future scheduling.

## Acceptance and publication boundaries

Mocked tables cover every hard exclusion, identity reuse, ownership ambiguity,
staleness and final-action races. Store tests perform write/close/reopen. Admission
tests cover concurrent reservation, pressure, hysteresis, priority and uncertainty.
Bounded-run tests exercise real success/failure paths; destructive cleanup is
simulated. Full local suite must actually finish with exit 0 before claiming PASS.

Phase 0 publication is currently blocked: PLAN copy returned AccessDenied and
git add could not create the shared Git index.lock (Permission denied). Do not
bypass either restriction. Source work and local evidence in this worktree remain
authorized. End state stays draft; no main push, ready, merge or installation.

## Resume findings and evidence (2026-10-13)

The inherited work was inspected before further edits. Independent read-only
review found two reaper evidence bugs: successful termination followed by a
handle-close failure was reported KEEP, and a later snapshot error could discard
earlier actuation outcomes. Both were repaired with mocked regressions and
rechecked by the separate reviewer. The stdlib reaper suite passes 34 tests.

The integration pass also corrected inaccessible-owner liveness (AccessDenied
is not death), temporary-output failure before spawn, final output cutoff,
named CLI priorities/budgets, observable request budgets, ini-based timer
disablement, and TruthDeck checkpoint registration. These broader changes have
syntax validation but still need pytest in a qualified environment.
Adapter owner labels were also made unique per independent invocation (or
explicitly inherited), avoiding cross-session attribution through one fixed
provider-wide owner name; regressions were added but remain pytest-blocked.

Coverage limitation: root worker launches are registered before resume; Job
descendants are sampled every 0.5 seconds. Short-lived descendants can finish
between samples. Job containment covers their lifetime, but the registry is not
an exhaustive process-birth journal. Claude/Kimi version probes and the GUI's
Python recovery helper now use the same registered launcher. Direct Git
subprocesses remain outside the Python/pytest/agent registry scope. Do not claim
every ecosystem process is registered.

The requested real dry-run used native Get-Process because psutil was unavailable.
It classified 655 actual processes, all KEEP (50.491299 GiB aggregate RSS),
including 71 Python/pytest processes (12.455237 GiB). Registry and full identity
were unavailable, so this is partial diagnostics, not orphan qualification.
