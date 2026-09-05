---
name: run-model-team
description: Compatibility entry for an explicit model-team request; forward the existing task to CoderPX G worker coordination without a separate roster or workflow.
---

# Model-team compatibility entry

Read [CoderPX G](../coderpxG/SKILL.md) and its
[worker contract](../coderpxG/references/workers.md). Forward the current task,
plan path, authorization and lifecycle stage once. Do not start another
supervisor, select a separate roster or recursively invoke /fwf; there is no Codex CLI fallback.
Keep in-flight legacy receipts and limits on their original contract until explicitly migrated.
This compatibility file is not a recommended additional public skill.
