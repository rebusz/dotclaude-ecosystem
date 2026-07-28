---
title: TruthDeck Conductor - Cross-Repo Agent Work Queue
date: 2026-07-22
status: draft
status_detail: architecture-written-awaiting-fwf-review-and-r2-go
risk: R2
phase: plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, orchestration, queue, persistence, truthdeck, multi-host]
related:
  - design/plans/2026-06-27_global_agent_workflow_os.md
  - design/plans/2026-07-21_global_fwf_fwp_contract_reset.md
  - design/plans/2026-07-22_truthdeck_agent_evidence_control_plane_r1.md
---

# TruthDeck Conductor - Cross-Repo Agent Work Queue

## Executive decision

Build **TruthDeck Conductor** as a local, durable coordinator for bounded engineering
work across the operator's repositories and agent hosts.

Conductor answers:

> What work is eligible now, who owns it, what evidence justified the assignment,
> and what must happen before it can advance?

TruthDeck continues to answer:

> What is true now, what is not proven, and what is the smallest permitted next
> action?

These are separate authorities. Conductor owns queue state. TruthDeck owns immutable
evidence snapshots. `/fwf` and `/fwp` continue to own the R1/R2/R3 engineering
lifecycle. Repositories remain the source of truth for plans and code.

**Plan-writing authorization:** granted by the operator on 2026-07-22.

**Implementation authorization:** not implied. Run this R2 plan through `/fwf` or
`/fwp`, then obtain one standing implementation `GO`.

## Consequence, downside, reversibility

- **Proposed action:** add a durable local queue, a single-writer coordinator,
  deterministic scheduler, work/lease/evidence model, CLI and bounded MCP surface,
  host adapters, recovery tooling, and TruthDeck checkpoint integration.
- **Plausible downside if wrong:** a central queue could become a competing workflow,
  launch duplicate agents, act on stale authority, monopolize repositories, or turn
  untrusted plan/handoff text into executable prompts.
- **Reversibility:** stop the coordinator, disable its owned host adapters, export the
  append-only event ledger, and revert its tracked installation. Application repos,
  TruthDeck snapshots, and host sessions remain intact. Database deletion is not part
  of rollback and requires a separate destructive action.
- **Risk grade:** R2 because Conductor introduces durable mutable state, leases,
  subprocess/host dispatch, replay, and cross-repository coordination. It has no
  broker, order-path, live-trading, deployment, or generic shell authority.

## Phase 0 - restatement and collision verdict

### Goal

Provide one visible, durable queue for engineering work across repositories and
Claude, Codex, Cursor, Gemini, Kimi, and Antigravity, with safe resumption after
session or process loss.

### Required behavior

1. Discover possible work without automatically authorizing it.
2. Admit only bounded work with explicit repository, risk, workflow, and terminal
   stage.
3. Order eligible work using dependencies, operator priority, risk gates, and aging.
4. Prevent concurrent ownership of the same Work Item and unsafe repository overlap.
5. Dispatch only through a capability-proven Host Adapter.
6. Require a fresh TruthDeck Evidence Checkpoint at declared lifecycle boundaries.
7. Preserve exact attempt history, handoffs, artifacts, and failure reasons.
8. Recover conservatively: an expired lease is not permission to repeat an ambiguous
   side effect.
9. Give the operator and every supported host the same queue/status semantics.

### Constraints

- Windows-first, with contract tests for POSIX paths and locking.
- Local-first; no mandatory cloud database or external control plane.
- No arbitrary shell service, arbitrary URL fetcher, or generic code-execution API.
- No inference of `GO` from chat, handoff prose, memory, a SHA, or a queue priority.
- No write into dirty operator checkouts.
- No duplicate lifecycle ownership with `/fwf`, `/fwp`, GitHub, Codex tasks, or CDP.
- No LLM access to broker APIs or the order path.

### Collision check

The plan-context loader cannot catalog this repository because it lives under
`D:/dotclaude` rather than `D:/APPS`. A bounded fallback found no repo-local
`PLANS.md`, `IDEA_BOX.md`, vision, `AGENTS.md`, `CLAUDE.md`, or
`Prompts/master_agent.md`.

Related artifacts were inspected:

- `2026-06-27_global_agent_workflow_os.md` was formally closed as shipped scope.
  Its artifact-bus concept was deliberately reduced to append-only files until a
  real multi-agent flow existed. Conductor is that new flow, but it does not reopen
  the old plan.
- `2026-07-21_global_fwf_fwp_contract_reset.md` owns workflow and risk routing.
  Conductor consumes that contract and cannot add a third public full workflow.
- `2026-07-22_truthdeck_agent_evidence_control_plane_r1.md` is shipped. It explicitly
  excludes a daemon, database, mutable task authority, and automatic workflow
  execution. Those exclusions remain true for TruthDeck Core.

**Verdict: CREATE NEW PLAN, LINK SHIPPED PREDECESSORS.** Do not amend or supersede
TruthDeck R1 or the closed Workflow OS.

`PONYTAIL: NOT USED` - this is R2 persistence/orchestration work, which is excluded
from the simplification checkpoint.

>> PHASE 0 COMPLETE

## Why now

The ecosystem has strong point tools but no durable owner of work between sessions:

- plans describe intended work but do not claim or schedule it;
- `/fwf` and `/fwp` execute one approved lifecycle but do not maintain a global queue;
- TruthDeck proves current evidence but intentionally does not own tasks;
- handoffs preserve context but do not reserve ownership;
- Codex tasks, Claude sessions, Kimi sessions, Cursor windows, and other hosts expose
  different continuation surfaces;
- a dead agent can leave an apparently active plan, worktree, or external action with
  no common recovery state;
- prioritization is reconstructed conversationally instead of recorded deterministically.

The missing component is not another source of truth. It is a coordinator that links
existing truths while preserving their authority.

## Current-state evidence and reuse map

Baseline at plan creation:

- repository `main == origin/main == a417a6fd2a6244d689bdce224ac11b8897d33828`;
- repository worktree was clean before the plan branch was created;
- code-review-graph reports `0` nodes, `0` files, never updated; the MCP minimal-context
  call did not complete, so targeted source reads were used as the declared fallback;
- TruthDeck is installed with `drift=[]`, CLI present, Claude/Codex skills present,
  and both Claude and Codex MCP registrations active;
- `D:/APPS/_shared/PORTS.md` was checked. The MVP intentionally opens no network
  listener and allocates no port.

Existing surfaces to reuse:

| Existing surface | Conductor use | Must not become |
|---|---|---|
| TruthDeck snapshots and gates | Evidence Checkpoints | queue database |
| `/fwf` and `/fwp` | lifecycle owner inside an admitted Work Item | scheduler internals |
| plan lifecycle hooks/catalogs | candidate discovery | automatic authorization |
| `git_hygiene.py` patterns | worktree and ownership observation | cleanup authority |
| `implementation_review_packet.py` | exact-head review identity | review executor |
| handoff hash verification | attempt continuation evidence | claim/lease |
| Codex task tools | Codex Host Adapter capability | universal host API |
| Claude CLI `-p`, resume/session flags | bounded Claude adapter candidate | generic command runner |
| Kimi CLI prompt/session/ACP surfaces | bounded Kimi adapter candidate | CDP provider identity |
| Cursor CLI | MCP install and operator navigation | proven autonomous agent |

## Frozen product contract

### Authority layers

| Layer | Owns | Does not own |
|---|---|---|
| Repository | plans, code, tests, tracked artifacts | session ownership |
| `/fwf` or `/fwp` | risk-routed plan review, implementation, exact-head review, landing | global prioritization |
| TruthDeck | observed facts, gates, immutable snapshots, one advisory next action | task state or execution |
| Conductor | admission, dependencies, priority, attempts, leases, dispatch state | technical truth or workflow gates |
| Host Adapter | a bounded host operation | cross-host policy |
| CDP Fleet Manager | browser job queue, role identity, browser health/lifecycle | application work queue |
| Operator | product priority, R2/R3 GO, external/destructive/live gates | routine mechanical reconciliation |

### Non-negotiable invariants

1. **A queue entry is not authority.** `QUEUED`, `READY`, or high priority never means
   implementation is approved.
2. **Evidence is referenced, not copied as truth.** Every gated transition records an
   immutable TruthDeck snapshot path, digest, observation time, and required gate.
3. **Claims and leases are not completion.** They express ownership only.
4. **Lease expiry is ambiguous.** It releases scheduling exclusivity but moves the
   Attempt to recovery review; it never blindly retries a side effect.
5. **One Attempt, one workspace identity.** Repo, base/head, branch, worktree, host,
   session/task ID, and Attempt ID are bound before execution.
6. **Dirty operator checkouts are observational.** Execution uses a dedicated worktree
   unless an explicit item authorizes the named clean checkout.
7. **No arbitrary execution surface.** Job kinds and adapter argv/templates are
   code-owned and allowlisted. Queue payloads cannot supply an executable or raw argv.
8. **Workflow ownership is preserved.** R1/R2/R3 implementation invokes the selected
   `/fwf` or `/fwp` contract; Conductor does not reproduce its internal stages.
9. **Risk gates fail closed.** Missing authorization, missing adapter capability,
   stale evidence, identity conflict, unknown dispatch result, or unsupported host is
   `HOLD`/`BLOCKED`, never a fallback launch.
10. **No host is supported by brand association.** Capability is proven per operation
    and installed version.
11. **Local-first and bounded.** Queue state, receipts, logs, and artifacts live under
    an owned user-home directory with quotas and redaction.
12. **No live/order coupling.** Conductor never submits orders, starts trading runtime,
    changes live configuration, or interprets model output as execution authority.

### Explicit non-goals

- No replacement for `/fwf`, `/fwp`, `/whatnext`, TruthDeck, GitHub, or repo plans.
- No generic autonomous-agent platform, prompt marketplace, or arbitrary tool broker.
- No automatic admission of every plan, idea, memory entry, or untrusted handoff.
- No semantic parsing of chat history to discover authorization.
- No credentials, browser cookies, API tokens, or complete raw model transcripts in
  queue records.
- No GUI in the MVP. CLI/MCP and machine-readable status come first.
- No cloud synchronization or multi-machine consensus in R2.
- No automatic branch deletion, worktree deletion, force push, merge, deploy, restart,
  or destructive cleanup.
- No CDP process, profile, port, role, login, or lifecycle management.
- No promise of autonomous dispatch for hosts without a proven non-interactive API.

## Domain model

The canonical glossary is in `CONTEXT.md`. The persistence model uses the following
entities.

### Work Item

Immutable identity plus versioned intent:

```json
{
  "schema_version": "conductor.work-item.v1",
  "work_item_id": "wi_<ulid>",
  "idempotency_key": "<scope-owned key>",
  "title": "<bounded display title>",
  "repo_id": "dotclaude-ecosystem",
  "repo_path": "D:/dotclaude/dotclaude-ecosystem",
  "plan_path": "design/plans/<plan>.md",
  "risk_class": "R2",
  "workflow": "fwf",
  "requested_terminal_stage": "merged",
  "job_kind": "engineering_plan_lifecycle",
  "priority": 50,
  "dependency_ids": [],
  "authority_requirement": "standing_r2_go",
  "execution_budget": {
    "max_attempts": 1,
    "max_wall_seconds": 7200,
    "max_cost_usd": null
  },
  "scope_digest_sha256": "<digest>",
  "created_at_utc": "<RFC3339>",
  "created_by": "<operator-or-adapter identity>"
}
```

Free-form task text is stored as an inert artifact reference with size and secret
limits. It is never evaluated as policy.

### Attempt

An Attempt binds:

- Work Item version and scope digest;
- Agent Host, Agent Instance, adapter version, and capability;
- repo base/head/branch/worktree identity;
- claim/lease identifiers;
- dispatch idempotency key and dispatch outcome;
- input artifact digests;
- timestamps and heartbeat sequence;
- output/handoff/evidence artifact references;
- terminal status and reason code.

Retries always create another Attempt. An earlier Attempt is immutable except for
append-only lifecycle events.

### Claim and Lease

A Claim is accepted atomically only when:

- the Work Item is eligible;
- dependencies are satisfied;
- no conflicting repo/worktree/resource claim exists;
- the Host Adapter proves the required capabilities;
- the authorization requirement is satisfied;
- the Evidence Checkpoint required for claim is fresh and eligible.

A Lease has a bounded TTL and monotonic heartbeat sequence. Extension requires the
same Agent Instance and Attempt. An expired lease transitions to
`RECOVERY_REQUIRED`; it does not enqueue a retry.

### Evidence Checkpoint

```json
{
  "checkpoint_id": "ev_<ulid>",
  "work_item_id": "wi_<ulid>",
  "attempt_id": "at_<ulid>",
  "boundary": "pre_claim|pre_dispatch|checkpoint|pre_review|pre_complete",
  "snapshot_path": "<absolute owned path>",
  "snapshot_sha256": "<digest>",
  "snapshot_id": "<truthdeck content id>",
  "required_gate": "<gate>",
  "observed_gate_state": "PASS|HOLD|BLOCKED|UNKNOWN|NOT_APPLICABLE",
  "observed_head": "<sha or null>",
  "recorded_at_utc": "<RFC3339>"
}
```

Conductor verifies the file and digest and consumes the declared TruthDeck result. It
does not recompute a TruthDeck gate.

### Host capability

Capabilities are granular:

- `discover`
- `claim`
- `heartbeat`
- `checkpoint`
- `execute_noninteractive`
- `resume`
- `cancel`
- `read_status`
- `return_artifact`

An adapter can be supported for some capabilities and `HOLD` for others.

## Work Item lifecycle

```text
DISCOVERED
    |
    | explicit admission
    v
QUEUED --dependency/authority/evidence missing--> HOLD
    |                                         |
    | eligible                                | condition changes + reconcile
    v                                         |
READY <----------------------------------------+
    |
    | atomic claim
    v
CLAIMED --> DISPATCHING --> RUNNING --> WAITING_EXTERNAL --> REVIEW
    |             |             |                  |             |
    |             |             |                  |             |
    |             +--> DISPATCH_UNKNOWN            +--> BLOCKED  |
    |                         |                                  |
    +--> lease expiry --> RECOVERY_REQUIRED <--------------------+
                                                              |
                            fresh evidence + terminal artifact  |
                                                              v
                                                          COMPLETED

Any non-terminal state may become CANCELLED by explicit operator action.
Invalid or conflicting persisted state becomes QUARANTINED.
```

`BLOCKED`, `HOLD`, `RECOVERY_REQUIRED`, `DISPATCH_UNKNOWN`, and `QUARANTINED` are
distinct and must remain visible.

## Admission and discovery

### Candidate discovery

Read-only discoverers may surface:

- active repo plans and plan catalogs;
- verified handoffs;
- open PRs and exact-head review/CI state;
- explicitly registered recurring operational checks;
- operator-submitted Work Items.

Memory and idea boxes may suggest candidates but cannot directly create `QUEUED` work.

### Admission

Admission requires one of:

1. explicit operator enqueue;
2. a code-owned rule for a named recurring monitor;
3. a workflow-owned continuation artifact whose contract explicitly permits
   continuation.

R2/R3 execution additionally requires a durable explicit authorization reference.
Conductor never searches chat logs for `GO`.

Duplicate admission is prevented by the idempotency key and scope digest. A material
scope change creates a new Work Item version and invalidates prior authorization and
evidence as required by policy.

## Scheduler contract

The scheduler is deterministic for the same eligible set and evaluation time.

Ordering inputs, in precedence order:

1. hard dependencies and resource conflicts;
2. required authority and Evidence Checkpoint eligibility;
3. explicit operator priority;
4. incident/containment class;
5. risk and workflow stage;
6. aging to prevent starvation;
7. stable Work Item ID tie-breaker.

Policies:

- per-repository concurrency defaults to one write-capable Attempt;
- read-only tasks may run concurrently when their declared paths/resources do not
  conflict;
- cross-repo tasks claim every repo in sorted canonical-path order to avoid deadlock;
- an active write Attempt blocks another overlapping write Attempt;
- high priority does not preempt an in-flight agent;
- aging cannot bypass dependencies, evidence, authority, or risk gates;
- operator pause and repo maintenance hold outrank priority.

The selected action and all rejected candidates are recorded with machine-readable
reason codes.

### Execution budgets and backpressure

- every autonomously dispatched Work Item has a finite attempt count and wall-clock
  budget;
- a monetary ceiling is optional only when the host cannot report/enforce cost, in
  which case the adapter must expose that limitation and use time/attempt limits;
- Conductor never changes the workflow-selected model basket or downgrades model
  capability solely to save cost;
- repo, host, and global concurrency limits are backend-owned operator settings with
  live readback;
- repeated adapter failures open a visible host-level hold after a configured bounded
  count; they do not create a retry storm;
- budget exhaustion transitions to `BLOCKED` with usage evidence and never silently
  launches another Attempt;
- priority cannot bypass host rate limits, cost ceilings, or global pause.

## Architecture

```text
repo plans / PRs / handoffs / operator
                  |
                  v
        read-only candidate discovery
                  |
                  v
 conductorctl / MCP / host skill
       | atomic command envelope
       v
 ~/.conductor/inbox/ --------------+
                                   |
                                   v
                         conductord single writer
                                   |
                    +--------------+--------------+
                    |                             |
                    v                             v
          SQLite WAL state + events      TruthDeck checkpoint runner
                    |                             |
                    v                             v
          deterministic scheduler       immutable snapshot reference
                    |
                    v
          capability/authority gate
                    |
          +---------+---------+------------------+
          |                   |                  |
          v                   v                  v
      Claude CLI          Kimi CLI       cooperative MCP/skill
      adapter             adapter        Codex/Cursor/Gemini/
                                            Antigravity
          |                   |                  |
          +--------- attempt artifacts/handoff -+
                                   |
                                   v
                    workflow-owned review/landing

 CDP Fleet Manager -- separate bounded provider adapter only --X-- browser ownership
```

### Process and storage model

Use a **port-free single-writer design**:

- `conductord` is the only SQLite writer;
- clients submit versioned command envelopes through unique temporary files followed
  by atomic rename into `~/.conductor/inbox/`;
- the coordinator validates a command before appending an event and mutating the
  materialized queue state;
- receipts are written atomically under `~/.conductor/receipts/`;
- CLI status opens SQLite read-only or consumes an exported status artifact;
- a leader lock plus owner PID/start identity prevents two coordinators;
- stale lock recovery requires both process-identity failure and database lease expiry;
- no loopback HTTP server, WebSocket, or new port exists in the MVP.

Directory contract:

```text
~/.conductor/
  conductor.db
  inbox/
  receipts/
  artifacts/
  logs/
  locks/
  backups/
  install-manifest.json
```

All paths are containment-checked after resolving symlinks/reparse points.

### Persistence

SQLite WAL is selected over a file-only queue because Conductor requires atomic
multi-entity claims, dependency queries, attempt history, and crash-safe leases.

Requirements:

- single writer;
- foreign keys and schema version table enabled;
- append-only event table plus rebuildable materialized tables;
- transactionally unique idempotency keys;
- UTC timestamps and monotonic durations kept distinct;
- migrations are forward-only in normal operation and backed up before apply;
- bounded startup integrity check;
- corruption or unsupported schema is fail-closed `QUARANTINED`;
- explicit JSONL export provides a durable diagnostic/rollback artifact;
- no automatic deletion in R2.

## TruthDeck integration

Conductor invokes the installed `truthctl` core at declared boundaries:

1. before a Work Item becomes `READY`;
2. before dispatch;
3. after a material Git/PR/review/runtime change;
4. before resuming an Attempt;
5. before review/landing;
6. before completion.

Each invocation creates a new immutable snapshot. Conductor stores only its reference
and digest. A changed HEAD, plan scope digest, authorization requirement, PR head,
review head, CI head, or runtime identity invalidates the corresponding checkpoint.

TruthDeck R1 receives no queue database or daemon responsibility. Conductor consumes
lifecycle evidence checkpoints via a read-only seam with the shipped session lifecycle
engine (`session_lifecycle.py` and `cross_runtime_session_lifecycle_adapters_r1.md`),
reading `session_state.py` and `truthctl` snapshots without writing `session_registry.json`
or owning session lifecycle state.

In the MVP, Conductor renders its own queue status and includes snapshot links. A later
code-owned TruthDeck collector may observe an exported `conductor.status.v1` artifact,
but only with explicit schema compatibility tests; no dynamic plugin is introduced.

## Host Adapter contract and current support

### Required adapter behavior

Every adapter must:

- declare granular capabilities and version;
- support a `doctor` probe with no mutation;
- accept a versioned assignment artifact, never arbitrary argv;
- bind host session/task identity to Attempt ID;
- emit structured progress, heartbeat, artifact, and terminal records;
- enforce repo/worktree and tool-permission boundaries;
- redact secrets and bound output;
- classify ambiguous launch/return as `DISPATCH_UNKNOWN`;
- implement idempotent resume where the host supports it;
- refuse cancellation if it cannot prove the target identity.

### Evidence at plan creation & delta discovery

| Host | Current local evidence | Initial plan status |
|---|---|---|
| Claude | `claude.exe` present; non-interactive `-p`; JSON/stream output; session ID/resume; bounded allowed/disallowed tools | Candidate for autonomous adapter (PROVEN) |
| Codex | Native app tools expose list/create/read/send/wait/handoff/archive; lifecycle adapter shipped in PRs #55–#57 | Cooperative/native-task adapter PROVEN; Standalone dispatch HOLD until stable API proven |
| Kimi | `kimi.exe` present; non-interactive prompt; stream JSON; session resume; ACP stdio and local server surfaces | Candidate for autonomous adapter |
| Cursor | Installed Cursor IDE 3.13.21 & Cursor Agent CLI 2026.07.23-e383d2b; CLI session lifecycle adapter landed (PR #58); no non-interactive execution API | Lifecycle adapter PROVEN; Cooperative client PROVEN; Autonomous dispatch HOLD / UNSUPPORTED |
| Gemini | Config home present; no standalone `gemini` executable found | MCP/skill contract only; Autonomous dispatch HOLD |
| Antigravity IDE | Antigravity IDE 1.107.0 installed at `C:\Users\dszub\AppData\Local\Programs\Antigravity IDE\bin\antigravity-ide.cmd`; CLI launcher provides `antigravity-ide chat [options] [prompt]`; user-level `mcp_config.json` present | Cooperative-only PROVEN (`cooperative-only`); Native session hooks and headless non-interactive autonomous dispatch UNSUPPORTED / HOLD (`HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT`) |
| agy CLI | Standalone `agy` CLI binary is not installed on this machine | Status: `HOLD_NOT_INSTALLED` |

This matrix is a starting observation, not permanent product capability. Each adapter
must pass its own installed-version smoke before promotion.

### Common participation floor

All MCP-aware hosts can eventually share the same queue semantics through a bounded
MCP server:

- inspect queue;
- inspect one Work Item;
- claim eligible work;
- heartbeat/checkpoint;
- attach a bounded artifact;
- report terminal status.

MCP tools do not accept executable names, shell commands, unrestricted environment
variables, or arbitrary mutation paths.

## CDP Fleet Manager boundary

CDP Fleet Manager is a separate R2 project owned by WatchF. It controls:

- browser-provider job scheduling;
- physical CDP role/profile identity;
- browser health and lifecycle requests;
- per-role leases and provider evidence.

Conductor controls:

- application Work Items;
- repo/agent ownership;
- workflow and evidence boundaries.

If a Work Item needs a CDP provider, a future adapter submits one bounded provider job
and receives a result artifact. Conductor never:

- starts, stops, kills, or repairs Chrome;
- owns a CDP role lease;
- chooses a browser profile;
- bypasses the CDP Manager queue;
- treats a provider result as implementation or order authority.

The Conductor MVP does not depend on CDP Fleet Manager being implemented.

## CLI and MCP contract

### CLI

```text
conductorctl doctor
conductorctl discover [--repo <path>]
conductorctl enqueue --request <json>
conductorctl authorize --work-item <id> --authority-ref <path>
conductorctl claim --work-item <id> --agent <identity>
conductorctl heartbeat --attempt <id> --sequence <n>
conductorctl checkpoint --attempt <id> --artifact <path>
conductorctl complete --attempt <id> --artifact <path>
conductorctl block --attempt <id> --reason <code>
conductorctl cancel --work-item <id>
conductorctl status [--repo <path>] [--json]
conductorctl next [--repo <path>] [--json]
conductorctl reconcile [--dry-run]
conductorctl export --output <path>
conductorctl version
```

Mutating commands write an inbox envelope and wait a bounded time for a receipt. They
never write SQLite directly. When the coordinator is down, the response is
`PENDING_DELIVERY` with the envelope path, not false success.

### MCP

Expose a small static surface over the same core:

- `conductor_status`
- `conductor_get_work_item`
- `conductor_claim`
- `conductor_heartbeat`
- `conductor_checkpoint`
- `conductor_report`

Administrative admission, authorization, cancellation, migration, install, and
recovery remain CLI/operator operations.

## Authorization and security

### Authorization records

An authorization reference is a structured, operator-created artifact containing:

- schema version;
- Work Item ID and scope digest;
- risk class;
- authorized workflow;
- permitted terminal stage;
- issued time and optional expiry;
- operator identity/provenance;
- artifact digest.

Conductor validates the artifact but does not infer intent from prose. Scope digest
changes invalidate the authorization.

`authorize` is an operator-only control and is deliberately absent from MCP and Host
Adapter capabilities. The initial implementation must require an interactive console
confirmation and reject authorization supplied through argv, redirected stdin,
environment variables, inbox automation, or an agent assignment. This is a
provenance boundary, not a claim of cryptographic human identity: if a host cannot
distinguish an operator interaction from an agent action, autonomous R2/R3 dispatch
remains `HOLD`.

### Prompt and artifact safety

- plan text, issue text, PR bodies, handoffs, logs, and model output are untrusted;
- assignment templates quote and delimit untrusted content as data;
- adapters receive only allowlisted paths and declared environment variables;
- output and artifacts are byte-bounded;
- secret patterns and unexpected binary content are rejected before persistence;
- queue/status rendering escapes terminal and Markdown control characters;
- raw host transcripts are not persisted by default.

### Filesystem and process safety

- resolve canonical paths before policy checks;
- reject workspaces outside configured roots;
- use dedicated worktrees for write-capable Attempts;
- never clean/reset/switch a dirty operator checkout;
- record PID plus process start identity; PID alone is insufficient;
- cancellation targets only the exact Attempt-owned process/session;
- adapter process trees receive bounded graceful stop, never a broad name-based kill;
- no inherited secret-rich environment beyond an explicit allowlist.

## Failure modes and recovery

| Failure | State | Automatic behavior | Required evidence |
|---|---|---|---|
| coordinator stopped before consuming envelope | `PENDING_DELIVERY` | consume after restart | valid envelope and digest |
| duplicate envelope | existing receipt | return same outcome | idempotency key |
| crash after external launch, before receipt | `DISPATCH_UNKNOWN` | no relaunch | host/session identity reconciliation |
| heartbeat expires during pure read task | `RECOVERY_REQUIRED` | inspect, then operator/policy may retry | process and artifact readback |
| heartbeat expires after possible write | `RECOVERY_REQUIRED` | never auto-retry | Git/worktree/session evidence |
| host adapter missing | `HOLD` | none | successful doctor/smoke |
| stale TruthDeck snapshot | `HOLD`/`UNKNOWN` | request fresh snapshot | new immutable checkpoint |
| scope/head changed | `HOLD` | invalidate checkpoint/authority as applicable | new scope digest and evidence |
| dependency failed | `BLOCKED` | no dependent dispatch | dependency resolution |
| DB integrity/schema failure | `QUARANTINED` | stop mutation | backup/export/recovery proof |
| receipt write failure after DB commit | degraded receipt | regenerate from event ID | DB event identity |
| host reports completion without artifact | `BLOCKED` | no completion | bounded artifact plus digest |
| cancellation identity mismatch | unchanged | refuse | exact Attempt/session/process identity |

Recovery commands must default to dry-run and produce an evidence packet. No recovery
operation may delete worktrees, branches, snapshots, or the queue database.

## Observability

Every event records:

- event ID and schema version;
- Work Item and Attempt IDs;
- previous and next state;
- actor/adapter identity;
- reason code;
- evaluation time;
- scope, input, and artifact digests;
- Evidence Checkpoint ID when applicable;
- process/session/worktree identity where applicable.

`conductorctl status --json` exposes:

- coordinator owner and heartbeat;
- schema/database health;
- inbox depth and oldest age;
- counts by lifecycle state and reason;
- active claims/leases with bounded identity;
- eligible next Work Item and rejected-candidate reasons;
- adapter health/capability matrix;
- stale evidence and recovery-required Attempts;
- artifact paths/digests without sensitive body content.

Logs are bounded and rotated. Retention/deletion remains report-only in R2.

## Implementation slices

### S0 - hostile fixtures, domain contract, and threat model

**Files:** `CONTEXT.md`, plan fixtures, schema fixtures, threat-model test data.

- freeze Work Item, Attempt, Claim, Lease, Evidence Checkpoint, command, receipt,
  event, authorization, capability, and status schemas;
- define state transitions and reason-code registry;
- create hostile fixtures for duplicate commands, stale authority, prompt injection,
  dirty worktrees, identity mismatch, ambiguous dispatch, and corrupt state;
- freeze the CDP separation and workflow authority matrix.

**Gate:** schema and threat-model review complete before persistence code.

### S1 - deterministic model and single-writer persistence

**Files, proposed:**

- `scripts/conductor_model.py`
- `scripts/conductor_store.py`
- `scripts/conductor_commands.py`
- `scripts/tests/test_conductor_model.py`
- `scripts/tests/test_conductor_store.py`

Implement strict schemas, transition validation, SQLite WAL/event ledger, migrations,
atomic inbox/receipts, idempotency, leader identity, export, and corruption quarantine.

**Gate:** crash/replay/property matrix passes without launching any agent.

### S2 - discovery, admission, scheduler, and repo ownership

**Files, proposed:**

- `scripts/conductor_discovery.py`
- `scripts/conductor_scheduler.py`
- `scripts/conductor_repo.py`
- corresponding focused tests.

Implement read-only candidate discovery, explicit admission, dependencies, priority,
aging, resource conflicts, worktree identity, and deterministic `next`.

**Gate:** the same fixture/evaluation time produces byte-stable ordering and reasons;
dirty operator checkout tests prove zero mutation.

### S3 - TruthDeck checkpoints and workflow bridge

**Files, proposed:**

- `scripts/conductor_truthdeck.py`
- `scripts/conductor_workflow.py`
- corresponding focused tests.

Invoke installed TruthDeck with explicit scope, consume shipped `session_state.py` and
`truthctl` snapshots via a read-only seam without duplicating session lifecycle logic,
validate snapshot path/digest/schema, invalidate stale checkpoints, and map Work Items
to the existing `/fwf` or `/fwp` entry contract without duplicating workflow stages.

**Gate:** stale/mismatched evidence and missing R2 authorization cannot reach dispatch.

### S4 - CLI, coordinator, and static MCP adapter

**Files, proposed:**

- `scripts/conductorctl.py`
- `scripts/conductord.py`
- `scripts/conductor_mcp.py`
- `requirements-conductor-mcp.txt`
- CLI/MCP/coordinator tests.

Implement the port-free coordinator, command/receipt protocol, status/readback,
reconcile/export, and six fixed MCP tools over the same core.

**Gate:** CLI/MCP parity, concurrent inbox writers, coordinator restart, leader
collision, and no-network-listener tests pass.

### S5 - host adapters, capability registry, and recovery

**Files, proposed:**

- `scripts/conductor_adapters.py`
- `scripts/conductor_adapter_claude.py`
- `scripts/conductor_adapter_kimi.py`
- cooperative adapter definitions for Codex/Cursor/Gemini/Antigravity;
- host smoke and recovery tests.

Start with fixture adapters. Promote Claude and Kimi only after bounded
non-interactive smoke. Promote other hosts per capability, leaving unsupported
operations visibly `HOLD`.

No adapter may use `--dangerously-skip-permissions`, `--yolo`, broad filesystem
access, or an unbounded environment.

**Gate:** duplicate-launch and ambiguous-dispatch chaos tests pass; every advertised
capability has installed-host evidence.

### S6 - skill, installer, operator docs, and activation

**Files, proposed:**

- `skills/conductor/SKILL.md`
- `scripts/conductor_install.py`
- `templates/conductor.config.json.template`
- Windows/POSIX installer integration;
- operator runbook and installer tests.

Install owned files idempotently with backups, ownership hashes, config round-trip,
status, upgrade, and surgical uninstall. Install no startup task until the core and
recovery suite pass.

**Gate:** clean install/status/reinstall/upgrade/uninstall and foreign-ownership
refusal pass in fake homes and the bounded active-home smoke.

### S7 - exact-head review, landing, and bounded live acceptance

- run the owning `/fwf` or `/fwp` implementation review against the exact head;
- land through draft PR, one ready transition, CI, merge, and checkout sync;
- install from merged `main`;
- enqueue one docs-only fixture Work Item;
- prove claim, heartbeat, TruthDeck checkpoint, artifact return, completion, restart,
  and export;
- do not dispatch into TSU/Tsignal or any live/hardware/order-adjacent repo in the
  first acceptance.

**Gate:** post-install status proves merged versus installed identity and the fixture
completes without duplicate dispatch or repository mutation outside its worktree.

## Test plan

### Model and transition matrix

- every allowed state transition;
- every forbidden transition;
- duplicate Work Item/idempotency/scope digest;
- lease before/at/after expiry;
- monotonic heartbeat replay and out-of-order heartbeat;
- dependency cycle and missing dependency;
- cross-repo resource lock ordering;
- authority scope mismatch and expiry;
- checkpoint head/scope/workflow mismatch.

### Persistence and concurrency

- concurrent atomic inbox writers;
- duplicate envelope before and after receipt;
- crash before transaction, during transaction, after commit, and before receipt;
- two coordinator leaders;
- stale PID reuse with different process start identity;
- WAL recovery and backup-before-migration;
- unsupported/corrupt schema quarantine;
- event-ledger replay equals materialized state;
- read-only status during active writer;
- bounded disk/output and failed atomic replace.

### Scheduler

- dependency and authority precedence;
- operator priority;
- risk and stage ordering;
- aging without bypassing hard gates;
- attempt, wall-clock, cost, rate, and concurrency budgets;
- budget exhaustion without retry;
- no starvation across repos;
- write/read resource conflicts;
- stable ID tie-break;
- operator pause and maintenance hold;
- deterministic rejected-candidate reason list.

### TruthDeck and workflow

- fresh eligible checkpoint;
- exact TTL boundary;
- stale/missing/malformed/conflicting snapshot;
- changed HEAD, plan scope, PR head, review head, and CI head;
- valid handoff hash with stale base;
- `/fwf` versus `/fwp` preservation;
- R2/R3 missing GO;
- merged code without installed/runtime proof;
- TruthDeck unavailable or timed out.

### Host adapters

- doctor missing executable/config;
- version drift;
- safe argv and environment;
- prompt/artifact injection;
- launch success with structured identity;
- launch timeout before/after host session creation;
- resume exact session;
- cancellation exact identity and mismatch refusal;
- output overflow and malformed stream;
- agent completion without artifact;
- host process dies while lease remains;
- Cursor/Gemini/Antigravity unsupported capability stays `HOLD`.

### Security

- path traversal and symlink/reparse escape;
- secret-bearing environment and artifact;
- terminal/Markdown escape injection;
- arbitrary executable/argv/URL rejection;
- foreign installer ownership;
- queue database and authorization permission checks;
- no network listener;
- static scan proving no broker/order/CDP lifecycle imports;
- before/after Git status proving collectors and status are read-only.

### Proposed validation commands

```powershell
python -m pytest -q scripts/tests/test_conductor_*.py
python -m pytest -q scripts/tests/
python -m ruff check scripts/conductor*.py scripts/tests/test_conductor_*.py
python scripts/conductorctl.py doctor --json
python scripts/conductorctl.py status --json
python scripts/conductorctl.py reconcile --dry-run
python scripts/conductorctl.py export --output "$env:TEMP/conductor-export.jsonl"
git diff --check
```

Full existing `scripts/tests` suite runs before PR-ready. A test is reported passed only
when exit code is zero and the expected targets actually ran.

## Performance and limits

Initial acceptance budgets:

- read-only status: p95 <= 250 ms on 10,000 events;
- enqueue receipt with live coordinator: p95 <= 500 ms;
- deterministic scheduling over 1,000 Work Items: p95 <= 500 ms;
- coordinator idle CPU: <= 1% averaged over five minutes;
- MCP construction: p95 <= 100 ms and six tools exactly;
- bounded status JSON: <= 1 MiB;
- individual assignment artifact: <= 256 KiB;
- no unbounded transcript or command output persistence.

Benchmarks use fixed fixtures and publish raw JSON evidence. Budgets may be revised by
engineering review with measured justification.

## Activation

1. Implement on a dedicated branch/worktree.
2. Run focused tests, full repo tests, lint, and security scans.
3. Complete exact-head `/fwf` or `/fwp` review and land on `main`.
4. Run installer `status` against the active home.
5. Install CLI, skill, static MCP adapter, and owned state directories.
6. Start the coordinator manually for the first smoke.
7. Run a docs-only fixture through enqueue -> claim -> checkpoint -> completion.
8. Stop/restart mid-fixture and prove recovery.
9. Only then enable an owned Windows startup task; POSIX service activation remains a
   separately verified installer path.
10. Promote host capabilities one by one after installed-version smoke.

Ship-on applies only after all R2 gates pass. Unsupported host operations remain
`HOLD`; the core feature is not disabled merely because one optional adapter is absent.

## Rollback and emergency off

1. Stop only the exact owned coordinator process.
2. Disable/remove only the owned startup registration.
3. Disable Host Adapters while retaining read-only queue/export.
4. Restore owned host config from installer backups if registration changed.
5. Reinstall the previous tracked version or revert merged commits.
6. Preserve `~/.conductor`, receipts, exports, TruthDeck snapshots, worktrees, and host
   sessions for diagnosis.

Rollback never deletes application branches/worktrees, queue state, or snapshots.
Destructive cleanup requires a separate explicit operator action.

## Definition of Done

- [ ] Domain and state schemas are versioned and threat-modelled.
- [ ] One single-writer coordinator owns durable mutation.
- [ ] Command/receipt/event replay is crash-safe and idempotent.
- [ ] Scheduler is deterministic, dependency-aware, fair, and resource-safe.
- [ ] Dirty operator checkouts are never mutated.
- [ ] Every gated transition binds a verified immutable TruthDeck checkpoint.
- [ ] `/fwf` and `/fwp` remain the only public full engineering workflows.
- [ ] R2/R3 authorization is explicit and scope-bound.
- [ ] Operator authorization is unavailable to MCP/Host Adapters and fails closed
      when interactive provenance cannot be established.
- [ ] Attempt, time, cost, rate, and concurrency limits prevent runaway dispatch.
- [ ] Claims, leases, attempts, recovery, and ambiguous dispatch remain distinct.
- [ ] CLI and MCP expose the same bounded model and reason codes.
- [ ] Every advertised host capability has an installed-version smoke.
- [ ] Unsupported host capabilities visibly report `HOLD`.
- [ ] Claude and Kimi autonomous candidates pass bounded smoke before promotion.
- [ ] Codex, Cursor, Gemini, and Antigravity have a proven cooperative adapter floor or
      an explicit unsupported record.
- [ ] CDP Fleet Manager remains a separate owner with no lifecycle imports.
- [ ] No broker/order/live-trading path is reachable.
- [ ] Installer upgrade/uninstall is ownership-checked and reversible.
- [ ] Exact-head review, CI, merge, main sync, active-home install, restart recovery, and
      docs-only end-to-end acceptance are proven.

## Open risks for `/fwf` review

1. **Name collision:** existing tools use “Conductor” as a host/session label. Product
   docs must consistently say `TruthDeck Conductor`; internal schemas use
   `conductor.*` without assuming any vendor host.
2. **Codex dispatch seam:** native task tools are proven inside the Codex app but not as
   a standalone Python API. Autonomous dispatch stays `HOLD` unless a stable supported
   seam is demonstrated.
3. **Authorization artifact UX:** it must be explicit enough to prevent inferred GO
   without making routine R2 work unusably manual.
4. **Single writer availability:** a stopped coordinator must leave visible pending
   envelopes and never tempt clients to mutate SQLite directly.
5. **External launch ambiguity:** process creation and host session creation are not one
   atomic transaction; `DISPATCH_UNKNOWN` and reconciliation are ship-critical.
6. **Cross-platform locking:** Windows process identity, reparse behavior, and atomic
   replace semantics require real tests; POSIX behavior cannot be assumed from Windows.
7. **Host drift:** host CLIs and app task APIs may change independently. Capabilities
   need versioned doctor evidence and fail-closed promotion.

## CEO review decisions (fwf Stage 1, 2026-07-23, agent-resolved R2)

**Mode: HOLD SCOPE.** The plan is deliberately bounded infrastructure; the complexity
smell (many new modules) is answered by the alternatives analysis below, not by
expansion. Reviewer: Claude (Fable), agent-resolved per the R2 `/fwf` contract.

### Premise verdict

Real problem, not proxy. Evidence from operator history: duplicate-work incident
(WatchF/TSU custody F1 duplicated as TSU PR #230, backed out), phantom-deletion
incident (#465) from manual multi-actor reconciliation, a 30-worktree pile requiring
manual triage (2026-07-03), and — live during this very review — Codex exhausting its
token quota for 5 days, stranding its in-flight lanes with no common recovery state.
Doing nothing keeps paying that tax. Conductor is the most direct path that does not
create a second workflow authority.

### Alternatives considered (0C-bis)

- **A - as planned (selected):** port-free `conductord` single writer + atomic inbox
  + SQLite WAL + adapters. Ideal-architecture path; only variant that gives live lease
  TTL/heartbeat processing without depending on the next CLI call happening.
- **B - daemonless tick:** no coordinator; every `conductorctl` call writes SQLite
  directly under `BEGIN IMMEDIATE`, a scheduled `tick` command processes expiries.
  Genuinely simpler (SQLite WAL serializes concurrent writers itself; the single-writer
  constraint is a design choice for deterministic event order, not a SQLite necessity).
  Rejected: lease expiry and recovery would only be observed on the next invocation,
  which is exactly the dead-agent window Conductor exists to close. Decision: keep A,
  and require the S4 gate to include a liveness test proving lease expiry is processed
  with zero client activity (see D1).
- **C - GitHub Issues/Projects as queue:** rejected — cloud dependency, no lease/
  heartbeat semantics, no local-first guarantee, and trading-adjacent repos must not
  depend on an external control plane.

### Binding decisions

- **D1 (S4 gate addition):** add a liveness acceptance test — with no client
  invocations, an expired lease transitions to `RECOVERY_REQUIRED` within one TTL
  window. This is the concrete payoff justifying the daemon over alternative B.
- **D2 (dependency check, resolved):** `2026-07-21_global_fwf_fwp_contract_reset.md`
  is confirmed landed on `main`; four of five open `codex/*` branches are
  patch-equivalent to main (reap candidates for hygiene), one (`ci-model-b0`) has one
  unlanded commit out of Conductor scope. S3 binds to the landed contract version.
- **D3 (name-collision hardening):** risk #1 is confirmed by live evidence: the gstack
  skill family already detects `CONDUCTOR_WORKSPACE_PATH`/`CONDUCTOR_PORT` env vars and
  a `CONDUCTOR_SESSION` mode for an unrelated third-party host. Conductor MUST NOT
  read or set any `CONDUCTOR_*` environment variable; use `TDCONDUCTOR_*` prefixes and
  keep product wording `TruthDeck Conductor`.
- **D4 (truthctl exit-code contract):** the checkpoint runner must distinguish
  "snapshot valid, gates not all green" (observed live: exit 12 with complete JSON)
  from "collector failed". Exit 12 with parseable snapshot is a VALID checkpoint whose
  gate states are consumed; only malformed/missing output is a checkpoint failure.
  Add both cases to S3 tests.
- **D5 (storage exhaustion):** disk-full/quota failure while writing
  `~/.conductor` (db, WAL checkpoint, inbox, receipts) is a distinct failure mode from
  corruption; it must fail closed to a visible degraded/QUARANTINED state without
  losing the event ledger. Add to S1 tests.
- **D6 (provider-quota reason code):** "host quota/token budget exhausted" (the
  currently-live Codex condition) becomes a named reason code driving the host-level
  hold, distinct from adapter-missing and adapter-error.

### Expansion opportunities (recorded, NOT in scope - operator may cherry-pick at GO)

1. `/whatnext` steering-brief integration: render `conductorctl status` next to the
   coverage map (R1, small, after S4).
2. Windows toast on `BLOCKED`/`RECOVERY_REQUIRED` via the existing notification path
   (R1, small, after S4).
3. TruthDeck read-only collector for `conductor.status.v1` (already deferred by the
   plan itself; keep deferred).
4. Verified-handoff auto-admission rule (plan already defers; keep deferred - highest
   prompt-injection surface).

## Matrix review record (fwf Stage 2, free basket, 2026-07-23, judge: Claude)

**Panel honesty:** 12 lanes launched; **2 substantive returns** (Nemotron 3 Super
120B, Poolside Laguna M.1), 2 degenerate (too-short), **8 failed**: all four CDP
frontier lanes (Gemini timeout incl. one retry, ChatGPT `input_selector_not_found`,
Perplexity `connect_over_cdp` timeout incl. one retry, Kimi no-listener), and four
OpenRouter free lanes (3x HTTP 404 roster rot, 1x 429). The frontier cross-check
that normally prevents self-grading was therefore **absent**. Confidence:
**LOW-MEDIUM** — consensus is real but shallow. Run:
`~/.claude/fusion_runs/2026-07-23_081437_title-truthdeck-conductor-cross-repo-age`.
The CDP fleet degradation is flagged as a separate WatchF triage task, out of this
plan's scope.

**Consensus (both lanes + judge):** plan is implementation-ready for the R2 gate;
CEO decisions D1-D6 close the real gaps and must be carried verbatim; authority
split (Conductor = queue state only) holds; **no boundary violations found** (no
broker/order reach, no CDP lifecycle, no third workflow).

**Applied amendments (judged valid, in scope):**

- **M1 (from panel, folded into S0/S4):** the operator-authorization
  interactive-provenance check becomes an explicit tested contract, not prose:
  S0 freezes the rule (authorize accepted only from an interactive console;
  rejected when supplied via argv, redirected stdin, environment variables, inbox
  envelopes, or an agent assignment) and S4 carries a test row for each rejected
  channel plus the accepted interactive path.
- **M2 (from panel, folded into S1/S2 gates):** the performance budgets in
  "Performance and limits" are validated by fixture benchmarks at the S1 and S2
  gates (raw JSON evidence published), not asserted.

**Judge blind-spot addition (carried to eng review):** MCP `conductor_claim` is
agent-reachable; claim-spam from a misbehaving MCP client must be bounded by the
existing rate/concurrency limits — add an explicit abuse-test row (repeated claim
attempts from one host identity open a visible host-level hold, never a retry
storm).

**Discarded:** degenerate bare-"GO" outputs (Cohere North Mini, Nemotron Nano)
carry no evidentiary weight and were not counted as approvals.

## Engineering review (fwf Stage 3, 2026-07-23, agent-resolved R2)

Reviewer: Claude (Fable). Scope was settled in Stage 1 (HOLD SCOPE) and is not
re-litigated. Sections: architecture, quality, tests, performance. Confidence
scores per finding; findings are folded directly into the slices below.

### Architecture

- **E1 [P2, confidence 8/10] Installer reuse.** S6's `conductor_install.py` must
  reuse the shipped TruthDeck installer pattern from `scripts/truthdeck_install.py`
  (ownership hashes, drift detection, backup-before-overwrite, `status` JSON,
  foreign-file refusal) — verified working live today (`drift=[]`, `state:
  installed`). This also answers runtime-environment ownership: Conductor's CLI/MCP
  pin the same interpreter/venv mechanism `truthctl` uses. Do not invent a second
  installer idiom in the same repo (DRY at the infrastructure level).
- **No further architecture findings.** Layering, leader-lock identity
  (PID + process start time), inbox atomicity, and the CDP/workflow boundaries were
  already pressure-tested by Stage 1 (alternatives A/B/C) and Stage 2; the failure-
  mode table covers every integration point with a visible state and no silent path.

### Code quality

No findings beyond what Stage 1 bound: the reason-code registry and all entity
schemas are single-sourced in `conductor_model.py` (S0/S1) and consumed by CLI,
MCP, and status alike; `TDCONDUCTOR_*` env prefix per D3.

### Tests (additions folded into the test plan)

The existing matrix is close to complete. Added rows:

- **T-live (S4, from D1):** with zero client invocations, an expired lease reaches
  `RECOVERY_REQUIRED` within one TTL window.
- **T-auth (S4, from M1):** authorization accepted only interactively; one test row
  per rejected channel (argv, redirected stdin, env var, inbox envelope, agent
  assignment) plus the accepted interactive path.
- **T-claimspam (S4, judge blind spot):** repeated `conductor_claim` attempts from
  one MCP host identity trip the bounded-failure host-level hold — visible hold,
  no retry storm, other hosts unaffected.
- **T-clock (S1):** system wall-clock moved backwards between events — ledger order
  is unaffected (event IDs monotonic), lease TTL/heartbeat use monotonic durations,
  and no state transition regresses.
- **T-upginstall (S6):** installer upgrade attempted while the coordinator is
  running — refused or safely serialized; never leaves a half-upgraded install.
- **T-disk (S1, from D5):** simulated disk-full/quota on db/WAL/inbox/receipt
  writes fails closed to visible degraded/`QUARANTINED` without event-ledger loss.

### Performance

Budgets stand as written; per M2 they are validated by fixture benchmarks with
published raw JSON at the S1 (store) and S2 (scheduler) gates, and revised only
with measured justification. No further findings.

### Worktree parallelization

| Lane | Slices | Notes |
|---|---|---|
| A (sequential spine) | S0 → S1 → S2 → S3 → S4 | shared `scripts/conductor_*` core, hard dependency chain |
| B (post-S4, parallel) | S5 adapters | depends on S4 CLI/coordinator surface |
| C (post-S4, parallel) | S6 installer/skill/docs | depends on S4 artifacts only |
| join | S7 | after B and C |

Lanes B and C may run in parallel worktrees after S4; flag: both touch
`scripts/`, so keep file sets disjoint (`conductor_adapter_*` vs
`conductor_install.py`/`skills/`).

### Failure modes

Zero critical gaps: every failure row in the plan's table has a visible state,
required evidence, and (with the T-rows above) a test. No silent path found.

### Outside voice

Owned by the `/fwf` workflow itself: Stage 2 matrix was the cross-model pass
(degraded panel, recorded honestly above). Codex CLI is quota-exhausted at review
time; no duplicate subagent pass was run — the workflow's own Stage 2 record is
the outside voice of record. gstack review-log/dashboard plumbing skipped
(cross-project slug attribution would be wrong from this session's cwd).

## Current-head delta review (fwf Stage 4, 2026-07-28, exact head: 0805465)

Reviewer: Antigravity Host / Claude Pair.
Reconciliation of Stages 1–3 review record with current HEAD (`0805465`):

1. **Binding Decisions D1–D6:** Preserved unchanged. D1–D6 remain valid and active.
2. **Host Capability Classification Corrections:**
   - **Antigravity IDE:** Classified strictly as `cooperative-only` (cooperative MCP/skill client `PROVEN`; native session event contract & headless non-interactive autonomous dispatch UNSUPPORTED / HOLD).
   - **`agy` CLI:** Classified as `HOLD_NOT_INSTALLED` (standalone `agy` CLI binary is not present on this machine; status is `HOLD_NOT_INSTALLED`, not a global host unsupported statement).
   - **Antigravity Lifecycle Adapter:** Classified as `HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT` (no native `hooks.json` event contract proven for Antigravity runtime).
   - **Cursor Host Adapter:** CLI session lifecycle adapter landed in PR #58 (`PROVEN` for session start/end event logging), but non-interactive autonomous dispatch remains `HOLD / UNSUPPORTED`.
3. **Session Lifecycle Engine Seam:** Conductor S3 reads `session_state.py` and `truthctl` snapshots via a read-only seam with the shipped session lifecycle engine (`session_lifecycle.py` and `cross_runtime_session_lifecycle_adapters_r1.md`), without writing `session_registry.json` or owning session state.
4. **Historical Test References:** Removed historical test count assertions from the plan doc; validation mandates executing the complete live `scripts/tests` suite.

## Approval gate

This document authorizes planning only.

Next workflow:

```text
/fwf D:/dotclaude/dotclaude-ecosystem/design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md
```

After the R2 CEO -> matrix -> engineering plan review incorporates all valid findings,
the workflow must stop at the standing implementation gate:

`>> APPROVAL NEEDED - reply GO to proceed`

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/fwf` Stage 1 | Scope & strategy | 1 | CLEAR | mode HOLD SCOPE; 6 binding decisions (D1-D6); 4 expansions deferred |
| Matrix Review | `/fwf` Stage 2 (`fuse.py --mode free`) | Multi-model 2nd opinion | 1 | CLEAR (degraded panel) | 2/12 substantive lanes; M1-M2 applied; confidence LOW-MEDIUM |
| Eng Review | `/fwf` Stage 3 | Architecture & tests (required) | 1 | CLEAR | 1 issue (E1 installer reuse, folded); 6 test rows added; 0 critical gaps |
| Current-Head Review | `/fwf` Stage 4 | Reconcile delta vs HEAD 0805465 | 1 | CLEAR | Antigravity IDE `cooperative-only`; `agy` `HOLD_NOT_INSTALLED`; lifecycle `HOLD_NO_PROVEN_SESSION_EVENT_CONTRACT`; read-only lifecycle seam bound |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | no UI scope (CLI/MCP MVP) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | not requested |

**CROSS-MODEL:** matrix consensus (Nemotron 3 Super, Laguna M.1) endorsed the
architecture and D1-D6 with no boundary violations; frontier CDP lanes failed
(fleet degradation, separately triaged) so cross-model coverage is thinner than
the free-basket norm — recorded, not hidden.

**VERDICT:** CEO + MATRIX + ENG + CURRENT-HEAD CLEARED — plan is review-complete for the R2
standing implementation gate. Implementation requires one explicit operator GO
(`>> APPROVAL NEEDED` above); no reviewer output constitutes that GO.

NO UNRESOLVED DECISIONS
