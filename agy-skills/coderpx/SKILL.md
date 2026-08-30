---
name: coderpx
description: >-
  Send one bounded packet to a Perplexity picker model through the CoderPX CDP
  lane and verify what comes back. Use when the user types /coderpx, says
  "send this to coderpx", "ask perplexity", or asks for a second opinion, a
  hostile review, a plan, a grill, or an implementation from Kimi K3, Grok 4.6,
  Claude Sonnet 5, GPT-5.6 Terra, Sonar 2, Gemini 3.7 Flash, GLM 5.3 or
  Nemotron 3 Ultra. Infer the task kind from the conversation; do not ask the
  user to restate it.
---

# CoderPX — one bounded submit to a Perplexity model

CoderPX is a **transport**, not a model and not a lane per model. The model is a
call parameter. "CoderPX Kimi" is not a thing — it is CoderPX invoked with
`--model "Kimi K3"`.

## Step 1 — infer the kind from context, do not ask

Read the conversation and pick one. The kind decides the packet and the model.

| Kind | You are asking for | Return |
|---|---|---|
| `implement` | a complete file, whole-file replacement | file content between sentinels |
| `review` | ship-blocking findings on a diff or a file | text |
| `plan` | a design or implementation plan | text |
| `grill` | adversarial interrogation of an idea, hunting for unstated assumptions | text |

If the user pasted a diff or named a PR → `review`. If they pasted a plan and
asked "is this right" → `review` or `grill`. If they described a change to make
→ `implement`. If genuinely ambiguous, state the kind you chose in one line and
proceed; do not stall a bounded lane on a clarifying question.

## Step 2 — pick the model

Verified live 2026-08-29 via `--probe-models`: Sonar 2, GPT-5.6 Terra,
Gemini 3.7 Flash, Claude Sonnet 5, Kimi K3, GLM 5.3, Grok 4.6, Nemotron 3 Ultra.

- **Strong** — `plan`, `review`, `grill`: `Kimi K3`, `Grok 4.6`,
  `Claude Sonnet 5`, `GPT-5.6 Terra`.
- **Fast** — mechanical `implement`: `Sonar 2`, `Gemini 3.7 Flash`, `GLM 5.3`.

**GPT-5.6 Sol and Claude Opus 5 are NOT available.** The subscription is
Perplexity **Pro**, not Max. Do not put them in a packet and do not tell the
user to pick them. Heavy GPT work goes to the ChatGPT CDP lane instead.

Name the model you chose and why, in one line, before you submit.

## Step 3 — write the packet

Fill `D:/APPS/_shared/coderpx/PACKET_TEMPLATE.md`. Every section. The model
receives **only this paste** — no repo, no chat history, no idea what CoderPX is.

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

## Step 4 — submit once

```bash
python D:/APPS/WatchF/scripts/coderpx.py <packet.md> --model "<picker fragment>" --output <result.md>
```

All three are required — the script refuses without a positional packet path,
`--model` and `--output`. There is no `--timeout-s`; the flag is
`--response-timeout-s`. It does not read stdin.

`--probe-models` lists the live picker if you need to check what is selectable.

## Step 5 — the manifest decides, not the reply

The response is usable **only** when the sibling `<result>.md.meta.json` says
`"status": "SUCCESS"`. Check `verified_model` too — it proves which model
actually answered. A reply file can exist while the manifest says
`SUBMIT_UNCONFIRMED`; that reply is not an answer.

**`SUBMIT_UNCONFIRMED` is terminal.** Never resubmit automatically. A second
attempt is a new, deliberate invocation.

## Step 6 — verify before you believe it

Perplexity output is advisory until you check it yourself.

- `implement`: apply the file, run the project's tests, read the actual diff.
  Never trust a narrative that says a change was made — `git diff` decides.
- `review` / `plan` / `grill`: verify each concrete claim against the repo.
  A model reasoning from a pasted excerpt will confidently report gaps in
  content it was never shown. Reject those with evidence rather than fixing
  imaginary problems.

## Red lines

- **Two rounds maximum.** After two submits without green tests, finish the work
  natively. Do not send a third.
- **CoderPX never merges.** Output arrives as text or a draft PR. Landing is
  yours, through the normal branch → PR → review → merge lifecycle.
- **No secrets in packets.** No `.env`, tokens, credentials, keys, account ids,
  balances, or PII. Code and specs only. If a packet cannot be made clean, it
  does not leave the machine.
- **The GitHub connector is not automatic.** CoderPX has an
  `--expect-github-connector` flag that only records intent — it never clicks or
  verifies anything. If your packet asks the model to read the repo, it may
  silently ignore that and invent the contents. Inline the code you need, or
  treat repo claims in the reply as unverified.
