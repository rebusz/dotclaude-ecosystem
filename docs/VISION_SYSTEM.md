# Vision System

Strategic layer above tactical plans. Visions answer **WHY** a group of plans exists.

## Concept

Three layers:

| Layer | Lifetime | Purpose | File |
|-------|----------|---------|------|
| **Vision** | months-years | strategic goal, Definition of Done, manually-curated roadmap | `<repo>/design/visions/<slug>.md` |
| **Plan** | days-weeks | tactical implementation, scoped, dated, status-tracked | `<repo>/design/plans/YYYY-MM-DD_<slug>.md` |
| **IDEA_BOX** | minutes-months | unranked future ideas, backlog buffer | `<repo>/IDEA_BOX.md` |

A plan attaches upward to a vision via frontmatter:

```yaml
---
title: "..."
date: 2026-05-09
status: draft
vision: ts-trustworthy-execution    # ← attaches to design/visions/ts-trustworthy-execution.md
---
```

The catalog generator (`vision_catalog.py`) walks all repos, parses plan frontmatter, and computes per-vision progress (shipped / in-progress / pending).

## Vision file format

```markdown
---
title: "Vision title"
slug: my-vision
status: in-progress     # draft, in-progress, plan-ready, shipped
created: 2026-01-15
target: 2026-06-30
owner: <name>
repos: [repo-1]
primary_repo: repo-1
tags: [...]
contracts: [FB-04]      # frozen boundaries this vision respects
---

# Vision title

## Why
<paragraph explaining the strategic motivation>

## Definition of Done
- <bullet 1>
- <bullet 2>

## Roadmap
1. - [ ] <milestone 1>
2. - [ ] <milestone 2>
3. - [x] <milestone 3 done>

<!-- BEGIN AUTO-STATE - managed by vision_catalog.py; manual edits will be overwritten -->
## Current State
- Plans shipped: 5 / 12
- Plans in progress: 2
- Plans pending: 5
- Open ideas waiting: 3
- Last activity: 2026-05-09
- Recommended next plan: **<computed-from-roadmap>**
<!-- END AUTO-STATE -->

## Notes & Decisions
<freeform>

<!-- BEGIN AUTO-LOG - managed by plan_context_updater.py with --shipped -->
- 2026-05-09 — plan-slug: shipped (note)
<!-- END AUTO-LOG -->
```

## Cross-repo visions

A vision can span multiple repos:

```yaml
repos: [tsignal-5, watchf, tsignallab]
primary_repo: tsignal-5
```

The primary repo holds the canonical file. The catalog flags it as CROSS-REPO.

## CLI

```bash
python ~/.claude/scripts/vision.py list                  # show all visions
python ~/.claude/scripts/vision.py show <slug>           # show one
python ~/.claude/scripts/vision.py new --title "..." --repo <repo> --why "..." --dod "a;b;c"
python ~/.claude/scripts/vision.py attach <plan-path> <slug>
python ~/.claude/scripts/vision.py next <slug>           # show next roadmap item
python ~/.claude/scripts/vision.py sync                  # regen catalog
```

## Auto-update flow

When a plan attached to a vision ships:

1. `plan_context_updater.py --plan <plan> --shipped` runs
2. Updater regenerates `VISIONS.md` (which also rewrites the `## Current State` AUTO-STATE block in the vision file)
3. Updater appends a line to the vision's AUTO-LOG section

Vision Why/DoD/Roadmap sections are NEVER auto-modified. Only AUTO-STATE and AUTO-LOG.
