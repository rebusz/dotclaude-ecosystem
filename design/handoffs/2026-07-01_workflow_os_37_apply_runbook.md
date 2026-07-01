# Workflow OS Section 3.7 Apply Runbook

Date: 2026-07-01
Risk: R2/R3 for any real permission change
Status: runbook only; no ACL writes executed

## Boundary

This runbook exists to make the next Section 3.7 step explicit. It does not execute ACL commands and does not mark apply complete.

Do not run any generated `icacls` command unless the operator gives an explicit token naming the apply step, for example:

```text
GO §3.7 R2/R3 apply pilot
```

The broad tokens `go`, `ok go`, `dzialaj`, or `wykonaj caly plan` are not sufficient for this step.

## Current Inputs

Path manifest:

```text
design/security/write_segregation_path_manifest.json
```

Current review-only dry-run artifact:

```text
design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json
```

Apply/rollback review packet:

```text
design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md
```

Observed coding/advisory identity in that artifact:

```text
pc-tsignal-flow\dszub
```

Dry-run preflight:

```powershell
python scripts/write_segregation_manifest.py validate-dry-run `
  design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json `
  --manifest design/security/write_segregation_path_manifest.json
```

Full pre-apply check, still without applying ACLs:

```powershell
python scripts/write_segregation_manifest.py preapply-check `
  --manifest design/security/write_segregation_path_manifest.json `
  --dry-run design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json `
  --packet design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md `
  --allow-dirty skills/master-agent/SKILL.md
```

That command should report `ok_without_go=true` when dry-run, packet, and repo state are acceptable. It should still report `ready_to_apply=false` until an exact R2/R3 apply token is supplied.

Expected current shape:

- `ok=true`
- `applies_acl=false`
- `requires_operator_go_before_apply=true`
- 24 manifest entries
- 22 non-noop entries

## Phase 0: Identity Decision

1. Confirm whether `pc-tsignal-flow\dszub` is the intended Windows identity for coding/advisory agents.
2. If not, provide the exact identity in `<MACHINE>\<user>` or `<DOMAIN>\<user>` form.
3. Regenerate the dry-run artifact only if the identity changes:

```powershell
python scripts/write_segregation_manifest.py dry-run-acl `
  design/security/write_segregation_path_manifest.json `
  --agent-identity "<MACHINE-or-DOMAIN>\<agent-user>" `
  --output design/security/<date>_observed_codex_identity_acl_dry_run_refresh.json
```

4. Run `validate-dry-run` against the regenerated artifact.
5. Run `preapply-check` against the dry-run and packet.
6. Commit the identity refresh before any apply work.

## Phase 1: Repo-State Preflight

Before any ACL apply, capture and review:

```powershell
git -C "D:/dotclaude/dotclaude-ecosystem" status --short --branch
git -C "D:/APPS/TSU" status --short --branch
git -C "D:/APPS/Tsignal 5.0" status --short --branch
```

Required interpretation:

1. `dotclaude-ecosystem` may have only known operator WIP outside the apply slice, such as `skills/master-agent/SKILL.md`.
2. `D:/APPS/TSU` must be clean, or the operator must explicitly accept the current branch and dirt as the reviewed input state.
3. `D:/APPS/Tsignal 5.0` must be clean, or the operator must explicitly accept the current branch and dirt as the reviewed input state.
4. If TSU/Tsignal contain unreviewed WIP, stop before apply.
5. Run `preapply-check`; it must report `ok_without_go=true` before the apply token can be honored.

Current note as of this runbook creation: TSU was observed on branch `codex/renko-producer-contract-spec` with an untracked design artifact. That is not a blocker to this R0 runbook, but it is a blocker to unattended apply.

## Phase 2: Dry-Run and Rollback Packet

Create or refresh the apply packet from the dry-run artifact before running any command:

1. Count all non-noop entries.
2. Group entries by repo and class.
3. Extract rollback commands into a human-readable packet.
4. Confirm every apply command has one rollback command.
5. Confirm every command targets the same identity.
6. Confirm all commands are `icacls /deny` for apply or `icacls /remove:d` for rollback.
7. Confirm no command uses `/grant`.
8. Commit the packet as docs before apply.

Current packet:

```text
design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md
```

Minimum packet sections:

- apply identity
- apply batches
- rollback commands
- write probe plan
- read probe plan
- allowed-write probe plan
- stop conditions

## Phase 3: Probe Design

Define probes before touching ACLs.

Write-deny probe:

1. Pick one disposable target from the pilot batch.
2. Attempt an agent-context write that should fail.
3. Record the exact error or nonzero exit.
4. Confirm no partial file remains.

Read probe:

1. Read the same protected path or a sibling protected path.
2. Confirm read still succeeds for audit/review use.
3. Record the command and output shape.

Allowed-write probe:

1. Write to an explicitly allowed planning path, for example a scratch file under a safe docs location.
2. Delete the scratch file.
3. Confirm normal docs/design work is not broken.

Runtime-owner probe:

1. Do not ask the coding agent to act as live runtime owner.
2. Operator or runtime owner must confirm the live owner is not locked out before wider apply.

## Phase 4: Pilot Apply

Only after explicit operator token:

```text
GO §3.7 R2/R3 apply pilot
```

Pilot rules:

1. Apply the smallest useful subset.
2. Prefer a low-blast-radius operator-only or disposable test target before live-brain-only paths.
3. Do not apply the full TSU/Tsignal manifest in the pilot.
4. Run write, read, allowed-write, and rollback probes immediately.
5. If any probe behaves unexpectedly, stop and rollback.

Pilot success evidence:

- apply command exit code captured
- denied write fails for the coding/advisory identity
- audit read still works
- allowed docs write still works
- rollback command exit code captured
- post-rollback write behavior returns to expected state

## Phase 5: TSU Batches

After pilot success and a separate operator GO for TSU batches:

1. TSU operator-only batch:
   - `.env`
   - operator-owned config or account material
2. TSU persistence batch:
   - live state database globs
   - journal destinations
   - interlock directories
3. TSU runtime/order batch:
   - broker/order/runtime authority paths
   - strategy/risk/interlock modules named by the manifest
4. TSU allowed-write verification:
   - design docs remain writable where classified as `write-allowed-for-agents`

Each batch requires:

- apply command list
- rollback command list
- write/read probes
- batch-specific stop condition
- commit or handoff note after successful validation

## Phase 6: Tsignal Batches

After TSU batches and a separate operator GO for Tsignal batches:

1. Tsignal operator-only batch:
   - `.env`
   - active account/config material
2. Tsignal runtime/interlock batch:
   - runtime authority paths
   - interlock paths
3. Tsignal order/control batch:
   - broker/order GUI or order-control paths
4. Tsignal bridge/heavy-asset batch:
   - paths that should be read-only or live-owner-only per manifest

Each batch requires the same apply, rollback, probe, and stop-condition evidence as TSU.

## Phase 7: Post-Apply Verification

After all approved batches:

1. Re-run dry-run validator against the artifact used for apply.
2. Confirm all applied commands have recorded rollback commands.
3. Confirm coding/advisory identity cannot write protected paths.
4. Confirm coding/advisory identity can still read allowed audit surfaces.
5. Confirm docs/design paths classified as writable remain writable.
6. Confirm TSU/Tsignal runtime owners are not blocked.
7. Confirm no generated command changed broker/order/runtime code.
8. Capture final repo statuses for dotclaude, TSU, and Tsignal.

## Phase 8: Artifact Updates

Only after successful apply and verification:

1. Update `design/security/workflow_os_37_operator_decision.json` from `closed_plan_only` to an apply-specific status.
2. Add the apply evidence artifact under `design/security/`.
3. Update `design/audits/2026-06-29_workflow_os_completion_audit.md`.
4. Update `design/handoffs/2026-06-29_workflow_os_operator_gate_packet.md`.
5. Re-run:

```powershell
python scripts/workflow_os_completion.py
python scripts/write_segregation_manifest.py validate design/security/write_segregation_path_manifest.json
python scripts/write_segregation_manifest.py validate-dry-run `
  design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json `
  --manifest design/security/write_segregation_path_manifest.json
python -m pytest scripts/tests -q
```

6. Commit and push only the Workflow OS evidence/doc changes.

## Stop Conditions

Stop before apply if any of these is true:

- operator identity is unclear
- TSU/Tsignal repo state is not clean or explicitly accepted
- `validate-dry-run` fails
- `preapply-check` does not report `ok_without_go=true`
- rollback commands are missing or unreviewed
- probe commands are undefined
- the requested action touches broker/order path beyond OS-level write-deny
- the token is a broad `go` rather than an explicit R2/R3 apply token

Stop after apply and rollback immediately if any of these is true:

- denied write unexpectedly succeeds
- audit read unexpectedly fails
- allowed docs write unexpectedly fails
- runtime owner appears locked out
- rollback command fails
- any command targets a path outside the manifest-reviewed scope
