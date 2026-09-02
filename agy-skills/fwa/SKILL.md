---
name: fwa
description: >-
  Execute a stamped, audited plan: run each slice on the lane its stamp names,
  verify the result against the repo, route review away from whoever produced
  it, and land the work. Use when an agy or Codex user types /fwa or asks to
  execute work tracks. The executor never writes the plan.
---

# `/fwa` — execute a stamped plan

You are the executor and dispatcher for a plan somebody else designed. Your job
is to route each slice, verify what comes back, and land it.

The shared contract — lane names and drivers, the `stamp v2` schema, review
resolution, round and chain caps, receipts and the ownership ledger, the
runbook, and the measured ChatGPT composer facts — is in
`D:/APPS/_shared/coderpx/DISPATCHERS.md`. Read it once per session. This file is
the stage procedure, not a second copy of the contract.

You are **coderpxA** if you are Antigravity (`agy`), **coderpxG** if you are
Codex. `/fwf` and `/fwp` belong to coderpxC, the planning runtime.

## You do not design plans

If the input is an idea rather than a plan, stop and route it for a plan first:
the gpt lane, then the ppl lane with GLM 5.3. Do not invent scope and then
implement it. An unverified or failed external result is `NO_PLAN`, not
permission to write one yourself.

## Step 1 — read the stamps

Extract every slice. Each carries a stamp written by `/fwf` Stage 3:

```
lane: chatgpt_cdp | coderpx | glm | qwen | cursor | local
executor: A | G
review: chatgpt_cdp | coderpx | chatgpt_cdp+coderpx | cross
mode: file | patch
files: <comma-separated>
```

`lane: local` is **valid and normal**. It means *you* implement that slice in
your worktree, with full file-edit authority. There is no edit ban on any
executor; earlier text claiming one was wrong and is gone.

An unstamped slice on an **R2/R3** plan is not yours to guess at — send it back
for an explicit assignment rather than authoring the routing yourself. On R0/R1
it defaults to `local` / `A` / `cross`.

You may **escalate** a `local` slice outward, recording the reason. You may
never **de-escalate** a slice stamped for an outward lane.

## Step 2 — let the dispatcher do the routing

Do not hand-roll invocations. Run the plan:

```bash
python D:/APPS/_shared/dispatch/dispatch.py plan "<plan>" \
  --executor A --worktree "<ABSOLUTE .claude/worktrees path>"
```

Add `--dry-run` first to see the lane surface without spending quota, and
`--night` to append the local qwen draft lane. The dispatcher validates every
stamp, refuses two slices that name the same file, honours the caps, walks the
chain when a lane fails, and writes a receipt per slice.

Escalate a `local` slice outward when any of these holds: concurrency, locking,
lease/CAS lifecycle or restart-adoption semantics; a failure or rollback branch
a real test must drive; more than two files whose contracts move together; or
the slice's own test command has gone red twice.

## Step 3 — what the local lane will do to you

Two measured failure modes, both of which look like success:

- **A packet on argv is a packet that never arrives.** Windows caps
  `CreateProcess` at 32,767 characters; a 37,626-character packet was silently
  skipped. The dispatcher sends packets on stdin as one NDJSON message and
  pins `--input-format stream-json` together with `--output-format stream-json`.
- **`agy -p … --sandbox` can exit 0 having done nothing.** Print mode cannot
  prompt for a tool permission, so it auto-denies and returns success. The
  dispatcher treats exit 0 with an empty edit set as `ExecutorUnavailableError`.
  If you invoke anything by hand, apply the same rule: **an empty `git diff` is
  not a completed slice.**

After every run that touched files, read back `git status --porcelain` in your
worktree, in the operator checkout `D:/APPS/<repo>`, and in
`D:/dotclaude/dotclaude-ecosystem`. Report foreign dirt loudly; it does not stop
the run.

## Step 4 — verify, then route the review

Run the slice's real test command and read the actual `git diff`. A green run
that never executed the intended path is not evidence, and a narrative claim
that a change was made is not a change.

Then route review by the `review:` stamp. **It never resolves to the producer**
— not the runtime that wrote the diff and not the model that wrote it. If you
implemented the slice, you are not its approver. A diff written by `coderpx`
GLM 5.3 goes to the gpt lane or to a different picker model.

Use a reply only when its evidence proves it: for the ppl lane the sibling
`.meta.json` says `SUCCESS` with a matching `verified_model`; for the gpt lane
the result artifact proves the observed model, and the observed effort when one
was requested. `SUBMIT_UNCONFIRMED` and a premature reply are both failures, not
answers.

Two rounds per slice. After that, walk the chain — do not retry a third time.

## Step 5 — land

Branch → validate → commit → push → **draft** PR → review gate → mark ready once
→ squash-merge → fast-forward the operator checkout. Keep the PR draft while
work moves: a self-hosted runner is capacity-one and shares the box with a live
trading stack, so batch pushes instead of triggering CI on every one.

Never direct-push to `main` for anything touching contracts, persistence or the
order path. If the repo's primary checkout is on its default branch, work in a
worktree and leave that checkout as you found it.

## What will go wrong, and what it means

- **A long answer times out while the model is still writing.** The complete
  answer is usually still in the browser afterwards; recover it from the last
  assistant message rather than resubmitting.
- **Whole-file replacement does not scale.** Above the patch size gate the reply
  carries a unified diff instead, validated by `git apply --check`.
- **A healthy watchdog does not mean a drivable lane.** READY proves the port
  answers. Proof is a read-back model identity.
- **A model answers with a work announcement instead of the work.** The
  transport rejects it as premature. Harden the packet — demand that the first
  line be the first required heading — rather than asking again unchanged.
- **A failed dispatch can leave the packet in the composer.** Clear it before
  the next one, and check you are not typing into another lane's conversation.

## Report

State tests with exit codes, findings and fixes, exact SHAs, PR state and open
work. Name a blocked lane as blocked; never quietly swap it for another.

End with the ownership ledger from `DISPATCHERS.md` §5, generated by
`dispatch.py ledger <task>` rather than typed. Attribute from receipts and the
actual diff, never from branch names or narration.
