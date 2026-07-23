---
title: TruthDeck / truthctl - Agent Evidence Control Plane
date: 2026-07-22
status: in-progress
status_detail: r1-fwf-implemented-local-green-awaiting-exact-head-review
risk: R1
phase: r1-fwf-exact-head-review
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

1. **Application observation is read-only by default and by construction.** Collectors use
   explicit argv arrays, `shell=False`, bounded timeouts/output, and a command allowlist. No
   generic shell-command tool exists. TruthDeck may write only its own immutable snapshot
   store and installer-owned user-home entries; those writes are explicit, ownership-checked,
   reversible, and never occur inside an observed application repository.
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
scripts/truthdeck_install.py        surgical install/status/uninstall + host registration
scripts/tests/test_truthdeck_*.py   unit, integration, contract, security tests
skills/truthdeck/SKILL.md           thin routing/usage skill; no duplicate policy table
templates/truthdeck.registry.json.template
docs/TRUTHDECK.md
requirements-truthdeck-mcp.txt
.github/workflows/truthdeck-ci.yml  one draft-skipped Windows CI gate
```

`truthdeck_model.py` owns a versioned `FACT_KEYS` registry (key, JSON type, producer,
freshness class, eligibility semantics). Collectors and gates share it; registry policy may
reference only those keys.

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
COLLECTOR_OUTPUT_LIMIT
COLLECTOR_OUTPUT_INVALID
COLLECTOR_INTERNAL_ERROR
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
REGISTRY_INVALID
SNAPSHOT_INVALID
STORAGE_CONFLICT
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

Independent collectors run in a bounded stdlib thread pool (`max_workers <= 4`) against one
shared monotonic deadline. Results are validated and sorted by canonical repo order plus
collector ID before resolution, so completion order cannot affect the snapshot. A collector
that misses its remaining deadline is terminated and contributes an ineligible timeout fact;
it cannot delay sealing past the total deadline.

Requirements:

- explicit argv list; never `shell=True`;
- per-command and total deadlines from policy, with timeout preserved as evidence;
- bounded stdout/stderr; secrets redacted before persistence;
- subprocesses receive only a documented environment allowlist; environment values are
  never persisted, and an output-size breach terminates the collector with
  `COLLECTOR_OUTPUT_LIMIT`;
- no `.env`, credential-store, keychain, environment-dump, or broker endpoint reads;
- parser rejects unknown top-level schema when the profile marks it strict;
- nonzero exit, partial JSON, and missing expected target remain visible;
- collectors cannot write into application repos;
- runtime commands must be named in the registry and independently marked `read_only`;
- path placeholders are resolved without command substitution or glob execution.
- resolved repo, handoff, output, and tool paths are containment-checked after symlink/reparse
  resolution; a path escaping its declared root is a `BOUNDARY_REFUSAL`.

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
- the only optional repo-local narrowing file is `.truthdeck-policy.json`; its closed schema
  can intersect collector/probe sets, reduce TTLs/timeouts/deadlines, or add required stages,
  but cannot enable mutation, broker/order access, new fact keys, or arbitrary commands.

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
| 2 | invalid input, registry error, or unsupported schema/version |
| 3 | security or application-boundary refusal |
| 10 | overall state `HOLD` |
| 11 | overall state `BLOCKED` |
| 12 | overall state `UNKNOWN`/incomplete collection |
| 124 | total deadline exceeded before a valid snapshot could be sealed |

MCP returns the same state and reason codes as structured content instead of translating
them into a second status model.

When `next` or `diff` consumes stored snapshots, it re-evaluates freshness and gates in
memory at one explicit evaluation time. It never overwrites the sealed snapshot and never
replays an expired `PASS` as current truth.

## Storage and concurrency

- State root: `~/.truthdeck/` (neutral between Claude and Codex).
- Snapshots: `snapshots/<scope-slug>/<UTC>-<content-id>.json`.
- Human view: generated on demand; JSON is canonical.
- Each snapshot is immutable: write/flush/`fsync` a unique same-directory temporary file,
  validate its readback, then `os.replace` it to a process-unique final name. Readers ignore
  temporary files.
- `latest.json` records the target plus digest and is written with the same same-directory
  flush/replace/readback sequence only after the snapshot validates. Pointer failure leaves
  the sealed snapshot usable and the previous valid pointer intact when the filesystem
  honors same-directory atomic replacement.
- Concurrent agents never append to a shared mutable JSON document.
- Snapshot IDs derive from canonical content excluding observation timestamp and local
  output path; identical evidence can therefore be recognized without overwriting history.
- Artifact filenames add a process-unique, non-authoritative writer suffix after the UTC and
  content ID. Concurrent identical observations therefore keep two immutable artifacts while
  retaining the same semantic `snapshot_id`; the atomic latest pointer may select either
  digest-identical artifact.
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

**Files:** `skills/truthdeck/SKILL.md`, `truthdeck_mcp.py`, `truthdeck_install.py`,
requirements pin, bootstrap installers, installer/MCP tests.

- keep the skill thin: invoke CLI/MCP, preserve reason codes, never duplicate the global
  risk/workflow table;
- expose exactly four MCP tools over the tested core;
- copy the skill to Claude and Codex and install the shared CLI modules;
- use the dedicated TruthDeck installer for activation. The repository bootstrap installers
  may include TruthDeck for future full installs, but activation must not run their broad
  whole-home backup/copy flow;
- install a `truthctl` shim only into an existing user-owned directory already on `PATH`;
  otherwise report the canonical `python <installed>/truthctl.py` invocation and `HOLD` the
  bare-command smoke instead of mutating `PATH`;
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
- add/run the draft-skipped Windows TruthDeck CI workflow; no-checks is not a pass for this
  profile;
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
  scripts/tests/test_truthdeck_git.py `
  scripts/tests/test_truthdeck_github.py `
  scripts/tests/test_truthdeck_handoff.py `
  scripts/tests/test_truthdeck_storage.py `
  scripts/tests/test_truthdeck_render.py `
  scripts/tests/test_truthdeck_gates.py `
  scripts/tests/test_truthdeck_cli.py `
  scripts/tests/test_truthdeck_profiles.py `
  scripts/tests/test_truthdeck_runtime.py `
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
- total collection deadline: 15 seconds for one repo and 30 seconds for a bounded multi-repo
  request; profile and repo policy may only reduce these defaults;
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

- [x] Canonical `truthdeck.snapshot.v1` schema and reason-code registry are documented and tested.
- [x] Core/CLI are dependency-free, deterministic, concurrent-safe, and Windows-first.
- [x] Git, plan, GitHub, review, handoff, artifact, and allowlisted runtime collectors exist.
- [x] Unknown/stale/conflict/timeout evidence cannot pass any required gate.
- [x] Planned, implemented, exact-head reviewed, CI, merged, and runtime states remain distinct.
- [x] One deterministic next action includes risk, reversibility, authorization, evidence,
      and forbidden actions.
- [x] Handoff verification separates hash integrity from live freshness and permission.
- [x] TSU/Tsignal profiles are read-only and prove no broker/order-path access.
- [x] CLI and four-tool MCP adapter produce identical normalized results.
- [x] Installer is idempotent, backs up host config, and removes only owned entries.
- [x] Focused tests, full `scripts/tests`, scoped Ruff, compileall, and diff-check pass.
- [ ] Exact-head independent review has no unresolved ship-blocking findings.
- [ ] Draft PR is readied once, merged, and the operator checkout is fast-forwarded.
- [ ] A self-snapshot truthfully distinguishes repository merge from installed/MCP-active state.
- [x] Documentation enables a new agent to produce its first snapshot in under five minutes.

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

## CEO review record - Stage 1 `/fwf`

Review date: 2026-07-22. Mode: **HOLD SCOPE**. The R1 `/fwf` contract assigns
product/mechanical questions in this stage to the agent; the decisions below are therefore
resolved and binding for implementation. No product expansion was accepted.

### System audit and premise verdict

- Review baseline: `main == origin/main == 185163d47bc4bba61b89a23ecf9e43ddbd0128e3`;
  clean worktree; one unrelated pre-existing stash (`park generated operator playbook pdf`)
  remains untouched.
- The optional code-review graph is empty (`0` nodes, `0` files, never updated), so the
  review used bounded source reads of the exact existing scripts and workflow plans.
- No prior TruthDeck implementation, branch, handoff, or competing plan exists. The closest
  surfaces are `steer_context.py`, `/whatnext`, `git_hygiene.py`,
  `implementation_review_packet.py`, and `terminal_evidence.py`.
- The actual pain is repeated reconciliation of independently authoritative evidence. Doing
  nothing preserves stale-head, merged-versus-runtime, and handoff-freshness mistakes.
- Verdict: solve the problem as an evidence compiler, not as a workflow/database/agent
  runtime. TruthDeck must remain downstream of existing authorities.

Landscape check:

- Supply-chain systems such as [SLSA verification](https://slsa.dev/spec/v1.2/verifying-artifacts)
  and [in-toto attestations](https://in-toto.io/docs/specs/) confirm the useful pattern of
  claims plus provenance plus policy verification, but their package/build focus does not
  cover local Git/worktree/runtime/operator gates.
- [OpenTelemetry signals](https://opentelemetry.io/docs/concepts/signals/) are a strong model
  for correlated observations, but adopting a collector/backend/telemetry stack would violate
  the local-first, no-daemon MVP.
- [MCP security guidance](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)
  reinforces the decision to expose a fixed, static four-tool surface with no dynamic tool
  registration or generic execution.

### Approach decision

| Approach | Shape | Effort | Risk | Completeness | Decision |
|---|---|---:|---:|---:|---|
| A - CLI-only minimum | Git/plan/GitHub snapshot and `next`; defer profiles, MCP, installer | M | Low | 6/10 | Reject: does not prove cross-host parity or runtime separation |
| B - Modular compiler | Current plan: deterministic core, bounded collectors, CLI, thin skill, optional MCP | L | Medium | 9/10 | **Approved** |
| C - Evidence platform | daemon, plugin SDK, database, push events, UI | XL | High | 10/10 | Reject: creates a competing authority and runtime |

Approach B is intentionally modular even though it touches more than 15 files. The module
count separates trust boundaries (model, subprocess collection, profiles, gates, storage,
rendering, CLI, MCP); it is not permission to create one class per file or a generic plugin
framework. Keep data structures simple and collapse helpers when separation adds no security,
testability, or ownership value.

### Dream-state delta

```text
CURRENT                         THIS R1 PLAN                     12-MONTH IDEAL
manual evidence joins    ->     deterministic local compiler ->  shared stable evidence
stale claims possible           provenance + fail-closed         contract consumed by agents
workflow-specific prose         CLI + optional MCP parity         without a new authority
```

The plan reaches the durable contract and first three profiles. It deliberately does not
reach signed operator authorization, automatic remediation, UI, or a live aggregation
service.

### What already exists and must be reused

| Sub-problem | Existing surface | Reuse rule |
|---|---|---|
| plan frontmatter | `_catalog_common.parse_yaml_block` | reuse bounded parsing pattern; add strict TruthDeck validation |
| Git/worktrees | `git_hygiene` read functions | reuse reads only; never import/call apply/deploy paths |
| exact-head identity | `implementation_review_packet` | consume packet fields and digest; do not mint a second review authority |
| timeout/redaction/atomicity | `terminal_evidence` | reuse semantics or narrowly extracted helpers; no sensitive command execution |
| steering | `steer_context` and `/whatnext` | consume compact TruthDeck output later; no steering-policy duplication in v1 |
| workflow/risk routing | `master-agent` and `/fwf`/`/fwp` | observe persisted evidence only; never reproduce routing tables |
| installation | `install/install.ps1` and `install/install.sh` | extend existing copy flow and add surgical TruthDeck-owned config handling |

### Architecture review

```text
CLI or four fixed MCP tools
          |
          v
validated request + profile registry
          |
          +--> fixed generic collectors --> normalized facts
          +--> code-owned probe ID ------> normalized facts
                                             |
                                             v
                                  freshness/conflict resolver
                                             |
                                             v
                                  independent lifecycle gates
                                             |
                                  +----------+----------+
                                  v                     v
                          one next action       immutable snapshot

Forbidden dependency edges:
  observed repo --X--> TruthDeck writes
  handoff prose --X--> policy/authorization
  MCP input -----X--> arbitrary argv/tool registration
  merged Git ----X--> inferred runtime proof
```

State transitions are computed, not mutated:

```text
planned -> implemented -> exact_head_reviewed -> ci -> merged -> runtime_proven
   |            |                 |               |       |             |
   +------------+-----------------+---------------+-------+-------------+
        each stage independently yields PASS/HOLD/BLOCKED/UNKNOWN/N_A

Invalid shortcut: any earlier PASS => later PASS
Prevention: later predicates require their own eligible exact-identity facts.
```

For multi-repo requests, each fact and gate is namespaced by canonical repo ID. The overall
next action is the first failing required gate in the request's explicit repo order. No gate
in repo A can satisfy repo B, and cross-repo aggregation creates no new authorization.

Single points of failure are `gh`, local Git, registered runtime probes, the registry, and
the snapshot store. Failure of any one is represented as evidence; it is never converted to
a green fallback. Rollback is a Git revert plus ownership-checked uninstall, normally under
five minutes, with snapshots retained.

### Four-path data flow

```text
HAPPY: request -> validate -> collect -> normalize -> gate -> seal -> render
NIL:   missing optional input -> explicit N_A/default from profile, never inferred PASS
EMPTY: command succeeds with empty target -> NO_SAMPLE / OUTPUT_INVALID -> UNKNOWN
ERROR: timeout/nonzero/malformed/conflict -> diagnostic fact -> non-PASS gate -> safe next check

INPUT -> schema/type/path validation -> allowlisted collection -> normalized facts
  |             |                         |                    |
  | nil/type    | escape/reparse          | timeout/limit      | conflict/stale
  v             v                         v                    v
reject/N_A   BOUNDARY_REFUSAL      collector reason code  UNKNOWN + provenance
```

Binding edge decisions:

- Use an injectable UTC clock in tests; freshness at exactly `fresh_until_utc` is stale.
- Canonical JSON uses UTF-8, sorted keys, compact separators, finite JSON values only, and no
  platform-dependent path casing in digests after canonical path normalization.
- `--require` rejects unknown, empty, duplicate-after-normalization, and out-of-order stage
  tokens; omitted stages remain visible.
- A valid empty result is distinct from missing output. Profile predicates decide whether an
  empty collection is `NO_SAMPLE` or an expected zero-value observation.
- Raw untrusted Markdown/JSON fields never enter rendered Markdown without length bounding
  and control-character escaping.

### Error and rescue registry

| Codepath | Failure | Specific boundary/result | Rescue action | User sees |
|---|---|---|---|---|
| request/registry parse | invalid JSON/schema/type | `RegistryError` / `REGISTRY_INVALID` | stop before collectors | invalid field and safe correction |
| path resolution | traversal, symlink/reparse escape | `BoundaryError` / `BOUNDARY_REFUSAL` | refuse request | declared root and rejected path |
| bounded subprocess | missing executable | `FileNotFoundError` / `COLLECTOR_UNAVAILABLE` | preserve other facts | unavailable collector |
| bounded subprocess | deadline exceeded | `subprocess.TimeoutExpired` / `COLLECTOR_TIMEOUT` | terminate process, retain bounded diagnostic | timeout and probe ID |
| bounded subprocess | stdout/stderr cap exceeded | `OutputLimitError` / `COLLECTOR_OUTPUT_LIMIT` | terminate process | limit and collector ID |
| collector parser | nonzero, empty, malformed or wrong schema | `CollectorOutputError` / `COLLECTOR_OUTPUT_INVALID` | mark required facts ineligible | exact parser reason |
| fact resolver | eligible sources disagree | `EVIDENCE_CONFLICT` result | retain both digests | conflict, never winner-by-convenience |
| snapshot validation | invariant/schema violation | `SnapshotValidationError` / `SNAPSHOT_INVALID` | do not persist/latest | invalid invariant |
| immutable create | filename collision or partial write | `FileExistsError`/`OSError` / `STORAGE_CONFLICT` | retry writer suffix; otherwise fail closed | storage failure |
| latest pointer | atomic replace fails | `OSError` / `STORAGE_CONFLICT` | keep sealed snapshot, leave prior pointer | snapshot path plus pointer warning |
| GitHub | auth/offline/rate/unknown JSON | collector-specific unavailable/invalid | no implicit cached pass | GitHub evidence unknown |
| handoff | hash/reference mismatch | explicit mismatch reason | no continuation verdict | expected/actual digest or stale ref |
| top-level CLI/MCP | unexpected internal defect | `COLLECTOR_INTERNAL_ERROR` at narrow boundary | no traceback in normal output; diagnostic ID and nonzero status | internal error, never green |

Unexpected exceptions may be caught only at the CLI/MCP isolation boundary to prevent a host
crash; tests and verbose local mode retain the exception chain. Collector implementations
must catch only named operational exceptions and add collector/scope context.

### Failure modes registry

| Codepath | Failure mode | Rescued? | Test? | User sees? | Logged/persisted? |
|---|---|---:|---:|---:|---:|
| registry | user injects arbitrary argv | yes/refused | required | `BOUNDARY_REFUSAL` | yes |
| subprocess | child hangs or floods output | yes/terminated | required | timeout/output-limit | yes, bounded |
| resolver | fresh sources conflict | yes/unknown | required | both sources/digests | yes |
| review/CI | evidence belongs to prior head | yes/non-pass | required | stale-head reason | yes |
| runtime | merged head but no build/sample | yes/non-pass | required | mismatch/`NO_SAMPLE` | yes |
| handoff | valid hash but stale base | yes/hold | required | integrity pass + freshness hold | yes |
| storage | concurrent identical writers | yes/unique artifacts | required | valid path | yes |
| latest pointer | replacement fails after seal | yes/degraded | required | warning + sealed artifact | yes |
| rendering | hostile Markdown/control text | yes/escaped | required | inert bounded text | yes |
| MCP | adapter/core result drift | yes/gate failure | required | parity failure | test artifact |

No accepted row remains with `Rescued=no`, `Test=no`, and silent user impact.

### Security and threat review

| Threat | Likelihood | Impact | Required mitigation |
|---|---:|---:|---|
| registry/CLI command injection | Medium | High | probe IDs only, fixed argv, `shell=False`, reject unknown keys |
| path traversal/symlink escape | Medium | High | post-resolution root containment on every read/write path |
| prompt injection in handoff/PR/log | High | High | inert data model, escaping, no semantic permission extraction |
| secret persistence | Medium | High | source allowlist, redact before store, bounded diagnostic fixtures |
| output-memory exhaustion | Low | High | streaming byte cap plus deadline and child termination |
| app-repo mutation by collector | Low | High | no collector output path in app repo; before/after dirty-state contract tests |
| host config damage | Low | Medium | schema discovery, backup, ownership marker, atomic replace, surgical removal |
| dynamic MCP surface drift | Low | Medium | exactly four static tools, no `tools/list_changed`, no network listener |
| self-issued authorization | Medium | High | v1 never emits `VERIFIED`; authorisation stays independent |

There are no new credentials. GitHub uses the operator's existing `gh` session without
reading or persisting credential material. TSU/Tsignal probes remain DISARMED-safe and may
not connect to broker/order surfaces.

### Code quality review

- Preserve one public model and one evaluator path shared by CLI and MCP; adapters may not
  translate reason codes or recompute readiness.
- Do not import mutation-capable `git_hygiene.main`, `do_apply`, or `do_deploy`; reuse only
  pure read helpers or extract a narrow read-only helper with regression tests.
- Prefer frozen dataclasses/enums and plain functions. No repository class hierarchy, event
  bus, service locator, dynamic import, or plugin base class.
- New functions with more than five decision branches must be split around validation,
  collection, normalization, and evaluation phases rather than suppressed from lint.
- Version schema and policy separately. Unknown major versions fail closed; additive unknown
  fields are accepted only where the schema explicitly allows them.

### Test review

```text
NEW UX: CLI snapshot/next/verify-handoff/diff/validate/version; four MCP calls
NEW DATA: request -> collectors -> facts -> resolver -> gates -> snapshot/render
NEW BRANCHES: five gate states; stale/conflict/timeout/empty/mismatch/N_A
ASYNC: none; concurrent filesystem writers only
EXTERNAL: git, gh, code-owned JSON probes, local filesystem
ERRORS: every row in Error and rescue registry
```

Required additions beyond the original matrix:

- exact TTL boundary with injectable clock and timezone/naive timestamp rejection;
- huge output terminates at the byte cap; child cleanup is proven on Windows;
- symlink/reparse and Unicode path containment; reserved-device/path traversal rejection;
- `latest.json` replace failure leaves the sealed snapshot valid and prior pointer intact;
- canonical digest remains stable across key order and Windows separator/case normalization;
- malformed/unknown registry major version runs zero subprocesses;
- multi-repo gate namespaces cannot cross-satisfy and request order determines one action;
- hostile Markdown/control characters render inertly under 4,000 characters;
- no app-repo writes, before/after status identical, for every shipped profile fixture;
- installer rollback refuses an ownership-hash mismatch;
- hostile QA test: fake `gh` returns success plus wrong-head checks and a command-looking PR
  body; result is stale/unknown and executes nothing;
- chaos test: simultaneous timeout, stale GitHub fact, pointer replace failure, and one healthy
  Git fact still yields a valid non-green sealed snapshot when storage itself is usable.

Test pyramid: many deterministic units, bounded fake-executable integration tests, a few CLI
and host-launch smokes, and no network-dependent test in the required local suite.

### Performance review

Likely slow paths are Git worktree enumeration, `gh` JSON calls, and runtime probes. They run
under a shared total deadline with per-collector deadlines; deterministic output order must
not depend on completion order. Bound repository count, fact count, diagnostic bytes,
subprocess output, and rendered characters in policy. Do not add cache-derived PASS in v1.
The existing p95 budgets remain acceptance gates; report the machine and sample count with
the measurements.

### Observability and debuggability review

The immutable snapshot is the operational trace. Every collector record includes start/end
timing, code-owned ID/version, exit/timeout/output-limit state, eligible fact count, and
redacted digest. CLI `--verbose` may expose bounded diagnostics, but normal output gives a
diagnostic ID, exact snapshot path, and reason codes. No daemon means no alert/dashboard is
required; a runbook table in `docs/TRUTHDECK.md` maps every stable reason code to a safe
verification step.

### Deployment, rollback, and interaction sequence

```text
branch -> local tests -> draft PR -> exact-head review -> ready once -> CI -> squash merge
   -> fast-forward operator checkout -> ownership-checked install -> self-snapshot

rollback decision
   +-- adapter only wrong -> remove owned MCP entry -> CLI remains
   +-- install wrong -----> restore timestamped host-config backup
   +-- core wrong --------> revert merged PR -> reinstall prior tracked version
   `-- snapshots ---------> retain for diagnosis (deletion needs separate explicit request)
```

Old and new code do not run simultaneously as a service. Activation writes only TruthDeck's
own user-home files after repository merge. MCP registration remains opt-in if startup/tool
description measurement breaches the plan budget. Post-install proof must report repository
merged, CLI installed, skill installed, MCP registered/disabled, and runtime profile evidence
as separate facts.

### Long-term trajectory

Reversibility: **5/5**. The main path dependency is the snapshot schema, so golden fixtures
and explicit version negotiation are mandatory. A future signing/authorization verifier,
UI, or shared store must consume snapshots as a separate project; none is anticipated inside
v1 abstractions. The architecture becomes a platform only through a stable evidence contract,
not through dynamic collectors.

### Design and UX review

Skipped: no graphical UI scope. CLI information order is deliberate: overall non-green
state, scope/identity, stage table, conflicts/staleness, one next action, authorization and
forbidden actions, then artifact identity. Markdown output must remain useful in both plain
PowerShell and agent context.

### NOT in scope

- signed operator identity/GO verifier - separate trust and key-management design;
- automatic repair or workflow execution - would violate advisory ownership;
- daemon/database/event bus/cloud sync - no demonstrated MVP need;
- GUI/EcosystemControl panel - wait for repeated operator demand after CLI use;
- generic collector plugins or repo-executed code - unacceptable command surface;
- global plan-loader path refactor - useful but unrelated to evidence compiler delivery;
- automatic snapshot retention/deletion - destructive policy needs separate approval;
- OpenTelemetry, SLSA, or in-toto dependency adoption - patterns inform the schema, not MVP dependencies.

### Temporal decisions resolved before implementation

| Phase | Decision now frozen |
|---|---|
| foundation | schema, clock, canonical JSON, exception/reason mapping, byte/time/path bounds first |
| core | gates consume eligible normalized facts only; no collector-specific truth logic |
| integration | fake executables and code-owned probe IDs; no app imports or config writes |
| polish | install/MCP are adapters over proven CLI core and can be disabled independently |
| closeout | self-snapshot is evidence of install state, not proof of app runtime or permission |

### Implementation tasks synthesized from CEO review

- [x] **T1 (P1, human ~2h / Codex ~15m)** - core contract - implement canonical model,
  injectable clock, strict validation, stable reason codes, and independent gates.
  - Surfaced by: architecture/data-flow review.
  - Files: `scripts/truthdeck_model.py`, `scripts/truthdeck_gates.py`, tests.
  - Verify: canonical/TTL/state-transition unit matrix.
- [x] **T2 (P1, human ~3h / Codex ~20m)** - collector boundary - implement byte/time/path
  bounds, fixed argv/probe IDs, redaction, and named failure mapping.
  - Surfaced by: error/security review.
  - Files: collector, Git, GitHub, handoff, profile/runtime modules, tests.
  - Verify: hostile fake-executable and no-write contract suite.
- [x] **T3 (P1, human ~2h / Codex ~15m)** - storage/render - make concurrent immutable
  artifacts, atomic latest degradation, safe bounded Markdown, and deterministic diff.
  - Surfaced by: storage collision and hostile rendering findings.
  - Files: `scripts/truthdeck_storage.py`, `scripts/truthdeck_render.py`, tests.
  - Verify: concurrent writers, replace failure, digest and hostile-text tests.
- [x] **T4 (P1, human ~2h / Codex ~15m)** - CLI/profile integration - implement commands,
  repo namespaces, one-action selection, and read-only TSU/Tsignal profile contracts.
  - Surfaced by: interaction/multi-repo review.
  - Files: `scripts/truthctl.py`, profile fixtures, docs, tests.
  - Verify: temporary-repo E2E and DISARMED/no-order boundary tests.
- [x] **T5 (P2, human ~2h / Codex ~15m)** - host adapters - add thin skill, exact four-tool
  MCP parity, and ownership-checked idempotent install/uninstall.
  - Surfaced by: deployment/security review.
  - Files: skill, MCP adapter, requirements, installers, installer tests.
  - Verify: parity, schema-discovery hold, backup/round-trip/ownership mismatch tests.
- [ ] **T6 (P1, human ~1h / Codex ~10m)** - closeout - run full validation, exact-head
  independent review, single paid CI transition, merge/sync, and post-install self-snapshot.
  - Surfaced by: deployment and Definition of Done.
  - Files: evidence artifacts and terminal plan status only.
  - Verify: commands in the validation section plus exact SHA/readback evidence.

No new `TODOS.md` item is created: all P1/P2 findings are necessary in-scope controls, and
all rejected expansions are explicit non-goals rather than deferred commitments.

### CEO completion summary

| Review area | Result |
|---|---|
| Mode and approach | HOLD SCOPE; modular compiler approved |
| System audit | clean baseline; no implementation collision; graph unavailable/empty |
| Architecture | downstream evidence compiler; forbidden edges explicit |
| Errors | 12 codepath classes mapped; 0 critical silent gaps |
| Security | 9 threats mapped; no broker/order/app mutation capability |
| Data/edge cases | four paths plus clock/path/concurrency/multi-repo rules frozen |
| Code quality | simple modules; no plugin/service hierarchy |
| Tests | hostile, chaos, Windows, parity, no-write additions required |
| Performance | bounded time/output/counts; original p95 budgets retained |
| Observability | immutable snapshot plus reason-code runbook |
| Deployment | draft/one-ready/CI/merge/install/self-snapshot; surgical rollback |
| Long term | reversible 5/5; schema is the only intentional platform seam |
| Design | skipped; no UI scope |
| Scope proposals | 0 proposed, 0 accepted, 0 deferred |
| Unresolved decisions | 0 |

## R1 audit synthesis - Stage 2 `/fwf`

Audit topology completed on 2026-07-22 in `free` mode with GPT synthesis. OpenRouter free
and Kimi CDP succeeded; Perplexity CDP, Gemini CDP, and Claude CLI failed visibly in
`_auditf_meta.json`. The reduced panel lowers confidence but does not hide missing lanes.

### Findings applied

1. **Snapshot replay freshness (consensus P2).** `truthctl next --snapshot` never replays a
   sealed `PASS` as current truth. It re-derives fact eligibility, gates, and next action in
   memory at `evaluated_at_utc` (default: current injected clock), without mutating the sealed
   file. Human/JSON output carries both `sealed_at_utc` and `evaluated_at_utc`. Tests may pin
   `--at <RFC3339>` for deterministic replay. `truthctl diff` compares sealed values and also
   reports freshness transitions after evaluating both snapshots at one common `--at` time.
2. **Review-attestation input (unique valid P2).** V1 does not claim that the current review
   workflow automatically persists an attestation. The review collector accepts only two
   explicit caller-supplied paths: the existing `implementation-review/v1` packet and the raw
   reviewer result. The S0 fixture freezes required reviewer tokens, verdict vocabulary, and
   `REVIEWED_HEAD`; there is no directory scan or synthetic authority file. Missing either
   path makes `exact_head_reviewed=UNKNOWN`. S6 persists the exact external result as workflow
   evidence before invoking TruthDeck.
3. **Governed fact keys and source normalization (consensus P2).** Add a code-owned,
   versioned fact-key registry containing key, JSON type, producer, freshness class, and
   eligibility semantics. Gates may reference only registered keys; unknown policy keys are
   `REGISTRY_INVALID`. S0 golden fixtures freeze the per-collector field selection, null
   handling, ordering, path normalization, and canonical JSON used for `evidence_sha256`.
4. **Registry and policy schema (consensus P2).** The stdlib validator has explicit required
   fields, closed objects, enum/value bounds, unknown-major refusal, and zero-subprocess
   behavior on failure. `policy_digest_sha256` covers the effective registry schema version,
   profile ID, enabled collectors, code-owned probe IDs, TTLs/timeouts/deadline, required
   stages, optional repo narrowing file, and fact-key registry version. It excludes local
   output paths and observation/timing fields.
5. **Stable repository identity (consensus P2).** `repo_id` is the profile ID plus normalized
   origin owner/repo when available; otherwise it is `local:` plus a digest of the canonical
   Git common directory. Worktrees share `repo_id` and carry a separate local `checkout_id`.
   Windows casing, separators, spaces, Unicode, and reparse resolution are fixture-tested.
6. **GitHub compatibility (consensus P2/P3).** Record `gh --version`; request an explicit
   field list; missing/null required fields are `COLLECTOR_OUTPUT_INVALID`, never false-y
   values. Bound GitHub calls per snapshot and fail closed on auth, rate, version, or schema
   drift.
7. **Storage atomicity precision (valid P2).** Write a unique temporary file in the target
   snapshot directory, flush and `fsync`, validate by readback, then `os.replace` it to the
   unique final name. Readers ignore temporary files. The latest pointer uses the same-dir
   temp/flush/replace/readback sequence and stores target plus digest. Concurrent writers are
   last-valid-pointer-wins; pointer failure never invalidates a sealed snapshot. No lock or
   cross-filesystem rename is required or permitted.
8. **Read-only Git reuse boundary (valid P2).** TruthDeck reuses `git_hygiene` behavior, not
   the mutation-capable module surface. `truthdeck_git.py` contains a narrow read-only adapter
   for status, ancestry, common-dir, worktrees, locks, and unique commits. Static contract
   tests reject imports/references to `do_apply`, `do_deploy`, mutation-capable application
   modules, dynamic imports, or shell execution.
9. **Total deadline and machine-visible refusal (valid P3).** Default total collection
   deadline is 15 seconds for a single repo and 30 seconds for a bounded multi-repo request;
   profiles may only narrow it. Local-only p95 remains a performance acceptance target, not
   a forced 2-second kill. Exit code `3` is reserved for `BOUNDARY_REFUSAL`; code `2` remains
   invalid input/registry/schema. Exit `124` means no valid snapshot could be sealed before
   the total deadline.
10. **Version and context edges (valid P3).** Cross-major snapshot diff/replay hard-refuses;
    collector-run timing/duration and observation timestamps are excluded from semantic
    content IDs; a caller-supplied handoff digest is described as meaningful integrity proof
    only when sourced independently from the handoff author; and the only optional repo-local
    narrowing path is `.truthdeck-policy.json`, with closed schema and deterministic
    intersection/minimum-only merge semantics.

### Findings discarded

- Concurrent-writer corruption, missing multi-repo ordering, missing path normalization, and
  ambiguous timeout/output reason mapping were based on pre-CEO-plan content; the reviewed
  plan already defines writer suffixes, atomic pointer degradation, explicit repo ordering,
  containment rules, and named reason mapping.
- A base class/plugin interface for collectors is rejected. A typed `Protocol` plus result
  validation is sufficient and does not create a dynamic extension surface.
- Automatic cache reuse, circuit breakers, a daemon performance monitor, network-home special
  behavior, and filesystem scanning for recovery are out of scope. Fail-closed diagnostics
  and a new explicit snapshot are the v1 recovery path.
- Fixing `plan_context_loader.py` for `D:/dotclaude` is unrelated; TruthDeck receives explicit
  repo/plan paths and implements its own bounded scope resolver.
- Import-time `sys.modules` policing is brittle. Static AST/import contract tests and the
  absence of application-repo paths from production modules enforce the intended boundary.

## Engineering review record - Stage 3 `/fwf`

Review date: 2026-07-22. Mode: **FULL_REVIEW**. The `/fwf` contract auto-resolves R1
engineering questions. The prior CEO complexity decision is upheld: proceed with the modular
compiler, but keep one core model/evaluator and no generic plugin framework.

### Step 0 scope and distribution decision

- Existing stdlib-only surfaces were verified directly: `_catalog_common.py`,
  `git_hygiene.py`, `terminal_evidence.py`, and `implementation_review_packet.py` import only
  Python standard-library modules.
- More than eight files is justified by trust-boundary separation and focused tests. Reducing
  to a monolith would couple subprocess security, policy, storage, gates, and host config.
- TruthDeck is distributed as tracked Python files plus a dedicated installer, not a package
  index artifact or compiled binary. Windows is the activation platform; POSIX receives
  contract-tested CLI/skill installation without active-home assumptions.
- Official recheck: MCP Python SDK v1 remains stable and v2 remains pre-release; latest v1 is
  `1.27.2`, while the workstation has `1.27.0`. The existing `mcp>=1.27,<2` range remains the
  correct compatibility contract.

### Architecture findings and decisions

1. **[P1] (confidence 10/10) No CI gate exists for a plan whose lifecycle requires CI.**
   Motivating plan text: `design/plans/...r1.md:1051` says `ready once -> CI -> squash merge`,
   while the repository has no `.github/` directory. Decision: add
   `.github/workflows/truthdeck-ci.yml`, run only on non-draft PRs and TruthDeck-relevant
   paths, use Windows + Python 3.12, install pytest/Ruff/MCP v1, run the full `scripts/tests`
   suite plus scoped TruthDeck Ruff/compileall. No push-to-main duplicate run.
2. **[P1] (confidence 10/10) The broad bootstrap installer is unsafe as the activation
   path.** `install/install.ps1:19` and `install/install.sh:20` copy the whole Claude home to
   a timestamped backup; lines 27/28 then copy every Python script. Decision: implement
   `truthdeck_install.py` with `status/install/uninstall`, a TruthDeck-only manifest, per-file
   hash ownership, targeted backups, atomic host-config edits, and rollback on partial failure.
   The broad installers only learn the new tracked skill for future full bootstrap use.
3. **[P1] (confidence 9/10) The documented `truthctl` command had no distribution path.**
   The plan invokes `truthctl snapshot` at line 134, but existing installers only copy `.py`
   files. Decision: the dedicated installer places a tiny hash-owned shim only in an existing
   user directory already on `PATH`; otherwise docs/readback use the explicit Python entry
   point and report bare-command activation as `HOLD`.
4. **[P2] (confidence 9/10) Independent collectors need bounded concurrency to meet the
   stated latency.** The plan requires GitHub-inclusive p95 <=10 seconds while multiple
   external collectors each allow five seconds. Decision: one `ThreadPoolExecutor`, maximum
   four workers, shared monotonic deadline, deterministic result sorting, no async/event loop.
5. **[P2] (confidence 9/10) MCP registration must use host-specific ownership seams.** Live
   schema inspection found Codex TOML `mcp_servers` entries with command/args shapes and Claude
   CLI support for user-scoped `mcp add/get/remove`. Decision: Claude registration uses its
   official CLI plus readback; Codex uses a closed, marker-delimited TOML block only after
   `tomllib` validation and absence/ownership checks. Unknown shape or existing foreign
   `truthdeck` entry is a hard hold. Each mutation has a targeted backup and post-write parse.

### Code quality findings and decisions

1. **[P1] (confidence 10/10) `git_hygiene.py` mixes read and mutation functions.** The file
   contains `analyze` plus `do_apply` and `do_deploy`; importing its high-level surface would
   make the boundary review-dependent. Decision: copy/extract only the small Git read
   primitives into `truthdeck_git.py`, with AST tests that reject mutation symbols and
   application-repo imports.
2. **[P2] (confidence 8/10) Optional MCP must not infect core imports.** Decision:
   `truthdeck_mcp.py` is the only module allowed to import `mcp`; every core/CLI test runs when
   MCP is absent, while parity/host-smoke tests install the bounded optional requirement.
3. **No further issue:** frozen dataclasses, plain functions, code-owned fact/probe registries,
   and one evaluator are right-sized. No class hierarchy, package build, daemon, cache, or DB.

### Test coverage diagram

```text
ENTRY / MODULE                         REQUIRED BEHAVIOR COVERAGE
truthdeck_model.py
  +-- registry/fact/snapshot parse     [PLANNED ***] valid + nil + empty + unknown + wrong type
  +-- canonical JSON/digests           [PLANNED ***] order/path/time exclusion + golden fixtures
  `-- freshness replay                 [PLANNED ***] before/at/after TTL + pinned --at

truthdeck_collectors.py
  +-- bounded process success          [PLANNED ***] stdout/stderr/env/provenance
  +-- missing/nonzero/malformed        [PLANNED ***] named non-PASS reason
  +-- timeout/output cap               [PLANNED ***] Windows terminate/kill + no orphan
  `-- shared deadline/concurrency       [PLANNED ***] stable order + late result ineligible

git/github/review/handoff/runtime
  +-- clean/dirty/worktrees/identity    [PLANNED ***] local + remote + common-dir worktrees
  +-- PR/check exact head               [PLANNED ***] draft/null/offline/rate/stale/no checks
  +-- packet + reviewer result          [PLANNED ***] missing/token/vocabulary/head mismatch
  +-- handoff digest/references          [PLANNED ***] independent hash + stale base + inert text
  `-- code-owned probes                 [PLANNED ***] strict JSON + no broker/order/app writes

truthdeck_storage/render/gates
  +-- temp/fsync/replace/readback        [PLANNED ***] crash residue + pointer degradation
  +-- concurrent writers                [PLANNED ***] two artifacts + one valid latest pointer
  +-- safe bounded Markdown/diff         [PLANNED ***] Unicode/control/hostile/cross-version
  `-- lifecycle and next action          [PLANNED ***] all 5 states/reasons + repo/stage ordering

truthctl.py
  +-- six command surfaces              [PLANNED ***] human/JSON/output/no-store/require
  `-- exit contract                     [PLANNED ***] 0/2/3/10/11/12/124

MCP/install/CI
  +-- exactly four MCP tools             [PLANNED ***] CLI/core parity + missing SDK
  +-- install/status/uninstall           [PLANNED ***] idempotent/backup/foreign ownership/rollback
  +-- Claude/Codex schemas               [PLANNED ***] fixture + live readback without secrets
  `-- non-draft Windows CI               [PLANNED ***] expected suite actually runs on PR head

USER FLOWS
  snapshot -> next                       [PLANNED -> INTEGRATION]
  verify handoff -> stale-base hold       [PLANNED -> INTEGRATION]
  stale review/check -> exact-head block  [PLANNED -> INTEGRATION]
  install -> status -> self-snapshot      [PLANNED -> SYSTEM]
  install partial failure -> rollback     [PLANNED -> SYSTEM]
```

No implementation exists yet, so coverage is planned rather than claimed. Every branch above
must have behavior + edge + named failure coverage. No LLM eval is needed; prompt files and
model behavior are not changed. The existing `unittest`-style tests collected by pytest remain
the house style.

### Test findings and decisions

1. **[P1] (confidence 10/10) The original focused command omitted first-class modules.** The
   module layout names Git, GitHub, handoff, storage, render, profiles, and runtime modules,
   while the command listed only model/collectors/gates/CLI/MCP/install tests. Decision: add
   explicit test files for every module to the focused command and keep full
   `python -m pytest -q scripts/tests` as the regression gate.
2. **[P1] (confidence 9/10) CI must prove the expected target ran.** Decision: tests assert
   schema/fact/reason registries are non-empty and enumerate the four MCP tool names; CI logs
   the exact pytest target and uses a check name required by the dotclaude profile.
3. **[P2] (confidence 8/10) Host config tests cannot touch active homes.** Decision: all
   mutation tests use temporary fake Claude/Codex homes. Exactly one post-merge smoke may use
   active homes, after status/readback and backup, under the approved installation scope.

### Performance findings and decisions

1. **[P2] (confidence 8/10) Output caps must be memory-safe, not post-capture checks.** Use
   `Popen` with same-host temporary output files, poll size plus monotonic deadline, terminate
   on cap, then read only the bounded prefix. This avoids unbounded `capture_output=True`.
2. **[P2] (confidence 8/10) GitHub calls must be bounded.** One `gh pr view --json` call per
   repo collects PR identity and `statusCheckRollup`; no polling and no automatic retry in a
   snapshot. Rate/auth/schema failure remains visible and non-green.
3. **No cache:** repeated collection may cost another `gh` call, but cache-derived current
   truth is a larger correctness risk. The immutable prior snapshot remains available for
   explicit offline inspection, never as a current PASS.

### Failure modes and user visibility

All production failures map to the CEO error/failure registries. Engineering review adds:

| Failure | Test | Handling | User visibility |
|---|---:|---|---|
| CI workflow absent/not triggered | yes | PR cannot satisfy CI gate | missing check / UNKNOWN |
| foreign MCP entry named truthdeck | yes | installer hard hold, no overwrite | owner mismatch |
| host CLI unavailable/denied | yes | CLI/skill install may proceed; MCP hold | host and command named |
| shim target not already on PATH | yes | no PATH mutation; Python entry remains | activation HOLD |
| output temp file exceeds cap | yes | terminate, discard raw temp, seal non-green fact | OUTPUT_LIMIT |
| collector finishes after deadline | yes | ignore late eligible facts | TIMEOUT/deadline |

Critical silent gaps: **0**.

### Worktree parallelization strategy

| Lane | Work | Depends on | Conflict note |
|---|---|---|---|
| A | S0 fixtures -> S1 model/storage/render -> S3 gates/CLI | none | owns shared schemas/core |
| B | collector runner -> Git/GitHub/review/handoff adapters | S0 fact/reason contract | merges into A before CLI E2E |
| C | profile discovery/runtime contracts -> skill/MCP/dedicated installer/CI | S0 registry contract; MCP waits for core API | installer lists all final modules |

Lanes B and early C discovery can proceed independently after S0, but the main implementation
keeps schema/core ownership in Lane A and validates each merge point. Do not split edits to
`truthdeck_model.py`, `truthdeck_profiles.py`, or installer manifests across concurrent lanes.

### Engineering implementation tasks

- [x] **E1 (P1, human ~2h / Codex ~15m)** - freeze schemas, fact/probe registries,
  canonicalization, clock, and golden hostile fixtures before production collectors.
- [x] **E2 (P1, human ~4h / Codex ~30m)** - build model, bounded runner, adapters, storage,
  renderer, gates, and CLI with the full branch matrix above.
- [x] **E3 (P1, human ~2h / Codex ~15m)** - add read-only TSU/Tsignal candidate probes only
  when existing commands satisfy the static contract; otherwise emit unavailable facts.
- [x] **E4 (P1, human ~3h / Codex ~20m)** - build four-tool MCP adapter and dedicated
  hash-owned installer with fake-home rollback tests and non-mutating status.
- [x] **E5 (P1, human ~1h / Codex ~10m)** - add the draft-skipped Windows CI gate and prove
  focused/full/scoped-lint/compile/diff checks locally before readying once.
- [ ] **E6 (P1, human ~1h / Codex ~10m)** - exact-head review, fixes, merge/sync, active-home
  install/readback, and TruthDeck self-snapshot.

No new TODO is created. Package publication, GUI, signing, daemon/cache, and workflow
integration remain explicit non-goals. The engineering test-plan artifact is stored under the
local gstack project directory; JSONL aggregation was skipped because `jq` is unavailable.

### Engineering completion summary

| Area | Result |
|---|---|
| Scope | accepted as-is; modular trust boundaries retained |
| Architecture | 5 issues found and resolved; dedicated installer + CI added |
| Code quality | 2 issues resolved; optional dependency isolated |
| Tests | full path diagram; 3 gaps resolved in plan |
| Performance | 2 issues resolved; no cache accepted |
| Failure modes | 6 additions; 0 critical silent gaps |
| Parallelization | 3 dependency-gated lanes; shared core kept single-owner |
| Outside voice | Stage 2 audit already supplied; no duplicate panel |
| Unresolved decisions | 0 |

## Implementation record - Stage 4 `/fwf`

Implementation completed on `codex/truthdeck-r1` against base
`185163d47bc4bba61b89a23ecf9e43ddbd0128e3`. The delivered surface contains the
stdlib-only model/CLI, bounded concurrent collectors, immutable store, deterministic gates
and renderer, fixed TSU probe allowlist, explicit unavailable Tsignal runtime profile,
four-tool MCP adapter, hash-owned installer, thin skill, operator documentation, and a
draft-skipped Windows CI workflow.

The first implementation head `d2003e1` was invalidated by the blocking review gate. Three
exact-head specialist passes found 18 unique security, correctness, and test-contract issues.
The repair set now binds executable probes to canonical repo identities and code hashes,
honors collector/check allowlists, preserves healthy results at deadlines, rejects stale or
conflicting evidence, makes install/MCP changes transactional and ownership-checked, adds
strict task aliases, and emits separate read-only installation/skill/MCP facts for the final
self-snapshot. `d2003e1` is not accepted as reviewed evidence.

The next candidate `b9f31f5` was also invalidated: a fail-soft external `/fwf` panel had one
complete Gemini lane and three partial OpenRouter model artifacts while Claude, Perplexity,
Kimi, and one OpenRouter aggregate lane failed or timed out. Triage rejected path/type false
positives but confirmed one P2: timeout cleanup terminated only the direct process despite the
plan requiring no orphaned descendant. The repair creates a process group/session, terminates
the Windows/POSIX process tree, and proves a grandchild cannot write after timeout. External
output for `b9f31f5` is diagnostic only and is not accepted as a PASS attestation.

Candidate `d08353f` received a complete independent Poolside Laguna M.1 exact-head PASS with
zero ship-blocking findings, and TruthDeck's own review gate accepted that packet/result pair.
The same self-check then exposed a separate integration blocker before CI: the bounded Windows
environment omitted non-secret host config paths (`APPDATA`/`LOCALAPPDATA`), so a child `gh`
process could not find the already-authenticated GitHub CLI keyring. `d08353f` is therefore
superseded despite the review PASS. The repair allows only config-location variables (including
portable `HOME`/`XDG_CONFIG_HOME`/`GH_CONFIG_DIR`) while a regression proves unrelated secret
environment variables remain absent. The repaired live collector then exposed a second fail-open
bug before readying: required checks treated GitHub `SKIPPED` and `NEUTRAL` conclusions as passing,
so the draft-skipped workflow falsely satisfied CI. Required checks now pass only on conclusion
`SUCCESS` (or legacy status-context `state=SUCCESS` when no conclusion exists), with regression
coverage for skipped, neutral, failure, and contradictory payloads.

The first `ready_for_review` transition on PR #41 remained `SKIPPED` because the workflow used
GitHub's default `pull_request` activity set, which excludes `ready_for_review`. The workflow
now declares `opened`, `synchronize`, `reopened`, and `ready_for_review` explicitly while its
job-level draft guard remains fail-closed. A contract test pins both clauses. Because the PR
was already ready, this repair is batched into one validated follow-up push, which supplies the
single `synchronize` CI run and requires a new exact-head review before merge.

After PR #41 merged, active-home installation correctly activated the CLI, both discovery
skills, and both MCP registrations, but runtime readback exposed a false-positive shim state:
the first home-owned PATH entry was an ephemeral `~/.codex/tmp/arg0/...` directory. A bounded
R1 follow-up restricts shim installation to durable `~/.local/bin` or `~/bin` entries already
present in PATH, reports `HOLD` when neither exists, and transactionally removes a prior owned
shim when migrating to a durable target. Fake-home tests cover preference, migration, cleanup,
and ephemeral-only refusal before active-home reinstall.

Follow-up exact-head model attempts were fail-closed when they truncated before a verdict. One
partial Cohere analysis identified a valid portability gap: the migration test expected the
Windows-only `truthctl.cmd` name. The test now derives the platform shim contract, and PATH
normalization strips surrounding whitespace/quotes before resolving durable entries. A separate
regression covers quoted durable paths; an alleged Windows case-sensitivity issue was discarded
because `WindowsPath` equality is already case-folded.

PR #42's first ready CI run then found a Windows runner representation-only failure: the
temporary home was expressed with the `RUNNER~1` short alias while the installer correctly
returned the resolved long path. The product behavior was unchanged; the migration assertion
now compares canonical `resolve()` paths. This single test-only fix is the sole follow-up push
to the ready PR and invalidates the previous exact-head review as required.

Boundary decision: `tools/autotrader_live_runtime_port_readback.py` was rejected as a
Tsignal runtime probe because its CLI writes JSON and Markdown into the application repo.
TruthDeck therefore reports Tsignal runtime evidence unavailable until a separately reviewed
stdout-only readback exists. The TSU allowlist contains only the existing
`tsu_remote_preflight.py --json` and `tsu_next_gate_status.py --json` tools, whose source
contracts are explicitly read-only and broker/order-path free.

Local evidence at implementation checkpoint:

- focused TruthDeck suite: `71 passed`;
- full `scripts/tests`: `173 passed, 2 subtests passed`;
- 50 consecutive concurrent-storage stress runs: PASS;
- scoped Ruff, `compileall`, and `git diff --check`: PASS;
- local Git/plan snapshot benchmark over 20 runs: p95 `1.9281s`, max `2.1221s`;
- MCP server construction over 20 runs: p95 `0.0137s`, max `0.0292s`, exactly four tools.

The exact-head review, PR CI/merge, operator-checkout sync, active-home installation, and
post-install self-snapshot remain Stage 6 evidence gates; local green status does not imply
any of them.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | HOLD_SCOPE, 0 critical gaps |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | PENDING | exact-head implementation review pending |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 12 issues/gaps resolved, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | N/A | no UI scope |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | N/A | not required by R1 workflow |

- **CROSS-MODEL:** R1 audit completed with 2/5 lanes; 10 valid contract amendments applied,
  stale/duplicative findings discarded, and no boundary-breaking P1 remained.
- **VERDICT:** IMPLEMENTED + LOCAL VALIDATION PASS - exact-head review and landing pending.

NO UNRESOLVED DECISIONS
