# Handoff to Codex: dispatch-enforcement workflow (2026-10-27)

Plan (spec, v2): `design/plans/2026-10-26_supervisor_dispatch_enforcement_r1.md`.

## Done

| Item | Where | Notes |
|---|---|---|
| S1 router `lane` | apps-shared#132, `5d30c37` | |
| Worker preamble | apps-shared#133, `cb54f3c` | |
| S3 supervisor contract | dotclaude#140, `8ab9770` | Injected on startup, resume, clear and compact; also `~/.claude/refs/supervisor-contract.md` |
| Contract on router error | dotclaude#143, `48a8712` | |
| S4 rules, roster, memory | dotclaude#142, `27fbedf` | |
| `D:/APPS/_shared` switched to master | `cb54f3c` | See note 1 |
| `TsignalLanePoll` scheduled task | Registered, every 15 min | Log: `~/.claude/state/lane_poll.log` |
| Lane repairs | WatchF #706 (Perplexity picker, `e1684014c`), WatchF #707 (Gemini account pin, `d989f0b8`) | Gemini accounts: `GEMINI_CDP_ACCOUNTS="tsignalx@gmail.com:1,obsidianflowx@gmail.com:2"` |
| Conductor receipts | Under ceiling (214 MB) | Archive in `C:/Users/dszub/.conductor/receipts_archive_20261027` |

Notes:
1. Before switching `_shared` to master, the other session's uncommitted edits were saved as WIP commit `5d3e6ce` on branch `docs/coderpx-perplexity-drift-20260925` and pushed. 9 untracked files that conflicted with master were moved to `D:/APPS/_shared_untracked_backup_20261027`.
2. Codex guard (`~/.claude/hooks/model_launch_guard.py`): `gpt-6.1-terra` is preferred. If the CLI rejects it on a ChatGPT account, use `gpt-6-luna` as the fallback.

## Open (do in order)

1. **S2 hooks, dotclaude#141** (draft, head `970cba2`, 185 guard tests pass).
   - Needs ONE completed cross-family review verdict at the exact head, with no SHIP-BLOCKING findings.
   - Supervisor policy: exotic shell-wrapper bypasses (nested interpreters, `flock -c`, `%COMSPEC%`, `for /f`, stdin interpreters) count as FIX-LATER. Document them in the PR. The hooks are an accident and rationalization barrier, not a sandbox.
   - Still SHIP-BLOCKING: crashes, false denies of normal work, fail-open, and settings or override bypass.
   - Reviewer: Perplexity "Opus 5.5" or GLM after its reset. Split the source into chunks of 800 lines or fewer; Grok timed out on the whole file.
   - Then: ready, CI, merge, fast-forward. Install the hooks into `C:/Users/dszub/.claude/settings.json` using MAIN-checkout paths, after a timestamped backup and a `json.load` validation. Smoke-test a deny case and an allow case per hook (normal Read, Edit and Bash must pass).
2. **WatchF #708** (draft, 210 tests): the Gemini oneshot opens the pinned `/u/N/app` tab. Needs review, then merge.
3. **Gemini /u/2 (obsidianflowx):** the operator must click "Got it" on the privacy notice and select Argon once. The account shows "Upgrade", so it may not have Argon.
4. **ChatGPT CDP lane reports "login required" although the profile is logged in.** This is a detection bug in the lane; file a WatchF fix.

## Lanes now

| Lane | State |
|---|---|
| AGY | Admitted |
| Perplexity Grok 4.7 / Kimi K3 | OK, but slow on large inputs |
| GLM | 5h limit until 16:44 |
| Kimi CLI | Monthly limit |
| Cursor | Limited |
| Argon tsignalx | Quota hit |
| local_llama | Down (server not running) |
