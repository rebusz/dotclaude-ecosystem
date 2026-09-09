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

# Backup existing.
#
# Scoped to what the installer writes, not the whole home. The unscoped copy
# carried credentials in plaintext and grew without bound -- 16.9 GB of stale
# copies against a 4.5 GB live home on the operator's box (audit P1-16).
# Everything omitted is untouched by this script or re-derivable from the repo.
BACKUP_SCOPE=(scripts skills commands settings.json CLAUDE.md hooks-install-manifest.json)
BACKUP_KEEP=3

if [ -d "$CLAUDE_HOME" ]; then
    backup="$CLAUDE_HOME.bak.$STAMP"
    echo "[1/6] Backup installer scope of ~/.claude -> $backup"
    mkdir -p "$backup"
    for item in "${BACKUP_SCOPE[@]}"; do
        if [ -e "$CLAUDE_HOME/$item" ]; then
            cp -R "$CLAUDE_HOME/$item" "$backup/"
        fi
    done
    printf 'Installer-scope backup taken by install.sh at %s.\nContains only: %s\n' \
        "$STAMP" "${BACKUP_SCOPE[*]}" > "$backup/README.txt"
    # Rotate: keep the newest $BACKUP_KEEP.
    { ls -1d "$CLAUDE_HOME".bak.* 2>/dev/null || true; } | sort -r | tail -n "+$((BACKUP_KEEP + 1))" |
        while IFS= read -r old; do
            echo "  rotating out $old"
            rm -rf -- "$old"
        done
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
BUNDLED_SKILLS=(master-agent executor distill-repo ponytail-on-demand run-model-team coderpxC)
for skill in "${BUNDLED_SKILLS[@]}"; do
    mkdir -p "$CLAUDE_HOME/skills/$skill"
    cp -R "$REPO_ROOT/skills/$skill/"* "$CLAUDE_HOME/skills/$skill/"
done
if [ -d "$CODEX_HOME" ]; then
    CODEX_SKILLS=(master-agent executor ponytail-on-demand run-model-team coderpxG)
    for skill in "${CODEX_SKILLS[@]}"; do
        if [ -d "$CODEX_HOME/skills/$skill" ]; then
            # Sibling root, never inside skills/: a backup left in the live
            # skills root is discovered and loaded as a skill of its own.
            mkdir -p "$CODEX_HOME/skills.bak/$STAMP"
            cp -R "$CODEX_HOME/skills/$skill" "$CODEX_HOME/skills.bak/$STAMP/$skill"
        fi
        mkdir -p "$CODEX_HOME/skills/$skill"
        cp -R "$REPO_ROOT/skills/$skill/"* "$CODEX_HOME/skills/$skill/"
    done
    echo "  copied bundled skills -> ~/.codex/skills/"
fi


# Antigravity (agy) skills -> ~/.gemini/config/skills/
# Separate root from ~/.claude/skills: these are read by the agy CLI, not Claude.
if [ -d "$GEMINI_HOME" ]; then
    AGY_SKILLS=(fwa coderpxA)
    for skill in "${AGY_SKILLS[@]}"; do
        if [ -d "$GEMINI_HOME/skills/$skill" ]; then
            # Sibling root, never inside skills/: a backup left in the live
            # skills root is discovered and loaded as a skill of its own.
            mkdir -p "$GEMINI_HOME/skills.bak/$STAMP"
            cp -R "$GEMINI_HOME/skills/$skill" "$GEMINI_HOME/skills.bak/$STAMP/$skill"
        fi
        mkdir -p "$GEMINI_HOME/skills/$skill"
        cp -R "$REPO_ROOT/agy-skills/$skill/"* "$GEMINI_HOME/skills/$skill/"
    done
    echo "  copied agy skills -> ~/.gemini/config/skills/"
fi

# settings.json -- wire the managed hook block (handler-granular merge, dry-run first)
echo "[4/6] Wire managed hooks into ~/.claude/settings.json"
HOOKS_INSTALLER="$REPO_ROOT/scripts/hooks_install.py"
# --home is explicit: hooks_install defaults to Path.home(), which on Windows
# resolves from USERPROFILE and ignores a shell-set HOME -- so a Git Bash run
# would target the real profile instead of the one this script was pointed at.
# The dry-run needs the same `|| true` as the apply: it now exits 3 when
# collisions remain, and under `set -e` that aborted the install outright.
HOOKS_HOME="$(dirname "$CLAUDE_HOME")"
python3 "$HOOKS_INSTALLER" install --checkout "$REPO_ROOT" --home "$HOOKS_HOME" || true   # dry-run diff
hooks_exit=0
python3 "$HOOKS_INSTALLER" install --checkout "$REPO_ROOT" --home "$HOOKS_HOME" --apply || hooks_exit=$?
if [ "$hooks_exit" -eq 3 ]; then
    echo "  WARNING: hook block wired, but unresolved handlers remain." >&2
    echo "           Inspect:    python3 $HOOKS_INSTALLER status --home $HOOKS_HOME" >&2
    echo "           Claim them: python3 $HOOKS_INSTALLER install --checkout $REPO_ROOT --home $HOOKS_HOME --apply --reconcile" >&2
    HOOK_WARNING=1
elif [ "$hooks_exit" -ne 0 ]; then
    echo "hooks_install.py exited $hooks_exit -- the managed hook block was NOT wired." >&2
    exit "$hooks_exit"
else
    echo "  managed hook block wired (run: python3 $HOOKS_INSTALLER doctor)"
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
if [ "${HOOK_WARNING:-0}" -eq 1 ]; then
    echo "=== Install complete, WITH an unresolved hook block ==="
else
    echo "=== Install complete ==="
fi
echo
echo "Next steps:"
echo "  1. Review ~/.claude/CLAUDE.md and personalize the ecosystem table"
echo "  2. Review ~/.claude/settings.json hooks"
echo "  3. (Optional) Set up your private context repo for AI tool sharing"
echo "  4. Run: python ~/.claude/scripts/plan_catalog.py to generate PLANS.md"
echo "  5. Run: python ~/.claude/scripts/vision_catalog.py to generate VISIONS.md"
