---
name: truthdeck
description: Produce deterministic evidence snapshots and one advisory next action without mutating application repositories or runtime.
---

# TruthDeck

Use TruthDeck when a task needs current Git, plan, PR/CI, exact-head review, handoff, or registered read-only runtime evidence.

1. Run `truthctl snapshot` with explicit repositories and evidence paths.
2. Preserve every gate state and reason code exactly; `UNKNOWN`, `HOLD`, and `BLOCKED` are not interchangeable.
3. Use `truthctl next --snapshot <path>` for one deterministic advisory action.
4. Never turn the command preview into authority. Broker/order operations, runtime mutation, generic shell execution, and application-repo writes are outside this skill.
5. For handoffs, require both the explicit path and expected SHA-256.
6. Use `--installation-home` only for explicit installation/MCP readback; never infer it from the repository merge state.

If no `truthctl` shim is installed, use the canonical command reported by `truthdeck_install.py status`.
