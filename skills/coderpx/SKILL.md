---
name: coderpx
description: >-
  Model dispatcher: send one bounded packet OUTWARD — to a Perplexity picker
  model over chrome_ppl, or to ChatGPT Sol over chrome_gpt — and verify what
  comes back. Use when the user types /coderpx, says "wyslij to do coderpx",
  "delegate this", "ask perplexity/chatgpt", "niech ktos inny to zrobi", or
  asks for an implementation, a code review, a PR review, a grill, or a second
  opinion. Claude stays the brain: it qualifies the task, writes the packet,
  verifies the reply against the repo, and owns the land-on-main lifecycle.
  Implementation and review are delegated BY DEFAULT to save Claude tokens;
  Claude never reviews its own diff. Infer the kind from the conversation — do
  not ask the user to restate it.
argument-hint: "[plan|implement|review|grill] <target> [--model \"<fragment>\"] [--lane ppl|gpt|local]"
---

# `/coderpx` — you dispatch, they type, you land

CoderPX is a **transport**, not a model and not a per-model lane. The model is a
call parameter: "CoderPX Kimi" is not a thing — it is CoderPX invoked with
`--model "Kimi K3"`.

**Your role in this skill is dispatcher, verifier and merger — not typist.**
The operator pays Claude tokens for judgment: qualification, packet authoring,
verification against the repo, and the land-on-main lifecycle. Implementation
and review belong outward by default. Every token spent re-deriving what an
external model already produced is a token wasted.

## Step 0 — token doctrine (the reason this command exists)

Binding, in priority order:

1. **Review is ALWAYS outward.** You never review your own diff, and you do not
   burn Claude tokens on a review another model does as well. Read the outward
   findings, not the whole diff. `/code-review` on your own work is
   self-grading — the same reason `/fwf` and `/fwp` pass `--synthesizer claude`
   so the frontier lane reviews the plan instead of the author.
2. **Implementation is outward by default.** Pull it in-house only for the
   reasons in Step 2, and say why in one line.
3. **Plans and architecture are YOURS.** This is where the `agy` version and
   this one diverge: `agy` is forbidden from writing plans; you are the
   architect. Delegate the *grill* of your plan, never its authorship.
4. **Do not read the repo to build a packet** when the GitHub connector covers
   it (Tsignal, TsignalLAB, WatchF, TSU — operator decision 2026-08-14). Name
   paths and let the connector fetch. Inline excerpts only for repos it cannot
   see.
5. **Fat packets, few rounds.** The Perplexity usage limit counts *submits*, not
   size. One complete packet beats three thin ones.
6. **Never re-implement outward work to check its style.** `git diff` and the
   test command decide. A narrative claim of a change is not a change.

## Step 1 — infer the kind from context, do not ask

| Kind | You are asking for | Return | Default owner |
|---|---|---|---|
| `plan` | design / implementation plan | text | **you** (delegate only the grill) |
| `implement` | complete file(s), whole-file replacement | file between sentinels, or draft PR | outward |
| `review` | ship-blocking findings on a diff / branch / PR | text | outward, **always** |
| `grill` | adversarial hunt for unstated assumptions | text | outward, **always** |

Diff or PR pasted → `review`. A plan pasted with "is this right" → `review` or
`grill`. A change described → `implement`. If genuinely ambiguous, state the
kind you chose in one line and proceed — a clarifying question costs a bounded
invocation.

## Step 2 — choose the lane

| Lane | Transport | Reach for it when |
|---|---|---|
| `gpt` | `cdp_chatgpt_code.py` → `chrome_gpt` (9233) | heavy reasoning: concurrency, lease/CAS lifecycle, restart-adoption, R3 order path, PR audits |
| `ppl` | `coderpx.py` → `chrome_ppl` (9224) | plans, reviews, grills, ordinary single-slice implementation |
| `local` | Claude subagent / `qwen` MCP / `agy --mode plan` | outward failed twice, or the task needs repo-wide context no packet can honestly carry |

**Keep it local only when one of these holds** — otherwise it goes outward:

- the change is under ~20 lines and the file is already in your context;
- it spans more files than a packet can honestly describe;
- two outward rounds went red (the 2-round cap, below).

Local dispatch obeys the standing binding: **implementation never runs on Fable
or Haiku**, and every `Agent` / `Workflow` call sets `model` **explicitly** —
omitting it inherits the session model and is a violation. `sonnet` is the
default implementation lane, `opus` for hard work.

## Step 3 — pick the model, and name it

Roster snapshot (`coderpx.py --probe-models`, 2026-08-27, refreshed with
operator picker evidence 2026-08-30): `Sonar 2`, `GPT-5.6 Terra`,
`Gemini 3.7 Flash`, `Claude Sonnet 5`, `Kimi K3`, `GLM 5.3`, `Grok 4.6`,
`Nemotron 3 Ultra`, plus the `Best` auto-router. **Re-probe before dispatch** —
this is a snapshot, not a contract.

- **Strong** (`plan`, `review`, `grill`, deep analysis, multi-file refactor):
  `GLM 5.3` (Reasoning — top Perplexity), `Kimi K3`, `Grok 4.6`,
  `Claude Sonnet 5`, `GPT-5.6 Terra`.
- **Fast** (mechanical `implement`): `Sonar 2`, `Gemini 3.7 Flash`.
- **ChatGPT lane**: `GPT-5.6 Sol (Pro)` / `Sol (Reasoning Extra High)`.

**`GPT-5.6 Sol Max` and `Claude Opus 5 Max` are NOT selectable** on this
subscription — padlocked, and the 2026-08-27 probe shows Perplexity does not
even emit locked entries as `[role='menuitemradio']`. Never recommend either;
heavy GPT work goes to the ChatGPT lane instead. `Claude Sonnet 5` **is**
allowed here: WatchF's `claude_killswitch` blocks Anthropic-billed transports
but exempts the Perplexity-billed Sonnet aliases.

Kimi 3 through the picker is **live**. The retirement recorded in
`run-model-team` covers the standalone Kimi CLI lane only.

Say which model you chose and why, in one line, before submitting.

## Step 4 — write the packet

Fill `D:/APPS/_shared/coderpx/PACKET_TEMPLATE.md` — every section, saved UTF-8.
The model receives **only this paste**: no repo by default, no chat history, no
idea what CoderPX is.

Three rules that have each cost a real submit:

- **Orient it in the first 200 words** (section 0): which repo, that "CoderPX"
  is a workflow and *not* a repository to search for, and what kind this is.
- **State the git topology explicitly** for `implement` — which branch is head,
  which is base. For `plan` / `review` write "none — text-only, no branch, no
  commit, no PR" rather than deleting the line.
- **Forbid tool use in the reply.** The transport's stability detector counts a
  pause for a tool call as end-of-answer: it saves the preamble while the
  manifest still reports SUCCESS. The cure is a packet that bans tools, **not**
  a longer timeout. Tell: `wc -c` on the result against what was asked for.

`implement` output contract — the whole file, top to bottom:

```
<<<FILE_BEGIN>>>
...entire file, indentation intact...
<<<FILE_END>>>
```

Run the template's **secret-hygiene checklist** and fail closed. No `.env`,
tokens, credentials, keys, account ids, balances, PII. If a packet cannot be
made clean, it does not leave the machine.

## Step 5 — submit once

Perplexity:

```bash
python D:/APPS/WatchF/scripts/coderpx.py <packet.md> --model "<picker fragment>" --output <result.md>
```

The positional packet path, `--model` and `--output` are all required; it does
not read stdin. The flag is `--response-timeout-s`, not `--timeout-s`.
`--probe-models` lists the live picker. `--expect-github-connector` **records
caller intent only** — it never clicks or verifies the connector, so a packet
that asks the model to read the repo may be silently ignored.

ChatGPT:

```bash
python D:/APPS/WatchF/scripts/cdp_chatgpt_code.py --role chrome_gpt --prompt-file <spec.md> --write <repo-relative target> --repo-root <repo root> --timeout-s 900 --require-single
```

It reads `--prompt-file`, not stdin. Exit 0 only when the file was actually
written; the JSON result carries `ok`, `written`, `reason`.

`coderpx.py` acquires the Conductor `host:heavy` capacity-one lease. Check
Conductor status before starting another heavy lane, and recover/release
afterwards — an orphaned `host:heavy` lease held by a dead PID wedges every
other consumer on the box.

## Step 6 — the manifest decides, not the reply

The response is usable **only** when the sibling `<result>.md.meta.json` carries
`"status": "SUCCESS"`. Check `verified_model` too — it proves which model
actually answered. A reply file can exist while the manifest says
`SUBMIT_UNCONFIRMED`; that reply is not an answer.

**`SUBMIT_UNCONFIRMED` is terminal.** Never auto-resubmit. A second attempt is a
new, deliberate invocation.

Known lane failure: `chrome_gpt` READY in the watchdog does **not** mean the
lane sends — the composer's Chat/Work radio sits on Work when the box is empty
and eats the submit. READY is not drivable.

## Step 7 — verify before you believe it

Outward output is advisory until you check it against the repo.

- `implement`: apply it, run the project's test command, read the actual
  `git diff`. Never accept a narrative that says a change was made.
- `review` / `plan` / `grill`: verify each concrete claim. A model reasoning
  from a pasted excerpt will confidently report gaps in content it was never
  shown — reject those with evidence instead of fixing imaginary problems.

## Step 8 — land it

Landing is yours, never theirs. Branch → validate → commit → **draft** PR →
risk-routed review gate → `gh pr ready` → squash-merge → fast-forward the
operator checkout at `D:/APPS/<repo>`. R2/R3 never direct-pushes and never
self-merges; R0 docs and CI-ignored paths may use the normal flow.

## Red lines

- **Two rounds maximum.** After two submits without green tests, finish
  natively. There is no third round.
- **External models never merge.** They deliver text, files between sentinels,
  or at most a branch `coderpx/<task-id>` with a draft PR.
- **No automatic retry, ever.** Submit uncertainty is terminal.
- **One bounded CDP owner.** Never start a second profile, port, browser stack,
  or background loop. Reuse the WatchF-owned lifecycle.
- **Relay output is advisory** until it passes the normal R-class gates. Nothing
  from a relay writes live decision or order state.
- **Connector exposure is a per-repo operator decision** — private-repo content
  transits Perplexity *and* the picked provider at inference time.

## Closing — Ownership Ledger (mandatory)

Every response that used `/coderpx` ends with this table. No table, no claim.

| Task | Kind | Transport | Verified model | Status |
|---|---|---|---|---|
| Plan refactor of module X | plan | Claude (in-session) | Opus 5 | AUTHORED |
| Grill of that plan | grill | ChatGPT CDP | GPT-5.6 Sol (Pro) | SUCCESS |
| Implement slice 1 | implement | CoderPX (chrome_ppl) | GLM 5.3 | SUCCESS (pytest exit 0) |
| PR review | review | CoderPX (chrome_ppl) | Kimi K3 | MERGE-AFTER-FIX |

`Verified model` comes from the manifest's `verified_model`, not from what you
asked for. `Status` is the manifest status plus the local test exit code.

## Related

- Protocol and red lines: `D:/APPS/_shared/coderpx/README.md`
- Packet contract: `D:/APPS/_shared/coderpx/PACKET_TEMPLATE.md`
- `/coderpx-packet` — the manual fallback: authors the packet and copies it to
  the clipboard for the operator to paste by hand. Use it only when the CDP
  transport is down.
- `/fwf`, `/fwp` — the plan lifecycles; they own their own review stage. Do not
  duplicate it with `/coderpx`.
