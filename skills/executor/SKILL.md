---
name: executor
description: >
  Launch the autonomous executor agent. Use AFTER a plan has been approved (GO given).
  Runs in an isolated worktree, implements code, runs tests, commits — with minimal
  interruption. Equivalent to invoking the executor subagent for approved R2/R3 work.
triggers:
  - /executor
---

## STEP 0 — Plan Lifecycle PRE-step (MANDATORY)

**Before launching the subagent**, run:

```bash
python ~/.claude/scripts/plan_context_loader.py --cwd "$PWD" --plan <plan-path-from-args>
```

Read the `<plan-context>` block. The executor must respect:
- vision Why+DoD constraints (do not silently expand scope past DoD)
- ideas being resolved (track slugs to pass to POST-step)
- in-progress related plans (avoid double-implementation)

If no plan path can be inferred from $ARGS, run with just `--cwd "$PWD"`.

## STEP 1 — Launch executor subagent

Use the Agent tool to launch the executor subagent with the following task:

$ARGS

The executor agent is defined at d:/APPS/Tsignal 5.0/.claude/agents/executor.md.
It runs in worktree isolation with permissionMode: acceptEdits.
Proceed autonomously — pause only on unexpected failures or scope ambiguity.

The executor agent must include this block at the end of its completion report:

```
EPILOG_PAYLOAD:
  start_sha: <SHA before any changes>
  end_sha: <git rev-parse HEAD now>
  worktree_path: <"main" or absolute worktree path>
  committed: <true or false>
  plan_path: <plan path if known, else empty>
  resolved_ideas: <comma-separated IDEA_BOX slugs marked DONE, else empty>
```

## STEP 2 — Plan Lifecycle POST-step (MANDATORY before epilog)

After receiving the payload and BEFORE the master-agent Post-Mode Epilog, run:

```bash
python ~/.claude/scripts/plan_context_updater.py --plan <plan_path> --shipped \
    --note "executor: $ARGS_summary" \
    [--resolved-ideas "<slugs from payload>"]
```

If `plan_path` is empty in payload, skip with a warning (catalogs only get regen via implicit nightly cycle, not blocking).

## STEP 3 — Post-Mode Epilog

After STEP 2 completes, run the Post-Mode Epilog from master-agent SKILL.md
using the diff range start_sha..end_sha (or git diff HEAD if uncommitted).
The executor subagent does NOT run its own epilog — epilog runs in parent context only.
