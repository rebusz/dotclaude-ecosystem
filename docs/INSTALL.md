# Install

## Prerequisites

- Python 3.10+ on PATH (script uses `python` shebang)
- `git` CLI on PATH
- Claude Code installed (creates `~/.claude/` on first run)
- Optional: Codex CLI (creates `~/.codex/`)

## Quick install

### Windows (PowerShell)

```powershell
git clone https://github.com/dszub/dotclaude-ecosystem.git
cd dotclaude-ecosystem
.\install\install.ps1
```

### POSIX (Linux / macOS)

```bash
git clone https://github.com/dszub/dotclaude-ecosystem.git
cd dotclaude-ecosystem
bash install/install.sh
```

The installer is **idempotent** — safe to re-run. It backs up your existing `~/.claude/` to `~/.claude.bak.<timestamp>` before any changes.

## What gets installed

| Source | Target | Action |
|--------|--------|--------|
| `scripts/*.py` | `~/.claude/scripts/` | copy (overwrite) |
| `skills/master-agent/` | `~/.claude/skills/master-agent/` | copy (overwrite) |
| `skills/executor/` | `~/.claude/skills/executor/` | copy (overwrite) |
| `templates/CLAUDE.md.template` | `~/.claude/CLAUDE.md` | install fresh, OR copy as `.from-template` if exists |
| `templates/AGENTS.md.template` | `~/.codex/AGENTS.md` | install fresh, OR append "Plan Lifecycle Hooks" section if exists |
| `templates/settings.json.template` | `~/.claude/settings.json` | install fresh, OR copy as `.from-template` if exists |

If you have an existing `settings.json` or `CLAUDE.md`, the installer leaves them in place and drops a `.from-template` sibling for manual merge.

## After install

1. **Personalize `~/.claude/CLAUDE.md`** — fill in the ecosystem table with your repos, customize risk classes
2. **Verify hooks in `~/.claude/settings.json`** — should have `PostToolUse` (autocommit + plan_keyword_detector) and `UserPromptSubmit` (keyword detector)
3. **Generate initial catalogs**:
   ```bash
   python ~/.claude/scripts/plan_catalog.py
   python ~/.claude/scripts/vision_catalog.py
   ```
4. **Test the keyword detector**:
   ```bash
   echo '{"prompt":"new plan for X","cwd":"<your-repo>"}' | python ~/.claude/scripts/plan_keyword_detector.py
   ```
   Should emit `<plan-context>...</plan-context>` block.

## Optional: private context repo for AI tool sharing

If you want Claude cowork dispatch / Perplexity Pro to access your memory + visions + plans + idea_boxes from outside your local PC:

1. Create a private GitHub repo
2. Run `python ~/.claude/scripts/sync_ecosystem_context.py --target <local-clone> --push` to populate it
3. Add `gitleaks` GH Action workflow (template in `dotclaude-ecosystem/templates/.github/workflows/`)
4. Set branch protection on `main`
5. Connect each AI tool to the private repo (see your AI tool's docs for GitHub/MCP setup)

See `templates/sync_setup.md` for the full setup walkthrough.

## Uninstall

The installer keeps a backup at `~/.claude.bak.<timestamp>`. To restore:

```bash
# Windows (PowerShell)
Remove-Item ~/.claude -Recurse -Force
Move-Item ~/.claude.bak.<timestamp> ~/.claude

# POSIX
rm -rf ~/.claude
mv ~/.claude.bak.<timestamp> ~/.claude
```
