# Audit - Sonar 2

Model: `perplexity/sonar-2`  
Source: `perplexity_cdp`  
Selected model option: `Sonar 2`  
Tokens: `unknown-web-ui`  
Latency: 57.3s

---

I'll audit the visible contract as presented. Given the heavy compaction, the audit focuses on what is explicitly stated and flags what is structurally implied but missing.

Audit: Session Lifecycle Router, Curator, and Hook Hardening
1. Architectural Soundness

[P1] session_router.py ownership and boot contract is underspecified.
The architecture block shows SessionStart ---> session_router.py (facts only) but is truncated immediately after. There is no stated owner for the router's output — who reads the emitted facts, in what format, and what happens if the router itself errors on startup? A router that fails silently before any hook is registered leaves the session with zero guardrails and no observable indication of the failure.

[P2] Curator / Router separation is implied but never contracted.
The title names three distinct components (Router, Curator, Hook Hardening) but the Architecture section is cut before any interaction diagram is visible. It's unclear whether the Curator is a separate process, a class inside the router, or a post-session hook. Without a defined boundary, two implementers can build two incompatible interpretations.

[P3] The "declared intent" survival mechanism across compaction is not architecturally grounded.
The Executive Decision states intent must "survive compaction," but no durable store (file, sidecar, environment variable) is named. If this is written to session_plan_<session_id>, that conflicts with Invariant 1 ("The session plan is scratch, not truth").

2. Threading / Async Safety

[P2] Hook execution model is unspecified.
The settings.json hook entries (referenced in Rollback) fire synchronously or asynchronously — the plan never says. If hooks run on the main Claude Code thread and perform any I/O (file write, network check), they block the session start/stop hot path. The Token Budget section begins to address this but is truncated before any latency acceptance criterion is visible.

[P2] Trigger matching on pasted/quoted content implies a parsing step on every user message.
The Test Plan row "Operator writes 'drift' in their own sentence → steering fires" confirms the matcher runs at message ingestion time. There is no stated threading model for this check — if it's synchronous regex over potentially large pastes (the "Why Now" section describes a Reddit thread paste), worst-case latency is unbounded.

[P3] No mention of lock or mutex strategy for any shared state the router might write (e.g., session metadata file). If two hooks fire near-simultaneously (SessionStart + a rapid user message), a TOCTOU race on the metadata file is possible.

3. Edge Cases

[P1] Degraded mode on hook failure is absent.
The Rollback section only describes the kill switch (remove entries from settings.json). There is no stated behavior for a partial failure — e.g., the SessionStart hook registers but the SessionStop hook crashes before writing a verdict. The "verified verdict at close" (Executive Decision) is silently skipped with no alert.

[P1] The quoted/fenced/pasted content exclusion is in the Definition of Done as a checkbox, not in the architecture.
"Trigger matching ignores quoted, fenced, and pasted content, proven by a regression" is a DoD item, meaning it's not yet designed. Shipping the drift-check without this exclusion is the plan's own identified most-likely failure (Author Pre-Mortem §1). This is a P1 because the Pre-Mortem explicitly calls it "most likely."

[P2] No handling for a session that is killed externally (OS kill, IDE crash) before the SessionStop hook fires. The "verified verdict at close" guarantee cannot be upheld in this scenario. No fallback verdict or stale-session GC is described.

[P2] The collision verdict in Phase 0 ("restatement and collision verdict") is truncated. If two concurrent sessions declare the same intent/skill chain, the collision resolution logic is invisible. This gap could cause silent goal-clobber.

4. Cost / Performance

[P2] Token Budget section is truncated before any numeric criterion is visible.
The section opens with "The hooks are a permanent tax on every session, so budgets are acceptance criteria" — but the actual numbers are cut. Acceptance criteria that exist only in omitted text cannot be verified during implementation or review. The reviewer cannot confirm whether the SessionStart prompt overhead has been bounded.

[P3] Throttling for the drift check is mentioned in the Pre-Mortem ("mitigated by throttling") but no throttle window, cooldown, or backoff strategy is specified anywhere visible. Without a concrete number, each implementer will choose an arbitrary value.

5. Integration Risks

[P2] settings.json is the sole integration point and its schema is never shown.
The hook entries are described only by their removal path. No field names, event names, or script invocation signatures are visible. A schema mismatch between what Claude Code fires and what session_router.py expects will silently no-op all hooks — the exact failure mode that motivated this plan.

[P2] The "frozen product contract" / Invariant 1 creates a tension with the survival requirement.
Invariant 1 says session_plan_<session_id> is scratch. The Executive Decision requires declared intent to survive compaction. These two requirements point at the same artifact but assign it contradictory durability. The Recorded Decisions table is truncated before D1's resolution is visible, so it's unknown whether this was resolved.

[P3] The GSTACK Review Report table is truncated before any findings are listed. If that review produced integration-relevant findings, they are invisible to this audit.

6. Underspecified Areas

[P1] Trigger matching specification is absent.
The Test Plan has one visible scenario but no specification of the matching algorithm — no regex, no token classifier, no heuristic. "Drift" detection on operator prose is a non-trivial NLP problem. Without a spec, the regression test in the DoD has no ground truth to test against.

[P1] "Verified verdict at close" is undefined.
The Executive Decision names this as the core deliverable, but no schema, storage location, consumer, or failure handling for the verdict is visible anywhere in the plan. This is the plan's central output and it has no design.

[P2] Skill chain and persona fields are mentioned in Phase 0 Goal §1 (truncated) but never appear in the Architecture or Implementation Slices. It is unclear how they are declared, stored, or used by the router.

[P2] Implementation Slices are described as "ordered and independently shippable" but the slice list is truncated after "S0 is a prerequisite." The dependency graph between slices is invisible, making sprint planning impossible.

TOP 3 CHANGES

1. [P1] Define and implement "verified verdict at close" before any other slice ships.
This is the stated purpose of the entire plan (Executive Decision) and has zero visible design. Before writing any code, produce: the verdict schema (fields, types), its storage location (not session_plan_<session_id> per Invariant 1), the consumer that reads it, and the fallback when SessionStop never fires. Without this, all other work is scaffolding for an undefined output.

2. [P1] Specify the trigger-matching algorithm with exclusion zones as a standalone spec, not a DoD checkbox.
The Author Pre-Mortem identifies drift-check noise as the most likely failure. The Definition of Done defers the quoted/fenced/pasted exclusion to a regression test with no spec behind it. Write the matching rule (regex, classifier, or heuristic), enumerate the exclusion cases (quoted, fenced, pasted, tool output), and make this the input to implementation — not a post-hoc regression discovery.

3. [P1] Harden hook failure into a defined degraded mode with an observable signal.
The kill switch (remove from settings.json) is all-or-nothing. Add a degraded mode: if any hook in the chain errors, write a sentinel file or log entry that is visible to the operator on the next session open. This closes the silent-failure gap for the SessionStop verdict loss and the external-kill edge case simultaneously.