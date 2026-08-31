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

## Codex Full-Workflow Routing

- Follow the authoritative **Review Workflow Routing** table in `skills/master-agent/SKILL.md`. `/fwf` and `/fwp` are the only public full-workflow commands and own R1/R2/R3 plan review, implementation, exact-head review, and landing.
- The only internal runner for R1/R2/R3 is `D:/APPS/_shared/audit/fuse.py`. `/fwf` passes `--mode free`; `/fwp` passes `--mode paid`. Do not expose runner presets or lane-bypass flags as operator workflows.
- `--synthesizer gpt|claude` records the active final judge and never changes the panel. Every client/risk class runs ChatGPT CDP (only GPT-5.6 Sol: Pro effort, then safe pre-submit xhigh fallback on the same model), Antigravity `gemini-3.7-flash-high` (Gemini CDP `gemini-3.7-flash` fallback), and Perplexity GLM 5.3/Kimi 3/Grok 4.6/Sonnet 5/GPT Terra. Claude CLI, Codex CLI, standalone GLM CLI, and nested CLI tournament synthesis are not workflow lanes.
- CDP lanes need operator-started signed-in Chrome and remain visible in fail-soft evidence when unavailable. Antigravity is pinned to read-only plan+sandbox mode for audit work.
- Read the generated synthesis prompt and apply consensus P1 plus unique valid P1/P2 inside frozen boundaries. Discard noise and boundary violations. Never touch Tsignal execution path without R3.
