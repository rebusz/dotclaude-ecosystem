# Audit — MiniMax M3

Model: `minimax/minimax-m3`  
Tokens: 13,111  
Latency: 30.7s

---

# Audit Report: Session Lifecycle Router, Curator, and Hook Hardening

## 1. Architectural Soundness

### 1.1 S1 Repo Registry — ownership gap (P2)
The plan defines a `session_registry.json` naming repositories entitled to "full run," but does not name the **owner** of that registry, the **merge authority** for new entries, or the **conflict resolution** policy when two machines diverge. The pre-mortem entry "Registry drift" accepts silent failure for unregistered repos, but does not specify how a repo gets added in the first place. Before implementation: write a one-paragraph registry maintenance contract (who edits, how conflicts resolve, whether the registry is committed, machine-local, or both).

### 1.2 S4 `/curator` claim extraction — model step is underspecified (P1)
"Claim extraction requires judgment, so it is a model step reading a bounded transcript window, not a regex." The plan names neither the **window size** nor the **model** nor **who invokes the model** (a hook can't per invariant 2). Is this a second LLM call paid by `/curator`'s invocation? Is it the same session model? This is a contract gap that affects cost, latency, and the invariant that "no model call inside a hook process." Clarify whether `/curator` is a Skill that runs an in-session model pass over a transcript window, and pin the window size and any token budget for that pass.

### 1.3 S6 personas — selector logic is missing (P2)
"Bad-actor selects when the plan touches the order boundary; a documentation plan selects none and says so." The selector is described as a single example pair. The plan needs a deterministic rule set: which frontmatter fields, which path patterns, and which risk class map to which persona. Otherwise the agent under review is choosing lenses by feel, which is exactly what the slice is supposed to prevent.

### 1.4 S5 `/sweep` IDEA_BOX write contract (P2)
The plan says findings are appended "as slugged entries" that are "consumable by `plan_context_updater`." The existing `IDEA_BOX.md` format (header schema, separators, required fields) is not pinned. The redaction in Finding 3.2 is good, but the **shape** of an entry (timestamp, source `file:line`, severity, reproducer) is unstated. Reference or define the exact format before implementation.

---

## 2. Threading / Async Safety

### 2.1 S2 PostToolBatch throttling — concurrent-batch definition (P2)
"`PostToolBatch` fires after **every** batch of parallel tool calls." What counts as a batch? If two parallel calls and three parallel calls both count as one batch each, throttling by "batches since last check" gives different density than throttling by "elapsed wall time" alone. Pin the throttle predicate (e.g., "fire if neither a check nor an N-tool N-second window has elapsed"). Without this, the "firing rate stays within budget" gate in S2 is untestable.

### 2.2 S3 state_reaper — TOCTOU on liveness check (P1)
The reaper excludes files modified inside the retention window and its own session_id. On a filesystem where `mtime` resolution is coarse (Windows FAT, some network mounts), a file written **just before** the reaper runs may have an `mtime` older than reality by up to 2 seconds. Combined with the live-session exclusion, a session that just started could lose its scratch file. The plan should either (a) cross-reference the harness's live-session list with a hard guarantee that list is obtainable (the plan hedges with "when that list is obtainable"), or (b) default to **never delete `session_plan_*` without a positive live-session confirmation**. As written, "when obtainable" is a fallback to age, which is the very gap Finding 2.1 closed.

### 2.3 S1 scratch file atomic writes — concurrent writers (P2)
The atomic write pattern (temp + `os.replace`) is reused, but the drift check (S2), the model itself, and `SessionStart` on `startup` can all write the same file. On Windows, `os.replace` is atomic on the same volume, but a reader between the temp create and the replace sees **nil** rather than the prior content. That is fine for hooks (fail-open), but if `/curator` reads concurrently with a drift-check rewrite mid-close, it may see an empty file. Document the reader contract: "if file is zero-length or unparseable, treat as no plan" — and verify this matches the S4 curator's error path.

### 2.4 Hook wall-time budget vs subprocess `git` (P2)
`SessionEnd` runs `git` to compute verdicts. `subprocess` calls block the hook process. With a p95 of 400 ms on SessionStart, the budget for SessionEnd is not stated. SessionEnd is on the close path where latency is less critical, but a hung `git` already motivated the `TimeoutExpired` rescue. The plan should pin a SessionEnd wall-time budget and the git timeout value (e.g., 5 s).

---

## 3. Edge Cases

### 3.1 S4 curator — model refusal to claim anything (P2)
The curator's failure-mode table covers `truthctl` absent and transcript unreadable, but not the case where the transcript is readable but the model declines to extract any claims. Is that `VERIFIED` (no false claims), `UNVERIFIED` (nothing to verify), or a curator error? The handoff contract must specify this.

### 3.2 S1 non-git directory — branch/HEAD strings (P3)
"Registry lookup miss and not a repo both fall to the same one-line branch." The one-line branch includes branch information per the test matrix ("repository and branch"). What does the router emit when there is no branch? The current spec leaves "branch" as a string that could be `<no-branch>` or empty; pin the exact string for the test.

### 3.3 S5 `/sweep` value threshold (P2)
"Findings above a value threshold are appended." The threshold is unstated. What makes one `TODO` worth a box entry and another not? Without a numeric or rule-based threshold, the gate "no findings on a clean repo" is easy, but "no spurious findings on a real repo" is unprovable. Pin the threshold (e.g., age + severity) and add a fixture covering borderline cases.

### 3.4 S3 verdicts — worktree-divergence case (P2)
The three verdict cases are merged-clean, merged-dirty, unmerged-large-context. What about an **unmerged small context**? A two-commit session that ended without merging is presumably `CHECKPOINT`, but the plan does not state the size predicate. The fixture repository list should cover this fourth case.

### 3.5 S6 personas — empty selection when none fit (P3)
"A documentation plan selects none and says so." What does the audit report look like with zero personas selected? Is that itself a finding? Pin the report shape.

---

## 4. Cost / Performance

### 4.1 S1 SessionStart in registered repo — 2,000 chars is not measured against realistic content (P2)
The 2,000-char budget is stated as an acceptance criterion. The example payload includes repository, branch, HEAD, dirty state, divergence, active plans, IDEA_BOX entries, recent handoff, **and** a proposed skill chain. The TruthDeck evidence control plane plans likely exceed this on their own. The budget needs a **measured** prototype before S7 enables SessionStart, with the worst-case repo in the registry as the test case.

### 4.2 S2 drift check — model read of scratch file (P2)
The drift check emits an `additionalContext` that re-states the goal. The plan does not state whether the drift check **reads** the scratch file inside the hook (cheap) or **asks the model to** (which would be the "no model call inside a hook" violation). Per invariant 2, the hook reads and emits; the model decides. But the drift check's "three questions" — is the plan still right, split a lane, time to hand off — are emitted *to* the model for it to answer. The plan should make explicit that the hook does not call a model and the questions are surfaced as user-role text, not answered by the hook.

### 4.3 S4 curator — transcript window cost (P1)
Per 1.2 above, this is the largest unstated cost. A session that ran for hours may have a multi-MB JSONL. The "bounded window" needs a number (last N turns? last N KB? last K tokens?) and a token budget for the model pass. Without this, the curator's "cost paid once per session close" is unfalsifiable.

### 4.4 S1 SessionStart — fork/compact/resume path costs (P3)
The router runs on every SessionStart variant. The p95 budget is split 400 ms registered / 150 ms unregistered. The fork/compact path will read an existing scratch file, which is fine, but does not also emit the full repository context? Specify.

---

## 5. Integration Risks

### 5.1 Hotfix `ad12cf2` shipped ahead of plan — contract drift risk (P1)
The hotfix for `plan_keyword_detector.py` and `answer_footer.py` landed as `ad12cf2`. The plan's invariant 5 ("Triggers must originate with the operator") depends on that fix. But the plan's S0 brings those scripts under version control **after** the hotfix. If the install manifest diverges from the canonical copy, the hotfix could be silently reverted on a reinstall. The plan should explicitly state: "S0 lands **before** any S1+ hook is enabled" and add a CI check that the installed script matches the canonical byte-for-byte. As written, S0 is described as having "no behavior change," which is true at the time of writing, but the ordering relative to enabling other hooks is not enforced.

### 5.2 S3 reaper vs `turn_counter_*` ownership (P2)
The reaper "deletes only files matching its own owned prefixes." But `turn_counter_*` is written by `answer_footer.py`, which is touched by S0. If S0 introduces any change to the naming convention (e.g., adding a suffix), the reaper silently misses files. The ownership contract should be: "the reaper is the **only** writer/deleter for `turn_counter_*` and `session_plan_*` prefixes." If `answer_footer.py` is changed in S0 to write a different prefix, that must be a coordinated change, not silent.

### 5.3 TruthDeck R1 `truthctl` — version coupling (P2)
The curator and the router both depend on `truthctl` and `plan_context_loader.py`. The plan does not pin the minimum TruthDeck version or assert what happens if the installed `truthctl` is older than the snapshot the curator expects. The `_PRICING` bug in `answer_footer.py` shows that silent fallback to a default is a real failure mode in this codebase. The curator's "all claims UNVERIFIED" rescue on `FileNotFoundError` covers absence but not version mismatch.

### 5.4 S6 personas + autoplan — selector integration (P3)
The plan extends the existing `personas` array. If the array is processed by index elsewhere (e.g., positionally in any current code), inserting three new entries could break callers. Verify by reading the existing consumer before S6 lands.

### 5.5 Conductor R2 boundary — drift-check question risks invitation (P2)
The drift check asks "should a second lane be split off?" The pre-mortem calls this "one step from wanting a channel." If the agent answers "yes, split," what does the hook do? Per invariant 3 it cannot act. So the hook emits the question and the model answers in its next turn — but the plan does not say what the **agent does** with that answer. The risk is that the operator reads the drift prompt as a feature and tries to use it to coordinate, which is Conductor's job. Document explicitly: "the drift check is a prompt to the current session's model, not an inter-session signal."

---

## 6. Underspecified Areas

### 6.1 S1 routing table — completeness (P1)
The routing table is described by a single chain (design consultation). Where is the table defined? Is it data (a JSON map next to the registry) or code? What chains exist for non-design repos? This is the **central** behavior of the router and is the least specified part of the plan. Implementation cannot start on S1 until the routing table is enumerated.

### 6.2 S4 curator — verifier logic per claim type (P1)
"Confront each claim with repository evidence: `git log`, `git diff`, recorded exit codes, file mtimes." This is the heart of the curator, and it is one sentence. A claim "tests passed" needs a recorded exit code, which means **the session transcript must have exit codes in it** (already true via `answer_footer.py`?) and the curator must parse them. A claim "fixed X" needs a `git diff` for `X` since session start. A claim "committed Y" needs `git log`. The mapping from claim phrasing to evidence query is the curator's actual product and must be specified in pseudocode or rule form before implementation.

### 6.3 S3 verdict logic — exact predicates (P2)
"Computes one of three verdicts from branch merge state, worktree cleanliness, and unresolved items." What are the predicates? "Merged-clean" — `git rev-parse HEAD` is reachable from `main`? "Merged-dirty" — merged but uncommitted changes remain? "Unmerged-large-context" — large by what metric? Token count of remaining context, file count, diff size? Pin these.

### 6.4 S7 enablement order and verification (P2)
"Enabling hooks in `settings.json` as the final step, one event at a time, verifying after each that a session still starts, compacts, and ends cleanly." What does "verify" mean? Smoke test only? Full pytest? A real session exercising the hook? The acceptance criterion is too loose for the irreversible step.

### 6.5 `/sweep` and `/curator` — invocation contract (P3)
These are Skills invoked explicitly. The plan does not state whether they require arguments, whether they accept flags, or what their stdout is. Skills are model-facing, so the model needs to know when to call them. Document the trigger phrases and the model's job after invocation.

---

## TOP 3 CHANGES

1. **Pin the S4 `/curator` model step (Finding 1.2, 4.3, 6.2).** Specify the bounded transcript window size in tokens, the model that performs claim extraction, the per-claim evidence-query mapping (`"fixed X"` → `git diff X` since start_sha; `"tests passed"` → recorded exit codes from transcript; etc.), and the token budget for the model pass. The curator is the plan's highest-leverage new behavior and is currently one sentence.

2. **Resolve S3 state_reaper fallback gap (Finding 2.2).** "When the live-session list is obtainable" re-introduces age-based deletion for the very case Finding 2.1 closed. Replace with a hard rule: **never delete `session_plan_*` without a positive live-session confirmation**, and document the failure mode when the harness does not expose that list (e.g., delete only files whose `session_id` ends in a sentinel set, or skip reaping rather than fall back to age).

3. **Order S0 ahead of any hook enablement and assert byte-identity in CI (Finding 5.1).** The hotfix already shipped on `main`; the canonical version of `plan_keyword_detector.py` and `answer_footer.py` must be locked in `scripts/` before S1+ hooks are wired, and the install manifest must be checked into CI. Add a gate: "no hook entry in `settings.json` is enabled until the corresponding script in `scripts/` matches the installed copy byte-for-byte." This closes the regression vector where the hotfix is silently undone on the next reinstall.