#!/usr/bin/env bash
# Reproducible / wipe-recovery installer for the curated taste-skill set.
# Reads skills/taste-skill.lock.json, clones the pinned commit, installs via the
# Vercel skills CLI (copy mode, global), then copies into Codex/Cursor native dirs
# (the CLI copy-mode does not populate those reliably). Idempotent.
set -euo pipefail
ECO_ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
LOCK="$ECO_ROOT/skills/taste-skill.lock.json"
[ -f "$LOCK" ] || { echo "Lockfile not found: $LOCK" >&2; exit 1; }

read -r SHA SOURCE < <(python -c "import json,sys;d=json.load(open(sys.argv[1]));print(d['pinned_commit'],d['source'])" "$LOCK")
mapfile -t SKILLS < <(python -c "import json,sys;[print(s) for s in json.load(open(sys.argv[1]))['installed']]" "$LOCK")
mapfile -t AGENTS < <(python -c "import json,sys;[print(a) for a in json.load(open(sys.argv[1]))['agents']]" "$LOCK")

VENDOR="$ECO_ROOT/vendor/taste-skill"
echo "taste-skill restore -> commit $SHA"
rm -rf "$VENDOR"; git clone "$SOURCE" "$VENDOR" >/dev/null; git -C "$VENDOR" checkout "$SHA" >/dev/null

SARGS=(); for s in "${SKILLS[@]}"; do SARGS+=(--skill "$s"); done
AARGS=(); for a in "${AGENTS[@]}"; do AARGS+=(-a "$a"); done
npx --yes skills add "$VENDOR" "${SARGS[@]}" "${AARGS[@]}" --global --copy -y

CANON="$HOME/.agents/skills"
for dst in "$HOME/.codex/skills" "$HOME/.cursor/skills-cursor"; do
  [ -d "$dst" ] || continue   # agent not installed -> skip
  for s in "${SKILLS[@]}"; do
    [ -d "$CANON/$s" ] && { rm -rf "$dst/$s"; cp -r "$CANON/$s" "$dst/$s"; }
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
