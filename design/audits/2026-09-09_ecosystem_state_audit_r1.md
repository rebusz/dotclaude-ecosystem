---
title: Ecosystem state audit — errors, drift, hardening
date: 2026-09-09
risk: R1
status: draft
head: b71fe76
scope: dotclaude-ecosystem (repo + installed runtime state)
---

# Ecosystem state audit — 2026-09-09

**Verdict: the control plane is well designed and badly delivered.** Nearly every
invariant this repo cares about has correct code somewhere and a detector that
fires. What is missing is *delivery*: the detectors report into files nobody
reads, the installer never took ownership of the thing it installs, and the
subsystem carrying the most authority carries the least CI.

Method: five parallel read-only audit lanes (conductor, installer/hooks, policy
prose, security, CI/coverage) plus first-hand runtime measurement of the live
`~/.claude` state. Evidence is `CONFIRMED` (file:line or a reproduced
observation) or `SUSPECTED`. Head under audit `b71fe76` = `origin/main`.

---

## Layer 0 — plan/vision collision (fallback)

`plan_context_loader.py` **could not run** for this repo (finding P1-3), so the
collision check was done by hand over `design/plans/` (14 plans) and
`IDEA_BOX.md`. There is no `design/visions/` directory in this repo.

| Existing plan | Status | Collision |
|---|---|---|
| `2026-08-04_installer_managed_hook_block_r2.md` | shipped | **Wrong.** The code shipped; the managed block was never installed. Amend, do not create a new plan. |
| `2026-07-25_sweep_abandoned_work_r1.md` | deferred | Directly owns the worktree/branch sprawl (P2-1). Promote. |
| `2026-08-27_cdp_admission_pool_split_r2.md` | active-continuation | Owns C1/C6 (pool key validation). Amend. |
| `2026-07-27_cross_runtime_session_lifecycle_adapters_r1.md` | active | Owns the doctor blind spots (B-F10). Amend. |

---

## Layer 1 — surface state

| Measure | Value | Note |
|---|---|---|
| `main` test state | **RED** since 2026-09-07 | 2 failures, neither covered by CI |
| Scripts under any CI | 27 of 72 (37.5%) | Conductor (~9k lines, 10 test files): **zero** CI |
| Test files no workflow runs | 25 of 53 (47%) | |
| `ruff check scripts` | 42 violations, exit 1 | 25 of them in Conductor files |
| Repo config (`pyproject`/`ruff.toml`/`pytest.ini`/`conftest.py`) | **none** | scope defined only by hand-written YAML arg lists |
| Local Python | 3.14.3 | CI pins 3.12 — local green ≠ CI green |
| Worktrees, this repo | 26 (12 older than 30 days) | |
| Worktrees, Tsignal 5.0 | **504**, 1361 local branches | growing ~25/day; janitor ALARM daily since June |
| `~/.claude` on disk | 4.5 GB live **+ 16.9 GB of installer backups** | `skills/gstack` 1.7 GB, `projects` 1.4 GB, `state` 384 MB |
| Hook errors logged | 2,035 lines, 50–150/day, trend up | |

The two `main` failures are `test_implementation_review_packet.py::test_master_agent_owns_risk_aware_review_routing`
and `test_ponytail_on_demand.py::test_master_agent_architect_decides_without_operator_flag`.
Both broke when PR #112 (`0ea895d`, titled "**Draft:** v2 prompt roles…")
rewrote `skills/master-agent/SKILL.md`. Neither test file appears in any
workflow's `paths:` or `run:` list, so nothing could have caught it — and the
`if: draft == false` gate means a PR merged while titled Draft ran no CI at all.

**P1-22 — the `ready_for_review` transition runs nothing, and a skipped job
reads as a passing one.** Observed directly on PR #114 while landing Slices A
and B, and narrowed by a subsequent push:

| Event | Result |
|---|---|
| `synchronize` while the PR is a **draft** | job `completed/skipped` |
| `ready_for_review` (`gh pr ready`) | **no run created at all**, despite `ready_for_review` being in the workflow's `types:` |
| `synchronize` after the PR is **ready** | job runs for real — and immediately caught a genuine bug |

So the gate itself works; the hole is the transition. A PR taken from draft to
ready and merged without a further push carries only `completed/skipped` checks,
`mergeStateStatus: CLEAN`, and **zero executed tests** — which is exactly the
operator's documented batching policy (keep it draft, `gh pr ready` once).
Same defect class as the rest of this audit: the signal is correct (`skipped`
really is what happened) and nothing consumes the difference between "skipped"
and "passed".

The value of closing it is not theoretical. The first real run on this branch
failed on something no local run could reproduce: the GitHub runner's TEMP is an
8.3 short path (`C:/Users/RUNNER~1/…`), which broke a string comparison of two
spellings of the same directory in the new ownership record. Slice C owns the
gate; the bug itself is fixed in `ca05725`.

**Cause found and verified (Slice C, PR #115).** It was the `paths:` filter.
GitHub evaluates it on `ready_for_review` in a way that produced no run at all,
so the transition the operator's batching policy depends on was the one event
that never fired. Removing the filter — done anyway, because it was also the
mechanism of the 45-script blind spot — fixes it. Measured on #115 by opening
the PR as a draft and marking it ready with no further push:

| Moment | Runs on the branch |
|---|---|
| draft, after the initial push | 1 (`completed/skipped`) |
| immediately after `gh pr ready` | **2** — the new one `in_progress`, not skipped |

One filter removal closes both P1-22 and P1-6. That is the whole finding: the
same mechanism that hid 45 scripts from CI also silenced the gate that would
have reported it.

---

## Layer 2 — data flow

### 2a. Hook wiring: the live box is double-wired to a stale worktree

`~/.claude/settings.json` contains **20 hook handlers where the manifest defines 10**.
Every managed hook is registered twice: once against
`D:/dotclaude/dotclaude-ecosystem/scripts/` and once against
`D:/APPS/_worktrees/dotclaude-ecosystem-unified-fwf-20260831/scripts/`.

The system's own detector agrees:

```
$ python scripts/hooks_install.py status        # exit 3
overall: MISSING
  [MISSING  ] SessionStart/.../session_router.py  -- managed block absent in settings.json
  ... (all 10)
  [COLLISION] SessionStart: py ".../dotclaude-ecosystem/scripts/session_router.py"
  [COLLISION] SessionStart: py ".../_worktrees/dotclaude-ecosystem-unified-fwf-20260831/scripts/session_router.py"
  ... (20 total)
```

`git_hygiene` has been printing `! MANAGED HOOKS: ecosystem hook block is COLLISION`
every day into `~/.claude/state/git_hygiene/report-latest_*.txt`. Nothing reads it.

Consequences, all live:

1. Two copies of every hook run per event — one from the operator's checkout
   (on branch `claude/conductor-gui-tsignal`, **19 commits behind main, 8 files dirty**,
   including `conductor_resources.py` and `autocommit_design_docs.py`), one frozen
   at `1b0a908`. Two code generations write the same state files concurrently.
2. `autocommit_design_docs.py` runs twice per `Write`/`Edit` → two `git add`/
   `commit`/`push` racing on `index.lock`.
3. `plan_keyword_detector.py` injects the steering block twice — reproduced in
   this very session's transcript.
4. `session_router.py` calls the write-once binding twice → 164 logged
   `LIFECYCLE_BINDING_MISMATCH`.

This is exactly the failure `IDEA_BOX.md` predicted three times and deferred
three times: *"modules present, hooks absent, operator believes it is live."*
The `2026-08-04_installer_managed_hook_block_r2.md` plan is marked **shipped**;
the managed block is **absent**.

### 2b. The plan lifecycle is broken at both ends

`scripts/plan_context_loader.py:32,49-55`:

```python
BASE = Path("d:/APPS")
def _detect_repo(cwd):
    for parent in [cwd, *cwd.parents]:
        if parent.parent.resolve() == BASE.resolve():
            return parent
    return None
```

**PRE-step.** A repo is only recognised when its parent is *exactly* `d:/APPS`. Measured:

| cwd | result |
|---|---|
| `D:/APPS/Tsignal 5.0` | detected |
| `D:/APPS/WatchF` | detected |
| `D:/APPS/_worktrees/dom-h0-ecosystem-20260907` | detected **as its own repo** (wrong slug → empty vision/IDEA_BOX lookup) |
| `D:/dotclaude/dotclaude-ecosystem` | **not detected** |
| `.claude/worktrees/<any>` | **not detected** |

Exit code is 0 in every case. So the headline feature of this repo — the
mandatory PRE-step for ARCHITECT / IMPLEMENT / EXECUTOR / AUTOPLAN — is dead for
the ecosystem repo itself and for **every agent working in a worktree**, which
the global rules name as the normal working mode. It fails open and silently.

**POST-step.** Reproduced in this session: `plan_context_updater --plan <p>` printed
`PLANS.md regen: FAIL — plan_catalog.py timed out after 60 seconds` and exited **0**.
The catalog it maintains has grown to 20.7 MB / 113,308 lines and no longer
regenerates inside its own timeout. The SIGKILL lands between `tmp.write_text()`
and `os.replace()` at `plan_catalog.py:274-276`, which has no `finally` — that is
where the six orphaned `PLANS.md.tmp.<pid>` files (27.8 MB, oldest 2026-05-18)
come from. Both ends of the repo's headline feature are down, and both fail open.

### 2c. Verdict delivery is dead; state grows to the 90-day bound

`~/.claude/state` holds **1,601 `session_verdict_*.json`, of which 0 have
`consumed_at` set** — none, since the oldest on 2026-07-26. Consumption happens
only in `curator_claims.py:1114`, reachable only when the operator manually runs
`/curator`. `state_reaper._candidate_window` therefore falls through to
`VERDICT_OUTER_BOUND_DAYS = 90` for every file.

Compounding it: `_candidate_window` (`state_reaper.py:183-230`) `os.scandir`s the
whole state dir and **reads every verdict JSON** before the deletion phase's
`time_budget_s = 0.15` deadline applies. Measured: 0.24 s warm just to read the
1,601 files. The scan alone exceeds the entire deletion budget, so each hook
invocation pays full O(N) I/O and deletes almost nothing. N grows.

### 2d. Policy source is split-brain; the generated block is at 99.6% of its guard

| Statement | Source A | Source B |
|---|---|---|
| Gemini pin | `agent-rules/core.md:28` → `3.7` | `core.md:30` + `overlays/codex-global.md` + `skills/master-agent/SKILL.md` → `3.8` |
| Codex CLI as a lane | `core.md:28` "never a workflow lane" | `core.md:30` GPT Sidecar 2 local workers |
| Order-path access | `core.md:18` "there is no forbidden code" | `skills/whatnext/SKILL.md:57`, `overlays/codex-global.md:30` "never touch the order path" |
| R2/R3 review topology | `master-agent/SKILL.md` unified audit | `docs/OPERATOR_PLAYBOOK.md:85` "matrix" |

`sync_agent_rules.py --write` currently **fails closed for all four global
targets**: the rendered `~/.claude/CLAUDE.md` is 163 lines / 16,581 bytes against
a `162 / 16,000` guard. The installed file sits at 162/162 lines and
15,943/16,000 bytes — 99.6% full. One added bullet froze the whole sync.

The repo's v2 `skills/master-agent/SKILL.md` (7,161 B) was merged but never
installed; `~/.claude/skills/master-agent/SKILL.md` is still the v1 monolith
(32,900 B) whose routing table is duplicated inside itself with two different
values. `install.ps1 -Check` reports **53 drift items**, 22 of them missing
`master-agent/references/**` files.

---

## Layer 3 — invariant verification

### P1 — ship-blocking

| # | Finding | Evidence |
|---|---|---|
| P1-1 | Managed hook block absent + 20 collisions; every hook double-fires, half from a stale Aug-31 worktree | CONFIRMED `hooks_install.py status` exit 3; `~/.claude/settings.json`; reproduced in this transcript |
| P1-2 | `autocommit_design_docs.py:283` commits with **no pathspec** — sweeps whatever is staged into a `docs: auto-backup` commit and pushes it. Armed now: the primary checkout has `agent-rules/core.md`, `overlays/claude-global.md`, `overlays/codex-global.md` staged | CONFIRMED file:line + `git diff --cached` |
| P1-3 | Same hook has no branch guard on the commit path: `PROTECTED_BRANCHES` (`:50`) is consulted only by `_can_amend` (`:79`), so on `main` it commits and `git push origin HEAD` | CONFIRMED `:50,79,283-286`; lane repro pushed to a local `origin/main` |
| P1-4 | `plan_context_loader` cannot detect any repo outside `d:/APPS/<name>`; PRE-step is a silent no-op for this repo and all worktrees | CONFIRMED `:32,49-55` + measured table above |
| P1-5 | `main` is RED (2 failures) since `0ea895d`; neither test is in any workflow | CONFIRMED pytest run + `paths:` inspection |
| P1-6 | Conductor (~9k lines, 10 test files, the authority layer) has no CI workflow at all | CONFIRMED `.github/workflows/*` |
| P1-7 | Arbitrary `--resource-key` mints a private capacity-1 pool → two heavy pytest runs concurrently, bypassing capacity-one `host:heavy` | CONFIRMED (runtime) `conductor_resources.py:99,271-277` |
| P1-8 | Operator attestation for `resource-recover` is grantable by a bare argv flag and by an inbox file; `envelope_source` is a dead parameter | CONFIRMED (runtime) `conductor_commands.py:36-46`, `conductorctl.py:120-124`, `conductord.py:50-66` |
| P1-9 | `acquire_leader_lock` has no `BEGIN IMMEDIATE` and no conditional UPDATE — 7 of 8 concurrent callers were granted the "single writer" lock | CONFIRMED (runtime) `conductor_store.py:1431-1490` |
| P1-10 | Host-resource leases are never reconciled automatically; a crashed heavy consumer wedges `host:heavy` forever while `doctor` reports PASS | CONFIRMED `conductord.py:70-79`, `conductor_commands.py:387-424` |
| P1-11 | `design/workflow_os_revisit_triggers.json` supplies **arbitrary argv** to `subprocess.run` on the daily unattended `TsignalGitHygiene` task | CONFIRMED `idea_digest.py:234-239` + `git_hygiene_scheduled.ps1:54-55` |
| P1-12 | `UserPromptSubmit` hook injects unescaped commit subjects / vision text from 5 repos into the model turn, followed by an `AI:` imperative. A commit subject containing the closing tag breaks the trust delimiter | CONFIRMED `plan_keyword_detector.py:147-164`, `steer_context.py:291,310,337,367` |
| P1-13 | `--validation` / `--validation-file` bypasses the review packet's fail-closed secret rejection entirely | CONFIRMED `implementation_review_packet.py:137,159,210,263` |
| P1-14 | Hook stdin decodes as **cp1252**; every non-ASCII trigger silently never fires. `nowy moduł` → `nowy moduÅ‚`, regex misses | CONFIRMED reproduced: `sys.stdin.encoding = cp1252`, match `True`→`False` |
| P1-15 | `install.ps1` ignores `hooks_install.py`'s exit code and prints "Install complete" on total failure (`$ErrorActionPreference` does not trap native exit codes) | CONFIRMED `install/install.ps1:229-231` |
| P1-16 | Installer clones `~/.claude` wholesale on **every** run, no rotation, no exclusions. **16.9 GB of stale backups against a 4.5 GB live home** (7.8 + 4.6 + 4.5 GB), each future run adds ~4.5 GB. All three trees carry `.credentials.json`, `.env` and `mcp-needs-auth-cache.json` in plaintext at default ACLs — and the July tree holds a *different* 471-byte credentials file, so a rotated token still sits on disk. The copy also runs for minutes before any install work, on the box running the live trading stack | CONFIRMED `install.ps1:151-154`; sizes measured; credential files verified present in all three |
| P1-17 | `agent-rules/core.md` contradicts itself on the Gemini pin and on the Codex-lane exclusion; `sync_agent_rules --write` is frozen (163/162 lines) so no target can be re-converged | CONFIRMED `core.md:28` vs `:30`; measured render |
| P1-18 | Repo v2 `master-agent` never installed; agents run the v1 monolith whose authoritative routing table is duplicated inside itself with divergent content | CONFIRMED 32,900 B vs 7,161 B; `install.ps1 -Check` 53 drift items |
| P1-19 | `skills/whatnext/SKILL.md:57` and `overlays/codex-global.md:30` forbid agents from touching the broker API / order path — the exact prohibition `core.md:18` names as the cause of the paper/live divergence | CONFIRMED both file:line |
| P1-20 | The plan-lifecycle **POST**-step is broken too: `plan_context_updater` reports `PLANS.md regen: FAIL — plan_catalog.py timed out after 60 seconds` and **still exits 0**. `~/.claude/PLANS.md` is 20.7 MB / 113k lines, so the catalog can no longer regenerate inside its own timeout. This is also the root cause of P2-2: the kill lands mid-write, orphaning `PLANS.md.tmp.<pid>` | CONFIRMED — reproduced in this audit session |
| P1-21 | 0 of 1,601 session verdicts ever consumed; state grows to the 90-day bound while the reaper pays O(N) JSON reads per hook fire against a 0.15 s budget | CONFIRMED measured + `state_reaper.py:183-230` |

### P2 — correctness / hardening

| # | Finding | Evidence |
|---|---|---|
| P2-1 | Worktree sprawl: 504 worktrees / 1361 branches on Tsignal (sampled one at 148 MB → order of tens of GB), 26 here with 12 stale >30d. `git_hygiene` ALARMs daily; `--apply` is manual and never run | CONFIRMED `git worktree list` + `summary.log` |
| P2-2 | Leaked atomic-write temp files: 6 × `~/.claude/PLANS.md.tmp.<pid>` (27.8 MB, oldest 2026-05-18) because `plan_catalog.py:274-276` has no `try/finally` cleanup; 6 more in `~/.claude/state` from hooks killed at their harness timeout mid-`atomic_write_bytes` | CONFIRMED file:line + files on disk |
| P2-3 | `append_hook_error` records only the **exception class name** — 514 bare `ValueError` and 271 `LIFECYCLE_FAILED ValueError` with no message, session id, or site. 18 distinct `raise ValueError` sites are indistinguishable. The error channel is unactionable by construction | CONFIRMED `session_state.py` `append_hook_error`; log histogram |

**P2-3, worked example (2026-09-09, while landing Slice B).** A probe that fed
`session_router.py` a SessionStart event reproduced `ROUTER_INVALID_INPUT
ValueError` — the single most common line in the operator's log. Recovering the
cause required patching `append_hook_error` at runtime to print the traceback,
because the log had discarded it. The site is
[`session_router.py:573`](../../scripts/session_router.py:573),
`raise ValueError("missing SessionStart fields")`, reached when `session_id`,
`cwd`, `source` or **`transcript_path`** is absent or the wrong type.

That is a lead, not a diagnosis: it cannot be confirmed against the 514
production entries precisely because the message was thrown away. Which is the
finding. One `f"{type(exc).__name__}: {exc}"` would have turned five hundred
unactionable lines into a one-line answer, and the fix belongs in Slice F.
| P2-4 | `append_hook_error` rewrites the **entire** log (read 128 KB → concat → fsync → replace) per line, inside a 2–10 s hook. That is what orphans the `.hook_errors.log.*.tmp` files at exactly full-log size | CONFIRMED same function |
| P2-5 | `LIFECYCLE_TRANSCRIPT_INCOMPLETE` is logged at error severity for a condition the adjacent comment calls expected — 722 of 2,035 lines (35%) is designed-in noise burying real errors | CONFIRMED `session_lifecycle.py:640-655` |
| P2-6 | `heartbeat()` never checks `expires_at_utc` — an expired lease is resurrected with a fresh window; `request()` does check, so the fail-closed boundary is asymmetric | CONFIRMED (runtime) `conductor_resources.py:447-475` |
| P2-7 | `cdp_tv` missing from the purpose↔pool alignment checks; a TV consumer admits into `cdp:gemini` and starves that lane | CONFIRMED (runtime) `conductor_resources.py:915-922` |
| P2-8 | Operator GO never expires and its `scope_digest_sha256` is never re-verified at claim or schedule time | CONFIRMED `conductor_model.py:342`, `conductor_scheduler.py:70-77` |
| P2-9 | WorkItem `heartbeat` accepts any lease id with any sequence — non-monotonic, unauthenticated, MCP-reachable | CONFIRMED `conductor_commands.py:246-266`, `conductor_store.py:1748-1770` |
| P2-10 | Unknown/newer store schema version is silently accepted instead of failing closed | CONFIRMED `conductor_store.py:1103-1107` |
| P2-11 | Conductor GUI executes an interpreter + script path read from a store-writable `install-manifest.json` | CONFIRMED `conductor_gui.py:67-82,1210-1219` |
| P2-12 | A `heartbeat` failure mid-run orphans the bounded pytest child instead of terminating it | CONFIRMED `conductor_resources.py:818-847` |
| P2-13 | Auto-reconcile writes a receipt row + file per poll (~86k/day at 1 s); `logs/` and `backups/` have no ceiling and are invisible to `storage_status` | CONFIRMED `conductord.py:70-79`, `conductor_store.py:48-52` |
| P2-14 | `sync_ecosystem_context.py:81` sanitizer misses `sk-proj-`, `sk-ant-`, `AIza`, JWT (the class excludes `-`), never fails closed, and the path auto-pushes to GitHub unattended | CONFIRMED regex executed against samples |
| P2-15 | Review-packet secret set misses every modern LLM key, `github_pat_`, `.envrc`, `id_rsa`, `*.keystore`, `credentials.txt`, connection strings, PEM blocks | CONFIRMED `implementation_review_packet.py:21-31` executed |
| P2-16 | Five independent, mutually inconsistent secret detectors; a fix to one leaves four wrong | CONFIRMED 5 file:line sets |
| P2-17 | `sync_agent_rules.py --write --source-root <dir>` rewrites the managed block in all four runtimes' global instruction files with no allowlist — persistent cross-session prompt injection | CONFIRMED `:406,211-245` |
| P2-18 | `plan_context_updater --note` is written unsanitized into a vision file that `steer_context`/`plan_context_loader` re-inject as context | CONFIRMED `:104,112,180` |
| P2-19 | Taste installers `git clone $lock.source` / `checkout $SHA` with no `--`, and `rm -rf`/`Remove-Item -Recurse -Force` on lockfile-supplied names | CONFIRMED `install_taste_skills.{sh,ps1}` |
| P2-20 | `npx --yes skills add` (unpinned) at install; `uvx code-review-graph` (unpinned) promoted into the global `CLAUDE.md` | CONFIRMED `install_taste_skills.*:21/34`, `overlays/claude-global.md:14` |
| P2-21 | `git_hygiene --deploy --apply` runs `git checkout base -- <files>` **into the primary checkout**, contradicting its own docstring invariant at `:17`; the file set comes from `origin/main` | CONFIRMED `:458-467` vs `:17` |
| P2-22 | Design-doc mirror does up to 6 min of synchronous git network I/O inside a 30 s hook; SIGKILL skips `finally` and orphans the temp index | CONFIRMED `autocommit_design_docs.py:142,153-191` vs manifest timeout |
| P2-23 | `_push` uses the tree's only `shell=True`, fire-and-forget, no timeout, output to DEVNULL — a rejected push still reports "commit + push" | CONFIRMED `:205-217` |
| P2-24 | Codex/Cursor hook doctors never check the adapter file exists (the Claude one does) — the IDEA_BOX hole still open on two of three runtimes | CONFIRMED `codex_hooks_doctor.py:93-96`, `cursor_hooks_doctor.py:74-77` |
| P2-25 | `install.ps1 -Check` reports "no drift" without ever inspecting the hook block | CONFIRMED `:98-142` |
| P2-26 | `answer_footer.py` reparses the entire transcript JSONL on **every turn** against a 5 s budget — O(session²) | CONFIRMED `:148-186` |
| P2-27 | Hooks spawn bare `python` from PATH while the installer deliberately resolves `py`; `session_title_janitor_scheduled.ps1:60-79` documents a production incident from exactly this | CONFIRMED 5 call sites |
| P2-28 | POSIX installer never received PR #108's fix — writes `$skill.bak.$STAMP` **inside** the live skills root | CONFIRMED `install.sh:43-48,58-61` |
| P2-29 | POSIX and Windows installers install different systems (no commands/prompts/retirement/check on POSIX) | CONFIRMED |
| P2-30 | `truthctl.py` is exercised by `truthdeck-ci`'s pytest step but excluded from that job's `paths:` — editing it alone runs nothing | CONFIRMED |
| P2-31 | Tests confirm the wrong invariant: `test_..._no_double_fire` installs twice from the same root (noop path) while the live box reached 20 handlers via a second checkout; `test_forged_..._fail_closed` asserts a forged token is *granted* ACTIVE; the provenance test loops over a parameter the code never reads | CONFIRMED 3 test file:line |

### P3 — noted

`git branch -D` fallback removes the documented second seatbelt (`git_hygiene.py:449`);
external-publication approval is a bare self-asserted argv flag; worktree
"authorization" is derived from the receipt it authorizes; unpinned `pytest`,
mutable action tags, `mcp>=1.0.0`; `DENY_FILES` in `sync_ecosystem_context` is
dead code (only ever applied to `*.md` globs); `IDEA_BOX.md` keeps 12 of 25
lines of shipped work in the hot index against its own rule; README's `Files`
tree covers 11 of 72 scripts; `docs/INSTALL.md` has two dead links; `~/.claude/PLANS.md`
is 20.7 MB / 113k lines; `skills/gstack` is 1.7 GB of the 4.5 GB home.

### Secret-history scan — coverage statement

All 2,634 objects / 1,193 blobs across 372 commits and 107 refs reachable in
this worktree were piped through a high-entropy pass and a generic
credential-assignment pass. **Zero real secrets found** — every hit was a test
fixture. Not covered: GC'd or never-fetched objects, remote branches outside
these 107 refs, the private `ecosystem-context` target repo, and secrets in
forms neither pattern set recognises. Separately, `dszub` / `C:\Users\dszub\…`
appear in ~30 tracked files and a real session UUID is committed in a baseline
fixture — severity depends on repo visibility, which was not checked.

---

## What is solid

Worth stating plainly, because the failures above are delivery failures, not
design failures.

- **Capacity-one admission is genuinely atomic.** `request()` does read-decide-insert
  under `BEGIN IMMEDIATE`; 50 threads through a 20-worker pool produced exactly
  one ACTIVE and 49 QUEUED. The inheritance-once rule is enforced in code — a
  second concurrent child is quarantined with a committed ledger row before
  raising, and an expired parent lease is rejected.
- **Bounded pytest is honest.** Fixed `[python, -m, pytest, *args]`, `shell=False`,
  interpreter validated against a resolved real file, allowlisted child env,
  retained `Popen` handle as the sole liveness authority, monotonic elapsed time,
  recorded pid + `create_time()`. No WMI, no process-table polling.
- **The `cdp:*` / `host:heavy` split holds where it matters** — verified at runtime
  that an occupied `host:heavy` does not delay a `cdp:chatgpt` admission.
- **The state layer is well built**: mkstemp + fsync + `os.replace` with bounded
  retry on the two transient Windows sharing errors, `os.link` for real write-once
  semantics, schema validation, size caps, `..`/absolute path rejection, symlink
  rejection, cursor-based liveness-aware reaping.
- **`hooks_install`'s merge design is right** — validate-before-mutate, handler
  granularity, foreign handlers preserved verbatim, backup → pending sidecar →
  settings → installed sidecar, and a `COLLISION` channel that refuses to
  silently mutate what it cannot classify. It correctly reported the live
  duplication; nothing consumed the report.
- **`install_codex_session_lifecycle` is the strongest installer in the tree**:
  before-hashes, assert-unchanged between writes, rollback manifest, compensating
  restore on any `BaseException`.
- No `pickle`, `marshal`, `yaml.load`, `eval`, `exec`, `__import__`,
  `Invoke-Expression`, or `[scriptblock]` anywhere in the tree. Workflows use
  `pull_request` (never `pull_request_target`), run on `windows-latest` (not the
  self-hosted pool), and interpolate no `${{ github.event.* }}` into any `run:`.

---

## The one pattern behind most of it

Three of the four largest clusters are the same defect wearing different clothes:

**A detector exists, fires correctly, and reports into a file nobody reads.**

- `hooks_install status` → exit 3, `overall: MISSING`. Read by nothing.
- `git_hygiene` → `MANAGED HOOKS: COLLISION` daily since at least 2026-09-04.
  Read by nothing.
- 1,601 session verdicts → produced correctly, consumed by nothing.
- 2,035 hook errors → logged correctly, with the reason discarded so that even a
  reader could not act.
- `install.ps1 -Check` → 53 drift items, and it does not look at hooks anyway.

The fix is not more detection. It is one delivery seam that turns these into
something the operator cannot miss, plus non-zero exit codes wired into the
places that already gate.
