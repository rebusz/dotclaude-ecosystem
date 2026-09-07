# Maintained host entry templates

These five Markdown files are source templates, not installed skills.
Their runtime bodies load the canonical protocol tree installed with
master-agent. The installer must copy each template only to the explicitly
mapped entrypoint and retain neighboring upstream files and user metadata.

| Template | Codex target under home | Claude target under home |
|---|---|---|
| plan-ceo-review.md | .codex/skills/gstack-plan-ceo-review/SKILL.md | .claude/skills/gstack/plan-ceo-review/SKILL.md |
| plan-eng-review.md | .codex/skills/gstack-plan-eng-review/SKILL.md | .claude/skills/gstack/plan-eng-review/SKILL.md |
| investigate.md | .codex/skills/gstack-investigate/SKILL.md | .claude/skills/gstack/investigate/SKILL.md |
| review.md | .codex/skills/gstack-review/SKILL.md | .claude/skills/gstack/review/SKILL.md |
| diagnoze.md | .codex/skills/diagnoze/SKILL.md | .claude/skills/diagnoze/SKILL.md |

These paths are the observed host layout for this migration. Do not install
additional same-name skill directories or edit upstream templates. Back up the
exact target files outside discovery roots and record before/after hashes.
An upstream gstack regeneration may replace an adapter: report that as drift
and reapply only after comparing the regenerated entry and release manifest.
Do not automatically run upgrades or overwrite a concurrently edited target.

The coordinated installer must select this release rather than refreshing
every ecosystem artifact. Its check mode validates the whole required library,
these entries and command targets before any write. Global role installation
does not migrate repository-local Prompts/master_agent.md domain protocols.
