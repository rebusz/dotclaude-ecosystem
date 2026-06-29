# Cline Global Overlay

## Plan Lifecycle Hooks

- Before plan/module creation, review, or execution across `D:/APPS/<repo>`, run: `python "C:/Users/dszub/.claude/scripts/plan_context_loader.py" --cwd "$PWD" [--plan <plan-path>]`.
- After code/plan changes are committed, or at end of work when a plan path exists, run: `python "C:/Users/dszub/.claude/scripts/plan_context_updater.py" --plan <plan-path> [--shipped] [--note "<one-line>"]`.
- If the loader/updater cannot detect `dotclaude-ecosystem`, keep working from the plan file and record the failure in the handoff.

## Cline Operating Notes

- This file is the global Cline rules target at `C:/Users/dszub/.clinerules/agent-rules.md`, generated from `D:/dotclaude/dotclaude-ecosystem/agent-rules`.
- Use text rules only on Windows. Do not configure `.clinerules/hooks` as part of this Workflow OS slice; the Cline plan explicitly treats Windows hooks as unverified/no-go.
- Cline local extension evidence confirms `.clinerules`, `.cline/skills`, `.clinerules/skills`, `.agents/skills`, and `AGENTS.md` are recognized surfaces. Prefer this global `.clinerules` target for shared invariants, and add repo-local `AGENTS.md` only through the existing allowlisted repo sync path.
- Keep Antigravity separate. Do not infer Antigravity paths, hooks, MCP schema, or `GEMINI.md` behavior from Cline evidence.

## Runtime Readback

- `session_cost_probe.py check` should report `cline_global.kernel_ok=true` after this target is written.
- If Cline ignores this file at runtime, treat the sync as ineffective and remove the target with one revert plus deletion of `C:/Users/dszub/.clinerules/agent-rules.md`.
