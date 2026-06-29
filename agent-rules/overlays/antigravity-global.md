# Antigravity Global Overlay

## Plan Lifecycle Hooks

- Before plan/module creation, review, or execution across `D:/APPS/<repo>`, run: `python "C:/Users/dszub/.claude/scripts/plan_context_loader.py" --cwd "$PWD" [--plan <plan-path>]`.
- After code/plan changes are committed, or at end of work when a plan path exists, run: `python "C:/Users/dszub/.claude/scripts/plan_context_updater.py" --plan <plan-path> [--shipped] [--note "<one-line>"]`.
- If Antigravity cannot run these commands directly, record the required command and continue from the checked plan file.

## Antigravity Operating Notes

- This file is the global Antigravity/Gemini context target at `C:/Users/dszub/.gemini/GEMINI.md`, generated from `D:/dotclaude/dotclaude-ecosystem/agent-rules`.
- Use text rules only in this Workflow OS slice. Do not configure `.agents/hooks.json`, `.agents/mcp_config.json`, or global MCP JSON from this target.
- Official Antigravity docs identify `GEMINI.md` and `AGENTS.md` as context files and `.agents/mcp_config.json` as a workspace MCP path. Treat those as separate surfaces; this target covers only the global context file.
- Keep Cline separate. Do not infer Cline `.clinerules` behavior from Antigravity evidence.

## Runtime Readback

- `session_cost_probe.py check` should report `antigravity_global.kernel_ok=true` after this target is written.
- If Antigravity ignores this file at runtime, treat the sync as ineffective and remove the target with one revert plus deletion of `C:/Users/dszub/.gemini/GEMINI.md`.
