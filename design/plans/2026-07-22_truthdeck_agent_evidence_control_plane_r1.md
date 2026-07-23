---
title: TruthDeck / truthctl - Agent Evidence Control Plane
date: 2026-07-22
status: draft
status_detail: owner-plan-ready-for-r1-fwf
risk: R1
phase: owner-plan
repos: [dotclaude-ecosystem]
tags: [agent-tooling, evidence, truth, cli, mcp]
related: [design/plans/2026-06-27_global_agent_workflow_os.md, design/plans/2026-07-21_global_fwf_fwp_contract_reset.md]
---

# TruthDeck / `truthctl` - Agent Evidence Control Plane

## Executive decision

Build TruthDeck in `D:/dotclaude/dotclaude-ecosystem` as a read-only, evidence-first
tool for Codex, Claude, Cursor, and the operator. Its job is to answer one question:

> What is true now, what is not yet proven, and what is the single smallest permitted
> next action?

TruthDeck is not a new workflow and does not replace `/fwf`, `/fwp`, `/whatnext`,
EcosystemControl, plan lifecycle hooks, or repo-specific readiness tools. It normalizes
their evidence, evaluates deterministic gates, and renders a machine-readable snapshot
plus one advisory next action.

**Plan-writing authorization:** granted in the 2026-07-22 Codex session.
**Implementation authorization:** not implied by this document. Run this R1 plan through
`/fwf <plan>` or `/fwp <plan>` before implementation.

## Consequence, downside, reversibility

- **Proposed action:** add a shared Python core, `truthctl` CLI, thin TruthDeck skill,
  optional local MCP adapter, installer support, and TSU/Tsignal read-only profiles.
- **Plausible downside if wrong:** TruthDeck could become a second stale source of truth,
  hide collector failures behind a green summary, leak sensitive local context, or compete
  with the existing workflow router.
- **Reversibility:** fully reversible. Revert the TruthDeck commits, remove only its
  installed wrapper/MCP registration after an ownership-hash check, and leave immutable
  local snapshots untouched unless the operator separately requests their deletion.
- **Risk grade:** R1. No trading runtime mutation, broker access, order-path access,
  configuration writes in application repos, or process start/stop behavior.

## Why now

The ecosystem already has strong point tools, but every non-trivial session still spends
time reconciling them manually:

- plans and visions express intent, not current Git or runtime truth;
- Git/worktree state does not know PR, CI, review, or runtime state;
- a merged implementation is often mistaken for runtime proof;
- exact-head review can silently become stale after a fix;
- handoffs are useful context but can be stale, hash-mismatched, or based on an obsolete
  branch;
- `/whatnext` must currently reconstruct the same plan/Git/runtime picture each time.

The product opportunity is therefore not another dashboard. It is a deterministic
**evidence compiler** for agent work.

## Current-state evidence and reuse map

Current repository baseline at plan creation:

- `main == origin/main == 36a2882da4cfd6ba50945a0af50f1abec91ab78d`;
- `python -m pytest -q scripts/tests` -> `102 passed, 2 subtests passed`;
- broad `python -m ruff check scripts` reports 14 pre-existing violations, so TruthDeck
  must lint every new/touched Python file without turning unrelated cleanup into scope;
- the repository code-review graph contains 0 nodes and has never been built; targeted
  source reads were used instead;
- `plan_context_loader.py` currently detects only repositories directly under
  `D:/APPS`, so it does not detect this repository under `D:/dotclaude`. This is a known
  plan-lifecycle limitation, not a reason to put the TruthDeck plan in the wrong repo.

Existing components to reuse rather than duplicate:

| Existing surface | TruthDeck use |
|---|---|
| `scripts/_catalog_common.py` | bounded frontmatter parsing and repo discovery patterns |
| `scripts/git_hygiene.py` | read-only worktree, branch, ancestry, dirt, and ownership analysis |
| `scripts/implementation_review_packet.py` | exact base/head identity, secret rejection, and review-packet contract |
| `scripts/terminal_evidence.py` | atomic writes, redaction helpers, timeout/error semantics |
| `scripts/plan_context_loader.py` / `plan_catalog.py` | plan/vision/idea context; never treated as live proof |
| `scripts/steer_context.py` + `skills/whatnext/SKILL.md` | steering consumer of TruthDeck facts, not a duplicate next-step engine |
| repo-specific JSON/read-only preflights | runtime facts through registered, allowlisted adapters |

## Frozen product contract

### Invariants

1. **Read-only by default and by construction.** Collectors use explicit argv arrays,
   `shell=False`, bounded timeouts, and a command allowlist. No generic shell-command tool
   exists.
2. **Unknown fails closed.** Timeout, missing command, malformed JSON, stale evidence, or
   conflicting sources can never become `PASS`.
3. **Every assertion carries provenance.** A fact without source, observation time, and
   freshness policy is not eligible for a gate.
4. **Domains remain separate.** Planned, implemented, exact-head reviewed, CI, merged, and
   runtime/live are independent stages.
5. **Handoff and memory are context, never authority.** A valid handoff hash does not grant
   GO, prove current HEAD, or prove runtime activation. Memory is not an MVP collector.
6. **No inferred operator authorization.** V1 may report the required literal token or an
   explicitly supplied authorization artifact, but it never mines chat logs or treats a
   SHA as a GO token.
7. **One next action.** The engine returns the earliest safety-relevant unsatisfied gate,
   not a backlog tour. It may include alternates in evidence, but only one item is marked
   `recommended=true`.
8. **No workflow competition.** TruthDeck observes `/fwf`/`/fwp` artifacts and review
   evidence. It cannot implement, review, ready, merge, deploy, start, stop, arm, or trade.
9. **Local-first artifacts.** Snapshots are immutable local files. No upload, telemetry,
   cloud database, or external publication is in scope.
10. **Deterministic core.** Given identical normalized facts and policy, gate results,
    reason codes, and next action are byte-stable apart from declared observation metadata.

### Explicit non-goals

- No GUI, React dashboard, or EcosystemControl panel in v1.
- No always-on daemon, HTTP service, event bus, SQLite database, or new state authority.
- No replacement for `code-review-graph`, plan catalogs, workflow skills, GitHub, or
  runtime-specific preflights.
- No automatic repair, checkout switch, worktree cleanup, commit, push, PR transition,
  merge, config change, process restart, broker access, or order action.
- No generic plugin system that executes arbitrary repository code.
- No semantic interpretation of free-form handoff prose as permission.
- No broad repo-path abstraction refactor of all existing plan/vision tools in this plan.

## User journeys

### Session start

```powershell
truthctl snapshot --repo "D:/APPS/TSU" --plan "design/plans/<plan>.md"
truthctl next --snapshot "$env:USERPROFILE/.truthdeck/snapshots/<id>.json"
```

The agent receives a compact summary and an immutable JSON evidence path. A nonzero exit
status remains visible when the state is `HOLD`, `BLOCKED`, or `UNKNOWN`.

### Verified handoff continuation

```powershell
truthctl verify-handoff `
  --repo "D:/APPS/Tsignal 5.0" `
  --handoff "$env:TEMP/<handoff>.md" `
  --sha256 "<expected>"
```

The result separates file integrity, referenced-path integrity, Git freshness, runtime
freshness, and authorization. A hash match alone is never a green continuation verdict.

### Exact-head closeout check

```powershell
truthctl snapshot --repo "D:/dotclaude/dotclaude-ecosystem" --pr 42 --require review,ci,merge
```

The review and CI gates pass only when their evidenced head equals the current PR head.

### MCP use

The MCP server exposes only four structured tools over the same core:

- `truthdeck_snapshot`
- `truthdeck_next`
- `truthdeck_verify_handoff`
- `truthdeck_diff`

It exposes no generic execution tool and no mutating application control.

## Architecture

```text
explicit CLI/MCP request
          |
          v
  scope + registry resolver
          |
          v
  bounded collectors -------------------------------+
  | git/worktrees | plans | GitHub | review |       |
  | handoff       | runtime profile | artifacts |   |
  +--------------------------+----------------------+
                             v
                 normalized facts (immutable)
                             |
                             v
              conflict + freshness resolution
                             |
                             v
                deterministic gate evaluator
                             |
                             v
             one advisory next-action selector
                             |
                 +-----------+-----------+
                 v                       v
       canonical snapshot JSON     bounded Markdown
                 |
                 v
        immutable local snapshot store
```

### Module layout

Keep top-level Python modules under `scripts/` because both current installers copy
`scripts/*.py` into `~/.claude/scripts/`:

```text
scripts/truthdeck_model.py          enums, dataclasses, schema validation
scripts/truthdeck_collectors.py     collector protocol + generic collectors
scripts/truthdeck_git.py            Git/worktree collector using git_hygiene reads
scripts/truthdeck_github.py         bounded gh JSON collector
scripts/truthdeck_handoff.py        hash/reference verifier; prose is inert data
scripts/truthdeck_profiles.py       code-owned probe allowlist and profile predicates
scripts/truthdeck_runtime.py        allowlisted JSON-probe adapter
scripts/truthdeck_gates.py          gate evaluation + reason codes
scripts/truthdeck_storage.py        canonical JSON, atomic append-only storage, latest pointer
scripts/truthdeck_render.py         bounded Markdown and diff rendering
scripts/truthctl.py                 CLI entry point
scripts/truthdeck_mcp.py            optional FastMCP adapter only
scripts/tests/test_truthdeck_*.py   unit, integration, contract, security tests
skills/truthdeck/SKILL.md           thin routing/usage skill; no duplicate policy table
templates/truthdeck.registry.json.template
docs/TRUTHDECK.md
requirements-truthdeck-mcp.txt
```

No module may import an application repo. Runtime integration is data-driven through
registered argv plus a named JSON parser contract.

## Data contract

### Snapshot

`truthdeck.snapshot.v1` contains:

```json
{
  "schema_version": "truthdeck.snapshot.v1",
  "snapshot_id": "<content-derived id>",
  "observed_at_utc": "<RFC3339>",
  "scope": {"repos": [], "plan": null, "pr": null, "task": null},
  "tool": {"version": "<semver>", "policy_digest_sha256": "<sha256>"},
  "facts": [],
  "conflicts": [],
  "gates": [],
  "next_action": {},
  "boundaries": [],
  "collector_runs": [],
  "source_digest_sha256": "<sha256>"
}
```

Each fact contains:

- stable `key` and JSON `value`;
- `state`: `observed`, `derived`, `unavailable`, `stale`, or `conflict`;
- `source_type` and redacted `source_locator`;
- `observed_at_utc` and optional `fresh_until_utc`;
- `evidence_sha256` over the normalized source payload;
- `derivation` listing input fact keys for derived values.

No numeric confidence score is used. Eligibility is structural: observed and fresh,
derived from eligible inputs, or ineligible.

### Gate states

- `PASS` - every required fact is eligible and the predicate is satisfied.
- `HOLD` - a known external/operator/evidence prerequisite is pending.
- `BLOCKED` - current evidence proves the transition cannot proceed.
- `UNKNOWN` - required evidence is missing, stale, malformed, timed out, or conflicting.
- `NOT_APPLICABLE` - explicitly declared by the repo profile, never inferred from absence.

Stable reason codes include at least:

```text
COLLECTOR_TIMEOUT
COLLECTOR_UNAVAILABLE
EVIDENCE_STALE
EVIDENCE_CONFLICT
GIT_HEAD_DRIFT
DIRTY_OPERATOR_CHECKOUT
HANDOFF_HASH_MISMATCH
HANDOFF_BASE_STALE
PR_HEAD_MISMATCH
REVIEW_STALE_HEAD
REVIEW_BLOCKING_FINDINGS
CI_STALE_HEAD
CI_REQUIRED_CHECK_FAILED
MERGE_NOT_PROVEN
RUNTIME_BUILD_MISMATCH
RUNTIME_EVIDENCE_STALE
NO_SAMPLE
AUTHORIZATION_REQUIRED
AUTHORIZATION_UNKNOWN
BOUNDARY_REFUSAL
```

### Stage model

```text
planned -> implemented -> exact_head_reviewed -> ci -> merged -> runtime_proven
```

Stages do not automatically imply later stages. `runtime_proven` is
`NOT_APPLICABLE` for non-runtime projects only when the profile declares that explicitly.

Key predicates:

- **planned:** parseable canonical plan, known risk, non-blocked plan state; approval is a
  separate fact;
- **implemented:** an exact implementation head/range is identified;
- **exact-head reviewed:** review attestation head equals the current implementation/PR
  head and has no unresolved ship-blocking verdict;
- **CI:** every profile-required check passed on that same head; no checks is not pass
  unless the profile explicitly declares CI not applicable;
- **merged:** PR merge state or Git ancestry proves the implementation head landed on the
  declared base;
- **runtime proven:** a fresh registered readback reports the expected deployed build
  identity and required runtime predicates. Empty evidence is `NO_SAMPLE`, not pass.

### Source precedence

Precedence is per domain, not global:

| Domain | Authoritative observation | Lower-authority context |
|---|---|---|
| Git/worktree | live local Git commands | plan or handoff prose |
| PR/CI | live `gh ... --json` response | cached PR links/status text |
| plan/risk | canonical repo plan/frontmatter | handoff summary |
| review | persisted exact-head attestation + packet identity | claims that review ran |
| runtime | registered read-only JSON readback | merged code, logs without build identity |
| authorization | explicit operator-owned artifact/input | SHA, memory, inferred chat wording |
| handoff | computed hash + verified live references | filename/date alone |

Conflicting eligible facts remain a conflict and force `UNKNOWN`; TruthDeck does not
silently choose a convenient source.

### Authorization ceiling in v1

V1 does not contain a signing or operator-identity system, so it cannot independently
prove a GO token. Authorization facts have three representational states:

- `REQUIRED` - policy says a separate operator token is needed;
- `ASSERTED_UNVERIFIED` - an explicit file/input claims a token, but TruthDeck cannot prove
  who issued it;
- `VERIFIED` - reserved for a future operator-owned verifier and never emitted by v1.

Consequently, R2/R3 authorization gates remain `HOLD` in v1 unless an independently
approved verifier is added later. This prevents an agent-authored file from granting the
agent its own authority.

## Collector contract

Every collector implements the same boundary:

```text
collect(scope, policy, deadline) -> CollectorResult(facts, diagnostics, elapsed_ms)
```

Requirements:

- explicit argv list; never `shell=True`;
- per-command and total deadlines from policy, with timeout preserved as evidence;
- bounded stdout/stderr; secrets redacted before persistence;
- no `.env`, credential-store, keychain, environment-dump, or broker endpoint reads;
- parser rejects unknown top-level schema when the profile marks it strict;
- nonzero exit, partial JSON, and missing expected target remain visible;
- collectors cannot write into application repos;
- runtime commands must be named in the registry and independently marked `read_only`;
- path placeholders are resolved without command substitution or glob execution.

Initial collectors:

1. `git`: HEAD/base/ancestry/status/worktrees/locks/unique commits/ownership.
2. `plan`: frontmatter, risk, status, linked plan path, related repos.
3. `github`: PR identity, draft/ready, head/base OIDs, checks, merge state.
4. `review`: implementation packet plus persisted reviewer attestation.
5. `handoff`: SHA-256, required sections, referenced paths/SHAs, live drift.
6. `runtime`: profile-owned, read-only JSON probes only.
7. `artifact`: JSON/Markdown evidence metadata and hashes; no arbitrary prose inference.

The review collector requires both paths explicitly (packet and reviewer output). It does
not scan directories for a convenient verdict. It validates the packet head, the required
`REVIEWED_HEAD`/transmission fields, verdict vocabulary, and the absence of unresolved
ship-blocking findings. It normalizes those inputs in memory; it does not create a second
review attestation authority.

## Registry and policy

`~/.truthdeck/registry.json` is user-owned configuration created from
`templates/truthdeck.registry.json.template` only when absent. It defines:

- named repo profiles and path templates;
- default base ref and whether CI/runtime are applicable;
- allowed collectors;
- named runtime probe IDs selected from the code-owned allowlist;
- TTLs and timeouts;
- task aliases mapping to explicit plan/repo/handoff paths;
- required stage gates.

Registry rules:

- schema-versioned and validated before any collector runs;
- paths may use a small documented placeholder set, never arbitrary environment expansion;
- user and repo registries may disable or narrow shipped probes, but cannot add argv,
  executables, modules, parser code, or broker/order capabilities;
- every executable argv lives in `truthdeck_profiles.py`, is reviewed as code, and has a
  contract test proving the referenced tool is read-only;
- installer preserves existing user configuration and writes a `.from-template` candidate
  when the template version advances;
- snapshot records the registry/policy digest;
- repo-local files may narrow collection but cannot enable mutation or broker/order access.

Initial profiles:

- `dotclaude-ecosystem`: generic Git/plan/GitHub/review, runtime not applicable;
- `tsu`: generic collectors plus `tools.tsu_remote_preflight --json` and named gate-status
  adapters; always read-only and DISARMED-safe;
- `tsignal-5.0`: generic collectors plus explicitly selected status/readback commands;
  no broker connect, arming, or order paths.

## Next-action algorithm

The selector is deterministic and policy-driven:

1. refuse on a boundary/security violation;
2. resolve identity conflicts and stale base/head evidence;
3. select the earliest required stage in `BLOCKED` or `UNKNOWN`;
4. otherwise select the earliest required stage in `HOLD`;
5. if all required stages pass, emit `ready_for_operator_review` with no execution;
6. attach risk, reversibility, required authorization, evidence keys, command preview when
   the preview is itself read-only, and explicit forbidden actions.

The selector never fabricates a repair command. When no registered safe action exists, it
asks for verification or operator direction.

## CLI contract

```text
truthctl snapshot         collect facts, evaluate gates, persist JSON, render summary
truthctl next             render the one selected action from a snapshot or live scope
truthctl verify-handoff   verify integrity, references, freshness, and authority separation
truthctl diff             compare two immutable snapshots by fact/gate/reason code
truthctl validate-registry
truthctl version
```

Output modes: human Markdown by default, `--json` for the canonical object, `--output`
for an explicit artifact copy, and `--no-store` for fixture/tests only. `--require`
accepts an explicit comma-separated stage list; omitted stages are still reported but do
not control the overall readiness exit code.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | requested gates `PASS`/`NOT_APPLICABLE`, or a non-gating validation succeeded |
| 2 | invalid input, registry error, or security/boundary refusal |
| 10 | overall state `HOLD` |
| 11 | overall state `BLOCKED` |
| 12 | overall state `UNKNOWN`/incomplete collection |
| 124 | total deadline exceeded before a valid snapshot could be sealed |

MCP returns the same state and reason codes as structured content instead of translating
them into a second status model.

## Storage and concurrency

- State root: `~/.truthdeck/` (neutral between Claude and Codex).
- Snapshots: `snapshots/<scope-slug>/<UTC>-<content-id>.json`.
- Human view: generated on demand; JSON is canonical.
- Each snapshot is immutable and created with exclusive-create semantics.
- A `latest.json` pointer is replaced atomically only after the snapshot validates.
- Concurrent agents never append to a shared mutable JSON document.
- Snapshot IDs derive from canonical content excluding observation timestamp and local
  output path; identical evidence can therefore be recognized without overwriting history.
- Retention is report-only in v1. No automatic deletion or pruning.

## MCP dependency decision

The core and CLI remain Python-stdlib-only. `truthdeck_mcp.py` is an optional adapter using
the official MCP Python SDK. At plan creation the workstation has `mcp 1.27.0`; the
official project documents v1.x as current stable and v2 as pre-release. Therefore:

```text
mcp>=1.27,<2
```

is pinned for this implementation. A separate compatibility slice may move to v2 only
after its stable release and migration tests. S5 must re-check the official stable release
before locking dependencies; if v2 has become stable, implementation pauses for an
explicit compatibility decision rather than silently using this dated pin. The server uses
stdio, four tools, and no network listener. Sources:

- https://github.com/modelcontextprotocol/python-sdk
- https://modelcontextprotocol.io/docs/develop/build-server

## Implementation slices

### S0 - Contract fixtures and threat model

**Files:** plan follow-up notes if needed, `docs/TRUTHDECK.md`, schema fixtures under
`scripts/tests/fixtures/truthdeck/`.

- freeze schemas, reason codes, exit codes, source precedence, and forbidden actions;
- create realistic fixtures for dirty worktrees, stale review/CI heads, runtime mismatch,
  `NO_SAMPLE`, malformed handoff, collector timeout, and conflicting sources;
- document the trust boundary and ensure fixture text is treated as inert input;
- capture a local latency baseline for Git-only and Git+GitHub collection.

**Gate:** fixtures and threat model reviewed before collector implementation.

### S1 - Deterministic core, storage, and renderer

**Files:** `truthdeck_model.py`, `truthdeck_storage.py`, `truthdeck_render.py`, tests.

- implement enums/dataclasses and strict `truthdeck.snapshot.v1` validation;
- implement canonical serialization, digests, exclusive immutable writes, atomic latest
  pointer, bounded Markdown, and snapshot diff;
- prove deterministic gate-input serialization and concurrent-writer safety.

**Gate:** no subprocesses or external dependencies; unit suite green.

### S2 - Generic collectors and policy registry

**Files:** collector, Git, GitHub, handoff, runtime modules; template registry; tests.

- reuse `git_hygiene` read logic without invoking its apply/deploy paths;
- add bounded GitHub JSON queries with fake-`gh` integration tests;
- add hash/reference handoff verification with no prose execution;
- add strict runtime JSON adapters that resolve only code-owned probe IDs;
- record every collector failure and freshness boundary.

**Gate:** hostile fixture pack proves no arbitrary execution, no application-repo writes,
and no false pass on partial evidence.

### S3 - Gate engine and `truthctl`

**Files:** `truthdeck_gates.py`, `truthctl.py`, tests and docs.

- implement independent lifecycle gates and deterministic next-action selection;
- implement all CLI commands and exit-code contract;
- support single- and bounded multi-repo scopes without inventing cross-repo authority;
- produce copy-paste examples and actionable errors (problem, cause, safe next check).

**Gate:** end-to-end CLI tests over temporary Git repos and fake PR/runtime surfaces.

### S4 - TSU and Tsignal profiles

**Files:** registry template/profile fixtures and contract tests only; no app-repo edits in
this slice unless a missing read-only JSON contract is separately planned in its owner repo.

- register TSU/Tsignal read-only status commands that already exist and return JSON;
- classify unsupported or unsafe probes as unavailable rather than shelling around them;
- prove merged-versus-runtime separation and DISARMED/no-order boundaries;
- compare TruthDeck output against manual live readback for at least one non-trading
  session in each profile.

**Gate:** exact same evidence yields the expected manual and TruthDeck verdict; any missing
repo-specific contract becomes a separate owner-repo task, not an inline workaround.

### S5 - Skill, MCP adapter, and installation

**Files:** `skills/truthdeck/SKILL.md`, `truthdeck_mcp.py`, requirements pin, installers,
installer/MCP tests.

- keep the skill thin: invoke CLI/MCP, preserve reason codes, never duplicate the global
  risk/workflow table;
- expose exactly four MCP tools over the tested core;
- copy the skill to Claude and Codex and install the shared CLI modules;
- add idempotent MCP registration with config backup, ownership marker, round-trip readback,
  and a removal path that deletes only TruthDeck-owned entries;
- discover and fixture-test the exact active Claude/Codex configuration schemas before the
  first registration write; unknown schema/version is a hard hold, not a best-effort edit;
- measure startup/tool-description cost before enabling the registration in active homes;
  if it breaches the agreed budget, ship CLI+skill enabled and keep MCP registration as an
  explicit installer switch while preserving the implemented adapter.

**Gate:** CLI/MCP parity tests, host launch smoke, and installer idempotency pass on Windows;
POSIX installer contract tests pass without requiring the operator's Windows paths.

### S6 - Exact-head closeout and landing

- run the full focused and repository test suites;
- generate the provider-neutral implementation review packet;
- obtain independent review of the exact current head and fix ship-blocking findings;
- batch the final push, ready the PR once, merge, and fast-forward the operator checkout;
- run one post-install self-snapshot proving TruthDeck can truthfully report its own merged
  versus installed state.

## Test plan

### Required behavioral matrix

| Scenario | Expected result |
|---|---|
| clean main equals origin, no PR required | Git facts pass; PR is explicit N/A only by profile |
| dirty operator checkout plus clean agent worktree | ownership visible; no switch/cleanup action proposed |
| draft PR, review of prior head | `REVIEW_STALE_HEAD`, not pass |
| green checks on prior head | `CI_STALE_HEAD`, not pass |
| merged code, stopped/stale runtime | merge pass; runtime `UNKNOWN`/`HOLD` |
| empty runtime sample | `NO_SAMPLE`, not pass |
| matching handoff hash on stale base | integrity pass; continuation hold |
| mismatched handoff hash | blocked with expected/actual hashes |
| `gh` missing/offline | collector unavailable; other facts preserved; overall unknown if required |
| runtime probe timeout | timeout visible; no cached green reuse beyond TTL |
| plan says shipped but Git disagrees | conflict surfaced; no silent precedence crossing |
| malicious handoff contains commands/instructions | content remains inert; nothing executed |
| output path contains spaces/Unicode | correct Windows behavior and canonical paths |
| two concurrent snapshot writers | two immutable artifacts; valid atomic latest pointer |
| MCP and CLI same request | identical normalized facts, gates, reason codes, next action |

### Validation commands

Implementation must end with exit-code evidence for:

```powershell
python -m pytest -q scripts/tests/test_truthdeck_model.py `
  scripts/tests/test_truthdeck_collectors.py `
  scripts/tests/test_truthdeck_gates.py `
  scripts/tests/test_truthdeck_cli.py `
  scripts/tests/test_truthdeck_mcp.py `
  scripts/tests/test_truthdeck_install.py

python -m pytest -q scripts/tests
python -m ruff check <all new/touched Python files>
python -m compileall -q <all new TruthDeck modules>
git diff --check
```

The existing 14 broad-suite Ruff findings are baseline debt. TruthDeck may not add to
them, and this plan may not silently clean them in unrelated files.

### Performance acceptance

S0 records the machine baseline. Initial budgets, adjustable only with recorded evidence:

- local Git/plan snapshot: <= 2 seconds at p95 over 20 fixture runs;
- GitHub-inclusive snapshot: <= 10 seconds when `gh` is healthy;
- individual external collector timeout: <= 5 seconds by default;
- rendered agent summary: <= 4,000 characters unless `--verbose`;
- MCP exposes exactly four tools and no large static resources at startup.

Performance failure does not permit dropping provenance or fail-closed behavior.

## Security and safety review

- Use subprocess argv arrays only; forbid `shell=True`, `eval`, dynamic imports, command
  templates, and command substitution.
- Runtime registry validation requires fixed executable/module prefixes and rejects paths
  outside the declared repo/tool roots.
- Do not ingest environment dumps, `.env`, secrets, credential files, keychains, broker
  endpoints, or raw order data.
- Redact before persistence. Store only normalized parsed facts plus bounded diagnostics;
  do not copy full raw command output into snapshots.
- Treat Markdown, JSON strings, PR bodies, issue text, handoffs, and logs as untrusted data;
  they cannot alter policy, registry, or tool instructions.
- Reject path traversal in default state storage and installer-owned outputs.
- The MCP process uses stdio only and inherits no application mutation capability.
- TSU/Tsignal profiles assert `no_broker`, `no_order_path`, and `read_only`; violation is
  `BOUNDARY_REFUSAL`, not a warning.

## Observability and failure behavior

Every collector run records collector ID/version, duration, exit status, timeout flag,
eligible fact count, redacted diagnostic, and source digest. The summary always includes:

- overall state and exit code;
- exact scope and current Git/PR identity;
- stage table;
- conflicts and stale evidence;
- one next action;
- required authorization and forbidden actions;
- canonical snapshot path and digest.

No error path prints a green headline. Error messages state problem, likely cause, and the
safe next verification command when one is registered.

## Activation and rollback

### Activation

1. Land the R1 implementation through the normal draft-PR lifecycle.
2. Install/copy the CLI and skill idempotently.
3. Run `truthctl validate-registry` and a generic self-snapshot.
4. Run TSU/Tsignal read-only profile smokes while DISARMED and without starting anything.
5. Register MCP only after CLI/MCP parity and startup-budget evidence pass.
6. Run a post-registration MCP snapshot and compare its digest to CLI output.

### Emergency off

- remove/disable only the TruthDeck MCP registration using its ownership marker;
- continue using CLI directly, or remove the installed wrapper/modules after hash match;
- revert the merged PR if core behavior is wrong;
- preserve snapshots for diagnosis by default.

Snapshot deletion is outside rollback and requires a separate explicit destructive action.

## Definition of Done

- [ ] Canonical `truthdeck.snapshot.v1` schema and reason-code registry are documented and tested.
- [ ] Core/CLI are dependency-free, deterministic, concurrent-safe, and Windows-first.
- [ ] Git, plan, GitHub, review, handoff, artifact, and allowlisted runtime collectors exist.
- [ ] Unknown/stale/conflict/timeout evidence cannot pass any required gate.
- [ ] Planned, implemented, exact-head reviewed, CI, merged, and runtime states remain distinct.
- [ ] One deterministic next action includes risk, reversibility, authorization, evidence,
      and forbidden actions.
- [ ] Handoff verification separates hash integrity from live freshness and permission.
- [ ] TSU/Tsignal profiles are read-only and prove no broker/order-path access.
- [ ] CLI and four-tool MCP adapter produce identical normalized results.
- [ ] Installer is idempotent, backs up host config, and removes only owned entries.
- [ ] Focused tests, full `scripts/tests`, scoped Ruff, compileall, and diff-check pass.
- [ ] Exact-head independent review has no unresolved ship-blocking findings.
- [ ] Draft PR is readied once, merged, and the operator checkout is fast-forwarded.
- [ ] A self-snapshot truthfully distinguishes repository merge from installed/MCP-active state.
- [ ] Documentation enables a new agent to produce its first snapshot in under five minutes.

## Author pre-mortem

1. **Second-source-of-truth failure:** mitigated by immutable observations, source digests,
   TTLs, and no mutable task database.
2. **Collector sprawl:** mitigated by a fixed protocol, registry allowlist, and three initial
   profiles only.
3. **False green on missing evidence:** mitigated by explicit `UNKNOWN`, reason codes, and
   nonzero exit statuses.
4. **Workflow duplication:** mitigated by advisory-only output and a thin skill/MCP layer.
5. **Startup tax:** mitigated by four tools, no resources/daemon, measured activation, and
   CLI parity as a complete fallback.
6. **Host-config damage:** mitigated by backup, ownership marker, idempotent round-trip tests,
   and surgical removal.
7. **Runtime boundary leak:** mitigated by explicit read-only profiles and hard refusal of
   broker/order-path commands.

## Plan exit gate

This owner plan is ready for the R1 workflow when all are true:

- plan file is committed in `dotclaude-ecosystem`;
- no unrelated user changes are staged or modified;
- `plan_context_updater.py` has been run and its inability to catalog this non-`D:/APPS`
  repo is reported truthfully;
- the operator chooses `/fwf` or `/fwp` for implementation review and execution.
