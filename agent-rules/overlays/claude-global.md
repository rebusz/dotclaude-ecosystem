# Claude Global Overlay

## Plan Lifecycle Hooks

- Triggers: `mode architect|implement|ship|autoplan|operator`, `/plan-ceo-review`, `/plan-eng-review`, `/autoplan`, `/executor`, `nowy plan`, `tworzymy plan`, `nowy modul`, `implementuj`.
- PRE: `python ~/.claude/scripts/plan_context_loader.py --cwd "$PWD" [--plan <plan-path>]`.
- POST after landing/closeout with a plan: `python ~/.claude/scripts/plan_context_updater.py --plan <plan-path> [--shipped] [--note "<one-line>"] [--resolved-ideas "<slugs>"]`.
- Loader/updater failures are best-effort but must be reported; continue.

## Claude-Only Routing

- `/fwf` and `/fwp` are the only public full-workflow commands. Claude Code passes `--synthesizer claude` only as final-judge provenance; R1/R2/R3 always use the same fixed ChatGPT CDP + Antigravity/Gemini fallback + Perplexity roster.
- `.claude/rules` = path-scoped lazy rules; `.claude/refs` = trigger-loaded procedures.
- For cross-file impact, use actual `code-review-graph` MCP tools; never assume stale names (`get_impact_radius`, `query_graph`, `semantic_search_nodes`). If the needed operation is absent or the graph stale, run `uvx code-review-graph update --repo <repo>` then `uvx code-review-graph status --repo <repo>` before narrow `rg` fallback.

## Silence Policy

- Development tooling is silent by default. Gate Python, JS/TS, Electron, pytest, CLI, TTS, and media playback behind explicit opt-in flags.
- Trading runtime alerts are the only default audio exception.
- If tests make noise, fix the sound path instead of disabling tests.
