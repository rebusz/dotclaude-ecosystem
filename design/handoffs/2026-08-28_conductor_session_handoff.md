---
title: "Session handoff — Conductor gate visibility and CDP pool split"
date: 2026-08-28
status: HANDOFF — read before continuing Conductor work
risk_class: R2
repo: dotclaude-ecosystem
scope: "This session owns Conductor only. Cross-repo work goes out as handoffs."
---

# Session handoff — Conductor gate visibility and CDP pool split

## Start here

Everything below was driven by one incident. On 2026-08-27 a CCTV lease expired at
`14:17:17Z` into `RECOVERY_REQUIRED`. Admission blocks on `{ACTIVE, RECOVERY_REQUIRED}`, so a
**dead** lease fences exactly like a running one while `active_units` reads `0`. Seven
requests queued behind a corpse for five hours: CoderPX, five CCTV retries, `t4-ops-unblock`,
and a `/fwf` matrix run. A second Opus session looked at it and concluded "two lanes are
occupied by X and gpt". Nothing was occupied.

Two root causes came out of that, and both are now fixed:

1. **The gate was invisible.** The only diagnosis path wrote a 262 KB receipt per read.
2. **One pool served four unrelated workloads.** A prompt to an already-running Chrome
   queued behind a full pytest suite.

## What shipped to `main`

| Commit | What |
|---|---|
| `f5a5517` | Gate Panel plan, `/fwf` reviewed (CEO + matrix + eng) |
| `c7cad5f` | `doctor` reads the resource pool and exits non-zero when the gate is wedged |
| `0b2b666` | CDP admission pool split plan |
| `ddf5dad` | Gate Panel GP-1..GP-5: live projection, verdict engine, Tk panel |
| `1b6d0cc` | CDP pool split CP-1/CP-2/CP-5: four pools, `slot_key`, per-pool panel |

### Measured effect

| Read path | Latency | Payload | Receipt written |
|---|---:|---:|---:|
| `resource-status --json` | 1,560 ms | 244 KB | **262 KB** |
| `resource-live --json` | **~16 ms** | **2.2 KB** | **0** |

Before this, 140 occasional manual `resource-status` reads had grown to 15.45 MB, **80% of
the entire receipt store**, with retention `REPORT_ONLY` so nothing ever deletes them.

### Live state right now

```
cdp:chatgpt      cap=3 enabled=1
cdp:gemini       cap=1 enabled=1
cdp:perplexity   cap=3 enabled=1
host:heavy       cap=1 enabled=1
```

Run the panel: `python scripts/conductor_gui.py`

## Open, and the order matters

### 1. PR #91 — `cdp:tv` pool. BLOCKING. Merge first.

**This is a regression I shipped in #90 and it is a latent outage.**

#90 enforced that `cdp_*` purposes are refused on `host:heavy`, but seeded only
`cdp:perplexity`, `cdp:chatgpt` and `cdp:gemini`. CCTV drives `chrome_tv` (port 9225,
dedicated TV profile) and was left with nowhere valid to go. Its next admission request
raises:

```
ValueError: CDP purpose 'cdp_provider' cannot consume 'host:heavy'
```

CCTV's last request was `2026-08-28T17:58:33Z`; #90 merged at `17:58:56Z`. **Twenty-three
seconds of margin.** It has not fired only because CCTV has not restarted.

#91 adds `cdp:tv` at capacity 1, routes `chrome_tv` to it, and proves fence isolation.
85 passed, exit 0. Nothing else should merge before it.

### 2. Consumer adoption, other repos — handoffs already written

Both repos have other agents working in them right now. Neither should be edited from a
Conductor session.

| Repo | State | Handoff / PR |
|---|---|---|
| WatchF | **broken against merged Conductor.** `HostHeavyLease` requests `cdp_provider` on `host:heavy`, which is now refused, so CoderPX and the `/fwf` CDP lanes are rejected. | WatchF PR #403 (code, written before the "handoffs only" boundary — needs coordination with whoever owns WatchF now) |
| Tsignal CCTV | breaks on next restart, see #91 above | Tsignal PR #1496 (handoff doc) |

Both fail **closed** rather than misrouting, which is the correct failure mode, but they are
outages until adopted.

### 3. CP-4 — response completion detection. Parked, deliberately.

The operator reports that a model sometimes emits a short "here is what I will do" sentence,
then thinks, and CDP returns that preamble as the final answer, which the caller treats as an
error.

**Not reproduced.** I looked for it in the 2026-08-27 evidence and it is not there: all three
"failed" Perplexity models returned complete, coherent 3.7-4.2 KB answers. The requirement is
accepted and recorded in the pool-split plan; the slice must **start by capturing a
reproduction** before anyone changes capture logic. It also lives in WatchF's CDP capture
path, not in Conductor.

## Unfixed, found on the way, not mine to fix here

### `fuse.py` compaction destroys the audit payload

This is the most expensive unfixed thing found this session.

All three "failed" Perplexity models in the 2026-08-27 matrix run answered correctly and
refused for the same reason: `fuse.py` compacted a 73 KB plan into headings with the content
stripped.

- Kimi K3 (4,134 B): *"the plan you've asked me to audit appears to be heavily truncated"*
- Claude Sonnet 5 (4,194 B): *"heavily compacted/truncated — many sections show only partial headings"*
- Nemotron 3 Ultra (3,713 B): *"most sections show only partial headings… cut off mid-sentence"*

Each quoted the same mutilated fragment, e.g. `"Make the three distinct host:heavy conditi"`.
**Three of four roster models were spent on an unreadable payload, and the matrix reported
them as lane failures rather than a payload defect.** Fix candidates: raise the input budget,
chunk, or attach the plan by reference — the GitHub connector is already present and enabled
in those lanes. Lives in `D:/APPS/_shared/audit/fuse.py`.

### `TsignalGitHygiene` alarms nobody acts on

Re-enabled this session and its watch list corrected (it was watching only Tsignal, not
`dotclaude-ecosystem`, so it would not have caught any of this session's drift). Verified
end to end, exit 0.

But it was disabled because it alarmed daily for weeks and nothing acted. Tsignal is at
**706 worktrees and 1,246 local branches**, growing about 10 worktrees a day. Reaped 51
worktrees and 113 branches in Tsignal, and 1 worktree and 2 branches in dotclaude, this
session. Remaining reapable in Tsignal after that pass: worth re-running the dry run.

**69 design docs exist on exactly one unmerged branch each and nowhere else.** The reaper
protects those branches, so they never surface. That is content at risk, not clutter.

## Things a new session should know

- **`conductorctl` has no `claim` command.** WorkItem `wi_07c6805f8d5f` is `READY` and
  authorized (`auth_fcf07a7d3aa7`, tty-verified). It will stay `READY`: claiming runs through
  the Host Adapter path and Cursor is `HOLD_UNSUPPORTED` for autonomous dispatch. It is an
  authorization record, not a live queue entry. Do not wait for it to flip.
- **An auto-backup hook commits and pushes `design/` edits under generated messages**, and
  sometimes amends its own commit. It raced this session repeatedly. Content was never lost,
  but the real message belongs in the PR body, since PRs squash-merge.
- **`gh pr merge` is sometimes blocked by the auto-mode classifier** and sometimes not. When
  blocked, the operator merges.
- **Antigravity dispatch:** `agy --model gemini-3.7-flash-high --effort high --mode
  accept-edits --dangerously-skip-permissions`. Do **not** pass `--sandbox`: it auto-denies
  every tool permission and returns **exit 0 having done nothing**. Pass the prompt from a
  file; a heredoc inside `$(...)` breaks on apostrophes.
- **Always re-run the tests yourself.** Antigravity's reports were honest every time this
  session, but one of its diffs still shipped a real footgun (see below).

## The one test that does not run

`test_clipboard_copy_performs_no_store_access` **skips** on this machine:
`Can't find a usable tk.tcl`. Clipboard needs a fuller Tcl/Tk init than widget construction;
the other six `tk_root` tests run. That invariant is **unverified here**. It is stated in
#89 and again in #90 rather than hidden.

## Judgement calls worth not re-litigating

- **`orphan_adoption_allowed = False` is correct** and was deliberately not touched.
- **`HostHeavyLease` keeps its name** even though it now leases any pool: it is imported by
  name in three files and renaming widens the diff for no functional gain.
- **Promotion is no longer strictly FIFO.** When the queue head is blocked only by
  `slot_key` exclusivity, promotion skips it; otherwise one queued Kimi 3 request would
  head-of-line block every other model. Commented and tested.
- **A fail-fast guard was added at the WatchF seam** because the class defaults
  (`purpose="cdp_provider"`, `resource_key="host:heavy"`) were exactly the pair Conductor now
  refuses. A bare `HostHeavyLease()` was invalid and **seven existing tests were constructing
  it**. In production that surfaces as a generic refusal three subprocess layers from the
  cause.

## Next concrete action

Merge **PR #91**. Everything else waits behind it.
