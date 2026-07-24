# Delegated R2/R3 Execution Protocol (cross-platform)

Trigger-loaded when landing R2/R3 work, when a delegated/executor session implements a plan, or
when deciding how a change reaches `main`. Referenced from core.md "Post-Implementation Review
Gate". Applies on EVERY platform — Claude, Codex, Cursor, Cline, Kimi, Antigravity, subagents —
because non-Claude tools do the implementation and do not read Claude memory or a repo's CLAUDE.md.

## Why this exists

2026-07-24: three R3 order-path/runtime changes were **direct-pushed to `main` with no PR and no
review gate** (Tsignal S2a, T3, T4). S2a shipped **two live ship-blockers** — phantom protection
(a fire-and-forget broker submit whose failure left the position marked protected with nothing at
the broker) and a dead restart-adoption path — both masked by shallow tests that mocked out the
code under test. They surfaced only in an after-the-fact oversight review and forced an
emergency-off. Direct-push is exactly how a broken R3 change reaches live practice.

## The rules

1. **Landing flow (R2/R3).** R2/R3 = order path, broker submit/arming, runtime execution,
   persistence contracts, live-decision state. These land: branch off `origin/main` -> implement
   scope only -> real tests -> **draft PR** (`gh pr create --draft`) -> notify for exact-head
   review -> fix SHIP-BLOCKING findings -> `gh pr ready` -> squash-merge -> fast-forward the
   operator's main checkout. **Never `git push` to `main` and never self-merge an R2/R3 change.**
   Direct-push is allowed ONLY for R0 docs / CI-ignored paths (`design/**`, `*.md`).

2. **Can't-open-PR fallback.** A platform whose harness cannot open a PR itself stops at a
   **pushed branch** and hands off the branch/SHA for a human or Claude to open the draft PR and
   run the gate. It must NOT merge or push to `main`, and must NOT fast-forward the operator's
   main checkout.

3. **Real-path test bar.** Tests must drive the REAL code path including the failure/rollback
   branch. Anti-patterns that manufacture false confidence (all from the 2026-07-24 ships):
   - a mocked event loop (`_loop = MagicMock()`) so the fire-and-forget broker-placement coroutine
     never runs and no order is ever asserted;
   - a hand-fed fixture (e.g. a fake `version:3` ledger row) that proves only the read-filter,
     while the write path that would produce it is never exercised — the feature is dead in prod;
   - a test that drives a disabled/emergency-off path instead of the live one.
   A persistence/restart DoD is a **round-trip** (write -> simulate restart -> read), not a
   hand-authored fixture of the post-state.

4. **Report honesty.** Report "done / tests green" ONLY when the work is committed AND pushed and
   the diff is on a named branch/PR. Name the branch/PR/SHA, the exact tests run + result, and any
   DoD still `PENDING`/`NO_SAMPLE` (e.g. a restart-readback). "Merged to main" is not a DoD.
   On 2026-07-24, S2a and T4 were both reported "implementation completed, tests PASSED" while the
   code was **not committed anywhere** — the reviewer could not find a diff. Verify with
   `git log -S`, not the report.

## Invariants restated

- **Fail-closed on safety.** An auto-recovery that clears a halt/lockout must confirm real broker
  state first and retain containment on any uncertainty (Tsignal T4 `_projectx_recovery_flat_detail`
  is the reference; S2a's fire-and-forget "mark protected" is the anti-pattern).
- **Practice/Combine parity is BINDING** (see core.md): a lane change lands on both account classes
  in the same slice.
- **Ship-on**, but a broken feature gets emergency-off + fix-forward, not left ON "to gather data".

This ref is the canonical cross-platform contract. Per-repo copies (e.g. Tsignal
`design/plans/DELEGATED_R3_EXECUTION_PROTOCOL.md`) may add repo-specific detail but do not weaken
these rules.
