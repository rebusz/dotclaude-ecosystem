# Audit - Claude Opus via shared audit CLI

Target: `2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`  
Model: `opus`  
Source: `claude_cli_shared`  
Runtime boundary: `repository-neutral audit only; no WatchF runtime`  
Latency: 209.29s

---

# Independent External Review

**Target:** `2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md`
**Reviewer role:** independent external, fail-closed
**Review date:** 2026-07-28

---

## 0. Transmission status — read this first

**`transmission: INCOMPLETE`**

The instruction I was given was to "follow the target's embedded review contract exactly, including its severity vocabulary" and "emit the required final attestation." **The transmitted target contains no embedded review contract.** Specifically, the transmitted bytes contain:

- no definition of a severity vocabulary (P1/P2 are *used* in the historical engineering review, never *defined*; no scale, no threshold, no blocking rule);
- no attestation template or required attestation fields;
- no `transmission` field, and no instruction on how to set one;
- no reviewer obligations, no pass/fail criteria for this review, no required output shape.

I therefore cannot follow the contract "exactly." I have proceeded under explicitly stated substitutes rather than returning nothing:

- **Severity vocabulary:** I reuse the document's own demonstrated `P1` / `P2` + `confidence n/10` convention. I add `P3` for nits; **`P3` is my extension, not the document's** — the target never defines the scale, so my P1/P2 boundary may not match the author's.
- **Attestation:** constructed by me in §6, clearly labeled as reviewer-authored.
- **Verdict vocabulary:** I reuse the document's own terms — `CLEAR`, `UNPROVEN`, `NOT STARTED`, `HOLD SCOPE`, `CONTINUE`, `SKIPPED`.

Additionally incomplete by reference — the following are cited as evidence by the target but were **not transmitted**, so nothing that depends on them is verified here:

| Referenced artifact | Status |
|---|---|
| `design/plans/2026-07-25_session_lifecycle_and_hook_hardening_r1.md` | not transmitted |
| `design/plans/2026-06-27_global_agent_workflow_os.md` | not transmitted |
| `design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md` | not transmitted |
| `design/audits/2026-07-27_2026-07-27_cross_runtime.../` rerun artifacts | not transmitted |
| All source: `codex_session_adapter.py`, `transcript_projection.py`, `install_codex_session_lifecycle.py`, templates, tests | not transmitted |
| PRs #55, #56, #57 | not transmitted |
| The C4 "redacted acceptance artifact" | not transmitted; location not named anywhere in the target |
| The carved skill's `SKILL.md` 11-section source | not transmitted |

Per instruction I have **not** inspected repository state. This is a document-only review. Every finding below is derivable from the transmitted bytes alone.

---

## 1. Verdict

**Plan quality: strong. Evidence discipline: strong in intent, materially short in one place.**

| Slice | Reviewer verdict |
|---|---|
| Codex slice, as *designed* | CLEAR |
| Codex slice, as *evidenced for "shipped"* | **UNPROVEN** — see P1-1, P1-2 |
| Cursor CU0-D discovery | CLEAR |
| Cursor CU0-L gate placement | CLEAR — correct next gate |
| Cursor CU1–CU4 | NOT STARTED; correctly held |
| Antigravity / Kimi | NOT STARTED; correctly out of scope |

**Recommendation: HOLD SCOPE. Do not grant `GO CURSOR CU0-L LIVE CONTRACT CAPTURE` on the strength of this document alone until P1-1 is closed** — the Codex slice is the precedent for how "shipped and active" is evidenced in this plan, and that precedent currently has gaps that would propagate straight into the Cursor acceptance record.

This is a genuinely rigorous document. The false-positive rejection in CU0-D (§Cursor discovery evidence: `CONTEXT_SEEN` rejected because no physical hook event existed) is exactly the behavior a fail-closed review wants to see, and the refusal to reverse-engineer `store.db` is the right call. My findings are about the gap between the plan's own stated acceptance bar and the evidence recorded against it — not about the design.

---

## 2. P1 findings

### P1-1 — C4 acceptance criteria have no corresponding evidence, yet the slice is marked shipped (confidence 9/10)

`C4 — Exact live acceptance` names nine required proofs plus a mandatory redacted artifact. The `Codex closeout evidence — 2026-07-27` block records: hashes for two targets, "Native persisted and ephemeral smokes passed," a test count, and p95 timings.

Cross-checking C4's requirements against the closeout record:

| C4 requirement | Evidence in transmitted target |
|---|---|
| hook discovery is user-level | not stated |
| `SessionStart` injected lifecycle context | not stated (subsumed in "smokes passed"?) |
| binding/plan identifiers match the Codex session | not stated |
| recorded transcript path is the same session's path | not stated |
| close writes a valid persisted verdict | not stated |
| ephemeral run leaves no binding / no new error | "ephemeral smoke passed" |
| `startup -> compact` retains exactly one write-once binding | **absent** |
| registered repository whose path contains a space resolves | **absent** |
| forced delegate failure → exactly one bounded adapter reason | **absent** |
| redacted artifact with session ID, binding/plan/verdict paths, transcript-path equality, elapsed times, bounded hook-error window | hashes and timings only; artifact location never named |

Three named acceptance checks have no evidence line at all, and the mandated artifact is neither transmitted nor located.

**Compounding this:** the plan elevates trust mode to a first-class correctness property — *"A one-command trust bypass is smoke evidence only, never proof of global activation"* (CEO decisions) and *"No surface is marked live until evidence is captured from a normal invocation without trust/config bypass"* (CU4). The closeout record does not state which trust mode the passing Codex smoke used. Under fail-closed rules, an unstated trust mode reads as **unverified**, not as normal trust.

**Required to close:** amend the closeout block with a per-C4-line evidence table, name the artifact path, and explicitly attest the trust mode. If the three missing checks were not run, say so and mark the Codex slice `SHIPPED WITH KNOWN ACCEPTANCE GAPS` rather than meeting the DoD.

### P1-2 — The full regression suite was never green, and "pre-existing" is asserted without a baseline (confidence 9/10)

The document is admirably honest here — *"those are recorded as non-green and are not represented as a passing full-suite result"* — but honest disclosure does not satisfy the plan's own gate. The plan states, in three separate places, that green regression blocks landing:

- Failure map: `Regression in Claude behavior | block landing | full lifecycle regression suite`
- Validation gate: `python -m pytest -q scripts/tests` is a required regression command
- Test review: *"every existing Claude lifecycle/Curator test remains unchanged and green"*

Yet PRs #55–#57 merged and `main == origin/main == 8fc7ac5`. The slice landed through a gate it did not pass.

Separately, the classification of the three failures as **pre-existing** and **load-sensitive** is an assertion with no transmitted evidence. A fail-closed review cannot accept "pre-existing" without a baseline run at the merge-base (`e2397ed`) showing the same three tests failing the same way. A 0.5 s Git subprocess timeout is exactly the kind of threshold that a new adapter's added process-per-event load could push over — the causal story is plausible but untested, and it is self-serving.

**Required to close:** either (a) attach a baseline failure record at `e2397ed`, or (b) raise/parameterize the 0.5 s Git subprocess timeout and produce one genuinely green `scripts/tests` run at `8fc7ac5`. Option (b) is cheaper and closes it permanently.

### P1-3 — Emergency-off destroys post-activation registry edits with no pre-restore snapshot (confidence 8/10)

Emergency-off step 2: *"atomically restore both pre-activation `~/.codex/hooks.json` and `~/.claude/session_registry.json` bytes."*

The registry is explicitly a **shared, live, operator-editable** artifact spanning ten repositories (§Repository registry scope: *"This is desired global ecosystem behavior, not a Codex-private setting"*). If the operator registers an eleventh repository a week after activation and then runs emergency-off because of an unrelated adapter fault, the blind byte-restore silently reverts that registration. Nothing in the emergency-off sequence snapshots the *current* bytes before overwriting them, and nothing verifies that the current registry still matches the hash recorded at install.

This is a recovery path that loses data, which is the worst place to lose it — it fires precisely when the operator is already in trouble.

**Required to close:** before restoring, compare the current registry SHA-256 against the installed hash recorded in the manifest. On match, restore. On divergence, snapshot current bytes to a timestamped file and either refuse with an actionable message or restore only the owned delta. Note that this also contradicts the *"Reversibility is 5/5: restore the exact pre-activation hook backup"* claim, which mentions only one of the two targets.

---

## 3. P2 findings

### P2-1 — The performance gate is stated as hard in one section and aspirational in another; measured values fail the stated form (confidence 9/10)

§Performance review: *"2 measured gates … the target is below 500 ms p95 for start and below 750 ms p95 for end."*
§Codex closeout: `565 ms` start, `777 ms` end — *"below the hard 2 s/3 s timeouts but slightly above the aspirational 500 ms/750 ms targets."*

"Gate" and "aspirational" are not the same word. A landing gate that is ambiguous about whether it blocks is not a gate. Product risk is low (hard timeouts were met, tooling is advisory), and the disclosure is honest, so this is P2 rather than P1 — but it should be resolved by editing one of the two sections, not left for the next reader to arbitrate. Recommend: reclassify explicitly as `budget: 2 s / 3 s (blocking)` and `target: 500 ms / 750 ms (non-blocking, tracked)`, and record the current values as a tracked miss.

### P2-2 — The degraded-close path copies a start-time transcript path without stated re-validation (confidence 7/10)

C1: on a null `SessionEnd.transcript_path`, *"copy that binding's transcript path into the delegated event."* The binding was written at `SessionStart`; the close may occur hours later. Between those points the path may have been deleted, truncated, replaced, symlinked, or grown past the 4 MiB bound.

The threat model row *"Host payload supplies an arbitrary transcript path → binding/session/repo cross-checks remain mandatory"* covers the host→event direction. The degraded path runs binding→event and inherits no stated check. Specify that the copied path is re-validated at close time (absolute, exists, resolves under the same registered repo root, within existing byte bounds) and that failure degrades to the bounded no-op rather than to a verdict computed from an unverified file.

### P2-3 — CU1's `preCompact` delegate target does not exist in the transmitted target (confidence 8/10)

CU1: *"`preCompact`: delegate to the existing checkpoint/start-context recovery seam without changing identity."*

The §What already exists reuse table enumerates five existing owners: `session_state.py`, `session_router.py`, `session_lifecycle.py`, `state_reaper.py`, `curator_claims.py`. No "checkpoint/start-context recovery seam" appears there or anywhere else in the transmitted bytes. Either it lives in the untransmitted predecessor plan, or CU1 depends on a seam that does not yet exist and is unowned. Under fail-closed rules this is **UNPROVEN**. Name the module and function, or add its construction as an explicit CU1 sub-task.

### P2-4 — The adapter's posture toward Cursor's `env` output is unspecified (confidence 7/10)

§Cursor discovery evidence notes that `sessionStart` is *"fail-open/fire-and-forget for blocking behavior while allowing `env` and `additional_context` output."* The plan constrains `additional_context` carefully (nonce-proven delivery, degraded otherwise) and never mentions `env` again.

`env` is a write into the host agent's process environment — a materially different and higher-privilege surface than context injection, and one an advisory R1 adapter has no need for. This belongs in §Frozen boundaries as an explicit prohibition: *the Cursor adapter never emits `env`*. Silence here is the kind of gap that gets filled by a later implementer who sees the field in the schema.

### P2-5 — CU0-L's concurrency precondition is operator discipline, not enforcement (confidence 7/10)

*"Preconditions: all Cursor IDE and Agent CLI processes are closed"* and CU3's *"must not run while an unrelated Cursor session could rewrite the same user config."* Both are stated as conditions the operator satisfies; neither names a mechanism.

The plan already does the hard half well — CU0-L verifies *"exact post-restore bytes/absence state"* and *"no probe process left running."* Close the loop on the front end: the probe should programmatically check for running Cursor processes and abort if any are found, and should re-read + re-hash the target immediately before write to detect a concurrent rewrite. Given that this is the only step in the whole plan that mutates a live user config on a machine where the mutating application may be running, enforcement is proportionate.

### P2-6 — CU0-L has no differential diagnosis for the zero-event result (confidence 8/10)

CU0-D established a sharp contradiction: the installed CLI bundle contains validators and merge logic for `sessionStart`/`sessionEnd`/`preCompact`, yet a project-level `.cursor/hooks.json` produced **zero** events across two successful conversations. The candidate causes are at least: project scope unsupported for CLI; hooks gated on a trust/allowlist step; Ask-mode excluded from lifecycle emission; wrong filename or config precedence; version gating between IDE `3.13.21` and CLI `2026.07.23`.

CU0-L tests only the user scope. If user scope *also* yields zero events, the plan lands in the same undiagnosed state with a probe budget already spent and a live user config already touched. Add at least one discriminating instrument to CU0-L — CLI verbose/debug hook logging, or a documented config-precedence check — so that a zero-event outcome distinguishes "scope unsupported" from "config not loaded."

### P2-7 — Registry expansion changes Claude behavior in nine repositories with no per-repo evidence (confidence 6/10)

§Repository registry scope is candid that this flips nine additional repos from the unregistered-minimal branch to full advisory lifecycle context. The evidence for that behavior change is one test assertion (*"an expanded active registry is proved in both a Claude-style router event and a Codex adapter event"*) plus one live check on a single space-containing path.

I accept the argument that eligibility is mechanical (exists + `git rev-parse --show-toplevel` matches + plan paths below root) and that per-repo live proof is disproportionate. Residual risk is low and the rollback path exists. Recorded as **accepted with residual risk**, not a defect — but the installer should print the resolved ten-root list into the manifest so the set is auditable after the fact rather than inferred from a hash. Note this interacts with P1-3: an auditable list makes divergence detection cheap.

---

## 4. P3 / nits

- **`phase: discovery`** in frontmatter, while the Codex slice is shipped and live. A reader scanning frontmatter concludes nothing has shipped. Suggest `phase: codex-shipped/cursor-discovery`.
- **`repos: [dotclaude-ecosystem]`** under-declares a change whose activation mutates shared state affecting ten repositories.
- **C4 list formatting** shifts mid-list from `Prove:` clauses (semicolon-terminated) to standalone assertions (period-terminated) at bullet 6, which is why the last three checks read as afterthoughts and — see P1-1 — were the three with no evidence.
- **Test-count reconciliation is not possible** from transmitted bytes: `354 tests + 9 subtests` (final validation) vs. `96 + 7 subtests` and `31 + 3 subtests` (implementation review). Different runs, so not contradictory, but `9` vs. `7+3=10` subtests invites the question. Recorded as unverifiable, not as an error.
- **Panel count ambiguity:** "8 reviews returned" reconciles as OpenRouter 4 + Perplexity 3 + Claude Opus CLI 1. Whether the "distinct Kimi-via-Perplexity lane" is inside the Perplexity 3 or an unlisted ninth is not resolvable from the text.
- **The "zero rows with `Rescued=no`, `Test=no`, and silent user impact" claim** is a three-way conjunction and is therefore trivially satisfiable; the registry table does contain a `Rescued=no` row (Claude regression), which is fine because it is tested and visible. The claim is true but weaker than it reads.
- **C4's acceptance artifact has no declared home.** §Frozen boundaries forbids copying secrets/transcripts into the repository, but never says where redacted acceptance evidence *does* live. Name a location.

---

## 5. Internal consistency checks that passed

Verifiable from the transmitted bytes alone, and worth recording because they materially raise my confidence in the parts I could not check:

- **"eleven concrete gaps"** in §Implementation review fixes — enumerates exactly 11. ✓
- **"32 named branch/flow obligations"** in §Engineering completion summary — the §Test review coverage diagram contains adapter 7 + projection 5 + installer 8 + live (3 parents + 9 children) 12 = **32**. ✓ An exact reconciliation on a number that would be easy to fudge.
- **"ten verified ecosystem roots"** — §Repository registry scope lists exactly 10 candidate roots. ✓
- **Rollout order** (Claude → Codex → Cursor → Antigravity → Kimi) is consistent across the frozen list, the deferred section, and both amendment reviews. ✓
- **The frozen boundary "no chat-database scraping"** is honored under pressure: CU0-D located `store.db` and its `meta.json` schema, and the plan explicitly declines to parse it. ✓ This is the single strongest signal in the document.
- **The `CONTEXT_SEEN` false-positive rejection** — a model self-report was discarded because no physical hook event corroborated it. ✓ Correct fail-closed instinct, and the reason CU0-L's nonce requirement is credible.
- **Approach C rejection** (host-neutral framework rewrite) and the `AdapterBase` discard in §Paid audit synthesis are consistent with each other and with the thin-adapter boundary. ✓

---

## 6. Attestation

> **Reviewer-authored.** No attestation template was transmitted; the field set below is my construction. See §0.

```
ATTESTATION — INDEPENDENT EXTERNAL REVIEW
target:            2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md
review_date:       2026-07-28
reviewer:          independent external, fail-closed
transmission:      INCOMPLETE
transmission_gap:  embedded review contract absent (no severity vocabulary
                   definition, no attestation template, no transmission field,
                   no reviewer obligations); 8 classes of referenced evidence
                   artifact not transmitted (see §0 table)
contract_followed: NO — substituted vocabulary and attestation, disclosed in §0
repo_state_read:   NO — document-only, per instruction
severity_scale:    P1/P2 reused from target's demonstrated usage;
                   P3 is a reviewer extension, not defined by the target

findings:          P1 = 3, P2 = 7, P3 = 7
p1_summary:        (1) C4 live-acceptance criteria lack corresponding evidence
                       and trust mode is unstated, for a slice marked shipped
                   (2) full regression suite never green; "pre-existing"
                       classification asserted without baseline
                   (3) emergency-off blind-restores a shared live registry,
                       destroying post-activation edits with no snapshot

verdicts:
  codex_design                CLEAR
  codex_shipped_evidence      UNPROVEN
  cursor_cu0_d_discovery      CLEAR
  cursor_cu0_l_gate           CLEAR (correct next gate)
  cursor_cu1_cu4              NOT STARTED (correctly held)
  antigravity_kimi            NOT STARTED (correctly out of scope)

recommendation:    HOLD SCOPE
authorization:     this review does NOT grant
                   "GO CURSOR CU0-L LIVE CONTRACT CAPTURE"
gating_condition:  close P1-1 before CU0-L, so the Cursor acceptance record
                   does not inherit the Codex evidence precedent
```

---

**What I could not do, stated plainly:** I could not follow the review contract, because it was not in the bytes I received. If a contract document exists — with the severity scale, the attestation schema, and the transmission field semantics — send it and I will redo the attestation in the required form; the findings themselves will not change, only their labeling. Sending the three predecessor plans and the audit rerun directory would additionally let me convert P2-3 and several §0 entries from `UNPROVEN` to a real verdict.
