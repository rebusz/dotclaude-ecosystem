# Workflow OS Section 3.7 Observed Identity Readback

Date: 2026-06-29
Risk: R1 review artifact only
Parent plan: `design/plans/2026-06-29_mechanical_write_segregation_safety.md`
Parent audit: `design/audits/2026-06-29_workflow_os_completion_audit.md`

## What Changed

Generated a review-only ACL dry-run artifact from the current Codex process identity:

```text
pc-tsignal-flow\dszub
```

Artifact:

```text
design/security/2026-06-29_observed_codex_identity_acl_dry_run.json
```

## Readback

- `applies_acl=false`
- `requires_operator_go_before_apply=true`
- `entries=24`
- `apply_commands=39`
- `rollback_commands=39`

## Boundary

This is not an applied ACL change and not an operator-approved identity decision. It is only a concrete candidate artifact for review. Do not execute any generated `icacls` command without refreshed live repo truth, quiesced TSU/Tsignal repos, rollback review, and explicit R2/R3 operator GO naming the apply step.
