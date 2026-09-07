# Full-workflow execution handoff

Use this reference with full-workflow.md. It records the existing interface;
it is not another workflow or permission to alter a dispatcher at runtime.

## Stamps and validation

Read the current D:/APPS/_shared/coderpx/DISPATCHERS.md and actual dispatcher
before stamping. Each executable slice names one exclusive write-set, its
dependencies, validation and independent reviewer. For the currently observed
file-mode interface, the stamp is immediately below its heading, as plain text:

```text
### Slice P1 — bounded implementation
lane: chatgpt_cdp
executor: G
review: coderpx
mode: file
reason: explicit versioned contract
files: audit/plan_audit_packet.py
```

This is an example, not an executable task. Include the complete validated
dispatch.packet.v1 body when the dispatcher sends the slice body verbatim.
Its required sections and one writable file come from validate_packet(), not
from guessed schema. Use patch mode only where the current implementation
supports the actual source size and write-set. Never fabricate a dry-run receipt.

For a Codex executor the existing dry-run is:

```text
python D:/APPS/_shared/dispatch/dispatch.py plan "<plan>" --executor G --worktree "<absolute-owned-worktree>" --repo-root "<absolute-owned-worktree>" --receipts-dir "<existing-owner-receipts>" --dry-run
```

Use A only when the assigned executor is actually Antigravity. Read the emitted
chain as well as exit status: a legacy executable lane or forbidden CLI fallback
is a contract mismatch even when structural validation returns zero. Do not
dispatch that chain, invent a bypass flag, reset quota state, or substitute
local authorship. Preserve the refusal and return the mismatch to its owner.

## Execution and review

After stage clearance and existing scope authority, the same command without
--dry-run executes the prepared plan. Pass the actual existing GO provenance
through the supported argument for R2/R3; prose, SHA and agent assignment do
not manufacture operator authority. Keep the durable owner receipts and cap
state on continuation. Reconcile an ambiguous submit in its original attempt;
do not spend another round or change providers to resolve uncertainty.

The configured CDP worker authors substantive code. Codex applies and verifies
the real diff and validation results. Select an independent reviewer with a
different producer identity/model, through the configured workflow. Preserve
implementation-review/v1's exact head/base, source access and attestation.
No current review means NO_REVIEW, not a reason to grade the author's own work.

Before final reporting, generate the actual ownership ledger:

```text
python D:/APPS/_shared/dispatch/dispatch.py ledger "<existing-task-id>" --receipts-dir "<existing-owner-receipts>"
```

A missing ledger stays missing. Never type guessed author or model evidence.
Only heavy pytest acquires host:heavy; CDP retains independent cdp:* pools.
No browser, Playwright, document or Git operation waits on the pytest lease.
