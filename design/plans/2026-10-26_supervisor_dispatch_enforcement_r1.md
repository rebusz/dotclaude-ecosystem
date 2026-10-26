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

3. **Hard enforcement hooks (PreToolUse).**
   - `Agent` matcher, new `hooks/claude_worker_guard.py`.
     - It DENIES spawning a Claude subagent for implementation, review, audit or diagnosis. Detection: the prompt or description matches impl/fix/review/audit/diagnose patterns, or the subagent type is executor or general-purpose with write intent.
     - Allowed only with an operator-created override file `~/.claude/state/allow_claude_workers` that has a TTL. Agents never create it.
     - The deny message returns the exact `lane …` command to use instead.
   - Bash matcher (extends `model_launch_guard.py`).
     - It denies direct model CLI launches (`codex exec`, `glm`, `kimi`, `cursor-agent`, `cdp_*`) that do not go through `dispatch.py lane`.
     - Direct calls stay possible only with `--lane-repair` (for repairing a lane).
   - Main-session read budget (PostToolUse on Read, Grep and Bash, main session only).
     - It counts bytes read per turn. Above 60 KB in one turn it injects "STOP reading: send this to `lane diagnose`".
     - It blocks a single Read over 40 KB unless the path is a review verdict or a receipt.

4. **Lane health and repair loop.**
   - `lane_health.json` is written by the router and by a probe (`lane probe --all`: ChatGPT Chat and Work, Argon, Perplexity, Kimi, GLM, AGY, Cursor, Codex) that runs at SessionStart and every 30 min.
   - A lane DOWN for UI drift or a permission reason, rather than quota, automatically creates a lane-repair job. That job is itself routed through `lane impl` in the WatchF and dispatch repos.
   - Claude starts no repair session on its own; the operator sees one line saying which lane is down, why, and since when.

5. **Free lanes first.** Review defaults to plain ChatGPT Chat GPT-6 Pro, which uses no Codex/Work quota. It goes through `auditgpt.py`, which uses GitHub links or generated packets because the connector needs Work. Then Argon (its own weekly pool), then Perplexity.
   - Astra on Work, which shares the Codex weekly pool, is reserved for R3 final reviews, plans and top decisions.
   - This matches the 2026-10-19 Chat-only runbook in WatchF.

6. **Supervisor turn shape (in the contract).** Each turn: (a) read the receipt or verdict, (b) decide, (c) at most one `lane` call per independent job, (d) a status line to the operator.
   - The supervisor does not read source code to verify a reviewer; it sends the cross-check to a second lane.
   - A status line lists: lanes in use, models, and what is DOWN or QUEUED.

# Hard rules (the contract's 5 lines)

1. Claude writes no code, does no review and does no diagnosis. Claude decides and briefs. Workers are always launched with `lane`.
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

# Operator decisions needed

1. **Strict `Agent` deny with an override file:** Claude subagents are blocked entirely for code, review and diagnosis, and only you can lift that with a TTL file. Alternative: allow Sonnet read-only `Explore`.
2. **Direct model CLI deny:** everything must go through `lane`, except `--lane-repair`.
3. **AGY permission rule:** add `"Bash(python D:/APPS/_shared/dispatch/dispatch.py:*)"` to `permissions.allow`. This one rule then covers every lane.
