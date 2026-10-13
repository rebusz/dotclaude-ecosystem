# Conductor process lifetime and memory admission

Risk R2. Source changes are pending full local validation and draft publication;
this document does not attest installation or authorize live cleanup.

## One owner and one store

The existing `ConductorStore` schema v8 holds process lanes, birth identities and
memory reservations. `HostResourceManager` admits the lane and records its root
before resuming the Windows payload. Pytest, Claude/Kimi dispatch and TruthDeck
checkpoint workers share this launcher. Descendants inherit `CONDUCTOR_LANE_ID`
and `CONDUCTOR_OWNER_ID`; these tags alone never authorize termination.

Each Windows launch owns a `KILL_ON_JOB_CLOSE` Job Object, a retained Popen
handle and its original thread handle. Job assignment and registry commit happen
before resume. Registration/assignment failure stops startup. Normal completion,
timeout and exceptions close the owned tree; uncertain cleanup retains the lane's
RAM reservation. No foreign jobs are opened or adopted. POSIX uses a private
process group; if its leader identity is no longer provable, cleanup fails closed.

Root launches are durably registered. Live Windows Job descendants are sampled
every bounded wait (at most 0.5 seconds), identity-checked and recorded. A helper
which starts and exits between samples can lack an individual record; it remains
inside the Job lifetime. This is not an exhaustive process-birth event log.
Claude/Kimi availability probes and the GUI's Python recovery helper use the
same registered launcher with unique lane IDs and short deadlines. Git commands
used by repository and installer helpers remain direct subprocesses;
they are not Python, pytest, or agent workers covered by the process registry.
This does not register every process on the workstation.

## Limits and scheduling

New registered launches reserve 1 GiB by default. Available physical RAM must
remain at least 6 GiB after all reservations and the new budget. Physical pressure
pauses admission until 8 GiB is available. Unknown telemetry blocks admission.
Budgets are conservative additional headroom, not hard RSS limits or a claim
that previously reserved memory is free. Configuration is through the manager's
`memory_floor_gib` and `memory_resume_gib` constructor parameters.

`resource-request` and `pytest` accept `--memory-budget-gib`; `resource-request`,
`pytest` and `enqueue` accept `--lane-priority options|cctv|bos|runtime`, mapping
to 400/300/200/100. Existing queue/scheduler tie-break rules remain. Priority
never bypasses source capacity, ownership fences or RAM admission. Heavy pytest
alone consumes `host:heavy`; CDP retains its own pool.

`resource-status --json` includes current RAM, bounded trend samples, thresholds,
reservations and per-request budgets. This command writes Conductor status state;
`resource-live` remains the existing read-only pool projection.

Pytest defaults: 7,200-second wall deadline, 300 seconds per test including setup
and teardown. Both are finite and configurable with `--timeout-seconds` and
`--per-test-timeout-seconds`. The bundled plugin cannot be disabled through CLI
options. Ini `addopts` is cleared: required pytest options must be explicit,
which also makes fan-out visible to the admission classifier. Captured output
uses temporary files with a 4 MiB polling cutoff and bounded result reads.

## Read-only maintenance

With dependencies installed, run this command from the owned checkout:

```powershell
& "D:/APPS/_worktrees/conductor-procmgmt-astra-20261013/.venv-procmgmt/Scripts/python.exe" "D:/APPS/_worktrees/conductor-procmgmt-astra-20261013/scripts/conductorctl.py" process-report --dry-run --owner "conductor-procmgmt-astra-20261013" --output "D:/APPS/_worktrees/conductor-procmgmt-astra-20261013/artifacts/procmgmt/process-report"
```

The registry is opened read-only without migration. JSON and Markdown include
PID, owner/lane, RSS GiB, KEEP/WOULD_KILL reasons and aggregate counts. RSS sums
can count shared pages multiple times. Missing ownership, stale/reused identity,
unknown ancestry, other sessions, scheduled work, protected bots/brokers/daemons,
and uncertain attempts remain KEEP. Existing unregistered Python processes are
not retrospectively adopted. Arguments and environments are not persisted.

A future Scheduled Task can invoke that dry-run every five minutes, one instance,
without elevation. This task creates no scheduled task, daemon, port or automatic
kill policy. The explicit kill actuator exists for future approved use but must
not be run for this assignment. Mock tests cover it; actual tests signal no live
processes. Successful termination requests and subsequent collection/handle
failures remain distinct recorded outcomes, never rewritten as KEEP.

If dependencies are unavailable, `artifacts/procmgmt/collect-native-processes.ps1`
and `report-native-processes.py` produce a clearly partial native inventory and
run the same classifier on it. This path has no actuator and cannot prove any
candidate safe to terminate.

## Validation and rollback

Use the established Conductor heavy gate for the full suite; never substitute an
isolated store to bypass its shared lease. Focused destructive-path tests use
fake handles/tables. See root `RECEIPT.md` for actual runs and blockers.

No installation is part of this worktree task. Source rollback is the normal
branch revert. A later installed rollback must first stop new admission and
prove all owned lanes terminal; preserve database history, locks and ambiguous
attempts. Do not downgrade an active v8 store with older code.
