---
name: fwa
description: >-
  Execute an audited plan or task handoff by assigning implementation and
  review work to ChatGPT CDP or Perplexity CoderPX, verifying it and landing it.
  Use when an agy user types /fwa or asks to execute work tracks. Agy never
  writes the plan and implements locally only after a recorded CDP problem.
---

# fwa — execute a plan through delegated model work

You are the executor and dispatcher. External models write the plan and perform
implementation/review assignments; your job is to route, verify and land them.

**You do not design plans.** If the input has no plan — only an idea — invoke
the `/coderpx` plan route: ChatGPT CDP Sol Pro, then Sol Extra High, then Kimi
K3. Do not invent scope and then implement it.

## Step 1 — read the input and list the slices

The user pastes a plan, a handoff, or work tracks. Extract a numbered list of
slices. For each: what changes, which files, how it is verified.

If a slice carries an explicit stamp, honor it:

```
lane: chatgpt_cdp | coderpx
review: chatgpt_cdp | coderpx | chatgpt_cdp+coderpx
fallback: agy_after_cdp_blocker
```

An unstamped slice on an **R2/R3** plan is not yours to guess at. Send it back
through the `/coderpx` plan route for an explicit assignment. Do not author the
missing routing yourself. A `lane: local` stamp is invalid under this contract;
agy becomes executor only through the recorded fallback condition.

## Step 2 — decide what is hard

Implementation is outward by default. Assign an ordinary bounded slice to one
Perplexity CoderPX model: Kimi K3, Claude Sonnet 5, Grok 4.6 or GPT-5.6 Terra.

Route a difficult slice to ChatGPT CDP Sol Pro, falling back to verified Sol
Extra High, when **any** of these holds:

- concurrency, locking, lease/CAS lifecycle, or restart-adoption semantics;
- a failure or rollback branch that a real test must drive, not a mock;
- more than two files whose contracts move together;
- the slice's own test command has gone red twice.

Only after a concrete CDP blocker or terminal dispatch failure is recorded may
agy implement the slice itself. A slow lane or awkward packet is not enough.
Record agy as the fallback executor in the final ownership ledger.

## Step 3 — implement

### Antigravity fallback

Use this lane only after the CDP problem is recorded. Edit inside your
workspace. After **every** run that touched files, check
`git status` in the worktree, in the operator checkout `D:/APPS/<repo>`, and in
`D:/dotclaude/dotclaude-ecosystem`. Report anything dirty outside your worktree
loudly; do not stop the run for it.

Never report a change as made on the strength of your own narration. `git diff`
decides. Attribute the implementation to `Antigravity (agy)` and include the
agy runtime model only when it is observable.

### Outward — ChatGPT CDP (the difficult lane)

Write the task spec to a file, then:

```bash
python D:/APPS/WatchF/scripts/cdp_chatgpt_code.py --role chrome_gpt \
  --model gpt-5.6-sol \
  --prompt-file <spec.md> --write <repo-relative target> \
  --repo-root <repo root> --timeout-s 900 --require-single
```

It reads `--prompt-file`, not stdin. Exit 0 only when the file was actually
written; the JSON result carries `ok`, `written` and `reason`. Prefer a verified
Sol Pro selection. The Extra High fallback is valid only through a supervised
dispatcher that can request and prove `reasoning_effort=xhigh`; this wrapper
does not expose that flag, so never claim Extra High from this command alone.

The spec must carry, in order: the task and **the single writable file**;
grounded evidence (logs with timestamps, PIDs, SHAs) with an instruction not to
re-derive causation; the exact `file:line` and what to change, using existing
constants rather than literals; numbered hard constraints with the expected diff
size; a byte-checkable definition of done; the full current file between
`--- CURRENT CONTENT OF <path> ---` and `--- END <path> ---`; and the output
contract — the whole file between `<<<FILE_BEGIN>>>` and `<<<FILE_END>>>` inside
one code block.

**One writable file per submit.** Sequence multi-file changes as separate
submits.

### Outward — CoderPX

Use the `/coderpx` skill. It owns model choice, the packet, the manifest check
and the round cap.

## Step 4 — verify, then review

Run the slice's real test command and read the actual diff. A green run that
never executed the intended path is not evidence.

Route the review by risk, not by convenience:

- Primary PR reviewer: ChatGPT CDP Sol Pro, falling back to verified Sol Extra
  High. Ask it to attack races, mocks that skip the real path, non-idempotent
  retries and scope creep.
- If fresh readback shows ChatGPT already owns active tasks, route the review
  to Kimi K3 through CoderPX.
- A serious R3 PR may use two independent reviewers: ChatGPT Sol and Kimi K3,
  both on the same exact head. Respect Conductor capacity when sequencing them.
- Agy verifies findings against the repo but is not the only approver for an
  externally implemented change.

If agy wrote fallback code, agy does not get to be its only approver.

## Step 5 — land

Branch → validate → commit → push → **draft** PR → review gate → mark ready once
→ squash-merge → fast-forward the operator checkout. Keep the PR draft while
work moves; a self-hosted runner is capacity-one and shared with a live trading
stack, so batch pushes instead of triggering CI on each one.

Never direct-push to `main` for anything touching contracts, persistence or the
order path.

## What will go wrong, and what it means

- **A long answer times out while the model is still writing.** A 43 KB packet
  took over 8 minutes; a 17 KB review over 15. The complete answer is usually
  sitting in the browser afterwards — recover it from the last assistant message
  using the sentinels rather than resubmitting.
- **Whole-file replacement does not scale.** It works for files of a few KB. A
  25 KB file will not come back intact. Split the work or edit locally.
- **A healthy watchdog does not mean a drivable lane.** `cdp_watchdog --check-once`
  reporting READY has coexisted with three consecutive failed dispatches. Read
  the page body before blaming a selector.
- **CoderPX submits are currently unreliable.** Two invocations on 2026-08-29
  ended `SUBMIT_UNCONFIRMED` with `verified_model: null` — it failed proving the
  model in the live picker. Treat `SUBMIT_UNCONFIRMED` as terminal, never
  resubmit automatically, and after two rounds finish natively.
- **A failed dispatch can leave the packet in the composer.** Clear it before
  the next one, and check you are not typing into another lane's conversation.

## Report at the end

Report tests with exit codes, findings and fixes, exact SHAs, PR state and open
work. If a lane failed, say which and why — a blocked lane is recorded as
blocked, never quietly swapped for another.

The final section is the `/coderpx` ownership ledger: one row per plan,
implementation slice and reviewer, naming the executor/provider, verified model
and evidence-backed status. If agy implemented after a CDP problem, name
`Antigravity (agy)` explicitly.
