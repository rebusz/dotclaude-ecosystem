# Agent Rules Sync

`agent-rules/` is the git-tracked source of truth for managed Claude `CLAUDE.md`
and Codex `AGENTS.md` blocks.

## Layout

- `agent-rules/core.md` - shared operating rules.
- `agent-rules/overlays/claude-global.md` - Claude-only global overlay.
- `agent-rules/overlays/codex-global.md` - Codex-only global overlay.
- `agent-rules/repos/<repo-slug>/shared.md` - repo-local shared rules.
- `agent-rules/repos/<repo-slug>/claude.md` - repo Claude overlay.
- `agent-rules/repos/<repo-slug>/codex.md` - repo Codex overlay.

## Commands

```powershell
python "C:/Users/dszub/.claude/scripts/sync_agent_rules.py" --check --repo "D:/APPS/Tsignal 5.0"
python "C:/Users/dszub/.claude/scripts/sync_agent_rules.py" --diff --repo "D:/APPS/Tsignal 5.0"
python "C:/Users/dszub/.claude/scripts/sync_agent_rules.py" --write --repo "D:/APPS/Tsignal 5.0"
```

The sync tool edits only this versioned block:

```markdown
<!-- BEGIN AGENT-RULES:shared:v1 -->
...
<!-- END AGENT-RULES:shared:v1 -->
```

It fails closed on malformed markers, writes atomically, uses per-target lock files,
and stores backups in the system temp directory.
