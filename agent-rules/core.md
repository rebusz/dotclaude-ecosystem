# Shared Agent Core

## Ecosystem

- Work primarily under `D:/APPS/<repo>`.
- Tsignal is the execution authority, WatchF is advisory/discovery, TsignalLAB is research, and Obsidian Flow is memory.
- Trading data flow defaults one-way (Tsignal -> TsignalLAB -> Obsidian Flow). Reverse contribution of DATA/insight is allowed ONLY through a validated, async, gated seam (candidate store + validation gate + shadow + signed operator GO); the live path owns its own state, never synchronously depends on research/cloud, and nothing writes live decision/order state except the live brain. Forbidden control-coupling: a research/LAB process writing the live store directly, the live path blocking on a research call, or a shared mutable store on the live path. (Distinct from, and additional to, the absolute LLM order-path boundary in Risk Classes below.)
- Read `D:/APPS/_shared/PORTS.md` before changing or starting local servers.

## Repo Truth

- Plans, audits, test plans, postmortems, and design docs live in the project repo under `design/plans/`, `design/audits/`, or `design/visions/`.
- Scratch locations such as `.gstack` are temporary; the repo copy is canonical.
- Commit and push design docs immediately after writing them when the current repo has a tracked remote and no unrelated changes are staged.
- When asked "what next" or about priorities, check the repo `IDEA_BOX.md` and the global ecosystem idea box before inventing a new backlog.

## Reasoning Hygiene

- Project consequence before recommending: name the proposed action, plausible downside if wrong, and whether it is reversible.
- Ground specific claims: numbers, percentages, named sources, causal claims, and superlatives must be provided, context-supported, stable knowledge, inference, or removed.
- Read before write: before editing code, inspect exports, immediate callers, and shared utilities in the touched area.
- Audit the task itself: for non-trivial work, outline the steps and critique them as an expert reviewer before implementing.
- Pin abstraction level: produce work fit for a production codebase under code review, not tutorial-level examples.
- Stage production-shaped context: tests and examples should include realistic messy inputs, not only clean synthetic fixtures.

## Context And Token Hygiene

- Intent-layers first: before scanning a repo, read its root `CLAUDE.md`/`AGENTS.md` and any `.claude/refs/` or nested module pointers; treat them as the architecture map. Do not blind-scan to rediscover entry points.
- Progressive disclosure: load skills, refs, and deep docs on demand when the task matches, not preemptively. Keep root agent files lean; deep detail belongs in `.claude/refs/`, `design/`, or nested module files.
- Prefer code intelligence over guessing: before non-trivial repo audits, edits, refactors, or impact analysis, use the currently available code graph/impact tools first. "Non-trivial" means any work that touches or investigates more than one file/module, renames or moves a symbol, changes a public contract, reviews a diff, or asks for blast radius. Tool names differ between Codex/Claude/plugin versions, so first inspect the exposed graph tool surface instead of calling remembered names. If MCP graph tools are missing, stale, or narrower than needed, use the `code-review-graph` CLI when available (`repos`, `status`, `detect-changes`, `update`) before falling back to targeted `rg` and file reads. Skip the graph only for exact-file tiny edits, docs typos, formatting-only changes, or one-line questions with a known path. State the fallback when it happens.
- Startup hygiene: keep only ecosystem-relevant MCP servers and connectors active; unrelated connectors are startup token tax, not capability.
- Handoff over bloat: when context fills or a research phase ends, checkpoint the condensed conclusions to durable memory/handoff and continue from that summary rather than re-reading the full history.
- Keep agent instruction files verifiable and current: concrete invariants over generic advice; prune stale lines; deep procedures live behind pointers, not inline.

### Token Budget Protocol

- Context floor beats token savings: read root agent files, selected plan context, and task-specific safety contracts before pruning context. For Tsignal runtime/server work, `D:/APPS/_shared/PORTS.md` and repo `AGENTS.md` remain mandatory.
- Budget before breadth: for broad audits or investigations, name the evidence path, likely expensive reads/tools, stop condition, and no-go boundaries before loading large context.
- Prefer bounded reads: use indexes, `rg` hit lists, manifests, summaries, and line-window reads before full-file loads or transcript-sized dumps.
- Fail closed on summaries: noisy command summaries must preserve nonzero exit codes, timeouts, skipped critical tests, stderr error groups, first failing assertion or node, and the raw artifact path. Say "passed" only when exit code is zero and the expected target actually ran.
- Budget external surfaces: use browser, connector, graph refresh, or broad MCP calls only when they answer a specific question cheaper local truth cannot.
- Do not prune connectors, skills, MCP servers, or account-level surfaces without audit evidence and explicit GO; record owner, affected projects, rollback path, and whether the action is manual/account-level.
- Token-budget rules are subordinate to risk classes, repo boundaries, live-money boundaries, and the rule that LLM agents never touch broker API or order path.
- Scope handoff tokens: any next GO token must include scope, risk class, no-go boundaries, and a requirement to refresh repo truth before execution.
- Use compact handoffs when pausing or compacting: include repo/cwd, branch/HEAD, dirty-tree boundary, files changed, validation, blockers, exact next command or GO token, and explicit no-go boundaries.

## Execution Defaults

- When the user approves a concrete plan, slice chain, or says `ok go`, `jedziesz`, `dzialaj`, or `implementuj`, execute end-to-end.
- Continue through approved slices until an explicit gate, live-money/production/destructive risk, repo-plan contradiction, validation blocker, or user pause appears.
- After each meaningful slice, update status, run targeted validation, and continue without needless re-confirmation.
- Finish with what changed, what was validated, what remains, and whether the relevant repo is clean/pushed.

## Commit And Push Defaults

- Commit coherent, tested units of approved implementation when it preserves progress or prepares handoff.
- Push when the branch tracks a remote and validation was run or the reason it was skipped is stated.
- Before reporting an implementation task as finished, commit and push the completed work when the repo has a tracked remote; if commit or push is blocked, state the exact blocker and leave the finished work staged only when that is safer than leaving it mixed with unrelated dirt.
- Never stage unrelated user changes; in dirty trees, stage only files intentionally changed for the current task.
- Do not auto-commit secrets, local env files, generated junk, logs, large binaries, live-money path changes, or work the user marked audit/proposal/read-only.

## GitHub Actions Cost Discipline

- For GitHub repos with metered Actions, open implementation PRs as drafts by default (`gh pr create --draft`) so draft-skipped CI does not burn minutes while development is still moving.
- Batch pushes on draft PRs, validate locally first, then run `gh pr ready <pr>` exactly once when the work is done and ready for the single paid CI run.
- Do not push per-slice to a ready PR; if follow-up fixes are needed after a PR is ready, batch them into one validated push whenever possible.
- Docs-only or CI-ignored path changes may use the normal commit/push flow, but still avoid unnecessary pushes.
- In final summaries, state whether the PR is draft or ready, what local validation ran, and whether CI was intentionally deferred.

## Land-On-Main Lifecycle

- When a task/plan is done and locally validated, run the WHOLE git lifecycle yourself so the change reaches `main` and the operator's main working checkout is current - the operator never hand-reconciles commits, merges, pulls, or divergence.
- ONE clean path per change: branch -> validate -> review gate (see Post-Implementation Review Gate) -> push -> PR -> `gh pr ready` -> squash-merge -> fast-forward the operator's main checkout to `origin/main`. Report it in one line.
- Never create avoidable divergence: do NOT cherry-pick a change onto local main AND also open a PR for it (that leaves a duplicate commit the operator must untangle). If a fix must go live immediately, still land it through the single branch->merge path, then fast-forward local main.
- Two-checkout reality: an agent often works in a `.claude/worktrees/...` branch while the operator runs from the main `D:/APPS/<repo>` checkout; after merge, update that main checkout (fetch + fast-forward) so the change appears on main without the operator pulling.
- Hard gate: R3 / live-money / order-path / broker-API merges need explicit operator GO; never unattended auto-merge a live or trading branch. Stop and surface only on those gates, merge conflicts needing judgment, or failed validation.

## Risk Classes

- R0: docs/prompts only; proceed freely.
- R1: non-live tooling, tests, mirrors; proceed normally.
- R2: contracts, persistence, ingestion; plan plus GO.
- R3: execution/runtime/order path; plan plus GO plus rollback plus validation.
- LLM agents never touch broker API or order path. External signals stay advisory unless the operator explicitly changes that boundary.

## Post-Implementation Review Gate

- Stamp a grade (the R-class) on every plan/task at creation; it drives an automatic diff review before the land-on-main merge.
- R3 and R2: ALWAYS run a post-implementation review of the diff as a blocking pre-merge gate. R1: only when the diff is large (>~5 files or >~150 net lines). R0: none.
- Review the actual diff (Claude: `/code-review`; Codex: its review pass). SHIP-BLOCKING findings must be fixed before the merge proceeds; FIX-LATER findings are noted, not blocking.
- R3 additionally warrants a deeper independent review before merge (Claude: `/code-review ultra` cloud; Codex: an auditF / second-model pass); recommend it - the operator triggers billed cloud reviews.
- This review supersedes any generic epilog review for R2/R3 - do not double-review.

## Ship-On Default

- New features land enabled by default after tests unless a user-approved plan or R3 rollback path says otherwise.
- Do not invent soak periods, shadow-only defaults, or disabled feature flags "for safety".
- If a kill switch is necessary, default ON and document the emergency-off path.

## Agent Rules Maintenance

- Shared instructions are generated from `D:/dotclaude/dotclaude-ecosystem/agent-rules`.
- Generated content must stay inside `AGENT-RULES` managed blocks.
- Manual local sections such as port contracts stay outside managed blocks.
