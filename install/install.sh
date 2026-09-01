#!/usr/bin/env bash
# dotclaude-ecosystem installer (POSIX)
# Idempotent: safe to re-run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_HOME="${HOME}/.claude"
CODEX_HOME="${HOME}/.codex"
GEMINI_HOME="${HOME}/.gemini/config"
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
BUNDLED_SKILLS=(master-agent executor distill-repo ponytail-on-demand run-model-team coderpx)
for skill in "${BUNDLED_SKILLS[@]}"; do
    mkdir -p "$CLAUDE_HOME/skills/$skill"
    cp -R "$REPO_ROOT/skills/$skill/"* "$CLAUDE_HOME/skills/$skill/"
done
if [ -d "$CODEX_HOME" ]; then
    CODEX_SKILLS=(master-agent executor ponytail-on-demand run-model-team)
    for skill in "${CODEX_SKILLS[@]}"; do
        if [ -d "$CODEX_HOME/skills/$skill" ]; then
            cp -R "$CODEX_HOME/skills/$skill" "$CODEX_HOME/skills/$skill.bak.$STAMP"
        fi
        mkdir -p "$CODEX_HOME/skills/$skill"
        cp -R "$REPO_ROOT/skills/$skill/"* "$CODEX_HOME/skills/$skill/"
    done
    echo "  copied bundled skills -> ~/.codex/skills/"
fi


# Antigravity (agy) skills -> ~/.gemini/config/skills/
# Separate root from ~/.claude/skills: these are read by the agy CLI, not Claude.
if [ -d "$GEMINI_HOME" ]; then
    AGY_SKILLS=(fwa coderpx)
    for skill in "${AGY_SKILLS[@]}"; do
        if [ -d "$GEMINI_HOME/skills/$skill" ]; then
            cp -R "$GEMINI_HOME/skills/$skill" "$GEMINI_HOME/skills/$skill.bak.$STAMP"
        fi
        mkdir -p "$GEMINI_HOME/skills/$skill"
        cp -R "$REPO_ROOT/agy-skills/$skill/"* "$GEMINI_HOME/skills/$skill/"
    done
    echo "  copied agy skills -> ~/.gemini/config/skills/"
fi

# settings.json -- wire the managed hook block (handler-granular merge, dry-run first)
echo "[4/6] Wire managed hooks into ~/.claude/settings.json"
HOOKS_INSTALLER="$REPO_ROOT/scripts/hooks_install.py"
python3 "$HOOKS_INSTALLER" install --checkout "$REPO_ROOT"            # dry-run diff
python3 "$HOOKS_INSTALLER" install --checkout "$REPO_ROOT" --apply    # merge managed block, foreign hooks preserved
echo "  managed hook block wired (run: python3 $HOOKS_INSTALLER doctor)"

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
