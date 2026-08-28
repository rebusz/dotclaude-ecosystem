# Shared Agent Core

## Ecosystem

- Work primarily under `D:/APPS/<repo>`. Tsignal executes; WatchF is advisory/discovery; TsignalLAB researches; Obsidian Flow is memory.
- Trading data flows one way (Tsignal -> TsignalLAB -> Obsidian Flow). Reverse insight travels ONLY through the validated async seam (candidate store + validation gate + shadow + signed operator GO); nothing outside the live brain writes live decision/order state. Full contract -> `agent-rules/refs/data-flow-seam.md`. This is a DATA-FLOW boundary, not a restriction on which files an agent may edit.
- Read `D:/APPS/_shared/PORTS.md` before changing or starting local servers.

## Repo Truth

- Plans, audits, postmortems, and design docs live in the project repo under `design/plans/`, `design/audits/`, or `design/visions/`; scratch locations are temporary. Commit and push them when the repo has a tracked remote and no unrelated changes are staged.
- When asked "what next" or about priorities, check the repo `IDEA_BOX.md` and the ecosystem idea box before inventing a new backlog.

## Risk Classes — care, not access

- R0 docs/prompts; R1 non-live tooling, tests, mirrors; R2 contracts/persistence/ingestion; R3 execution/runtime/order path.
- The R-class scales CARE — plan, blast radius, rollback, targeted validation, and for R2/R3 a standing operator GO. It never forbids ACCESS.
- **Agents design, edit, refactor, and test all code — broker API, order path, and live-path code included.** There is no forbidden code. Detouring around the live path out of caution is itself a defect: that is what produced the paper/live divergence documented in `agent-rules/refs/paper-live-parity.md`.
- **Paper/live parity is binding.** One execution code path serves both surfaces; account, port, credentials, and enablement are DATA, never code branches. A `*_paper_only` fork, a live-only special case, or an execution change validated only on paper is a ship-blocker.
- **Live READ is free**: connecting to real accounts for read-only diagnosis (auth, entitlements, connectivity, position/order readback) needs no extra approval.
- **The TRIGGER is gated**: order submit/modify/cancel, arming automation, or flipping enablement flags on REAL-MONEY or TOPSTEP COMBINE accounts requires explicit just-in-time operator GO. Paper/practice submits are free.
- Emergency-off and flatten paths must behave identically on both surfaces and default ON.
- External signals stay advisory unless the operator explicitly changes that boundary.

## Execution Defaults

- Assess whether work splits into independent lanes; run or delegate them concurrently when the tooling supports it.
- GPT coding, plan-audit, and implementation-review work uses signed-in `chrome_gpt` ChatGPT CDP and fails closed; Codex CLI is allowed only when resolver-owned policy stamps `purpose=latency_critical_runtime` plus a registered runtime context (initially advisory OpusF scenario production). Use the workflow-selected basket: `/fwf` free or `/fwp` paid. Never downgrade model capability solely to cut cost. Perplexity Max is the bounded **CoderPX** on-demand lane: an agent submits one validated packet through WatchF's Conductor-gated `chrome_ppl` lifecycle, records response + manifest, then verifies and lands any justified result. CoderPX never auto-retries, marks Ready, merges, or bypasses repo gates. Protocol + packet template: `D:/APPS/_shared/coderpx/README.md`.
- An approved audited plan (`GO`, `ok go`, `jedziesz`, `dzialaj`, `implementuj`) carries standing authorization through implementation, in-scope fixes, exact-head review, ready, CI, merge, and checkout sync. SHAs are evidence, not operator tokens. Re-ask only for scope expansion, unresolved failure/conflict, a real-money/Combine trigger, a destructive action, or a pause.
- Validate each slice; final reports state changes, tests, remaining work, and repo state.

## Conductor Host-Resource Gate

- TruthDeck Conductor owns the durable `host:heavy` capacity-one lease for
  cooperative heavy pytest, Playwright, and CDP-provider work; adapters must
  request it before launch and remain visible in Conductor readback.
- A bounded child may inherit an active attempt-scoped
  `TDCONDUCTOR_LEASE_ID` once; a second concurrent inherited child, forged or
  stale token, expired lease, or `RECOVERY_REQUIRED` state fails closed. There
  is no preemption or automatic retry across an ambiguous owner.
- Bounded pytest uses only `<python> -m pytest <args>` with a retained
  `Popen` handle and `shell=False`; WMI/CIM/process-list polling and arbitrary
  shell execution are not substitutes for ownership evidence.
- `authorize --interactive` is an operator-only tty-verified coordinator
  handshake with an exact prompted GO. Authorization cannot be granted by
  argv flags alone, inbox, environment, MCP, or agent assignment paths.
- Storage growth is read back with numeric ceilings and report-only retention;
  status must be checked before starting another heavy lane.
- **CI runner pool exemption (decided 2026-08-13, zero-spend CI plan §8):** the
  workstation's GitHub Actions self-hosted runner pool is EXEMPT from the capacity-one
  `host:heavy` lease — governed instead by pool size, BelowNormal priority, the pilot
  SLO drain ladder, and `TsignalCiWatchdog` readback (`~/.claude/state/ci_watchdog/`).

## Land-On-Main Lifecycle

- Finished, locally validated work reaches `main` under your own hands — the operator never hand-reconciles commits, merges, or divergence.
- ONE clean path per change: branch -> validate -> commit -> draft PR -> risk-routed review gate -> `gh pr ready` -> squash-merge -> fast-forward the operator's main checkout. Report it in one line.
- Never create avoidable divergence (no cherry-pick onto local main alongside a PR for the same change). An agent usually works in a `.claude/worktrees/...` branch while the operator runs from `D:/APPS/<repo>`; after merge, fast-forward that checkout.
- R2/R3 lands via draft PR + review gate — never direct-push or self-merge to `main`; R0 docs and CI-ignored paths may use the normal flow. Real-money/Combine triggers, production deploys, and destructive actions still need just-in-time GO. Details -> `agent-rules/refs/delegated-execution-protocol.md`.
- CI Discipline: Tsignal and TSU CI runs on the workstation's self-hosted runner pool — unmetered, but each runner is capacity-one and shares the box with the live trading stack. Keep implementation PRs draft while work moves, batch pushes, validate locally, then `gh pr ready` once — one CI pass per change instead of occupying a runner on every push. Small repos still on GitHub-hosted free tier do spend hosted minutes; the same batching keeps them inside it. State draft-vs-ready and what validation ran in the final summary.

## Commit And Push Defaults

- Commit coherent, tested units; push when the branch tracks a remote and validation ran (or say why it did not). Report "done" only when committed AND pushed, naming branch/PR/SHA.
- Stage only files you intentionally changed; never auto-commit secrets, env files, generated junk, large binaries, or work the operator marked read-only.

## Repo Hygiene

- Integrate small and often — a fast-forward is safe, a far-diverged branch is where merges break.
- A daily janitor (`git_hygiene.py`, Windows task `TsignalGitHygiene`) writes a DRY-RUN report and a primary-off-main / unpushed-R3 alarm under `~/.claude/state/git_hygiene/`; it reaps nothing on its own. Reaping is manual and gated (`--apply`), safe only when other sessions are quiesced — a clean worktree from a runtime that does not lock is not protected. Lock your worktree if your runtime can.

## Review Gate

- Stamp the R-class on every plan at creation; it selects the owning workflow before the land-on-main merge. Follow the **Review Workflow Routing** table in `skills/master-agent/SKILL.md` — it is authoritative and not duplicated here.
- `/fwf` and `/fwp` own the R1/R2/R3 lifecycle through implementation and blocking `review`; R0 has no mandatory workflow. Do not duplicate the `review` stage the workflow already owns; audit and matrix runners are internal stages, not public commands.
- Review the actual diff (Claude `/code-review`; Codex its review pass). SHIP-BLOCKING findings block the merge; FIX-LATER findings are noted. External review requires preflight, secret rejection, draft PR, packet, and exact-head evidence; standing plan GO covers configured reviewers.

## Evidence Discipline

- Tests must drive the REAL code path, including the failure/rollback branch — no mock that skips the broker submit, no fixture faking restart adoption, no test against a disabled path. Persistence/restart DoD is a round-trip, not a post-state fixture.
- Fail closed when summarizing: preserve nonzero exit codes, timeouts, skipped critical tests, and the first failing assertion with its artifact path. Say "passed" only when the exit code is 0 AND the intended target actually ran.
- Ground specific claims — numbers, named sources, causal statements — in something checkable, or drop them.

## Ship-On Default

- Features land ENABLED after tests unless an approved plan says otherwise. Do not invent soak periods, shadow-only defaults, or disabled flags "for safety". A necessary kill switch defaults ON with a documented emergency-off path.

## Context Discipline

- Intent-layers first: read the repo's root `CLAUDE.md`/`AGENTS.md` and its refs as the architecture map instead of blind-scanning for entry points.
- Progressive disclosure: load skills, refs, and deep docs when the task matches. Keep always-loaded files lean — deep procedure belongs in skills, `agent-rules/refs/`, `design/`, or nested module files. Hot indexes (`MEMORY.md`, `AGENTS.md`) are working sets, not append logs: move DONE entries to a cold archive, promote them back if they reopen.
- Prefer code intelligence over guessing: for any work touching more than one file/module, renaming a symbol, changing a public contract, or judging blast radius, use the available code-graph/impact tools first (inspect the exposed tool surface — names differ across runtimes; `code-review-graph` CLI otherwise). State the fallback when you use one.
- Keep only ecosystem-relevant MCP servers and connectors active. When context fills or a research phase ends, checkpoint conclusions to durable memory/handoff and continue from that summary. Budget before breadth; prefer bounded reads. Full procedure -> `agent-rules/refs/token-budget-protocol.md`.

## Operator Reporting Style

- Lead with the outcome or the action taken; explanation comes after.
- Number multi-step work; keep lists to five items or fewer.
- End with exactly ONE concrete next action, not a menu of options.
- Report errors matter-of-factly: what failed, plus the evidence path. No softening, no burying.
- Restate load-bearing runtime state when it matters (process alive? armed? which account? which checkout?).
- No preamble, no closers, no tangents. Wins get one line.

## Agent Rules Maintenance

- Shared instructions are generated from `D:/dotclaude/dotclaude-ecosystem/agent-rules`; generated content stays inside `AGENT-RULES` managed blocks, and manual local sections stay outside them.
- Edit the source and re-run `scripts/sync_agent_rules.py --write`; never hand-edit a managed block in a target file.
