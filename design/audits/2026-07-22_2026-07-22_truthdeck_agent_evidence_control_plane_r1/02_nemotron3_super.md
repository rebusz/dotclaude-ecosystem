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