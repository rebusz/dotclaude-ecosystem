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
