---
name: review
description: Review an actual implementation diff for actionable correctness and regression findings, with exact-source evidence and independent authorship.
---

# Implementation review

Resolve the installed protocol library: `~/.codex/skills/master-agent/references/protocols`
on Codex, `~/.claude/skills/master-agent/references/protocols` on Claude.
Read `00-contract.md` and `implementation-review.md`, then perform the role.
If the library is missing, identify the paths and retain NO_REVIEW for v2.

Use the existing workflow's review owner, packet renderer and reviewers.
An author cannot supply their own independent clearance. Preserve the
`implementation-review/v1` packet header, full head/base, inventory and
attestation. This adapter does not introduce a new review schema.

Read applicable repository review checklists and domain contracts. Existing
gstack supporting checklists remain available beside this installed entry;
load the relevant ones when the diff needs them. Do not replay the upstream
entrypoint as a second workflow or substitute style findings for defects.
Return findings and evidence to the current review stage, which owns fixes
and landing under the user's standing authorization.
