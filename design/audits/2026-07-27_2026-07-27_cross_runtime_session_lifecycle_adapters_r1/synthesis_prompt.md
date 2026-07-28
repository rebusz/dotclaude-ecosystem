# audit topology — Synthesis (`paid` mode)

**Plan**: `2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`
**Run date**: 2026-07-27
**Lanes**: openrouter_paid, perplexity_cdp, gemini_cdp (FAILED), kimi_cdp (FAILED), claude_cli
**OpenRouter basket**: paid complement roster

---

## Instructions for the synthesizer

Synthesize the 8 audits below (OpenRouter paid basket + Perplexity/Gemini/Kimi/frontier lanes). For each finding:

1. **Consensus P1** — appears in 2+ audits -> MUST fix, apply to plan immediately.
2. **Unique P1/P2** — only 1 model flagged but architecturally valid -> apply if it fits frozen boundaries.
3. **Discard** — P3 style noise, contradictions with frozen boundaries, hallucinated requirements -> skip.

For each item to apply: state the **plan heading**, the **change**, and the **reason**.
Red lines: never override frozen boundaries; never touch Tsignal execution path without R3 gate.

---

## 01_deepseek_v4_pro

# Audit — DeepSeek V4 Pro

Model: `deepseek/deepseek-v4-pro`  
Tokens: 9,700  
Latency: 101.0s

---

## Audit Report

**Overall Assessment:** The plan is thorough, well-scoped, and demonstrates careful attention to failure modes, rollback, and backward compatibility. The architecture of a thin adapter delegating to the existing lifecycle engine is sound. However, a few areas require clarification or hardening before implementation begins.

---

### Findings

#### 1. Architectural Soundness

- **Adapter-to-Engine Interface Underspecified**  
  The plan states that `session_router.py` and `session_lifecycle.py` “accept the persisted Codex payload shape directly,” but it does not define the exact function signatures or data contract the adapter must call. Without a precise interface (e.g., `router.handle_start(session_id, transcript_path, cwd, ...)`), there is a risk of integration mismatch during implementation.  
  **Grade:** P2 (important — should fix before coding)

- **No Concurrency Safeguards for State Files**  
  The existing lifecycle engine writes to `.claude/state` files. If multiple Codex sessions run concurrently (e.g., in separate terminal tabs), simultaneous writes to the same session state files could cause corruption or lost updates. The plan does not address this, and the engine was originally designed for single-session Claude Code usage.  
  **Grade:** P2 (important — should fix; either add file locking or document the single-session assumption)

#### 2. Threading/Async Safety

- **Single-Process Model is Safe, but Concurrency Gap Exists**  
  The adapter itself is a short-lived subprocess, so no internal threading issues. However, as noted above, concurrent invocations of the lifecycle engine from multiple Codex sessions are not protected. This is the only concurrency concern.  
  **Grade:** P2

#### 3. Edge Cases

- **Missing Transcript at SessionEnd**  
  The failure map covers missing binding state but does not explicitly handle the case where the transcript file is deleted between `SessionStart` and `SessionEnd`. The close verdict logic may attempt to read the transcript and fail silently or raise an unhandled exception.  
  **Grade:** P2 (should add explicit handling or confirm existing engine resilience)

- **Relative `transcript_path` Resolution**  
  The plan lists “relative path” as an edge-case fixture but does not specify how the adapter resolves it (e.g., joining with `cwd`). The prototype supplied absolute paths, but if Codex ever emits a relative path, the adapter must handle it.  
  **Grade:** P3 (nice-to-have clarification)

#### 4. Cost/Performance

- **No Concerns** — The adapter is lightweight, and existing byte limits bound transcript scanning. No network calls or memory leaks are introduced.

#### 5. Integration Risks

- **Hook Template Schema Not Specified**  
  The plan says “Add a canonical Codex hook template,” but the exact JSON structure (matchers, command, timeout, etc.) is left to implementation. A mismatch with Codex’s expected hook format could prevent activation or cause silent failures.  
  **Grade:** P2 (should provide the template skeleton or reference the exact Codex hook schema)

- **Session ID Format Compatibility**  
  The plan assumes the Codex `session_id` can be used directly as a key in the existing lifecycle store. While the existing modules “accept the payload shape directly,” there is no explicit check that the ID format (e.g., length, characters) is compatible with file naming or internal lookups.  
  **Grade:** P3 (low risk, but worth a quick validation)

#### 6. Underspecified Areas

- **Transcript Projection Location and Per-Record Detection**  
  The plan says to “extend the existing transcript readers with explicit format detection” and lists `curator_claims.py` and `session_lifecycle.py`. It does not clarify whether detection is per-record (as implied by “mixed-format files degrade”) or per-file, nor where the detection function will live. This could lead to scattered logic.  
  **Grade:** P3 (nice-to-have design note)

- **Activation Script Interface**  
  The activation command is described functionally but not named or located (e.g., `python scripts/install_codex_hooks.py`). This is minor but would help reviewers.  
  **Grade:** P3

---

### TOP 3 CHANGES

1. **Define the exact adapter-to-engine contract** — Specify the function calls and arguments the adapter will use to delegate to `session_router.py` and `session_lifecycle.py`. This prevents integration drift and ensures the adapter can be built correctly. (P2)

2. **Address concurrent session file safety** — Either add file locking to the lifecycle engine’s state writes, or explicitly document that the system assumes only one Codex session runs at a time. Without this, concurrent sessions risk corrupting lifecycle state. (P2)

3. **Provide the hook template structure** — Include the exact JSON schema for the Codex hook configuration (matchers, command, timeout) in the plan or a linked spec. This eliminates guesswork and ensures the activation script generates a valid hook file. (P2)

---

## 01_ppl_best

# Audit - Best

Model: `perplexity/best`  
Source: `perplexity_cdp`  
Selected model option: `Best
Selects the best available model`  
Tokens: `unknown-web-ui`  
Latency: 72.0s

---

Below is a structured architectural audit of the Cross-Runtime Session Lifecycle Adapters — Codex First plan. Given that significant sections were compacted and marked as omitted, findings are rated with an explicit confidence qualifier where the omission affects certainty.

1. Architectural Soundness

Finding A1 — [Architecture] Adapter ownership and error propagation chain are underspecified. (P1)
The ASCII diagram shows ~/.codex/hooks.json → codex_session_adapter.py → persisted transcript but the path is truncated. It is unclear who owns the transcript store (the adapter, a shared session bus, or the lifecycle engine itself), and whether failures in codex_session_adapter.py propagate upstream to the lifecycle engine or are silently dropped. For a best-effort/advisory system, silent drops may be intentional — but there is no documented contract for what happens when the adapter cannot write its transcript (disk full, permission denied, concurrent write). This must be explicit before the C0 red-tests are meaningful.

Finding A2 — [Deferred Runtime Slices] No handoff contract between Codex slice and future Cursor/Antigravity/Kimi slices. (P2)
The plan defers Cursor, Antigravity, and Kimi with "each next slice begins with native lifecycle-…" (truncated). If the Codex adapter introduces any singleton state (e.g., a global session registry keyed by Git root), later adapters that try to register the same roots will hit collision. The plan should define whether adapter registration is idempotent and whether the registry is a shared singleton or per-adapter.

Finding A3 — [Repository Registry Scope] No fallback for Git roots that disappear between registration and hook invocation. (P2)
"Candidate roots" are verified at planning time against a specific HEAD (e2397ed…). If a registered root is deleted, renamed, or unmounted before a Codex session fires, the hook will execute against a stale registry entry. The failure map covers Hook is untrusted but not Hook fires against missing root.

2. Threading/Async Safety

Finding B1 — [Architecture / Implementation Tasks T1] Concurrent session start/end ordering is unspecified. (P1)
Codex may emit SessionStart and SessionEnd rapidly (e.g., on a fast script run). If codex_session_adapter.py uses any async or threaded I/O for transcript persistence, a SessionEnd arriving before the SessionStart write completes creates an orphaned or inverted record. The fixture set in C0 must include an out-of-order delivery fixture (SessionEnd before SessionStart) and the adapter must define its ordering guarantee explicitly.

Finding B2 — [Architecture] Hook invocation model (sync vs. async subprocess) not specified. (P2)
~/.codex/hooks.json in the codex-cli model typically invokes hooks as subprocesses. If codex_session_adapter.py is invoked synchronously on the Codex hot path, any blocking I/O (transcript write, registry lookup, network call) directly adds latency to the user-facing Codex session startup. The plan does not specify a timeout budget for hook execution or whether hooks are fire-and-forget.

3. Edge Cases

Finding C1 — [Failure Map] Failure map is incomplete — only one row is visible. (P1, audit confidence: moderate due to compaction)
The visible row covers Hook is untrusted. Standard failure cases that should be covered but are not confirmed present: hook binary not found at invocation time, malformed SessionStart payload (missing required fields), transcript store write failure, duplicate SessionStart without intervening SessionEnd (nested/re-entrant sessions), and Codex process kill between start and end (no SessionEnd ever emitted). At minimum, the re-entrant session and missing SessionEnd cases need explicit safe-behavior definitions before T1 fixtures are written, since those fixtures drive the contract.

Finding C2 — [Validation and Landing Gate] Test gate does not cover unhappy paths explicitly. (P2)
The pytest invocation targets test_codex_session_adapter.py but no mention of negative-path or degraded-mode tests in the gate command. If the landing gate only asserts the happy path passes, a broken failure-handling code path will not block merge. The gate should include at least one explicit negative fixture (malformed payload, missing root) as a required passing test.

Finding C3 — [Definition of Done] "Persisted Codex ses…" is truncated. (P2, audit confidence: low)
The definition of done is cut mid-sentence. It is unknown whether "persistence" means append-only JSONL, a database, or an in-memory structure flushed at shutdown. This directly affects the orphaned-session edge case (C1) and the concurrent write safety question (B1). This must be restored before implementation begins.

4. Cost/Performance

Finding D1 — [Repository Registry Scope] Registry verification at session-start time may be expensive. (P3)
If the adapter re-verifies Git roots on every SessionStart hook invocation (e.g., by running git rev-parse), and the user has many registered roots, this adds measurable latency per session start. Since the plan freezes the registry at planning time, a cached/static registry loaded once at adapter startup is preferable — but the plan does not specify when and how often root verification runs.

Finding D2 — [Architecture] Transcript persistence I/O on the hook hot path. (P2)
Writing a persisted transcript synchronously in the hook path (even for advisory-only data) is a potential latency sink. No buffering, batching, or async-write strategy is specified.

5. Integration Risks

Finding E1 — [Verified Current State / Frozen Boundaries] Hook schema contract with codex-cli is unversioned. (P1)
The plan pins the repo HEAD at e2397ed but does not specify which version of codex-cli the hook schema (hooks.json format, SessionStart/SessionEnd payload fields) is validated against. If codex-cli is updated and the hook payload schema changes, codex_session_adapter.py will silently misparse events. The C0 fixtures must pin the exact codex-cli version they were generated against and the adapter must defensively validate payload fields.

Finding E2 — [CEO Review / Feature Branch] Base branch is main; branch name not confirmed present. (P3)
The CEO review notes the feature branch name but it is truncated. If work lands directly on main without a PR gate, the validation script is the only safety net. Confirming the branch exists and the landing gate runs in CI (not just locally in PowerShell) would close this gap.

6. Underspecified Areas

Finding F1 — [Definition of Done] Persistence model undefined. (P1)
As noted in C3: the persistence strategy (format, location, flush policy, rotation) is truncated and must be fully specified. It determines durability guarantees, orphan handling, and test fixture structure.

Finding F2 — [C0 Contract Fixtures] Fixture coverage matrix not enumerated. (P2)
T1 says "add red contract tests — surfaced by parser gap and four-path review" but the four paths are not named. Before writing fixtures, the four paths (presumably: persisted start, persisted end, ephemeral start, ephemeral end — plus error variants) should be explicitly listed so reviewers can confirm coverage completeness.

Finding F3 — [GSTACK REVIEW REPORT] Table is truncated — findings unknown. (P2)
The GSTACK review table header is present but the rows are cut. If this review surfaced findings that drove task prioritization, those findings should be visible in the audit. Their absence means the audit cannot confirm that all GSTACK-flagged issues are addressed by the current task list.

TOP 3 CHANGES

1. P1 — Define and document the persistence model before any fixture is written
[Definition of Done] and [Architecture] are both truncated at the persistence description. The transcript store format (JSONL append-only, SQLite, etc.), location, flush policy, and orphan-session handling (no SessionEnd ever received) must be written out explicitly. Every C0 fixture and every failure-map row depends on this contract. Without it, tests may pass against an incorrect assumption and require full rewrite at C1.

2. P1 — Add out-of-order and orphaned-session fixtures to the C0 red-test set
[C0 Contract Fixtures] and [Failure Map] must explicitly cover: (a) SessionEnd arriving before SessionStart, (b) duplicate SessionStart with no intervening SessionEnd, and (c) process-killed session (no SessionEnd emitted). These are the most likely real-world failure modes for a hook-driven lifecycle adapter and they must be contractually handled before any green tests are accepted.

3. P1 — Pin the codex-cli hook schema version in fixtures and add defensive payload validation in the adapter
[Verified Current State] pins the repo HEAD but not the codex-cli version. The SessionStart/SessionEnd payload fields must be validated against a pinned schema version (document it in the fixture header). The adapter must defensively reject or warn on unknown/missing fields rather than silently proceeding with a partial parse, or a silent regression will occur on any codex-cli upgrade.

---

## 02_mistral_medium35

# Audit — Mistral Medium 3.5

Model: `mistralai/mistral-medium-3-5`  
Tokens: 7,796  
Latency: 36.5s

---

Here’s the audit of the **Cross-Runtime Session Lifecycle Adapters — Codex First** plan, graded against the specified criteria:

---

---

### **1. Architectural Soundness**
**Findings:**
- **P1 (Blocker)** — **## Architecture > Diagram**: The architecture diagram shows `codex_session_adapter.py` delegating to `session_router.py`/`session_lifecycle.py`, but **ownership of the adapter’s failure modes is unclear**. The plan states the adapter "fails open" but does not explicitly assign responsibility for logging/telemetry of failures (e.g., `CODEX_ADAPTER_*` reason codes). **Who owns the bounded error logging?** The adapter or the router/lifecycle?
  - *Cite*: "Fail open and log bounded reason codes without transcript contents" (## C1) vs. "router/lifecycle delegate | expected validation failure" (## Error and rescue registry).
  - *Risk*: If the adapter logs but the router also logs, this could lead to duplicate or conflicting error handling.

- **P2 (Important)** — **## Frozen boundaries**: The plan explicitly prohibits "transcript globbing or fallback to another session," but **does not specify how the adapter handles concurrent sessions** (e.g., two Codex sessions starting simultaneously). The existing Claude lifecycle engine may assume sequential events, and the adapter’s behavior here is underspecified.
  - *Cite*: No mention of concurrency in ## C1 or ## Architecture.

- **P3 (Nice-to-have)** — **## Repository registry scope**: The list of candidate Git roots is hardcoded (e.g., `D:/APPS/TSU`). This is brittle for future machines/environments. Consider making this configurable or dynamically discovered.

---

### **2. Threading/Async Safety**
**Findings:**
- **P1 (Blocker)** — **## C1 > Thin Codex event adapter**: The adapter reads from `stdin` and delegates to `session_router.py`/`session_lifecycle.py`. **No mention of thread safety or lock inversion risks** if the router/lifecycle is not thread-safe.
  - *Cite*: The existing Claude lifecycle engine (predecessor plan) may not be designed for concurrent calls. The adapter must either:
    - Guarantee sequential invocation (e.g., via Codex’s hook contract), or
    - Add locking around shared state (e.g., `session.plan.v1` writes).
  - *Risk*: Race conditions if two Codex sessions trigger `SessionStart`/`SessionEnd` simultaneously.

- **P2 (Important)** — **## C2 > Dual-format transcript projection**: The projection logic for Codex transcripts (e.g., `response_item.payload.type=message`) **may block on I/O** if parsing large JSONL files. The plan does not specify:
  - Whether parsing is streamed or buffered.
  - Timeouts for malformed/unusually large transcripts.
  - *Cite*: "Oversized sources... degrade to incomplete/unverified evidence" (## Failure map) but no performance guardrails.

- **P3 (Nice-to-have)** — **## C3 > Global hook template**: The activation script’s backup/restore logic (e.g., atomic file operations) is not specified. **Potential for partial writes or corruption** if interrupted (e.g., power loss).

---

### **3. Edge Cases**
**Findings:**
- **P1 (Blocker)** — **## Failure map > "Repo is unregistered"**: The plan states unregistered repos receive "minimal advisory context," but **does not define what "minimal" entails**. Could this leak sensitive data (e.g., `cwd`) or violate the fail-closed posture?
  - *Cite*: "Unregistered repositories receive a short advisory/minimal context" (## Definition of done) is vague.
  - *Risk*: Inconsistent behavior if "minimal context" is not strictly bounded.

- **P1 (Blocker)** — **## C2 > Function call/result pairing**: The plan requires "exact `call_id`" matching, but **does not handle `call_id` collisions** (e.g., reused IDs across sessions or malformed IDs). The failure mode ("no command evidence") is correct, but the edge case of duplicate IDs in a single transcript is untested.
  - *Cite*: "Codex function calls/results pair only by exact `call_id`" (## C2).

- **P2 (Important)** — **## C1 > `transcript_path: null`**: The adapter treats this as a no-op, but **what if `transcript_path` is a non-null but invalid path (e.g., `/dev/null` or a symlink to a non-existent file)?** The plan only covers `null` explicitly.
  - *Cite*: "Treat a null/empty `transcript_path` as an intentional no-op" (## C1).

- **P3 (Nice-to-have)** — **## Live acceptance**: The plan does not test **interrupted sessions** (e.g., Codex crash mid-session). The adapter should handle `SessionEnd` without a prior `SessionStart`.

---

### **4. Cost/Performance**
**Findings:**
- **P2 (Important)** — **## C2 > Transcript projection**: The plan does not specify **memory limits** for parsing Codex transcripts. Large sessions could exhaust memory if the entire JSONL is loaded at once.
  - *Cite*: "Existing transcript byte limits remain the performance boundary" (## Performance) but no explicit limits for Codex.
  - *Risk*: Memory bloat if Codex transcripts are significantly larger than Claude’s.

- **P2 (Important)** — **## C1 > Adapter overhead**: The adapter adds a **new process per hook event** (Codex spawns a Python script per `SessionStart`/`SessionEnd`). At scale (e.g., 100s of sessions), this could introduce latency.
  - *Mitigation*: The plan notes "hook timeout" enforcement, but does not specify the timeout value or how it’s configured.

- **P3 (Nice-to-have)** — **## C3 > Activation script**: The registry template expansion (step 4) could be slow if scanning many repos. **No performance constraints** are defined.

---
---
### **5. Integration Risks**
**Findings:**
- **P1 (Blocker)** — **## Verified current state > Transcript readers**: The plan acknowledges that **Codex transcripts use `type=response_item` vs. Claude’s `type=assistant`**, but **does not verify backward compatibility** with existing Curator claims.
  - *Cite*: "Existing transcript readers only recognize Claude records... this is the only proven parser gap."
  - *Risk*: If Curator expects `type=assistant` and the projection misses edge cases, claims could be silently unverified.

- **P2 (Important)** — **## Architecture > `.claude/state`**: The plan reuses `.claude/state` for Codex, but **does not confirm that Codex respects this directory’s permissions/ownership**. If Codex runs as a different user, file access could fail.
  - *Cite*: "The `.claude/state` name is retained as the existing cross-host lifecycle store."

- **P3 (Nice-to-have)** — **## C3 > Hook template**: The template uses **absolute Windows commands**, but the plan does not test **non-Windows paths** (e.g., macOS/Linux). This could break cross-platform activation.

---
---
### **6. Underspecified Areas**
**Findings:**
- **P1 (Blocker)** — **## C1 > Adapter input validation**: The adapter "allows only `SessionStart` and `SessionEnd`," but **does not define how it rejects other events**. Does it:
  - Exit silently?
  - Log a warning?
  - Return a non-zero exit code?
  - *Cite*: "Treat a null/empty `transcript_path` as an intentional no-op" implies other events may not be no-ops.

- **P1 (Blocker)** — **## C2 > Projection for mixed-format files**: The plan states that **mixed Claude/Codex records degrade to incomplete/unverified**, but **does not specify how the projection handles a file with both formats**. Does it:
  - Skip non-Codex records?
  - Fail the entire file?
  - *Cite*: "Malformed arguments, unmatched results, oversized sources, and mixed-format files degrade to incomplete/unverified evidence."

- **P2 (Important)** — **## C3 > Registry template expansion**: The plan does not specify **how the registry template is "verified"** (step 4). Is this a manual step, or does the activation script validate repo existence/Git roots?

- **P2 (Important)** — **## Live acceptance > "normal trusted new Codex session"**: The plan does not define **what "normal hook trust" entails**. Is this a Codex-specific trust mechanism, or does it rely on filesystem permissions?

---
---
---
### **TOP 3 CHANGES**
1. **P1 (Architectural/Threading)** — Clarify ownership of error logging and concurrency guarantees in the adapter. Explicitly state whether the adapter is single-threaded (sequential hooks) or requires locks around shared state (e.g., `session.plan.v1` writes). *Cite: ## C1, ## Architecture*.
2. **P1 (Edge Cases/Integration)** — Define "minimal advisory context" for unregistered repos and add explicit tests for `transcript_path` edge cases (invalid paths, symlinks, etc.). *Cite: ## Failure map, ## C1*.
3. **P1 (Integration Risks)** — Add a backward-compatibility test for Curator claims with Codex-projected transcripts to ensure no silent failures. *Cite: ## Verified current state, ## C2*.

---

## 02_ppl_sonar2

# Audit - Sonar 2

Model: `perplexity/sonar-2`  
Source: `perplexity_cdp`  
Selected model option: `Sonar 2`  
Tokens: `unknown-web-ui`  
Latency: 61.3s

---

Based on the visible plan contract and architectural context, here is the full audit.

Audit: Cross-Runtime Session Lifecycle Adapters — Codex Slice
1. Architectural Soundness

[Architecture / Implementation Slices] The adapter diagram shows ~/.codex/hooks.json → codex_session_adapter.py → persisted transcript but the ownership boundary between the adapter and the downstream lifecycle engine is truncated. It is unclear whether codex_session_adapter.py calls the lifecycle engine directly, publishes to a queue, or writes a file that the engine polls. This ambiguity means two implementors could make incompatible assumptions. P1.

[Repository Registry Scope] The candidate roots section is truncated ("Candidate roots…"). The registry discovery strategy — whether it is static config, Git walk, or environment variable — is unspecified. If the adapter hardcodes paths valid only on the author's machine, it will silently skip repos on any other developer's environment. P2.

[Deferred Runtime Slices] Cursor, Antigravity, and Kimi are deferred with a note that "each next slice begins with native lifecycle-…" (truncated). There is no interface contract (abstract base class, protocol, or schema) frozen now that the Codex adapter must conform to. Without that, Codex becomes a de facto reference implementation that future slices will diverge from. P2.

2. Threading / Async Safety

[Architecture] The hook entry point is invoked by codex-cli as an external process (standard hook pattern). If the adapter performs synchronous file I/O for transcript persistence on that same call path, a slow disk or network mount will block codex's hook timeout, causing Codex to log the hook as failed/untrusted. The plan's failure map acknowledges the untrusted-hook case but does not bound the maximum write latency or specify an async/fire-and-forget write path. P1.

[Validation / Landing Gate] The pytest invocation is synchronous and focused. No mention of thread-safety tests for concurrent SessionStart + SessionEnd events (e.g., rapid session churn or nested sessions). If two Codex processes fire hooks simultaneously against the same persisted transcript store, a write race is possible. P2.

3. Edge Cases

[Failure Map and Rollback] The failure map is partially truncated but the visible row covers only "Hook is untrusted." Missing explicitly: (a) SessionEnd received with no matching SessionStart (orphaned-end), (b) SessionStart received twice without an intervening SessionEnd (re-entrant session), (c) malformed or schema-mismatched JSONL payload from a future codex-cli upgrade. The C11/C14 advisory posture means these won't hard-fail, but silent data loss or double-counting in the lifecycle engine is a real risk. P1.

[Verified Current State] The plan pins codex-cli at a specific version (0.… truncated). There is no guard ensuring the installed CLI version matches at hook registration time. A user upgrading codex-cli independently could change the hook payload schema with no warning. P2.

4. Cost / Performance

[C0 — Contract Fixtures] Red tests against sanitized JSONL fixtures are the correct approach. However, if fixtures are generated by replaying real transcripts, sensitive tokens or API keys embedded in assistant text could leak into the test corpus. The plan does not specify a sanitization procedure or a secret-scan gate. Given the repo contains broker integration code, this is a non-trivial risk. P2.

[Architecture / Persisted Transcript] Transcript persistence strategy is unspecified (append-only log? SQLite? flat files per session?). An append-only log with no rotation or size cap will grow unboundedly. For a developer running many short Codex sessions daily this becomes a latent disk-pressure issue. P3.

5. Integration Risks

[Architecture → Lifecycle Engine boundary] The plan states the lifecycle engine "currently starts only when Claude Code emits SessionStart/SessionEnd." The Codex adapter must produce events that are schema-identical to Claude Code's events, or the lifecycle engine must be extended to accept a Codex variant. Neither path is explicitly specified. If the engine does a strict discriminator check on runtime: "claude", Codex events will be silently dropped. P1.

[CEO Review / Base Branch] The plan confirms main as base branch and references a feature branch (truncated). There is no mention of a merge strategy (squash vs. merge commit) or whether the feature branch is protected from force-push. For a lifecycle-critical hook that modifies user-level config (~/.codex/hooks.json), an accidental force-push erasing the rollback breadcrumb is a real ops risk. P3.

6. Underspecified Areas

[Definition of Done — Codex Slice] The DoD is truncated after "A persisted Codex ses…". Without the full DoD, the landing gate test suite (test_codex_session_adapter.py) cannot be verified to cover all acceptance criteria. This is the single most important gap to resolve before T1 begins. P1.

[Architecture diagram] The downstream side of codex_session_adapter.py (what consumes persisted transcripts, how the lifecycle engine is notified) is absent from the visible contract. This needs to be an explicit named interface with a defined call signature or message schema before any slice beyond C0 starts. P1.

[Implementation Tasks T1+] Only T1 is fully visible. T2–Tn are truncated. It is impossible to verify that the task graph is acyclic, that no two tasks mutate the same file, or that the human-estimated hours are consistent with the Codex estimates. P2.

TOP 3 CHANGES

1. [P1] Define and freeze the adapter→lifecycle-engine contract before any code is written.
The architectural boundary between codex_session_adapter.py and the lifecycle engine is the highest-risk gap. Specify: (a) the exact event schema Codex events must conform to, (b) whether Claude Code and Codex events share the same schema or are discriminated by a runtime field, and (c) the transport (direct call, file drop, queue). Without this, T1 fixtures will be written against an assumed contract that may be wrong by the time integration happens.

2. [P1] Add orphaned-end and re-entrant-session cases to the failure map and cover them in red tests (C0).
The current failure map covers only the "hook untrusted" path. Silent data corruption from unmatched SessionStart/SessionEnd pairs is the most likely real-world failure mode (process kill, crash, rapid restart). These cases must have defined safe behaviors and be covered by fixtures in C0 before green tests are written.

3. [P1] Bound and enforce hook write latency to prevent Codex marking the hook as untrusted.
Any synchronous I/O in the hook path is a reliability defect, not a performance nicety. The adapter must either fire-and-forget persistence (write to an in-process queue, flush asynchronously) or complete all work within a documented timeout budget. Add a latency assertion to the landing gate test suite.

---

## 03_minimax_m3

# Audit — MiniMax M3

Model: `minimax/minimax-m3`  
Tokens: 8,782  
Latency: 31.4s

---

# Audit Report — Cross-Runtime Session Lifecycle Adapters (Codex Slice)

## 1. Architectural Soundness

### Finding A1 — Adapter ownership boundary is underspecified at the router seam [P2]
**Section:** `### C1 — Thin Codex event adapter` and `### C2 — Dual-format transcript projection`
The plan says "Delegate persisted events to the existing router/lifecycle owners" but does not state which function on `session_router.py` / `session_lifecycle.py` is the entry point, what its return contract looks like, or whether the adapter must catch exceptions raised from those owners. The Error and Rescue table (`router/lifecycle delegate | ValueError | bounded log, exit 0`) implies broad exception swallowing around the delegate call, but the plan never specifies whether the adapter wraps a single function or a multi-step delegation. Need a one-line function-level contract (signature, return shape, side effects) before T2 starts.

### Finding A2 — Transcript projection is split across two files without an owner statement [P1]
**Section:** `### C2 — Dual-format transcript projection`; **Task T3**
The plan assigns work to both `scripts/curator_claims.py` and `scripts/session_lifecycle.py`. `curator_claims.py` is the verified-close path; `session_lifecycle.py` owns close verdicts. Splitting format-detection logic across the two means future hosts (Cursor/Antigravity/Kimi) will need to touch both files again, and the structural-detection rule "no global provider flag" is only meaningful if one file owns the format detection. Specify: `curator_claims.py` owns detection + projection; `session_lifecycle.py` remains policy-only and consumes normalized evidence. Without this, the "smallest adapter per host" promise breaks at host #3.

### Finding A3 — "Registry scope" duplicates the registry owner without a contract [P2]
**Section:** `## Repository registry scope` and `### C3 > item 4`
The adapter expands the canonical registry template "to the verified ecosystem repositories" at install time. But `### What already exists` says repository resolution is the sole property of `scripts/session_state.py` and "Reuse unchanged; no second registry parser". Activation-time registry mutation is a second writer with no specified protocol — same conflict as "second registry owner" appears in frozen boundaries. Either the activation step calls into `session_state.py` (preferred — single owner) or the boundary contradiction needs an explicit resolution.

### Finding A4 — Architecture diagram understates the Curator contract [P3]
**Section:** `## Architecture`
The diagram shows "unchanged fail-closed Curator verification" on the projection output. Given A2, the diagram should also show where format detection lives. Minor, but combined with A2 it hides the seam.

---

## 2. Threading / Async Safety

### Finding T1 — Hook process model not stated [P1]
**Section:** `### C1`, `### C3`, `### Performance, observability, deployment, and future`
The plan repeatedly references "hook timeout", "exits 0", "bounded log", and "host continues" but never specifies Codex's hook invocation model: process-per-event vs. persistent worker, stdin delivery (assumed here) vs. CLI flag, concurrent dispatch ordering, or whether `SessionStart` can fire before the prior `SessionEnd` has completed writing state. If Codex spawns a fresh `python` process per event and one Codex session can interleave start/end (e.g., `resume` during an outstanding close), the adapter has a write-after-write race against `session_lifecycle.py`'s state files despite both paths claiming single ownership. Specify the process model and add a test that fires start/end back-to-back to a temp state dir.

### Finding T2 — State-file writes serialized only by accident [P2]
**Section:** `### C1`, `### Failure map and rollback > Adapter exceeds timeout or raises`
The reaper and existing lifecycle owners use local file writes; the plan does not require file locking (`fcntl`/`msvcrt`) or atomic write-rename. With hook timeouts (T1), a `SessionEnd` that times out mid-write can leave a half-written state file. The adapter is described as fail-open, but a corrupted state file would cause the next start to misread prior session state. Specify atomic write semantics in the delegate contract, or explicitly accept the risk and document it under "what could go wrong once shipped".

### Finding T3 — Transcript readers re-scan on every Curator invocation [P3]
**Section:** `### C2`
Not introduced by this plan, but the plan adds a second on-disk shape for these readers without addressing concurrent partial writes by the host (Codex appending to the JSONL while the reader parses). Verify readers either tolerate trailing partial lines or document the contract that the host flushes before `SessionEnd` completes.

---

## 3. Edge Cases

### Finding E1 — `transcript_path` can be a relative path [P2]
**Section:** `### Data, quality, and edge cases` mentions "relative path" as a fixture but no resolution rule. The plan only treats `null` and empty as no-ops. A relative path needs to resolve against `cwd` from the event payload before reachability checks. Without a rule, `OSError` on open becomes a fail-open branch that bypasses projection entirely.

### Finding E2 — Oversized file policy unspecified [P2]
**Section:** `### C2 > oversized sources`, `### Performance... > existing transcript byte limits`
Mentions "oversized sources ... degrade to incomplete/unverified evidence" but does not state the byte limit, where it is enforced (reader vs. adapter), or whether the adapter pre-checks size before tailing. If the limit lives only in the reader, the adapter will time out on an oversized file before the reader can short-circuit. The plan should name the limit, the file where it lives, and whether the adapter pre-stats the file when the transcript_path is non-null.

### Finding E3 — Hook trust revoked during a live session [P1]
**Section:** `### C4 — Exact live acceptance`, `### Failure map > Hook is untrusted`
The plan lists "Hook is untrusted" as a recoverable failure but does not specify the runtime behavior when trust is revoked *between* `SessionStart` and `SessionEnd`. If the adapter depends on a user-level config that the user can edit mid-session, the next event may behave differently (e.g., silent no-op instead of verdict write), creating orphan state. Add a test or a documented expectation: trust revocation during a session may strand `session.binding.v1` without a corresponding `SessionEnd`.

### Finding E4 — Mixed Claude + Codex records in one JSONL are stated but not localized [P3]
**Section:** `### C2 > mixed-format files degrade`
Acceptable but the plan should specify how the reader reconciles a `call_id` namespace collision if the same file ever contained both formats (it won't today, but the projection rule says "exact `call_id`" without host scoping).

### Finding E5 — Plan does not enumerate `compact` semantics [P3]
**Section:** `## Verified current state` lists Codex matchers `startup|resume|clear|compact`. Compact is a hook-visible event with no Claude analogue. The plan routes it through the same `SessionStart` branch, but compacted-in-place transcripts may reuse `session_id` while changing `transcript_path`. Confirm explicitly that the router treats `compact` as a fresh `startup` for binding purposes, or define the alternative.

---

## 4. Cost / Performance

### Finding P1 — Adapter spawn-per-event dominates at volume [P2]
**Section:** `### Performance, observability, deployment, and future`
The plan assumes "local process startup plus the already measured router/lifecycle work." A fresh `python` interpreter per Codex event is on the order of 80–200 ms per invocation on Windows before any work. With power users triggering `compact` and `clear` repeatedly, this is a meaningful cost. The plan should record a measured baseline (cold and warm) during T5 and enforce it as a regression gate, not just "expected adapter overhead."

### Finding P2 — Activation script hash manifest is not versioned against script drift [P3]
**Section:** `### C3 > item 5: records hashes and an emergency-off restoration command`
The plan records hashes for the "emergency-off" restoration but does not say what happens when the adapter source is updated post-install. Stale hook pointing at changed code is not unsafe but produces a confusing audit trail. State whether the install re-validates hashes at session start (expensive) or simply documents that hooks should be reinstalled after source updates.

### Finding P3 — No mention of `pyproject` / requirements freeze [P3]
**Section:** Throughout
The frozen boundaries say "no new dependency," but the plan never states which Python is required on the host (Codex's bundled runtime vs. system Python) or what version floor is enforced. Codex may invoke `python` from PATH that differs from the developer environment. State the interpreter selection rule and pin it.

---

## 5. Integration Risks

### Finding I1 — Hook contract drift between Codex versions [P1]
**Section:** `## Verified current state` says `codex-cli 0.145.0` reports stable hooks; `### Not in scope` defers Cursor/Antigravity/Kimi. But the plan installs a user-level hook on `~/.codex/hooks.json` without a Codex-version compatibility check or a documented minimum version. If Codex changes the event name, adds a required field, or moves `transcript_path`, the hook silently no-ops on upgrade. The plan claims fail-open is by design, but that is only safe for host continuity, not for cross-runtime parity (the whole reason this plan exists). Add a Codex-version probe at adapter startup with a bounded warning reason code, and document the minimum version in the canonical template.

### Finding I2 — Activation assumes Codex accepts Windows path translation [P2]
**Section:** `### C3 > canonical Codex hook template with absolute Windows commands`
`~/.codex/hooks.json` interpretation on Windows for `command` strings is not stated. If Codex expects POSIX-style paths or rejects backslashes inside JSON, the "validates the generated hook configuration" step needs to cover the path-encoding test, not just JSON well-formedness. Add a portable-path round-trip test on Windows.

### Finding I3 — `sync_agent_rules.py --check` may not catch adapter-shaped regressions [P3]
**Section:** `## Validation and landing gate`
The repo's rule-sync check is unrelated to the adapter surface. The landing gate is acceptable, but T3 changes `curator_claims.py` and `session_lifecycle.py` — both high-blast-radius files. Add an explicit assertion (or grep) that the curator verification policy (not just the parser) is unchanged in the diff, so reviewers can quickly confirm "projection yes, policy no."

### Finding I4 — Backup atomicity on activation [P2]
**Section:** `### C3 > item 2: backs up an existing user hook file before replacing/merging`
If the backup is created and then the write fails (disk full, permissions), the user is left with a renamed original plus a missing canonical hook. The chaos test ("interrupts installation between backup and replacement") partially addresses this but does not state the recovery action when the backup exists and the new file does not. Specify: on partial install, restore from backup before exit nonzero.

---

## 6. Underspecified Areas

### Finding U1 — Adapter function signature and module-level parsing [P1, pre-T2]
**Section:** `### C1`
No function signature, no module-level entrypoint naming convention, no `if __name__ == "__main__"` shape, no stdin read strategy (`sys.stdin.read()` vs. `json.loads(sys.stdin.buffer.read())`). The plan's locked placement of the adapter at `scripts/codex_session_adapter.py` does not say whether it is also importable (for tests) and how. Until this is specified, T1's fixture tests have no concrete target.

### Finding U2 — Registry expansion list of repositories [P2, pre-T4]
**Section:** `## Repository registry scope`
The candidate list mixes `dotclaude-ecosystem` with deeply nested paths (`D:/APPS/Tsignal 5.0`, `D:/APPS/Obsidian Flow`). Activation-time expansion will bake all of these into the canonical registry template shipped to the repo. State which subset is canonical for the merged template versus which is purely local-to-this-machine evidence. Otherwise a future contributor who runs activation will see 10 repos hardcoded.

### Finding U3 — Test isolation against operator state [P2]
**Section:** `## Test diagram`, `scripts/tests/fixtures/`
The plan says "Tests use temporary homes/state and no network" but does not specify how the activation test isolates `~/.codex/hooks.json` and `~/.claude/state` from the operator's real files. If the test patches `pathlib.Path.home()` only partially (e.g., missing on Windows for `USERPROFILE`), it will write to the real home. Add a "test env override" contract to T4.

### Finding U4 — Live acceptance evidence format [P2, pre-T5]
**Section:** `### C4 — Exact live acceptance`
Acceptance criteria are correct but the *evidence artifacts* are not enumerated. Will T5 capture the full `hook_errors.log` window, the exact `session.binding.v1` and `session.plan.v1` files, and a transcript hash? Without an evidence checklist, "prove the live user-level hook" is reviewer-dependent.

### Finding U5 — Bypassed-trust smoke evidence boundary [P3]
**Section:** `## CEO decisions > Activation choice`
Clear in prose, but not codified anywhere as a "shall not" in the activation step. Add as a single-line constraint in T4's verify list: "bypassed-trust smoke does not satisfy activation."

---

## TOP 3 CHANGES

1. **[P1, A2 + T1] Specify the adapter seam and Codex's hook process model before T1/T2.**
   Pick one file to own format detection (`curator_claims.py`), define the adapter's importable function signature and `__main__` shape, document Codex's stdin/process-per-event contract, and add a back-to-back start/end test against a temp state directory to expose any write-after-write race.

2. **[P1, I1 + E3] Add a Codex-version probe and a trust-revocation expectation.**
   The whole point of this plan is cross-runtime parity. Silent no-op on a Codex upgrade defeats the plan's own premise. Probe `codex-cli --version` at adapter startup, log a bounded reason code on mismatch, and document the minimum version in the canonical template. Likewise, declare what happens to a live session whose hook trust is revoked mid-session.

3. **[P1, I4 + U3] Make activation atomic and isolate it from the real home in tests.**
   Backup-then-replace must restore-on-failure as an automatic rescue, not a documented manual step. Codify that test isolation in T4 with explicit `USERPROFILE`/`HOME` overrides so the activation suite cannot touch the operator's real `~/.codex/hooks.json` under any test failure mode.

---

## 04_seed_1_6

# Audit — ByteDance Seed 1.6

Model: `bytedance-seed/seed-1.6`  
Tokens: 9,499  
Latency: 70.4s

---

### Audit Findings

#### 1. Architectural Soundness
- **Finding**: Unclear definition of "verified" for ecosystem repositories in registry expansion, and no explicit ownership for non-`dotclaude-ecosystem` repo verification logic.
  - Cited Section: ## Implementation slices > C3 > 4; ## Repository registry scope
  - Grade: P2 (important — should fix)
  - Rationale: The activation tool expands the registry to non-`dotclaude-ecosystem` repos but only checks existence and plan-path; no details on eligibility criteria (e.g., repo permissions, activity thresholds) or who owns maintaining that verification logic, risking inclusion of invalid repos.
- **Finding**: No assignment of ownership for cross-OS hook template maintenance (tied to later underspecified cross-OS support gap).
  - Cited Section: ## Implementation slices > C3
  - Grade: P2 (important — should fix)
  - Rationale: The Windows-only template risks breaking non-Windows installations, but no owner is explicitly tasked with updating it for Linux/macOS compatibility.

#### 2. Threading/Async Safety
- **Finding**: No safeguards for concurrent state file writes from multiple Codex sessions to the shared `~/.claude/state` directory.
  - Cited Section: ## Architecture; ## Performance; ## Error and rescue registry
  - Grade: P2 (important — should fix)
  - Rationale: Concurrent `SessionEnd` events from multiple Codex sessions could corrupt shared state files, as the plan does not mention file locking, atomic writes, or sequentialization logic — even though local I/O is identified as a scalability pressure point.

#### 3. Edge Cases
- **Finding**: Canonical Codex hook template only includes absolute Windows commands, failing idempotent installation on non-Windows OSes.
  - Cited Section: ## Implementation slices > C3
  - Grade: P1 (blocker — must fix before implementation)
  - Rationale: The ## Definition of done requires idempotent installation, but the template’s Windows-only commands will fail on Linux/macOS (where Codex runs, per ## Verified current state’s `~/.codex/hooks.json` Unix-style path), violating the installation requirement and preventing cross-OS activation.
- **Finding**: No detail on partial processing of mixed-format transcript files (valid + invalid lines).
  - Cited Section: ## Implementation slices > C2; ## Data, quality, and edge cases
  - Grade: P3 (nice-to-have)
  - Rationale: The plan notes mixed-format files degrade to incomplete evidence but does not specify if valid lines are processed or the entire file is skipped, leaving ambiguity for test validation.

#### 4. Cost/Performance
- **Finding**: No explicit configuration details for the state reaper to bound local JSONL/state-file I/O at scale.
  - Cited Section: ## Performance; ## Architecture and four-path flow
  - Grade: P3 (nice-to-have)
  - Rationale: The plan claims the reaper bounds I/O but does not define reaper frequency, max file deletion limits, or threshold triggers, making scalability assurances unverifiable at 10x/100x session volume.
- **Finding**: No check for duplicate registry entries during ecosystem repo expansion.
  - Cited Section: ## Implementation slices > C3 > 4; ## Repository registry scope
  - Grade: P2 (important — should fix)
  - Rationale: The activation tool could add duplicate repo entries to the registry, leading to redundant state writes and increased I/O without a duplicate check.

#### 5. Integration Risks
- **Finding**: No explicit test for Codex-projected records causing false positives in Curator’s fail-closed claim verification.
  - Cited Section: ## Implementation slices > C2; ## Validation and landing gate
  - Grade: P2 (important — should fix)
  - Rationale: The plan includes `test_curator_claims.py` in validation but no specific test case for Codex-projected records introducing false valid claims, risking weakening the fail-closed guarantee despite projection logic.

#### 6. Underspecified Areas
- Eligibility criteria for "verified ecosystem repositories" beyond existence and plan-path checks (## Implementation slices > C3 > 4; ## Repository registry scope).
- Cross-OS command support in the Codex hook template (## Implementation slices > C3).
- State reaper configuration details (frequency, limits, triggers) (## Performance; ## Architecture and four-path flow).
- Concurrent state file write safeguards (## Architecture; ## Performance; ## Error and rescue registry).
- Partial processing rules for mixed-format transcript files (## Implementation slices > C2; ## Data, quality, and edge cases).

### TOP 3 CHANGES
1. (P1 Blocker) Update the canonical Codex hook template in ## Implementation slices > C3 to include cross-OS absolute commands (Linux/macOS and Windows) and add OS detection logic to the activation tool, ensuring idempotent installation across all Codex-supported operating systems.
2. (P2 Important) Add explicit safeguards for concurrent state file writes (e.g., atomic writes, file locking) in ## Architecture and ## Error and rescue registry, and document these safeguards in the lifecycle state file maintenance documentation.
3. (P2 Important) Define clear eligibility criteria for "verified ecosystem repositories" (e.g., repo permission checks, activity thresholds) in ## Implementation slices > C3 > 4 and ## Repository registry scope, and assign explicit ownership for maintaining this verification logic to the `dotclaude-ecosystem` team.

---

## 07_ppl_kimi_k26

# Audit - Kimi K2.6

Model: `perplexity/kimi-k2.6`  
Source: `perplexity_cdp`  
Selected model option: `Kimi K2.6`  
Tokens: `unknown-web-ui`  
Latency: 73.9s

---

Below is the full architectural audit. Note: the plan was submitted in compacted form — truncated sections are explicitly called out where they affect auditability, but per your rules, omitted spans are not themselves flagged as defects.

Audit: Cross-Runtime Session Lifecycle Adapters — Codex Slice
Architectural Soundness

P1 — Missing adapter ownership boundary (§Architecture)
The architecture diagram is truncated after codex_session_adapter.py | persisted transcript, so the downstream consumers of the session record (e.g., the lifecycle engine, event bus, or storage layer) are invisible. Without seeing who owns the session state after the adapter writes it, there is no way to verify that the adapter is correctly scoped as a leaf writer vs. a stateful coordinator. If the adapter both writes the transcript and triggers downstream hooks, it carries dual responsibility that violates single-responsibility and makes rollback harder.

P2 — No explicit schema version on persisted transcript (§Architecture / §C0)
The plan mentions a "persisted transcript" but no versioning field is visible. If codex-cli changes its SessionStart/SessionEnd payload shape (it's an external CLI tool), the adapter will silently accept stale or malformed payloads with no detection path. A schema_version field pinned to codex-cli 0.x should be in the contract fixture.

P3 — Registry scope is self-declared, not runtime-verified (§Repository registry scope)
The plan states "only existing Git roots verified on this machine." Verification logic is not specified — it's unclear whether this is a git rev-parse --show-toplevel probe at hook install time, at session start time, or only at plan authoring time. A stale registry entry (deleted repo, renamed path) would cause a silent no-op rather than a logged warning.

Threading / Async Safety

P2 — Hook invocation model is unspecified (§Architecture / §Failure map)
It is not stated whether codex_session_adapter.py is invoked synchronously in-process or as a subprocess by the Codex CLI hook runner. If synchronous/in-process: any blocking I/O (file write, network call) on the hook path stalls the Codex session itself — a real UX regression. If subprocess: there is a TOCTOU window between session start and the first transcript write where a crash leaves no record. Neither path is addressed.

P2 — Concurrent session handling not addressed (§Architecture)
The plan is silent on what happens when two Codex sessions start simultaneously (e.g., two terminal windows, or a spawned sub-agent). If the persisted transcript is a single append-only file keyed only by session, concurrent writers without file-locking will produce interleaved JSONL that corrupts session boundaries. Session IDs and file-per-session vs. single-log strategy must be specified.

P3 — No teardown/cleanup guarantee on SessionEnd failure (§Failure map)
The failure map row for hook-trust failure is truncated. It is not visible whether SessionEnd missing (e.g., Codex crash) triggers a timeout-based close or leaves the session open indefinitely. An open session with no heartbeat bound is a memory/state leak.

Edge Cases

P1 — "Hook is untrusted" failure row is truncated (§Failure map)
The safe behavior and evidence columns for the "Hook is untrusted" row are cut off. This is the highest-risk failure mode for a hook-based integration — if Codex refuses the hook due to trust policy, the entire adapter is inert and the operator has no signal. The degraded-mode path (fallback? alert? silent skip?) must be fully specified before implementation of T1 begins, because the red tests in C0 need to assert on this path.

P2 — Ephemeral vs. persisted payload divergence (§C0)
The fixtures cover both persisted and ephemeral payloads, which is correct, but the plan does not specify what differs between them structurally. If the adapter applies identical parsing logic to both, an ephemeral session missing a session_id field will produce a KeyError or a null-keyed record. The contract fixture must explicitly enumerate required vs. optional fields per payload type.

P2 — No replay/dedup guard on SessionStart (§Architecture)
If the hook fires twice for the same session (Codex restart, hook re-registration), the adapter will create a duplicate session record. There is no idempotency key or dedup check mentioned anywhere in the visible plan.

Cost / Performance

P3 — Test suite scope not bounded (§Validation and landing gate)
The pytest invocation targets test_codex_session_adapter.py only, which is correct for a focused gate. However, if the fixture directory (scripts/tests/fixtures/) grows with multiple runtime slices added later (Cursor, Antigravity, Kimi per §Deferred runtime slices), a shared fixture pattern without namespacing will cause test coupling and slow the full suite. Address fixture namespacing before the second runtime slice begins.

P3 — No latency budget stated for hook execution (§Architecture)
For a user-level hook that fires on every Codex session start, even a 50ms synchronous disk write is noticeable. No SLA or timeout ceiling is specified. This is not a blocker for the Codex slice but must be defined before any runtime slice runs on a latency-sensitive path.

Integration Risks

P1 — codex-cli version is truncated in plan (§Verified current state)
The plan records codex-cli 0. — the version string is cut. The adapter's contract fixtures are pinned to a specific CLI payload shape. If the actual installed version differs from what the fixtures assume, the red tests in C0 will pass against a straw-man payload and the adapter will fail in production against the real CLI. The full pinned version must be captured before C0 work begins.

P2 — No contract test for hook registration itself (§C0 / §Validation)
C0 adds red tests for payload parsing, but there is no mention of a test that verifies ~/.codex/hooks.json is correctly written and readable by Codex. The hook registration step is a separate integration surface from payload parsing — it can fail independently (wrong JSON key, wrong path, wrong permissions) without any of the C0 tests catching it.

P2 — Deferred runtimes share no defined interface (§Deferred runtime slices)
The plan defers Cursor, Antigravity, and Kimi with "each next slice begins with native lifecycle-..." (truncated). If the Codex adapter's internal interface (e.g., the SessionRecord dataclass, the adapter base class) is not explicitly frozen as a contract before the Codex slice ships, each deferred slice will independently re-derive it and cause integration churn when they merge back to main.

Underspecified Areas

P1 — Hook trust model mechanics (§Frozen boundaries / §Failure map)
The plan declares "advisory/best-effort only, preserving the operator's accepted C11/C14 posture" but does not explain what C11/C14 are in the context of hook trust. Are these Codex trust-level constants? Internal risk posture codes? Without this definition, any developer picking up T1 cannot correctly implement the trust-rejection handling path.

P2 — Rollback procedure is a table stub (§Failure map)
The failure map exists but every row's "Safe behavior" and "Evidence" columns are truncated. A rollback plan that cannot be read is not a rollback plan. The hook uninstall path (removing ~/.codex/hooks.json entry, clearing persisted state) must be written out explicitly, especially since this is a user-level hook that persists across Codex restarts.

P2 — Definition of done is truncated (§Definition of done — Codex slice)
Two of the three DoD bullets are cut. The visible bullet ("A user-level Codex hook is active for every new Codex session" and "A persisted Codex ses-...") leaves the acceptance criteria incomplete. Incomplete DoD means the landing gate (python -m pytest) may pass while the actual operator expectation is unmet.

TOP 3 CHANGES

1. P1 — Recover and fully specify the hook trust failure path before any code is written
The "Hook is untrusted" row in §Failure map is truncated, and §Frozen boundaries references C11/C14 posture without definition. This is a blocker: the C0 red tests in T1 must assert on the trust-rejection path, and they cannot be written correctly until the degraded-mode contract is explicit. Reconstruct the full failure map row and define C11/C14 inline in the plan before T1 begins.

2. P1 — Pin and record the full codex-cli version string in §Verified current state, and bind fixtures to it
The version is truncated at codex-cli 0.. The C0 contract fixtures are only meaningful if they reflect the exact payload shape of the installed CLI version. Add a codex-cli --version output capture to the plan, pin it in the fixture file header, and add a pre-test assertion that the installed version matches the pinned value. Without this, green C0 tests give false confidence.

3. P1 — Define the SessionRecord adapter interface as a frozen contract before the Codex slice ships
The deferred runtimes (Cursor, Antigravity, Kimi) will each implement their own adapter. If the shared interface — the base class, the SessionRecord schema, and the event emission contract — is not frozen now, each slice will independently diverge and produce integration debt at merge time. Add an explicit AdapterBase definition (even a stub dataclass + abstract methods) to C0, make the Codex adapter implement it, and gate the slice on that interface being code-reviewed and merged first.

---

## 20_claude_cli_opus

# Audit - Claude Opus via shared audit CLI

Target: `2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`  
Model: `opus`  
Source: `claude_cli_shared`  
Runtime boundary: `repository-neutral audit only; no WatchF runtime`  
Latency: 154.91s

---

# Independent External Review — Fail-Closed

**Target:** `2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`
**Transmission:** `INCOMPLETE`
**Verdict:** `BLOCKED` — no CLEAR attestation can be issued on this transmission.
**Method:** Document-only. I ran no tools and inspected no repository state, per the instruction not to infer beyond the transmitted target.

---

## 1. Transmission status (fail-closed)

The target does not contain the artifacts your instruction told me to follow. Specifically, the transmitted text has **no embedded review contract**:

- no severity vocabulary (nothing defines BLOCKER/MAJOR/MINOR, P-levels for findings, or CLEAR/BLOCK semantics for an external reviewer);
- no required final attestation template or wording;
- no transmission field to set;
- no reviewer scope, evidence requirements, or acceptance thresholds.

The closest structures present are the **GSTACK REVIEW REPORT** table (which uses `CLEAR / PENDING / N/A` as *review-run* statuses, not finding severities) and the CEO section's `HOLD SCOPE` / `CONTINUE` verdicts. Neither is a reviewer contract, and I will not reverse-engineer one and then claim compliance with it.

Also absent, and referenced as load-bearing by the target:

- the three linked predecessor plans, including `2026-07-25_session_lifecycle_and_hook_hardening_r1.md`, whose contracts the target itself calls **a ship blocker** for backward compatibility;
- the carved skill's `sections/review-sections.md` (the target notes it was missing and that the embedded 11-section `SKILL.md` source was substituted — that substitution is unverifiable from here);
- the pinned head `e2397edce91221e0df0987eaecd381183192dd8c`, so this is **not** an exact-head review.

**Consequence:** fail-closed. Retransmit with the review contract and the predecessor lifecycle plan before any CLEAR is sought.

**Contract substitution used below (mine, not the target's):** `BLOCKER` = must be resolved before implementation lands; `MAJOR` = must be resolved before the landing gate passes; `MINOR` = fix in-slice or record as accepted; `NOTE` = no action required. Findings are stated so they remain valid under any reasonable substituted vocabulary.

---

## 2. BLOCKER findings

### B1 — Review contract not transmitted
As above. A fail-closed review whose contract is absent cannot return anything but `BLOCKED`. Everything below is offered as substantive work product, not as contract-compliant sign-off.

### B2 — Registry expansion is an unrollbackable change to the shipped Claude path
C3 step 4 *"expands the canonical registry template to the verified ecosystem repositories"* — nine new roots beyond `dotclaude-ecosystem`, which "Verified current state" says is the registry's entire current coverage.

Three problems compound:

1. The registry is shared with the shipped Claude lifecycle (the reuse table lists `scripts/session_state.py` as the single "Repository resolution" owner, reused unchanged). Adding nine roots therefore changes **Claude Code runtime behavior** in those nine repos: sessions that previously fell into the "unregistered → minimal advisory context" path will now create `session.plan.v1` / `session.binding.v1` state. That directly contradicts the DoD item *"Existing Claude Code behavior and schemas remain backward compatible."* Schemas remain compatible; behavior does not.
2. The regression suite cannot catch this. `python -m pytest -q scripts/tests` exercises code, not the machine-local registry contents. The gate as written would pass while the behavior change ships.
3. **Emergency off does not reverse it.** All four documented steps concern `~/.codex/hooks.json` and lifecycle state files. Restoring the hook backup disables the Codex adapter and leaves nine repos registered for Claude. The stated *"Reversibility is 5/5: restore the exact pre-activation hook backup"* is false for the change C3 actually makes.

**Required:** either (a) split registry expansion out of this slice entirely, or (b) back up and hash the registry template alongside the hook file, add its restoration as an explicit emergency-off step, and add a DoD line acknowledging the intended Claude-side behavior change with a live check in a registered non-`dotclaude-ecosystem` repo. Silently widening the shipped path's blast radius inside an "adapter" slice is the single largest gap in this plan.

---

## 3. MAJOR findings

### M1 — `resume | clear | compact` SessionStart events are unspecified
"Verified current state" records that Codex's `SessionStart` matchers are `startup|resume|clear|compact`. C1 then says only *"Allow only `SessionStart` and `SessionEnd`"* with no branching on `source`, and C4 proves exactly one path: *"a brand-new persisted Codex session."*

Compaction fires `SessionStart` **repeatedly inside a single session**. The plan never states whether a second start for an existing `session_id` is a no-op, an idempotent re-injection, or a second `session.plan.v1`/`session.binding.v1` write. All three are plausible readings of "Delegate persisted events to the existing router/lifecycle owners." The failure map, the four-path flow, the failure-modes registry, and the test diagram all omit the case.

**Required:** state the intended behavior per `source` value, add a fixture per matcher in C0, and add a repeated-start assertion to C4 (start → compact → verify exactly one binding).

### M2 — `SessionEnd` `reason` → verdict mapping is undefined
DoD asserts *"Codex `SessionEnd` persists one of the existing coarse lifecycle verdicts."* The prototype is recorded as supplying `source`/`reason`, but no mapping table, no enumeration of Codex reason values, and no fixture per reason appears anywhere. As written, the DoD item is unverifiable and T3/T2 have no acceptance criterion for it.

**Required:** an explicit reason→verdict table, plus the default for an unrecognized reason (which should be an honest coarse verdict, not the most favorable one).

### M3 — Hook file replacement is not specified as atomic
C3 backs up before replacing, and the chaos test covers interruption *between backup and replacement*. Nothing covers a torn write **during** replacement. The failure map's row (`write/replace failure → keep backup, nonzero install`) presupposes a clean failure; a half-written `~/.codex/hooks.json` is invalid JSON at user level, affecting every Codex session — precisely the risk the CEO section flags. The backup exists, but recovery becomes a manual operation on an already-degraded host.

**Required:** specify temp-file + atomic rename onto `~/.codex/hooks.json`, and extend the chaos test to kill the process mid-replacement and assert the target is either wholly old or wholly new.

### M4 — Internal contradiction on mixed-format transcripts
C2: *"mixed-format files degrade to incomplete/unverified evidence."*
CEO review: *"Provider detection is structural per record; no global provider flag."*

These are not the same rule. Per-record structural detection implies a mixed file projects both formats normally; the C2 rule implies contamination downgrades the whole file. Under the C2 reading, a single stray `response_item` line in a Claude transcript would downgrade previously-verified Claude evidence — a regression in the shipped path that the "old Claude fixtures remain green" check would not catch, because those fixtures are pure.

**Required:** pick one rule, state it in C2, and add a mixed-file fixture asserting the chosen behavior explicitly.

### M5 — Windows path normalization for registry matching is unspecified
Four of the ten candidate roots contain spaces (`D:/APPS/Tsignal 5.0`, `Obsidian Flow`, `Hue Flow`, `Vavo OS`), the registry is written with forward slashes while Codex will supply a native `cwd`, and drive-letter case varies in practice. The plan asserts a *"canonical repo-relative path filter"* for the write-attribution threat but says nothing about canonicalization for **repo resolution**.

The failure mode is silent and indistinguishable from correct behavior: a normalization miss routes a registered repo down the "unregistered → minimal advisory context, exit 0" path. DoD parity would read as satisfied in C4 (which uses one repo) while failing in the others.

**Required:** state the normalization rule (case-folding, separator, resolved/`realpath`, trailing separator, UNC/junction handling), and make C4 acceptance run in a registered root **with a space in its path**.

### M6 — Asymmetric lifecycle leaves dangling bindings with no owner
The plan handles `SessionEnd` with a missing binding (failure-modes registry, "session closes"). It does not handle the inverse: a binding created at start whose close never lands — because `SessionEnd` arrived with a null `transcript_path` (which C1 unconditionally treats as a no-op regardless of event kind), because the delegate raised and the adapter exited 0, or because the host died. `scripts/state_reaper.py` is listed as owning "Scratch retention," not open bindings.

Because the entire host boundary is fail-open with `exit 0`, this failure is silent by construction: a bounded log line and a permanently open session.

**Required:** define the null-transcript rule separately for `SessionEnd` (a close should not require the transcript to persist a coarse verdict), name the owner of stale open bindings, and add a test row for "start persisted, end degraded."

---

## 4. MINOR findings

- **m1 — No timeout value anywhere.** C3 says "bounded timeouts," the failure map has an "Adapter exceeds timeout" row, and the acceptance "enforces the configured hook timeout" — but no number is stated. For a hook on the start path of every Codex session, the gate cannot be checked objectively. Specify the value.
- **m2 — Duplicate `call_id` behavior is implied, not stated.** It appears in the edge-case list and as "exact unique" in CEO prose; C2 itself only says "pair only by exact `call_id`". State the drop-both rule in C2.
- **m3 — C4 destroys its own evidence.** *"Delete only the explicitly created disposable test session"* removes the state that proves acceptance. Require the evidence (binding/plan identifiers, transcript path equality, verdict, elapsed time) be captured to the PR before deletion.
- **m4 — No task owns `sync_agent_rules.py --check`.** It is in the regression gate; T1–T5 name no rule/doc files. Either confirm the new scripts need no rule sync or add it to T4.
- **m5 — No live degraded-path check.** C4 proves the happy path and the ephemeral no-op. Given fail-open/`exit 0`, the most likely production failure is a silent delegate error; a live check that a forced delegate failure leaves the Codex session usable and produces exactly one bounded log line is cheap.

---

## 5. NOTES (no action required)

- The fail-open host boundary and the fail-closed Curator verification are used correctly and are not in tension — but the plan never says so in one place, and a future reader will misread it. One sentence in "Frozen boundaries" would prevent that.
- Approach A/B/C analysis, the reuse table, the "zero rows with `Rescued=no`, `Test=no`" claim, and the refusal to fabricate session identity for hosts without reliable events are all sound and specific. The rejection of Approach C on scope grounds is correct for R1.
- The `.claude/state` retention decision is correctly argued: renaming would convert an adapter into a migration.

---

## 6. What I could not review

- Backward compatibility against the shipped predecessor lifecycle contract — plan not transmitted, and the target itself calls this a ship blocker.
- Whether `session_router.py`, `session_lifecycle.py`, `session_state.py`, or `curator_claims.py` behave as the reuse table asserts.
- The `codex-cli 0.145.0` hook contract, the `~/.codex/hooks.json` schema, and the prototype findings — all reported, none independently verifiable here.
- Head identity `e2397ed…`, branch cleanliness, and the stash claim.
- The 11-section skill source substitution.

---

## 7. Attestation

The target did not transmit an attestation template; the following is my own wording, and is **not** a claim of compliance with the target's (absent) review contract.

> I reviewed the complete text transmitted as `2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md` and nothing else. I executed no tools, read no files, and inspected no repository, branch, or commit state. All findings above are derived solely from internal evidence in the transmitted text. I did not verify the pinned head, the predecessor plans, the Codex hook contract, or any claim under "Verified current state"; those are recorded as unreviewable in §6.
>
> **Transmission: INCOMPLETE** — the embedded review contract, severity vocabulary, attestation template, and transmission field were not present in the target, and the linked predecessor plans were not supplied.
>
> **Verdict: BLOCKED.** Fail-closed on B1. Independent of B1, B2 must be resolved before implementation: the C3 registry expansion changes shipped Claude Code behavior in nine repositories, is not covered by the stated regression gate, and is not reversible through the documented emergency-off path, contradicting both the backward-compatibility DoD item and the "Reversibility is 5/5" claim.
>
> No CLEAR is issued. Retransmit with the review contract and the predecessor lifecycle plan for a contract-compliant review.

