# Plan Lifecycle Hooks

The system that ensures every plan/module-creating AI session reads the relevant context before working and updates state after.

## Why this exists

Without lifecycle hooks, plans land orphaned:
- Vision Current State stays stale
- PLANS.md drifts from reality
- IDEA_BOX entries linger after the work is done
- Operator loses cross-repo strategic picture

The hooks make context-loading and state-updating a hard contract for the AI, not a "should" that gets forgotten.

## How it works

### Three components

1. **`plan_context_loader.py`** (PRE-step) — reads:
   - Linked vision (via plan frontmatter `vision:` slug, or repo lookup)
   - Repo `IDEA_BOX.md` + global `ECOSYSTEM_IDEA_BOX.md`
   - Relevant sections of `PLANS.md` (cross-repo + in-progress + drafts for current repo)

   Output is wrapped in `<plan-context>...</plan-context>`. AI reads this BEFORE designing.

2. **`plan_context_updater.py`** (POST-step) — runs after work is committed:
   - Regenerates `PLANS.md` and `VISIONS.md`
   - Appends entry to vision auto-log (with `--shipped`)
   - Marks resolved IDEA_BOX entries `(DONE YYYY-MM-DD)` (with `--resolved-ideas`)

3. **`plan_keyword_detector.py`** (UserPromptSubmit hook) — auto-fires loader when prompt contains:
   - "nowy plan", "tworzymy plan", "nowy moduł"
   - "new plan", "create plan", "design plan", "new module"
   - "mode architect", "mode implement"
   - "/plan-ceo-review", "/plan-eng-review", "/plan-design-review", "/autoplan"

### Triggered by

| Trigger | PRE | POST | EPILOG_PAYLOAD |
|---------|-----|------|----------------|
| `mode architect` | ✓ | ✓ | required |
| `mode implement` | ✓ | ✓ | required |
| `mode ship` | ✓ | ✓ | required |
| `mode autoplan` | ✓ | ✓ | required |
| `/executor` | ✓ | ✓ | required |
| Keyword in prompt (any of the above) | ✓ (auto) | manual | optional |
| `mode debug` / `mode review` | ✗ | ✗ | n/a |

### EPILOG_PAYLOAD format

Before emitting `>> DONE` / `>> SHIPPED` / `>> ARCHITECTURE COMPLETE`:

```
EPILOG_PAYLOAD:
  start_sha: <SHA before any changes>
  end_sha: <git rev-parse HEAD now>
  plan_path: <plan path if known, else empty>
  committed: <true or false>
  resolved_ideas: <comma-separated IDEA_BOX slugs marked DONE, else empty>
```

The POST-step uses these values to call the updater with the right flags.

## Exceptions

- **R0** ad-hoc edits (typo fix, single-line tweak) — skip both
- **Pure debug/review** — skip PRE; skip POST unless plan status changed
- **Loader failure** — note it, continue work; never block

## What gets sanitized

The keyword detector and loader only READ files — they don't push anywhere. The optional `sync_ecosystem_context.py` does sanitize before pushing to a private context repo (regex strip P&L, broker IDs, absolute paths, tokens).
