---
name: plan-eng-review
description: Review a known plan for executable contracts, ownership, failure handling, validation and delivery. Produce actionable slices for the current workflow.
---

# Engineering plan review

Resolve the installed protocol library: `~/.codex/skills/master-agent/references/protocols`
on Codex, `~/.claude/skills/master-agent/references/protocols` on Claude.
Read `00-contract.md` and `eng-review.md`, then perform the role. Missing files
must be reported with their paths; do not claim v2 execution from a fallback.

Use the supplied plan and CEO decision. Do not ask what to review when the
target is already known. Apply the owning `/fwf` or `/fwp` question policy,
stamp format, author routing and dispatcher validation. Return to that same
workflow after the review. A review report is not executable dispatch evidence.

Trace a consequential finding to actual source and check the counterargument.
Prefer a complete implementation slice over a quota of findings or files.
Reviewing many files is not itself a reason to cut accepted scope.
Separate unit, integration and model-evaluation evidence; a passing parser
test cannot establish prompt quality or full transmission through CDP.
