# Global `/fwf` + `/fwp` Contract Reset

**Grade:** R1 — global agent workflow tooling, prompts, tests, and documentation; no trading runtime or order path.
**Status:** SHIPPED / REVIEW PASS (2026-07-21)
**Owner:** `dotclaude-ecosystem` with coordinated changes in `claude-config` and `D:/APPS/_shared`.
**Supersedes:** the public command/routing portions of `2026-06-27_global_agent_workflow_os.md`. It does not rewrite that shipped historical record.

## Why

The global workflow surface drifted into overlapping commands, aliases, presets, and bypasses (`/fw`, `/fw close`, `/fusion`, `/audit`, `cheap`, `--preset`, `--skip-cdp`). The prompt contract, global routing rules, deployed copies, and Python runners no longer describe one system. That makes it possible to select the wrong model basket, omit CDP lanes, or stop before implementation review.

The operator requires one unambiguous lifecycle with exactly two public full-workflow commands:

- `/fwf`: free OpenRouter basket plus the subscribed CDP/frontier lanes.
- `/fwp`: paid OpenRouter basket plus the same subscribed CDP/frontier lanes.

## Frozen product contract

### Public command surface

Only `/fwf <plan>` and `/fwp <plan>` are public full-workflow commands. Remove the old deployed workflow commands `/fw`, `/fusion`, and `/audit`. Component skills such as `plan-ceo-review`, `plan-eng-review`, and `review` remain callable skills, but they are stages inside `/fwf` and `/fwp` when the full workflow is selected.

There is no public `cheap`, `close`, `paid`, `preset`, `only-lane`, or `skip-cdp` workflow variant.

### Risk routing

| Grade | Fixed lifecycle |
|---|---|
| R1 | `plan-ceo-review` with agent-resolved questions -> audit topology -> `plan-eng-review` with agent-resolved questions -> implementation -> `review` |
| R2 | `plan-ceo-review` with agent-resolved questions -> matrix topology -> `plan-eng-review` with agent-resolved questions -> standing implementation GO -> implementation -> `review` |
| R3 | `plan-ceo-review` with questions answered by the operator -> matrix topology -> `plan-eng-review` with agent-resolved questions -> standing implementation GO -> implementation -> `review` |

The R2/R3 standing GO remains an embedded safety gate required by the global risk contract; it is not a third command or a separate closeout workflow. A GO remains valid through in-scope fixes, exact-head review, CI, merge, and checkout sync. Real-money, Combine, broker-submit/arming, destructive actions, and scope expansion still require their separate just-in-time authorization.

### Free versus paid

The topology and lifecycle are identical between `/fwf` and `/fwp`. Only the OpenRouter basket changes:

- `free`: OpenRouter free roster.
- `paid`: the configured paid complement basket.

Both modes retain Perplexity CDP, Gemini CDP, and the synthesizer-aware frontier lane: GPT CDP when Claude synthesizes, Claude CLI when GPT/Codex synthesizes. FWP replaces the free OpenRouter basket; it does not add paid models on top of free models.

### Fixed engine surfaces

- R1 calls `auditf.py --mode free|paid`.
- R2/R3 call `fuse.py --mode free|paid`.
- `auditf.py` and `fuse.py` expose no workflow preset, `cheap`, `skip-cdp`, or single-lane bypass.
- Low-level timeouts, output paths, repository context, and synthesizer identity remain legitimate operational flags.
- Missing/unavailable lanes remain visible in artifacts; the command must not silently claim a complete panel.

## CEO review

**Verdict:** GO, HOLD SCOPE.

The smallest coherent solution is a single contract spanning canonical prompts, engines, generated global rules, deployment, pruning, and tests. A docs-only rename would preserve runtime drift; compatibility aliases would recreate the ambiguity being removed. No third workflow or compatibility period is approved.

All R1/R2 CEO questions and R3 non-product mechanics are resolved automatically by the agent. R3 CEO product/risk questions are presented to the operator and block until answered.

## Engineering review

### Ownership

1. `D:/APPS/_shared`
   - Owns `auditf.py` audit topology and `fuse.py` matrix topology.
   - Owns free/paid model roster selection and engine contract tests.
2. `D:/dotclaude/claude-config`
   - Owns canonical `fwf.md` and `fwp.md` commands.
   - Owns deployment to Claude and Codex homes and pruning of stale workflow commands.
3. `D:/dotclaude/dotclaude-ecosystem`
   - Owns risk routing, master-agent policy, operator documentation, generated agent rules, and routing tests.

### Dependency order

1. Make engine mode contracts executable and tested.
2. Make canonical commands call only those contracts; deploy/prune deterministically.
3. Update global routing and generated rules to name only `/fwf` and `/fwp`.
4. Run focused tests, deployed-copy parity checks, and an exact-diff review.
5. Land each repository through its normal draft-PR lifecycle, then sync operator checkouts.

### Failure modes and controls

| Failure | Control |
|---|---|
| Paid models leak into FWF | exact panel tests reject paid lane names in `--mode free` |
| Free models leak into FWP | exact panel tests reject OR-free lane names in `--mode paid` |
| CDPs/frontier disappear | both-mode tests assert their expected lane identities |
| Stale `/fw`, `/fusion`, or `/audit` remains installed | sync `--check` fails on stale files; `--write` prunes only the enumerated workflow filenames |
| Prompt and engine drift | command contract tests assert exact runner/mode/risk routing strings |
| R3 questions auto-decided | command tests require operator-answer language for R3 CEO stage |
| Implementation ships without review | both command contracts end in `review` and fix-first review handling |
| Dirty runtime checkout is overwritten | `_shared` implementation uses a clean worktree from `origin/master` |

## Implementation slices

### S1 — engine contracts (`D:/APPS/_shared`)

- Add `--mode free|paid` to `auditf.py`; free selects the free aggregator and paid selects the paid OpenRouter basket while preserving CDPs/frontier.
- Replace `fuse.py` public presets with `--mode free|paid`; both use matrix tournament topology.
- Remove public `--skip-cdp`, `--only-lane`, `cheap`, `matrixP`, and raw preset routing.
- Update runner documentation and tests.

### S2 — commands and deployment (`claude-config`)

- Replace `commands/fw.md` with `commands/fwf.md` and `commands/fwp.md`.
- Encode the risk table, question ownership, standing R2/R3 GO, implementation, review, and landing lifecycle.
- Generalize `sync_to_home.py` to deploy both commands to Claude/Codex.
- Prune only the known stale workflow files: `fw.md`, `fusion.md`, and `audit.md` in both homes.
- Update contract and sync tests.

### S3 — global routing (`dotclaude-ecosystem`)

- Update `skills/master-agent/SKILL.md`, shared core/overlays, executor references, and operator documentation.
- Remove `/fw close`, direct top-level audit routing, FWF-optional R1, and workflow selection via Ponytail.
- Regenerate managed rules with `sync_agent_rules.py --write` and verify `--check`.
- Update focused tests to assert the new two-command surface.

## Validation / Definition of Done

- Engine dry-run tests prove exact free/paid roster partition and invariant CDP/frontier lanes.
- Engine parsers reject `--preset`, `cheap`, `--skip-cdp`, and `--only-lane`.
- Canonical command tests prove all three risk routes and question-ownership rules.
- Sync tests prove two deployed files and deterministic pruning of the three stale workflow files.
- Global routing sources contain no active `/fw close`, `/fusion`, `/audit`, `cheap`, or skip-based workflow instruction.
- `sync_agent_rules.py --check` passes after generation.
- Deployed Claude and Codex command files hash-match canonical sources; old workflow files are absent.
- Real diff receives the `review` skill pass; ship-blocking findings are fixed before merge.
- All three branches are committed/pushed, PR-reviewed/merged, and their operator checkouts fast-forwarded.

## Rollback

Revert in reverse dependency order: global routing, commands/deployment, engines. Re-run command sync and agent-rule generation after the reverts. The rollback restores the previous files from Git; it never touches trading runtime, broker state, or `_shared` runtime locks.

## Explicit non-goals

- No trading strategy, broker, CCTV, Pure Signal, or order-path change.
- No new model-provider integration or model-quality decision.
- No GUI work.
- No compatibility aliases, soak/shadow phase, or third workflow command.

## Implementation evidence

**Start heads**

- `apps-shared`: `b060a5e`
- `claude-config`: `593bdd9` (the branch intentionally includes the existing local command-runtime fix that the replacement command set supersedes)
- `dotclaude-ecosystem`: `f37d5cf`

**Landed heads**

- `apps-shared`: `1d855a40892aec987c02f34a5736616104762fcf` — PR #17.
- `claude-config`: `fea0842c84374557d54df4156123f15a834d935c` — PR #6.
- `dotclaude-ecosystem`: `c9ef8c514eb23fdc045d03ab51c25889411eeece` — PR #36.

**Validation**

- `apps-shared`: `python -m pytest -q audit` -> `36 passed` (exit 0).
- `claude-config`: `python -m pytest -q` -> `24 passed` (exit 0).
- `dotclaude-ecosystem`: `python -m pytest -q scripts/tests` -> `102 passed, 2 subtests passed` (exit 0).
- `sync_agent_rules.py --check` -> all four global targets clean.
- Command sync readback -> `fwf.md` and `fwp.md` clean in Claude and Codex homes; six stale workflow files removed.
- Runtime parser readback from `D:/APPS/_shared` exposes only required `--mode {free,paid}` model selection and no preset/lane-bypass flags.
- Operator checkouts are current. The dirty `_shared` checkout retained its pre-existing Python fallback, watchdog, runtime locks, and untracked data.
- Final plan lifecycle updater returned exit 0 and regenerated `VISIONS.md`; its `PLANS.md` catalog subprocess timed out after 120 seconds and is recorded as a best-effort catalog failure.

Pytest emitted a Windows `pytest-current` atexit cleanup `PermissionError` after the two successful Python suites; the pytest processes returned exit code 0 and all expected tests ran.

**Implementation review**

- Reviewed the real diffs in all three repositories.
- Fixed synthesizer-specific wording in the R1 synthesis artifact.
- Removed the orphaned close-workflow reference from master-agent.
- Added exact OpenRouter model-ID assertions, not only basket-size assertions.
- No remaining ship-blocking finding after the corrected test heads.
