# Audit — MiniMax M3

Model: `minimax/minimax-m3`  
Tokens: 17,036  
Latency: 51.1s

---

Let me carefully audit this plan against the specified criteria. This is a complex cross-runtime session lifecycle adapter plan covering Codex (shipped) and Cursor (discovery complete, not implemented). Let me work through each criterion systematically.

The plan is dense and covers:
1. Codex adapter already shipped (T1-T5 done)
2. Cursor discovery complete (CU0-D done), but implementation gated behind CU0-L live contract capture
3. Frozen rollout order: Claude → Codex → Cursor → Antigravity → Kimi
4. Existing lifecycle engine stays authoritative; adapters are thin

Let me audit each criterion:

## 1. Architectural Soundness

**Strengths:**
- Clear separation: thin adapters feed existing router/lifecycle engine
- Single policy owner (`session_router.py`, `session_lifecycle.py`)
- Transcript projection isolated behind a policy-free boundary
- Approach B selected over speculative framework rewrites (Approach C rejected)

**Potential Issues:**
- The "registry blast radius" — adding 10 repos to the shared registry affects Claude behavior too. This is acknowledged and intentional, but worth noting.
- The plan has TWO primary architectural diagrams that are slightly different (one in "Architecture", one in "Architecture and four-path flow") — duplication could cause drift.
- PONYTAIL section says "NOT USED — no concrete simplification candidate" — but with three production modules, the decision to not abstract could become painful when Antigravity and Kimi arrive.

## 2. Threading/Async Safety

**Strengths:**
- Codex runs hooks synchronously as a process per event (explicit)
- Adapter is process-per-event; no in-process concurrency concerns within the adapter itself
- Back-to-back and repeated event tests noted

**Potential Issues:**
- The plan doesn't explicitly address what happens when multiple Cursor processes might write hooks.json concurrently. The installer says "Activation remains a post-merge machine-local step. It must not run while an unrelated Cursor session could rewrite the same user config." but this is a process-level discipline rather than a locking mechanism.
- No mention of what happens if a hook process is still running when install happens — installer says "concurrent target overwrite checks" was added but I'd want to see whether stale hook processes could clobber post-install state.

## 3. Edge Cases

**Strengths:**
- Comprehensive edge cases (null transcript, malformed JSON, mixed formats, duplicate call_id, etc.)
- Null transcript at start = no-op; null at end with valid binding = degraded close (clever asymmetric handling)
- Ephemeral sessions explicit no-ops to prevent error flood
- Crash handling explicitly reaper-owned, no synthetic events

**Potential Issues:**
- "Resume preserves existing conversation identity" — what if the existing identity has been reaped? Plan doesn't say. The reaper owns it but the adapter doesn't know.
- What about SessionEnd arriving for a session that never sent SessionStart? Orphan end test exists but I'd want to see the explicit handling.
- What happens if `session_router.handle_event` raises an unexpected exception type not listed? The catch-all is at "host boundary" which is the adapter's main(). What exceptions bubble out?
- Codex compact event semantics — the plan reinjects compact context "without replacing the write-once binding". But what if state files have been manually deleted between start and compact? Edge case not explicitly handled.

## 4. Cost/Performance

**Strengths:**
- Explicit timeouts (2s start, 3s end)
- p95 measurements captured (565ms/777ms — above aspirational targets but below timeouts)
- 4 MiB transcript cap unchanged
- No new subprocess calls on hot path (e.g., `codex --version` rejected as overhead)
- Failure mode registry and performance review both identify local JSONL/state-file I/O as first pressure point at 10x/100x

**Potential Issues:**
- Adapter p95 of 565ms/777ms vs aspirational 500ms/750ms — slightly over. Plan acknowledges but doesn't specify remediation.
- "Installer probes may invoke Codex/Git because they are outside the hook hot path" — but what if installer is run frequently? Probably fine since it's a one-shot, but worth noting.
- The plan doesn't discuss what happens at 1000x session volume — only 10x/100x. If a user does 50 sessions/day, that's 50 process spawns/day. Should be fine but no measurement.

## 5. Integration Risks

**Strengths:**
- Backward compatibility is "ship blocker"
- Existing Claude behavior regression = block landing
- Schema/version pinning via fixture headers (codex-cli 0.145.0)
- Clear contract surfaces: hooks.json → adapter → router → state

**Potential Issues:**
- **Hook contract drift** — Codex 0.145.0 is pinned, but what's the upgrade path when Codex updates the contract? Plan says "install preflight requires stable hook support and records the installed version" but the version check logic is underspecified. What does "stable hook support" mean concretely?
- **Cursor contract gap** — "native Cursor lifecycle support exists, but project-level CLI hook loading and IDE/CLI context delivery are UNPROVEN" — this is correctly gated behind CU0-L, but if CU0-L fails, the entire Cursor slice may need redesign.
- **Cloud agents explicitly out of scope** — but they're a real surface users will hit. If users use Cursor Cloud, they get NO continuity. This is honest but worth flagging that the "host-independent continuity" promise has a hole for this specific surface.
- **IDE vs CLI parity** — Plan correctly separates them but says "no surface is marked live until evidence is captured." What if CLI works but IDE doesn't (or vice versa)? The plan accepts degraded verdicts but the user expectation of "host-independent continuity" then becomes "host-but-not-surface-independent."
- **Antigravity/Kimi** — out of scope but rollout order is frozen. If those contracts turn out to be fundamentally different (e.g., only async, no transcript), the adapter pattern may not compose.
- **Stale caches** — plan mentions "registry template currently covers only `dotclaude-ecosystem`" but the registry is a file, not a cache. Maybe refers to the active session state?

## 6. Underspecified Areas

**Significant gaps before Cursor implementation (CU1+):**

1. **CU0-L evidence boundary** — "field names, reason classes, non-secret IDs, paths under its disposable workspace, and timing." How are paths sanitized? What's the exact redaction policy? Where does the evidence go? Just "redacted acceptance artifact" — where stored, format, retention?

2. **Hook version detection** — "install preflight requires stable hook support and records the installed version" — what specifically is the check? What if hook support changes between minor versions?

3. **Concurrent overwrite during install** — "concurrent target overwrite checks" was folded but I don't see the mechanism. File lock? Stale detection via mtime? Read-after-write hash compare?

4. **Adapter exception types** — `JSONDecodeError`, `OSError`, "runtime reason class" — what counts as a "runtime reason class"? Are all non-VE, non-OSE exceptions lumped together? The plan says "Catch-all protection remains only at the host boundary where fail-open behavior is the contract" but the catch-all is implicit.

5. **Reaper interaction** — Plan says "Existing reaper owns missing `SessionEnd`" but doesn't specify how the adapter knows when state has been reaped. If SessionEnd arrives for an already-reaped session, what happens?

6. **Registry path canonicalization** — "Windows matching uses resolved absolute paths, case-insensitive drive letters, normalized separators, and no prefix-only comparison" — what about UNC paths? Symlinks? Mount points? Junction points?

7. **Adapter delegation failure** — "a forced delegate failure leaves Codex usable and writes exactly one bounded adapter reason." What if the delegate failure is intermittent? Does the bounded reason get written once per session or once per event? Rate limiting?

8. **CU1 event-name normalization** — "the adapter owns Cursor payload validation, event-name normalization" — what's the normalization? Just renaming `sessionStart` → `SessionStart`? Or more semantic translation?

9. **CU2 conditional projection** — "Add sanitized records and structural projection without reading `store.db` by guessed location." What if Cursor's only stable path IS the database? Plan defers but doesn't define when deferral becomes a permanent "lower fidelity."

10. **Hook removal in emergency-off** — "atomically restore both pre-activation bytes... or remove only the owned hook groups if no prior hook file existed" — how is "owned" determined if there's no prior file?

11. **State file backup during install** — "leave lifecycle state files intact for diagnosis" — but what if state files are corrupted or incompatible? Plan doesn't say.

12. **Performance regression detection** — "Each invocation must remain below its configured 2 s/3 s timeout; the target is below 500 ms p95 for start and below 750 ms p95 for end." What's the action if measured p95 exceeds target but stays under timeout? Currently aspirational.

13. **Process model for Cursor hooks** — Codex runs hooks synchronously. Does Cursor? Plan defers but should at least state the assumption under test.

14. **Antigravity/Kimi** — explicitly deferred. But if those have fundamentally different shapes (e.g., webhook-only), the "thin adapter" pattern may need rethinking. Worth flagging that the pattern is being validated only against Codex so far.

Now let me think about what's already shipped vs what's pending:

**Codex slice is SHIPPED.** T1-T5 are done. The CU0-D discovery is done. The pending items are CU0-L, CU1, CU2, CU3, CU4. So most of my "underspecified" critique should focus on those.

But the plan is being audited as a whole. The shipped Codex slice is now in production. Issues with shipped code are P1; issues with planned code are also P1 if they block implementation.

Let me grade findings:

**P1 (blockers):**
- Hook version detection logic is underspecified (will affect install/upgrade)
- Adapter exception taxonomy at host boundary is vague (could mask real bugs)
- Reaper interaction with adapter not specified (orphan end, post-reap end)
- Concurrent install overwrite protection mechanism not specified
- The 500ms/750ms aspirational targets were missed (565ms/777ms) — no remediation plan

**P2 (important):**
- Two architectural diagrams in plan (one in "Architecture", one in "Architecture and four-path flow") risk drift
- Cloud agents gap in "host-independent continuity" promise
- Registry canonicalization doesn't enumerate UNC/symlinks/junctions
- Stale hook processes after install — race condition
- Adapter doesn't know about reaped state at SessionEnd
- IDE vs CLI asymmetry acceptance — degraded verdict for users

**P3 (nice-to-have):**
- Paid audit synthesis notes 2 of 5 lanes failed — confidence is "medium-high partial" which should be flagged
- "Trajectory" — thin adapter pattern validated against one host (Codex); speculative for Antigravity/Kimi
- Pre-existing load-sensitive test timeouts flagged as "non-green" — should be fixed before more slices
- "PONYTAIL: NOT USED" section signals no simplification; with three more hosts queued, this could compound

Let me also think about cost/performance more carefully:

- Process-per-event for Codex hooks. Each spawn = Python interpreter cold start. On Windows this is ~150-300ms. The 565ms p95 is reasonable but suggests Python startup is the dominant cost.
- The plan doesn't discuss using a long-running daemon. But that violates the "no broker, no daemon" frozen boundary. So this is by design.
- A potential optimization: compile Python to a binary. Not discussed.
- Memory: nothing about memory profile of adapter. Should be small but unmeasured.

Cost consideration for the user: each Codex session = 2 hook events = 2 Python process spawns. At 50 sessions/day, that's 100 spawns. On a Windows machine with cold Python startup ~200ms, that's 20 seconds of pure interpreter startup per day. Not a real cost concern, but worth knowing.

OK let me think about what the TOP 3 changes should be:

1. **Specify the adapter host-boundary exception handling and version detection** — without this, future contracts could silently break or bugs could be hidden behind catch-all logging.

2. **Define the reaper <-> adapter contract explicitly** — orphan ends, post-reap ends, and the "missing binding" path are mentioned but the actual decision tree isn't clear.

3. **Plan for IDE/CLI surface asymmetry** — if Cursor IDE works but CLI doesn't (or vice versa), what's the operator experience? Plan says "explicit unsupported/degraded verdict" but the user-visible contract should be specified.

Actually, let me reconsider. The most important issues are:

1. The hook version detection / contract drift mechanism is underspecified — this affects every future install. **P1**
2. Adapter host-boundary exception taxonomy is vague — could hide bugs or produce inconsistent behavior. **P1**
3. The 565/777ms measurements exceed aspirational targets with no remediation path — and we're about to add Cursor hooks which may be slower. **P2**
4. Two parallel architectural diagrams in the plan — drift risk for the next reviewer/agent. **P2**
5. Pre-existing test timeouts flagged as "non-green" — three lifecycle tests are unstable. **P1** if these are blocking the "full-suite green" claim that the plan implies
6. Reaper <-> adapter interaction not explicitly specified. **P1**

Wait, let me look at the implementation review section again: "the broad test run exposed pre-existing load-sensitive 0.5 s Git subprocess timeouts in three lifecycle tests; those are recorded as non-green and are not represented as a passing full-suite result."

This is honest disclosure but a real P1 issue — the plan claims "354 tests plus 9 subtests" and "full lifecycle regression suite" but three lifecycle tests are non-green. If those tests cover reaper or critical paths, that's a stability concern.

Let me also think about integration risks more carefully:

The plan says "Existing Claude Code behavior and schemas remain backward compatible." But adding 10 repos to the registry IS a Claude behavior change (from "unregistered minimal branch" to "full advisory lifecycle context"). The plan acknowledges this explicitly in "Repository registry scope" and the engineering review section. Good.

However — what about the runtime hook itself? Adding a Codex hook doesn't affect Claude. But expanding the registry affects BOTH. The plan captures this correctly. Good.

Now what about cross-platform: "On this Windows-first machine the installer renders the absolute sys.executable and adapter path into commandWindows; cross-OS activation is deferred until a non-Windows operator requests it." This is honest but creates a portability debt. If a Linux user wants this, they'll need a new installer slice. Not a blocker but worth noting.

Let me finalize my TOP 3:

1. **Specify adapter host-boundary exception handling and hook version detection** — both currently underspecified and could cause silent failures or hidden bugs as more hosts come online.

2. **Resolve pre-existing non-green lifecycle tests** — three tests with 0.5s Git subprocess timeouts are flagged but unaddressed; if these cover reaper or critical paths, full-suite stability is not proven.

3. **Define IDE/CLI per-surface degraded UX** — when one Cursor surface works but the other doesn't, what does the operator see? Plan accepts degraded verdicts but doesn't specify the user-visible contract or fall-back.

Actually, I think I should consider another issue: the plan is enormous. Let me make sure I'm not missing anything by checking the headings and structure:

- Decision and collision verdict ✓
- Why ✓
- Definition of done — Codex slice ✓
- Definition of done — Cursor slice ✓
- Verified current state ✓
- Frozen boundaries ✓
- Architecture ✓
- Implementation slices (C0-C4) ✓
- Repository registry scope ✓
- Failure map and rollback ✓
- Validation and landing gate ✓
- Cursor adapter boundary and delivery slices (CU0-CU4) ✓
- Deferred runtime slices ✓
- CEO decisions ✓
- Engineering review ✓
- Performance review ✓
- Cursor amendment review status ✓
- Cursor amendment CEO review ✓

The plan is comprehensive. The implementation tasks have checkboxes. Most decisions are well-reasoned.

Let me also check the dual-format projection. The plan claims "All diagram branches are required tests." Good. But: "Duplicate or non-string call_id values drop all evidence for that ID." — this is correct behavior but could be exploited. If a malicious transcript has duplicate IDs, all evidence drops. But the same is true for a single call with no result. Probably fine because verification requires exact pairing anyway.

OK I think I have enough to write the audit. Let me structure it:

I'll use the criteria as sections, cite specific plan sections by heading, grade each finding.

Let me finalize my findings:

### P1 Findings:

1. **## Architecture (C1) > Adapter host-boundary exception taxonomy is vague.** The plan lists `JSONDecodeError`, `ValueError`, `OSError`, "runtime reason class only" but doesn't define the catch-all behavior or what happens to unexpected exceptions. With five+ hosts planned, inconsistent handling will be a bug factory.

2. **## Implementation slices > C3 — Hook version drift detection mechanism is not specified.** Plan says "install preflight requires stable hook support and records the installed version" but doesn't define:
   - What constitutes "stable hook support" 
   - What minimum version is required
   - What happens if installed version is between known-good and current
   
3. **## Verified current state > Codex closeout evidence — Pre-existing load-sensitive test timeouts are non-green.** Three lifecycle tests with 0.5s Git subprocess timeouts are explicitly flagged as "non-green and are not represented as a passing full-suite result." Yet the plan claims "full lifecycle regression suite" and uses test counts as proof. This is a stability gap.

4. **## Architecture > Reaper <-> adapter contract is not explicit.** Plan says "missing end on crash remains reaper-owned; no synthetic close event is fabricated" but doesn't specify:
   - What `SessionEnd` does when binding has been reaped
   - What `SessionStart` does when state for that ID exists but is stale
   - Whether the adapter can detect reap events

5. **## Cursor adapter boundary and delivery slices > CU0-L — Evidence artifact format is underspecified.** Plan says "record event name, stable non-secret identity, workspace root, transcript classification, timing, and nonce result only" but doesn't specify:
   - Where the artifact is stored
   - Its retention policy
   - Its exact redaction scheme for paths/IDs
   - Whether it's checked into the repo or kept machine-local

### P2 Findings:

6. **## Architecture and ## Cursor adapter boundary and delivery slices — Two parallel architectural diagrams risk drift.** One in "Architecture" section (Codex), one in "Architecture and four-path flow" section, plus the Cursor diagram in "Cursor adapter boundary and delivery slices." Three diagrams for two hosts. Consolidate or mark as authoritative.

7. **## Verified current state > Performance — Aspirational latency