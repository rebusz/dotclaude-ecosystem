# Ecosystem workflow audit: supervisor workflow, model roster, bridges, prompts

**Mode:** AUDIT (compliant / violations / risky-but-acceptable / false positives / P1-P3), plus an ARCHITECT target design
**Date:** 2026-11-05 · **Auditor:** synthesizer (Opus 5.5), read-only · **Risk of this document:** R0

## 0. Header

**Scope.** I covered the instruction layer (core, contract, roster, skills, commands, repo CLAUDE.md and AGENTS.md), the single-door lane router (`dispatch.py lane`), the CDP browser bridges and the CoderPX protocol, and the orchestration and lease layers (Conductor, cdp_lane_lock, program_*). I also covered the master-session lifecycle, hook enforcement and config fan-out, and the landing pipeline (review gate, CI, merge, checkout sync).

| Repo (container path) | Operator path | Container HEAD | Live HEAD (from git_state.txt) |
|---|---|---|---|
| dotclaude-ecosystem | D:/dotclaude/dotclaude-ecosystem | `21a4590` (2026-10-27) | **`298882f`** (#144, 2026-11-05: Conductor CDP 4 slots and 15 min max hold) |
| apps-shared | D:/APPS/_shared | `1111976` (2026-11-04) | **`bfc4294`** (#173, 2026-11-05: router chatgpt 4 slots, 15 min hold, Argon probe 120 s) |
| Tsignal | D:/APPS/Tsignal 5.0 | `3cdb0c2` (2026-11-05) | `2eb2f35b1` (#2650) |
| EcosystemControl | D:/APPS/EcosystemControl | `70674e1` (2026-10-24) | `70674e1` plus a dirty `services_extra.yaml` |
| claude-config | ~/.claude mirror | `e16da40` (2026-11-05, evidence bundle only; settings.json is from 2026-03-26) | n/a |
| ecosystem-context | snapshot | `469b577` (2026-07-18) | n/a |

I read the two live-only commits (#144 and #173) with `git fetch` + `git show`. Findings marked **NEW** take them into account.

**Evidence limits.**
- WatchF was not available: the drivers `coderpx.py`, `cdp_gemini_oneshot.py`, `cdp_chatgpt_code.py`, `auditgpt.py` and `cdp_watchdog.py`, plus the selectors and the DOM tests. TsignalLAB and Obsidian Flow were not available either.
- The live operator state came from a sanitized read-only bundle (`claude-config/design/audits/2026-11-05_live_evidence/`, abbreviated **LIVE/** below). It does not include memory files, the full `lane_receipts`, `session_binding`, GitHub runner inventory or branch-protection details beyond what the API returned (`protected:false`).
- Tests ran on Linux with Python 3.13. Windows-path tests fail for platform reasons, and I do not count those as bugs (see §5).
- `test_lane_router.py::test_timeout_handling` kills the pytest process on POSIX. That is a real POSIX bug, but it does not affect production.
- **Who disabled `TsignalLanePoll` and why is unknown.** `LIVE/scheduled_tasks.tsv:16` shows `Disabled`, last run 27.10 13:42, last_result 0 (a clean last run, so it was not a crash). Nothing in the bundle or the handoffs says who disabled it or whether it was deliberate (for example to stop D-2 resets). I do not treat it as an accident, and re-enabling it is an operator question (Q5) asked before N3.
- **Root cause of today's Perplexity failures is unknown.** The two review receipts (and one diagnose receipt, `QUEUED__job-diagnose-1793894459-159a92`) show `CDPLaneAcquireError` (lock or admission acquisition), not a dead window. The Conductor admission change #144 landed the same morning. Stale Conductor or lane-lock holders could not be inspected.

---

## 1. Executive summary

- **The daily breakage traces to five structural causes. No single model or lane explains it.**
  1. **No single machine-readable policy/state authority.** Routing and roster rules live in **at least 8 places**: contract, roster, `lanes.json`, `MODEL_ROSTER.json`, master-agent SKILL, fwf, the **live-only, unversioned** `~/.claude/refs/model-launch-rules.md`, and memory plus handoffs. They disagree. The always-loaded global kernel sits at **15,987 / 16,000 bytes and 162 / 162 lines**, the fail-closed regrowth ceiling, so any new rule has to land in an unmanaged file.
  2. **Lane state does not tell the truth.** Non-impl lanes that exit non-zero are never marked DOWN. "Exists" probes heal broken lanes. Structured driver errors (`coderpx.result.v1 failure_class=CDPLaneAcquireError`) are reduced to `exit_code_70`. Live: `perplexity_grok` is **UP with 145 consecutive failures**, last OK 11-03.
  3. **Nothing drains the queue.** The poller `TsignalLanePoll` has been **Disabled since 10-27** (by whom and why is unknown): its log stops there and the queue holds 1,645 files. Of the newest 400 receipts, **115 are DONE, 131 FAILED and 154 still QUEUED** (pending, because nothing has drained since 10-27).
  4. **Planning and review depend on a CDP browser fleet whose liveness has no complete owner.** Gemini has no standing hold (EC `coderpx_lane_supervisor.py:30` covers only chrome_ppl and chrome_gpt). `WatchF-CDPFleetSupervisor` has been Disabled since 08-06. The EC holds that do exist recover once and never re-check. In the two review receipts collected today (a small sample; one diagnose receipt shows the same pattern), every CDP attempt failed, for different reasons. Argon failed because the fleet was down (`cdp_fleet_ensure chrome_gemini: failed … timed out`). Perplexity failed with `CDPLaneAcquireError`, an admission or lock acquisition failure whose cause is unknown (possibly a stale Conductor or lane-lock holder; #144 changed Conductor admission that morning). chatgpt exited 1. Two receipts are a small sample. The R3 reviews were QUEUED, and masters fall back to off-door Sonnet reviews.
  5. **The supervisor's working set lives inside the session.** That covers the CI merge chain, background bash, unprocessed lane results and the status board. There is **no server-side merge gate** (Tsignal `main` `protected:false`, GitHub Free private repo). Today's `ci_seq2.sh` is an **untracked file in the shared checkout** `D:/APPS/_shared/dispatch/`.
- **Router state-machine bugs manufacture false failures and data hazards.**
  - A correct Codex diff is marked `submit_unconfirmed` because the custody marker is substring-matched in CLI stderr. **This happened live today**: `p0-custody-tests-1105` ran on `codex_terra`, exited 0 after 416 s, and ended FAILED/held.
  - A queue drain runs `git reset --hard` to a stale `base_sha` before any HEAD or lane check. I reproduced this three times. It is latent only because the poller is off, so **re-enabling the poll as is would arm it** against 1,645 queued jobs.
  - Preflight refusals return FAILED with no reason.
- **Interim operating note, effective now and until N1 lands:** do not run `dispatch.py lane drain` and do not re-enable `TsignalLanePoll`. Use `lane status` only. The 11-03 handoff (`2026-11-03_supervisor_handoff.md:75`) tells successors to "Run `dispatch.py lane drain` … before trusting the queue". Because of D-2, that single command hard-resets every queued impl worktree to its stale base.
- **The enforcement the contract claims does not exist.** The injected contract says "binding, enforced by hooks" and "reading source … blocked". Live, the only PreToolUse hook is a hand-edited `model_launch_guard.py` on `Bash|PowerShell` (with `.bak` copies from 10-27 and 11-03). It reads the unversioned rules file. There is no Read, Edit, Write or Agent guard, and `claude_worker_guard.py` is absent. The S2 PR (dotclaude #141) is still a draft. Router-launched Codex never passes through that guard, and the Codex credit guard (`codex_limit_guard.py`) is called by nothing.
- **The central master-session contradiction.** The contract tells the supervisor not to read source or review. The roster, core.md:79 and the operator's 11-03 rule 5 tell it to verify diffs and tests itself. Masters therefore either break the contract or let results rot. 11-05 left three R3/R2 worktrees "came back but not processed".
- **Cross-family identity is not proven.** The router pre-fills `MODEL_IDENTITY … answered=<requested>; route=requested`, so a Perplexity "Best" downgrade passes the family gate.
- **CI and landing friction is concrete and fixable.**
  - Any PR comment, including a posted review, cancels Draft CI.
  - Concurrent full suites pin themselves to the same 8 masked CPUs (3 runs x `-n 6` = 18 workers), so xdist crashes.
  - Merge evidence misses green runs whose run-level conclusion reads "cancelled", which adds redundant main suites (two of them turned main red).
  - Tracked operator-state YAML blocks checkout sync. Live, 4 `pure_signal_config.yaml.bak_*` files sit in the main checkout.
- **NEW today:** #144 makes Conductor release **ACTIVE** `cdp:chatgpt`/`cdp:perplexity` slots after 900 s **even when the owner is alive**, bypassing its own liveness veto. Adapters are allowed 900 s plus setup, so a fifth job can enter a window that is still answering. The operator's 15-minute release rule (live `model-launch-rules.md` rule 2) is right; the defect is that Conductor releases without ending the owner's work. #173 handles the same rule correctly in the router: it clamps every job to `MAX_JOB_TIMEOUT_S = 900.0`, so work ends within 15 minutes, and keeps its 1,500 s `_LANE_LOCK_HARD_STALE_S` only as a pid-reuse ceiling that does not evict a live holder.
- **Retention is approaching its limits.** Conductor receipts are at 236.5 / 256 MB (REPORT_ONLY). `lane_receipts` holds 783 MB in 31k files. The checkouts hold 747 worktrees and 33 stashes (Tsignal) and 245 / 23 (WatchF). `TsignalGitHygiene` last result was 0x41306 (terminated), and the reaper does not recognize squash merges.
- **What works and should be kept:** the deterministic rules generator, the size guard, the core invariants (care, not access; paper/live parity; gated live trigger; real-path DoD), CDP no-retry custody, the atomic lane state, fail-open merge evidence, CPU masking, the ff-only checkout sync, and live-safety discipline in every handoff.
- **Direction:** fix the router state machine before re-enabling the poll, make lane state and policy one machine-readable source with expiring overrides, make health honest, take landing out of the session, and shrink the prose to a short constitution plus role cards. More rule text will not help, because the kernel is already at its ceiling.
- **Your question "they figure it out, but not always": when is prescriptive text still needed?** Rule of thumb (detail in §6a):
  - (a) Irreversible or safety actions stay **hard gates enforced in code**: the live trigger, custody halts, the cross-family review gate, and never skipping tests.
  - (b) **Measured environment quirks** that no tool encodes yet stay as **short refs with a `Last-verified:` date**, until a tool takes them over. Examples: Windows MSYS path mangling, the `glm.cmd` newline cut, packet size caps.
  - (c) **Everything else is intent plus invariants.** Today the opposite holds: `skills/coderpxC/SKILL.md` has 227 lines, `coderpx/DISPATCHERS.md` 347, and the roster's §5 "binding" cheat-sheet carries a ~2 KB narrative of one OpenCode slice. The good pattern already exists: `Tsignal/.claude/skills/tsignal-*` are 1.2-2.7 KB lazy evidence routers.

---

## 1a. Live state (2026-11-05, LIVE/)

| Fact | Evidence | Reading |
|---|---|---|
| Only PreToolUse hook = `model_launch_guard.py` on `Bash\|PowerShell` (10 s). No Read/Edit/Write/Agent guard. | `LIVE/settings.hooks.json`, `LIVE/hooks/LISTING.txt` (guard 3,052 B, mtime 11-03, plus `.bak-20261027` and `.bak-20261103`) | The contract's enforcement claim is false. The guard is hand-maintained, and no repo or manifest owns it. |
| The guard denies Codex exec unless `-m gpt-6.1-terra\|gpt-6-luna\|gpt-6.1-sol\|gpt-6-astra` is used. It injects `model-launch-rules.md`. | `LIVE/hooks/model_launch_guard.py:28-60` | Router-launched Codex (Popen inside `dispatch.py`) is not seen. The guard covers only hand launches. |
| `model-launch-rules.md` (2,955 B, edited 11-04 22:06): "ChatGPT CDP = 4 parallel slots, Perplexity 4 … released at most 15 min"; "Review packets = GitHub links … never pasted large diffs"; "Never use AGY for … reviews". | `LIVE/refs/model-launch-rules.md` rules 2, 3, 6 | A **binding** rules file that exists in no repo. Rule 6 contradicts the router's inline-excerpt packets (`lane_router.py:1956`, "Inline excerpts (repo not connected)"). |
| `supervisor-contract.md` installed copy is IDENTICAL to the template. `supervisor-model-roster.md` is NOT installed. | `LIVE/refs/DIFF.txt` | The hand copy has precedence over the template (`session_router.py:545-548`), so future template fixes will not reach sessions (E-7). |
| Global kernel 15,987 B / 162 lines. Limit 16,000 / 162. | `LIVE/rendered/RENDERED_HEADS.txt:1`; `sync_agent_rules.py:221-222` | Zero headroom. Rule growth leaks into unmanaged files (R-5). |
| `TsignalLanePoll` Disabled, last run 27.10 13:42. Poll log ends 10-27. | `LIVE/scheduled_tasks.tsv`; `LIVE/state/lane_poll.tail300.log` | Nothing drains or expires the queue. This confirms the "112 stale QUEUED" handoff (11-03:75) was a dead poller, not infinite requeue. |
| `lane_queue` = 1,645 files. Newest 10: 8 `queued` (R3 p0 waiver/custody reviews, CCTV diagnose) and 2 `held` (impl submit_unconfirmed). | `LIVE/state/lane_queue/COUNT.txt`, sample jobs | The queue is a graveyard. `held` jobs have no exit path. |
| Newest 400 receipts: QUEUED 154 / FAILED 131 / DONE 115. 31,305 receipt files, 783 MB. | `LIVE/receipts/STATUS_COUNTS_newest400.json`; `LIVE/conductor/receipt_dir_sizes.txt` | 115/400 DONE, 131 FAILED, and 154 still QUEUED. The QUEUED ones are pending, not failed: nothing has drained since 10-27. Of the 246 jobs that reached a final state, 47% succeeded. No retention. |
| `perplexity_grok` UP, consecutive_failures 145, last_ok 11-03T13:53Z, last_probe 11-05. Also UP: k3 98, glm 97, argon 39, chatgpt_chat_pro 12, perplexity_sonnet 32. | `LIVE/state/lane_health.json` | Health UP ≠ works. Exists-probes heal, and non-zero exits never trip DOWN (D-4). |
| Today's review chains (2 receipts): chatgpt `exit_code_1` (14 s, one receipt only); argon `exit_code_3` "cdp_fleet_ensure chrome_gemini: failed - ipv6:version:<urlopen error timed out>" (both); perplexity_grok/k3/glm `exit_code_70` with `{"schema":"coderpx.result.v1","status":"INTERNAL_ERROR","failure_class":"CDPLaneAcquireError"}` (both). Result: QUEUED. | `LIVE/receipts/QUEUED__job-review-1793894451-9d3973.final.json`, `QUEUED__p0-waiver-review2-1105.final.json` | Two distinct causes. Argon = fleet down. Perplexity = admission or lock acquisition failed, cause unknown. Live rule 2 classes stale holders and 600 s slot waits as lane defects, and #144 changed Conductor admission that morning. The drivers already emit a typed error that the router ignores (C-1, D-4). |
| `p0-custody-tests-1105`: `codex_terra`, exit 0, 416 s, `fallback_used:true` (model_label_used gpt-6-luna) → FAILED `submit_unconfirmed` "SUBMIT_UNCONFIRMED seen". | `LIVE/receipts/FAILED__p0-custody-tests-1105.final.json` | Live recurrence of D-1. The job writes custody tests, which naturally contain the token. |
| Review jobs record `author_family: claude`. | same QUEUED receipt | Claude authored code the same day the contract says "NEVER fall back to Claude" (R-1). |
| 9 lane rows not in `lane_registry` (codex_luna_medium/xhigh, codex_terra_xhigh, codex_sol_xhigh, cursor_auto, perplexity_gemini_flash/gpt_sol/nemotron, **lane_timeout_test**). | `LIVE/state/lane_health.json` vs `lanes.json` ids | Stale rows, and a **unit-test row (`job-timeout-test`) leaked into live state** (D-9). |
| 9 lanes DOWN: cursor x2 / glm / kimi on quota, 3 codex `registry_invalid` (since 10-30), codex_sol_xhigh flaky, local_llama. | `LIVE/state/lane_health.json` | Every non-CDP review lane (kimi_cli, cursor_cli, glm_zai) is DOWN at the same moment the CDP fleet is down, so the review gate cannot be met except by Claude. |
| CDP: ports 9223/9224/9233 have no LISTEN entries at snapshot time. There are many TIME_WAIT entries to 9223, and `cdp/status.txt:10` shows `127.0.0.1:9223 → :25794 TIME_WAIT` with 9223 on the server side, so 9223 (chrome_ppl) was serving shortly before the snapshot. `cdp_lane_lock` all roles unlocked. `WatchF-CDPFleetSupervisor` Disabled since 06.08. WatchF backend logs repeated `chrome_x: failed - check_exception: unsupported role` after WatchF #736. | `LIVE/cdp/status.txt`; `LIVE/scheduled_tasks.tsv`; `LIVE/cdp/watchf_watchdog_log.tail200.txt` | The Gemini window was down (Argon receipts). Perplexity's window was up recently, so its `CDPLaneAcquireError` is not explained by "fleet down". No component owns liveness for all three roles (C-1). |
| Conductor: receipts 53,598 files, 236.5 MB of 256 MB ceiling, retention REPORT_ONLY. DB 397 MB. 221 historical RECOVERY_REQUIRED transitions, 0 current. `leader_active:false`. Stray 0-byte `~/.claude/state/conductor.db`. | `LIVE/conductor/status.txt`, `recovery_required.txt` | 92% of ceiling within days. Recovery is not currently wedged. |
| Worktrees/stashes: Tsignal 747/33, WatchF 245/23, _shared 141/1, dotclaude 50/2, EC 8/1. `_shared` has untracked `dispatch/ci_seq2.sh`, `NUL`, `dispatch/pr2648.patch`. Tsignal has 4 `pure_signal_config.yaml.bak_*`. WatchF has 4 `.env.bak_*`. | `LIVE/git_state.txt` | The merge chain moved from the scratchpad to an untracked file in a shared checkout. Operator-state workaround debris (L-5). |
| `TsignalGitHygiene` last_result 267014 (0x41306, task terminated). | `LIVE/scheduled_tasks.tsv` | The reaper does not finish. It is also squash-blind (L-9). |
| 19 bash/python processes match the orphan regex, including 2 scripts running from `AppData/Local/Temp/claude/…` session dirs since 09:25. | `LIVE/processes.tsv` | This fits session-scoped chains (M-1). Whether they are orphans is unproven. |

**Corrections from the live data:**
- (a) "dotclaude main has no commits since 10-27" is stale. #144 landed 11-05, and my container lagged.
- (b) `claude-config/settings.json` `hooks:{}` is not evidence of the live state. Live has 11 hook entries.
- (c) Collector false positives: the "MISSING" Tsignal project hooks (an artifact of the space in the path) and the PreToolUse "(none)" entry (args-style command). Both have been discounted.

---

## 2. Incident taxonomy (ranked by operator time lost)

| # | Class | Frequency / evidence | Root cause | Status | Structural fix |
|---|---|---|---|---|---|
| 1 | CDP lanes down or drifting (picker, composer, chip, login, consent, fleet not up, admission) | 15 handoff dates 10-06..11-05. About 20 WatchF repair PRs after 10-17 (INC-1). Today every CDP attempt in 2 collected review receipts failed: Argon fleet down, Perplexity `CDPLaneAcquireError` (LIVE). | Consumer UI scraping on the critical path. No owner for fleet liveness (supervisor task Disabled). Probes check file existence only. | Open; repeated fix/regress cycle | Fleet ownership in EC for all 3 roles (C-1). Canary that heals only what it tested (C-7). Typed driver errors honored (D-4). One non-scrape reviewer per gate (C-1/Q3). |
| 2 | Lane state lies; queue never drains | Poll Disabled since 10-27. 1,645 queue files. 154/400 QUEUED. Lanes UP with 97-145 failures (LIVE). 11-03:75 "112 QUEUED … never drained". | No TTL, owner or reaper. Poll budget 300 s < adapter 900 s. Non-impl failures never DOWN. Exists-probe heals. | Open | D-2/D-3/D-4 router pack, then re-enable the poll with a heartbeat surfaced at SessionStart. |
| 3 | CI contention and session-scoped landing | 18 handoff dates. xdist INTERNALERROR (11-04:35). Orphan chains "merged on their own" (11-05:52). `ci_seq2.sh` copied between sessions. | Per-ref concurrency on one host with a shared CPU mask. Merge chain lives in the session. No server-side gate. | Hosted route #2653 pending | One full-suite runner label (L-2), a landing queue service (M-1/L-1), SHA-bound review status (L-1). |
| 4 | Rule churn and contradictions | About 10 Codex/Claude reversals 10-07..11-03 (INC-5). 8 authorities (R-1). Kernel at ceiling (R-5). | Operator decisions land in whatever medium the session owns. No expiry or supersedes relation. | Open | `lanes.json` policy plus `operator_overrides[]` with `expires_at`, generated prose, drift lint (R-1/R-2). |
| 5 | False or terminal SUBMIT_UNCONFIRMED | 16 handoffs since 10-02. Live `p0-custody-tests-1105`. Argon 180 s timeout (#160). | Substring custody check over CLI stderr. Timeouts below latency. No collect verb. | Partly fixed (#160) | Scope markers to `transport:"cdp"` rows (D-1). Submit/collect split (C-3). |
| 6 | Results not processed; state lost at handoff | 7 handoffs. 11-05: 3 R3/R2 worktrees unprocessed. 10-24: 96 dirty files. | No `consumed` state. Results are dirty files in remembered worktrees. | Open | `lane ack`/`inbox`, router WIP-commit on the lane branch, a generated handoff state block (M-2/M-4). |
| 7 | Quota discovered by failing | 26 handoff files, 19 dates. Manual AGY rotation (10-24:78). | Quota is modelled only as DOWN after a 429. | Open | Burn and reset view in `lane status`, soonest-reset preference, one consolidated status line (M-8). |
| 8 | Review loops that do not converge | #2493 12 rounds, #2362 16, 11-05 4-5 rounds (INC-9). | No findings ledger or delta SHA. The lane door dropped `MAX_ROUNDS_PER_SLICE=5` (`dispatch.py:54-56` vs lane_router). | Open | Findings ledger in the review preamble, plus a round counter returning `needs_plan` (C-8). |
| 9 | Silent preflight refusals | 11-03 morning:77, 11-04:38, 11-05:136. | Early-return receipts carry no `reason`. | Open | Reason codes plus stderr (D-5). |
| 10 | Windows shell pitfalls relearned | `/ci full` mangled by MSYS on 3 PRs (11-03:37-39). Self-killing kill regex (11-05:53). `glm.cmd` newline cut. | Lessons go into prose, not tools. LESSONS_LEARNED has no entry after 10-04. | Open | Encode them in tools: draft-ci "unrecognized command" reply, merge-chain `--takeover` by pidfile (L-10). |

---

## 3. Findings by area

Format: **ID · Severity · kind · R-class · effort · verifier status** (CONFIRMED / PARTIAL / LIVE = confirmed by the live bundle / UNVERIFIED-P3). The source finding ids from the dimension audits are given in brackets.

### 3.1 Prompts and rules (the instruction layer every model reads)

**R-1 · P1 · contradiction · R1 · M · CONFIRMED+LIVE: eight competing "binding" routing and roster authorities** [PROMPT-1, DISP-7, SUP-4, INC-5, HOOK-9, LAND-5]
- Evidence:
  - `templates/supervisor-contract.md:10-13` gives impl "AGY → Cursor → GLM → Kimi → Codex terra", and L19 says "NEVER fall back to Claude".
  - `agent-rules/refs/supervisor-model-roster.md:28` says "never Astra/Sol on Codex" and L40 "Codex: not used at all".
  - The `lanes.json` `codex_astra_high` notes say the "operator 2026-11-03 lifted the Sol/Astra-on-Codex ban" (this is the only versioned trace).
  - `lane_router.py:1189-1190` rejects anthropic for impl/review, while handoff 11-05:124 records "Claude Sonnet subagents as cross-family reviewers (operator rule 10-30)", and that rule is in no repo.
  - `skills/master-agent/SKILL.md:55` calls itself "the authoritative router". `core.md:28` and `:77` point to two different authorities.
  - `models/MODEL_ROSTER.json` `fixed_review_slots[0]='gpt-5.6-sol'`, and WatchF reads it via `watchf_source.py:39,90-93`.
  - `Tsignal/CLAUDE.md:11` (managed from `repos/tsignal-5.0/shared.md:5`) calls the **roster** "binding, newest version", while roster §0 says "the contract wins".
  - **LIVE:** an eighth, unversioned source exists: `~/.claude/refs/model-launch-rules.md`, injected by the guard. It conflicts with the repo text in two more places:
    - Rule 8 says "never write code on Haiku", while `supervisor-contract.md:4` lets a Tier-2 coordinator on "Sonnet or Haiku" "edit at most 20 source lines".
    - Rule 10 says "No heavy local tests during RTH", while `Tsignal/.github/workflows/ci.yml:200` says "CI runs during RTH on the trading workstation" (operator 2026-08-14), and the 11-03 binding rule 5 says "Run the broad local suite (-n 6) before gh pr ready".
  - `skills/executor/SKILL.md:4-6,28` launches a Claude Agent subagent to "implement code, run tests, commit" for approved R2/R3 work, against contract hard rule 2 ("NEVER fall back to Claude").
- Why it matters: every master starts by arbitrating contradictions. Different sessions on the same day apply opposite rules. Anthropic's memory docs warn that "if two instructions contradict each other, Claude may pick one arbitrarily".
- Fix:
  - (1) Now (R0): fix the `shared.md:5` pointer and re-sync.
  - (2) Make `lanes.json` `lane_registry` the only routing truth. Add `policy{}` (family rules, Claude-fallback condition) and `operator_overrides[]` (id, date, verbatim quote, source, expires_at, supersedes).
  - (3) Generate the contract's routing lines and the roster table from it (`lane roster --markdown`), plus a drift test.
  - (4) Generate `MODEL_ROSTER.json` from the registry, or add a cross-check test. Do not just mark it historical, because WatchF reads it.
  - (5) Move `model-launch-rules.md` into `agent-rules/refs/` so it becomes generated or managed. Its rule 2 (CDP 4 slots, 15-min release) is already a lane rule and should be ratified into the repo as is.
  - (6) Make `skills/executor` dispatch through `dispatch.py lane`, or mark it as allowed only under a declared Claude fallback. Align contract line 4 with rule 8 (Haiku relays only and never edits).
  - (7) The operator ratifies 10-30 and 11-03 verbatim and rules on RTH rule 10 against the CI design and the verify duties (Q1). The 11-04 "no self-imposed entry lockouts" memory is a trading-decision rule (R3, live-decision policy). It belongs to the operator's live-config process, not to this routing registry.

**R-2 · P1 · stale · R1 · M · CONFIRMED: volatile quota and ban state hard-coded into binding prose, "overriding every table row" after it expired** [PROMPT-5, DISP-6, HOOK-9]
- Evidence:
  - `supervisor-model-roster.md:38-47` holds the 10-19 facts block ("GLM resets 2026-10-25", "Cursor monthly used up") and L47 "Precedence: this block overrides every table row".
  - The roster has 35 ISO dates and 47 quota/reset mentions in 137 lines.
  - The 11-03 handoff patches false Argon quota in prose ("memory 10-30: clear lane_health before believing it").
  - **LIVE:** the real availability is in `lane_health.json` (9 DOWN rows) and in `model-launch-rules.md` (slot counts).
- Why it matters: models either obey stale bans or learn to ignore binding text, and the second habit generalizes to the safety rules.
- Fix: delete the facts block and its Precedence paragraph now (R0). Put availability only in lane state plus `operator_overrides` with expiry. Have `session_router` inject a ≤800 B "lanes now" line, with probe age and UNKNOWN for stale entries. Add a lint that **warns** on `until <past date>` / `resets <past date>` in `agent-rules/` and `templates/`, with the changelog exempt.

**R-3 · P1 · contradiction · R0 · S · CONFIRMED: the supervisor is forbidden to read source but is required to verify diffs and tests** [PROMPT-3, HOOK-7]
- Evidence:
  - `supervisor-contract.md:18` says the supervisor "does no review and no diagnosis". L24 says it "does not read source code to verify a reviewer … blocked … by hooks".
  - `roster:104-106` says "verify the diff and the test run itself (never trust a narrative)". `roster:45` says "verify each [Argon claim] against the code".
  - The 11-03 binding rule 5 says "Reviewer SHIP is not test evidence. Run the broad local suite".
  - `core.md:79` (always loaded) says "Review the actual diff (Claude /code-review…)".
  - On the S2 branch, `dispatch_read_guard.py` denies supervisor `.py` reads globally, and `is_tier2()` defaults to False, so every unmarked session would be treated as the supervisor.
- Why it matters: an obedient supervisor cannot catch a false BLOCK or a fake "tests pass", so results pile up (11-05:76-101). A verifying supervisor breaks the contract and then rationalizes other breaches.
- Fix: restate the rule as authorship versus verification. The supervisor never AUTHORS source and does no bulk review. It MAY read diffs, receipts and test output, within a read budget (telemetry, not a deny), and it MUST run the lane's `verify_cmd` before commit or ready. **During RTH that duty is limited to targeted tests of the touched area**, because live rule 10 forbids heavy local tests then. The broad `-n 6` suite of the 11-03 rule 5 runs outside RTH or in CI, pending the operator's ruling (Q1). Reconcile core.md:79 with the same wording. Drop the S2 read ban (Q2).
- Turn DoD for the supervisor role card:
  - (1) Returned lane output is processed this turn: read the receipt, `git diff --stat`, run targeted verify, then commit, re-dispatch or `lane ack abandoned`.
  - (2) Queue duty: report `held`, `expired` and DONE-unacked jobs from `lane status` every turn, and never run `lane drain` by hand before N1.
  - (3) A review verdict counts only if it carries MODEL + `identity_evidence` + SHIP | SHIP-WITH-FIXES | BLOCK + `file:line` for every blocker. Anything else is re-requested, not acted on (see C-8).

**R-4 · P2 · gap · R0/R1 · M · CONFIRMED: one role-blind constitution plus the supervisor contract is injected into worker runtimes** [PROMPT-4, HOOK-3]
- Evidence:
  - `sync_agent_rules.py:210-243` renders the same `core.md` into the Claude, Codex, Cline and Gemini files. `core.md:29,59-60` tells "you" to land and merge, while the `lane_router.py:1990-1998` impl preamble says "Do NOT commit".
  - `session_router.py:563-569,616-617` always prepends the contract, and `codex_session_adapter.py:60-66` forwards it. I reproduced this: a Codex SessionStart gets "# Supervisor contract (binding, enforced by hooks)", 2.5 KB.
  - **LIVE:** `~/.codex/AGENTS.md` is 29,150 B and `GEMINI.md` 19,079 B, so workers pay for supervisor text.
- Fix: split into a constitution (invariants for every role, with the safety invariants kept verbatim) plus role cards of ≤1.5 KB each (supervisor, coordinator, worker, reviewer). Inject by `owner_runtime` plus a dispatch-set lane marker, and log which variant was injected.

**R-5 · P2 · fragility · R0 · S · NEW/LIVE: the always-loaded kernel is at its fail-closed size ceiling, so new rules escape into unmanaged files**
- Evidence: **LIVE** `RENDERED_HEADS.txt:1` shows `~/.claude/CLAUDE.md bytes=15987 lines=162`, against `sync_agent_rules.py:221-222` `line_limit=162, byte_limit=16000`. The newest binding rules (11-03 Codex lift, 11-04 4-slot / 15 min, 10-30 Sonnet) all live outside the managed blocks: `model-launch-rules.md`, `lanes.json` notes, memory, handoffs. The on-demand prose is also large: `skills/coderpxC/SKILL.md` 227 lines, `coderpx/DISPATCHERS.md` 347, roster 137 lines with a ~2 KB single-slice OpenCode bullet in the §5 "binding" cheat-sheet.
- Why it matters: the size guard is good, but with zero headroom the cheapest route for every new rule bypasses it.
- Fix: move the Conductor mechanics (`core.md:32-55`, about 1.8 KB) and the landing protocol copies into skills or `--help`. Interim target (X5): **global kernel** (the rendered `~/.claude/CLAUDE.md` = constitution + Claude overlay) ≤12 KB, i.e. ≥25% headroom under the 16,000 B guard. End-state budget: see §6a. Treat overflow as the signal to move procedure into tools, not as a reason to add files. Feedback loop: run `/doctor prompt-audit` on every rules PR, and measure the cut skills with the skill-creator benchmark before and after (trigger accuracy and task success), so slimming is proven, not assumed.

**R-6 · P2 · stale · R0 · S · CONFIRMED: stale instruction files still loaded or served** [PROMPT-9, PROMPT-10, HOOK-5, SUP-14, INC-13, CDP-10 (docs part)]
- Evidence:
  - `claude-config/CLAUDE.md` holds a 2026-03-20 status and says "No LLM access to broker API or order path". Its ownership disclaimer is an HTML comment, which is dropped on load, so this session received the March text.
  - `Tsignal/.clinerules:64` keeps the retired FB-04 rule and is not a sync target.
  - `Tsignal/AGENTS.md:142-147` says CI is self-hosted only.
  - `.claude/refs/current-state.md` is dated 2026-04-21 and still listed under Load On Demand.
  - Both `fwf.md` copies pin "GPT-5.6 Sol / gemini-3.7 / Grok 4.6". `codex-global.md:27` pins GPT-5.6 Sol.
  - The Tsignal master-agent SKILL says "GENERATED from claude-config/skills", but that directory does not exist.
  - `ecosystem-context/_meta/last_synced.json` is from 2026-07-18.
  - `cdp_fleet/README.md:80-82` uses `host:heavy` and "Perplexity Max", against `coderpx/README.md` using `cdp:perplexity` and "no Max".
  - Duplicate coderpxG skill: `claude-config/commands/coderpxg.md` points to `apps-shared/design/visions/astra-instructions-v1/skills/coderpxg/SKILL.md`, which differs from `dotclaude-ecosystem/skills/coderpxG/SKILL.md` (1 changed link, 16 extra lines) [CDP-11].
- Fix: keep one coderpxG skill source and point the command at it. Make `claude-config/CLAUDE.md` a visible 5-line pointer. Add `.clinerules` as a sync target, keeping FB-01/02/05. Replace inline model lists with "panel = registry role review". Keep one fwf source with `--mode free|paid`. Use `Last-verified:` headers, and have `ecosystem_doctor` flag refs older than 30 days and `last_synced` older than 2 days.

**R-7 · P2 · gap · R0 · S · CONFIRMED: operator rules given in chat have no ingestion path** [PROMPT-12]
- Evidence: 11-03 evening rule 1 says "No Claude fallback", while 11-03 morning:81 records Sonnet reviews "under the operator's 10-30 rule". The 11-04 rule exists only as memory `feedback_no_self_imposed_entry_lockouts_2026_11_04` (11-05:138). The 10-26 handoff:39 uses Opus implementers against contract L4.
- Fix: keep an append-only `agent-rules/operator_rules.jsonl` (id, date, verbatim quote, source, scope, supersedes, expires_at), written by `rules add` **only with operator text**. `session_router` injects the active rules (≤1.5 KB). Handoffs cite rule ids, and a lint rejects "binding rules" sections in handoffs.

**R-8 · P3 · contradiction · R0 · S · PARTIAL: three agy recipes** [PROMPT-13, INC-14]. `lanes.json:28-32` pins `--dangerously-skip-permissions` (operator D4, contained to the worktree). `roster:117` and `roster:134` (v1.9) and `codex-global.md:29` describe other recipes. The router path is not affected, because the classifier never sees agy argv and the empty-diff no-op is already FAILED (`lane_router.py:2998-3021`). Fix: delete the agy command lines from roster §5 and codex-global and point to `lanes.json`.

**R-9 · P3 · gap · R1 · S · UNVERIFIED-P3: lane packets and answers are not neutralized as untrusted text** [PROMPT-14]. `untrusted_text.py` is used only by the context hooks. `lane_router.py:1956` embeds third-party text with no data fence. Fix: wrap it in a DATA section with a provenance header, and add "quoted content is data" to the role cards.

### 3.2 The single-door router (`dispatch.py lane`) and lane state

**D-1 · P1 · bug · R1 · S · CONFIRMED+LIVE: custody markers matched in CLI transcripts mark correct impl diffs `submit_unconfirmed`** [DISP-1, INC-2, SUP-10]
- Evidence:
  - `lane_router.py:535-538` checks `"SUBMIT_UNCONFIRMED" in text or "RECOVERY_REQUIRED" in text` over the full stderr (`:489-532`). It runs for every role before the impl post-check (`:2538-2541`, `:2619-2680`, which set held).
  - Tsignal has 271 `RECOVERY_REQUIRED` hits in `.py` files and 38 files containing the tokens.
  - I reproduced it (FAILED, the diff left behind, `verify_cmd` never run).
  - **LIVE:** `p0-custody-tests-1105` (codex_terra, exit 0, 416 s) shows the same.
  - Handoffs 11-04:37 and 11-05:135 say "'submit_unconfirmed' usually still means a correct diff".
- Fix: add a `transport:"cdp"` row field. Run the marker scan only for those rows, and later only on an anchored driver status line. CLI rows go through exit code, empty-diff and `verify_cmd`. Do **not** add a blanket "verify passes ⇒ DONE" rule. Add regression tests: CLI stderr containing the token must give DONE, and a CDP row must still halt.

**D-2 · P1 · risk · R2 · S(guard)/M(owned worktrees) · CONFIRMED (3 repros): queue re-run hard-resets the worktree to a stale `base_sha` before any HEAD or lane check** [DISP-2, ORCH-1, SUP-2]
- Evidence:
  - `lane_router.py:2165-2168` calls `_reset_worktree_to_base` (`git reset --hard` + `git clean -fd`, `:717-731`) before the dirty check (`:2170`) and before lane selection.
  - `drain_queue` (`:3305`) passes the default `allow_reset=True`.
  - In the repro the supervisor commit was gone while the lane was still DOWN.
  - Handoff 11-05:133 tells masters to "make a WIP commit first", into exactly those worktrees.
  - `resume_job` (`:3423-3501`) already has the right guard (`stale_base`, `dirty_worktree`, `allow_reset=False`).
  - **LIVE:** latent only because `TsignalLanePoll` is Disabled, and 1,645 queue files are waiting.
- Fix (must land **before** the poll is re-enabled): factor resume's guard into a helper and call it from drain. Allow a reset only when HEAD == base, or base..HEAD contains only hook auto-backup commits (`_only_hook_autobackup_commits`), **and** the dirt equals the job's own saved attempt diff. Otherwise mark the job `held` with `stale_base` and print the saved diff path. Check availability before touching the tree. Later (R2 plan): router-owned per-job worktrees.

**D-3 · P1 · bug · R1/R2 · M · CONFIRMED+LIVE: the queue has no TTL, cap, owner or reaper; drains strand jobs as `running`; `held` is invisible; nothing drains** [DISP-4, ORCH-2, INC-6, missed: status lists only queued]
- Evidence:
  - `lane_router.py:3196-3220`: any non-DONE outcome is QUEUED again +15 min with no cap. I reproduced attempts climbing 2→3→4.
  - `:3277-3295`: drain marks every due job `running` and then runs them serially.
  - `lane_poll_scheduled.ps1:33` sets `$CommandTimeoutMs = 300000` and then runs `taskkill /F /T`, against `timeout_s` 900 for every lane.
  - Only `:3294` and `:3504` ever set `running`, and nothing resets it. `resume_job` refuses non-queued jobs (`:3392-3399`).
  - `lane status` lists only `status=="queued"` (`:3700`) and prints "ALL LANES UP" otherwise.
  - **LIVE:** the poll has been Disabled since 10-27, the queue has 1,645 files, and 154/400 receipts are QUEUED.
- Fix:
  - (a) QUEUE only on retryable classes (quota, ui_drift, permission, busy, timeout, throttled). Anything else is FAILED `all_attempts_failed`.
  - (b) `max_requeues` (2) plus a TTL (24 h, or a base-branch move), leading to `expired` with a receipt.
  - (c) Drain claims one job at a time with a lease {pid, create_time, deadline}, using `_is_pid_alive`. Dead or expired leases are re-queued.
  - (d) Dedupe on (role, brief sha256, ref).
  - (e) `lane status` shows running, held and expired counts with ages, plus the last-drain heartbeat.
  - (f) Add `lane expire|cancel` verbs.
  - (g) Raise the poll budget above the adapter timeout plus margin, or drain detached.

**D-4 · P1 · bug · R1 · S · CONFIRMED+LIVE (upgraded from P2): health does not tell the truth: non-zero exits never trip DOWN, "exists" probes heal any DOWN, and typed driver errors are discarded** [DISP-5, CDP-2, CDP-3 (heal part), ORCH-6, missed items]
- Evidence:
  - `lane_router.py:2720-2737`: a non-impl non-zero exit only calls `record_failure()`, and `consecutive_failures` is never read. The 2-strike `flaky` rule (`:2739-2748`) covers only short exit-0 answers.
  - `lane_state.py:355-383`: `record_probe(ok=True)` clears every reason except quota, spend_guard and registry_invalid.
  - 18 of 20 probes are `exists`. I reproduced `ui_drift` being cleared to UP.
  - `classify_failure` returns `failed` for model_picker_not_found, `required_pre_submit_failed` (the pattern is the hyphenated `pre-submit`), send_control_disabled, CDPSubmitError, credit wall, login and CDPResponseTimeout.
  - **LIVE:** `perplexity_grok` is UP with cf=145 and last_ok 11-03. Perplexity returns `coderpx.result.v1 failure_class=CDPLaneAcquireError` and the router records `exit_code_70`.
- Fix:
  - (1) A non-zero non-impl failure counts toward `flaky` (N=2), with exponential backoff (30 min · 2^(cf-1), cap 8 h).
  - (2) Probe strength: an `exists` probe may clear only `probe_failed` / `binary_missing`. Only a functional probe or a real job success clears ui_drift, permission or flaky.
  - (3) Parse the trailing `coderpx.result.v1` JSON and map `failure_class`, falling back to regex, with a parametrized fixture of real driver strings.
  - (4) A role-level breaker keyed on a new `cdp_role` field.
  - (5) Prune or quarantine health rows not in the registry.

**D-5 · P1 · bug · R1 · S · CONFIRMED: preflight refusals return FAILED with no reason ("dies silently")** [DISP-3, ORCH-5, SUP-9, INC-8, PROMPT-8, CDP-11]
- Evidence: `lane_router.py:2089-2290`: worktree missing, invalid, not toplevel or dirty, brief missing or unreadable, and registry error all return with `attempts:[]` and no `reason`. `_clean_git_status` (`:182-186`) exempts only `.pytest-lane-temp`, so a brief inside the worktree refuses itself. Three handoffs record this (11-03m:77, 11-04:38, 11-05:136). `resume_job` already uses reason codes (`:3426-3500`).
- Fix: reuse resume's vocabulary and add `brief_missing` / `brief_unreadable` / `brief_inside_worktree`, with `reason_detail` (path, or the first 10 porcelain entries) and one stderr line. Keep exit 4 (do not invent exit 5 without updating the contract and `codex_job_bridge.py`). No `--allow-dirty`, no auto-stash. Add one test per branch.

**D-6 · P2 · gap · R1 · S · CONFIRMED: routing safety defaults fail open: `--risk` defaults to R1 and `--author-family` is optional** [DISP-9]
- Evidence: `lane_router.py:3583-3589` and `:2051` `job.get("risk","R1")`. Cross-family exclusion applies only when `excluded_families` is non-empty (`:1326-1330`). Review order 1 is `chatgpt_chat_pro` (gpt), and the codex impl lanes are gpt too. **LIVE:** receipts show `risk: None`.
- Fix: require `--risk` for impl, review and grill (or default to R3). Add `--from-job <impl job>` to derive the author family. Refuse R2/R3 review or grill with no author family. Write the family into impl receipts.

**D-7 · P2 · gap · R1 · S · CONFIRMED: no hold, release, clear or ack verbs; spend_guard DOWN is permanent; regex quota gives a 24 h DOWN** [DISP-6, ORCH-6]
- Evidence: the usage at `lane_router.py:3571` lists `role|probe|status|drain|repair|authorize|resume`. `clear_spend_guard` (`lane_state.py:332`) has no caller. A bare `\bquota\b` gives a 24 h weekly window (`:338-339`). 11-03:72 says "clear lane_health before believing it".
- Fix: `lane hold|release` (an operator_hold is releasable only through the operator path, `lane_authorize --interactive`). `lane clear <lane> --reason` writes an audited event. Regex-only quota gets a provisional 30-60 min window. Record holds in `quota_events.jsonl`.

**D-8 · P2 · fragility · R1 · S · CONFIRMED: the lane door imports the 5.4k-line legacy `dispatch.py` and `MODEL_ROSTER.json` at module load** [DISP-10]
- Evidence: `dispatch.py:31-39` runs `load_configuration` and `select_watchf_source` at import. I reproduced it: `WATCHF_ROOT=relative dispatch.py lane status` gives a traceback. A disabled stale catalog entry raises `RosterReadError`. `lane_router.py:1426-1428` silently swaps in `sys.executable` when the WatchF venv is missing.
- Fix: give the router its own entry point, or use lazy imports. Move the agy flags into registry rows. A missing venv becomes a probe failure.

**D-9 · P2 · gap · R1 · S · CONFIRMED+LIVE: the router suite is red on main, not in CI, kills itself on POSIX, and leaks into live state** [DISP missed, DISP-12, ORCH-4, CDP missed]
- Evidence:
  - `tests/test_lane_router_hazards.py::test_targeted_resume_fails_closed_without_reset_on_fallback_or_head_change` fails deterministically. The mock predates #156's `--porcelain -z --untracked-files=normal`.
  - `test_timeout_handling` hits `os.killpg(getpgid(child))` on a child without `start_new_session` (`:1121-1124`, `:1516-1524`) and gets rc=137.
  - `hybrid-ci.yml:113` runs only `ci/test_hybrid_router.py`.
  - The router had 14 fix commits since 10-15.
  - **LIVE:** a `lane_timeout_test` row with `last_job_id: job-timeout-test` sits in the operator's `lane_health.json`, so a test ran against the real state dir.
- Fix: fix the mock. Use `start_new_session=True` on POSIX (keep taskkill on Windows). Add a pytest autouse fixture that forces `LANE_STATE_DIR` to `tmp_path` and fails if `~/.claude/state` is touched. Run `dispatch/test_lane_*.py` and `tests/test_lane_router_hazards.py` as a required check on `dispatch/**`, sharded to stay inside memory.

**D-10 · P2 · overengineering · R1 · L · PARTIAL: `run_job` is a 1,235-line function with 27 inline attempt dicts and id-substring special cases** [DISP-11]. The measurements are accurate (`:2030-3264`; `"chatgpt" in lane_id` at `:2316,:2620` lets `astra_work`/`sol_work` skip the slot check; impl order ties at 42). Do it in this order: Receipt/Attempt builders that require `reason` (fixes D-5 everywhere), row flags `transport` / `slot_pool` / `cdp_role` (fixes D-1 and C-4), reject duplicate `order` values, and only then split into phases.

### 3.3 CDP bridges and the CoderPX protocol

**C-1 · P1 · fragility · R1 (EC/WatchF) / R2 (API lanes) · M · CONFIRMED+LIVE: planning and review depend on a CDP fleet whose liveness has no complete owner: Gemini has no standing hold, WatchF-CDPFleetSupervisor is Disabled since 08-06, and the EC holds recover once and never re-check** [INC-1, CDP-6, CDP-8]
- Evidence:
  - All 3 plan lanes, 5 of 6 grill lanes and 6 of 11 review lanes are CDP (`lanes.json`).
  - `EcosystemControl/scripts/coderpx_lane_supervisor.py:30` has `SUPPORTED_ROLES=("chrome_ppl","chrome_gpt")`. The supervisor loop only sleeps after one recover, and health is a port-only `/json/version` check.
  - `services_extra.yaml:828-836` documents the DORMANT-stop self-destruct pattern that was fixed for chrome_gpt only.
  - **LIVE:** `WatchF-CDPFleetSupervisor` has been Disabled since 06.08. No LISTEN on 9223/9224/9233. Argon failed with `cdp_fleet_ensure chrome_gemini: failed … timed out`. WatchF logs `chrome_x: unsupported role` after #736.
  - Every non-CDP review lane (kimi, cursor, glm) was DOWN on quota at the same time, so the gate could only be met by Claude.
  - The two collected review receipts show **two different causes**, not one "fleet down". Argon failed on `cdp_fleet_ensure chrome_gemini … timed out` (fleet down). Perplexity failed with `CDPLaneAcquireError` (admission or lock acquisition, cause unknown) while `cdp/status.txt:10` shows 9223 serving shortly before the snapshot. That one fits live rule 2's "stale holder or 600 s slot-lock wait is a lane defect" better than a dead window, and #144 changed Conductor admission that same morning.
- Fix:
  - (1) One owner for fleet liveness: EC supervises all 3 roles, adds a `coderpx_gemini` row, and re-recovers periodically through WatchF `recover_role` with backoff, never while a submit holds the role.
  - (2) Remove `chrome_x` from the fleet-ensure set, or map the alias.
  - (3) Diagnose the Perplexity `CDPLaneAcquireError` separately: read the Conductor `cdp:perplexity` rows and holders and the lane-lock dir at failure time, and record holder pid, age and `CDP_MAX_HOLD_EXCEEDED` events (ties to C-5).
  - (4) Add a non-scrape reviewer to the first two review positions. **Not agy:** live rule 3 says "AGY = implementation only … Never use AGY for diagnosis, audits or reviews". agy is also impl position 1, so it would be same-family for agy-authored diffs. Options are a paid API lane (Q3) or the existing non-CDP lanes (kimi_cli, glm_zai) once their quota allows. Any non-scrape reviewer still obeys reviewer family ≠ author family, and two families for R3.
  - (5) Add `transport_class: scrape|api|cli` and require one non-scrape lane per R3 review set.

**C-2 · P1 · bug · R1 · S · CONFIRMED: the router pre-fills `MODEL_IDENTITY answered=<expected>`, so the cross-family gate is tautological** [PROMPT-6, CDP-5]
- Evidence: `lane_router.py:1924-1928` and `:1938-1942` write `answered={m_label}; route=requested`. `test_lane_router.py:4347` asserts the pre-fill. The template (`PACKET_TEMPLATE.md:137-140`) says "Do not copy the requested name into answered". The only check (`:2770-2797`) compares the dictated `MODEL:` line. `gates_merge = trust=='trusted'` (`:2927,:3190`). `PERPLEXITY_ROSTER.md:30-31` documents the Best route.
- Fix: use the neutral wording from `dispatch.py:1085`. Read the driver's `verified_model`/route readback, and set `gates_merge=false` plus `MODEL_UNVERIFIED` when it is missing, Best or unknown. Keep the MODEL line as a format check only. Add a real-path test (`wrap_coderpx_packet` → receipt).

**C-3 · P1 · fragility · R2 · L · CONFIRMED: SUBMIT_UNCONFIRMED is overloaded and terminal with no read-only collect; fixed timeouts manufacture it; an adapter timeout falls through to the next lane** [CDP-7, DISP-8, ORCH-9, CDP missed]
- Evidence:
  - `lane_router.py:2619-2680` sets `held` and nothing reads it.
  - `chatgpt_chat_pro` has `--response-timeout-s 840` with a 900 s adapter (= "times out after about 14 min", 11-05:130). #160 cut Argon at 180 s and then raised it to 780 s.
  - There is no `{driver_timeout_s}` placeholder (`:1401-1442`).
  - On `adapter_res.timed_out` the router moves to the next lane (`:2516-2531`), which replaces an attempt that may already be in flight. That contradicts `roster:67`.
  - The ~14-min ChatGPT Pro timeout (840 s) follows directly from the operator's 15-min release rule (live rule 2) and the #173 clamp `MAX_JOB_TIMEOUT_S = 900.0`. It is not a free tuning knob.
- Fix: split the status into `SUBMITTED_AWAITING` (conversation URL and nonce recorded at submit time) and `SUBMIT_UNCONFIRMED`. Add `lane collect <job>`: read-only, bound to the recorded conversation, never submits, with a round-trip test plus the refusal branch. **Collect is how long answers finish.** The slot is released at ≤15 min, the answer keeps generating in the browser conversation, and a later collect harvests it. Add a `{driver_timeout_s}` placeholder = router timeout minus margin, so every driver stops before the 900 s release. Do not raise per-role timeouts above 15 min. Whether Pro or Argon R3 reviews may hold a slot longer is an operator question (Q3). A CDP adapter timeout is a custody halt, not a fallthrough. Until collect exists, show held jobs with their slot or conversation id in `lane status`.

**C-4 · P2 · contradiction · R1 · M · PARTIAL+NEW: concurrency for one Chrome role is governed by several uncoordinated gates** [CDP-1, ORCH-3]
- Evidence:
  - Container code (`lane_router.py:734-737`): `chatgpt_chat_pro:1, argon_cdp:3`, keyed by lane_id. Conductor: `cdp:gemini:1` (`conductor_resources.py:78-83`). `cdp_lane_lock` is exclusive per role and the router never calls it. Another gate is the WatchF slot DB (`:891-970`).
  - **NEW:** #173 and #144 aligned ChatGPT and Perplexity at 4 today, but Argon is still 3 in the router against 1 in Conductor. `astra_work`/`sol_work` still skip the ChatGPT slot check (id-substring test). `dispatch.py:83-107` has a relative-path fallback lock.
  - Whether the WatchF drivers lock internally is missing evidence.
- Fix: give every row a `cdp_role` field. Admission sits next to the process that touches Chrome. Declare the WatchF slot pool as a named gate. Set Argon to 1 until the per-account Chrome setup is proven. Make the fallback lock fail closed.

**C-5 · P2 · bug · R1 · S · NEW (code-confirmed, impact plausible): Conductor's new 15-min max hold evicts *live* CDP holders**
- Evidence: dotclaude `298882f:scripts/conductor_resources.py`: `DEFAULT_CDP_MAX_HOLD_SECONDS = 900`. At ~L767-806 an ACTIVE `cdp:chatgpt|cdp:perplexity` request older than 900 s from activation gets `cdp_max_hold_exceeded=True`, which skips the heartbeat `continue` and, at L842, sets `evidence="CDP_MAX_HOLD_EXCEEDED"` **before** the owner-liveness branch. That branch's own comment says "One live … owner keeps the hold; elapsed TTL alone never establishes process death". The adapter timeout is 900 s plus prompt build, measured from adapter start, not from Conductor activation. `auditgpt` waits 840 s for the response after setup. #173 (`bfc4294`) obeys the same operator rule correctly: it clamps `MAX_JOB_TIMEOUT_S = 900.0` so the work itself ends within 15 min, and its 1,500 s `_LANE_LOCK_HARD_STALE_S` is only a pid-reuse ceiling that leaves a live holder alone.
- Why it matters: a fifth submit can enter a window that is still answering, which manufactures SUBMIT_UNCONFIRMED and UI collisions (class 1/5).
- Binding constraint: LIVE `model-launch-rules.md` rule 2 (operator 2026-11-04) says "every slot is released at most 15 min after it is taken — a stale holder … is a lane defect to repair at once". Do **not** raise the max hold.
- Fix: keep the 15-min release and remove the overlap by one of two means:
  - (a) every CDP driver's answer timeout ends before the 900 s release, **measured from Conductor activation** (pass the remaining budget down as `{driver_timeout_s}`); or
  - (b) eviction first kills the owner's process tree (cdp_lane_lock's job-object pattern), then releases the slot.
  - Add a test: at 900 s the owner tree is dead before the slot is reused, and no fifth submit starts while a window is answering.

**C-6 · P2 · gap · R1 · S · CONFIRMED: no per-lane packet size caps; the skill says size does not matter** [PROMPT-7, CDP-4]
- Evidence: the only cap is 256 KiB in `wrap_coderpx_packet` (`:1967-1971`). `roster:114-115`: Perplexity rejects 40k characters, and Argon above ~50 KB is unconfirmed about half the time. `coderpxC/SKILL.md:43` says "the limit counts submits, not size". **LIVE** `model-launch-rules.md` rule 6 asks for GitHub links instead of pasted diffs, while the router inlines excerpts.
- Fix: `max_prompt_chars` per lane, and refuse before submit with `PACKET_TOO_LARGE`, which consumes no round and does not queue. Fix the skill text. Reconcile rule 6 with the router packet mode.

**C-7 · P2 · gap · R1 · M · PARTIAL: no canary and no DOM fixtures; breakage is found by real jobs** [CDP-3 canary, CDP-9]
- Evidence: `preflight.py` stops at the "drive" depth (a visible composer, `:22-34`). No EC service schedules a deep probe. The selector regressions (WatchF #524 "Working", two picker rebuilds, today's `model_picker_not_found`) are documented only as prose in `DISPATCHERS.md` §8.
- Fix: a WatchF-owned canary that does picker enumeration and label readback without submitting, takes the same role admission as jobs, respects Argon spacing, and does a nonce submit only at fleet start and after a DOWN. It writes `cdp_lane_health.json` (typed class plus DOM hash). Add a router probe kind `health_file{max_age_s}`. The canary heals only the reason it tested. Commit sanitized DOM fixtures with Playwright contract tests. Implementation is WatchF work.

**C-8 · P2 · fragility · R0/R1 · S · CONFIRMED: review loops do not converge; the lane door dropped the round cap** [INC-9]
- Evidence: #2493 12 rounds, #2362 r16, #2527 5 failed rounds, 11-05 4-5 rounds. `dispatch.py:54-56` sets `MAX_ROUNDS_PER_SLICE=5` (enforced at `:4355`), and `lane_router` has no round concept. The review preamble (`:1929-1966`) carries no invariants, findings or delta SHA.
- Fix: per-PR findings ledger (ID, severity, path:line, status) plus `delta since <reviewed SHA>` in the preamble. Reviewers verify closure and report only NEW blockers with a reproducer. A round counter from receipts returns `needs_plan` after round 3 (the #2415 precedent). **Review-verdict DoD** in the reviewer role card and preamble: line 1 `MODEL:`, then `identity_evidence` (picker_readback | self_report | none), then exactly one of SHIP | SHIP-WITH-FIXES | BLOCK, then `file:line` plus a reproducer for every blocker. The router marks a verdict without these fields `verdict_malformed`, so it neither gates nor triggers another round.

**C-9 · P2 · stale · R0/R1 · S · CONFIRMED: the protocol anti-drift test is red and not in CI** [CDP-10]. `coderpx/test_coderpx_protocol.py:41` fails (the README changed in 141e7d7). `pytest coderpx cdp_fleet`: 1 failed, 17 passed. Fix: put `coderpx/`, `cdp_fleet/` and `dispatch/` into `hybrid-ci.yml`. Update `EcosystemControl/tests/test_config.py:788` before deleting the `chrome_kimi` row.

**C-10 · P3 · bug · R1 · S · UNVERIFIED-P3: `preflight.py` rejects the documented `chrome_x` alias** [CDP-12]. `_parse_roles` and `recover()` skip `_ROLE_ALIASES`. LIVE: WatchF also rejects `chrome_x` (see C-1).

### 3.4 Orchestration, lease and durable-delivery layers

**O-1 · P2 · improvement · R0 · S · CONFIRMED: no state-authority map; at least six durable stores** [ORCH-12, ORCH-7]
- Evidence: `~/.claude/state/{lane_health,lane_queue,lane_receipts,lane_locks}`, `cdp_lane_locks`, `~/.conductor/conductor.db`, the WatchF slot pool, `dispatch/receipts` and the `coderpx.program.v2` store. The program_* cluster (11.2k LOC prod, 10.7k test) was last touched 10-12 and is still referenced by the sidecar installer and `roster_installer_ci` (so it is P3, not dead). **LIVE:** an extra stray 0-byte `~/.claude/state/conductor.db`.
- Fix: a descriptive `apps-shared/dispatch/STATE_AUTHORITY.md` (resource → current owner → writers → recovery verb → known contradictions), linked from the contract. Leave the target column open until the WatchF lock question is answered. Mark the coderpxg/custody plans Superseded, and add a pytest marker for program_* only after the operator confirms nothing launches `program_entry`.

**O-2 · P2 · gap · R1 · S · NEW/LIVE: unbounded retention across stores, with doctor checks that are write-only** [ORCH-11 + live]
- Evidence: **LIVE** Conductor receipts at 236.5/256 MB with `retention_mode: REPORT_ONLY`, `host_resource_events` 30,053 rows, DB 397 MB. `lane_receipts` 783 MB in 31,305 files (no reaper in `lane_state.py`). The collector reports about 30k `session_binding` files (not in the bundle). `ecosystem_doctor.py:55-60` sets a verdict ceiling of 800, while 11-03:76 counted 1,446.
- Fix: a retention policy per store (lane receipts: keep `.final` for 30 days, attempts and prompts for 7 days, never delete `held` or unconsumed jobs). Switch Conductor to enforce at 80%. Doctor reports per-store % of ceiling. Either the handoff generator consumes verdicts or verdicts stop by default.

**O-3 · P2 · risk · R2 · M · CONFIRMED: Tsignal CCTV hard-depends on dev-tool Conductor admission** [ORCH-8]. `cctv_feed_supervisor.py:58,1173-1176,2000-2019` defaults to `required`, and a failure latches recovery. Keep it fail-closed. Declare the Conductor resource CLI as a versioned contract with conformance fixtures, so any Conductor change, including C-4/C-5, is R2 for Tsignal. #144 touched only chatgpt/perplexity, not `cdp:tv`.

**O-4 · P3 · fragility · R1 · S · CONFIRMED: the contract's only override tool is missing on main and its path is hard-coded** [HOOK missed]. `lane_router.py:3833-3836` points to `D:/dotclaude/.../lane_authorize.py`, which exists only on the S2 branch. Contract rule 5 is therefore a dead end. Fix: mark it pending, or land `lane_authorize.py` alone, and resolve the path through `TSIGNAL_APPS_ROOT`.

### 3.5 Master (supervisor) sessions

**M-1 · P1 · fragility · R1 (tool) / R2 (EC service) · M · CONFIRMED+LIVE: the master's operational state lives in the session; chains are orphaned or die at handoff** [SUP-1, INC-4, LAND-1]
- Evidence:
  - 11-05:52 "TaskStop does not kill the bash children … merged on their own". :53 is the self-killing kill regex. :55 "ci_seq2.sh lives in the old session's scratchpad". :61 "dies with that session".
  - 10-27:43 "report reaches the old supervisor session". 10-21:95-96 "Tools (scratchpad …)".
  - `coderpxC/SKILL.md:169-213` says "the chat board is the source of truth".
  - No merge-chain tool exists in any repo. `program_delivery.py` is unused.
  - **LIVE:** `ci_seq2.sh` is untracked in `D:/APPS/_shared/dispatch/`, and 2 scripts have been running from `Temp/claude/…` since 09:25.
- Fix: a repo-tracked `apps-shared/ci/merge_chain.py` (or `land`) with a persisted queue file and a pidfile. `--takeover` kills by the recorded PID tree. It merges only PRs with a review status at the exact head (L-1), using `--match-head-commit`. Lifetime rule: the runner holds a lease renewed by its owning master. When the lease lapses it finishes or aborts the current item and **pauses**, and never starts an unowned merge. (Whether the queue should also refuse R3 merges during RTH is **not** an existing invariant. Contract hard rule 5 gates *restarts* during RTH, not merges, and the bot picks up main only on restart. It is offered as an operator proposal in Q4, not as part of this fix.) Later, an EC-supervised service with process-tree ownership. Do not wrap `DeliveryController` (its program-authority preconditions do not fit). Copy its state discipline instead.

**M-2 · P1 · gap · R2 (auto-commit) / R1 (ack, inbox, doctor) · S · CONFIRMED+LIVE: lane results have no consumed state; DONE results rot in dirty worktrees** [SUP-3, INC-7]
- Evidence: 11-05:76, 80 and 101 list three unprocessed results (R3 lost-fill, #2658, #2647). The impl preamble says "Do NOT commit". The next run refuses the dirty tree. `session_lifecycle.py:744-790` looks only at the cwd checkout. Direct (non-queued) DONE runs leave no job record at all. **LIVE:** 2 `held` impl jobs in the newest 10.
- Fix:
  - R1 part: write a job record for every run. Add `lane ack --job ID --state verified|committed|abandoned [--sha]` and `lane inbox`. Add an `ecosystem_doctor` `lanes` check: DONE-unacked, held, expired, dirty worktrees with no ack.
  - R2 part (plan first, draft PR plus cross-family review): on a DONE impl, the router commits on the **lane branch only**, after its own `verify_cmd`, as `wip(lane): <job> verify=<pass|fail>`, using explicit pathspecs. This changes the persistence and custody path and reverses the router's own preamble ("Do NOT commit", `lane_router.py:1913`), so it is R2, not R1.
  - The supervisor's verify step for these results follows R-3: targeted tests during RTH (live rule 10).

**M-3 · P2 · gap · R1 · M · CONFIRMED: the lane CLI is synchronous with no detach or wakeup; masters poll with background bash and in-session cron** [SUP-6]. `lane_router.py:3640` runs `run_job` inline. coderpxC prescribes a 15-min CronCreate board. Fix: `lane <role> --detach` (job record with pid and owner, run under a job object or process group), plus `lane wait --any --timeout` that watches `receipts/<job>.final`. The master runs a single Monitor on it. Build on the existing receipts and do not add a new events store.

**M-4 · P2 · overengineering · R1 · M · PARTIAL: the session-lifecycle stack produces artifacts nobody consumes; handoffs are hand-written** [SUP-7, ORCH-11]. `truthdeck_handoff.py:27-29` needs 40-hex `Base SHA:` / `Head SHA:` lines, which only 1 of 537 handoffs has. `ecosystem_doctor.py:11` reports "1,601 verdicts … 0 consumed". "submit_unconfirmed" is re-typed in 16 handoffs. Fix: `supervisor_state handoff` generates the factual block (bot SHA vs main, PR table head/review/CI, worktrees with dirty counts and owning job, lane inbox, lanes-now, CI queue, Base/Head SHA lines) from receipts plus `gh` plus `git worktree list`. The human writes only intent, decisions and do-not-touch.

**M-5 · P2 · bug · R1 · S · CONFIRMED (repro): the SessionStart "recent handoff" hint picks a July file** [SUP-11]. `session_router.py:217-224` slices `[:200]` before `max(mtime)`. Tsignal has 537 handoffs, and the 200th in NTFS order is `2026-07-09_…`. Fix: scan with a bound of ≤2000, key on the filename date prefix and then mtime, and add a test with more than 200 files.

**M-6 · P3 · overengineering · R0 · M · PARTIAL: the Tier-2 coordinator adds a place where results get lost** [SUP-8]. Merge into M-1: every coordinator or subagent writes its result to a repo or ledger path before returning. Retiring the tier is an operator decision once there is token data.

**M-7 · P3 · bug · R1 · S · UNVERIFIED-P3: `answer_footer` prices Opus 5.5 and Sonnet 5.5 at the fallback rate and rescans the transcript on every Stop** [SUP-13]. Fix: longest-prefix family match and a cached byte offset.

**M-8 · P2 · gap · R1 · S · PARTIAL: quota is discovered by failing and there is no burn view** [INC-11]. `lane status` already prints `until=` and recent events (`:3706-3720`). What is missing is hits over 7 days, a soonest-reset preference, and reconciling `roster:82-87` "tell operator at once" with contract rule 4's one line per turn. **LIVE** `model-launch-rules.md` rule 9 also says "at once" and "never auto-rotate accounts", so automated AGY or Argon account rotation is **out of scope** unless the operator changes rule 9 (the EC rotation plan e87ac1f stays parked). Add a per-lane scorecard to see who actually delivers: `lane status --scorecard`, computed from receipts, shows DONE / FAILED / QUEUED per lane over 7 days with the dominant `failure_class`. Live data already contradicts lane health: `perplexity_grok` is UP with cf=145, and its `last_job_id` `p0-waiver-review2-1105` failed with exit 70. The scorecard gives masters and the operator data for reordering the roster instead of rule churn.

### 3.6 Enforcement and config distribution

**E-1 · P1 · risk · R0 now / R1 next · S · CONFIRMED+LIVE (P2 to P1): the injected contract claims hook enforcement that does not exist; the only live guard is unversioned** [HOOK-1, PROMPT-2, SUP-5]
- Evidence:
  - `supervisor-contract.md:1,7,24` ("enforced by hooks", "denied by hooks", "blocked … by hooks").
  - `templates/hooks.manifest.json` has no PreToolUse entry.
  - PR #141 is draft, `merged_at:null`, updated 2026-10-27. The S2 branch (+7,122 lines) does not touch the manifest or `hooks_install.py`.
  - **LIVE:** the only PreToolUse hook is `model_launch_guard.py` on Bash|PowerShell, hand-edited 10-27 and 11-03 with `.bak` copies. It reads the unversioned `model-launch-rules.md`. There is no Read, Edit, Write or Agent guard, and `claude_worker_guard.py` is absent. The installed contract copy is identical to the template.
  - The contract injected into every session, including cloud and Linux sessions, hard-codes `python D:/APPS/_shared/dispatch/dispatch.py lane` (`supervisor-contract.md:7`), and `lane_router.py:3834` hard-codes the D:/ path to `lane_authorize.py`. In a cloud session the "single door" does not resolve, so the model improvises [HOOK missed #4].
- Fix:
  - Today, reword the contract to what is true ("policy; mechanical guard: Codex model flags on direct Bash launches only").
  - Resolve the door path through an env var (`DISPATCH_PY`, or `TSIGNAL_APPS_ROOT`/`_shared`) rendered at injection. Add one line: "If the door is unavailable on this host, do not launch models directly; report BLOCKED with the missing path."
  - Move `model_launch_guard.py` and `model-launch-rules.md` into dotclaude (`scripts/`, `agent-rules/refs/`) with a manifest entry, so `hooks_install` owns them. Generate the enforcement line from `hooks_install status`.
  - For S2, land only the `Agent` model guard, or use native `CLAUDE_CODE_SUBAGENT_MODEL` + `_FORCE` and `permissions.deny Agent(...)`, plus a direct-model-CLI Bash deny, starting log-only. Close the read and edit bans (Q2).
  - Caveat on `_FORCE`: it applies to **every** subagent and overrides any deliberate Opus subagent the roster allows (for example "Opus subagent for R3 root cause"). It is not a drop-in replacement. Put it in the supervisor profile only, and give deliberate Opus work a separate session, or keep the `Agent` guard with an explicit allowlist.

**E-2 · P1 · gap · R1 · S · CONFIRMED+LIVE: the Codex credit guard exists but the single door never calls it** [HOOK-6]. `codex_limit_guard.py` (#136) is referenced only by itself. `codex_terra` (automatic impl position 5) runs a raw `codex exec`. Reactive quota detection cannot trip, because at 100% Codex silently spends credits. **LIVE:** `model_launch_guard` checks model flags only, and router Popen launches never pass through it. Fix: a pre-flight for every lane whose argv[0] is `codex`, `manual_only` lanes included. Exit 75 maps to `mark_down(reason='weekly_limit', reset_at=…)`. "Credit state unknown" is shown as such, not as OK.

**E-3 · P2 · bug · R1 · S · CONFIRMED (repro): the installer cannot wire an `Agent`, `Skill`, `PowerShell` or `mcp__*` matcher** [HOOK-2]. `hooks_install.py:48-51` `KNOWN_TOOLS` has only `Task` and others. An `Agent` matcher raises `HookInstallError`. **LIVE:** the PreToolUse matcher in use (`Bash|PowerShell`) is itself not installable through the manager. Fix: a shape check (`^[A-Za-z]\w*$|^mcp__\w+$`) plus a warning for unknown names. Keep `Task`.

**E-4 · P2 · contradiction · R1 · S · CONFIRMED: two installers own the same deployed command files** [HOOK-4]. `dotclaude install.ps1:27-30,51-63` and `claude-config/sync_to_home.py:9-24` both write `~/.claude/commands/{fwf,fwp}.md` and `~/.codex/prompts/fwa.md`, with different content (fwa is 144 lines in one and 10 in the other). `astra_activation_r2.md:25` names claude-config as owner. This is an operator ruling. The losing installer becomes check-only, plus a test that no two installers declare the same target.

**E-5 · P2 · fragility · R1 · S · PARTIAL: hook health is not observed** [HOOK-8]. `ecosystem_doctor.py:366-371` checks only hooks, verdicts, temp and janitor. Router exceptions drop the routing context to `hook_errors.log` (`session_router.py:670-676`). Fix: doctor checks for `hook_errors.log` in the last 24 h by code, the contract source and its sha, live PreToolUse versus the manifest (this would have caught E-1), and storage %. Per-hook failure policy: context hooks fail open loudly, deny guards fail closed only on an explicit rule match.

**E-6 · P2 · fragility · R1 · S · CONFIRMED+LIVE (P3 to P2): a hand-copied `~/.claude/refs/supervisor-contract.md` shadows the template** [HOOK-10]. `session_router.py:545-548` gives home refs precedence over the repo template. **LIVE:** that copy exists (2,457 B, 10-26) and nothing installs it. Every R-3/E-1 template fix would silently miss sessions. Fix: install it with a hash check, or drop the home path from the lookup. Emit the contract sha in the context.

**E-7 · P3 · stale · R0 · S · PARTIAL: the claude-config mirror misleads evidence and cloud sessions** [HOOK-5]. Settings are from 2026-03-26 (Edmonton/Trailforks rules, `C:\Users` paths). Fix: rename to `settings.snapshot-2026-03.json` and make CLAUDE.md a pointer.

**E-8 · P3 · risk · R1 · S · UNVERIFIED-P3: a dormant ntfy approval hook would approve tool calls from a public topic** [HOOK-11]. `claude-config/hooks/ntfy_approve.py:17,50-51`. Delete it, or add a per-request secret. It must never be wired on the trading box.

**E-9 · P3 · fragility · R1 · S · UNVERIFIED-P3: hook and guard tests are coupled to Windows paths; CI is windows-latest only** [HOOK-12]. Fixtures use `D:/tmp/...`. Derive them from `tmp_path` and add an ubuntu job.

### 3.7 Landing and CI

**L-1 · P1 · gap · R1 (receipt) / operator (plan) · M · CONFIRMED: no server-side merge gate, and "exact-head review" is not bound to any SHA** [LAND missed, LAND-4]
- Evidence:
  - `gh api repos/rebusz/Tsignal/branches/main` returns `protected:false`. Rules return 403 "Upgrade to GitHub Pro". `allow_auto_merge:false`.
  - `ci.yml:154` and #2653 assume a "required check name" that nothing enforces.
  - #2651's last review (comment 6645538191, 23:54:36Z, names no SHA) was followed by `8c5b9c1bc`, which added `REVIEWED_PROTECTIVE_STOP_LATENCY_LOOP_PROBE` to `tests/test_submit_seam_mock_boundary.py` (S2 order-path guard: "a new hit is a test-design review"). The PR merged 17 min later.
- Fix: `review_receipt.py` posts commit status `review/cross-family` on the exact SHA, with lane, model and verdict. Mechanical carry-forward only for a conflict-free merge from main whose range-diff is identical, or for `*.md`/design-only deltas. **Never** for tests, fixtures, baselines or allowlists. The landing queue (M-1) is the sole merger. A post-merge audit in merge-evidence flags merges whose PR head lacks the status. GitHub Pro for real required checks is an operator cost decision (Q4).

**L-2 · P1 · fragility · R1 · S · CONFIRMED: nothing serializes full suites; concurrent runs share one CPU mask and crash xdist** [LAND-3, INC-3, SUP-12, ORCH-10]
- Evidence: `ci.yml:24-26` concurrency is per ref. The test job uses `[self-hosted, Windows, X64]` (`:156`). `TSIGNAL_CI_CPU_MASK 0xFF00` at `-n 6` (`:199-204`): three runs put 18 workers on 8 CPUs, on the live workstation during RTH. The comment at `:195-198` says this "no longer costs green", while 11-04:35 recorded "20+ spurious failures and xdist INTERNALERROR".
- Contradiction with a binding rule: LIVE `model-launch-rules.md` rule 10 says "No heavy local tests during RTH". `ci.yml:200` says "CI runs during RTH on the trading workstation" (operator 2026-08-14, CPU-masked). The 11-03 binding rule 5 asks for "the broad local suite (-n 6) before gh pr ready". R-3/M-2 add verify duties. Either the CPU mask counts as compliant with rule 10, or full suites must move off-box or outside RTH during market hours. That is the operator's call (Q1).
- Fix: register exactly one instance with `--no-default-labels --labels tsignal-full,Windows,X64` and target the full suite at it. GitHub queues runs without dropping them, which workflow concurrency would not do. Separate `proof_labels` from `local_labels` in the hybrid policy so the selector stays on a light instance. Fix the misleading comment and #2653's "serialize above" before it merges. If Q1 rules full local suites out during RTH, route full suites hosted during RTH (#2653) and local only outside RTH. The operator registers the runner.

**L-3 · P1 · bug · R1 · S · CONFIRMED (GitHub): any PR comment, including a posted review, cancels the running Draft CI** [LAND-2]. `draft-ci.yml:12-13,28-35`: issue_comment and pull_request share the group `Draft CI-<PR>` with `cancel-in-progress`. Run 41937199558 was cancelled at 23:55:29Z by issue_comment run 41937356759, two seconds after review comment 6645538191. Fix: move `/ci full` to its own `ci-command.yml`. Validate with actionlint plus a replay comment.

**L-4 · P1 · bug · R1 · S · CONFIRMED (GitHub): merge evidence misses green runs, so redundant main suites run and turned main red twice** [LAND-8]
- Evidence: `ci.yml:110-124` filters `event:'pull_request'` and requires a run-level `success`. `/ci full` dispatches `workflow_dispatch`, which the filter misses. PR runs 41913409494, 41783684752 and 41820935314 concluded "cancelled" in the same second their pytest job succeeded (cause unknown). That triggered main reruns 41823120945, 41921684104 (red) and 41786525281 (red).
- Also: main goes red for **infrastructure** reasons with no triage. Push run 41879990854 (#2648) failed in "Settle CI reservation" (exit 1, no annotation detail) with pytest skipped. The next session would read that red as a test failure [LAND missed].
- Fix: look up check-runs for `pytest (Python 3.12, ubuntu)` at the head SHA from any event (fail open stays). Set main push `cancel-in-progress:false` or group by sha. Investigate the run-level cancel, probably the `always()` selector or settle jobs. Make a failing settle/selector step write a job-summary line ("infra: billing settle failed, pytest not run") and alert through the CI watchdog, so it does not look like a red suite. Coordinate with #2653.

**L-5 · P1 · contradiction · R3 · M · CONFIRMED+LIVE: operator-state files are tracked although `.gitignore` says they are "not source", which blocks checkout sync after every merge** [LAND-6]. `.gitignore:31-34` lists them, yet `git ls-files` shows `config/pure_signal_config.yaml` and `tsignal/ui/settings.json` tracked. `checkout_sync.py:64-67` and `restart_preflight.py:65-75` refuse on tracked dirt. 11-04:47 records a stash/apply plus the leftover `opctl-2640`. **LIVE:** 4 `pure_signal_config.yaml.bak_*` files in the main checkout. Fix (R3 plan): untracked `*.override.yaml` layered over the defaults, following the `executor_config_override.yaml` precedent. Migrate once, read back on start, and log stale keys. No `skip-worktree` shortcut.

**L-6 · P2 · gap · R1 · M · PARTIAL: no flake ledger; up to three stacked retries** [LAND-7]. `ci.yml:392-412` absorbs up to 5 failures with only a warning. The chain adds `rerun --failed` on top. Flake lists differ between handoffs. CI runs `-p no:randomly` while `pytest.ini:14` sets `randomly_seed=last`. Fix, in order L-2 → L-4 → ledger: `tests/flake_ledger.json` with expiry as the only absorbable set. `r3_contract` tests are never absorbable. Drop the chain-level rerun. Add one weekly randomized-order run.

**L-7 · P2 · risk · R1 · M · PARTIAL: after #2653, hosted Ubuntu and local Windows evidence share one check name** [LAND-9]. `hybrid-policy.json` routes `ci.yml::test` to ubuntu-latest under `pytest (Python 3.12, ubuntu)`. #2653 adds a `local_only` marker that skips host-affine proofs. Fix: the job summary records route, `runner.os` and the count of skipped `local_only` tests. R3-manifest PRs force a LOCAL route at the exact head.

**L-8 · P2 · gap · R1 · M · CONFIRMED: cancelling a run does not stop pytest; there is no reaper** [LAND-10]. The watchdog is report-only (`ci/watchdog/README.md:5-6`). The installer already wires `ACTIONS_RUNNER_HOOK_JOB_STARTED` (`install_hybrid_ci.ps1:189`). Fix: a `JOB_COMPLETED` hook that kills only processes whose exe or cwd is under that instance's `_work`, with a kill ledger and **never** matching on the name `python.exe` (the live bot shares the box).

**L-9 · P2 · bug · R1 · S · LIVE (P3 to P2): the worktree reaper is blind to squash merges** [LAND-11]. `git_hygiene.py:141-144,318-346` uses `is_ancestor`, and squash merges never are ancestors, so landed worktrees are "[R3] unmerged" forever. **LIVE:** Tsignal 747 worktrees and 33 stashes. `TsignalGitHygiene` result 0x41306 (terminated). Fix: detect "landed" by tree containment (`git merge-tree --write-tree`) or by merged-PR head equality via `gh`. Stays report-only by default. Add a squash-merge fixture test.

**L-10 · P2 · fragility · R1 · S · CONFIRMED: Windows shell pitfalls are relearned instead of encoded** [INC-10]. `draft-ci.yml:374` uses strict equality on `/ci full`, so MSYS-mangled bodies ("C:/Program Files/Git/ci full") are dropped silently (11-03:37-39). Fix: reply "unrecognized command" when the body ends with `ci full` but does not equal it, keeping the OWNER/MEMBER/COLLABORATOR check. Ship the takeover and force-cancel helpers with M-1.

---

## 4. Compliant / working well

- **Rules generator:** `sync_agent_rules.py` re-renders the Tsignal CLAUDE.md and AGENTS.md byte-identically (checksums d772affb…, 6ea8a71d…). It has a fail-closed size guard (`:217-223`). The drift is in the sources, not the generator.
- **Right-sized skills:** `Tsignal/.claude/skills/tsignal-*` are 1.2-2.7 KB lazy evidence routers with ~150-character descriptions. They state what to check and where, not long procedures. This is the model for slimming coderpxC, DISPATCHERS and the roster.
- **Core invariants at the right altitude:** `core.md:14-23` (risk classes = care, not access; live read free, trigger gated; parity; emergency-off default ON) and the evidence DoD (`core.md:81-85`, `paper-live-parity.md`, `delegated-execution-protocol.md`).
- **Session router** fails open with a "SUPERVISOR CONTRACT MISSING" sentinel, keeps its context bounded, uses `untrusted_text.clean_fact`, and injects the contract even on error (#143).
- **Router data model:** roster order, family, roles, trust and `manual_only` are data (`load_registry` `:1134-1250`). State uses a FileLock with atomic writes and corrupt-JSON quarantine (`lane_state.py:91-245`). Quota resets are parsed and per-account Argon rotation is classified (#154). Impl handling has an empty-diff FAIL and a `verify_cmd`, and the attempt diff is saved before any reset. Cross-family exclusion survives `--prefer-lane`. Spend guard and probation lanes stay out of R2/R3.
- **CDP custody:** no blind retry after SUBMIT_UNCONFIRMED. `cdp_lane_lock` (OS lock as the truth, kill-on-close job object, exit 75/70, 13/13 tests pass). Browser lanes are advisory, with a fail-closed secret scan.
- **Today's #173 router change** was reviewed by ChatGPT Pro and Sonnet. It implemented the operator's 15-min rule by clamping job time to 900 s, so work ends before release, and kept the 1,500 s lock ceiling only as a pid-reuse guard. Operator rule → code → test in the same morning is the pattern to copy. C-5 (Conductor, #144) is the one place where the release happens without ending the work.
- **Conductor:** evidence-bearing recovery (owner pid + start time, `OWNER_PROCESS_ALIVE`), port-free SQLite WAL. **LIVE:** 0 current RECOVERY_REQUIRED rows.
- **interlock_lease** (broker arm lease): OS mutex only, no TTL takeover, fail-closed. Keep it out of any consolidation.
- **CI:** fail-open squash-merge evidence (`ci.yml:62-128`), pinned and hash-verified dependencies, a job-scoped venv, CPU mask away from trading cores, a bounded fail-closed flake retry (a watchdog kill is never retried), `/ci full` limited to OWNER/MEMBER/COLLABORATOR. The hybrid router fails closed with a USD 3 hard stop. `checkout_sync.py` is ff-only and never resets.
- **Live-safety discipline under pressure:** flat-gated restarts with ProjectX/IBKR readback, Combine DISARMED, real-money triggers left to the operator (11-04:24-30, 11-05:34,117).
- **Handoffs** record requested vs actual model, exact heads and merge SHAs. That made this archaeology possible.
- **Evidence collection:** the live bundle was read-only, redacted with a self-tested redactor, and listed its own false positives. This is a good template for future audits.

---

## 5. Risky-but-acceptable, and false positives

**Risky-but-acceptable (keep, document):**
- `agy --dangerously-skip-permissions` pinned by operator decision D4 (`lanes.json:28`), contained by the `--add-dir` worktree check plus a status readback. The router path is not subject to the classifier.
- Consumer-account CDP automation accepted as shared fate (`coderpx/README.md:17-20`). Acceptable for overflow. Not acceptable as the **only** way to satisfy an R3 gate (C-1).
- Tsignal CCTV fail-closed on Conductor admission (O-3). This is the right direction. It only needs a contract.
- A Sonnet fallback reviewer under operator rule 10-30 (lanes down, implementer not Claude). Acceptable once it is codified verbatim, receipted, and still family-checked (R-1/R-7).
- The contract-only context on a router exception (#143). Keep it, and surface the loss (E-5).
- The router's 15-min requeue for quota DOWN with a parsed reset. Fine once TTL and caps exist (D-3).

**False positives and refuted claims (checked, dropped or corrected):**
- *Lead 4 as a live bug* (agy flag pinned while the roster says denied): the router path is fine. Only stale prose remains (R-8, P3).
- *"settings.json has hooks {}, so no hooks are live"*: the mirror is stale. Live has 11 entries.
- *"dotclaude main has no commits since 10-27"*: true in the container, false live (#144 on 11-05).
- *"claude_worker_guard / guards exist in no repo"*: they exist on the unmerged S2 branch. Only `model_launch_guard` is repo-less.
- *Collector "MISSING" Tsignal project hooks and PreToolUse "(none)"*: parser artifacts (INDEX.md).
- *"112 stale QUEUED came from infinite requeue"*: they came from a dead poller (Disabled since 10-27). Infinite requeue is real but separate (D-3).
- *"Today's Perplexity failures were the fleet being down"*: not supported. The receipts say `CDPLaneAcquireError` (acquisition), and 9223 was serving shortly before the snapshot (`cdp/status.txt:10`). Only Argon's failure is fleet-down. The Perplexity cause remains unknown (C-1).
- *"Raise CDP timeouts or max hold above 15 min"* (earlier draft of C-3/C-5, DISP-8 "review R3 = 1800 s"): rejected. It conflicts with binding live rule 2. Long answers finish through collect instead.
- *"Add a read-only agy review/grill lane"* (CDP-8 verifier fix): rejected. Live rule 3 forbids AGY for reviews, and agy is impl position 1, so it would be same-family for its own diffs.
- *"The router puts 3 Argon submits into one window"*: unproven. The WatchF drivers may lock internally (C-4 is P2).
- *"Add an agy no-op probe"*: already implemented (`empty_diff`, `agy_edit_evidence.py`).
- *"Codex .git writes are rule confusion"*: the cause is the sandbox.
- *"Conductor is wedged in RECOVERY_REQUIRED"*: 221 transitions are historical and 0 are current.
- *"The agy rotation plan ignores ban risk"*: refuted (EC `2026-10-18_agy_gemini_account_rotation_r1.md:16`).
- *Unsafe recommendations rejected:* "verify passes ⇒ DONE regardless of transport" (D-1), auto-stash a dirty worktree (D-5), `--allow-dirty`, `skip-worktree` for operator YAML (L-5), Conductor as sole CDP enforcer before it has a contract (C-4), carry-forward of review across test or allowlist changes (L-1), auto-merge armed before a review status exists (L-1), moving program_* without updating the installer manifest (O-1).
- *Platform noise, not bugs:* 4 `test_session_router_contract.py` failures and 12 lifecycle tests (`D:/tmp` fixtures are not absolute on POSIX). The legacy `test_dispatch_*` failures come from the missing `~/.claude/scripts` and WatchF. 11 S2 guard failures on POSIX are probably path shape (E-9).
- *Lead 5* (MEMORY.md snapshot from 07-18): confirmed stale, not a false positive (R-6).

---

## 6. Target design: "Supervisor OS v2"

**Principle:** frontier models get *intent + invariants + live state + fast feedback*. Procedures belong in tools. State belongs in files that tools write. Prose never carries state.

**(a) Instruction layer**
- **Constitution** of ≤6 KB, identical for all runtimes. It holds invariants only: risk classes, live-trigger GO, paper/live parity, real-path test DoD, secrets, one-way data flow, reporting style. No model names, no dates. Soft wording that gives reasons ("because a fake green merges R3 code"), not CRITICAL/NEVER walls.
- **Role cards** of ≤1.5 KB, injected by whoever launches the agent. `supervisor` comes from session_router for an interactive Claude session. `worker`, `reviewer` and `coordinator` come from the router preamble. The supervisor card states authorship vs verification (R-3), the turn DoD ("returned output processed or re-dispatched this turn") and the queue duty.
- **Live state is machine-readable only:** `lanes.json` (`policy`, `lane_registry`, `operator_overrides[]` with `expires_at` and verbatim quotes) plus `lane_health` plus `operator_rules.jsonl`. SessionStart renders "lanes now" (≤800 B, with probe ages) and "active operator rules" (≤1.5 KB).
- **Generated views:** the contract routing lines, the roster table and `MODEL_ROSTER.json` are rendered from the registry, with drift tests.
- **Procedures** (Conductor, CI routing, CDP recipes, landing) are skills or `--help`, each ≤8 KB, on the `tsignal-*` router pattern.
- **Size budget** (one definition per number):

  | Layer | What it measures | Now | Interim (X5) | End state |
  |---|---|---|---|---|
  | Constitution | invariants shared by all runtimes (`core.md` after the cut) | ~11.8 KB core incl. procedure | — | ≤6 KB |
  | Global kernel | rendered `~/.claude/CLAUDE.md` = constitution + Claude overlay; guard 16,000 B | 15,987 B (0% headroom) | ≤12 KB (≥25% headroom) | ≤8 KB |
  | Role card | supervisor / worker / reviewer / coordinator, injected by the launcher | contract 2.5 KB to every runtime | ≤1.5 KB each | ≤1.5 KB each |
  | Repo CLAUDE.md | repo-local facts (ports, junctions, retired shell) | Tsignal 9.0 KB | ≤6 KB | ≤4 KB |
  | Live context | "lanes now" + active operator rules at SessionStart | — | ≤2.3 KB | ≤2.3 KB |
  | **Always loaded (Claude, Tsignal)** | sum of the rows above plus skill descriptions | ~33 KB | ≤24 KB | **≤15 KB** |
  | Supervisor on-demand refs | roster, DISPATCHERS, coderpxC, README, PACKET, fwf … | ~105 KB | ≤60 KB | ≤30 KB |

- **When prescriptive text is still needed (rule of thumb):**
  - (a) **Irreversible or safety actions are hard gates enforced in code, with text only stating the intent.** Live trigger GO, custody halts (SUBMIT_UNCONFIRMED never retried), the cross-family review gate, and never skipping or disabling tests. Frontier models reason well but do not always do it, so these must not depend on the model remembering.
  - (b) **Measured environment quirks** that no tool encodes yet stay as short refs, each with a `Last-verified:` date, until a tool takes them over and the line is deleted. Examples: MSYS `/ci full` mangling, the `glm.cmd` newline cut, packet size caps, the Argon 300 s spacing.
  - (c) **Everything else is intent plus invariants**: why the rule exists, what "done" means, where live state lives. No procedures, no model names, no dates.
  - Evidence that (c) is not the case today: `skills/coderpxC/SKILL.md` 227 lines, `coderpx/DISPATCHERS.md` 347 lines, and a ~2 KB OpenCode slice narrative inside the roster §5 "binding" cheat-sheet [CDP-11, PROMPT-11].
- **Feedback loops instead of more text:** `/doctor prompt-audit` on every rules PR. Skill evals with the skill-creator benchmark before and after each cut (trigger accuracy plus task success on 3-5 recorded master tasks). The lane scorecard (M-8) and doctor lines as runtime feedback.
- **Handoff template** (INC-12): state block generated by M-4, unprocessed results, pending operator decisions, the policy version. **No "binding rules" section.** New rules go to `operator_rules.jsonl` or `lanes.json` overrides.

**(b) One state authority per resource**
- Policy, queue, health and receipts: `lane_router` + `lane_state`, extended with lease and owner, TTL, `consumed_at`, `cdp_role` and `transport`. Write `STATE_AUTHORITY.md` first.
- Chrome-window capacity: one declared gate next to the process that touches Chrome (WatchF slot pool or role lock). Router and Conductor read it. The 15-min release (live rule 2) stays. A release must either follow work that already ended on its budget or kill the owner tree first, and must never free a slot under a live, answering owner (C-5).
- Broker arm: interlock_lease, unchanged. Evidence: TruthDeck, on demand. program_*: frozen, then retired.
- Retention is defined per store and enforced at 80% (O-2).
- Optional later: migrate lane JSON to SQLite WAL (consistent with "SQLite WAL is write master"), exposed as an MCP tool (`lane_submit`, `lane_status`, `lane_receipt` with a mandatory `failure_reason`). That removes the brief-file failure class.

**(c) Durable master state, generated handoff, event-driven waiting**
- `lane --detach` plus `lane wait --any` (Monitor) replaces polling and bash chains. Pushes go to the session via a channel or `subscribe_pr_activity` where available.
- Landing runs as a tracked tool or EC service with a persisted queue and lease-renewal pause semantics (M-1).
- The handoff is generated from receipts, gh and worktrees (M-4), plus ≤20 human lines. Successors begin from `lane inbox` and the state block.

**(d) Hardening the bridges**
- One fleet owner (EC) for chrome_gpt, gemini and ppl. Periodic re-recovery with backoff, never during a held submit.
- A canary that enumerates the picker without submitting and heals only what it tested.
- Typed driver errors (`coderpx.result.v1` → closed enum: UI_DRIFT_PICKER, UI_DRIFT_COMPOSER, SIZE_REJECTED, LOGIN_REQUIRED, ACCOUNT_MISMATCH, CREDIT_WALL, QUOTA, RESPONSE_TIMEOUT, SUBMIT_UNCONFIRMED, WINDOW_DOWN, LANE_ACQUIRE), with regex only as a fallback. A role-level breaker and exponential backoff.
- Per-lane size caps and `{driver_timeout_s}` (ending before the 15-min release). Submit/collect split, so long answers are collected, not waited on.
- Identity taken from driver readback.
- API-first where feasible: at least one non-scrape reviewer family on every R3 gate (OpenRouter or Gemini API under a spend cap if the operator approves; not agy, per live rule 3). The reviewer family is always ≠ the author family, and R3 keeps two families. CDP is demoted to overflow. CLI lanes are normalized on their NDJSON stream plus a final result plus a git diff readback.

**(e) Landing as a service**
- SHA-bound `review/cross-family` status. The queue is the sole merger, using `--match-head-commit`, with a post-merge audit.
- One `tsignal-full` runner label for serialization. Merge evidence by check-run. Draft CI unaffected by comments.
- Flake ledger with expiry: quarantine only lets a listed node be absorbed, it **never skips** a test, and `r3_contract` tests are never absorbable.
- A JOB_COMPLETED reaper scoped to `_work`. Squash-aware worktree reaping.
- Operator overrides moved out of tracked YAML (R3).

**(f) Enforcement that is versioned, tested and fail-safe**
- Every live hook is in the manifest, installed by `hooks_install`, and reported by the doctor (live vs manifest diff, sha of the contract injected).
- Native knobs are preferred over 3k-line parsers: `CLAUDE_CODE_SUBAGENT_MODEL[_FORCE]`, `permissions.deny Agent(...)`, PreToolUse `if` filters.
- Detection over prevention for frontier models: a Stop or SessionEnd audit of Opus spawns and Claude-authored R2/R3 diffs without a declared fallback, written to the status line.
- Deny guards fail closed only on an explicit rule match, and fail open loudly on infrastructure faults. Guards are scoped to sessions explicitly marked supervisor.

**What must NOT change (safety invariants):**
- One-way data flow (Tsignal → LAB → OF; H10 → OF). Advisory systems never write live decision or order state.
- Real-money and Topstep Combine submit, modify, cancel, arm and enablement need explicit just-in-time operator GO. Paper submits are free. Emergency-off and flatten behave identically and default ON.
- Paper and live are one code path. Execution changes are never validated only on paper.
- R2/R3 land via draft PR plus a cross-family review gate at the exact head. Never self-merge, never direct-push R2/R3. Reviewer family ≠ author family. R3 keeps two families.
- Tests drive the real path including the failure branch. Never skip or disable tests to go green (quarantine ≠ skip).
- CDP SUBMIT_UNCONFIRMED is never blindly retried or replaced. Collect is read-only.
- Atomic writes. SQLite WAL is write master. No secrets in packets or commits. Live bot runs from the main checkout. Ports contract (6175/6101/6102/6103).
- Operator-only authority for rule changes, policy promotion and live config. Sessions never author or relax operator rules.

---

## 7. New solutions from research

| Solution | Pain addressed | Fit | Effort | Sources |
|---|---|---|---|---|
| Native subagent model forcing (`CLAUDE_CODE_SUBAGENT_MODEL` + `_FORCE=1`) and `permissions.deny Agent(name)` in the **supervisor profile only**, replacing most of `claude_worker_guard.py`. Risk: FORCE applies to every subagent and overrides deliberate Opus subagents the roster allows (e.g. R3 root cause), so those need a separate session or an allowlisting guard. Forks and `model: inherit` skills still run on the main model. | Opus coordinator burn; unenforced "never Opus" | High (with caveat) | S | code.claude.com/docs/en/sub-agents.md |
| PreToolUse with `if` permission-rule filter, `permissionDecision`, `updatedInput`; SubagentStop blocking without a receipt path; HTTP hooks with `onFailure:block` | Prose bans; lost coordinator reports | High | S | code.claude.com/docs/en/hooks |
| Lane router exposed as a stdio MCP server (pattern: `conductor_mcp.py`), with the brief passed inline and a typed receipt | Missing brief, "dies silently", shell child leaks | High | M | code.claude.com/docs/en/agents.md ("expose it to Claude as an MCP server") |
| GitHub-native queueing via one dedicated runner label, plus `gh pr merge --auto --match-head-commit` once a review status exists (plan permitting) | Scratchpad merge chains, orphans, xdist crashes | High (auto-merge depends on plan) | S | repo API (`allow_auto_merge:false`, owner User, private); github.blog merge-queue GA note (merge queue needs an org); dev.to concurrency-trap |
| Durable job ledger (extend `lane_state`, SQLite WAL), owned by EC; DBOS only if a library is wanted | Unprocessed results; state re-derived from prose | High | M | docs.dbos.dev; CLAUDE.md WAL rule |
| Official API lanes behind R2/R3 gates (OpenRouter Kimi K3 about $2.60/$13 per M, GLM 5.3 about $1.40/$4.40 per M; Gemini API/Vertex), about $0.05-0.10 per review, daily cap | Daily CDP breakage; identity unverified; ToS/ban risk | High (operator cost decision) | M | openrouter.ai/compare; OpenAI ToU (no programmatic output extraction); Perplexity AUP (secondary); Antigravity account restrictions (official X post) |
| Normalize CLI lanes on headless NDJSON plus a final result plus a git diff readback (`agy -p --output-format stream-json`, `cursor-agent -p --output-format stream-json`, `codex exec --json --output-schema`, `opencode serve`); skip ACP for now | Ambiguous outcomes (no-op exit 0, false unconfirmed) | Medium | M | antigravity.google/docs/cli/headless; docs.cursor.com output-format; opencode.ai/docs/server; zed.dev external agents |
| `/doctor prompt-audit` plus a CLAUDE.md size under 200 lines, softened imperative language, motivation for rules | Contradictions picked arbitrarily; over-triggering on MUST | High | S | code.claude.com/docs/en/memory.md; Claude prompting best practices |
| SessionStart `additionalContext` "lanes now" table (re-runs on resume) | Stale quota prose; probing burns turns | High | S | code.claude.com/docs/en/hooks |
| Monitor tool on the receipts dir; channels (research preview) for CI or dispatch pushes; Desktop or cloud scheduled tasks for durable steps | Polling, watchers lost on `--resume` (background Bash is not restarted) | Medium | M | code.claude.com/docs/en/scheduled-tasks.md, channels.md, routines.md |
| Flake quarantine with expiry (pytest-rerunfailures 16.2 `only_rerun`, `--fail-on-flaky`), with no skip of R3 contract tests | Blind reruns on the single CI lane | High | S | pypi pytest-rerunfailures 16.2 |
| Personal plugin marketplace (hooks, skills, commands, workflows) with pinned refs; verify via the stream-json init event | Three sync scripts; unprovable live state | Medium | M | code.claude.com/docs/en/plugins/org, workflows.md |
| Machine-readable `supervisor_state.json` plus dynamic workflows for Claude-side mechanical verification fan-out (tests plus diff stat only) | First hour of each master spent on archaeology | Medium | S | Claude prompting best practices (state in structured files and git); workflows.md |

---

## 8. Roadmap

Legend: **[H]** = implementable_here (R0/R1, can be changed and tested in this container). Owner: **op** = operator, **sup** = supervisor session, **lane** = delegated lane (via draft PR plus cross-family review).

### Now (this week; ordering matters)

**Interim operating rule until N1 lands (all masters, effective immediately):** do not run `dispatch.py lane drain` and do not re-enable `TsignalLanePoll`. Use `lane status` only. Ignore the 11-03 handoff instruction (`2026-11-03_supervisor_handoff.md:75`, "Run `dispatch.py lane drain` … before trusting the queue"), because under D-2 one drain hard-resets every queued impl worktree to its stale base. Process `held` impl jobs by hand: inspect `git diff`, run targeted tests (RTH: targeted only, live rule 10), commit or abandon.

| # | Item | R | Owner | DoD | Depends | [H] |
|---|---|---|---|---|---|---|
| N1 | **Router safety pack.** Drain HEAD/dirty guard (D-2). One claim per drain, lease, dead-owner reclaim, `max_requeues`/TTL→`expired`, `lane expire\|cancel` (D-3). Marker scan only for `transport:"cdp"` rows (D-1). Preflight reasons (D-5). | R1/R2 | lane + sup review | Regression tests: moved-HEAD drain makes no reset and the job is `held stale_base`; RECOVERY_REQUIRED in CLI stderr gives DONE while a CDP row still halts; a killed drain re-queues; a refusal carries a reason. The router suite is green. | none | **[H]** `apps-shared/dispatch/lane_router.py`, `lane_state.py`, `lanes.json`, `test_lane_router.py`, `tests/test_lane_router_hazards.py` |
| N2 | **Honest health.** Non-zero exit counts toward flaky with backoff; exists-probe cannot heal ui_drift/flaky/permission; parse `coderpx.result.v1 failure_class`; prune unknown rows; `lane status` shows held/running/expired with ages, poll heartbeat age and an "UP but cf≥N" warning (D-4); `lane status --scorecard` from receipts: DONE/FAILED/QUEUED per lane over 7 days plus the dominant `failure_class` (M-8) | R1 | lane | Live-shaped fixture (cf=145 UP) gives DOWN/backoff; `CDPLaneAcquireError` maps to a typed class; the scorecard on a fixture of the live receipts shows `perplexity_grok` with 0 DONE and `CDPLaneAcquireError` dominant | none | **[H]** same files |
| N3 | **Queue triage, then re-enable the poll.** `lane expire --older-than 24h` on the 1,645 files, **excluding `held` jobs** (custody: reconciled on the same attempt, never retried or replaced, `roster:67`); set poll budget > adapter timeout + margin (or detached drain); write `lane_poll_heartbeat.json`; re-enable `TsignalLanePoll` only after the operator answers Q5 | R1 | op (task), sup | After triage: 0 `queued` jobs older than 24 h; every `held` job (2 live today) is untouched and still listed by `lane status`; each expired job has an `expired` receipt; heartbeat <20 min shown at SessionStart; 24 h after re-enable the poll log shows 0 worktree resets and 0 jobs left `running` | **N1, N2, Q5** | partly **[H]** (`dotclaude-ecosystem/scripts/lane_poll_scheduled.ps1`); enabling the task is op |
| N4 | **CDP fleet ownership.** Decide the owner (Q5). Add `chrome_gemini` to `SUPPORTED_ROLES` plus a `coderpx_gemini` row; periodic re-recover with backoff that skips held roles; drop `chrome_x` from the ensure set | R1 | op + lane | All 3 ports LISTEN after reboot; recovery events logged; an R3 review completes on a CDP lane with reviewer family ≠ author family (and a second family for R3) | Q5 | EC part **[H]** (`EcosystemControl/scripts/coderpx_lane_supervisor.py`, `services_extra.yaml`, `tests/test_coderpx_service.py`); WatchF part not |
| N5 | **Contract truth pass (R0).** Rewrite the enforcement header to match reality; authorship vs verification (R-3, core.md:79); delete roster facts block plus Precedence; fix `shared.md:5` pointer and re-sync; put `model-launch-rules.md` and `model_launch_guard.py` under dotclaude plus a manifest entry; install the contract with a hash, or drop the home-path precedence (E-6) | R0/R1 | sup + op ratify | sync tests pass; `hooks_install status` lists the guard as managed; the injected contract sha equals the template | Q1, Q2 | **[H]** `dotclaude-ecosystem/templates/supervisor-contract.md`, `agent-rules/core.md`, `agent-rules/refs/supervisor-model-roster.md`, `agent-rules/repos/tsignal-5.0/shared.md`, `templates/hooks.manifest.json`, `scripts/session_router.py` |
| N6 | **Identity gate.** Neutral MODEL_IDENTITY; `gates_merge=false` plus `MODEL_UNVERIFIED` without readback (C-2) | R1 | lane | Real-path test: answered=Best gives gates_merge false | none | **[H]** `lane_router.py`, `test_lane_router.py:4347` |
| N7 | **Codex credit pre-flight** in the router for every codex lane; exit 75 gives `weekly_limit` DOWN (E-2) | R1 | lane | Fake rollout at 100% gives DOWN with no exec | none | **[H]** `lane_router.py`, `dotclaude-ecosystem/scripts/codex_limit_guard.py` |
| N8 | **Conductor max-hold fix, keeping the 15-min release (live rule 2):** either (a) pass the remaining budget from Conductor activation down as `{driver_timeout_s}` so every CDP driver stops before 900 s, or (b) make eviction kill the owner's process tree first, then release (C-5) | R1 (R2 for CCTV contract) | lane | Test: at 900 s the owner tree is dead before the slot is reused; no 5th submit starts while a window is answering | none | **[H]** `dotclaude-ecosystem/scripts/conductor_resources.py` + tests (psutil needed) |
| N9 | **CI quick wins (draft PR):** move `/ci full` to its own workflow (L-3); merge evidence via check-runs from any event, main push no cancel (L-4); fix the misleading `ci.yml` comment; "unrecognized command" reply (L-10) | R1 | lane + cross-family review | actionlint clean; a replay comment does not cancel the targeted run; the next merge after a "cancelled"-but-green PR runs no main suite | none | **[H]** `Tsignal/.github/workflows/{ci,draft-ci}.yml` (behaviour is verified on GitHub) |
| N10 | **Test hygiene:** fix the red hazards test; POSIX `start_new_session`; autouse fixture that forbids the real `~/.claude/state` (the `lane_timeout_test` leak); add `dispatch/`, `coderpx/`, `cdp_fleet/` to `hybrid-ci.yml`; fix `test_coderpx_protocol.py` | R1 | lane | Full lane suite runs to a summary on Linux; CI gate is required on `dispatch/**` | N1 | **[H]** `apps-shared/dispatch/*test*`, `.github/workflows/hybrid-ci.yml`, `coderpx/test_coderpx_protocol.py` |
| N11 | **Doctor additions:** `lanes` (unacked, held, expired, poll heartbeat, UP-with-failures), live hooks vs manifest, contract sha, per-store % of ceiling; recent-handoff selection fix (M-5) | R1 | lane | Doctor prints one line on a live-shaped fixture; >200-handoff test passes | N2 | **[H]** `dotclaude-ecosystem/scripts/ecosystem_doctor.py`, `session_router.py`, tests |

### Next 2 weeks

| # | Item | R | Owner | DoD | Depends | [H] |
|---|---|---|---|---|---|---|
| X1 | `lanes.json` `policy` + `operator_overrides` (expiring) + `operator_rules.jsonl` + `rules add`; render the contract lines and roster table; MODEL_ROSTER cross-check; past-date lint (warn) | R1 | lane + op ratify | Drift test fails on a hand edit; SessionStart shows active overrides | N5, Q1 | **[H]** apps-shared `dispatch/`, dotclaude `agent-rules/`, `scripts/` |
| X2 | `lane hold\|release\|clear\|ack\|inbox\|--from-job`; `--risk` required; `--detach` + `lane wait`; job record for every run (M-2 R1 part) | R1 | lane | Round-trip tests; operator-hold release needs the op path; a direct DONE run shows in `lane inbox` until acked | N1 | **[H]** |
| X2b | Router `wip(lane): <job> verify=<pass\|fail>` commit on the **lane branch only**, after its own `verify_cmd`, explicit pathspecs (M-2 R2 part; reverses the "Do NOT commit" preamble, `lane_router.py:1913`) | **R2** | lane via draft PR + cross-family review, op | Plan first; tests: commit lands only on the lane branch, never main or the operator checkout; failed verify is recorded in the message and the result is not merge-gating | X2 | **[H]** code + tests, but landing needs the R2 gate |
| X3 | Repo-tracked merge chain / `land` with pidfile, `--takeover`, lease-pause, SHA-bound `review/cross-family` status, post-merge audit | R1→R2 | lane | Orphan test: lease lapse pauses the chain; merge refused without a status at head | N9 | **[H]** `apps-shared/ci/`, `dotclaude-ecosystem/scripts/` |
| X4 | Single `tsignal-full` runner label; `proof_labels` vs `local_labels`; fix #2653 before merging; `local_only` count in the summary; R3 forces LOCAL | R1 | op (runner) + lane | Two ready PRs queue FIFO; no concurrent full suites | Q4 | policy/schema **[H]** (`apps-shared/ci/hybrid_router.py`, `hybrid-policy.json`); runner op |
| X5 | Constitution plus role cards; worker contract by `owner_runtime`/lane marker; Conductor mechanics and landing copies moved to skills; supervisor card carries the R-3 turn DoD (process returned output this turn; queue duty: report held/expired/DONE-unacked each turn) and the reviewer card the review-verdict DoD (C-8); fixed handoff template with no "binding rules" section (INC-12); `/doctor prompt-audit` and skill-creator benchmark before/after the cut | R0 | sup + lane | Global kernel (rendered `~/.claude/CLAUDE.md`) ≤12 KB; each role card ≤1.5 KB; a Codex SessionStart gets the worker card; safety invariants unchanged verbatim; benchmark shows no drop in trigger accuracy or task success | X1 | **[H]** dotclaude `agent-rules/`, `scripts/session_router.py`, `sync_agent_rules.py` |
| X6 | Per-lane `max_prompt_chars`, `cdp_role`, `transport`, `{driver_timeout_s}`; Argon capacity 1; astra_work/sol_work slot check | R1 | lane | Oversize refused pre-submit; same-role admission test | N1 | **[H]** |
| X7 | Non-scrape reviewer on every R3 gate: if the operator approves (Q3), one API lane under a spend guard; otherwise move kimi_cli/glm_zai into the first two review positions when their quota allows. **Not agy** (live rule 3: AGY = implementation only; agy is also impl position 1, so it would be same-family for its own diffs). Add `transport_class` and the "one non-scrape lane per R3 set" rule | R1/R2 | lane + op | An R3 review completes with the CDP fleet down, with reviewer family ≠ author family and two families for R3; the receipt names the lane, model and `identity_evidence` | Q3 | registry **[H]** |
| X8 | Retention: lane_receipts reaper (never held/unconsumed), Conductor enforce at 80%, verdict consumption; squash-aware `git_hygiene` (L-9); fix TsignalGitHygiene termination | R1 | lane | `lane_receipts` < 300 MB (from 783 MB) with 0 `held` or unconsumed jobs deleted; Conductor receipts < 80% of the 256 MB ceiling with retention in enforce mode; squash-merged worktrees classified "landed" on a fixture; `TsignalGitHygiene` last_result 0 | N11 | **[H]** `apps-shared/dispatch/lane_state.py`, `dotclaude-ecosystem/scripts/{git_hygiene,state_reaper}.py` |
| X9 | S2 decision: land the Agent guard (or native env knobs) plus a log-only direct-CLI deny; KNOWN_TOOLS shape check; close the read/edit bans | R1 | op + lane | Guard installed via manifest; doctor shows it | Q2 | **[H]** `dotclaude-ecosystem/scripts/hooks_install.py` + tests |
| X10 | pure_signal / UI settings override split (R3 plan with rollback, round-trip restart test, runtime-config readback) | R3 | lane + op GO | checkout_sync unattended after a merge; override survives restart | none | no (R3) |
| X11 | Findings ledger plus round counter `needs_plan` in the review preamble; review-verdict DoD enforced by the router (MODEL + `identity_evidence` + SHIP\|SHIP-WITH-FIXES\|BLOCK + `file:line` per blocker, else `verdict_malformed`); flake ledger (after X4/N9) | R0/R1 | lane | Round 4 returns needs_plan; a verdict missing `file:line` for a BLOCK is `verdict_malformed` and does not gate; unlisted retry pass fails with a "new flake" message | X4 | **[H]** |
| X12 | Single installer owner for commands; one coderpxG skill source (`claude-config/commands/coderpxg.md` currently points at the `apps-shared/design/visions/…` copy, which differs from `dotclaude-ecosystem/skills/coderpxG/SKILL.md`); claude-config CLAUDE.md as a visible pointer; `.clinerules` sync target; refs `Last-verified` | R0/R1 | op ruling + lane | No two installers share a target (test); exactly one coderpxG SKILL.md is referenced | op | **[H]** |

### Later

| # | Item | R | Owner | DoD | Depends | [H] |
|---|---|---|---|---|---|---|
| Z1 | Submit/collect split for CDP: `SUBMITTED_AWAITING` (conversation URL + nonce recorded at submit), read-only `lane collect` (C-3) | R2 | lane (router) + WatchF driver read-back; draft PR + cross-family review | Round-trip test held → collect → done on the recorded conversation; refusal-branch test: an unprovable conversation is refused and **no submit** happens; the slot is still released at ≤15 min | X6, WatchF harvest mode | router part **[H]**, WatchF part no |
| Z2 | WatchF canary (picker enumeration, label readback, nonce submit only at fleet start / after DOWN) plus sanitized DOM fixtures (C-7) | R1 | lane (WatchF) | Canary writes `cdp_lane_health.json` with typed class + DOM hash; router `health_file{max_age_s}` probe heals only the tested reason; Playwright contract tests for each selector family | N2, N4 | no (WatchF) |
| Z3 | `run_job` phase refactor (D-10); router-owned per-job worktrees (`git worktree add <state>/wt/<job>`) | R1 / R2 | lane | Full lane suite green before/after; no shared worktree is ever reset by the router | N1, N10, X6 | **[H]** |
| Z4 | Lane ledger in SQLite WAL + MCP `lane_*` tool (mandatory `failure_reason`); Monitor/channel push to masters; generated handoff with truthdeck verification (M-3, M-4) | R2 | lane + op | Dual-read migration test; a brief passed inline cannot produce `brief_missing`; generated handoff passes `truthdeck verify-handoff` | X2, X2b | **[H]** (code), migration op |
| Z5 | Plugin marketplace for hooks/skills/commands with pinned refs; retire legacy sync scripts | R1 | lane + op | stream-json init event lists the plugin; no hook runs twice; `install.ps1 -Check` and doctor clean | X9, X12 | partly **[H]** |
| Z6 | program_* retirement (after operator confirms nothing launches `program_entry`); Conductor resource CLI as a versioned contract with conformance fixtures (O-1, O-3) | R1 / R2 | lane + op | Installer manifest and `roster_installer_ci` updated in the same PR; CCTV conformance fixtures pass | op confirmation | **[H]** |
| Z7 | JOB_COMPLETED runner reaper scoped to `_work` (L-8); GitHub Pro / branch protection per Q4 | R1 / op | op (runner, plan) + lane | Reaper kills only processes under that instance's `_work`, kill ledger written, never matches the live bot; if Pro: `pytest` and `review/cross-family` are required checks | Q4 | script **[H]**, install op |

---

## 9. Open questions for the operator

1. **Routing authority, lane-rule ratification, and RTH testing.**
   - (a) Should `lanes.json` (policy + registry + expiring overrides) be the single binding source, with contract and roster text generated from it?
   - (b) Do you confirm, verbatim, these **lane/routing** rules for the repo: 10-30 (Sonnet as R2/R3 cross-family reviewer only when the non-GPT lanes are down and the implementer is not Claude); 11-03 (Codex Astra allowed at high for hard tasks); and the live `model-launch-rules.md` rule 2 (ChatGPT and Perplexity CDP 4 slots each, every slot released ≤15 min), which I propose to move into `agent-rules/refs/` unchanged? (The 11-04 "no self-imposed entry lockouts" memory is a trading-decision rule and stays in your live-config process; it is not part of this question.)
   - (c) Live rule 10 "No heavy local tests during RTH" conflicts with `ci.yml:200` ("CI runs during RTH on the trading workstation", CPU-masked, your 2026-08-14 decision) and with the 11-03 rule 5 broad `-n 6` suite before `gh pr ready`. Does the CPU-masked CI count as compliant, or must full suites go hosted (or wait until after RTH) during market hours? Until you rule, this audit limits supervisor verify duties to targeted tests during RTH.
2. **Supervisor reading.** Should the supervisor be allowed to read diffs, receipts and test output under a budget (authorship stays banned), replacing the S2 read ban? Should S2 then land only the Agent model guard plus a log-only direct-CLI deny, with the rest of #141 closed?
3. **Non-scrape reviewer and long answers.** Pay for one API-backed reviewer family (about $0.05-0.10 per review, daily cap of your choice), or keep subscriptions only and accept that R3 gates QUEUE whenever the CDP fleet and the non-CDP CLI lanes are down (as they were today)? Separately: should GPT-6 Pro / Argon R3 reviews ever hold a CDP slot longer than 15 min, or does the 15-min release stay absolute, with long answers finished only through `lane collect` (Z1)? The audit assumes the latter.
4. **Merge gate.** Buy GitHub Pro for Tsignal (branch protection, required `pytest` and `review/cross-family` checks, auto-merge), or make the client-side landing queue the sole merger with a post-merge audit? And, as a proposal only (not an existing invariant): should the landing queue refuse R3 merges during RTH without a standing GO? Contract hard rule 5 gates restarts, not merges, and the bot only picks up main on restart, so the answer can reasonably be no.
5. **Disabled scheduled tasks and fleet ownership.** Did you disable `TsignalLanePoll` (10-27) and `WatchF-CDPFleetSupervisor` (08-06) on purpose? The poll stays off until N1 lands either way (D-2), but N3 re-enables it only with your yes. For the CDP fleet: re-enable the WatchF supervisor, or move standing holds and re-recovery for all three Chrome roles into EcosystemControl? Only one of them should own it.
