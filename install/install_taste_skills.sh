#!/usr/bin/env bash
# Reproducible / wipe-recovery installer for the curated taste-skill set.
# Reads skills/taste-skill.lock.json, clones the pinned commit, installs via the
# Vercel skills CLI (copy mode, global), then copies into Codex/Cursor native dirs
# (the CLI copy-mode does not populate those reliably). Idempotent.
set -euo pipefail
ECO_ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="$ECO_ROOT/skills/taste-skill.lock.json"
[ -f "$LOCK" ] || { echo "Lockfile not found: $LOCK" >&2; exit 1; }

# Every lockfile value reaches git, npx or rm -rf, so it goes through the one
# validator first (plain-assignment command substitution keeps set -e armed;
# process substitution would swallow a rejection).
VALIDATE="$ECO_ROOT/install/taste_lock.py"
SHA=$(python "$VALIDATE" "$LOCK" commit)
SOURCE=$(python "$VALIDATE" "$LOCK" source)
CLI=$(python "$VALIDATE" "$LOCK" cli)
SKILLS_RAW=$(python "$VALIDATE" "$LOCK" installed)
AGENTS_RAW=$(python "$VALIDATE" "$LOCK" agents)
mapfile -t SKILLS <<<"$SKILLS_RAW"
mapfile -t AGENTS <<<"$AGENTS_RAW"

VENDOR="$ECO_ROOT/vendor/taste-skill"
echo "taste-skill restore -> commit $SHA"
rm -rf -- "$VENDOR"
git clone --quiet -- "$SOURCE" "$VENDOR"
git -C "$VENDOR" -c advice.detachedHead=false checkout --quiet --detach "$SHA"
[ "$(git -C "$VENDOR" rev-parse HEAD)" = "$SHA" ] || { echo "checkout is not $SHA" >&2; exit 1; }

SARGS=(); for s in "${SKILLS[@]}"; do SARGS+=(--skill "$s"); done
AARGS=(); for a in "${AGENTS[@]}"; do AARGS+=(-a "$a"); done
npx --yes "$CLI" add "$VENDOR" "${SARGS[@]}" "${AARGS[@]}" --global --copy -y

CANON="$HOME/.agents/skills"
for dst in "$HOME/.codex/skills" "$HOME/.cursor/skills-cursor"; do
  [ -d "$dst" ] || continue   # agent not installed -> skip
  for s in "${SKILLS[@]}"; do
    [ -d "$CANON/$s" ] && { rm -rf -- "$dst/$s"; cp -r -- "$CANON/$s" "$dst/$s"; }
  done
  echo "  copied ${#SKILLS[@]} skills -> $dst"
done

# 4. Redeploy ecosystem-local overlays (house rules) into every agent skill dir
OVERLAYS=(frontend-house-rules)
OVERLAY_DIRS=("$HOME/.claude/skills" "$HOME/.agents/skills" "$HOME/.codex/skills" "$HOME/.cursor/skills-cursor")
for ov in "${OVERLAYS[@]}"; do
  osrc="$ECO_ROOT/skills/$ov"
  [ -d "$osrc" ] || continue
  for od in "${OVERLAY_DIRS[@]}"; do
    [ -d "$od" ] || continue
    rm -rf "$od/$ov"; cp -r "$osrc" "$od/$ov"
  done
  echo "  deployed overlay $ov"
done
echo "Done. Review skills before use; they run with full agent permissions."
