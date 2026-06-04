# Compact Handoff Template

Use this when a research phase ends, context is swollen, or work must continue
in a fresh session. Keep it short enough to paste into a new thread without
dragging old transcript history along.

```markdown
HANDOFF <short-scope> | <risk-class> | <YYYY-MM-DD HH:mm local>

Repo/cwd:
- <absolute repo path>

Branch/HEAD:
- <branch> @ <short-sha>

Dirty tree:
- <clean OR exact owned files changed/staged>
- Unrelated user/WIP changes: <none OR exact boundary>

Done:
- <3-7 bullets of durable facts, commits, or artifacts>

Validation:
- <commands run and pass/fail summary>
- Raw artifacts: <paths OR none>

Blocker/stop reason:
- <why work paused or what gate is next>

No-go boundaries:
- <runtime/order/broker/hardware/account/config limits>

Next token:
- <exact GO token or exact next command>
- Before executing: refresh repo truth, branch/HEAD, dirty tree, plan context,
  and task-specific safety contracts.
```

Rules:

- A handoff is context, not standing permission. Refresh current repo truth
  before executing it.
- Include no-go boundaries even for docs/tooling work.
- Do not include secrets, raw env dumps, broker/account payloads, or large logs.
- Prefer links/paths to artifacts over pasted output.
- If validation was skipped, say why.
