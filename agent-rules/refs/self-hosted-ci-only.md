# Self-hosted CI only

Risk: R0 policy. Operator decision: 2026-09-17.

## Scope and authority

All operator-owned repositories, including small, public, experimental and newly
created repositories, execute CI/build/release jobs only on operator-controlled
local self-hosted infrastructure. GitHub remains the repository, PR, artifact and
workflow orchestration service. Free hosted minutes and a zero-dollar billing
cap are not exceptions. This supersedes the small-repository hosted-free-tier
exception in the 2026-08-13 local CI plan and any older agent instructions.

## Agent contract

1. Before push, PR-ready, workflow dispatch or rerun, read all affected workflow
   triggers and routes at the exact head. Inspect matrices, expressions, reusable
   workflows and third-party build services, not only literal `runs-on` strings.
   Every executable job must resolve to an approved local self-hosted runner.
2. Verify repository visibility, runner registration, labels, OS and online
   capacity. A workflow edit is not runner installation, and an online Windows
   service does not prove a Linux/container job works. A repository with no CI
   is NO_CI, not migrated or PASS.
3. No automatic cloud fallback, hosted rerun, free-tier exception, or fake green
   check. Missing infrastructure/review/required check means BLOCKED. Preserve
   required-check names and test coverage during migration. Do not remove branch
   protection to get a merge through.
4. Use bounded local concurrency, isolated job environments, timeouts and the
   existing affinity/priority/watchdog contracts. Do not create one unbounded
   heavy lane per repository on the workstation. Changes to services, pools and
   Linux infrastructure follow the R1 workflow and applicable operator gates.
5. Validate locally, batch pushes and keep implementation PRs draft. Completion
   requires a successful real job at the exact head with runner name/OS/labels,
   job URL, exit/conclusion and artifact evidence. Static validation alone is
   CONFIGURED, not runtime acceptance.

## Public repositories and untrusted contributions

Never route public/fork pull-request code or untrusted workflow edits onto the
trusted trading workstation. Use separately isolated operator-controlled local
infrastructure and admission controls, or leave automated execution BLOCKED and
run trusted reviewed validation locally. Do not change repository visibility,
weaken security, or substitute cloud execution to avoid this boundary.

## Migration and recovery

Hosted workflows may be paused as containment with their prior state and exact
workflow IDs recorded. That pauses CI; it does not constitute a completed
migration. Re-enable only after route validation and compatible local execution
are proven. Rollback restores a known self-hosted workflow or pauses the broken
workflow; it never restores cloud execution. Keep failures and queued work visible.

## Instruction delivery

Canonical policy is this file plus `agent-rules/core.md`; update generated global
rules only with `scripts/sync_agent_rules.py`. Verify Claude, Codex, Cline and
Antigravity readback separately. Other hosts and delegated workers must receive
this policy through their actual instruction loader/task packet. Existing agent
conversations can retain old instructions: require a fresh read before their next
CI action. File installation is not proof every running agent acknowledged it.
