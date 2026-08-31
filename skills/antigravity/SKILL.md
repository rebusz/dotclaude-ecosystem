---
name: antigravity
version: 2.0.0
description: Google Antigravity CLI (agy) integration for Claude Code — local executor with Gemini 3.7 Flash, pinned flags harness, containment refusal, and multi-model outbound dispatch.
triggers:
  - /antigravity
  - /agy
  - ask agy
  - consult antigravity
  - antigravity review
  - antigravity plan
allowed-tools:
  - Bash
  - Read
  - Write
  - Glob
  - Grep
  - AskUserQuestion
---

# Antigravity CLI (`agy`) Skill for Claude Code

This skill defines the integration contract, execution harness, and multi-model dispatch rules for the Google Antigravity CLI (`agy`, Gemini 3.7 Flash).

---

## 1. Authority & Ecosystem Role

1. **`agy` (Gemini 3.7 Flash) is the local executor with full file-edit authority.** There is no edit ban on `agy` or any executor lane.
2. **`agy` executes plans, never designs them.** Plans arrive from Claude Opus/Fable after `/fwf` or `/fwp` audit.
3. **Escalation leaves Antigravity.** `gemini-3.1-pro-*` and `claude-opus-4-6-thinking` are rejected as escalation tiers. Hard work is designated outward via `dispatch.py` to ChatGPT CDP (`chrome_gpt`, Sol extra high) or CoderPX (`chrome_ppl`, Kimi K3 / Sonnet 5 / Terra / Grok 4.6).
4. **Review never runs on Claude quota.** R2/R3 plans route review to ChatGPT CDP hostile review (with CoderPX fallback); the hardest slices get an independent CoderPX review as well.

---

## 2. Pinned Flags & Local Edit Harness

All local file modifications through `agy` MUST pass the exact pinned flags and execute via `dispatch.py --local` or direct invocation matching:

```powershell
agy -p "<packet>" --mode accept-edits --dangerously-skip-permissions `
    --add-dir "<ABSOLUTE worktree path>" --model gemini-3.7-flash-high --effort high
```

### Containment Refusal Gate (Mandatory)
- **Refuse to launch** unless `--add-dir` resolves to an **absolute** path inside a `.claude/worktrees/` directory.
- This gate prevents accidental writes to live operator checkouts (e.g. `D:/APPS/<repo>`).

### Three-Repo Readback (Reports, Never Blocks)
- After every edit execution, capture `git status --porcelain` across **three** surfaces:
  1. Target worktree checkout (`.claude/worktrees/...`)
  2. Main repo checkout (`D:/APPS/<repo>`)
  3. Ecosystem memory repo (`D:/dotclaude/dotclaude-ecosystem`)
- Foreign-repo dirt prints a loud `WARNING` naming each affected path and is recorded verbatim into the run receipt and PR body.

---

## 3. Slice Stamp Contract

Every plan slice emitted in Stage 3 of `/fwf` and `/fwp` carries a machine-readable stamp:

```yaml
### Slice S3 — cctv admission routing
lane: chatgpt_cdp              # local | chatgpt_cdp | coderpx
review: chatgpt_cdp+coderpx    # chatgpt_cdp | chatgpt_cdp+coderpx | standard
reason: concurrency + Conductor lease semantics
files: tsignal/services/cctv_feed_supervisor.py
```

### Evaluation Rules
1. **Honor the stamp:** `lane: local` is executed locally by `agy`.
2. **`agy` may escalate:** `agy` may escalate a `local` slice outward to `chatgpt_cdp` or `coderpx` (e.g. on 2nd consecutive test failure, concurrency/CAS logic, or multi-contract changes), recording the reason in the readback.
3. **`agy` may never de-escalate:** A slice stamped `chatgpt_cdp` or `coderpx` cannot be implemented locally.
4. **Missing / unrecognized stamps fail closed:** On **R2/R3** plans, an unstamped slice is refused by `dispatch.py` and escalated to the plan lane; on **R0/R1** plans, it defaults to `local`.

---

## 4. Multi-Model Dispatch Harness (`dispatch.py`)

Entry point: `D:/APPS/_shared/dispatch/dispatch.py`

```powershell
# Local execution with pinned flags and 3-repo readback
python D:/APPS/_shared/dispatch/dispatch.py <packet.md> --local --worktree "<ABS_WORKTREE_PATH>"

# Outbound dispatch with automated fallback (ChatGPT CDP -> CoderPX -> Operator stop)
python D:/APPS/_shared/dispatch/dispatch.py <packet.md> --dry-run
```

- **One writable file per packet:** Multi-file packets fail validation immediately.
- **Single-flight lock:** Wraps outbound calls in `cdp_role_file_lock` to prevent Chrome profile collision.
- **Receipts:** Run receipts are recorded in `_shared/dispatch/receipts/<task-id>/<timestamp>.json`.
