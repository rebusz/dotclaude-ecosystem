# Workflow OS Remaining Gates Readback

Date: 2026-07-01
Risk: R0 readback
Status: shipped scope complete; future gated work remains

## Current State

Workflow OS shipped scope is complete. Recent committed readback before this R1 refresh:

```text
b2f52ea docs(workflow-os): record remaining gated work
```

`python scripts/workflow_os_completion.py` reports `ready=true`.

`python scripts/idea_digest.py workflow-triggers --file design/workflow_os_revisit_triggers.json` reports:

```text
triggered=0 completed=5 killed=4 deferred=0 manual=0 blocked=0
```

The only dirty file in `dotclaude-ecosystem` is `skills/master-agent/SKILL.md`, which is operator/other-session WIP and outside Workflow OS commits.

## Remaining Gates

### Section 3.7 Apply

Section 3.7 is not executable from a broad "go" or from the shipped Workflow OS scope. It is R2/R3 future work and requires an explicit operator GO naming the write-deny apply step.

Current boundary check:

- `D:/APPS/TSU` is clean on `master == origin/master`.
- `D:/APPS/Tsignal 5.0` is clean on `main == origin/main`.

Refreshed review-only dry-run artifact:

```text
design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json
```

Detailed apply runbook:

```text
design/handoffs/2026-07-01_workflow_os_37_apply_runbook.md
```

Apply/rollback review packet:

```text
design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md
```

Sanity readback:

- `applies_acl=false`
- `requires_operator_go_before_apply=true`
- 24 manifest entries
- 22 non-noop entries
- no missing apply/rollback command pairs

Repeatable validation:

```powershell
python scripts/write_segregation_manifest.py validate-dry-run `
  design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json `
  --manifest design/security/write_segregation_path_manifest.json
```

Full pre-apply check:

```powershell
python scripts/write_segregation_manifest.py preapply-check `
  --manifest design/security/write_segregation_path_manifest.json `
  --dry-run design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json `
  --packet design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md `
  --allow-dirty skills/master-agent/SKILL.md
```

The next executable token must be explicit, for example:

```text
GO §3.7 R2/R3 apply pilot
```

Before any apply:

- TSU and Tsignal repo states must be quiesced or explicitly accepted.
- The dry-run artifact must include apply and rollback commands.
- `validate-dry-run` must pass against the source manifest.
- `preapply-check` must report `ok_without_go=true`.
- Rollback commands must be reviewed.
- A write probe and read probe must be defined.
- Operator must confirm the Windows identity to deny writes for.

### Manual Triggers

No manual trigger is active now. These stay parked:

- `impeccable-layer`: only when a real GUI/web build starts.
- `deer-flow-after-paper-week`: only after PAPER WEEK ships and LAB research outgrows existing deep-research/fusion.
- `autoresearch-gpu-host`: only after PAPER WEEK ships and an overnight GPU host exists.
- `capability-registry-generated`: only after at least three gated tools pass section 9.

## Decision

Do not mark Section 3.7 apply complete. Do not execute ACL writes. The R1 dry-run refresh is complete, but real permission changes still require a separate R2/R3 apply GO.
