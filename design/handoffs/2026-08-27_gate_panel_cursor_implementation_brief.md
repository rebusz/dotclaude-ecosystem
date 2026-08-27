# Implementation brief — Conductor Gate Panel (GP-1 .. GP-6)

**Written** 2026-08-27 | **For** Cursor (implementation lane)
**Plan** `design/plans/2026-08-27_conductor_operator_gui_r1.md` (1,098 lines, R2)
**Authorization** `GO CONDUCTOR GATE PANEL R2` given by the operator 2026-08-27.
**Repo** `D:/dotclaude/dotclaude-ecosystem`, trunk `main`.

Read the plan. This brief is the build order plus the traps, not a replacement for it.

## What you are building

A local, port-free, **read-only** Tk window that answers one question about the Conductor
`host:heavy` gate: can a heavy job start right now, and if not, who holds it, since when, what
is queued, and what exactly must the operator type to clear it.

It is a **projection**. It adds no admission authority, no lease store, no release path, no
port. `PORTS.md` is not touched.

## Read this first: four traps that already bit this plan

Three review stages (CEO, cross-model matrix, engineering) found twelve defects **in the plan
itself**. Four of them are things a competent implementer would re-invent. They are corrected in
the plan, but they are the reason the obvious implementation is wrong.

### Trap 1 — the obvious read path is not read-only

Do **not** reach the data through `HostResourceManager` or `ConductorStore`. Both constructors
write:

- `conductor_resources.py:191` — `HostResourceManager.__init__` calls `save_resource_pool()`
  when the pool row is missing.
- `conductor_store.py:239` — `ConductorStore.__init__` creates directories and initialises or
  migrates the database.

A projection built on either fails `scripts/tests/test_conductor_cli_security.py:67`
(`test_cli_read_only_commands_do_not_create_home`) the first time it runs against an absent
`~/.conductor/`.

Use `_read_only_snapshot_connection` (`conductor_store.py:67`) instead. `read_store_status`
(`conductor_store.py:102`) is the worked example: it takes the snapshot at `:120` and returns an
`ABSENT` result at `:116` when the database file does not exist, without creating anything.
Copy that shape, including the absent case.

### Trap 2 — the blocking state set is smaller than it looks

The admission blocker set is exactly `{ACTIVE, RECOVERY_REQUIRED}`. Verified in both places that
enforce it: `conductor_resources.py:311` (admission) and `:897` (`_promote_locked`).

- `INHERITED` does **not** hold the gate. It is a child under the holder's lease.
- `QUARANTINED` does **not** block. Admission proceeds normally with quarantined rows present.
- `HOST_RESOURCE_DISABLED` is raised at `:238` **before** the blocker query, and on a missing
  pool row too, so DISABLED outranks everything.

There is no `pool_state` field. `HostResourcePool` (`conductor_model.py:285`) has only
`resource_key`, `capacity`, `enabled`, `schema_version`. `QUARANTINED` is a *request* state
(`conductor_model.py:240`).

### Trap 3 — `release` always refuses a fenced request the same way

For a request already in `RECOVERY_REQUIRED`, `release()` raises
`RECOVERY_REQUIRED_RELEASE_REFUSED` at `conductor_resources.py:395`, **before** it looks at
inherited children or process liveness. `INHERITED_CHILD_ACTIVE` at `:417` is reachable only
when the request is `ACTIVE`. Only `recover()` (`:504`) can answer `OWNER_PROCESS_ALIVE` or
`INHERITED_CHILD_ACTIVE` for a fenced request.

The panel must never tell the operator that `release` will report a liveness reason. It will
not, and saying so sends them down the exact dead end the panel exists to prevent.

### Trap 4 — the copyable command must run in PowerShell

The operator's shell is PowerShell. Backslash line-continuations are bash and are a parse error
there; a bare `python scripts/conductorctl.py` depends on the terminal's working directory. The
panel's single most valuable feature is "paste this", so a command that does not run is a
failed feature, not a cosmetic bug.

Emit **one line**, `&` call operator, quoted absolute paths resolved at runtime:

```text
& '<sys.executable>' '<repo>\scripts\conductorctl.py' resource-recover --request-id rr_… --attest-owner-gone --reason '<why>'
```

Accept it with a test that actually runs the generated string through PowerShell against a
temporary fenced store. Not by inspecting the string.

## Build order

GP-1 and GP-2 have no Tk dependency and carry the agent-facing half of the fix. GP-1 has
standalone value: it gives the CLI and any agent a 10 ms answer instead of a 1.6 s one that
damages the store. **Land GP-1 and GP-2 first, and do not treat them as scaffolding for GP-3.**

| Slice | Scope | Gate |
|---|---|---|
| GP-1 | `read_resource_live_snapshot()` and `read_gate_frame()` as **module-level functions in `conductor_store.py`**, beside `read_store_status`; `resource-live` CLI returning before any store object is constructed | Joins the existing read-only CLI contract; `status()` structural compatibility; promotion-order test |
| GP-2 | Verdict engine and recovery command builder as **pure functions with no Tk import** | Full state matrix + the differential test against admission |
| GP-3 | Tk panel: verdict banner, holder/blocker card, queue table, strip | Headless-safe render tests; panel never appears in the resource ledger |
| GP-4 | History drawer on `read_resource_history_page(limit, cursor)`; degraded states; clipboard; launcher | History must not reach `ConductorStore.list_resource_requests()` |
| GP-5 | `skills/conductor/SKILL.md` adoption; `IDEA_BOX.md`; parent-plan cross-reference | `sync_agent_rules.py` clean; no unmanaged-block edits |
| GP-6 | Focused tests, exact-head R2 review, draft PR, ready, CI, merge, checkout sync | One ready transition, reviewed exact head |

**One snapshot per refresh.** The footer needs `read_store_status()` and the body needs the
resource rows. Two calls means two `shutil.copy2` of a 17.1 MB database per refresh.
`read_gate_frame()` returns both halves from one connection. Pin it with a test that patches
`shutil.copy2` and asserts exactly one call.

## Non-negotiable invariants

1. No listening socket, no port. `PORTS.md` unchanged.
2. The panel **never** calls `resource-request` and never appears in the resource ledger. There
   is a test for this and it must drive the real path.
3. No writes to `conductor.db`, `receipts/`, `inbox/`, `artifacts/`.
4. Never present an action that bypasses `RECOVERY_REQUIRED_RELEASE_REFUSED`,
   `OWNER_PROCESS_ALIVE`, `INHERITED_CHILD_ACTIVE`, or `OWNER_LIVENESS_UNPROVEN`.
5. No process enumeration. Exactly one `psutil` lookup per displayed lease that recorded a pid,
   or "unknown". Zero WMI/CIM/process-list scans.
6. The panel reports the **observation** ("recorded pid 51204 is not running"), never the
   **conclusion** ("the owner is gone", "safe to attest"). `--attest-owner-gone` is where a
   human vouches for what the system could not prove; a panel that pre-vouches turns an
   attestation into a rubber stamp.
7. Reads happen on a worker thread, never on the Tk event loop. `sqlite3.OperationalError` from
   the snapshot maps to the existing "stale, retrying" state, not an error dialog.

## Tests that matter most

- **The differential test against admission** (GP-2). Build each state in a real store, call
  `HostResourceManager.request(...)`, assert the verdict agrees with what admission actually
  did. The verdict engine is a second opinion about admission; this is the test that stops it
  becoming a confident liar. It is the highest-value test in the plan.
- **The read-only contract** (GP-1). Add `resource-live` to the existing parametrized lists in
  `test_conductor_cli_security.py` at `:67` and `:97`, and mirror the WAL-visibility pattern at
  `:122`. Do not write a parallel receipt-counting assertion; the existing `_tree_snapshot`
  equality is strictly stronger.
- **The FENCED regression**, built from the captured 2026-08-27 readback: `active_units == 0`
  with one `RECOVERY_REQUIRED` and six `QUEUED` must yield FENCED naming `tsignal-cctv:79584`.

Heavy or full-suite runs request `host:heavy` through Conductor like any other consumer. This
work does not exempt its own tests from the gate.

## Landing

Branch, validate locally, commit, draft PR, review gate, `gh pr ready` once, squash-merge,
fast-forward the operator's checkout. R2 lands via draft PR plus review gate, never
direct-push to `main`.

Batch pushes and keep the PR draft while work moves. CI runs on the workstation's self-hosted
runner pool, which shares the box with the live trading stack.

## After you land

The operator has routed the implementation review to **CoderPX with Kimi 3**. Leave the PR
draft-ready with the exact head recorded so that review runs against a real diff.

## What is explicitly NOT in scope

Mutating controls in the panel, auto-release or auto-retry, a second admission authority, a
tray or always-on shell, remote access, capacity above 1, any resource class other than
`host:heavy`, application start/stop (that is the Ecosystem Control Panel), Chrome or
`chrome_ppl` ownership, and granting R2/R3 GO from the GUI.

Two known-good follow-ups are recorded in the plan and are **not** yours: teaching
`conductorctl doctor` about the resource pool, and receipt retention. Do not fold them in.
