---
title: "Supervisor dispatch enforcement: Claude supervises, lanes work, hooks enforce"
risk: R1
status: Active
date: 2026-10-26
owner: operator (dszub)
---

## Status: Active

# Problem

The operator has explained the supervisor model for months (roster refs, memory notes, the injected `model-launch-rules.md`). The same failures still come back every day.

Evidence from 2026-10-26:
- Four implementation rounds of rebusz/Tsignal#2527 and #2529 went to Opus subagents, about 1.1M Claude tokens. Claude tokens are for supervision only.
- Lane failures (AGY permission rule, Cursor pools, GLM/Kimi 5h limits, ChatGPT Work pre-submit drift) were treated as "fall back to Claude" instead of "next external lane, and repair the broken one".
- The no-quota lanes were barely used: plain ChatGPT Chat GPT-6 Pro (outside the Codex/Work pool), Perplexity's model picker (GLM 5.3, Grok, Kimi K3, Sonnet) and Gemini Argon.
- The main session did its own verification reads and log digging instead of sending them to a lane.

Root cause: every rule is TEXT, and Claude makes a fresh choice at each launch. Injected text gets read and then rationalized away ("all lanes are down, so Opus"). The one hook that exists (`hooks/model_launch_guard.py`) guards only Bash launches. Nothing guards the `Agent` tool, which is where the tokens went.

**Design principle: remove the choice. Routing is code, and violations are blocked mechanically, not discouraged.**

# Architecture

```
operator ──> Claude main session (SUPERVISOR: decide, brief, read verdicts)
                 │  only through one command
                 ▼
          lane  <role>  --brief <file> [--repo --ref --pr]      (D:/APPS/_shared/dispatch)
                 │  deterministic roster order + live lane health
                 ▼
  impl:   AGY flash-high → Cursor → GLM → Codex luna            (never Claude)
  review: ChatGPT Chat GPT-6 Pro → Argon CDP → Perplexity(GLM/Grok/K3) → Kimi → Astra(Work, R3 only)
  grill:  Perplexity strongest other-family model → Argon
  plan/top decision: Astra (Work) + Argon
  diagnosis/read-heavy: Argon / ChatGPT Chat / Perplexity with repo links or generated packets
                 │
                 ▼
  receipts + lane_health.json   (quota hit, UI drift, 429 → lane DOWN with reset time)
                 │
                 ▼
  ALL lanes for a role down → job QUEUED + operator alert + lane-repair task.  NEVER Claude.
```

## Components

1. **One instruction file, always loaded.** `~/.claude/refs/supervisor-contract.md`, at most 40 lines: the role table above plus five hard rules. The SessionStart hook (`session_router.py`, on startup, resume, clear and compact) injects it verbatim as additionalContext into every session and every compaction.
   - It replaces the scattered roster, memory and launch-rules text as the source the supervisor reads.
   - Those other documents remain as references and must not contradict it.

2. **`lane` router (extends `dispatch.py`).**
   - Usage: `python D:/APPS/_shared/dispatch/dispatch.py lane <impl|review|grill|plan|diagnose> --brief FILE [--repo R --ref SHA --pr N --worktree PATH --author-family F]`.
   - Reads `lanes.json` for the roster order and `~/.claude/state/lane_health.json` for live state.
   - Chooses the first healthy lane in roster order. Cross-family selection is automatic: `--author-family` excludes the author's family from review.
   - On failure (429/quota, pre-submit or UI drift, early quit, no diff), it marks the lane DOWN with a reason and an expected reset, then moves to the next lane in the same call.
   - Writes a receipt with: lane, model, MODEL-line verification, exit, output path, quota events.
   - Quota hits go to a `quota_events.jsonl` that the supervisor reports to the operator at once.
   - When the chain for a role is exhausted it exits `QUEUED` and writes `~/.claude/state/lane_queue/*.json`. The queue drains automatically when a lane's reset time passes; a scheduled runner retries every 15 min.
   - For implementation lanes it pins the venv python, LF line endings, "do not commit", and "finish all items", and applies a post-check: if the diff is empty or partial, the lane counts as FAILED and the job moves to the next lane.

3. **Three tiers. Claude coordinates, roster models work (operator decision, 2026-10-26).**
   - **Tier 1, main supervisor** (Opus/Fable, this session): decides, writes briefs, reads verdicts, reports. Nothing else.
   - **Tier 2, task coordinator**: a separate session (`start_session`) or a subagent per task, on **Sonnet** (or **Haiku** for pure relay and status), never Opus.
     - It drives the job through `lane`: brief, dispatch, read the receipt, send the result to the next lane (review), relay a short report to Tier 1.
     - The roster models do about 80% of the work: code, tests, reviews, diagnosis.
     - The coordinator's own edits are limited to commits and glue: staging, commit messages, merge-conflict resolution, a ≤20-line fix the lanes failed twice.
     - Its report states its own lines changed vs lane-produced lines.
     - This keeps the supervisor's context clean without burning Claude tokens on work.
   - **Tier 3, roster lanes**: AGY, Cursor, GLM, Codex luna, ChatGPT Chat/Work, Argon, Perplexity, Kimi.

4. **Hard enforcement hooks (PreToolUse).**
   - `Agent` matcher, new `hooks/claude_worker_guard.py`.
     - It DENIES an `Agent` call with no explicit `model`, or with `model` opus/fable.
     - It DENIES a brief that lacks the coordinator contract line: "You are a Tier-2 coordinator: all code, tests, reviews and diagnosis go through `dispatch.py lane`; you only relay, commit and glue."
     - The deny message returns the corrected call.
     - The same rule applies to `start_session`: it needs an explicit `model` sonnet/haiku and a coordinator brief.
   - Coordinator edit cap. PreToolUse on Edit/Write inside Tier-2 contexts (identified by the hook payload's agent or session id; mapping to be verified in S2).
     - Writes to source files (`*.py`, `*.ts`, `*.tsx`) are counted.
     - Above 20 changed lines per task the hook denies, with "dispatch it to `lane impl`".
   - Operator override: a TTL file `~/.claude/state/allow_claude_workers` lifts both rules. Agents never create it.
   - Bash matcher (extends `model_launch_guard.py`).
     - It denies direct model CLI launches (`codex exec`, `glm`, `kimi`, `cursor-agent`, `cdp_*`) that do not go through `dispatch.py lane`.
     - Direct calls stay possible only with `--lane-repair` (for repairing a lane).
   - Main-session read budget (PostToolUse on Read, Grep and Bash, main session only).
     - It counts bytes read per turn. Above 60 KB in one turn it injects "STOP reading: send this to `lane diagnose`".
     - It blocks a single Read over 40 KB unless the path is a review verdict or a receipt.

4a. **Lane registry: every model is a data row, not code (`lanes.json`).**
   - Each lane declares:
     - `id`
     - `family` (gpt, gemini, zai, moonshot, anthropic, local, other), used for the cross-family rule;
     - `roles` (impl, review, grill, plan, diagnose);
     - `cost_class`: `subscription` (ChatGPT Chat/Work, Gemini, Perplexity, GLM z.ai, Kimi, Cursor, Codex, AGY), `free` (OpenRouter `:free` models, OpenCode free models), or `local` (llama.cpp/GGUF on this workstation);
     - `quota_window` (5h/weekly/none);
     - `invoke` adapter (CLI or CDP command template);
     - `probe` (health check);
     - `trust` (`trusted`, or `probation` for a newly tested model);
     - `rth_allowed`.
   - Covered from day one:
     - AGY (impl);
     - Cursor CLI (impl);
     - GLM z.ai CLI (impl, review, grill);
     - Kimi CLI (review, impl);
     - Codex luna (impl, last);
     - ChatGPT Chat GPT-6 Pro (review, diagnose);
     - ChatGPT Work Astra/Sol (plan, R3 review);
     - Gemini Argon CDP (review, grill, diagnose);
     - Perplexity picker models (grill, review);
     - OpenCode (impl/review, model chosen per row);
     - OpenRouter free models (review, diagnose; impl only if trusted).
   - `free` lanes are hard-capped at zero spend.
     - The adapter refuses any OpenRouter model id without the `:free` suffix, and any response that reports a non-zero cost.
     - Free lanes go first in the order wherever their trust allows.
   - `local` lanes (models under test on the RX 9070 XT) run as `rth_allowed: false` by default, because of the no-heavy-compute-during-RTH rule; the operator can flip that per lane.
   - `probation` lanes (any newly added free or local model):
     - get only R0/R1 work, plus shadow reviews whose verdicts are recorded but never gate a merge;
     - are never the sole reviewer of R2/R3.
     - Promotion to `trusted` is an operator decision, based on recorded shadow agreement with trusted reviewers.
   - Adding a model means adding a row and a probe. No supervisor habit is involved.

5. **Lane health and repair loop.**
   - `lane_health.json` is written by the router and by a probe (`lane probe --all`: ChatGPT Chat and Work, Argon, Perplexity, Kimi, GLM, AGY, Cursor, Codex) that runs at SessionStart and every 30 min.
   - A lane DOWN for UI drift or a permission reason, rather than quota, automatically creates a lane-repair job. That job is itself routed through `lane impl` in the WatchF and dispatch repos.
   - Claude starts no repair session on its own; the operator sees one line saying which lane is down, why, and since when.

6. **Free lanes first.** Review defaults to plain ChatGPT Chat GPT-6 Pro, which uses no Codex/Work quota. It goes through `auditgpt.py`, which uses GitHub links or generated packets because the connector needs Work. Then Argon (its own weekly pool), then Perplexity.
   - Astra on Work, which shares the Codex weekly pool, is reserved for R3 final reviews, plans and top decisions.
   - This matches the 2026-10-19 Chat-only runbook in WatchF.

7. **Supervisor turn shape (in the contract).** Each turn: (a) read the receipt or verdict, (b) decide, (c) at most one `lane` call per independent job, (d) a status line to the operator.
   - The supervisor does not read source code to verify a reviewer; it sends the cross-check to a second lane.
   - A status line lists: lanes in use, models, and what is DOWN or QUEUED.

# v2: grill fixes (Gemini 4 Argon, plus a partial Grok 4.7 answer; operator GO 2026-10-26)

1. **Bash bypass.**
   - The Bash PreToolUse hook denies file mutation of guarded paths from Bash (redirects, `sed -i`, `tee`, `cp`/`mv` into source extensions, the hooks dir, `settings*.json`, `~/.claude/state/allow_claude_workers*`, `lane_health.json`, the queue).
   - `--lane-repair` is accepted only when a lane-repair job id exists in the queue for that lane.
   - The override is never a plain file. It is created only by an operator-only command, `lane authorize --interactive`, which requires a real TTY and an exact typed GO, using the Conductor `authorize --interactive` pattern. The command writes an HMAC-signed, TTL-bounded token; the key is in the operator's user DPAPI store, not readable by repo files.
   - A PostToolUse net-diff cap (`git diff --numstat` against the task's BASE_SHA) catches any edits that slipped through.
2. **Read budget.**
   - It is PreToolUse (checked before the read), cumulative per session, and applies to both tiers. Default caps: supervisor 150 KB/session, Tier-2 400 KB/task.
   - Max agent depth is 1: a Tier-2 cannot spawn an Agent or `start_session`.
   - Large Bash output is forced to a file, and only a tail is returned.
3. **Router isolation.**
   - Every impl job records BASE_SHA in its own worktree.
   - Between lane attempts, `git reset --hard BASE_SHA` and `git clean -fd`, in that job's worktree only.
   - Success means the job's `verify_cmd` exit code is 0 and the diff is non-empty. Anything else is FAILED, and the job moves to the next lane.
4. **State integrity.**
   - `lane_health.json`, the queue and the receipts use a file lock plus write-temp and `os.replace`.
   - Lane-repair jobs bypass the impl chain. They run on a dedicated repair path (a direct lane CLI with `--lane-repair` and the job id), so an all-down impl chain cannot deadlock its own repair.
5. **Chunked reads.**
   - In the supervisor session, Read and Grep are denied on source extensions (`*.py`, `*.ts`, `*.tsx`, `*.js`).
   - Allowed: `design/**`, handoffs, memory, receipts, verdicts, logs (tail only).
6. **Main session self-edit.**
   - Edit/Write in the supervisor session is denied on source extensions (fail-closed).
   - Allowed: plans, handoffs, memory and docs.
7. **Hook safety.**
   - A hook that crashes denies the guarded tool, with a message naming the hook file and the error.
   - The operator's `lane authorize --interactive` can disable all dispatch hooks for a TTL, as the emergency-off path.
   - Hook tests replay recorded payloads, including today's Opus spawns and direct `codex exec`, and assert deny/allow.

# Hard rules (the contract's 5 lines)

1. The supervisor writes no code, does no review and does no diagnosis. Claude decides and briefs. Per-task work runs in a Sonnet/Haiku coordinator that sends about 80% of the work to roster lanes through `lane`.
2. Never fall back to Claude. If the chain is exhausted, the job is QUEUED, the operator is alerted and the lane gets repaired.
3. Free lanes before quota lanes: ChatGPT Chat, Argon and Perplexity first; Codex and Astra-on-Work last or for R3 only.
4. Every quota hit or DOWN lane is reported to the operator in the same turn, in one line.
5. Real-money and Combine triggers, restarts during RTH, and permission changes stay operator-only (unchanged).

# Rollout (R1, no live trading path)

- **S1 (router):** `lane` subcommand, `lane_health.json`, receipts, queue, empty or partial-diff post-check. Tests drive real lane adapters against fake CLIs (exit codes, 429 text, early quit) and cover the queue path.
- **S2 (hooks):** `claude_worker_guard.py` on `Agent`; the Bash direct-launch deny; the read-budget hook. Tests replay recorded hook payloads from today's transcript: the Opus spawns must be DENIED and the `lane` calls ALLOWED.
- **S3 (contract and probe):** `supervisor-contract.md`, SessionStart injection (including compact), `lane probe --all` on a schedule, and lane-repair job creation.
- **S4:** retire contradicting text in the memory index and the roster ref, so they point at the contract.

Implementation goes through the lanes themselves (AGY/GLM/Codex). Review is cross-family, on plain ChatGPT Chat or Argon. Self-hosted CI only.

# Operator decisions

1. DECIDED 2026-10-26: per-task coordinators are allowed, on Sonnet or Haiku, never Opus. Roster models do about 80% of the work; the coordinator relays to the supervisor.
2. DECIDED 2026-10-26: every model goes through `lane` only, with a hard deny on direct CLI/CDP launches except `--lane-repair`.
3. OPEN, operator action: add `"Bash(python D:/APPS/_shared/dispatch/dispatch.py:*)"` to `permissions.allow`. This one rule then covers every lane.
