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