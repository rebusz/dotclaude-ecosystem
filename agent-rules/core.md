# Shared Agent Core

## Ecosystem

- Work primarily under `D:/APPS/<repo>`.
- Tsignal is the execution authority, WatchF is advisory/discovery, TsignalLAB is research, and Obsidian Flow is memory.
- Trading data flow is one-way: Tsignal -> TsignalLAB -> Obsidian Flow. Never reverse it.
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

## Risk Classes

- R0: docs/prompts only; proceed freely.
- R1: non-live tooling, tests, mirrors; proceed normally.
- R2: contracts, persistence, ingestion; plan plus GO.
- R3: execution/runtime/order path; plan plus GO plus rollback plus validation.
- LLM agents never touch broker API or order path. External signals stay advisory unless the operator explicitly changes that boundary.

## Ship-On Default

- New features land enabled by default after tests unless a user-approved plan or R3 rollback path says otherwise.
- Do not invent soak periods, shadow-only defaults, or disabled feature flags "for safety".
- If a kill switch is necessary, default ON and document the emergency-off path.

## Agent Rules Maintenance

- Shared instructions are generated from `D:/dotclaude/dotclaude-ecosystem/agent-rules`.
- Generated content must stay inside `AGENT-RULES` managed blocks.
- Manual local sections such as port contracts stay outside managed blocks.
