---
title: "Implementation handoff: automatic recovery of proven-dead Conductor owners"
date: 2026-08-31
risk_class: R2
status: awaiting-implementation-go
repo: dotclaude-ecosystem
cross_repo_consumers:
  - WatchF
  - Tsignal 5.0
related:
  - design/plans/2026-07-22_truthdeck_conductor_cross_repo_work_queue_r2.md
  - design/plans/2026-08-27_conductor_operator_gui_r1.md
  - design/plans/2026-08-27_cdp_admission_pool_split_r2.md
  - design/handoffs/2026-08-27_gate_panel_cursor_implementation_brief.md
---

# Implementation handoff: automatic orphan recovery in Conductor

## 1. Decision and authorization boundary

The operator rejected the current manual-only recovery contract on 2026-08-31:

> Orphaned lanes must unblock automatically. This is the supervisor's or
> Conductor's responsibility. Reset controls must be present in the Conductor GUI.

Implement **automatic recovery only when process death is mechanically proven**.
Do not weaken the ambiguity fence. Conductor must never kill a process, infer death
from lease age alone, or use an operator attestation as an automatic fallback.

This handoff authorizes documentation and implementation preparation only. Code
implementation requires the exact operator token:

```text
GO CONDUCTOR ORPHAN AUTO-RECOVERY R2
```

The older Gate Panel plan deliberately listed auto-recovery as a non-goal. That
decision is superseded by the operator direction above, but all its other safety
invariants remain binding.

## 2. Live incident frozen for regression fixtures

Readback was taken receipt-free with `conductorctl resource-live` on 2026-08-31.
All three recorded owner PIDs were separately checked with `Get-Process` and were
absent. No process was terminated.

| Pool | Fenced request | Owner | Lease process identity | Queue | Live owner verdict |
|---|---|---|---|---:|---|
| `host:heavy` | `rr_e75bd06d622d` | `tsignal-cctv:104996` | `process_pid=null`, `process_start_time=null` | 4 | PID `104996` absent |
| `cdp:perplexity` | `rr_2adf40323568` | `coderpx:8384` | `process_pid=null`, `process_start_time=null` | 0 | PID `8384` absent |
| `cdp:tv` | `rr_80a40a675689` | `tsignal-cctv:148260` | `process_pid=null`, `process_start_time=null` | 19 | PID `148260` absent |

Exact manual failure for the `host:heavy` row:

```text
resource-recover --request-id rr_e75bd06d622d
status=ERROR
error_message=OWNER_LIVENESS_UNPROVEN
```

Additional runtime facts:

- no `conductord.py` process was running;
- the current request path therefore cannot rely on a daemon-only reaper;
- the 19 `cdp:tv` queue entries include requests from many earlier CCTV process
  identities, so releasing only the fence would promote a stale queued owner;
- the installed manifest at `~/.conductor/install-manifest.json` reported
  `source_head_sha=c4333d980cd7e35d6277e3aa3c4e434da6e591ec`, which predates the RECOVER
  button merged in PR #97 (`c7679be`);
- the installer copied `conductor_gui.py` as a payload but did not expose a
  canonical `conductor_gui` command or shim;
- an active GUI launched directly from the repository did show RECOVER buttons.
  The operator-facing failure is stale installation/discoverability, not absence
  of the widget in current source.

Turn these rows into committed, anonymization-free regression fixtures. They are
already local infrastructure identifiers, not credentials.

## 3. Root cause

Four contracts combine into the outage:

1. `HostResourceManager._create_lease_locked()` initializes
   `process_pid/process_start_time` to `None`. Only the bounded pytest adapter
   later fills them. CDP adapters and CCTV never attach an owner process.
2. `reconcile()` converts expired `ACTIVE` requests to
   `RECOVERY_REQUIRED`, while `recover()` correctly refuses an unrecorded owner
   with `OWNER_LIVENESS_UNPROVEN`.
3. `request()` checks idempotent replay before doing any resource cleanup, and
   `_promote_locked()` promotes the oldest queued row without proving that its
   owner still exists.
4. `conductord` periodically reconciles WorkItem leases only. It does not sweep
   every host-resource pool, and in this incident the daemon was not running
   anyway.

The result is permanent queue starvation after an owner dies, even when the PID
embedded in `agent_instance` is demonstrably absent.

## 4. Frozen safety contract

### 4.1 What may recover automatically

An `ACTIVE` or `RECOVERY_REQUIRED` request may transition automatically to
`RELEASED` only when all of the following are true:

1. its lease is expired or it is already `RECOVERY_REQUIRED`;
2. no `INHERITED` child still references the lease;
3. the recorded owner PID is absent, or the PID exists with a different process
   start time;
4. the decision and evidence are written in the same `BEGIN IMMEDIATE`
   transaction that releases capacity and considers queue promotion.

Use exact terminal reason codes:

```text
AUTO_RECOVERY_OWNER_PROCESS_GONE
AUTO_RECOVERY_OWNER_PID_REUSED
```

The resource event must include the PID, recorded start time, observed outcome,
request/lease IDs, resource key, and `actor_identity=resource-auto-recovery`.

### 4.2 What must remain fenced

Never auto-recover when:

- the recorded PID and start time still identify a live process;
- an inherited child remains active;
- no owner identity exists and no narrowly supported legacy identity can prove
  death;
- process inspection returns access denied or another result that is not
  equivalent to `NoSuchProcess`;
- the store or schema is unreadable.

These cases retain their existing exact failures:

```text
OWNER_PROCESS_ALIVE
INHERITED_CHILD_ACTIVE
OWNER_LIVENESS_UNPROVEN
```

`resource-recover --attest-owner-gone` and the GUI RECOVER control remain the
manual fallback for genuinely ambiguous rows. They are not used by the sweeper.

### 4.3 Queued requests are not leases

A queued request has never received launch authority. It may therefore be
terminalized automatically when its owner is proven dead. This is not
preemption.

Use:

```text
QUEUE_OWNER_PROCESS_GONE
QUEUE_OWNER_PID_REUSED
LEGACY_QUEUE_OWNER_UNRECORDED
```

`LEGACY_QUEUE_OWNER_UNRECORDED` is a one-time migration/cutover treatment for
pre-owner-identity `QUEUED` rows. Do not promote such rows. A live consumer will
retry and create a fresh, identity-bearing request. Do not apply this rule to
legacy `ACTIVE` or `RECOVERY_REQUIRED` rows.

### 4.4 Legacy fenced rows

For the migration fixture only, recognize these exact legacy identity shapes:

```regex
^(tsignal-cctv|coderpx):(?P<pid>[1-9][0-9]*)$
```

The fallback may auto-recover only when that PID is absent. If the PID exists,
with or without a known start time, leave the row fenced. Do not generalize the
parser to arbitrary `name:<number>` strings.

Record legacy evidence as:

```text
AUTO_RECOVERY_LEGACY_AGENT_PID_ABSENT
```

Remove dependence on this fallback for all newly created requests.

## 5. Implementation slices

### AR-1 — Persist owner identity on requests

Owning repo: `dotclaude-ecosystem`.

Files:

- `scripts/conductor_model.py`
- `scripts/conductor_store.py`
- `scripts/conductorctl.py`
- `scripts/conductor_commands.py`
- `scripts/conductor_resources.py`
- store/model/CLI/resource tests

Add a forward-only schema migration after version 6:

```text
host_resource_requests.owner_process_pid INTEGER NULL
host_resource_requests.owner_process_start_time REAL NULL
host_resource_requests.owner_identity_source TEXT NOT NULL DEFAULT 'UNRECORDED'
host_resource_requests.owner_last_seen_at_utc TEXT NULL
```

Do not overload `host_resource_leases.process_pid`: that field currently names a
bounded child for the pytest adapter. Owner and child are different authorities
and must remain separately observable.

`conductorctl resource-request` must capture its parent process identity and send
it in the command payload. Known adapters should additionally pass their own PID
and start time explicitly so a `.cmd` shim or intermediate launcher cannot make
the short-lived CLI process look like the owner. Conductor must validate that an
explicit owner PID is the CLI parent or one of its ancestors and that the supplied
start time matches the live process before admitting the request. Invalid identity
fails closed with:

```text
OWNER_PROCESS_IDENTITY_INVALID
```

On an idempotent replay from the same proven owner, refresh
`owner_last_seen_at_utc` before returning the current state. A different owner may
not adopt the row by reusing its idempotency key.

### AR-2 — Atomic sweep before admission and promotion

Owning repo: `dotclaude-ecosystem`.

Implement one private locked primitive in `HostResourceManager`; do not build a
second reaper or open a second database transaction. It must, for one pool:

1. convert expired `ACTIVE` leases to `RECOVERY_REQUIRED`;
2. release proven-dead fenced owners;
3. terminalize proven-dead queued owners;
4. apply the legacy queue cutover;
5. promote only a queued request whose owner identity is current and live;
6. return structured counts and affected request IDs.

Call the primitive inside `request()` **before** idempotent replay and before the
capacity query. This is the mandatory self-heal path when no daemon is running.

Also call it from `reconcile()` and expose its result without changing the
existing nonzero/error behavior. `dry_run=True` must report the same candidates
without modifying requests, leases, events, or queue order.

Promotion must loop past terminalized stale rows. It must never create a lease
for an owner whose liveness is absent or disproven.

### AR-3 — Daemon sweep for every pool

Owning repo: `dotclaude-ecosystem`.

Extend `conductord.run_coordinator_loop()` so its periodic pass sweeps every row
in `host_resource_pools`, not only `host:heavy` and not only the hard-coded
defaults. Keep this as a second trigger for the same AR-2 primitive, not a second
implementation.

The daemon is an accelerator, not a prerequisite: all acceptance tests must also
pass with no daemon process.

### AR-4 — Adopt explicit owner identity in known consumers

Owning repos and files:

| Repo | File | Required change |
|---|---|---|
| WatchF | `watchf/browser/host_heavy_lease.py` | Add current process PID/start time to `resource-request`; cover CoderPX and other CDP users of this adapter. |
| Tsignal 5.0 | `tsignal/services/cctv_feed_supervisor.py` | Add supervisor PID/start time to the `cdp:tv` request. The supervised producer remains the child, not the owner. |

Do not edit the dirty primary Tsignal checkout. Use an isolated worktree from the
current `origin/main`, and touch only the supervisor plus its focused tests.

No consumer may call `resource-recover`, provide operator attestation, kill a
foreign process, or implement its own lease database cleanup.

### AR-5 — Make the installed GUI canonical and visible

Owning repo: `dotclaude-ecosystem`.

Files:

- `scripts/conductor_install.py`
- `scripts/conductor_gui.py` only after resolving the PR #98 collision
- installer and GUI tests

Add `conductor_gui` to the installer-owned canonical commands and shims. After an
upgrade, `install-manifest.json` must name the merged source head and the installed
GUI hash must equal the source hash.

PR #97 already added one RECOVER button per fenced blocker. Do not reimplement
that mutation. PR #98 is currently open and is the sole owner of the GUI layout
and “all pools visible without scrolling” change. Either land #98 first and branch
from the new `main`, or rebase after it lands. Never overwrite its palette/layout
diff.

Acceptance for the installed window:

- every fenced pool is visible from the top pool strip;
- selecting/locating a fenced pool exposes its RECOVER control without requiring
  a repository checkout;
- proven-dead rows normally disappear through automatic recovery before the
  operator needs the control;
- ambiguous rows keep a visible manual RECOVER control and confirmation dialog;
- the GUI remains port-free and does not become a background mutation loop.

Do not merge Conductor authority into EcosystemControl in this slice. A common
shell remains a separate product decision.

## 6. Required red/green tests

Write the tests before the production change.

### Core resource tests

1. Expired owner PID absent: a new request atomically releases the fence and is
   admitted; no attestation is supplied.
2. PID reused: same behavior, with `AUTO_RECOVERY_OWNER_PID_REUSED` evidence.
3. Owner PID/start still alive: remains fenced and the newcomer queues.
4. Process lookup access denied: remains fenced.
5. Active inherited child: remains fenced even when the parent PID is gone.
6. Legacy `tsignal-cctv:<absent-pid>` and `coderpx:<absent-pid>` fenced rows recover.
7. Unsupported legacy identity remains `OWNER_LIVENESS_UNPROVEN`.
8. N stale queued owners followed by one live owner: all stale rows terminalize
   and only the live owner is promoted.
9. Pre-v7 queued rows with no owner identity receive
   `LEGACY_QUEUE_OWNER_UNRECORDED`; pre-v7 active/fenced rows do not.
10. Idempotent replay by the same owner refreshes last-seen; a different owner
    cannot adopt the key.
11. `dry_run` reports candidates and writes zero rows/events.
12. Two concurrent admission calls cannot both recover/promote the same capacity.

### CLI/daemon tests

1. `resource-request` records a real owner PID and creation time.
2. An explicit owner PID not in the CLI ancestry is refused exactly with
   `OWNER_PROCESS_IDENTITY_INVALID`.
3. `conductord --single-pass` sweeps all database-defined pools.
4. The original request path self-heals while no daemon exists.

### Consumer tests

1. WatchF `HostHeavyLease` sends the CoderPX process identity, not the temporary
   `conductorctl` process identity.
2. CCTV sends the supervisor identity and retains the producer as a child.
3. Neither consumer auto-attests or kills another process.

### Installer/GUI tests

1. `TOOL_SCRIPTS` and manifest contain `conductor_gui` plus Windows/POSIX shims.
2. Source mismatch is reported before upgrade and eliminated after upgrade.
3. Installed `conductor_gui.py` contains the same RECOVER behavior as source.
4. Widget smoke: a fenced fixture renders the RECOVER control from the installed
   module; skip only with the existing explicit no-display reason.

Targeted gate after implementation:

```powershell
python -m pytest scripts/tests/test_conductor_resources.py scripts/tests/test_conductor_store.py scripts/tests/test_conductor_cli.py scripts/tests/test_conductor_gui.py scripts/tests/test_conductor_install.py -q
```

Then run the complete `dotclaude-ecosystem` suite through the managed
`host:heavy` test adapter. Do not bypass Conductor to test the Conductor fix.

## 7. Landing sequence and live proof

1. Resolve or land PR #98, then start the Conductor implementation branch from
   the resulting `origin/main`.
2. Land AR-1 through AR-3 and AR-5 as one Draft PR because schema, admission,
   recovery, installer, and GUI evidence form one R2 contract.
3. Land WatchF and Tsignal adapter adoption as dependent Draft PRs. Keep Tsignal
   changes out of its dirty primary checkout.
4. Run exact-head review and fresh CI under the normal R2 workflow. Do not mark
   Ready or merge without the implementation GO above.
5. After merge, run the ownership-checked Conductor installer from the merged
   source. Do not hand-copy files into `~/.conductor/app`.
6. Let the running CCTV supervisor's next request exercise the `cdp:tv`
   self-heal path. Exercise `cdp:perplexity` with one bounded CoderPX probe and
   `host:heavy` with the previously queued benchmark/test request.
7. Capture receipt-free `resource-live --all --json` before and after. The final
   proof must show zero `RECOVERY_REQUIRED`, no legacy stale queue entries, and
   only leases whose recorded owners are live.

No live proof may kill PID `104996`, `8384`, `148260`, or any current lane owner.
Those three historical PIDs are already absent.

## 8. Definition of done

- [ ] A dead, identity-bearing owner cannot leave a pool fenced indefinitely.
- [ ] Self-healing works on the next request with `conductord` absent.
- [ ] A running `conductord` sweeps every configured pool through the same code.
- [ ] Stale queued consumers cannot be promoted into fresh orphan leases.
- [ ] Live, inherited, access-denied, and unrecorded ambiguous owners remain
      fail-closed.
- [ ] Every automatic transition carries deterministic event evidence and an
      exact reason code.
- [ ] WatchF CoderPX and Tsignal CCTV send durable owner identity.
- [ ] The installed GUI is at the merged source head and has a canonical launcher.
- [ ] RECOVER remains available for ambiguous rows, but normal proven-dead
      cleanup requires no operator command or click.
- [ ] The three-pool 2026-08-31 fixture passes and the live queues unblock without
      process termination.
- [ ] Work lands through branch -> Draft PR -> exact-head R2 review -> fresh CI;
      runtime install remains a distinct post-merge proof step.

## 9. Explicit exclusions

- No process kill, tree kill, WMI/CIM fleet scan, or foreign-role preemption.
- No automatic attestation.
- No age-only release of `ACTIVE` or `RECOVERY_REQUIRED` rows.
- No browser-fabric flag change and no model/provider default change.
- No second scheduler, lease store, HTTP server, or port.
- No merge of Conductor and EcosystemControl authority.
- No WatchF benchmark implementation in this slice; this repair only removes its
  resource blocker. Resume the benchmark after live recovery proof.
