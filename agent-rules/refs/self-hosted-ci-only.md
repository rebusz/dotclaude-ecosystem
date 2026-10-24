# Included GitHub Actions capacity with local fallback

Risk: R0 policy within the R3-authorized hybrid CI project.
Operator decision: 2026-10-24. The existing filename remains a compatibility link.

## Scope and authority

This policy supersedes the 2026-09-17 prohibition on GitHub-hosted CI in all
operator-owned repositories, including new repositories. GitHub remains the
repository, PR, check and workflow control plane. Use the included allowance for
portable private-repository jobs and switch to compatible local self-hosted
runners before exhausting that allowance. The existing `rebusz` Actions budget
is **USD 3 per month with Stop usage when budget limit is reached enabled**.
It is a backstop for metered usage, not permission to increase the budget or a
target to spend. Other billing products and account settings are unchanged.

Project plan:
`D:/APPS/_shared/design/plans/2026-10-24_hybrid_ci_budget_r3.md`.
The August local-CI plan's resource isolation and watchdog contracts remain in
force. This decision changes routing, not review, required checks or live-trigger
authority.

## Admission and routing

1. Before push, PR-ready, dispatch or rerun, inspect the affected workflows at
   the exact head, including matrices, expressions, reusable workflows and
   third-party execution. Classify each job as portable, host-affine or untrusted.
   Existing host-affine jobs and workflows pinned to another attempt's host or
   provenance remain local; do not silently rewrite their custody contract.
2. Admit portable private jobs to standard GitHub-hosted runners only using
   authenticated, fresh usage and entitlement evidence for the repository owner
   and current billing period. Quota is shared across that owner's repositories.
   Include the configured safety margin, bounded job cost and concurrent
   reservations. Unknown or stale usage, an exhausted admission threshold, an
   unverified runner SKU or missing billing access selects the compatible local
   route. An API error is never zero usage. Larger runners and other paid cloud
   services are outside this policy.
3. The private-job selector must run independently of hosted-minute availability,
   on an approved trusted self-hosted controller. It must not execute untrusted
   checked-out code or expose its billing credential to build steps. A cached
   repository variable alone is not fresh admission evidence. Monthly reset
   requires a fresh current-period observation; clock rollover alone does not
   clear unresolved reservations or authorize hosted work.
4. Verify local runner registration, OS, labels and online capacity before
   claiming fallback is available. Windows capacity does not establish Linux
   compatibility. Preserve job/check names, test coverage, environment isolation,
   artifacts and required-check semantics across routes. A missing compatible
   runner or required check is BLOCKED; a repository without CI is NO_CI.
5. Preserve the account's USD 3 hard-stop setting and check storage as well as
   minutes. Artifact retention and cache limits must remain bounded. Budget
   alerts alone are not a stop control. Never add a payment method, raise a
   budget, disable the hard stop or expand credential permissions to force
   admission without the applicable authorization.

## Public repositories and untrusted contributions

Public repositories use standard GitHub-hosted runners, whose compute is free
under GitHub's current public-repository terms. This does not authorize larger
runners, unbounded storage or automatic transfer of public/fork pull-request
code to the trusted trading workstation. Keep ordinary GitHub fork approval,
token and secret restrictions. Untrusted private contributions also never reach
the trusted controller or workstation. If hosted execution is unavailable, keep
the failure visible or use separately approved isolated infrastructure; do not
fall back to the trusted workstation or weaken repository security.

## Execution, migration and recovery

Use bounded local concurrency, job timeouts and the existing affinity,
BelowNormal-priority and watchdog contracts. Do not create an unbounded heavy
lane per repository. Preserve unknown submissions, existing attempts and live
runner ownership. A failed test/build remains a failure, not a trigger to rerun
elsewhere until green. A confirmed pre-execution infrastructure rejection may
select the validated fallback; uncertainty about whether execution started must
be reconciled before any replacement run.

Retain before/after workflow states and IDs. Re-enable previously paused
workflows only after their routes and compatible environments are validated.
Keep implementation PRs draft and batch pushes. Do not remove branch protection,
rename away a required failure, or treat a skipped check as a passing test.
Completion needs real successful exact-head jobs with job URL, runner identity,
OS, conclusion and test evidence for the hosted and applicable local routes.
Exercise quota exhaustion, stale/missing telemetry, concurrent admission,
billing reset and infrastructure rejection through the real selector path.
Static validation establishes configuration, not runtime acceptance.

Rollback selects a proven local route for trusted private jobs or pauses the
affected workflow while preserving the failure and custody evidence. Public
jobs retain standard-hosted-only admission. Rollback never lifts the USD 3 cap,
routes untrusted code to the workstation, or removes services automatically.

## Instruction delivery

Canonical policy is this file plus `agent-rules/core.md`; update generated global
rules only with `scripts/sync_agent_rules.py`. Review pre-existing source/target
drift before installation so a CI change does not overwrite unrelated rules.
Preserve manual sections and verify Claude, Codex, Cline and Antigravity readback
separately. Update the CI section of `D:/APPS/AGENTS.md` through its owner, keeping
the port contract intact. Existing conversations and delegated workers must read
the current policy before their next CI action; installation alone is not proof
every active session acknowledged it.
