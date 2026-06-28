# Token Budget Protocol — deep procedure (read on demand)

Pointer target from `agent-rules/core.md` → `## Context And Token Hygiene` → `### Token Budget Protocol`. The load-bearing invariant stays in `core.md`; this file holds the full procedure, loaded only when a token-budget decision is in play.

- Context floor beats token savings: read root agent files, selected plan context, and task-specific safety contracts before pruning context. For Tsignal runtime/server work, `D:/APPS/_shared/PORTS.md` and repo `AGENTS.md` remain mandatory.
- Budget before breadth: for broad audits or investigations, name the evidence path, likely expensive reads/tools, stop condition, and no-go boundaries before loading large context.
- Prefer bounded reads: use indexes, `rg` hit lists, manifests, summaries, and line-window reads before full-file loads or transcript-sized dumps.
- Fail closed on summaries: noisy command summaries must preserve nonzero exit codes, timeouts, skipped critical tests, stderr error groups, first failing assertion or node, and the raw artifact path. Say "passed" only when exit code is zero and the expected target actually ran.
- Budget external surfaces: use browser, connector, graph refresh, or broad MCP calls only when they answer a specific question cheaper local truth cannot.
- Do not prune connectors, skills, MCP servers, or account-level surfaces without audit evidence and explicit GO; record owner, affected projects, rollback path, and whether the action is manual/account-level.
- Token-budget rules are subordinate to risk classes, repo boundaries, live-money boundaries, and the rule that LLM agents never touch broker API or order path.
- Scope handoff tokens: any next GO token must include scope, risk class, no-go boundaries, and a requirement to refresh repo truth before execution.
- Use compact handoffs when pausing or compacting: include repo/cwd, branch/HEAD, dirty-tree boundary, files changed, validation, blockers, exact next command or GO token, and explicit no-go boundaries.
