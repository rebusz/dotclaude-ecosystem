# IDEA_BOX System

Per-repo and global backlog of features, bugs, refactors, ideas. Cheap to add, easy to scan.

## Two scopes

### Per-repo: `<repo>/IDEA_BOX.md`

Repo-local backlog. Features, bugs, TODOs, refactoring candidates that affect ONLY that repo.

### Global: `~/.claude/ECOSYSTEM_IDEA_BOX.md`

Cross-cutting concerns that affect multiple repos: bridge contracts, phase gates, architectural policies. NOT feature requests for a specific repo.

## Format (no enforced schema, just convention)

```markdown
# Idea Box — <Repo Name>

## Feature Ideas
- [P1][S] Quick wins (high priority, small effort)
- [P2][M] Medium-priority, medium effort
- [P3][L] Nice-to-have, large effort
- ~~[P1][S] Done items, struck through with date~~ DONE 2026-04-15 (commit abc1234)

## Bug Fixes / TODOs
- [P1][M] Bug description with reproducer + scope

## New Modules
- [P2][L] Larger pieces of work that need their own plan eventually

## Test Coverage Gaps
- [P2][S] Specific test coverage holes worth filling

## Refactoring Ideas
- [P3][M] Cleanup ideas
```

### Tags

- **Priority**: `[P1]` urgent, `[P2]` standard, `[P3]` someday
- **Size**: `[S]` <1 day, `[M]` 1-3 days, `[L]` >3 days
- **Cross-repo**: `[CROSS-REPO: TargetRepo]` when ripple needed

### State transitions

- New idea → bullet appended (any of the categories)
- Picked up for work → planning happens, idea stays in box
- Shipped → strikethrough + DONE marker + commit reference

When an entry is shipped, the `plan_context_updater.py --resolved-ideas <slug>` flag automatically appends `(DONE YYYY-MM-DD)` to lines containing the slug. Optional — can also be done manually.

## Capture flow

When the user says one of:
- "we should..."
- "someday..."
- "TODO:..."
- "idea:..."
- "add to backlog"

→ AI offers to append to the most relevant IDEA_BOX (per-repo first, global only for cross-cutting).

Per-repo CLAUDE.md should mention this so the AI auto-suggests.

## Cross-repo ranked digest

```bash
python ~/.claude/scripts/idea_digest.py
```

Reads all IDEA_BOX files (per-repo + global), ranks by P1→P3, flags `[CROSS-REPO]` items at top, prints to stdout.

## Why this is separate from MEMORY.md

| | MEMORY.md | IDEA_BOX.md |
|---|---|---|
| Direction | past | future |
| Trigger | "remember that..." | "we should..." |
| Lifetime | persistent learnings | actionable backlog |
| Tone | observation, lesson, fact | proposal, intent |
| Curation | auto-prune stale | manual prune when shipped |
