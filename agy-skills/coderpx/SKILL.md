---
name: coderpx
description: >-
  Antigravity-only dispatcher for delegated planning, implementation and PR
  review through supervisor-owned ChatGPT CDP and Perplexity CoderPX lanes.
  Use when an agy user invokes /coderpx or asks agy to route model work. Never
  let agy author a plan itself; preserve verified model identity and finish
  with a task-by-task ownership ledger.
---

# CoderPX — Antigravity model dispatcher

This skill is for **Antigravity (agy) only**. It is installed under
`~/.gemini/config/skills/`; it is not a Claude Code or Codex workflow.

`/coderpx` owns task routing across two supervisor-owned transports:

- **ChatGPT CDP** on `chrome_gpt` for GPT-5.6 Sol;
- **Perplexity CoderPX** on `chrome_ppl` for Kimi K3, Claude Sonnet 5,
  Grok 4.6 and GPT-5.6 Terra.

CoderPX is a transport, not a model. Always record the provider, requested
model, verified model and assigned task separately.

## Step 1 — infer the task kind

Read the conversation and choose the kind without making the user restate it.

| Kind | Meaning | Expected result |
|---|---|---|
| `plan` | create a design or implementation plan | delegated plan text |
| `implement` | produce a complete bounded code change | file content or verified diff |
| `review` | review a PR, exact-head diff or file | ship-blocking findings |
| `grill` | adversarially test assumptions | findings and unresolved questions |

A pasted diff or named PR means `review`. A requested change means
`implement`. A request to design work means `plan`.

Choosing `plan` does **not** authorize agy to write or synthesize the plan.

## Step 2 — route by task and risk

### Plans

Antigravity has no authority to author plans itself.

1. Primary: ChatGPT CDP with verified **GPT-5.6 Sol (Pro)**.
2. If Pro mode cannot be selected and verified: ChatGPT CDP with
   `gpt-5.6-sol` and verified `reasoning_effort=xhigh` (Extra High).
3. If the ChatGPT CDP route is unavailable or blocked: Perplexity CoderPX with
   **Kimi K3**.

Agy may prepare the bounded packet, verify the returned plan against the repo
and present it. It must not fill in missing plan sections from its own
reasoning. An unverified or failed external result is `NO_PLAN`, not permission
for agy to create one.

### Implementation

For ordinary implementation, assign exactly one Perplexity CoderPX model:

- **Kimi K3**
- **Claude Sonnet 5**
- **Grok 4.6**
- **GPT-5.6 Terra**

Choose the best fit for the bounded task and state the choice before dispatch.
Do not use Sonar, Gemini, GLM or Nemotron as implementation substitutes.

For difficult implementation — especially concurrency, lifecycle, recovery,
multi-file contract movement or R3 execution-path work — prefer ChatGPT CDP
with verified **GPT-5.6 Sol (Pro)**. If Pro cannot be verified, use Sol with
verified `reasoning_effort=xhigh`.

Only after a concrete CDP blocker or terminal dispatch failure is recorded may
Antigravity implement the slice itself. Label that row
`Antigravity (agy)`; do not silently turn local work into the default route.

### PR review and grill

1. Primary: ChatGPT CDP with verified **GPT-5.6 Sol (Pro)**.
2. If Pro cannot be verified: Sol with verified
   `reasoning_effort=xhigh`.
3. If fresh readback shows ChatGPT already owns active work, use Perplexity
   CoderPX with **Kimi K3** instead of queueing an avoidable competing review.

For a serious R3 PR, two independent reviewers may be used: ChatGPT Sol and
Kimi K3. They must inspect the same exact head and produce separate evidence.
Respect Conductor capacity; independent does not require simultaneous launch.

## Step 3 — prove the selected route

Use fresh supervisor/job-manager readback when deciding whether ChatGPT is busy.
Do not infer load from an open browser tab, a stale artifact or configured
provider names.

Before dispatch, state in one line:

`<task> -> <provider> / <requested model> / <requested effort> because <reason>`

ChatGPT selection is valid only when the result proves the observed Sol model
label. When Extra High is requested, the result must also prove the selected
reasoning effort. If the available wrapper cannot request and verify
`reasoning_effort=xhigh`, that fallback is unavailable; never silently use the
account default.

## Step 4 — prepare the packet

For Perplexity, fill `D:/APPS/_shared/coderpx/PACKET_TEMPLATE.md`. Every
section is required. The model receives **only this paste** — no repo and no
chat history.

For ChatGPT CDP, prepare the same bounded context: task, repo, risk class,
head/base topology, writable files, exact constraints, verification command and
the current content needed to answer without guessing.

Two rules that cost real submits when broken:

- **Orient it in the first 200 words.** Say which repo, that "CoderPX" is a
  workflow and not a repository to search for, and what kind of task this is.
- **State the git topology explicitly** for `implement`, including which branch
  is head and which is base. A packet that leaves the model guessing burns a
  whole round on a clarifying question.

For `implement`, the reply must carry the whole file between sentinels:

```
<<<FILE_BEGIN>>>
...the entire file, top to bottom, indentation intact...
<<<FILE_END>>>
```

Never send secrets, credentials, account data, balances or PII.

## Step 5 — submit through the owned transport

Perplexity CoderPX:

```bash
python D:/APPS/WatchF/scripts/coderpx.py <packet.md> --model "<picker fragment>" --output <result.md>
```

All three are required — the script refuses without a positional packet path,
`--model` and `--output`. There is no `--timeout-s`; the flag is
`--response-timeout-s`. It does not read stdin.

`--probe-models` lists the live picker if you need to check what is selectable.

ChatGPT work must use the supervisor-owned `chrome_gpt` path with explicit Sol
model identity. Do not route Sol through Perplexity and do not create a second
browser or lifecycle owner.

## Step 6 — evidence decides

For Perplexity, use the reply only when the sibling
`<result>.md.meta.json` says `"status": "SUCCESS"` and carries a matching
`verified_model`.

For ChatGPT, require the result artifact to prove success, the observed Sol
model label and — when requested — the observed reasoning effort.

`SUBMIT_UNCONFIRMED` is terminal. Never automatically resubmit an ambiguous
attempt. A second submit is a new deliberate assignment, and Perplexity remains
capped at two rounds.

## Step 7 — verify the work

External model output is advisory until agy checks it against the repo.

- `implement`: inspect the actual diff and run the real tests, including the
  failure or rollback path.
- `review` / `grill`: verify every concrete finding against the exact PR head
  and reject claims based on omitted context.
- `plan`: verify repo paths, existing contracts, risk class and definition of
  done. Do not rewrite the plan locally.

CoderPX and ChatGPT never merge. Agy owns verification and the normal landing
lifecycle after the required review gates pass.

## Step 8 — end with an ownership ledger

End every answer with a compact Markdown table in the user's language. It is
the final section and contains one row per plan, implementation slice and
review assignment. Two R3 reviewers get two separate rows.

| Task | Work | Executor / provider | Verified model | Status |
|---|---|---|---|---|
| concise user-facing task | `plan`, `implement`, `review` or `grill` | ChatGPT CDP, Perplexity CoderPX, or Antigravity (agy) | observed model or `UNVERIFIED` | evidence-backed status |

- Attribute accepted work from dispatch/result evidence and the actual diff,
  not from branch names or narration.
- For successful CDP work, copy the observed/verified model exactly.
- If model identity is absent, write
  `UNVERIFIED (requested: <model>)`. If no submit occurred, write
  `NOT USED (requested: <model>)`.
- When agy implemented after a recorded CDP problem, name
  `Antigravity (agy)` as executor and include its runtime model only if that
  identity is observable.
- Do not list models that were considered but never assigned.

## Red lines

- Agy never authors or completes a plan.
- Agy implementation is a recorded fallback, never the default.
- Never claim Pro, Extra High or a Perplexity model without observed identity.
- Never send a third Perplexity attempt.
- Never put secrets or live account data in a packet.
- External models never merge, mark Ready, arm runtime or perform broker/order
  actions.
