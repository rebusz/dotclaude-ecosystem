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
