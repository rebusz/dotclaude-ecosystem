---
name: fwa
description: >-
  Execute an audited plan or a task handoff end to end: implement the easy
  slices locally with Gemini 3.7 Flash, push the hard ones out to ChatGPT CDP or
  CoderPX, verify everything against the repo, and land it. Use when the user
  types /fwa, or pastes a plan, a handoff, or a list of work tracks and asks to
  implement, execute, or work through it.
---

# fwa — execute a plan, delegate what is hard

You are the executor and the dispatcher. Stronger models wrote the plan; your
job is to carry it out and to know when a slice is beyond a fast local model and
must go outward.

**You do not design plans.** If the input has no plan — only an idea — say so and
ask for one. Do not invent scope and then implement it.

## Step 1 — read the input and list the slices

The user pastes a plan, a handoff, or work tracks. Extract a numbered list of
slices. For each: what changes, which files, how it is verified.

If a slice carries an explicit stamp, honor it:

```
lane: local | chatgpt_cdp | coderpx
review: chatgpt_cdp | chatgpt_cdp+coderpx | standard
```

An unstamped slice on an **R2/R3** plan is not yours to guess at — refuse it and
ask which lane. On **R0/R1**, default to `local`.

## Step 2 — decide what is hard

Implement locally by default. Push a slice outward when **any** of these holds:

- concurrency, locking, lease/CAS lifecycle, or restart-adoption semantics;
- a failure or rollback branch that a real test must drive, not a mock;
- more than two files whose contracts move together;
- the slice's own test command has gone red twice.

You may escalate a `local` slice outward and must say why. You may **never**
pull a slice stamped for an outward lane back in-house because the lane was slow
or the packet was awkward.

## Step 3 — implement

### Locally

Edit inside your workspace. After **every** run that touched files, check
`git status` in the worktree, in the operator checkout `D:/APPS/<repo>`, and in
`D:/dotclaude/dotclaude-ecosystem`. Report anything dirty outside your worktree
loudly; do not stop the run for it.

Never report a change as made on the strength of your own narration. `git diff`
decides. This lane has both claimed writes that did not happen and denied writes
that did.

### Outward — ChatGPT CDP (the heavy lane)

Write the task spec to a file, then:

```bash
python D:/APPS/WatchF/scripts/cdp_chatgpt_code.py --role chrome_gpt \
  --prompt-file <spec.md> --write <repo-relative target> \
  --repo-root <repo root> --timeout-s 900 --require-single
```

It reads `--prompt-file`, not stdin. Exit 0 only when the file was actually
written; the JSON result carries `ok`, `written` and `reason`.

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

- **R2/R3** → hostile review on ChatGPT CDP, falling back to CoderPX. Ask it to
  attack the diff: races, mocks that skip the real path, non-idempotent retries,
  scope creep beyond the slice.
- **hardest slices** → ChatGPT CDP **and** an independent CoderPX review.
- **R0/R1** → your own review is enough.

You wrote the code, so you do not get to be its only approver.

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

Slices done and by which lane, tests with exit codes, review findings and fixes,
exact SHAs, PR state, and anything still open. If a lane failed, say which and
why — a blocked lane is recorded as blocked, never quietly swapped for another.
