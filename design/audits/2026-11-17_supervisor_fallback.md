# Supervisor fallback implementation evidence (R1)

Date: 2026-11-17. Owner: Codex chat `01a1ea08`.
Base: `39186f50f3127b0a71809a59f0b53e17adbd7074`.
Implementation: `5b5e65f830b8c9275a77326c423bc1215c472dd5`.

## Scope and custody

Operator authorized the rule and its installation, without a second takeover GO.
Only supervisor policy, installer and tests changed. No TST application code,
TWS/Tsignal, desktop, services, accounts or actual broker orders were touched.
Existing worker attempts and paused jobs are unchanged.
Canonical checkout had one unrelated untracked audit directory, preserved.
Existing available worktrees had other owners/untracked files or historical work;
none had a release for this assignment. New exclusive locked worktree:
`D:/APPS/_worktrees/dotclaude-supervisor-fallback-20261117`, branch
`codex/supervisor-fallback-20261117`. No existing worktree was adopted or reset.
Root AGENTS.md/CLAUDE.md do not exist in the policy repository. The plan loader
returned `could not detect repo` despite a valid Git root; bounded fallback used
IDEA_BOX and the existing October 26 plan. Graph reported stale HEAD, so targeted
source reads supplied the dependency map.

## Source and enforcement

`templates/supervisor-contract.md` is canonical; installed home ref wins in
`scripts/session_router.py::_supervisor_contract`. The original contract's blanket
coding/read/diagnosis ban and QUEUED-only rule caused the instruction-level block.
The new contract requires documented native completion when permitted workers
fail terminally or are unavailable before submission. Healthy workers remain
preferred. It lifts only supervisor role/read/edit/test/20-line constraints.
Uncertain submits, foreign owners, independent review, tests, CI and protected
triggers remain gated. Binary/probe/UI labels are explicitly insufficient proof.
`agent-rules/core.md` and roster reference agree; the old plan is explicitly
superseded on these clauses, with historical evidence retained.

Active `~/.claude/settings.json` registers SessionStart at the canonical repo's
`session_router.py`. Its only PreToolUse guard is the installed
`~/.claude/hooks/model_launch_guard.py` on Bash/PowerShell. Neither the canonical
repo nor installed hooks contains the planned supervisor source-read ban,
20-line counter or claude_worker_guard. Those planned hooks were not invented,
removed or disabled. The model guard and all settings stayed byte-identical.

## Validation

Python 3.12 command (exit 0):
`py -3.12 -m pytest scripts/tests/test_supervisor_fallback.py scripts/tests/test_session_router_contract.py scripts/tests/test_sync_agent_rules.py scripts/tests/test_session_router.py scripts/tests/test_chatgpt_cdp_routing_policy.py -q --basetemp D:/APPS/_scratch/supervisor-fallback-final-01a1ea08`
Result: **64 passed, 8 subtests passed**, no skipped tests.
Targeted ruff: exit 0. `git diff --check`: exit 0.

The six cases assert the actual SessionStart-injected contract's boundaries for
terminal workers, healthy worker, uncertain submit, live foreign owner, tool
denial and protected triggers. They are policy regression tests, not an LLM
behavior simulator or executable order authorization tests.
The seventh test drives the real PowerShell installer into an isolated home,
checks backup and unchanged settings, loads its installed contract through a
fresh SessionStart process, preserves a synthetic terminal receipt, runs a real
failing fixture test, edits more than 20 source lines with native Python, then
runs the real unittest successfully. It invokes no provider/model and proves
native tools plus instruction installation, not future model compliance.
Initial exploratory Python 3.14 run passed seven tests but emitted a pytest
atexit cleanup PermissionError; final validation used 3.12 and an exclusive temp
root and had no such error. No permissions were changed to repair cleanup.

Actual installed PreToolUse guard replay: ordinary unittest command returned no
hook denial (exit 0); forbidden `codex exec -m gpt-6-sol` returned deny (exit 0).
These are payload replays; the forbidden command was never executed. Guard hash:
`c2d95aa11d7cbc647244a56d84ad0eb2c0d5517c65f4ffa6906592a2e24c286e`.

## Installation and readback

Ran `install/install.ps1 -SupervisorContractOnly`, then the same with `-Check`:
both exit 0. Scoped installer backs up the old ref, replaces via temp file and
checks hash; it changes no settings, hook registrations, sandbox or permissions.
Contract installed at `C:/Users/dszub/.claude/refs/supervisor-contract.md`, SHA256
`7ab90bc669e6900616119e0690b3eaf19b76c296cd262fa45704d786bdd4be86`.

Ran existing `scripts/sync_agent_rules.py --source-root agent-rules --write`
with explicit targets `codex-global`, `claude-global`, `cline-global`,
`antigravity-global`, then `--check`: all four clean, exit 0. Generator enforced
committed sources and its existing size limits; only the intended managed line
changed for Codex/Claude (preflight diff inspected), no managed block hand edits.
Backups are generator-owned under `~/AppData/Local/Temp/agent-rules-backups`.
Settings SHA256 both before and after:
`269f77140df128e1f69e71e80232b67d25f98cf8da29f7e847b00fbcc162249a`.

A fresh process invoked the exact registered canonical SessionStart script with
no SUPERVISOR_CONTRACT_PATH override, probes disabled and isolated session-state
dir. Exit 0; its additionalContext started with the exact installed contract.
Local receipt: `D:/APPS/_scratch/supervisor-fallback-guard-01a1ea08.json`.
This proves the fresh hook readback. A new interactive model chat consuming that
context was not launched; already-open chats' higher-priority instructions are
not retroactively overridden. No existing chat behavior is claimed repaired.

## Delivery gates

Preliminary separate-session native GPT review found no P1/P2; it is not the
required cross-family review by itself. Exact-head cross-family review and CI
are pending at this documentation commit and must be reported with real receipts.
Public repo CI is standard `windows-latest`, 30-minute cap, no workstation route;
draft PR CI is intentionally skipped until ready. No branch protection was
reported by GitHub (404); that does not waive policy gates.
