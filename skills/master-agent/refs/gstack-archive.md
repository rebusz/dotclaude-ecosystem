# gstack ops modes — ARCHIVE (load on demand only)

Retired from the main master-agent surface 2026-07-03 (skill/command consolidation;
see TSU `design/audits/2026-07-03_skill_command_surface_audit.md` §3). They still
work when the operator asks for one by name — follow the protocol below. Preferred
replacements: REVIEW → `/code-review`, CSO → `/security-review`,
INVESTIGATE → `mode debug deep`, plan pipelines → `/fw`.

### SHIP — merge+push+PR workflow
1. Pre-flight: platform, base branch, git status. 2. Run tests (fail → stop).
3. Flag if `/code-review` wasn't run (don't block). 4. Version bump MICRO/PATCH
(auto unless ambiguous). 5. Changelog from git diff since last tag. 6. Commit +
push (conventional message). 7. PR with summary + test links.
Stops only for: merge conflicts, test failures, ambiguous bump. `>> SHIPPED`

### QA — test flows, find+fix loop
Tiers: Quick (P1/P2) | Standard (+P3, default) | Exhaustive (+cosmetic).
Test plan from README/routes → execute (browser/manual, screenshots, assertions) →
per bug: reproduce, fix, re-verify, atomic commit → health score before/after →
READY / BLOCKED. `>> QA COMPLETE`

### CSO — security audit
Modes: daily (confidence ≥8/10, zero-noise) | comprehensive (≥2/10).
Secrets archaeology (git history, .env, logs) → dependency CVEs/supply chain →
CI/CD security → OWASP Top 10 → STRIDE → active verification (PoC for
high-confidence findings). `>> CSO COMPLETE`

### OFFICE-HOURS — product interrogation
Postures: Startup (default) | Builder. Six forcing questions: demand reality
(behavior, not interest), status quo (the real competitor), desperate specificity
(name ONE person; their Tuesday), narrowest wedge someone would pay for,
observation surprises, future-fit in 3 years. Anti-sycophancy: push on vague
answers; challenge social proof with demand tests. Output: design doc + next
action. `>> OFFICE-HOURS COMPLETE`

### AUTOPLAN — full review pipeline
CEO → architecture → design → DX review with 6 principles (completeness, boil the
lake, pragmatic, DRY, explicit over clever, bias to action). Decision classes:
mechanical → auto-decide silently; taste → auto-decide + surface; user challenge
(irreversible / against stated direction) → NEVER auto-decide.
Superseded in practice by `/fw`. `>> AUTOPLAN COMPLETE`

### RETRO — weekly retrospective (default 7 days)
git log metrics (commits, LOC delta, test/LOC ratio, active days) → hotspots
(most-changed files) → session clustering → went well / didn't / actions → trend
vs previous retro. `>> RETRO COMPLETE`

### CAREFUL — destructive-command guard (session-long)
Warn + confirm before: `rm -rf`, `DROP TABLE/DATABASE`, `TRUNCATE`,
`git push --force`, `git reset --hard`, `git checkout .`, `kubectl delete`,
`docker system prune`, `docker rm -f`. Safe exceptions: node_modules/, dist/,
.cache/, __pycache__/, build/.

### LEARN — project learnings (JSONL per project)
`show` (20 recent by type) | `search <q>` | `prune` (stale/contradictions) |
`export` (markdown for CLAUDE.md) | `stats`. Types: pattern, pitfall, preference,
architecture, operational, tool. `>> LEARN COMPLETE`
