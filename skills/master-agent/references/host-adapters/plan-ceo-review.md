---
name: plan-ceo-review
description: Review a plan's problem, value, scope and acceptance criteria. Reuse the supplied plan and settled decisions; return a product decision to the owning workflow.
---

# CEO plan review

Resolve the installed protocol library: `~/.codex/skills/master-agent/references/protocols`
on Codex, `~/.claude/skills/master-agent/references/protocols` on Claude.
Read `00-contract.md` and `ceo-review.md` from that library, then perform the role.
If either file is missing, report its exact path; do not claim the v2 role ran.

Use the plan already supplied by the user or current workflow. `/fwf` and `/fwp`
own routing, question policy and the next stage. A completed CEO review returns
its decision to that owner; it does not start another full workflow.

Outside a workflow, resolve reversible scoping choices from the user's brief.
Ask only when the answer changes the intended product or acceptance criteria.
An accepted scope and standing GO are inputs, not questions to repeat.
Keep technical feasibility questions for engineering unless they invalidate
the product decision. Preserve explicit requests for expansion or reduction.

This maintained adapter replaces the role entry text only. Browser, design,
release and other gstack capabilities remain separate installed skills.
