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