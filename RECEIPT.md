# Conductor process management — resume receipt

2026-10-13. R2. Operator GO: Dawid, approximately 12:40/12:42 CEST.
Scope: `D:/APPS/_worktrees/conductor-procmgmt-astra-20261013` only.
Integrator: native Codex (operator requested Astra/xhigh). Existing uncommitted
work was preserved and reviewed before edits. No deployment or live actuation.

**Overall: PARTIAL / NOT DELIVERED.** Source and local evidence exist. Full local
pytest, implementation commit/push, external PLAN copy and draft PR remain
outstanding. No full-suite, review, CI or publication gate is reported PASS.

## Source result

The inherited implementation adds schema-v8 process ownership/reservations to
ConductorStore, shared Windows Job containment, lane/owner environment tags,
pytest per-test and wall deadlines, RAM admission with hysteresis, named lane
priorities, and a default read-only JSON/Markdown reaper report.

This resume fixed actuation evidence loss, inaccessible-owner recovery,
pre-spawn capture-file failure, final output cutoff, ini-based timer disablement,
CLI budget/priority wiring, per-request budget visibility and registered
TruthDeck checkpoint execution. Adapter owners now inherit an explicit caller
identity or use a unique lane identity, never one shared owner name for unrelated
sessions. The diagnostic report now totals WOULD_KILL and
KEEP RSS and groups reasons. No existing foreign process was adopted.

Root worker launches are registered before Windows payload resume. Descendants
are contained and sampled every 0.5 seconds; short-lived descendants may lack an
individual row. Claude/Kimi availability probes and the GUI Python recovery
helper now use the registered launcher. Direct Git helper processes remain
outside the Python/pytest/agent registry scope. This is not an exhaustive
process-birth journal. See
[operator guide](docs/conductor-process-management.md) and [GRILL](GRILL.md).

## Validation

| Check | Actual outcome |
| --- | --- |
| `python -m unittest scripts.tests.test_conductor_reaper -v` (previous run) | **PASS**, exit 0, 34 tests; all termination APIs mocked; not rerun because already finished |
| `python -m compileall -q scripts` (previous run) | **PASS**, exit 0 |
| Ruff on changed implementation/test files | **PASS**, exit 0 |
| Compile changed implementation/test files | **PASS**, exit 0 |
| Full local pytest through `conductorctl pytest` | **BLOCKED**, corrected invocation exited 1 before spawn with `[Errno 87] session lookup failed`; pytest did not start |
| Current RAM admission | **BLOCKED**, available 12.5125 GiB, reserved 7 GiB, requested 1 GiB, headroom 4.5125 GiB vs 6 GiB floor (`RAM_BUDGET_RESERVED`) |
| Added adapter/GUI registration tests | **NOT RUN**, pytest remained blocked |
| `git diff --check` | **NOT RUN** in this resume |
| Independent review | Separate read-only subagent inspected containment/reaper and later liveness/launcher corrections; its two P2 findings were repaired and rechecked; no independent exact-head gate claimed |
| CI | **NOT RUN**; workflow source routes only to `[self-hosted, windows, dotclaude-isolated]`, excludes draft PR execution; runner availability unverified |

Logs: [reaper unit result](artifacts/procmgmt/reaper-unittest.log),
[full-suite preflight failure](artifacts/procmgmt/full-pytest-preflight.log).
No full-suite first failing assertion exists because collection never began.
The October 12 urgent-workflow review/CI waiver was not applied to this task.

Native Python was `C:/Python314/python.exe`; pytest and psutil were initially
missing. This resume installed pytest, psutil, Ruff, and both MCP requirement
files only in the ignored worktree-local `.venv-procmgmt`. The corrected full
pytest request failed before child creation with `session lookup failed`; direct
memory status also denied admission at the values above. An earlier mistyped
request (extra `python -q` target) entered QUEUED as `pytest_heavy_unknown`; that
exact unstarted request was released. Final `resource-live` readback showed zero
active, queued, or recovery-required work. No heavy lease was forged, shared
store substituted, or another owner's lock taken.

## Real process-table dry-run

Snapshot: **2026-10-13 11:45:15 UTC / 13:45:15 CEST**.
Collector: native PowerShell `Get-Process`, read-only. The real reaper
`build_report` classifier consumed this snapshot. Mode: **dry-run**; actuation
list empty. No kill/restart, port access, scheduled-task change or credential/
environment-file read occurred.

| Scope | Observed | WOULD_KILL | KEEP | WOULD_KILL RSS | KEEP RSS |
| --- | ---: | ---: | ---: | ---: | ---: |
| All observed processes | 655 | 0 | 655 | 0 GiB / 0 GB | 50.491299 GiB / 54.215 GB |
| Python/pytest names | 71 | 0 | 71 | 0 GiB / 0 GB | 12.455237 GiB / 13.374 GB |

| KEEP reason | Count | RSS GiB |
| --- | ---: | ---: |
| PROCESS_METADATA_UNKNOWN | 431 | 38.555238 |
| SYSTEM_OR_SESSION_ZERO | 112 | 8.171681 |
| PROTECTED_SCHEDULED_TASK | 102 | 1.862635 |
| OTHER_SESSION_OR_USER | 7 | 0.183895 |
| PROTECTED_BROKER | 2 | 1.647541 |
| CONTROLLER_OR_ANCESTOR | 1 | 0.070309 |

**Partial diagnostic evidence:** psutil was unavailable; native inventory lacks
parent/owner/command identity. The existing registry could not be opened
(`REGISTRY_UNREADABLE_OperationalError`), and CIM physical-RAM telemetry returned
`CimException`, so available/total RAM remains UNKNOWN. Every process was kept.
These counts do not prove that no orphans exist and do not qualify any legacy
process for termination. Aggregate RSS can double-count shared pages; neither
the RSS sum nor the operator's earlier incident estimate is proven reclaimable
physical memory. Actual freed memory: **zero**.

Artifacts: [JSON report](artifacts/procmgmt/process-dry-run.json),
[Markdown report](artifacts/procmgmt/process-dry-run.md),
[sanitized native snapshot](artifacts/procmgmt/native-process-snapshot.json).
Reproduction uses the saved
[collector](artifacts/procmgmt/collect-native-processes.ps1) and
[classifier driver](artifacts/procmgmt/report-native-processes.py), which has no
actuator. Both completed with exit 0; the report explicitly retains incomplete
collection status.

## Resume validation and refreshed process-table dry-run

Dependencies were installed only in the ignored worktree-local
`.venv-procmgmt`: `pytest`, `psutil`, `ruff`, common repository test packages,
and both MCP requirement files. No shared/live venv was modified.

Correct full-suite command was sent through `conductorctl pytest` with no extra
pytest target, but the wrapper exited 1 before child creation:
`[Errno 87] session lookup failed`. A read-only `resource-live` check afterward
showed host:heavy ACTIVE=0, QUEUED=0, RECOVERY_REQUIRED=0. Direct memory status
at 2026-10-13 12:23:31 UTC reported 12.5125 GiB available, 7 GiB reserved,
4.5125 GiB headroom, and the configured 6 GiB floor. Full pytest and the newly
added registration tests remain unverified; no admission bypass was used.

Refreshed official reaper report: **2026-10-13 12:24:01 UTC / 14:24:01 CEST**.
Mode **dry-run**; process table complete; registry **RECORDED**; collection
error null. 603 processes: 0 WOULD_KILL, 603 KEEP; 0 GiB / 0 GB would-kill RSS;
39.155097 GiB / 42.042 GB keep RSS; 205 rows have unknown RSS. The 56 Python/
pytest-name rows were all KEEP, totaling 9.316652 GiB / 9.998 GB RSS. Keep
reasons: OTHER_SESSION_OR_USER 200, UNREGISTERED 294, PROTECTED_DAEMON 69,
CONTROLLER_OR_ANCESTOR 6, PROCESS_METADATA_UNKNOWN 7,
PROTECTED_SCHEDULED_TASK 9, PROTECTED_CCTV 4, PROTECTED_BROKER 2,
PROTECTED_LIVE_BOT 2, PROTECTED_DEVSPACE 5, SYSTEM_OR_SESSION_ZERO 5.
Artifacts: [refreshed JSON report](artifacts/procmgmt/process-dry-run.json) and
[refreshed Markdown report](artifacts/procmgmt/process-dry-run.md). No process
was signaled or changed.

## Repository and publication state

- Branch: `arch/conductor-procmgmt-astra-20261013`, still tracking `origin/main`.
  Start HEAD: `18eb15340349494c500947e19f206e71592910e8`.
  End observed HEAD: `51a2b2f9341151ac72a4bf21b8a1b214f9878ed6`.
  During this run another actor committed the plan and GRILL, at 11:53:49 UTC,
  with subject `docs: conductor memory pressure prevention plan + grill (WIP, Astra)`.
  This session issued no commit command and does not claim authorship of that
  Git operation. The new commit was preserved; subsequent GRILL additions remain dirty.
- **Plan committed: true (observed); implementation committed: false; pushed:
  false; draft PR: not created by this session.** A final `git ls-remote --heads
  origin refs/heads/arch/conductor-procmgmt-astra-20261013` returned exit 0 with no
  advertised branch ref. `gh pr view` failed before network access because
  `AppData/Roaming/GitHub CLI/config.yml` was denied; external PR status remains
  unverified. Prior-run GRILL
  records `git add` failing to create the shared `index.lock` with Permission
  denied. `.git` points to
  `D:/dotclaude/dotclaude-ecosystem/.git/worktrees/conductor-procmgmt-astra-20261013`,
  outside this session's writable root. The existing refusal was preserved;
  no alternate index, copied repository, remote API commit, hook bypass or main
  push was used to evade it.
- Phase 0 [plan](docs/plans/2026-10-13_memory_pressure_prevention_plan.md) is now
  committed locally in `51a2b2f`. SHA256:
  `79769d1c1666f84999184ec9d18174a9d2ec10a0cac390bccb0601c92b8d14ee`.
  Previous-run external copy to
  `D:/APPS/_shared/dispatch/receipts/conductor-procmgmt-astra-20261013/PLAN.md`
  returned AccessDenied (recorded in GRILL); that destination remains outside
  the writable root. Final direct readback reported PLAN.md does not exist.
  No copy is claimed.
- [Draft PR body](PR_BODY.md) is prepared locally, without a fabricated PR URL.
  No installation, Ready, merge, checkout sync or runtime proof is claimed.
- Plan context loader ran. End updater returned exit 0: `PLANS.md regen: OK`,
  `VISIONS.md regen: OK`, no vision frontmatter. No plan was marked shipped.

EPILOG_PAYLOAD:
```json
{"start_sha":"18eb15340349494c500947e19f206e71592910e8","end_sha":"51a2b2f9341151ac72a4bf21b8a1b214f9878ed6","plan_path":"docs/plans/2026-10-13_memory_pressure_prevention_plan.md","committed":true,"implementation_committed":false,"resolved_ideas":[]}
```

Next action: resume this same worktree in a session with qualified pytest
dependencies and authorized access to its shared Git metadata and the requested
PLAN-copy destination, preserving all current files and attempt custody.
