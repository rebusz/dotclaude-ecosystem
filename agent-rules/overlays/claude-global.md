# Claude Global Overlay

## Plan Lifecycle Hooks

- Triggers include `mode architect`, `mode implement`, `mode ship`, `mode autoplan`, `mode operator`, `/plan-ceo-review`, `/plan-eng-review`, `/autoplan`, `/executor`, `nowy plan`, `tworzymy plan`, `nowy modul`, and `implementuj`.
- PRE-step before planning/coding: `python ~/.claude/scripts/plan_context_loader.py --cwd "$PWD" [--plan <plan-path>]`.
- POST-step after landing or at closeout when a plan path exists: `python ~/.claude/scripts/plan_context_updater.py --plan <plan-path> [--shipped] [--note "<one-line>"] [--resolved-ideas "<slugs>"]`.
- If the loader/updater fails, note it and continue; the hooks are best-effort but must not be silently skipped.

## Claude-Only Routing

- For `mode auditq`, `mode audit_q`, `audytQ`, or `audit Q`, read `~/.claude/AUDIT_Q.md`.
- For `mode auditai`, `mode audit_ai`, `audytAI`, or `audit AI`, read `~/.claude/AUDIT_AI.md`.
- For `mode auditpx`, `mode audit_px`, `audytPX`, `audit PX`, `mode auditppl`, `mode audit_ppl`, `audytPPL`, or `audit PPL`, read `~/.claude/AUDIT_AI.md`.
- Use `.claude/rules` for path-scoped lazy rules and `.claude/refs` for long procedures read only when triggered.
- When the `code-review-graph` MCP is connected, use the graph tools it actually exposes for cross-file impact before editing; do not assume old names such as `get_impact_radius`, `query_graph`, or `semantic_search_nodes` are present. If MCP lacks the needed operation or the graph is stale, refresh/probe with `uvx code-review-graph update --repo <repo>` and `uvx code-review-graph status --repo <repo>` before narrow `rg` fallback.

## Silence Policy

- Development tooling is silent by default. Gate Python, JS/TS, Electron, pytest, CLI, TTS, and media playback behind explicit opt-in flags.
- Trading runtime alerts are the only default audio exception.
- If tests make noise, fix the sound path instead of disabling tests.
