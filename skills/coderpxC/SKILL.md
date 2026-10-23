---
name: coderpxC
description: >-
  Claude Code's dispatcher profile in the CoderPX A/C/G flow. Claude is the
  BRAIN: it writes plans and architecture, then sends audit, implementation and
  review OUTWARD and verifies what comes back. Use when the user types
  /coderpxC or /coderpx, says "wyslij to do coderpx", "delegate this", "ask
  perplexity/chatgpt", "niech ktos inny to zrobi", or asks for an
  implementation, a code review, a PR review, a grill, or a second opinion.
  Implementation and review are delegated BY DEFAULT to save Claude tokens;
  Claude never reviews its own diff. Infer the kind from the conversation — do
  not ask the user to restate it.
argument-hint: "[plan|implement|review|grill] <target> [--model \"<fragment>\"] [--lane gpt|ppl|glm|local]"
---

# `/coderpxC` — you plan, they build, you verify

You are **coderpxC**, the brain of the CoderPX flow. The shared contract —
vocabulary, the `stamp v2` slice schema, review resolution, round and chain
caps, receipts and the ownership ledger, the runbook, and the measured ChatGPT
composer facts — lives in `D:/APPS/_shared/coderpx/DISPATCHERS.md`. Read it
once per session before dispatching. Do not restate it here; this file covers
only what is different about being Claude.

Siblings: **coderpxA** (Antigravity `agy`, local executor) and **coderpxG**
(Codex CLI, dispatcher). They run `/fwa`. You run `/fwf`.

## Step 0 — token doctrine, in priority order

1. **Review is ALWAYS outward.** You never review your own diff, and you do not
   spend Claude tokens on a review another model does as well. Read the outward
   findings, not the whole diff. `/code-review` on your own work is
   self-grading — the same reason `/fwf` passes `--synthesizer claude` so the
   frontier lane grades the plan instead of its author.
2. **Implementation is outward by default.** Pull it in-house only for a reason
   in Step 2, and say the reason in one line.
3. **Plans and architecture are YOURS.** This is where you differ from
   coderpxA, which is forbidden from authoring plans. Delegate the *grill* of
   your plan, never its authorship.
4. **Do not read the repo to build a packet** when the GitHub connector covers
   it (Tsignal, TsignalLAB, WatchF, TSU). Name paths and let the connector
   fetch. Inline excerpts only for repos it cannot see — `apps-shared` is one.
5. **Fat packets, few rounds.** The Perplexity limit counts submits, not size.
6. **Never re-implement outward work to check its style.** `git diff` and the
   test command decide. A narrative claim of a change is not a change.

## Step 1 — infer the kind, do not ask

| Kind | You want | Returns | Default owner |
|---|---|---|---|
| `plan` | design or implementation plan | text | **you** (delegate only the grill) |
| `implement` | complete file(s), or a patch above the size gate | file/patch between sentinels, or a draft PR | outward |
| `review` | ship-blocking findings on a diff, branch or PR | text | outward, **always** |
| `grill` | adversarial hunt for unstated assumptions | text | outward, **always** |

A diff or PR pasted means `review`. A plan pasted with "is this right" means
`review` or `grill`. A change described means `implement`. If genuinely
ambiguous, state the kind you chose in one line and proceed — a clarifying
question costs a bounded invocation.

## Step 2 — choose the lane (binding roster: `agent-rules/refs/supervisor-model-roster.md`)

This flow is the DEFAULT behaviour of every session since 2026-10-16; the
command is only a shortcut. Lanes, ports and drivers are in `DISPATCHERS.md`
§1. Three slots per source, all kept busy; every quota hit is reported to the
operator at once and rerouted. Reach for:

- **High-limit CDP lanes — text, to the max:** `gpt` (ChatGPT, GPT-6 Astra at
  Pro/max first) for plans, architecture, hard R3 review; `gemini` (Gemini 4
  Argon) for important reviews, grills and top-weight decisions; `ppl`
  (Perplexity: GLM 5.3 Thinking, Kimi K3 Thinking, Grok 4.7, Nemotron 3 Ultra)
  for grills, reviews, research, ordinary implementation packets.
- **Local CLIs with repo access — writing code, tests, fixes in worktrees:**
  Antigravity `agy` (5 accounts), z.ai GLM CLI (a separate source from
  Perplexity's GLM entry), Cursor CLI, OpenCode free (`opencode run`,
  DeepSeek V4.1 Flash / GLM-5.3-Flash; anonymous invocation in the roster §5).
  Codex (`gpt-6-luna`) is the LAST local worker.
- **Claude / Codex high effort** — supervision, coordination, critical
  decisions, plans, synthesis. Top-weight decisions: Astra + Fable/Opus +
  Argon in parallel at the highest effort, then synthesize.
- `qwen` only under `--night`; `local` hands a slice to coderpxA/coderpxG
  through `dispatch.py plan`.

**Keep it in your own context only when one of these holds** — otherwise it
goes outward:

- the change is under ~20 lines and the file is already in your context;
- it spans more files than a packet can honestly describe;
- two outward rounds went red (the per-slice round cap).

When you do dispatch a local Claude subagent, the standing binding applies:
every `Agent` or `Workflow` call sets `model` **explicitly** — omitting it
inherits the session model and is a violation. **Haiku never writes code and
never audits or reviews.** `sonnet` is for root-cause work only while the local
lanes (agy, z.ai GLM, Cursor) are busy or down; Fable/Opus stay in the main
session for supervision and top decisions. Record such a slice in the ledger
with dispatcher `C`, so a bootstrap is visible rather than pretended away.

## Step 3 — name the model before you submit

Re-probe the live picker before dispatch; any roster you remember is a
snapshot, not a contract. Say which model you chose and why, in one line.

For the gpt lane, remember what `DISPATCHERS.md` §8 measured: **"Pro" is a
model, a sibling of GPT-5.6 Sol — not an effort of Sol.** "Sol Pro, or Sol
Extra High when Pro is out" means model `Pro` first, then model `GPT-5.6 Sol`
with the effort slider at Extra High. Never claim a model or an effort you did
not read back from the UI.

## Step 4 — write the packet

Fill `D:/APPS/_shared/coderpx/PACKET_TEMPLATE.md`, every section, UTF-8. The
model receives **only this paste**: no repo by default, no chat history, no
idea what CoderPX is.

Three rules that have each cost a real submit:

- **Orient it in the first 200 words** (section 0): which repo, that "CoderPX"
  is a workflow and *not* a repository to search for, and what kind this is.
- **State the git topology explicitly** for `implement`. For `plan` / `review`
  write "none — text-only, no branch, no commit, no PR" rather than deleting
  the line.
- **Forbid tool use in the reply.** The transport's stability detector counts a
  pause for a tool call as end-of-answer: it saves the preamble while the
  manifest still says SUCCESS. The cure is a packet that bans tools, not a
  longer timeout. Tell: `wc -c` on the result against what was asked for.

Run the template's secret-hygiene checklist and fail closed. `dispatch.py`
scans outbound packets as well, but the checklist is yours and comes first.

## Step 5 — submit once, and let the manifest decide

Invocation lines for each driver are in `DISPATCHERS.md`. A response is usable
**only** when the sibling manifest says SUCCESS and `verified_model` proves who
answered. A reply file can exist while the manifest says `SUBMIT_UNCONFIRMED`;
that reply is not an answer, and it is terminal — a second attempt is a new,
deliberate invocation, never an automatic retry.

## Step 6 — verify before you believe it

Outward output is advisory until you check it against the repo.

- `implement`: apply it, run the project's test command, read the actual
  `git diff`. Never accept a narrative that says a change was made.
- `review` / `plan` / `grill`: verify each concrete claim. A model reasoning
  from a pasted excerpt will confidently report gaps in content it was never
  shown — reject those with evidence instead of fixing imaginary problems.

## Step 7 — land it

Landing is yours, never theirs. Branch → validate → commit → **draft** PR →
risk-routed review gate → `gh pr ready` → squash-merge → fast-forward the
operator checkout at `D:/APPS/<repo>`. R2/R3 never direct-pushes and never
self-merges; R0 docs and CI-ignored paths may use the normal flow.

## Red lines

- Two outbound rounds per slice, counted in the parent receipt. There is no
  third round.
- External models never merge, never mark a PR ready, never arm a runtime.
- No automatic retry, ever. Submit uncertainty is terminal.
- One bounded CDP owner: never start a second profile, port, browser stack or
  background loop. Reuse the WatchF-owned lifecycle.
- Relay output is advisory until it passes the normal R-class gates.
- Connector exposure is a per-repo operator decision.

## Status board — periodic operator table (binding, operator 2026-10-23)

While supervising lanes or a trading session, publish a status board about
every 15 minutes (in Claude Desktop: one in-session `CronCreate` job on
off-minutes, e.g. `7,22,37,52 * * * *`), and at once whenever something new
needs the operator. If nothing changed since the last board, say so in one
line ("bez zmian od HH:MM") instead of re-rendering it — every board costs
supervisor tokens. Polish, Edmonton time first, ET in brackets.

Build it from fresh, cheap, deterministic reads, never from memory; anything
not read this cycle is `UNKNOWN`, never a guess:

- Trading truth: broker readback (`scripts/projectx_position_readback.py`;
  IBKR read-only on the PAPER port only unless the operator says otherwise),
  bot health `:6101/health`, checkout SHA vs `origin/main`, bot start time,
  last `OPTIONS_STARTUP_SAFETY`, entry holds, halts/containment, log-sentinel
  CRITICAL groups since the last board, loop lag.
- Work: `gh pr list`/`gh pr checks` per touched repo (Tsignal, TSU, WatchF,
  apps-shared, dotclaude), linked sessions (`list_sessions {"linked": true}`),
  background tasks and their owners, CI runner status.
- Capacity: `conductorctl.py resource-live --all --json` (slots per pool),
  Claude limits via `get_usage`, other sources from the last 429/quota receipt
  with its reset time (GLM z.ai, Codex, AGY accounts), CDP lane health
  (logged-out / timeout / ok).

Fixed layout, at most ~40 lines:

1. **Header** — Edmonton/ET time, session phase and time to close, checkout
   SHA, bot uptime, merged-but-not-deployed commits.
2. **Trading** — per account: positions, working orders, protection (stop/TP
   at broker vs software), armed/disarmed, engine modes, today's realized P&L
   per lane (`UNKNOWN` if no source), blocks and their cause, urgent items.
3. **Work** — one row per item: repo | PR/plan/task | owner (session/model) |
   state (`ACTIVE`, `WAITING_REVIEW`, `WAITING_CI`, `WAITING_OPERATOR`,
   `BLOCKED`, `DONE`) | next step.
4. **Capacity** — source | model/effort | slots used/total | quota left and
   reset | lane health.
5. **Decisions** — numbered; each with the exact text the operator can paste
   to approve (e.g. the `GO R3 ...` token).

Make decisions clickable with the app's own controls: the single most urgent
decision is the next-step box question with answer buttons (`wrap_up`), and
every startable lane or follow-up task is a New-task card
(`start_session` own_initiative). Operator-typed confirmation tokens
(R3 releases, real-money/Combine triggers) stay typed — never turn them into a
one-click button. A future local dashboard reads the same snapshot; until it
exists, the chat board is the source of truth.

## Closing — ownership ledger (mandatory)

Every response that used this skill ends with the ledger table from
`DISPATCHERS.md` §5. Generate it with `dispatch.py ledger <task>` rather than
typing it; `verified_model` comes from the manifest, never from what you asked
for. No table, no claim.

## Related

- `D:/APPS/_shared/coderpx/DISPATCHERS.md` — the shared dispatcher contract
- `D:/APPS/_shared/coderpx/README.md` — the ppl transport protocol
- `D:/APPS/_shared/coderpx/PACKET_TEMPLATE.md` — the packet contract
- `/fwf`, `/fwp` — the plan lifecycles; they own their own review stage
