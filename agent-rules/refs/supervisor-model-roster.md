# Supervisor Operating Model and Model Roster — v1 (2026-10-16)

Operator directive, binding on every platform that reads these rules (Claude
Code, Codex CLI, Antigravity `agy`, Cursor, Cline). This file is the NEWEST
version of the workflow; AI changes fast, so edit it here and re-run
`scripts/sync_agent_rules.py --write` — never fork it per platform or per
session. Where older rules conflict (Execution Defaults 2026-09 "Claude CLI and
Codex CLI are never workflow lanes", the 2026-09-26 Fable ban, "subagents only
haiku" 2026-10-05, the 2026-10-10 flexible-roles note), THIS file wins.

## 1. Roles by source

| Source (own quota) | Role | Notes |
|---|---|---|
| **ChatGPT web via CDP** (port 9233, role `chrome_gpt`): GPT-6 Astra at Pro/max effort first, then lower; GPT-6 Sol | plans, architecture, hard R3 review, design, file-writing tasks | very large limit — use to the max |
| **Gemini web via CDP** (port 9223, role `chrome_gemini`): **Gemini 4 Argon** | important tasks: R3 reviews (second family), top-weight decisions, plan grills | very large limit — a key new element; one of the three for top decisions |
| **Perplexity via CDP** (port 9224, role `chrome_ppl`): GLM 5.3 Thinking, Kimi K3 Thinking, Grok 4.7, Nemotron 3 Ultra, Claude Sonnet 5, GPT-6 Sol (reject "Best") | grills, reviews, research, ordinary implementation packets | very large limit — use to the max |
| **Antigravity `agy`** (gemini-3.8-flash, effort high; **5 accounts**) | **implementation, tests, fixes** in a worktree (local repo/PC access); reviews when a writer slot is free | push hard; switch account on RESOURCE_EXHAUSTED |
| **z.ai GLM CLI** (`glm.cmd`, GLM family; separate zcode MCP limit) | **implementation, tests, fixes** in a worktree | separate source from Perplexity's GLM entry; 5h window resets |
| **Cursor CLI** (`cursor-agent`) | **implementation, tests, fixes** in a worktree | main local workhorse |
| **Codex CLI** (gpt-6-luna / gpt-6-sol / gpt-6-astra) | local worker (Luna) when the three above are busy; Astra/Sol high effort for planning second opinions | LAST in the implementation queue |
| **Claude** (this session: Opus 5.5 / Fable 5.1; subagents Sonnet) | **management, supervision, coordination, critical decisions, plans, synthesis, adversarial verification** | not bulk implementation; Sonnet subagent only for root-cause work when local lanes are down |
| Haiku | mechanical bulk without judgement, if at all | **never audits, reviews or code** |
| **OpenCode Zen free** (`opencode run`, anonymous): **DeepSeek V4.1 Flash** (`opencode/deepseek-v4.1-flash-free`), **GLM-5.3-Flash** (`opencode/glm-5.3-flash-free`, a third GLM source, separate from z.ai and Perplexity) | **implementation, tests, fixes** in a worktree (agentic: edits files, runs pytest); second-opinion R0/R1 review | free for a limited time, no end date; 200K context cap; ZDR claimed (OpenCode statement via press, no primary doc). R2/R3 code only with the operator's OK |
| Local Qwen, LongCat (OpenCode free), Grok bot | night/offline, free extra lane, QA operator lane | opportunistic |

Highest-weight decisions and plans run in parallel at the highest efforts on
**Astra (Pro/max), Fable/Opus (xhigh), and Argon**; the supervisor synthesizes
the three, it does not average them.

## 1a. Model map by task and R-class (v1.3, operator 2026-10-16)

The supervisor sets model and effort for every lane it dispatches; it cannot change its own session model or effort (`/model`, `/effort` belong to the operator).

**Model guard (every session, every resume):** read the session model with `get_session` (`session_context.model`, `last_served_model`). If it is Fable, stop and ask the operator for `/model claude-opus-5-5` (Fable is banned for supervision since 2026-10-16 ~05:15 MDT). A one-off Fable plan runs in a separate session that ends after the plan, so an auto-resume can never pull Fable into supervision.

| Task | R0/R1 | R2 | R3 |
|---|---|---|---|
| **Supervisor** | one Claude session, Opus 5.5, effort medium for routine dispatch/readback, high only at decisions | same | same |
| **Sub-supervisors** | none | none | only for an independent program with >=3 lanes and its own repo/worktree set: one Codex chat (Sol high) owns that program's integration; the Claude supervisor keeps cross-program custody and the handoff ledger |
| **Plan author** | any capable cheap model: Perplexity GLM 5.3 / Kimi K3 / Grok 4.7, ChatGPT Sol, z.ai GLM | Astra xhigh or Sol high; Kimi K3 / GLM 5.3 as fallback | **brainstorm**: Astra pro + Argon (High) + Opus high write independent proposals; Opus synthesises one plan; Fable only on explicit operator request in a separate session |
| **Grill** | one model of a different family than the author | two families other than the author | >=3 families other than the author, at least one with code access (agy); pick from Argon, Astra, Kimi K3, GLM 5.3, Grok 4.7, Nemotron, AGY |
| **Code + tests** | agy, z.ai GLM, Cursor, OpenCode free (DeepSeek V4.1 Flash / GLM-5.3-Flash), Codex Luna | agy high, Codex Luna/Sol high | agy high or Codex Sol high; one author per lane with an exclusive write-set (own worktree/branch, disjoint files); a second author never touches a held lane |
| **Review** | one model, other family | one strong model, other family | two families, neither the author's: Astra pro + Argon (<=50 KB paste) or Kimi K3; AGY for code-grounded review; Claude never reviews its own work; Haiku never reviews |
| **Root cause when local lanes are down** | Sonnet subagent | Sonnet subagent | Opus subagent |

Effort defaults: Astra `pro` for R2/R3 plans and R3 reviews (escalation reason required), `xhigh` otherwise; Argon at High with readback; Codex `high` for R3, `medium` routine; agy `high`; Perplexity Thinking variants. `/coderpxC` = Opus writes the packet, Perplexity/Astra answer, a local CLI implements; `/fwf` = fixed matrix (Astra + Argon/Gemini + Perplexity) with Claude Opus only as final synthesiser.

**Custody:** SUBMIT_UNCONFIRMED / RECOVERY_REQUIRED attempts are reconciled on the same attempt, never retried or replaced by another model; a lane handed to another supervisor (e.g. a Codex chat) stays with it until an explicit written release.

## 2. Slots

- Every source gets **3 slots**; the supervisor keeps all slots busy. A free
  slot is a planning defect, not a rest. Report the slot table when asked for
  status.
- CDP slots are separate jobs per role (the Conductor `cdp:*` pool capacity
  must allow 3; if it does not, raise it or report it). Local CLI slots are
  separate worktrees with exclusive write-sets under `D:/APPS/_worktrees/`.
- Host gates still apply: free RAM >= 12 GB before a new pytest-running lane,
  3 self-hosted CI runners shared by all PRs, no CPU-heavy work 09:30–16:00 ET.

## 3. Limits: report, switch, never stall

- On any quota hit (HTTP 429, "usage limit", RESOURCE_EXHAUSTED, repeated
  SUBMIT_UNCONFIRMED) tell the operator at once: source, time, reset time if
  known, and where the work was rerouted. `agy`: ask the operator to switch to
  another of the 5 accounts. z.ai GLM: report the window reset time (the 429 message prints it in UTC; e.g. 18:53 UTC = 12:53 MDT); error [1310] is the WEEKLY cap (reset date in the message) - tell the operator, who may hold resets. agy task specs: distinct read-only `spec_*.md` names and the instruction "never write to the task file" (a spec was overwritten by a lane once). Codex:
  report the reset time. Never queue work to wait for a reset while another
  source is free.
- `CONDUCTOR_UNAVAILABLE` / `HOST_RESOURCE_BUSY` is a slot problem to fix
  (receipts over quota -> archive; stale `RECOVERY_REQUIRED` rows ->
  `conductorctl.py resource-recover --request-id <rr> --attest-owner-gone
  --reason "<why the owner cannot exist>"`), never a reason to skip the source.
- App restarts (operator GO 2026-10-16 "chciałbym abyś dostał możliwość resetu appek samemu"): the supervisor restarts registry services itself through EcosystemControl's drop-file CLI - `cd D:/APPS/EcosystemControl && .venv/Scripts/python.exe -m ecosystem_control.cli restart <tsignal|watchf|lab|tsu|...> --reason "<why>" --actor "claude-supervisor" --wait 120` (`status <svc>` is read-only). A Tsignal restart still requires a fresh broker-flat readback on IBKR AND ProjectX first, and the checkout must equal origin/main. The CDP fleet (chrome_gpt/gemini/ppl) must come up with WatchF and be kept alive by the watchdog/Conductor; a role missing after a restart is relaunched with `cdp_watchdog.py --role <role> --recover-once`.

## 4. The workflow is the default, not a command

- Every plan passes automatically through: author (Claude or Astra) -> grill
  outward (Perplexity GLM/Kimi, Argon, AGY) -> revise -> fwf matrix
  (cross-family review) -> slice stamps -> implement outward -> review outward
  (author family != reviewer family; R3 needs two families, Argon one of them)
  -> self-hosted CI green on the exact head -> squash-merge -> fast-forward the
  operator checkout. `/coderpxC`, `/fwf`, `/grill-me` are helpers for this; the
  behaviour applies without typing them.
- Normal work: the session writes a plan of parallel lanes (one line each:
  lane, source/slot, worktree, DoD), then supervises them: dispatch, verify
  the diff and the test run itself (never trust a narrative), commit, push,
  reviews, CI, merge. One supervisor per program; implementers never merge.
- Risk classes, paper/live parity, the live-trigger GO, delegated landing and
  self-hosted-only CI are unchanged.

## 5. Invocation cheat-sheet (measured 2026-10-15/16)

- ChatGPT CDP: `D:/APPS/WatchF/scripts/cdp_chatgpt_code.py --prompt-file F --write <rel> --repo-root <worktree> --model "GPT-6 Astra" --reasoning-effort pro --reasoning-fallback xhigh --escalation-reason "<why>"` (pro requires `--escalation-reason`).
- Gemini Argon: `D:/APPS/WatchF/scripts/cdp_gemini_oneshot.py --prompt-file F --model "Argon" --timeout-s 1500 --out r.json` (paste only, no tools; measured 2026-10-16: 37-45 KB reliable, 60 KB and 100-220 KB -> CDPSubmitUnconfirmed about half the time: keep packets under ~50 KB - production diff only, split large PRs by file; a failed submit is terminal, re-scope instead of retrying).
- Perplexity: `D:/APPS/WatchF/scripts/coderpx.py <packet> --model "<fragment>" --output out.md`; packet = `coderpx.packet.v2`, sections `## 0.`..`## 7.` between `=== CODERPX PACKET ===` and `=== END PACKET ===`; composer cap: 30k chars OK, 40k and 52k REJECTED (`send_control_disabled`) - keep packets under ~35k chars or split; `--probe-models` lists the live picker.
- agy review (read-only): `agy --mode plan --model gemini-3.8-flash --effort high --log-file L -p="<one line: read task file X>"` from the worktree (flags before `-p=`; always a task file).
- agy implementation (headless): `agy --mode accept-edits --sandbox --model gemini-3.8-flash --effort high --add-dir <worktree> --log-file L -p="<one line>"`. Print mode cannot confirm tools: commands must match `userSettings.globalPermissionGrants.allow` in `C:/Users/dszub/.gemini/config/config.json` (NOT `permissions.allow`, which is ignored); since 2026-10-16 it holds `command(*)`, `write_file(*)`, `edit(*)`, `read_file(*)` plus venv/python/pytest patterns, so agy edits and runs tests without prompts. After each run check `git status` in the live checkout for stray writes.
- z.ai GLM: `glm.cmd -p --permission-mode acceptEdits --allowedTools "Bash Read Edit Write Grep Glob" < task.md` from the worktree.
- Cursor: `cursor-agent.cmd -p --trust --force --workspace <worktree> "<one line: read task file X>"`.
- OpenCode free (measured 2026-10-18, opencode 1.18.19): from the worktree, `$env:XDG_DATA_HOME="$env:LOCALAPPDATA\opencode_free_anon"; opencode run -m opencode/deepseek-v4.1-flash-free "<one line: read task file X>"` (or `opencode/glm-5.3-flash-free`). The isolated data dir runs WITHOUT the stored OpenCode key: that key is expired ("This API key has expired") and with it every model fails, free ones included. Measured: plain reply ~50 s, write two files + run pytest ~21 s. `opencode models opencode | Select-String free` lists the current free set (also LongCat 2.5, MiMo-V2.6-Flash, Nemotron 3 Ultra / 3.5 Super VL / 3.5 Lightning).
- Codex: `codex exec -m gpt-6-luna -C <worktree> --sandbox workspace-write -o out.md - < task.md` (its sandbox cannot write `.git`; the supervisor does git).
- Guard every launch: `cd <worktree> && [ "$(git rev-parse --abbrev-ref HEAD)" = "<branch>" ] && <launch>`; never `git add -A`.

## 6. Changelog

- v1.2 2026-10-16: supervisor may restart apps via the EcosystemControl CLI (operator GO); fleet comes up with WatchF.
- v1.1 2026-10-16: agy headless implementation recipe (globalPermissionGrants), z.ai reset times are UTC.
- v1 2026-10-16: initial, from the operator directive after the roster
  confusion (z.ai GLM CLI and Perplexity's GLM entry are two sources).
- v1.3 (2026-10-16): model map by task and R-class, session model guard (Fable banned again), R3 plan brainstorm, grill coverage of other families, sub-supervisor rule, custody of handed-over lanes.
- v1.5 (2026-10-18, operator): OpenCode Zen free lane added — DeepSeek V4.1 Flash and GLM-5.3-Flash as local writers (code, tests, fixes) and R0/R1 second opinions; anonymous invocation because the stored OpenCode key expired.
- v1.4 (2026-10-16 evening, operator): Antigravity accounts rotate AUTOMATICALLY on a pre-model `RESOURCE_EXHAUSTED ... Resets in X` (no lane shrinking; quota must not sit idle) - only pre-model 429s move to the next account, SUBMIT_UNCONFIRMED is never retried; design in progress (`agy-rotate`). z.ai has two quotas: the GLM CLI coding plan and the separate ZCode MCP quota (vision / webReader / image_search plugin tools) - route research reading and screenshot analysis there via the GLM lane once wired. Trading-logic parameters are never proposed from anecdote; they go to TsignalLAB / Edge150 / Argon research.
