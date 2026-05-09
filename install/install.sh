#!/usr/bin/env bash
# dotclaude-ecosystem installer (POSIX)
# Idempotent: safe to re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_HOME="${HOME}/.claude"
CODEX_HOME="${HOME}/.codex"
STAMP="$(date +%Y%m%d-%H%M%S)"

echo "=== dotclaude-ecosystem installer ==="
echo "Source : $REPO_ROOT"
echo "Target : $CLAUDE_HOME"
echo

# Backup existing
if [ -d "$CLAUDE_HOME" ]; then
    backup="$CLAUDE_HOME.bak.$STAMP"
    echo "[1/6] Backup ~/.claude -> $backup"
    cp -R "$CLAUDE_HOME" "$backup"
else
    echo "[1/6] No existing ~/.claude to back up"
    mkdir -p "$CLAUDE_HOME"
fi

# Scripts
echo "[2/6] Copy scripts -> ~/.claude/scripts/"
mkdir -p "$CLAUDE_HOME/scripts"
cp "$REPO_ROOT/scripts/"*.py "$CLAUDE_HOME/scripts/"

# Skills
echo "[3/6] Copy skills -> ~/.claude/skills/"
for skill in master-agent executor; do
    mkdir -p "$CLAUDE_HOME/skills/$skill"
    cp -R "$REPO_ROOT/skills/$skill/"* "$CLAUDE_HOME/skills/$skill/"
done

# settings.json
echo "[4/6] Merge hooks into ~/.claude/settings.json"
SETTINGS_TPL="$REPO_ROOT/templates/settings.json.template"
SETTINGS_DST="$CLAUDE_HOME/settings.json"
if [ -f "$SETTINGS_DST" ]; then
    echo "  existing settings.json found — manual merge required, see install_notes.md"
    cp "$SETTINGS_TPL" "$SETTINGS_DST.from-template"
else
    cp "$SETTINGS_TPL" "$SETTINGS_DST"
    echo "  installed fresh settings.json"
fi

# CLAUDE.md
echo "[5/6] Install CLAUDE.md template"
CLAUDE_MD_TPL="$REPO_ROOT/templates/CLAUDE.md.template"
CLAUDE_MD_DST="$CLAUDE_HOME/CLAUDE.md"
if [ -f "$CLAUDE_MD_DST" ]; then
    echo "  existing CLAUDE.md found — leaving in place; template at $CLAUDE_MD_DST.from-template"
    cp "$CLAUDE_MD_TPL" "$CLAUDE_MD_DST.from-template"
else
    cp "$CLAUDE_MD_TPL" "$CLAUDE_MD_DST"
    echo "  installed fresh CLAUDE.md"
fi

# Codex AGENTS.md
echo "[6/6] Codex AGENTS.md (optional)"
if [ -d "$CODEX_HOME" ]; then
    AGENTS_TPL="$REPO_ROOT/templates/AGENTS.md.template"
    AGENTS_DST="$CODEX_HOME/AGENTS.md"
    if [ -f "$AGENTS_DST" ]; then
        if grep -q "Plan Lifecycle Hooks" "$AGENTS_DST"; then
            echo "  already present"
        else
            echo "  appending Plan Lifecycle Hooks section"
            printf "\n" >> "$AGENTS_DST"
            cat "$AGENTS_TPL" >> "$AGENTS_DST"
        fi
    else
        cp "$AGENTS_TPL" "$AGENTS_DST"
        echo "  installed fresh AGENTS.md"
    fi
else
    echo "  ~/.codex not found — skipping"
fi

# Initial empty memory/idea-box
for f in MEMORY.md ECOSYSTEM_IDEA_BOX.md; do
    p="$CLAUDE_HOME/$f"
    if [ ! -f "$p" ]; then
        printf "# %s\n\n_Auto-managed. Add entries via natural-language requests to AI._\n" "${f%.md}" > "$p"
    fi
done

echo
echo "=== Install complete ==="
echo
echo "Next steps:"
echo "  1. Review ~/.claude/CLAUDE.md and personalize the ecosystem table"
echo "  2. Review ~/.claude/settings.json hooks"
echo "  3. (Optional) Set up your private context repo for AI tool sharing"
echo "  4. Run: python ~/.claude/scripts/plan_catalog.py to generate PLANS.md"
echo "  5. Run: python ~/.claude/scripts/vision_catalog.py to generate VISIONS.md"
