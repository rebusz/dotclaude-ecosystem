# audit topology — Synthesis (`free` mode)

**Plan**: `2026-07-22_truthdeck_agent_evidence_control_plane_r1.md`
**Run date**: 2026-07-22
**Lanes**: openrouter_free, perplexity_cdp (FAILED), gemini_cdp (FAILED), kimi_cdp, claude_cli (FAILED)
**OpenRouter basket**: free roster ($0 API spend)

---

## Instructions for the synthesizer

Synthesize the 5 audits below (OpenRouter free basket + Perplexity/Gemini/Kimi/frontier lanes). For each finding:

1. **Consensus P1** — appears in 2+ audits -> MUST fix, apply to plan immediately.
2. **Unique P1/P2** — only 1 model flagged but architecturally valid -> apply if it fits frozen boundaries.
3. **Discard** — P3 style noise, contradictions with frozen boundaries, hallucinated requirements -> skip.

For each item to apply: state the **plan heading**, the **change**, and the **reason**.
Red lines: never override frozen boundaries; never touch Tsignal execution path without R3 gate.

---

## 01_kimi_k3_swarm_max

# Audit - Kimi K3 Swarm Max (CDP)

Target: `2026-07-22_truthdeck_agent_evidence_control_plane_r1.md`  
Model: `kimi/k3-swarm-max`  
Source: `kimi_cdp`  
Tokens: `unknown-web-ui`  
Latency: 155.0s

---

Repo access limitation: No GitHub connector or filesystem access in this lane; the plan lives in D:/dotclaude/dotclaude-ecosystem, so its stated baselines (main == 36a2882d… at authoring, 185163d4… at CEO review, 102 passing tests, 14 pre-existing Ruff findings, empty code-review graph) are unverifiable here. This audit is from the document alone. Note also that per the GSTACK table, the required Eng Review (Stage 3 of /fwf) is still pending — this external audit does not substitute for it.
Design Audit — TruthDeck / truthctl Agent Evidence Control Plane (R1, post-CEO-review)
Overall verdict: No P1 blockers. The plan is disciplined: the frozen invariants, authorization ceiling, per-domain precedence, forbidden dependency edges, and dual error/failure registries are exactly the right skeleton for an evidence compiler downstream of existing authorities. The CEO review genuinely hardened it (TTL boundary, chaos test, ownership-hash uninstall, digest canonicalization). The remaining findings are contract-precision gaps that will surface as ambiguities in S0–S3, plus a few presentation/operational risks. Nothing contradicts frozen ecosystem boundaries.
1. Architectural soundness
F1 — P2 — The review collector consumes an artifact nobody is contracted to produce. (§Collector contract: "requires both paths explicitly (packet and reviewer output)"; §Source precedence: "persisted exact-head attestation")
The collector validates REVIEWED_HEAD, transmission fields, verdict vocabulary, and absence of unresolved ship-blocking findings — a good, strict contract. But the ecosystem's review flow transmits reviewer output in conversation; no component is designated to persist a versioned attestation file at a canonical location, and the reuse table only says "do not mint a second review authority." Result: exact_head_reviewed will be structurally UNKNOWN in the common case, which is fail-closed but makes the plan's headline pain point ("exact-head review can silently become stale") unfixable in practice. Additionally, the "verdict vocabulary" and "ship-blocking findings" parsing depends on the unversioned reviewer-output format — pin that vocabulary to a named, versioned contract (e.g., implementation-review/v1 reviewer section) in S0 fixtures.
F2 — P3 — Repo identity vs. repo path is not pinned. (§CEO review: "namespaced by canonical repo ID"; §Storage: snapshots/<scope-slug>/)
"Canonical repo ID" is used but never derived: registry profile name? canonical path? Both? On Windows with D:/APPS/Tsignal 5.0 (space, casing) and multiple worktrees of one repo, cross-snapshot diff stability and gate namespacing depend on this choice. Specify the derivation (registry profile ID keyed to canonicalized path, worktrees mapped to parent repo identity) in the S0 contract freeze.
F3 — P3 — Exit code 2 conflates operator error with security refusal. (§CLI contract › Exit codes)
"invalid input, registry error, or security/boundary refusal" sharing code 2 means calling automation cannot distinguish a typo from a BOUNDARY_REFUSAL (which the threat model treats as a High-impact event worth visibility). Give boundary refusals their own class (e.g., 3); the reason-code is in the JSON, but the exit-code contract is the machine-readable surface the plan itself emphasizes.
2. Data contracts — schema, freshness, provenance, versioning, replay
F4 — P2 — truthctl next --snapshot on an aged snapshot has undefined freshness semantics. (§CLI contract; §Data contract)
Facts carry fresh_until_utc, but gates are computed at seal time and persisted as verdicts. Rendering next from a 6-hour-old snapshot either (a) replays sealed verdicts — can present a stale PASS; (b) re-evaluates TTLs against the current clock — weakens the "byte-stable" determinism claim in a way that must be declared; or (c) refuses past an age bound. The plan picks none. Related gap: because snapshot_id excludes observation timestamp, truthctl diff of two snapshots of identical evidence taken 6 hours apart shows zero delta while freshness meaning changed — staleness transitions are invisible to the diff contract. Decide (b) or (c), render sealed-at/evaluated-at, and make fact-state re-derivation part of the diff output.
F5 — P2 — No governed fact-key registry; gate policy can silently drift from collector semantics. (§Data contract: "stable key"; §Registry: "required stage gates")
Gates reference fact keys; collectors mint them; collector_runs records collector ID/version and the snapshot records policy digest — but the semantics of a key (type, eligibility rule, producer) are unversioned. A collector update plus registry edit can change gate meaning while every recorded digest still verifies. Add a code-owned, versioned fact-key table (name, type, producer, eligibility semantics) with contract tests; unknown key in policy ⇒ REGISTRY_INVALID.
F6 — P3 — Determinism claim needs an explicit digest boundary for timing fields. (§Invariants #10; §Observability: "start/end timing, duration")
collector_runs includes durations, which are nondeterministic. The "identical evidence can therefore be recognized" property holds only if elapsed/timing fields are excluded from the content digest as "declared observation metadata." Say so explicitly in the schema, or the byte-stability invariant is untestable.
F7 — P3 — evidence_sha256 normalization is unspecified per collector. (§Data contract)
Cross-machine digest stability requires the normalization spec (field selection, ordering, null/whitespace handling) to live in the S0 golden fixtures, not in implementation code. The CEO review froze canonical-JSON rules for snapshots; extend them to source payloads.
F8 — P3 — Cross-schema-version truthctl diff undefined. (§CLI contract; §Long-term trajectory)
The plan names the snapshot schema as the one intentional platform seam but doesn't state v1-vs-v2 diff behavior. Cheapest honest contract: hard refuse with a clear message. One line now, painful retrofit later.
3. Trading-system safety (advisory vs. execution authority)
F9 — No finding; strongest section of the plan. The advisory/execution boundary is airtight: invariant 8's forbidden verb list; the authorization ceiling making self-issued GO structurally impossible (VERIFIED never emitted by v1); TSU/Tsignal profiles asserting no_broker/no_order_path/read_only with BOUNDARY_REFUSAL rather than warning; handoff/memory excluded from authority; activation step 4 ("DISARMED and without starting anything") ensuring probes never start or arm a runtime. Fully consistent with the frozen order-path change-control boundary; nothing here blurs advisory vs. execution.
F10 — P3 — Handoff --sha256 <expected> provenance is circular unless independently sourced. (§User journeys › Verified handoff continuation)
A hash supplied by the same agent that received the handoff proves only self-consistency. Invariant 5 (handoff is context, never authority) contains the blast radius, so this is not a safety hole — but the journey text should state that a meaningful integrity check requires the expected digest from an operator-owned channel, else verify-handoff reports integrity against the caller's own claim.
F11 — P3 — Name the S4 seed probe set. (§Registry › Initial profiles)
The TSU probe (tools.tsu_remote_preflight --json) is named; Tsignal's "explicitly selected status/readback commands" are not. S4's gate (missing contracts become owner-repo tasks, not inline workarounds) is the right discipline; naming candidate probe IDs now prevents quiet expansion to "whatever returns JSON."
4. Edge cases — stale data, partial data, degraded mode, operator visibility
F12 — P3 — Total deadline has no default value. (§CLI contract: exit 124 "total deadline exceeded"; §Performance acceptance: per-collector ≤ 5s)
Per-collector budgets are set; the total deadline that triggers 124 is not. With N collectors × 5s plus git worktree enumeration, specify the total default and its relationship to the 10s GitHub-inclusive p95 budget (a 5s gh timeout inside a 10s p95 budget is coherent only if the total exceeds both — state it).
F13 — P3 — Wall-clock trust in production freshness. (§CEO review: injectable clock is test-only)
TTL judgments trust the workstation clock. Record a clock-sanity diagnostic (e.g., divergence between system time and latest committer timestamp beyond a bound) so skew becomes visible evidence rather than silent misjudgment.
F14 — P3 — gh field-level drift. (§Collector contract)
Specify that absent/null expected fields in gh --json output are COLLECTOR_OUTPUT_INVALID, never false-y pass, and record the gh version in collector_runs (only collector ID/version is currently mandated).
F15 — P3 — Chronic-conflict fatigue. (§Source precedence: conflicts force UNKNOWN)
Correct fail-closed behavior, but the designed-common divergence (handoff prose vs. live Git) will fire often; operators habituate to non-green. The observability contract already separates conflicts in the summary — add a presentation distinction between expected context divergence and true evidence conflict in S3 rendering. Presentation only; do not weaken the gate.
Covered well: TTL exact-boundary (stale at fresh_until_utc), NO_SAMPLE vs. empty, stale review/CI heads, hostile Markdown/control chars, byte-cap child termination proven on Windows, symlink/reparse/Unicode/reserved-device containment, concurrent-writer exclusivity with writer suffix, latest-pointer replace failure degradation, chaos test yielding valid non-green seal, no green headline on any error path.
5. Integration risks — WatchF / Tsignal / TsignalLAB / Obsidian Flow
F16 — P3 — Consumer-side contract for /whatnext/steer_context deferred without an anchor. (§Reuse map)
Deferral is correct (no workflow competition), but nothing records the intended consumption shape (read latest.json for a declared scope vs. invoke truthctl next). One line in docs/TRUTHDECK.md (S0) prevents a later ad-hoc integration pattern. WatchF/TsignalLAB/Obsidian Flow have zero boundary contact here — that absence is correct and should be listed explicitly under §NOT in scope (currently only implied by "three initial profiles").
F17 — P3 — Repo-local narrowing files: merge semantics unpinned. (§Registry rules: "repo-local files may narrow collection")
Location, schema, and precedence vs. the user registry are undefined. Policy digest preserves determinism forensically, but two agents resolving different effective policy for one scope will diverge without an obvious explanation. One path, one schema, narrow-only merge rule — add to S0.
6. Quant usefulness (evidence-signal analog)
F18 — N/A as a trading surface; the noise/double-counting analogs are handled by design. Domain-separated stages prevent merged-code double-counting as runtime proof; per-domain precedence prevents silent source substitution; handoff/memory exclusion removes the "stale context as authority" noise channel. Residual noise risk is F15 (conflict fatigue). Runtime probes against a live Tsignal instance are read-only status reads with DISARMED-safe contract tests — no execution-path contact, no probe-induced load concern worth gating.
TOP 3 CHANGES
Contract the review-attestation artifact before S2 (F1). Either designate the existing review workflow as the owner of a persisted, versioned attestation file (path, format, verdict vocabulary pinned in S0 fixtures), or declare exact_head_reviewed = UNKNOWN the expected steady state where no attestation path is registered. Without this, the plan's central differentiator — killing stale-head review mistakes — is structurally inert.
Freeze snapshot-consumption freshness semantics (F4 + F6). Decide whether truthctl next --snapshot re-evaluates TTLs against the current clock (recommended: re-derive fact eligibility, render sealed-at/evaluated-at, and surface staleness transitions in diff), and explicitly exclude timing/duration fields from the content digest as declared observation metadata. This makes invariants #2 and #10 jointly testable instead of implicitly in tension.
Govern the fact-key namespace and normalization (F5 + F7 + F2). Add to the S0 contract freeze: a versioned, code-owned fact-key registry with contract tests; per-collector evidence_sha256 normalization specs as golden fixtures; and a pinned canonical-repo-ID derivation. These are one-page decisions now and breaking schema changes later — and they are what make the recorded policy/source digests actually meaningful over time.

---

## 02_nemotron3_super

# Audit — Nemotron 3 Super 120B (free)

Model: `nvidia/nemotron-3-super-120b-a12b:free`  
Tokens: 17,597  
Latency: 36.2s  
Quality: DEGENERATE — cot_leak, truncated_mid_sentence  
Packet Context: none; model=nvidia/nemotron-3-super-120b-a12b:free

---

We are given a detailed implementation plan for TruthDeck/truthctl. We must audit it against the criteria:

1. Architectural soundness
2. Threading/async safety
3. Edge cases
4. Cost/performance
5. Integration risks
6. Underspecified areas

We must grade each finding as P1 (blocker), P2 (important), or P3 (nice-to-have) and end with a "TOP 3 CHANGES" section.

Let's go through the plan and note any issues.

First, note that the plan is very detailed and seems well thought out. However, we must look for potential problems.

### Architectural soundness

The architecture is described as having a clear separation of concerns: collectors, normalization, gate evaluation, next-action selection, storage, and rendering. The use of a registry for profiles and policy is good.

However, note that the plan states: "Keep top-level Python modules under `scripts/` because both current installers copy `scripts/*.py` into `~/.claude/scripts/`." This might be acceptable, but we should check if there are any issues with having the code in `scripts/` and then copying to the user's home. It might lead to versioning issues if the user has multiple versions, but the plan does not specify how versioning is handled.

One potential issue: the plan mentions that the core and CLI are dependency-free (stdlib-only) except for the optional MCP adapter. However, the plan also mentions reusing existing scripts like `git_hygiene.py`, `plan_context_loader.py`, etc. We must ensure that these existing scripts are also dependency-free and do not introduce any external dependencies that would break the stdlib-only goal.

Looking at the existing scripts (as per the plan):
- `scripts/_catalog_common.py`
- `scripts/git_hygiene.py`
- `scripts/implementation_review_packet.py`
- `scripts/terminal_evidence.py`
- `scripts/plan_context_loader.py` / `plan_catalog.py`
- `scripts/steer_context.py`

We are not given the content of these, but the plan says they are being reused. We must assume they are safe and do not introduce external dependencies. However, if any of these scripts have external dependencies (like `requests` for GitHub), then the TruthDeck core would not be stdlib-only. The plan does not explicitly state that these reused scripts are stdlib-only.

But note: the plan says for the GitHub collector: "add bounded GitHub JSON queries with fake-`gh` integration tests". This implies that the GitHub collector will use the `gh` CLI (via subprocess) and not a Python library. Similarly, the runtime collectors use code-owned probe IDs that are resolved to executables. So the reuse of existing scripts might be for helper functions that are pure Python and stdlib-only.

However, we must check the existing `git_hygiene.py` and `terminal_evidence.py` for any external dependencies. Since we don't have the code, we rely on the plan's statement that they are being reused for read-only functions and that the collectors use explicit argv arrays and bounded timeouts.

Given the plan's emphasis on stdlib-only for the core and CLI, and the fact that the MCP adapter is optional and uses an external SDK (but only for the MCP adapter), we can assume that the reused scripts are also stdlib-only. But this is an assumption.

Another architectural point: the plan says "No module may import an application repo." This is good for isolation.

### Threading/async safety

The plan does not explicitly mention threading or async. However, it does mention concurrent writers to the snapshot store and how they are handled (by creating immutable artifacts with unique suffixes and an atomic latest pointer). The plan states:

- "Concurrent agents never append to a shared mutable JSON document."
- "Each snapshot is immutable and created with exclusive-create semantics."
- "A `latest.json` pointer is replaced atomically only after the snapshot validates."

This suggests that the design is safe for concurrent access from multiple processes (since it's using file system operations that are atomic on modern OSes). However, note that the plan does not mention any use of threads or async within a single process. The collectors are run via subprocess (so they are separate processes) and the main process is likely single-threaded.

But what about the MCP server? The plan says the MCP server uses stdio and four tools, and no network listener. It does not specify if the MCP server is threaded or async. However, since it's using stdio and the official MCP Python SDK, we must check if the SDK uses threading or async. The plan does not specify.

However, the plan does state that the core and CLI are dependency-free (stdlib-only) and the MCP adapter is optional. The MCP adapter is only used when the MCP server is enabled. The plan does not require the MCP server to be threaded or async, but if it is, we must ensure safety.

Given that the plan does not mention any threading or async in the core logic, and the collectors are subprocess-based, the main process is likely single-threaded. Therefore, threading safety might not be a concern. However, we should note that the plan does not explicitly rule out the use of threads or async in the future, but for v1 it seems to be synchronous.

### Edge cases

The plan has a thorough section on error and rescue registry and failure modes registry. It covers many edge cases such as:

- Boundary violations (path traversal, symlink escape)
- Collector timeouts, output limits, internal errors
- Evidence conflicts, stale evidence
- Snapshot validation and storage conflicts
- MCP adapter/core result drift

The plan also includes a test plan that requires testing these edge cases.

However, one edge case that might be missing: what happens when the user's home directory (where `~/.truthdeck` is stored) is on a network drive with high latency or intermittent connectivity? The plan does not specify how the tool behaves in such scenarios. It might lead to timeouts or storage conflicts.

Another edge case: the plan uses UUIDs or content-derived IDs for snapshot IDs. What if two different scopes produce the same content-derived ID? The plan says: "Snapshot IDs derive from canonical content excluding observation timestamp and local output path; identical evidence can therefore be recognized without overwriting history." This implies that the ID is a hash of the canonical content (without timestamp and output path). So if two different scopes produce the same canonical content (which is unlikely but possible if the scopes are different but the facts are the same), then they would have the same snapshot ID. However, the plan also says that the snapshot ID is used in the filename along with a UTC timestamp and a process-unique suffix. So even if the content-derived ID is the same, the full filename would be different because of the UTC and the suffix. The `latest.json` pointer is per scope-slug, so it would be scoped.

But note: the plan says "snapshot_id" is content-derived and excludes observation timestamp and local output path. So two snapshots from different scopes but with the same facts (and same policy, etc.) would have the same snapshot_id. However, the scope is part of the snapshot (in the `scope` field). So the full snapshot content would differ because of the scope. Therefore, the snapshot_id (which is a hash of the entire snapshot content excluding the timestamp and output path) would be different because the scope is included. So it should be safe.

However, the plan does not explicitly state what is included in the canonical content for the snapshot_id. We must assume it includes the scope, facts, gates, etc., but excludes the `observed_at_utc` and the local output path (which is not stored in the snapshot). This is acceptable.

### Cost/performance

The plan sets performance budgets:

- local Git/plan snapshot: <= 2 seconds at p95 over 20 fixture runs;
- GitHub-inclusive snapshot: <= 10 seconds when `gh` is healthy;
- individual external collector timeout: <= 5 seconds by default;
- rendered agent summary: <= 4,000 characters unless `--verbose`;
- MCP exposes exactly four tools and no large static resources at startup.

These seem reasonable. However, note that the plan does not specify how the performance will be measured or what machine is used for the baseline. But it does say that S0 records the machine baseline.

One potential performance issue: the plan says that the core is deterministic and that given identical normalized facts and policy, the results are byte-stable. However, the plan does not mention any caching. This is good because it avoids stale caches, but it might lead to repeated computation. However, since the tool is meant to be run on demand and the collection is bounded, it should be acceptable.

Another point: the plan says "Do not add cache-derived PASS in v1." This is explicit and good.

### Integration risks

The plan integrates with existing tools (Git, GitHub via `gh`, plan files, review packets, handoffs, and runtime probes). It also integrates with the user's home directory for storage and the MCP adapter for Claude and Codex.

Potential integration risks:

1. **GitHub**: The plan uses the `gh` CLI. This requires that the `gh` CLI is installed and authenticated. The plan does not specify what happens if `gh` is not installed or not authenticated. However, the collector for GitHub would return `COLLECTOR_UNAVAILABLE` or `COLLECTOR_OUTPUT_INVALID` (if it fails to authenticate) and then the gate would be `UNKNOWN` or `BLOCKED` as appropriate. This is covered by the error registry.

2. **Runtime probes**: The plan says that runtime probes are code-owned and allowlisted. The installer must ensure that the probes are present and executable. If a probe is missing, the collector would return `COLLECTOR_UNAVAILABLE`.

3. **MCP adapter**: The plan states that the MCP adapter is optional and uses the official MCP Python SDK. The plan pins the version to `mcp>=1.27,<2`. However, if the user has a different version of the MCP SDK installed, it might cause conflicts. The plan does not specify how the MCP adapter handles version conflicts. It might be better to vendor the MCP SDK or use a more flexible versioning strategy, but the plan explicitly pins the version and says that if v2 becomes stable, they will pause for a compatibility decision. This is acceptable.

4. **Installer**: The plan says the installer is idempotent and backs up host configuration. However, we must check if the installer handles the case where the user already has a `~/.truthdeck` directory from a previous installation. The plan says: "installer preserves existing user configuration and writes a `.from-template` candidate when the template version advances". This seems to handle upgrades.

5. **Path handling**: The plan emphasizes path containment checks after symlink/reparse resolution. This is important for security and correctness on Windows, where paths can be tricky.

### Underspecified areas

Looking through the plan, I notice a few areas that might need more detail:

1. **Clock injectability**: The plan mentions using an injectable UTC clock in tests, but it does not specify how this is done in production. We assume that in production it uses the system clock, but we should confirm that the design allows for injection (e.g., via dependency injection) to facilitate testing.

2. **Policy digest**: The snapshot includes a `policy_digest_sha256`. The plan does not specify what constitutes the policy. Is it the registry? The gate definitions? We must know what is hashed to produce this digest to ensure that changes in policy are reflected.

3. **Registry schema validation**: The plan says the registry is schema-versioned and validated before any collector runs. However, we are not given the schema for the registry. We must know what fields are allowed and what the validation rules are to ensure that the registry cannot be misused to introduce dangerous configurations.

4. **Exact definition of "read-only" for runtime probes**: The plan says runtime probes must be named in the registry and independently marked `read_only`. However, we are not given how this `read_only` mark is enforced. Is it a convention? Or is there a mechanism to check? The plan says: "every executable argv lives in `truthdeck_profiles.py`, is reviewed as code, and has a contract test proving the referenced tool is read-only". This suggests that the allowlist in `truthdeck_profiles.py` is the source of truth and that each entry is reviewed. This is acceptable, but we must ensure that the contract tests are comprehensive.

5. **Handling of empty plan or handoff files**: The plan does not specify what happens if a plan file is empty or malformed. The plan collector would likely fail to parse and return an error, which would be captured as `COLLECTOR_OUTPUT_INVALID` or similar. This is covered by the error registry.

6. **Multi-repo scope**: The plan says that for multi-repo requests, each fact and gate is namespaced by canonical repo ID. However, we are not given how the canonical repo ID is generated. We must ensure that it is stable and unique to avoid collisions.

7. **The `--require` flag**: The plan says that `--require` accepts an explicit comma-separated stage list. We must know what happens if an invalid stage is given. The plan says: "`--require` rejects unknown, empty, duplicate-after-normalization, and out-of-order stage tokens". This is good, but we must ensure that the implementation does so.

8. **The `truthctl diff` command**: The plan says it compares two immutable snapshots by fact/gate/reason code. We must know how it handles snapshots of different schemas or versions. The plan does not specify, but we assume it would fail gracefully.

Given the above, we can now list our findings and grade them.

### Findings

We'll go through each criterion and note any issues.

#### 1. Architectural soundness

- **Finding**: The plan reuses existing scripts (`git_hygiene.py`, `plan_context_loader.py`, etc.) but does not explicitly confirm that these scripts are stdlib-only and do not introduce external dependencies. If any of these scripts have external dependencies (e.g., `requests` for GitHub API), then the TruthDeck core would not be stdlib-only as claimed.
  - **Grade**: P2 (important) - because if the reused scripts have external dependencies, it violates the stdlib-only goal and could introduce security or maintenance issues.

#### 2. Threading/async safety

- **Finding**: The plan does not mention any use of threads or async in the core logic, and the collectors are subprocess-based. However, the MCP adapter uses the official MCP Python SDK. We are not told if the SDK is thread-safe or if the MCP server is designed to handle concurrent requests safely. Since the MCP server uses stdio and is likely to be run in a single-threaded manner (as per the MCP stdio transport), it might be safe. However, without explicit confirmation, there is a risk.
  - **Grade**: P3 (nice-to-have) - because the MCP adapter is optional and the core is synchronous, but it would be good to confirm the MCP server's concurrency model.

#### 3. Edge cases

- **Finding**: The plan does not explicitly address what happens when the user's home directory (for `~/.truthdeck`) is on a network filesystem with high latency or intermittent connectivity. This could lead to storage failures or timeouts that are not handled gracefully.
  - **Grade**: P2 (important) - because it could cause the tool to hang or fail unexpectedly in common environments (e.g., corporate networks with home directories on servers).

#### 4. Cost/performance

- **Finding**: The plan sets performance budgets but does not specify how the performance will be monitored in production or what happens if the budgets are exceeded. It only says that performance failure does not permit dropping provenance or fail-closed behavior. However, it does not specify any fallback or alerting mechanism.
  - **Grade**: P3 (nice-to-have) - because it is important to know if the tool is meeting its performance goals in the wild, but it is not a blocker for correctness.

#### 5. Integration risks

- **Finding**: The plan relies on the `gh` CLI for GitHub integration. It does not specify what version of `gh` is required or how it handles changes in the `gh` CLI's output format. If the `gh` CLI changes its JSON output, the collector might break.
  - **Grade**: P2 (important) - because the GitHub collector is a key component and breaking changes in `gh` could lead to incorrect evidence collection.

#### 6. Underspecified areas

- **Finding**: The plan does not specify the exact schema for the registry.json file. Without this, users and implementers cannot know what configuration is allowed and what validation rules apply.
  - **Grade**: P2 (important) - because the registry is a critical configuration point and an underspecified schema could lead to misconfiguration or security issues.

- **Finding**: The plan does not specify what constitutes the "policy" for the `policy_digest_sha256` field in the snapshot. This is important for understanding what changes would invalidate the digest and require a new snapshot.
  - **Grade**: P2 (important) - because without knowing what is included in the policy digest, we cannot be sure that policy changes are properly reflected.

- **Finding**: The plan does not specify how the canonical repo ID is generated for multi-repo namespaces. This is important to avoid collisions and ensure stability.
  - **Grade**: P2 (important) - because if the repo ID is not stable or unique, it could lead to incorrect fact namespacing and gate evaluation.

### TOP 3 CHANGES

Based on the above, we select the three highest-priority findings (P1 or P2) that are most critical to address before implementation.

1. **Architectural soundness: Verify reused scripts are stdlib-only** (P2) - because if the core ends up with external dependencies, it violates a key design goal and could introduce security risks or break the isolation guarantees.

2. **Edge cases: Handle network/home directory latency** (P2) - because it is a common real-world scenario that could cause the tool to fail or hang, and it is not addressed in the current plan.

3. **Integration risks: Specify `gh` CLI version and output format stability** (P2) - because the GitHub collector is a key integration point and breaking changes in `gh` could lead to incorrect evidence.

However, note that we did not find any P1 (blocker) issues. All the issues we found are P2.

But let's double-check for any P1:

- Is there anything that would make the tool fundamentally broken or unsafe?
  - The plan has a strong security focus (no shell=True, path containment, etc.).
  - The fail-closed principle is well defined.
  - The reversibility is clear.

We did not see any P1.

Therefore, our top 3 changes are:

1. Ensure that all reused scripts (`git_hygiene.py`, `plan_context_loader.py`, etc.) are stdlib-only and do not introduce external dependencies. If they do, either replace the usage with stdlib

---

## 04_laguna_m1

# Audit — Poolside Laguna M.1 (free)

Model: `poolside/laguna-m.1:free`  
Tokens: 15,429  
Latency: 92.0s  
Packet Context: none; model=poolside/laguna-m.1:free

---


## Audit Findings

### 1. Architectural Soundness

**P1 - Missing concurrent writer collision handling specification**  
Section "Storage and concurrency" states concurrent writers create separate immutable artifacts but doesn't specify the exact mechanism for preventing race conditions during the "exclusive-create semantics" phase. The atomic latest pointer replacement failure is mentioned but the recovery path for partial writes or filesystem-level race conditions is underspecified.

**P2 - Insufficient git_hygiene reuse boundary definition**  
Section "S2 - Generic collectors" mentions reusing `git_hygiene` read logic but doesn't specify which exact functions/modules are safe to import. The plan needs explicit import boundaries to prevent accidental invocation of apply/deploy paths.

**P2 - Registry security enforcement mechanism undefined**  
Section "Registry and policy" states users cannot add argv/executables/modules but doesn't specify the validation mechanism. How is the registry schema enforced to prevent injection of arbitrary commands?

### 2. Threading/Async Safety

**P1 - Race condition in latest.json atomic replacement**  
Section "Storage and concurrency" describes atomic replacement but doesn't address what happens if the filesystem doesn't support atomic renames (e.g., cross-filesystem moves) or if the process crashes mid-replacement. The recovery path for a corrupted or stale `latest.json` is missing.

**P3 - No specification for subprocess cleanup on Windows**  
Section "Collector contract" mentions terminating subprocesses on timeout but doesn't specify Windows-specific process tree cleanup (e.g., child processes that may outlive the parent).

### 3. Edge Cases

**P1 - Registry corruption recovery undefined**  
Section "Error and rescue registry" doesn't cover what happens when `~/.truthdeck/registry.json` is corrupted, malformed, or has an unsupported schema version. The fail-closed behavior needs explicit handling.

**P2 - Partial write handling in concurrent scenarios**  
If a snapshot write is interrupted (power failure, process kill), the plan doesn't specify how incomplete artifacts are detected and cleaned up during subsequent reads.

**P2 - Cross-filesystem symlink handling**  
Section "Collector contract" mentions symlink resolution but doesn't address cross-filesystem symlinks which could bypass containment checks.

### 4. Cost/Performance

**P2 - No caching strategy for repeated identical requests**  
The plan explicitly rejects caching-derived PASS in v1, but doesn't address performance implications for repeated identical snapshot requests within TTL windows. This could lead to excessive GitHub API calls.

**P3 - Missing performance degradation handling**  
If individual collectors exceed their timeouts repeatedly, there's no circuit-breaker or backoff mechanism specified, potentially leading to resource exhaustion.

### 5. Integration Risks

**P1 - MCP configuration schema discovery underspecified**  
Section "S5 - Skill, MCP adapter, and installation" states "discover and fixture-test the exact active Claude/Codex configuration schemas" but doesn't specify what these schemas are, how they're discovered, or what happens if they change. This is a critical integration point.

**P2 - Registry template version migration path**  
The plan mentions installer preserves existing user configuration and writes `.from-template` candidate when template version advances, but doesn't specify the merge strategy or conflict resolution for user-modified registry entries.

### 6. Underspecified Areas

**P1 - Exact git_hygiene module boundaries**  
Before implementation, the plan needs to explicitly list which functions from `git_hygiene.py` are safe to import and how to extract them without mutation capabilities.

**P1 - MCP registration rollback atomicity**  
Section "Activation and rollback" describes MCP removal using ownership marker but doesn't specify how to handle partial failures during registration (e.g., skill copied but MCP registration fails).

**P2 - Registry schema validation implementation**  
The plan needs more detail on how the registry JSON schema validation works, particularly for rejecting unknown executable paths and ensuring probe IDs map to code-owned implementations.

---

## TOP 3 CHANGES

1. **Add explicit concurrent write handling specification** - Define the exact mechanism for exclusive-create semantics including filesystem-level atomicity guarantees, partial write detection, and recovery procedures for interrupted snapshot creation.

2. **Specify git_hygiene import boundaries** - Create a clear list of safe read-only functions from `git_hygiene.py` with explicit module boundaries, and add regression tests ensuring no mutation paths are accidentally invoked.

3. **Define MCP configuration schema discovery and handling** - Document the exact Claude/Codex configuration schemas, specify how they're discovered and validated, and define behavior for schema version mismatches including fail-closed handling.


---

## 07_cohere_north_mini

# Audit — Cohere North Mini Code (free)

Model: `cohere/north-mini-code:free`  
Tokens: 16,573  
Latency: 73.1s  
Quality: DEGENERATE — truncated_mid_sentence  
Packet Context: none; model=cohere/north-mini-code:free

---

## Architectural soundness

| Finding | Location | Grade | Detail |
|---|---|---|---|
| **Missing registry schema & template** | ## Registry and policy → “`~/.truthdeck/registry.json` is user‑owned configuration created from `templates/truthdeck.registry.json.template` only when absent.” | **P1** | No JSON schema, validation rules, or example template are provided. Without a contract, a malformed registry could silently disable required collectors or enable unsafe argv, breaking the “fail‑closed” guarantee. |
| **No explicit guard against importing application repos** | ## Module layout → “No module may import an application repo.” | **P2** | The plan states the rule but does not enforce it at import time (e.g., via `sys.modules` checks or static analysis). A future developer could inadvertently import a repo‑specific module, violating the read‑only boundary. |
| **Ownership of `plan_context_loader.py` limitation not addressed** | ## Current‑state evidence and reuse map → “`plan_context_loader.py` currently detects only repositories directly under `D:/APPS`, so it does not detect this repository under `D:/dotclaude`.” | **P1** | TruthDeck must collect facts for its own repository (`dotclaude-ecosystem`). The existing loader cannot discover it, so the Git/plan/GitHub/review collectors will miss the host repo unless a separate discovery path is added. |
| **Atomic‑write semantics lack explicit cross‑platform locking** | ## Storage and concurrency → “Each snapshot is immutable and created with exclusive‑create semantics.” | **P2** | “Exclusive‑create” is not defined for Windows (e.g., `CreateFile` with `CREATE_EXCLUSIVE`). Without a documented lock (e.g., `msvcrt.locking` or `portalocker`), concurrent writers could corrupt `latest.json` or produce duplicate content IDs. |
| **Profile predicate evaluation is underspecified** | ## Module layout → `scripts/truthdeck_profiles.py` (no content shown) | **P2** | The plan says profiles define “code‑owned probe allowlist and profile predicates” but does

---

## 08_nemotron3_nano_reason

# Audit — Nemotron 3 Nano Omni 30B reasoning (free)

Model: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`  
Tokens: 17,932  
Latency: 74.8s  
Packet Context: none; model=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free

---

**Architectural soundness**  
- **P1** – *Missing explicit collector contract* – The “Collector contract” (section **## Collector contract**) only describes the function signature `collect(scope, policy, deadline) -> CollectorResult`. No base class, protocol, or enforced interface is defined, leaving ownership and correctness to documentation alone. This is a blocker because it opens the door to collectors that do not respect the deadline, return malformed results, or write outside the allowed paths. *(cited: ## Collector contract)*  
- **P2** – *Insufficient registry validation detail* – The “Registry and policy” section (## Registry and policy) states that the registry is validated before collectors run, but it does not specify how unknown major schema versions, missing required fields, or version mismatches are handled. Without a clear validation policy, the system could silently accept incompatible configurations, causing subtle correctness bugs. *(cited: ## Registry and policy)*  
- **P3** – *Concurrent snapshot write race* – The “Storage and concurrency” section (## Storage and concurrency) notes atomic exclusive‑create semantics but does not describe how two collectors could attempt to replace the same `latest.json` pointer simultaneously. The current design risks a lost‑update scenario where the latest pointer points to a partially written or duplicate artifact. *(cited: ## Storage and concurrency)*  

**Threading/async safety**  
- **P1** – *No synchronization for concurrent snapshot writes* – As above, the lack of a lock or atomic rename around the `latest.json` update creates a race condition when multiple agents produce snapshots for the same scope. This is a blocker because it can corrupt the canonical pointer and break reproducibility. *(cited: ## Storage and concurrency)*  
- **P2** – *Blocking I/O in collectors not bounded* – The “Performance acceptance” section (## Performance acceptance) caps per‑collector timeouts but does not guarantee that a collector that blocks (e.g., long‑running `git` enumeration) will not hold up the CLI or cause the total snapshot deadline to be exceeded. This could violate the 2‑second p95 target for local snapshots. *(cited: ## Performance acceptance)*  

**Edge cases**  
- **P1** – *Unclear mapping of collector failure modes to reason codes* – The “Failure and rescue registry” (## Failure and rescue registry) lists many reason codes, but it does not specify which collector exit status or internal error maps to which code (e.g., non‑zero exit vs. timeout vs. output‑limit). Ambiguous mapping can cause a `PASS` when the intent was `UNKNOWN` or `BLOCKED`. *(cited: ## Failure and rescue registry)*  
- **P2** – *TTL and freshness handling for runtime probes* – The “Data contract” (## Data contract) mentions `fresh_until_utc` but does not define how a probe that expires after the snapshot is sealed should be treated. If a stale probe result is cached beyond its TTL, the system could report `PASS` incorrectly. *(cited: ## Data contract)*  

**Cost/performance**  
- **P1** – *No total deadline enforcement for snapshot collection* – The “Performance acceptance” section caps individual collector timeouts but does not bound the overall wall‑clock time for a multi‑collector snapshot (e.g., Git + GitHub + runtime probes). Without a global deadline, a slow collector could push the snapshot beyond the 2‑second p95 budget. *(cited: ## Performance acceptance)*  
- **P2** – *Potential excessive API calls* – The “Collector contract” (## Collector contract) allows a `gh` JSON collector, but there is no guidance on how many calls are made per snapshot or how rate‑limiting is enforced. Unbounded API usage could increase latency and cost, violating the 10‑second p95 target for GitHub‑inclusive snapshots. *(cited: ## Collector contract, ## Performance acceptance)*  

**Integration risks**  
- **P1** – *Missing guarantee that snapshots embed the registry version/digest* – The “Data contract” (## Data contract) states that the snapshot records the registry/policy digest, yet the design does not enforce that the digest is immutable for the lifetime of the snapshot. If the registry changes after a snapshot is taken, later validation could become inconsistent. *(cited: ## Data contract)*  
- **P2** – *Potential collector‑allowlist mismatch* – The “Registry and policy” (## Registry and policy) permits disabling or narrowing collectors per profile, but it does not spell out how the system validates that a requested collector is actually allowed for the given scope. A mis‑configuration could cause a prohibited collector to run, breaking the read‑only guarantee. *(cited: ## Registry and policy)*  

**Underspecified areas**  
- **P1** – *Multi‑repo scope handling and fact namespace* – The “Stage model” (## Stage model) and “Data contract” (## Data contract) assume a single repository scope, but the CLI supports bounded multi‑repo requests. The plan does not define how fact keys are namespaced per repo, how required stages are ordered across repos, or how the “one next action” is selected when multiple repos have pending gates. *(cited: ## Stage model, ## Data contract)*  
- **P2** – *Path placeholder resolution with Unicode and spaces* – The “Collector contract” (## Collector contract) mentions that placeholders are resolved without command substitution, but it does not specify how Windows paths containing spaces, Unicode characters, or reparse points are canonicalized. This omission could lead to `BOUNDARY_REFUSAL` or incorrect repository detection. *(cited: ## Collector contract)*  
- **P3** – *Tie‑breaking rules for next‑action selection* – The “Next‑action algorithm” (## Next‑action algorithm) describes the deterministic selection process but does not detail how ties (e.g., two equally early `HOLD` stages) are resolved. Without a deterministic tie‑breaker, the output could be nondeterministic, violating the “deterministic core” invariant. *(cited: ## Next‑action algorithm)*  

---

### TOP 3 CHANGES  

1. **Introduce an explicit collector interface (base class or protocol)** that enforces the `collect(scope, policy, deadline) -> CollectorResult` contract, validates deadline usage, and guarantees that all collectors run under the same deadline semantics. This resolves ownership ambiguity and prevents accidental violations of the read‑only / no‑write rules. *(cited: ## Collector contract)*  

2. **Implement atomic snapshot creation with a safe latest‑pointer update** – use a temporary file, write the JSON atomically, then rename it, and perform the `latest.json` pointer replacement only after the snapshot validates. Add a file‑system lock or version check to avoid concurrent write races. *(cited: ## Storage and concurrency)*  

3. **Define clear TTL‑based freshness enforcement and reason‑code mapping** – specify that any collector timeout, non‑zero exit, or output‑limit condition maps to the appropriate reason code (`COLLECTOR_TIMEOUT`, `COLLECTOR_OUTPUT_LIMIT`, etc.) and that runtime probes whose `fresh_until_utc` has passed are treated as `UNKNOWN`/`NO_SAMPLE`. Include a global snapshot deadline (e.g., 2 s p95) that aborts the collection pipeline if any collector exceeds its per‑collector or total budget. *(cited: ## Failure and rescue registry, ## Data contract, ## Performance acceptance)*
