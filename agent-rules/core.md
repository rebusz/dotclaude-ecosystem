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

## Execution Defaults

- When the user approves a concrete plan, slice chain, or says `ok go`, `jedziesz`, `dzialaj`, or `implementuj`, execute end-to-end.
- Continue through approved slices until an explicit gate, live-money/production/destructive risk, repo-plan contradiction, validation blocker, or user pause appears.
- After each meaningful slice, update status, run targeted validation, and continue without needless re-confirmation.
- Finish with what changed, what was validated, what remains, and whether the relevant repo is clean/pushed.

## Commit And Push Defaults

- Commit coherent, tested units of approved implementation when it preserves progress or prepares handoff.
- Push when the branch tracks a remote and validation was run or the reason it was skipped is stated.
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
