# HANDOFF — CONDUCTOR INSTALL RUNTIME ACTIVATION / CCTV ADMISSION

Date: 2026-08-26
Risk: R2/R3
Status: HOLD — runtime activation NOT PERFORMED

## Purpose

Activate the installer-owned TruthDeck Conductor command runtime only after a separate explicit runtime GO, then prove that the Tsignal CCTV supervisor crosses admission without weakening any fail-closed boundary.

Creating `~/.conductor/install-manifest.json` is an activation event. The Tsignal supervisor retries admission automatically, so the manifest may make the CCTV producer launchable as soon as it becomes valid.

## Hard gate

Without a fresh explicit runtime GO, do not:

- run `conductor_install.py install` against the live user home;
- run `install/install.ps1 -InstallConductor` or `install/install.sh --install-conductor` against the live user home;
- create, copy, edit, or synthesize `~/.conductor/install-manifest.json`;
- copy or reinterpret `~/.truthdeck/install-manifest.json`;
- start or restart Tsignal, TSU, the CCTV producer, Chrome TV, CDP, or Playwright;
- acquire a live `host:heavy` lease;
- delete the Conductor manifest as an ad-hoc rollback while supervisor or producer custody is ambiguous.

## Preconditions after GO

1. The installer repair PR is merged and the exact merged `dotclaude-ecosystem` source SHA is recorded.
2. Tsignal is on the intended reviewed supervisor build.
3. Read-only Conductor status is captured first:

```powershell
py scripts/conductor_install.py status --repo-root "D:\dotclaude\dotclaude-ecosystem" --home "C:\Users\dszub"
```

Expected pre-activation state for the incident described by FOUNDATION T-3:

- `state=ABSENT`;
- `db_exists=true` is allowed and is state-store evidence only;
- manifest path is `C:\Users\dszub\.conductor\install-manifest.json`;
- no claim of an installed `conductorctl` is made from DB, receipts, logs, or locks.

4. Capture the Tsignal CCTV supervisor status before activation. Expected incident state is fail-closed: `BLOCKED_CONDUCTOR_UNAVAILABLE`, `running=false`, `launch_health_proven=false`.

## Activation command

Use the canonical owner directly; do not hand-write the manifest and do not use PATH discovery:

```powershell
py scripts/conductor_install.py install --repo-root "D:\dotclaude\dotclaude-ecosystem" --home "C:\Users\dszub"
```

The installer must own the write. It installs `conductorctl.py` under `~/.conductor/app/scripts/`, records file SHA-256 digests, and writes schema `conductor.install.v1` atomically.

Immediately run the read-only status command again and require:

- `state=INSTALLED`;
- `interpreter` matches `canonical_commands.conductorctl[0]`;
- `canonical_commands.conductorctl[1]` is the installer-owned `~/.conductor/app/scripts/conductorctl.py`;
- the installed source head and source-tree digest match the intended checkout;
- `drift=[]`;
- no TruthDeck manifest is involved.

If any of those checks fail, stop the activation procedure. Do not fabricate or patch the live manifest.

## CCTV readback

The manifest write may be observed by the already-running supervisor retry loop. Do not manually start the producer.

### +1 minute

Capture:

- `data/cctv_test/cctv_feed_supervisor_status.v1.json`;
- Conductor resource status for the CCTV request/lease;
- supervisor logs around admission and first heartbeat.

Require no `RECOVERY_REQUIRED`, no admission ambiguity, no unmanaged/PATH launch, and no duplicate producer. If the producer is running, its lease/request IDs must be present and the feed must prove fresh generation for every approved scope before `launch_health_proven=true`.

### +30 minutes

Capture the same surfaces again. Require:

- one owned producer generation, unless a fully explained restart occurred;
- heartbeat sequence advancing monotonically with the exact lease ID;
- no lease expiry/reacquire storm;
- no repeated `BLOCKED_CONDUCTOR_UNAVAILABLE` after a clean installed readback;
- 1m, 30m, and 1d CCTV scopes remain fresh and contract-valid.

### +1 day

Capture:

- installer read-only status (`INSTALLED`, no drift);
- Conductor resource status and event/receipt evidence for the CCTV lease lifecycle;
- supervisor status and restart count;
- 1m/30m/1d scope freshness and generation advancement;
- relevant Tsignal/TSU logs for admission, heartbeat, release/recovery, and producer restarts.

Require no hidden PATH fallback, no unmanaged subprocess, no heartbeat/release ambiguity, no duplicate lease spend, and no silent degradation to stale CCTV data.

## Failure handling

If activation produces ambiguity, treat it as a custody problem rather than an installation cleanup task. Do not manually delete the manifest, forge receipts, or kill/restart processes outside the reviewed supervisor/Conductor lifecycle. Record exact request ID, lease ID, PID, heartbeat sequence, and current supervisor state, then use a separate recovery/rollback handoff with explicit operator authority.

## Completion record

Record all of the following when the activation is actually performed:

- runtime GO reference;
- installer repo exact source SHA;
- generated manifest path and read-only `INSTALLED` status;
- exact canonical `conductorctl` tuple;
- +1m readback;
- +30m readback;
- +1d readback;
- any restart/recovery evidence;
- final runtime verdict.

Until that record exists, runtime activation status remains **NOT PERFORMED**.
