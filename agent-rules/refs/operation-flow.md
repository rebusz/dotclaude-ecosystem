# Operation-local progress and mistake recovery

Load for coordination, blocked operations, incident recovery or resource admission.
This is the canonical procedure; helpers link here rather than maintaining variants.

## Decide from the operation, not the session label

Record the failed or pending operation, its dependency/resource, owner/attempt and
release condition in the existing task record. CREATED means accepted, not running;
active/inProgress without a current result proves no execution. WAITING_APPROVAL
means an unresolved native prompt, not refusal or SUBMIT_UNCONFIRMED. Point to that
prompt once (operation, scope, session/attempt); resume only after its actual result.
Do not create a duplicate prompt or change executor/shell to evade it.

Before unattended dispatch, inspect the selected worker's effective session
approval policy, sandbox writable roots, network access and needed tools
against the exact owned write-set and external calls. A parent's profile,
global config and standing business GO are not worker permissions. If access
is insufficient, hold only that operation and name its release condition.
Ask once for the exact application profile change when needed; do not
replay denied commands or switch workers to evade a refusal. An actual
pending native prompt is WAITING_APPROVAL, never RUNNING; a profile gap
without a prompt is BLOCKED. Continue qualified disjoint work and verify
the new effective profile before resuming the dependent operation.

| Observation | Dependent operation | Independent authorized work |
|---|---|---|
| Policy/permission denial, ACL/sandbox/GPO restriction | Stop; use only the legitimate approval route if offered. No bypass or weakened policy | Continue outside that denied operation and its dependencies |
| Wrong argv/path/encoding, absent tool or incompatible configuration | Diagnose and make the ordinary scoped repair; no new business GO | Continue; do not call setup failure behavioral RED |
| Transport failure confirmed before submission, or confirmed terminal failure | A qualified supported alternative may perform the authorized slice without resetting caps | Continue |
| Timeout with unknown submission/result | Preserve SUBMIT_UNCONFIRMED and original custody; no retry/replacement/duplicate completion | Continue only nonoverlapping work |
| Provider quota or one pool unavailable | Stop work needing that provider/pool; UNKNOWN optional quota is not exhaustion | Qualify another independent assignment under its own admission |
| Required review/CI unavailable | Hold dependent clearance/landing; preserve the draft and completed local evidence | Implement/validate other owned work, or deliver another qualified repo |

A failed command is not automatically a permission denial; a real permission
denial is not an ordinary command failure. Before submission, check that packet
restrictions permit the qualified adapter's actual tools. READ_ONLY may require
a read-only command such as Get-Content; blanket NO_COMMANDS can prevent the
requested source read without any native permission refusal. Inspect the actual error and context.
Standing GO covers ordinary setup repair, but cannot change ACLs, sandbox, GPO,
Conductor authorization, deployment or live triggers. Do not repeat a previously
denied action through another route. Preserve every existing paused scope.

The supervisor schedules the next ready package after a completion or block.
Use events/long polling when appropriate, or inspect at a real coordination point.
One pending question does not suspend other answers, validation or delivery.
Once no independent work remains, report the concrete unresolved dependencies;
do not manufacture progress by rereading unchanged state or producing receipts.

## Two results for each recognized mistake

Start separate repair and prevention processes, concurrently when disjoint and
supported. Give each an owner and bounded write-set; they may share an integration
owner but must return distinct results. Reuse the existing incident and attempts.
If tools cannot run concurrently, keep both work items explicit and progress them
without claiming separate executions. Never duplicate an uncertain attempt.

Repair corrects the actual effects and validates the repaired behavior. Prevention
identifies the cause, changes the smallest relevant rule/workflow/tool, and replays
the original failure situation plus an allowed control. A proposal, checklist,
lesson or IDEA_BOX entry alone is not completed prevention. Record open prevention
under an existing IDEA_BOX slug; close it only with change and replay evidence.
Do not accumulate a new universal rule for each typo; improve the relevant source
or helper, and consolidate identical causes. Urgent repair does not wait for the
whole prevention package; independent useful lanes keep advancing.

An additional test or report does not transfer ownership of the existing
implementation/review/CI/landing. Say which package and stage an owner controls;
any transfer needs explicit handoff evidence. Preserve original immutable receipts.

## Resource and process custody

Only heavy pytest takes capacity-one `host:heavy`; CDP uses independent `cdp:*`.
Builds, browser/Playwright, replay, focused lightweight pytest, docs and Git are not
heavy. The registered CI runner pool is exempt from host:heavy and uses its own
pool size, BelowNormal priority, pilot SLO drain ladder and TsignalCiWatchdog.
Exemption does not waive CI route/isolation/authorization or the pool's own limits.

A bounded child may inherit active attempt-scoped TDCONDUCTOR_LEASE_ID once.
A second concurrent inherited child, forged/stale/expired lease or RECOVERY_REQUIRED
fails closed. No preemption or automatic retry across ambiguous ownership.
Run bounded pytest as `<python> -m pytest <args>` using retained Popen, shell=False;
WMI/CIM/process-list polling is not ownership proof. Read storage status/ceilings before another heavy run. A storage
`BLOCKED` projection marked REPORT_ONLY is diagnostic, not an admission refusal;
only the actual qualified admission result decides whether that heavy attempt
may start. A real refusal still holds that operation. Retention is report-only;
no cleanup or cap increase to pass.
`authorize --interactive` remains operator-only, tty-verified, exact prompted GO;
argv flags, inbox, environment, MCP or assignments cannot supply authorization.

## Bounded, accurate evidence

Reuse one current task record plus actual outputs required to reproduce a decision.
Keep source/head, producer/reviewer, result/exit and unresolved dependency; do not
invent provider fields or a new receipt schema. For a wrapped operation, inspect
the nested result status, exit and timeout as well as the outer coordinator
result. Outer SUCCESS/0 is not PASS when the child FAILED, exited nonzero,
timed out, skipped critical work or never ran the intended target. Raw logs stay
local and are not automatically committed. Choose a known root and verified
test selectors from the owner's executed
command or existing files before broad discovery. A guessed pytest path that
collects zero tests is setup evidence, not behavioral RED. For liveness use
resource-live; before admission use the bounded storage-only projection with
its actual exit code, not a full resource-status ledger. Capture large
inventories, parse, filter by owned scope, then project total_count and
relevant identities/status. In a large shared checkout, check tracked conflicts
with `git status --short --untracked-files=no` and explicit intended paths; do not
walk unrelated untracked directories or retry denied paths. Preserve Git porcelain
status columns when parsing (`--porcelain -z` is preferable); never strip leading
whitespace before interpreting a status row. Never dump environment
variables or credentials. No repeated whole Conductor status/log scans.

Read repository/Git text as UTF-8 strict and configure stdout explicitly when
needed; machine JSON may escape Unicode losslessly. Retain subprocess output as
raw bytes. An encoding/printing repair does not justify repeating the original
provider/test side effect. Distinguish source bytes, proposed patch bytes and
Git-filtered content hashes; handle LF/CRLF intentionally, never replacement decode.
Every hash names its representation: sent UTF-8 prompt bytes and raw CRLF file
bytes may differ. Save transmitted bytes with write_bytes (or explicit newline);
verify each digest within its own representation contract, never across domains.
Resolve each Git SHA/tree in its owning repository/object store. Missing object
is not a tree mismatch, custody proof or permission failure; check the correct
store rather than resetting/fetching/replaying unrelated work automatically.

## Effect classification and lifetime custody

Classify an adapter operation from its implementation and observed tests before
using it as readback. `status` may read persisted state, but a method named
`collect` can create a recovery worker or resume a native thread. Record whether
an entrypoint is pure persisted read, local receipt write, process spawn, native
resume or new generative submit. Every non-pure effect needs its own current
owner, window, cap, permission and resource admission before invocation.
An unknown method is not read-only by name. Provide a separate pure projection
when collect cannot be made safe; after an authorization window, pure readback
of already persisted results is allowed, while spawn/resume/new work waits for
a newly authorized continuation. Existing in-flight custody survives window end.

Repeated observations of the same incident reuse its stable key and owners.
Lifetime caps, original program/window/attempt bindings and prior refusal states
survive a new session or program revision. A new window does not reset a used
cap or turn a held/paused operation into READY. Policy wording is CONTEXT_ONLY
until the actual dispatch boundary verifies and enforces role/model, side effect,
owner, window and cap. A manifest or installed rule alone is not enforcement.

Instruction activation has separate states: source committed, render reviewed,
target installed with hash readback, execution gate enforced, and behavior shown
in a brand-new session. An old session may retain old context. Do not install
shared active targets or change an active controller until the owning runtime is
quiescent, all shared-root owners are checked, and a content-bound migration
with rollback snapshot is admitted. WINDOW_CLOSED alone is not quiescence.
