# Workflow OS Section 3.7 Apply/Rollback Packet

Date: 2026-07-01
Risk: R2/R3 for any real permission change
Status: review packet only; no ACL writes executed

## Source

Manifest:

```text
design/security/write_segregation_path_manifest.json
```

Dry-run artifact:

```text
design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json
```

Validation:

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

If a clean non-default TSU branch is the reviewed input state, add an explicit branch override:

```powershell
  --allow-branch "D:/APPS/TSU=## codex/<accepted-branch>...origin/codex/<accepted-branch>"
```

Expected shape:

- identity: `pc-tsignal-flow\dszub`
- entries: 24
- non-noop entries: 22
- write-allowed no-op entries: 2
- `applies_acl=false`
- `requires_operator_go_before_apply=true`
- `preapply-check` should be `ok_without_go=true` and `ready_to_apply=false` until an exact R2/R3 apply token is supplied
- non-default TSU/Tsignal branches should require explicit `--allow-branch`

## Operator Gate

Do not execute any command in this packet without an explicit R2/R3 apply token naming the step. Broad tokens such as `go`, `ok go`, or `wykonaj caly plan` are not sufficient.

Minimum apply token:

```text
GO Section 3.7 R2/R3 apply pilot
```

Before apply, confirm the Windows identity. Current artifact targets:

```text
pc-tsignal-flow\dszub
```

## Repo-State Preflight

Run immediately before any apply:

```powershell
git -C "D:/dotclaude/dotclaude-ecosystem" status --short --branch
git -C "D:/APPS/TSU" status --short --branch
git -C "D:/APPS/Tsignal 5.0" status --short --branch
```

Current note at packet creation:

- `dotclaude-ecosystem`: clean except known operator WIP `skills/master-agent/SKILL.md`
- `D:/APPS/TSU`: clean, but on a work branch observed as `codex/renko-contract-fixture-admission`
- `D:/APPS/Tsignal 5.0`: clean on `main == origin/main`

If TSU or Tsignal branch/dirt is not explicitly accepted as reviewed input state, stop before apply.

The pre-apply checker enforces this mechanically by failing on unaccepted dirty state, failing on unaccepted branch state, and refusing `ready_to_apply=true` without an exact Section 3.7 R2/R3 apply pilot token.

Packet-only validation:

```powershell
python scripts/write_segregation_manifest.py validate-packet `
  design/handoffs/2026-07-01_workflow_os_37_apply_rollback_packet.md `
  --dry-run design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json
```

Apply evidence template:

```text
design/security/2026-07-01_section37_apply_evidence_template.json
```

Future apply evidence must validate with:

```powershell
python scripts/write_segregation_manifest.py validate-apply-evidence `
  design/security/<section37-apply-evidence>.json `
  --dry-run design/security/2026-07-01_observed_codex_identity_acl_dry_run_refresh.json
```

## Pilot Recommendation

Use the smallest low-blast pilot before any repo-wide apply:

1. `tsu-env` or another single operator-only file target if the operator confirms it is safe to probe.
2. If the operator prefers a non-secret pilot, regenerate a temporary test-only manifest for a disposable test path and do not use the trading-path artifact for the pilot.

Pilot must prove:

- apply command exit code captured
- intended denied write fails
- audit read still works
- allowed docs write still works
- rollback command exit code captured
- post-rollback behavior returns to expected state

## TSU Batch A: Operator-Only Files

Apply commands:

```powershell
icacls "D:\APPS\TSU\.env" /deny "pc-tsignal-flow\dszub:(W)"
```

Rollback commands:

```powershell
icacls "D:\APPS\TSU\.env" /remove:d "pc-tsignal-flow\dszub"
```

Entries:

- `tsu-env`

## TSU Batch B: Live State And Journal

Apply commands:

```powershell
icacls "D:\APPS\TSU\data\live_state*.db*" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\TSU\data\journal*" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\TSU\data\interlock" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\TSU\data\live_state*.db*" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\TSU\data\journal*" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\TSU\data\interlock" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsu-live-state-db`
- `tsu-journals`
- `tsu-interlocks`

## TSU Batch C: Broker And Approval Code

Apply commands:

```powershell
icacls "D:\APPS\TSU\src\tsu\broker" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\TSU\src\tsu\approve" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\TSU\src\tsu\broker" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\TSU\src\tsu\approve" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsu-broker-code`
- `tsu-approval-code`

## TSU Batch D: Runtime Authority Code

Apply commands:

```powershell
icacls "D:\APPS\TSU\src\tsu\core\journal.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\TSU\src\tsu\core\live_state.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\TSU\src\tsu\core\manifest.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\TSU\src\tsu\supervisor" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\TSU\src\tsu\core\journal.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\TSU\src\tsu\core\live_state.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\TSU\src\tsu\core\manifest.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\TSU\src\tsu\supervisor" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsu-core-runtime-authority`
- `tsu-supervisor`

## TSU Batch E: Decision Path Code

Apply commands:

```powershell
icacls "D:\APPS\TSU\src\tsu\interlock" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\TSU\src\tsu\lanes" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\TSU\src\tsu\risk" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\TSU\src\tsu\strategy" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\TSU\src\tsu\interlock" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\TSU\src\tsu\lanes" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\TSU\src\tsu\risk" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\TSU\src\tsu\strategy" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsu-decision-path-code`

## TSU Batch F: GUI Broker/Config Controls

Apply commands:

```powershell
icacls "D:\APPS\TSU\tsu-gui\src\components\*Broker*" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\TSU\tsu-gui\src\components\*ConfigWrite*" /deny "pc-tsignal-flow\dszub:(W)"
```

Rollback commands:

```powershell
icacls "D:\APPS\TSU\tsu-gui\src\components\*Broker*" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\TSU\tsu-gui\src\components\*ConfigWrite*" /remove:d "pc-tsignal-flow\dszub"
```

Entries:

- `tsu-gui-broker-config-controls`

## Tsignal Batch A: Operator-Owned Config

Apply commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\.env" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\active_accounts.json" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\config" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\.env" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\active_accounts.json" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\config" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsignal-env-and-account`
- `tsignal-config`

## Tsignal Batch B: Live State And Interlocks

Apply commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\data\*.db*" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\data\interlock" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\data\*.db*" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\data\interlock" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsignal-live-db`
- `tsignal-interlocks`

## Tsignal Batch C: Live Bridge

Apply commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\data\bridge\executor" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\Tsignal 5.0\data\bridge\tsignal" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\Tsignal 5.0\data\bridge\questrade" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\Tsignal 5.0\data\bridge\watchf" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\data\bridge\executor" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\Tsignal 5.0\data\bridge\tsignal" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\Tsignal 5.0\data\bridge\questrade" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\Tsignal 5.0\data\bridge\watchf" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsignal-live-bridge`
- `tsignal-watchf-bridge`

## Tsignal Batch D: Entrypoints And Trading Code

Apply commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\tsignal_bot.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\tsignal_headless.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\tsignal_webhook_handler.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\tsignal_order_panel.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\tsignal_settings.py" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\tsignal\trading" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\tsignal_bot.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\tsignal_headless.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\tsignal_webhook_handler.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\tsignal_order_panel.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\tsignal_settings.py" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\tsignal\trading" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsignal-entrypoints`
- `tsignal-trading-code`

## Tsignal Batch E: Feed Auth, Runtime, Interlock

Apply commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\tsignal\feed\questrade_*" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\tsignal\runtime" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\Tsignal 5.0\tsignal\interlock" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\tsignal\feed\questrade_*" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\tsignal\runtime" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\Tsignal 5.0\tsignal\interlock" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsignal-feed-auth`
- `tsignal-runtime-interlock-code`

## Tsignal Batch F: Order GUI

Apply commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\tsignal-gui\src\app\components\order-entry*" /deny "pc-tsignal-flow\dszub:(W)"
icacls "D:\APPS\Tsignal 5.0\tsignal-gui\src\app\panels\qt-rapid\*Order*" /deny "pc-tsignal-flow\dszub:(W)"
```

Rollback commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\tsignal-gui\src\app\components\order-entry*" /remove:d "pc-tsignal-flow\dszub"
icacls "D:\APPS\Tsignal 5.0\tsignal-gui\src\app\panels\qt-rapid\*Order*" /remove:d "pc-tsignal-flow\dszub"
```

Entries:

- `tsignal-order-gui`

## Tsignal Batch G: Heavy Live Assets

Apply commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\data" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\Tsignal 5.0\AI" /deny "pc-tsignal-flow\dszub:(W)" /T
icacls "D:\APPS\Tsignal 5.0\scratch\bench\models" /deny "pc-tsignal-flow\dszub:(W)" /T
```

Rollback commands:

```powershell
icacls "D:\APPS\Tsignal 5.0\data" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\Tsignal 5.0\AI" /remove:d "pc-tsignal-flow\dszub" /T
icacls "D:\APPS\Tsignal 5.0\scratch\bench\models" /remove:d "pc-tsignal-flow\dszub" /T
```

Entries:

- `tsignal-heavy-live-assets`

## No-Op Write-Allowed Entries

These entries must remain writable for agents and have no ACL commands in the dry-run:

- `tsu-design-docs`
- `tsignal-design-docs`

## Probe Plan Per Batch

Before apply:

1. Pick one command from the batch.
2. Identify a matching rollback command.
3. Pick one expected denied-write target.
4. Pick one expected read target.
5. Pick one allowed docs write target.

After apply:

1. Record apply command exit code.
2. Attempt denied write and record failure.
3. Attempt read and record success.
4. Attempt allowed docs write and cleanup.
5. Run rollback.
6. Record rollback exit code.
7. Re-run the write/read/docs probes after rollback if this is the pilot.

## Stop Conditions

Stop and rollback if:

- any apply command exits nonzero
- `validate-packet` fails before apply
- denied write unexpectedly succeeds
- audit read unexpectedly fails
- allowed docs write unexpectedly fails
- `validate-apply-evidence` fails on the recorded evidence
- rollback command exits nonzero
- a command target is not present in the dry-run artifact
- the operator did not explicitly approve the batch being applied

## Post-Packet Status

This packet completes the runbook's Phase 2 review artifact. It does not complete Section 3.7 apply.
