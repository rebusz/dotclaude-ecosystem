---
title: Keep recorded live owners across CDP max-hold admission sweeps
status: review-pending
risk: R2
repos: [dotclaude-ecosystem]
owner: root integration; native Sol/xhigh bounded implementation
---

# Goal and authority

An ACTIVE ChatGPT/Perplexity request older than 900s currently loses its slot
even with a matching live owner and a fresh heartbeat. Any pool's request()
can trigger that global sweep, including Gemini or another provider. This can
admit overlapping work while the original worker still runs.

Root explicitly selected the current agent-rules/core.md live-owner veto over
the deliberate release-live-owner test introduced by #144. Preserve #144's pool
capacities and 900s max-hold threshold otherwise. Risk is R2 because resource
ownership, persisted admission and recovery contracts change. Standing scoped
GO authorizes this repair, not live state edits, deployment or a held-job retry.

Manual evidenced /fwf path is used. Native Codex Sol/xhigh authors under root's
explicit assignment after source-proven unsafe ChatGPT/PPL admission blocked
those routes. No artificial provider probe, old-C-copy reroute or model turn
was used. This authorship is not an independent review or a legacy panel run.

# Frozen scope and base

Base 298882fa7ca78a254bff6ab92de9eddae89f503f; locked root
D:/APPS/_worktrees/codex-conductor-live-owner-veto-20261109,
branch codex/conductor-live-owner-veto-20261109. Only:

- scripts/conductor_resources.py
- scripts/tests/test_conductor_resources.py
- this plan

Source/test base hashes and Git ownership guards are in
D:/APPS/_scratch/weekend-supervisor-20261108/provider_conductor_worktree_guard_20261109.json.
Graph context is missing; bounded AST/source/test/rg fallback is used. Repo
IDEA_BOX and related plan names were inspected; this is a focused correction
to #144, not a new resource coordinator or duplicate queue.

# Intended correction

The max-hold branch must adjudicate every recorded request/lease process
identity using the existing PID plus creation-time check. One live or
unprovable recorded identity vetoes reclaim. An unrecorded fresh holder must
not be released solely because activation is old; existing ordinary stale
unrecorded cleanup semantics remain bounded by their own TTL rules. Preserve
the inherited-child veto, recovery boundaries, promotion-time accounting and
all other pool/capacity/TTL/authorization policies.

Max-hold eligibility remains ACTIVE cdp:chatgpt and cdp:perplexity. Admission
trigger scope remains cross-pool; tests must prove another pool cannot free
a live eligible holder. Do not change the global sweep into a narrower
query that hides other necessary recovery work.

# Validation and rollback

Use only an isolated temporary ConductorStore. A retained Popen(shell=False)
child with its actual psutil creation identity owns the request; controlled
clock and real manager heartbeat calls cross 901s without sleeping 900s. RED
must show current live/unprovable owners wrongly reclaimed. GREEN must prove
live owner/fresh heartbeat and cross-pool request keep the slot; after the
owned child actually exits, max-hold dead-owner cleanup still releases. Also
cover unprovable recorded identity, fresh unrecorded owner, RECOVERY_REQUIRED
live owner and surviving INHERITED child, plus promotion/maxhold0/capacity
regressions. Never mock the primary liveness verdict or use the live DB.

All pytest commands use exact python -m pytest with a retained Popen handle,
shell=False, bounded timeout/log/exit; focused tests are lightweight. No live
lease/admission/JSON/pool/account changes, installation, C-copy sync, global
hooks, CI, commit or push in this worker slice. Root owns independent exact
candidate review and subsequent Git/delivery. Missing review is NO_REVIEW.

Rollback is the isolated reviewed source delta. Effective canonical D: code
and installed C: copy remain unchanged during this slice, so the admission
HOLD is not lifted merely because this candidate passes tests. Previously
uncertain attempts retain their original custody and are never resubmitted.

# Candidate evidence and remaining gates

The implementation removes the hard-max shortcut around the existing common
owner checks. Thus every recorded request/lease identity is adjudicated before
reclaim, and the existing child veto still follows. With no recorded identity,
max-hold alone cannot reclaim a holder before its ordinary stale-activity TTL.
For max-hold cleanup the reason remains CDP_MAX_HOLD_EXCEEDED; evidence now
records OWNER_DEAD or OWNER_UNRECORDED rather than treating age as death proof.

Retained subprocess evidence is under
D:/APPS/_scratch/weekend-supervisor-20261108/provider_conductor_live_owner_20261109/:

- RED: 10 failed, exit 1, PID 43084, 2.422s wall, original production hash
  cb80d0834a714fbc862ccd09af022c1b2d7046cc1f53927bb59252f0216edb42.
  First assertion: a live holder was wrongly in swept_request_ids, test line 926.
- Focused GREEN: 27 passed, 69 deselected, exit 0, PID 11152, 4.375s wall.
- Complete resource test file: 96 passed, exit 0, PID 62248, 27.672s wall.
  Both GREEN commands imported the owned candidate; no timeout occurred.

Native authorship is Sol/requested xhigh; no delegated generation or independent
review is implied. Root owns independent candidate review and Git. Commit,
push, PR, CI, installation, effective-source sync, and live-admission validation
remain pending/held. No live queue, lease, pool, account, or policy was edited.
The plan hook uses --skip-catalogs to preserve this three-path write boundary;
global catalog regeneration belongs to root integration.
