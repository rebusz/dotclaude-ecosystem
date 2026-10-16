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
| Local Qwen, LongCat (OpenCode), Grok bot | night/offline, free extra lane, QA operator lane | opportunistic |

Highest-weight decisions and plans run in parallel at the highest efforts on
**Astra (Pro/max), Fable/Opus (xhigh), and Argon**; the supervisor synthesizes
the three, it does not average them.

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
- Codex: `codex exec -m gpt-6-luna -C <worktree> --sandbox workspace-write -o out.md - < task.md` (its sandbox cannot write `.git`; the supervisor does git).
- Guard every launch: `cd <worktree> && [ "$(git rev-parse --abbrev-ref HEAD)" = "<branch>" ] && <launch>`; never `git add -A`.

## 6. Changelog

- v1.2 2026-10-16: supervisor may restart apps via the EcosystemControl CLI (operator GO); fleet comes up with WatchF.
- v1.1 2026-10-16: agy headless implementation recipe (globalPermissionGrants), z.ai reset times are UTC.
- v1 2026-10-16: initial, from the operator directive after the roster
  confusion (z.ai GLM CLI and Perplexity's GLM entry are two sources).
