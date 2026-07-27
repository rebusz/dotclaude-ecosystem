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