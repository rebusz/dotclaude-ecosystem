# mode auditppl - Synthesis

**Plan**: `2026-07-25_session_lifecycle_and_hook_hardening_r1.md`
**Run date**: 2026-07-25
**Models**: Best, Sonar 2, Kimi K2.6

---

## Instructions for Claude

Synthesize the 3 Perplexity audits below. For each finding:

1. **Consensus P1** - appears in 2+ audits -> MUST fix, apply to plan immediately.
2. **Unique P1/P2** - only 1 model flagged but architecturally valid -> apply if it fits frozen boundaries.
3. **Discard** - P3 style noise, contradictions with frozen boundaries, hallucinated requirements -> skip.

For each item to apply: state the **plan heading**, the **change**, and the **reason**.

---

## Best

# Audit - Best

Model: `perplexity/best`  
Source: `perplexity_cdp`  
Selected model option: `Best
Selects the best available model`  
Tokens: `unknown-web-ui`  
Latency: 120.5s

---

Now I have the full uncompacted plan. This is a thorough document — I can perform a proper audit.

Audit: Session Lifecycle Router, Curator, and Hook Hardening

This plan is well-structured and unusually self-aware. The CEO Review has already resolved 11 findings (including one critical). The remaining audit below covers what that review did not close or what it introduced.

1. Architectural Soundness

[Architecture / Implementation Slices]

P1 — Schema version is declared but migration strategy is absent. session.plan.v1 is now versioned (Finding 1.1, resolved in CEO Review), and readers treat an unrecognized version as absent . However, the plan has no stated policy for what happens when session_state.py writes v2 during a future hardening pass while old hooks on a second machine still read v1. A version-mismatch on resume silently falls to "no plan" — indistinguishable from a missing file — so a stale-install scenario produces invisible regressions with no log line. The hook_errors.log path only fires on exceptions, not on a clean version miss. Needs: a one-line UNRECOGNIZED_VERSION entry to the error log on version mismatch.

[Architecture]

P2 — session_state.py is the single write owner, but concurrent write risk is only partially closed. Finding 2.1 closed the reaper race. It did not address two sessions in the same directory writing session_plan_<id>.json simultaneously through session_state.py. The os.replace atomic-write pattern handles the individual write, but if SessionStart fires for two sessions simultaneously (e.g., a worktree shared across two terminals), both will resolve the same registry entry and emit identical additionalContext — which is harmless — but the drift check (S2) in each session will read the other session's scratch file if both share the same session_id source (unlikely) or may both believe themselves the authority for that working directory. The plan's invariants protect downstream systems, but the multi-session-per-directory case is unspecified.

[S4 — /curator]

P2 — Claim extraction from JSONL is a model step, but the context window for that step is unspecified. The plan says "bounded transcript window" but never states the bound in tokens or lines. The curator runs once at session close; if a session is 200+ turns, and each turn is 2–5 KB of JSONL, even a "bounded" window could be 50–100 KB before summarization. The token budget table (§ Token budget) covers injection paths but not the curator's own model call. This is the one place in the plan where a model call is explicitly introduced inside a hook — and it has no cost ceiling.

2. Threading / Async Safety

[S2 — Drift Check on PostToolBatch / S3 — SessionEnd]

P2 — Hook wall-time budget exists; timeout handling path is underspecified. The plan sets a 2-second fail-open timeout (§ Token budget), and CEO Review added p95 targets for SessionStart. However, PostToolBatch can fire after every parallel tool batch — including parallel file-write batches that are themselves I/O-heavy. If the subprocess running session_drift.py is killed by the 2-second timeout, the plan says the session is "unaffected" and "failure recorded to a log" (Finding 8, resolved). What is not stated: whether the timeout kill is SIGTERM-then-SIGKILL or only SIGTERM, and whether a Python process that has already opened session_plan.json for writing releases the lock before it is killed. On Windows (the deployment target, given D:/dotclaude paths) subprocess.TimeoutExpired + kill() does not guarantee file handle release; a subsequent session_state.py write from the same session may hit PermissionError, which falls to "treat as no plan" — losing the checkpoint silently.

[S3 — state_reaper.py]

P3 — Reaper is invoked from SessionEnd, which is itself a hook. If SessionEnd is killed by its own 2-second timeout while the reaper is mid-scan (e.g., deleting 1944 files on a spinning disk), the reaper leaves the directory partially cleaned and its own internal state inconsistent. This is tolerable since the next reaper run is idempotent — but the plan does not state that the reaper is re-entrant/idempotent by design.

3. Edge Cases

[S1 — Repo Registry / Frozen Contract Invariant 5]

P1 — The "operator-authored text only" invariant for trigger matching has no specified enforcement point for PostToolBatch. Invariant 5 states triggers must originate with the operator . Slice 1 (the hotfix, ad12cf2) closed this for UserPromptSubmit — pasted content in the prompt. But PostToolBatch fires after tool outputs are processed, and tool outputs (file reads, shell command results, web fetch results) can contain trigger keywords that appear in data["tool_results"]. If session_drift.py reads data["tool_results"] to understand "what has happened since the last check," it inherits the same injection surface the hotfix closed. The plan's test matrix tests fenced code and pasted text in the prompt, but has no test for a trigger keyword appearing in tool output fed to the drift check.

[S3 — SessionEnd verdicts]

P2 — CHECKPOINT verdict condition is underspecified relative to HANDOFF. The plan defines three verdicts: ARCHIVE-OK, HANDOFF, CHECKPOINT. The test fixtures define HANDOFF as "merged with open items" and CHECKPOINT as "unmerged with large context" . But the intersection — unmerged and open items and small context — has no stated verdict. More critically, "large context" is an unsigned threshold; it is not in the token budget table, not in Definition of Done, and not in the test matrix as a parametrized dimension. An implementation without this ceiling will choose an arbitrary cutoff.

[S4 — /curator / Security Finding 3.1]

P2 — Redaction strategy delegates to terminal_evidence.py helpers, but that module's scope is terminal output, not JSONL transcripts. Finding 3.1 was resolved by re-using terminal_evidence.py's redaction helpers . However, JSONL session transcripts carry structured assistant/tool/user message objects — not raw terminal lines. If terminal_evidence.py's regexes operate on flat strings and the JSONL is passed as parsed objects, the redaction may not traverse nested content arrays (e.g., tool_result with a list of content blocks). This is a boundary mismatch rather than a missing feature, but it is the highest-sensitivity data path in the plan.

4. Cost / Performance

[Token Budget]

P2 — PostToolBatch firing rate is throttled, but the throttle dimension is "batch count and elapsed context" — two independent axes with no stated combination rule. The plan says "at most once per N batches" but N is not defined anywhere in the plan text . It appears in the pre-mortem as a mitigation, in the test plan as a gate, and in the DoD as a measurement target — but the actual value and the combination logic (batch count OR elapsed time? AND? whichever fires first?) is left to implementation. This is a budget gap, not a tuning preference, because the acceptance criterion ("measured firing rate stays within budget") cannot be evaluated without knowing what budget the implementation is supposed to hit.

[S0 / Current-state evidence]

P3 — answer_footer.py pricing fix is in scope for S0 but its test coverage is not in the test matrix. The current-state evidence section notes the footer silently falls back to Sonnet pricing for claude-opus-5, understating cost ~5x . S0 brings it under version control; the DoD requires pricing to cover the Claude 5 family. The test plan includes "Unknown model id" and "claude-opus-5 session" scenarios — but these are listed among the new scenarios without specifying which test file owns them. Given S0 produces no behavior change (byte-identical copy), the pricing fix must land in a separate behavioral commit, but the slice description does not separate the copy from the fix.

5. Integration Risks

[Reuse map / S4 — /curator]

P2 — /curator delegates to truthctl snapshot --require ..., but the --require flag's contract with a missing or stale TruthDeck snapshot is documented in the TruthDeck R1 plan, not here. Finding 2.1 in this plan's own error map covers truthctl absent → all claims UNVERIFIED. It does not cover truthctl present but snapshot stale (e.g., snapshot is from 3 hours ago, HEAD has moved). The curator would reproduce a stale gate result verbatim without flagging staleness to the operator, potentially marking a claim VERIFIED against an outdated baseline. The reuse map says "gate results reproduced verbatim" — verbatim reproduction of a stale result is silent misinformation.

[Deployment — CEO Review Finding 9]

P2 — Hook wiring is a manual step with no drift detection. CEO Review accepted this (Finding 9, "recorded rather than solved") . That is a legitimate call for an R1 plan. However, the ship-on-default rule ("hooks land enabled") combined with a manual wiring step creates an asymmetry: a new machine runs zero hooks silently (no error, no warning), but the operator may believe hooks are active because the modules are installed. The accepted risk is that this is an installer-ownership problem. The gap not addressed: should session_router.py emit a one-line warning when it runs but detects its own SessionStart entry is absent from settings.json? That would be self-diagnosing within the existing module scope.

[S6 — Adversarial personas]

P3 — operator-0931 persona assumes a fixed market open time, but the operator trades across instruments that may have different sessions (futures pre-market, options, equities). This is a soft specification gap — the persona description is a prompt, not code — but if it is baked into a prompt file it will silently mis-frame the question for instruments that open at different times.

6. Underspecified Areas

[S2 — Drift check throttle]

P1 — N (batch count) and the elapsed-context threshold are not defined. Cited above in §4. This is the single most important numeric gap in the plan: the drift check's firing frequency is the primary knob for whether S2 ships as a useful tool or as the noise the pre-mortem names as the most likely failure. Implementation will invent a value; the plan provides no acceptance range. Must be defined before S2 implementation begins.

[S4 — /curator model call cost ceiling]

P2 — No token/cost ceiling for the claim-extraction model step. Cited above in §1. The token budget table covers all hook injection paths but omits the one explicit model call introduced by the plan. At minimum, the max transcript window (in lines or chars), the model tier to use, and the per-invocation cost ceiling should appear alongside the other budget rows.

[S3 — CHECKPOINT threshold]

P2 — "Large context" is an undefined threshold. Cited above in §3. This needs a concrete value (e.g., ≥ 80% of model context window, or ≥ N turns) before session_end.py can be implemented determinably.

[S5 — /sweep value threshold]

P3 — "Findings above a value threshold are appended to IDEA_BOX.md" — but the value threshold is undefined. A silent always-append or a never-append both satisfy the spec as written. This is less urgent than the drift throttle but will produce either noise or a useless skill.

TOP 3 CHANGES

1. P1 — Define the drift-check throttle N and context-elapsed threshold before S2 implementation begins.
The pre-mortem names noise as the most likely failure mode, and the DoD gates on a measured firing rate — but neither N nor the elapsed threshold appears anywhere in the plan. Without these values the acceptance criterion is unevaluable and implementation will invent an arbitrary default. Concretely: add a [drift_throttle] row to the Token Budget table with min_batches_between_checks: <N>, min_elapsed_chars: <M>, and the combination rule (whichever-is-larger fires first). This is a one-sentence addition that unblocks deterministic implementation and makes the DoD measurable. (Sections: S2, Token Budget, Definition of Done)

2. P1 — Add an injection-surface test for PostToolBatch tool-result content, mirroring the S1 hotfix.
The plan_keyword_detector.py hotfix (ad12cf2) closed trigger injection via pasted prompt text. session_drift.py will read "what has happened since the last check" — which necessarily includes tool outputs — and therefore inherits the same injection class. The test matrix has no scenario covering a trigger keyword in a tool result. Add: "Tool output contains drift/ultracode → drift check does not fire steering" as a required regression scenario in test_session_drift.py, and specify that session_drift.py reads only fields authored by the operator (e.g., user-turn text) when scanning for context, never tool-result payloads. (Sections: Why now, Frozen contract Invariant 5, S2, Test plan)

3. P2 — Add a token/cost ceiling for the /curator claim-extraction model call to the Token Budget table.
The Token Budget section covers every hook injection path but omits the one explicit model call in the plan. A long session with 200 turns and 3 KB/turn of JSONL produces ~600 KB of transcript. Even a "bounded window" is unbounded without a stated limit. Add a curator claim-extraction row: max window in characters (e.g., last 20,000 chars of JSONL), model tier (specify whether this uses the session's active model or a cheaper summarizer), and a per-invocation cost ceiling. This closes the only unceilinged cost path in an otherwise budget-disciplined plan and makes the DoD's "every token budget measured and met" claim complete. (Sections: S4 — /curator, Token budget, Definition of Done)

---

## Sonar 2

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

---

## Kimi K2.6

# Audit - Kimi K2.6

Model: `perplexity/kimi-k2.6`  
Source: `perplexity_cdp`  
Selected model option: `Kimi K2.6`  
Tokens: `unknown-web-ui`  
Latency: 53.7s

---

I will audit the visible contract on its own merits, treating all omitted spans as noted in the plan header (not defects).

Audit: Session Lifecycle Router, Curator, and Hook Hardening

The plan describes a Claude Code session lifecycle system: a session_router.py that ingests "facts only," hooks fired at SessionStart/SessionEnd, a drift-detection trigger, and a settings.json kill switch. Because roughly 60–70% of the body was compacted away, many findings below are elevated precisely because the omitted spans cannot be audited — those are the most dangerous blindspots.

Architectural Soundness

P1 — Architecture section is almost entirely omitted. The ## Architecture block shows only the first two lines of an ASCII diagram (SessionStart ---> session_router.py (facts only) and |). There is no visible description of: what consumes the router's output, how the curator relates to the router, who owns the verdict state between start and close, or how the hook chain is ordered. With no ownership map, implementors will make incompatible assumptions. Requires full diagram before any slice is built.

P2 — "Facts only" constraint on session_router.py is unenforceable as stated. The plan declares the router receives "facts only" but defines no schema, validation layer, or rejection policy for non-fact inputs. Without a contract object (dataclass, TypedDict, or Pydantic model), any caller can pass arbitrary data and the constraint becomes documentation fiction.

P2 — Verdict state ownership is unclear. The Executive Decision mentions "a verified verdict at close" but no component is named as the authoritative store of that verdict between SessionStart and the close hook. If the process crashes mid-session, the verdict is lost. No persistence or recovery path is visible.

Threading / Async Safety

P1 — Hook execution model is unspecified. The ## Token budget section acknowledges hooks are "a permanent tax on every session," implying they run synchronously on a hot path. Whether the drift-check trigger runs in the same thread as the shell, in a subprocess, or via async I/O is entirely omitted. A blocking regex scan over large pasted content (the exact scenario described in ## Why now) on the main thread is a latency blocker.

P2 — Trigger matching and quoted-content exclusion are not designed, only promised. The ## Definition of Done states "trigger matching ignores quoted, fenced, and pasted content, proven by a regression test," but no implementation detail appears. A stateful parser that tracks fence depth and quote context requires careful re-entrancy handling — this is non-trivial to get right under concurrent hook invocations.

Edge Cases

P2 — Degraded-mode behaviour on hook failure is missing. The ## Rollback and emergency off section documents only the kill switch (remove four entries from settings.json). There is no degraded mode: what happens if a single hook raises an unhandled exception? Does the session proceed silently, block, or surface a warning? Silent pass-through is a correctness risk; hard blocking is a usability risk.

P2 — The Reddit-paste scenario (the motivating case) has no explicit test. ## Why now describes the trigger event as an operator pasting a public Reddit thread. The ## Test plan shows only a generic "Operator writes 'drift' in their own sentence" case. The motivating edge case — pasted external content containing trigger words — must be a regression test but is absent from the visible test plan.

P3 — No timeout defined for drift-check hook. The ## Author pre-mortem names "drift check becomes noise" as the most likely failure, mitigated by throttling. But no maximum wall-clock budget per hook invocation is specified, leaving the throttle implementation underspecified.

Cost / Performance

P2 — Token budget section is truncated at the critical line. The sentence beginning "SessionSta" is cut off mid-word. The token budgets are labelled "acceptance criteria," making this a functional gap: the implementation slice authors have no numeric target to code against or CI gate to enforce.

P3 — No memory ceiling for pasted-content buffers. If the drift scanner buffers full message content to identify quoted/fenced blocks, large pastes (e.g., multi-thousand-line code dumps) could accumulate in memory across a long session. No ceiling or streaming parse strategy is mentioned.

Integration Risks

P1 — settings.json schema change is not versioned. The kill switch depends on removing four hook entries from settings.json. If the schema evolves between slices, a partial rollback (removing some but not all entries) could leave the system in an inconsistent state. No migration or schema version field is referenced.

P2 — session_plan_<session_ invariant is truncated. Frozen product contract Invariant 1 reads "The session plan is scratch, not truth. session_plan_<session_" — the rest is cut. This is a frozen invariant, meaning downstream tooling may depend on whatever filename or ID pattern was specified. The omission is a contract gap.

P2 — Decision table is partially omitted. ## Recorded decisions shows only D1 ("Plan shape → Split: defects as a separa…"). If D2–Dn include decisions about hook ordering, file ownership, or interface contracts, those are silently missing from the audit surface and could conflict with slice implementations.

Underspecified Areas

P1 — Implementation slices are described only in prose header, zero detail visible. The ## Implementation slices section contains only the ordering rationale and the note that S0 must precede edits to untracked scripts. No slice boundary, input/output contract, or acceptance test is visible. This is the core deliverable of the plan; it cannot be implemented from what is shown.

P2 — "Declared intent that survives compaction" has no persistence mechanism defined. The executive decision names this as the primary goal. No storage target (file, environment variable, metadata field) is specified, nor is the read-back path at SessionEnd described.

P3 — Approval gate paths reference a local filesystem path (/fwp D:/dotclaude/dotclaude-ecosystem/design/pl…) with no CI/CD equivalent. If this system runs on a non-Windows host or in a containerised environment, the path is invalid.

TOP 3 CHANGES

1. P1 — Restore and publish the full ## Architecture diagram before any slice begins.
The two visible lines are insufficient for any implementor to make correct ownership decisions. The router → curator → hook chain, the verdict store, and the session-close reconciler must all be named with explicit data-flow arrows and component owners. This is the single highest-risk gap because every other component decision flows from it.

2. P1 — Define the hook execution model (sync vs. async, timeout, failure policy) in a dedicated ## Hook Runtime Contract section.
Specify: thread model, maximum wall-clock budget per hook (numeric, not narrative), behaviour on unhandled exception (warn-and-continue vs. block), and whether the drift scanner streams or buffers. Without this, the token-budget acceptance criteria are unenforceable and the motivating Reddit-paste scenario remains a latent blocker.

3. P1 — Complete the ## Implementation slices section with explicit input/output contracts and the omitted session_plan_<session_ invariant.
Each slice must declare: files touched, interface contract (typed), and the single regression test that proves it is independently removable. The truncated frozen invariant must be restored verbatim, as downstream tooling depends on the exact pattern.
