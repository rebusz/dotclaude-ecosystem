# Cline and Antigravity Live-Install Verification Readback

Date: 2026-06-29
Risk: R1, read-only verification
Scope: local platform surface discovery only. No sync target was written.

## Result

Do not implement Antigravity sync targets yet.

Cline has enough local extension-code evidence to mark its live-install verification complete, but no Cline sync target was written in this pass. Antigravity has local installation evidence, but the local filesystem did not prove the exact project sync surfaces from the Workflow OS plan strongly enough to write managed files.

## Evidence

Cline:

- `C:\Users\dszub\.cline` exists.
- `C:\Users\dszub\.cline\data\settings\cline_mcp_settings.json` exists and currently contains an empty `mcpServers` object.
- `C:\Users\dszub\.cline\data\settings\global-settings.json` exists.
- VS Code global storage contains:
  - `C:\Users\dszub\AppData\Roaming\Code\User\globalStorage\saoudrizwan.claude-dev`
  - `C:\Users\dszub\AppData\Roaming\Code\User\globalStorage\rooveterinaryinc.roo-cline`
- Local Cline extension code exists at `C:\Users\dszub\.vscode\extensions\saoudrizwan.claude-dev-4.0.0`.
- Bounded grep of the local Cline bundle found references to:
  - `.clinerules`
  - `.cline/skills`
  - `.clinerules/skills`
  - `.clinerules/hooks`
  - `.agents/skills`
  - `AGENTS.md`
- `skills-lock.json` in that Cline extension contains the bundled `cline-sdk` skill.
- Roo-Cline 3.54.0 also has local package evidence for `AGENTS.md` loading:
  - `roo-cline.useAgentRules`
  - default `true`
  - description: enables loading `AGENTS.md` files for agent-specific rules.

Antigravity:

- `C:\Users\dszub\.antigravity` exists.
- `C:\Users\dszub\AppData\Local\Programs\Antigravity` exists.
- `C:\Users\dszub\AppData\Local\Programs\Antigravity IDE` exists.
- `C:\Users\dszub\.agents\skills` exists and currently contains the Codex/agents skill copy.
- Local grep across Antigravity resources did not produce a reliable hit for:
  - `GEMINI.md`
  - `AGENTS.md`
  - `.agents/hooks.json`
  - `mcp_config.json`
  - `serverUrl`

## Decision

Mark Cline live-install verification complete, but keep Antigravity deferred/manual. The plan's warning remains correct for Antigravity: third-party path conventions are not enough, and a silent wrong path would create drift without runtime signal.

## Next Gate

To promote Antigravity, verify one of these with the running application or official local docs:

1. the exact project-level rules file path the app reads,
2. the exact user-level skills path the app reads,
3. the exact MCP config path and schema,
4. a runtime readback showing the managed kernel was loaded.

Only then write an Antigravity sync target. For Cline, the next slice can design the exact sync target from the verified local surfaces, with a runtime readback before declaring it effective.

## Boundaries

- Did not read `C:\Users\dszub\.cline\data\secrets.json`.
- Did not edit Cline, Antigravity, `.agents`, or repo platform files.
- Did not add `AGENTS.md`, `GEMINI.md`, `.clinerules`, `.agents/hooks.json`, or `mcp_config.json`.
