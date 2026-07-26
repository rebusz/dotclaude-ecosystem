- [SEVERITY P1] (confidence 10/10) S2 / Slice order - S1 cannot measure a “full SessionStart run” before S2 implements that run. The budget dependency is circular, so the stated execution order is impossible.
  
  > “S1 also produces the cost baseline… of a full `SessionStart` run”

- [SEVERITY P1] (confidence 10/10) Stage 3 Issue 6 - The finding is true, but the fix is mechanically false. Printing output does not release a synchronous command hook; Claude Code processes hook output when the subprocess exits. Running the reap “after injection is emitted” therefore still adds its full latency to SessionStart. [Official hook reference](https://code.claude.com/docs/en/hooks).
  
  > “runs after the injection is emitted, so a slow sweep can never eat the startup budget”

- [SEVERITY P1] (confidence 9/10) S2 `fork` - The plan promises to read the existing scratch file, but SessionStart supplies the new session ID and no parent-session ID. A fork cannot locate its parent’s `session_plan_<id>` without an unspecified cross-session lookup—the exact unsafe guessing rejected for transcripts.
  
  > “`fork` | reads the existing file, never clobbers it”

- [SEVERITY P1] (confidence 9/10) Stage 3 Issue 1 - The finding is true, but `consumed_at` does not fix delivery. SessionStart injects context for Claude; it does not prove the operator saw the verdict. Stamping consumption when injected can delete an unread verdict and directly defeats the goal that the operator “will meet it.”
  
  > “`consumed_at` stamp set by whichever delivery path renders it first”

- [SEVERITY P1] (confidence 9/10) S3 verdict rules - “Merged into trunk” and “open items” are undefined relative to `start_sha` and session-owned work. A session starting on clean `main` can receive `ARCHIVE-OK` without accomplishing anything; unrelated dirty files can force `HANDOFF`. The verdict is repository state mislabeled as session verification.
  
  > “merged into trunk, worktree clean, no open items | `ARCHIVE-OK`”

- [SEVERITY P2] (confidence 10/10) Stage 3 Issue 5 - The finding is true, but the applied fix is internally inconsistent and incomplete. It claims wall-time unit assertions, then explicitly removes clock dependence; T6 verifies only character ceilings. No wall-time regression assertion actually exists.
  
  > “the character ceilings and the wall-time budgets are unit-test assertions”

- [SEVERITY P2] (confidence 10/10) Stage 3 Issue 3 - The original finding is true, but the fix records `transcript_path` only on `startup`/`clear`. A `fork` has a new transcript while retaining inherited state, so leaving the path untouched binds `/curator` to the parent transcript—the concurrency/security failure the fix claims to prevent.
  
  > “`transcript_path`… left untouched on `resume`/`compact`/`fork`”

- [SEVERITY P2] (confidence 9/10) S4 claim extraction - The transcript is documented as asynchronously written and potentially behind the live conversation. The plan never establishes a flush or stability boundary, so `/curator` can miss the latest claims and falsely present its extraction as complete. [Official hook reference](https://code.claude.com/docs/en/hooks).
  
  > “Extract concrete assertions from the session transcript”

- [SEVERITY P2] (confidence 9/10) Stage 3 Issue 2 - The finding misreads a deferred diagnostic as missing core functionality. Re-homing it into `/curator` expands the skill, while Claude Code already provides `/hooks` to inspect effective hooks across user, project, plugin, and managed sources. Reading one `settings.json` can report false absence. [Official hook reference](https://code.claude.com/docs/en/hooks).
  
  > “`/curator` reports which of this plan’s two hook entries are present in `settings.json`”

- [SEVERITY P2] (confidence 9/10) Stage 3 D1 merge - D1’s premise is wrong: separate modules do not imply two authoritative registry resolvers. `session_registry.py` can own resolution and `session_state.py` can call it. The merge combines global repository configuration with per-session persistence and immediately makes the claimed four-operation boundary porous.
  
  > “anything a later slice wants to add belongs in that slice’s own module”

- [SEVERITY P2] (confidence 9/10) S2 startup declaration - A SessionStart hook can inject an instruction, but it cannot make the model write the scratch file before the first user prompt. The plan silently assumes the model will obey and perform an unsolicited write, so “declared intent at start” is neither deterministic nor guaranteed.
  
  > “model writes intent”

- [SEVERITY P2] (confidence 8/10) Stage 3 Issue 7 - Deferring installer ownership while S5 hand-edits global settings leaves the ecosystem-wide feature non-reproducible and machine-local. Recording the defect for a fourth time does not resolve it; it contradicts the claim that the plan is independently shippable.
  
  > “enable hooks in `settings.json` as the final step”

- [SEVERITY P2] (confidence 8/10) S1 registry - The plan builds a permanent manual registry instead of fixing or generalizing repository detection. That creates another stale configuration surface solely to preserve D7, despite the reuse rule that the router must not duplicate `plan_context_loader.py` policy.
  
  > “`plan_context_loader.py` repo detection | Cannot see `dotclaude-ecosystem`; the registry exists because of this”

- [SEVERITY P2] (confidence 8/10) Architecture / strategic calibration - Goal 2 says claims are confronted before anything is called done, but `/curator` is optional and SessionEnd produces only a coarse Git-state verdict. The design therefore does not enforce—or even reliably perform—its headline verification at close.
  
  > “`/curator` renders it on demand”

- [SEVERITY P3] (confidence 9/10) Stage 3 Issue 4 - This finding is true and its DoD reconciliation is correct; the remaining problem is the review’s “all resolved” wording, because Issues 5–7 remain incomplete or deferred.
  
  > “Six issues plus one deferred TODO, all resolved”

- [SEVERITY P3] (confidence 8/10) Stage 3 Issue 6 / timeout contract - The plan sets a universal two-second hook ceiling without reconciling SessionEnd’s default 1.5-second budget or specifying the required per-hook timeout override. A valid two-second lifecycle hook can be killed by the harness.
  
  > “hook wall time: <= 2 seconds each”

Meta: Jul 25 12:00 MDT | Codex | scope: Stage-3 plan challenge | id: lifecycle-review