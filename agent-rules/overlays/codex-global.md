# Codex Global Overlay

## Global Response Footer

- Append a compact metadata footer to final user-facing Codex replies: `Meta: <Mon DD HH:mm MDT> | Codex | scope: <short-scope> | id: <short-id>`.
- Use the user's local timezone when available; default here is `America/Edmonton` / `MDT`.
- Do not run a shell command solely to compute the footer timestamp.
- Do not place the footer inside code blocks, commit messages, PR descriptions, generated docs, or exact paste-ready content unless asked.

## Plan Lifecycle Hooks

- For plan/module creation, review, or execution across `D:/APPS/<repo>`, run before any other tool call: `python "C:/Users/dszub/.claude/scripts/plan_context_loader.py" --cwd "$PWD" [--plan <plan-path>]`.
- Read the `<plan-context>` output, reference vision Why/DoD when relevant, check IDEA_BOX, and avoid duplicating existing PLANS.md work.
- After code/plan changes are committed, or at end of work if no commit, run: `python "C:/Users/dszub/.claude/scripts/plan_context_updater.py" --plan <plan-path> [--shipped] [--note "<one-line>"] [--resolved-ideas "<slugs>"]`.
- Before final summary in plan-creating modes, include `EPILOG_PAYLOAD` with start SHA, end SHA, plan path, committed, and resolved ideas.

## Codex Operating Notes

- Use `C:/Users/dszub/.codex/AGENTS.md` for durable global Codex behavior, not `config.toml`.
- Codex loads `AGENTS.md` hierarchically; keep repo-local files focused on local contracts and avoid duplicating global footer/execution policy.
- For `code-review-graph` in Codex, use the MCP tools currently exposed by `mcp__code_review_graph` (for example `list_graph_stats`, `get_review_context`, `get_architecture_overview`, `get_knowledge_gaps`, `get_bridge_nodes`, and `get_suggested_questions`). Do not call stale tool names from older repo docs. If Codex MCP lacks a needed graph operation, use the local CLI (`code-review-graph status --repo <repo>`, `code-review-graph detect-changes --repo <repo>`, `code-review-graph update --repo <repo>`) before targeted `rg` fallback.

## Codex Audit Routing

- The ecosystem audit pipelines live in `D:/APPS/_shared/audit/` (shared, version-controlled). To audit a plan/design:
  - **auditF** (free — OpenRouter 8 free models + Perplexity/Gemini CDP + a frontier auditor): `python "D:/APPS/_shared/audit/auditf.py" "<ABSOLUTE_PLAN_PATH>" --topic <topic> --synthesizer gpt`
  - **auditP** (paid OpenRouter complement basket): `python "D:/APPS/_shared/audit/multi_audit.py" "<ABSOLUTE_PLAN_PATH>" --topic <topic>`
- **MANDATORY: Codex always passes `--synthesizer gpt` to auditF.** Codex IS the synthesizer (GPT), so this drops the GPT audit lane (no self-grading) and instead fires the Claude Opus CLI lane (`WatchF/scripts/auditcl.py`) as the external frontier auditor. Omitting it defaults to `claude` → GPT grades its own work (wasted tokens, the original reason that lane churned).
- CDP lanes need operator-started signed-in Chrome (`chrome_te`/`chrome_ppl`); the Claude CLI lane needs `claude` on PATH. auditF is fail-soft — down lanes are skipped.
- After the run, read `design/audits/<date>_<topic>/synthesis_prompt.md`, synthesize (consensus P1 → apply; unique valid P1/P2 → apply; discard noise / frozen-boundary violations), apply fixes to the plan. Red lines: never override frozen boundaries; never touch Tsignal exec path without R3.
