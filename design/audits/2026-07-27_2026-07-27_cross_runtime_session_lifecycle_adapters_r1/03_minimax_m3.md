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