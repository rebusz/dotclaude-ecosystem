# Conductor memory pressure prevention

Date: 2026-10-13. Risk: R2 (durable process ownership and host admission).
Owner/integrator: Codex, operator-selected Astra/xhigh. Complex Windows process
lifetime and fail-closed ownership justify the requested effort. Operator GO:
Dawid, 2026-10-13 approximately 12:40/12:42 CEST. Scope: this worktree only;
delivery is a branch and draft PR, never main or a runtime deployment.
Start SHA: 18eb15340349494c500947e19f206e71592910e8.

## Why and definition of done

Prevent another agent/pytest fan-out from exhausting workstation RAM while
preserving other sessions, trading, scheduled work and uncertain attempts.
The operator reports 61.6 GB RAM, 0.5-4 GB free, about 72 Python processes and
about 42 suspected orphan Python/pytest processes using about 22 GB. These are
incident inputs, not independently verified measurements or permission to kill.
Deliver one integrated Conductor ownership/admission path, safe dry-run reports,
mocked destructive-path tests, full local pytest exit 0, RECEIPT.md and a draft PR.
Report unavailable gates literally; never replace a failed check with a pass.

## Root causes

1. Detached pytest/agent children can survive a launcher or lane timeout; a PID
   alone is neither durable ownership nor protection against PID reuse.
2. Git/conhost/helper descendants may outlive their immediate Python parent.
   Parent absence and process names alone cannot justify termination.
3. Lane and source capacity limit counts, not aggregate memory. Concurrent
   admitted lanes can exhaust RAM even when every slot is legitimate.
4. Corpus snapshots and captured subprocess output can amplify peak RAM and disk
   usage. This change reports pressure and bounds execution; it does not delete
   corpora, trim arbitrary working sets or clean another session's artifacts.

## Prevention

Extend scripts/conductor_resources.py, the existing ConductorStore persistence,
conductorctl commands, and current adapter launch boundaries. Do not introduce a
second scheduler, lease authority, daemon or independent admission database.
Use a small shared process-containment helper only where it keeps OS mechanics
out of policy. Preserve host:heavy capacity one for heavy pytest, independent CDP
pools, inherited-child limits and RECOVERY_REQUIRED/SUBMIT_UNCONFIRMED custody.

Persist every launch through the owned Conductor launch boundaries with lane,
owner, parent PID, PID + creation time, Windows session ID, worktree, command
hash, heartbeat/deadline and outcome. Propagate CONDUCTOR_LANE_ID and the owner
identity tag to children. Never store raw command arguments or environment
values in process reports. A tag is an aid to attribution, not permission alone.
Legacy processes are unidentified and remain untouched.

Attach bounded workers to a Windows KILL_ON_JOB_CLOSE Job Object before their
payload can spawn descendants. Retain the job and Popen handles through terminal
readback. Fail closed if containment cannot be established. On other platforms
use an owned process group with equivalent bounded lifetime. Cleanup never uses
global process-name matching or taskkill /IM. Ownership uncertainty retains the
reservation and records recovery instead of claiming release.

Conductor-launched pytest gets finite per-test and global wall timeouts. Enforce
the per-test timer without silently accepting missing support or caller flags
that disable it. A timeout is a failed run with bounded cleanup and evidence.
Per-lane memory budgets reserve expected headroom at admission and are observable;
budget exhaustion prevents new work and does not preempt protected processes.

## Detection

Start with a configurable 6 GiB available-RAM floor and 8 GiB resume threshold
(hysteresis); use available physical memory, not summed RSS. Reserve each lane's
declared budget, default 1 GiB. Unknown/invalid telemetry blocks new launches.
Existing lanes retain custody. Surface a warning below 10 GiB and a falling
available-memory trend from bounded recent samples. Tests use injected memory
measurements and clocks. Sample at admission and existing coordinator/routine
ticks, never create a new high-frequency polling daemon.

## Automatic remediation and hard exclusions

Default reaper operation is a read-only dry-run. An explicit --kill flag is
required for any future actuation; it WILL NOT be used during this task.
Candidate qualification requires a trusted registry record, matching PID and
start time, matching ownership/session, positive stale evidence (terminal lane
or expired deadline plus confirmed owner absence), and a final identity recheck.
Unknown metadata, changed PID identity, live owner, active/uncertain attempt,
unidentified descendants and conflicting evidence all mean KEEP.

Hard denylist wins over ownership: tsignal_bot/live bot, TWS/IB, CCTV supervisor
and tools.channel_reader_cv producer, WatchF/LAB daemons, scheduled tasks,
SYSTEM/session 0, other sessions/owners, this controller and its ancestors,
protected devspaces and any unidentified process. Never kill by parent absence,
age, memory size, executable name or token alone. Do not adopt old processes by
guessing. Windows handle-based termination must preserve identity through the
check/action boundary; ambiguous cleanup stays recovery-required.

## Scheduling

Provide a bounded, port-free conductorctl maintenance/status routine suitable
for the existing coordinator or a future operator-created Scheduled Task.
Proposed schedule: every 5 minutes, report-only, one instance, limited duration,
same interactive operator identity, no highest-privilege/SYSTEM execution.
Do not install/enable a Scheduled Task or a live kill routine in this worktree
task. Document the exact dry-run command after implementing the CLI. Automated
actuation remains a separate explicit operator action with recorded receipts.

## Observability

JSON resource-status exposes RAM available/total, thresholds, reservations, pressure state,
sample time/trend, blocked reason and priority. Order queued work options > CCTV
> BOS > runtime, preserving existing scheduler tie-break rules. Priority never bypasses the RAM floor,
current ownership, provider limits or protected runtime boundaries.
JSON + Markdown process reports include PID, owner, lane, RSS GiB, identity,
would-kill reason or keep reason, and telemetry errors. Bound report history;
retention remains report-only. Never read .env/credentials or persist raw command
lines, tokens, account data or full environment. Include collection limitations.

## Rollout phases

0. Write this plan before code; attempt immediate commit/push and the requested
   PLAN.md copy to D:/APPS/_shared/dispatch/receipts/conductor-procmgmt-astra-20261013.
   Filesystem/network refusals are scoped blockers, never bypassed.
1. Write GRILL.md: challenge assumptions, failure boundaries and alternatives;
   inspect existing launch, store, lease and scheduling seams before implementation.
2. Integrate registry/containment, pytest timers and memory admission into those
   seams; add pure reaper qualification and explicit dry-run/kill CLI separation.
3. Test PID reuse, wrong owner/session, protected names/paths, stale vs active,
   missing telemetry, storage corruption, timeout/cleanup failures, hierarchy,
   priority and resume behavior. No tests kill real workstation processes.
4. Run full local pytest through qualified host:heavy admission using retained
   Popen ownership and real exit status. Capture one real process-table dry-run.
   Do not start heavy validation if denied or under pressure; keep other work moving.
5. Update RECEIPT.md, commit coherent changes, push branch, open DRAFT PR to main.
   Self-hosted route only; no CI dispatch or ready/merge requested. Do not extend
   the October 12 urgent-workflow review/CI waiver to unrelated work.

## Rollback

No installation/runtime mutation is part of this task. Revert the branch commits
to roll back source; retain registry/history as evidence. For a future deployment,
stop admitting new lanes, wait for owned running jobs to reach a proven terminal
state, then roll back installed modules. Never delete active records/locks,
disable containment mid-lane, close another owner's job or clear recovery to
force admission. Keep report-only visibility and existing protected processes.

## Constraints and open verification

Windows Job nesting/assignment support, all actual subprocess launch seams,
current RAM, installed pytest capabilities, global lease status, Git write access,
remote authentication and isolated self-hosted runner availability require live
verification. The sandbox currently allows writes only to this worktree and
temporary storage; the external PLAN copy and shared Git metadata may be blocked.
No live ports, bot restart/kill, credential reads, skipped hooks, lock takeover,
protected Cursor/devspace paths, or reaper kill-mode execution are authorized.
