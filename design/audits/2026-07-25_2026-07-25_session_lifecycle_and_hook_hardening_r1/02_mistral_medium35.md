# Audit — Mistral Medium 3.5

Model: `mistralai/mistral-medium-3-5`  
Tokens: 12,932  
Latency: 54.4s

---

Here’s the audit of the **Session Lifecycle Router, Curator, and Hook Hardening** plan against the specified criteria:

---

---

### **1. Architectural Soundness**
#### **Findings:**
- **P1 (Blocker): Missing ownership for `session_state.py`**
  - **## Architecture > Data flow** and **## Phase 0 > Reuse map** imply `session_state.py` (added in CEO Review) owns scratch file I/O, but its contract (e.g., atomicity guarantees, validation rules) is not explicitly documented in the plan.
  - **Impact:** Without clear ownership, future hooks might reimplement or misuse the scratch file, violating **Invariant 1** ("scratch, not truth").
  - **Location:** Missing in **## Architecture** and **## Implementation slices > S1-S3**.

- **P2 (Important): Unclear boundary between `/curator` and TruthDeck**
  - **## Frozen product contract > Invariants 1-4** state `/curator` must delegate to `truthctl` and never reimplement gates, but **## Phase 0 > Collision verdict** only resolves this for *gate evaluation*.
  - **Gap:** No explicit contract for how `/curator` handles `truthctl` failures (e.g., timeouts, missing binaries). The **Error and rescue map** covers `FileNotFoundError` but not `subprocess.TimeoutExpired` for `truthctl` calls.
  - **Location:** **## S4 - `/curator`** and **## Error and rescue map**.

- **P3 (Nice-to-have): Redundant registry in `session_registry.py`**
  - **## S1 - Repo registry** introduces a new registry, but **## Reuse map** shows `plan_context_loader.py` already loads plans/visions. The plan doesn’t justify why a separate registry is needed vs. extending `plan_context_loader.py`.
  - **Impact:** Duplicates logic, but not a correctness issue.

---

### **2. Threading/Async Safety**
#### **Findings:**
- **P1 (Blocker): Race condition in `state_reaper.py`**
  - **## S3 - PreCompact and SessionEnd** and **CEO Review > Finding 2.1** describe the reaper excluding live sessions, but the mechanism for detecting "live sessions" is underspecified.
  - **Risk:** If two sessions’ `SessionEnd` hooks run concurrently, the reaper in one could delete the scratch file of the other mid-write.
  - **Location:** **## S3 > state_reaper.py** and **## Error and rescue map > reaper vs live session**.

- **P2 (Important): No lock for scratch file writes**
  - **## Architecture** shows multiple hooks (`PostToolBatch`, `PreCompact`, `SessionEnd`) writing to `session_plan_<id>.json`, but there’s no mention of file locking or atomic writes.
  - **Risk:** Concurrent writes (e.g., drift check updating goal while `PreCompact` re-injects) could corrupt the file.
  - **Partial mitigation:** CEO Review resolves this via `session_state.py` with atomic writes, but the plan doesn’t explicitly state this is thread-safe across *processes* (hooks run in separate Python processes).
  - **Location:** **## Architecture** and **## S1-S3**.

- **P1 (Blocker): Blocking I/O in `SessionStart`**
  - **## Token budget** sets a 400ms p95 target for `SessionStart`, but **## S1 - Repo registry** implies synchronous git calls (`git status`, `git log`) to populate the registry.
  - **Risk:** Git operations can block for seconds on large repos (e.g., monorepos), violating the budget.
  - **Location:** **## S1 > session_router.py** and **## Token budget**.

---

### **3. Edge Cases**
#### **Findings:**
- **P1 (Blocker): Stale scratch file on `SessionStart` resume**
  - **CEO Review > Finding 4.1** resolves the clobber case, but the plan doesn’t address:
    - What if the scratch file’s `schema_version` is unrecognized during resume?
    - What if the file’s `repo` field mismatches the current directory (e.g., session moved worktrees)?
  - **Impact:** Could re-inject a goal for the wrong repo.
  - **Location:** **## S1 > SessionStart router** and **## Frozen product contract > Invariant 1**.

- **P2 (Important): `/curator` claim extraction edge cases**
  - **## S4 - `/curator`** specifies extracting claims from the transcript, but:
    - No handling for claims spanning multiple turns (e.g., "I fixed X... [compaction] ...and verified Y").
    - No handling for claims in non-English languages or code fences.
  - **Impact:** `UNVERIFIED` is safe, but false `REFUTED` could erode trust.
  - **Location:** **## S4 > Claim extraction**.

- **P2 (Important): `SessionEnd` verdict gaps**
  - **## S3 > SessionEnd** defines three verdicts (`ARCHIVE-OK`, `HANDOFF`, `CHECKPOINT`), but:
    - No verdict for "session crashed mid-turn" (e.g., model error).
    - No verdict for "repo in detached HEAD state."
  - **Impact:** Defaults to `UNKNOWN` (per **Error and rescue map**), but this isn’t documented in the verdict enum.
  - **Location:** **## S3 > SessionEnd** and **## Test plan**.

- **P3 (Nice-to-have): `/sweep` false positives**
  - **## S5 - `/sweep`** scans for abandoned work, but:
    - No handling for `TODO` comments in generated files (e.g., `node_modules/`).
    - No handling for `IDEA_BOX.md` entries already resolved but not yet pruned.
  - **Impact:** Noise in findings, but not correctness-critical.

---

### **4. Cost/Performance**
#### **Findings:**
- **P1 (Blocker): Unbounded git calls in `/sweep`**
  - **## S5 - `/sweep`** scans the entire repo for `TODO`/`FIXME`, but:
    - No exclusion list (e.g., `node_modules/`, `.git/`).
    - No depth limit for git history checks (e.g., `git log` for scaffolding age).
  - **Risk:** Could take minutes on large repos, violating the implicit "advisory only" non-blocking rule.
  - **Location:** **## S5 > sweep_scan.py**.

- **P2 (Important): `SessionStart` registry lookup overhead**
  - **## S1 > Repo registry** implies loading all plans/visions for the repo at startup.
  - **Risk:** For repos with hundreds of plans (e.g., `dotclaude-ecosystem`), this could exceed the 400ms p95 budget.
  - **Mitigation:** The plan doesn’t specify caching or lazy loading.
  - **Location:** **## S1 > session_router.py** and **## Token budget**.

- **P2 (Important): Duplicate work in drift check**
  - **## S2 - Drift check** fires on `PostToolBatch`, but:
    - No memoization of repository state (e.g., `git status` results) between checks.
    - **Risk:** Repeated git calls on every batch, even if nothing changed.
  - **Location:** **## S2 > session_drift.py**.

- **P3 (Nice-to-have): Memory leaks in long-running sessions**
  - **## Architecture** doesn’t address memory usage of hooks (e.g., `session_router.py` loading large plan files).
  - **Risk:** Python processes may grow unbounded over hours-long sessions.
  - **Mitigation:** Hooks are short-lived, but not explicitly stated.

---

### **5. Integration Risks**
#### **Findings:**
- **P1 (Blocker): Contract mismatch with `truthctl`**
  - **## S4 - `/curator`** assumes `truthctl snapshot --require` is stable, but:
    - No version pinning for `truthctl` (e.g., `truthctl v1.2.3`).
    - No handling for `truthctl` schema changes (e.g., new gate fields).
  - **Impact:** `/curator` could break if TruthDeck updates its snapshot format.
  - **Location:** **## S4 > curator_claims.py** and **## Reuse map**.

- **P2 (Important): Stale `IDEA_BOX.md` in `/sweep`**
  - **## S5 - `/sweep`** appends findings to `IDEA_BOX.md`, but:
    - No check if the file was modified by another process (e.g., `plan_context_updater`) since the scan started.
    - **Risk:** Race condition could overwrite concurrent updates.
  - **Location:** **## S5 > sweep_scan.py**.

- **P2 (Important): Hook order dependencies**
  - **## Architecture** shows `SessionStart` must run before `PreCompact` (to create the scratch file), but:
    - No explicit ordering guarantee in `settings.json` (hooks run in undefined order).
    - **Risk:** `PreCompact` could fire before `SessionStart`, causing a no-op re-injection.
  - **Mitigation:** The plan doesn’t specify how to enforce order.
  - **Location:** **## Architecture** and **## S7 - Exact-head review**.

- **P3 (Nice-to-have): `autoplan` persona conflicts**
  - **## S6 - Adversarial personas** adds new personas, but:
    - No handling for conflicts between personas (e.g., `bad-actor` and `auditor-post-hoc` disagreeing on a plan change).
  - **Impact:** Non-deterministic plan text changes.

---

### **6. Underspecified Areas**
#### **Findings:**
- **P1 (Blocker): Scratch file schema**
  - **CEO Review > Finding 1.1** adds `"schema_version": "session.plan.v1"`, but the full schema (required fields, types, bounds) is not documented.
  - **Impact:** Hooks may assume fields exist (e.g., `checkpoints[]`) without validation.
  - **Location:** Missing in **## Architecture** and **## Frozen product contract**.

- **P1 (Blocker): Retention window for `state_reaper.py`**
  - **## S3 > state_reaper.py** and **CEO Review > Finding 2.1** describe retention but don’t specify:
    - Default retention period (e.g., 7 days? 30 days?).
    - Configurability (e.g., via env var or `settings.json`).
  - **Impact:** Undefined behavior for operators.
  - **Location:** **## S3** and **## Rollback and emergency off**.

- **P2 (Important): Throttling parameters for drift check**
  - **## S2 - Drift check** mentions throttling by "batch count and elapsed context" but doesn’t specify:
    - The exact throttling algorithm (e.g., "once per 5 batches or 10 minutes").
    - How "elapsed context" is measured (tokens? time?).
  - **Impact:** Hard to test or tune.
  - **Location:** **## S2 > session_drift.py**.

- **P2 (Important): `/curator` transcript window size**
  - **## S4 - `/curator`** says it reads a "bounded window" of the transcript but doesn’t specify:
    - The window size (e.g., last N turns? last M tokens?).
    - How bounds are enforced (e.g., truncation, error if exceeded).
  - **Impact:** Could violate memory/token budgets.
  - **Location:** **## S4 > curator_claims.py**.

- **P3 (Nice-to-have): Hook error log rotation**
  - **CEO Review > Finding 8.1** adds `hook_errors.log`, but:
    - No retention policy (e.g., max size, max age).
    - No rotation mechanism.
  - **Impact:** Log could grow unbounded.

---

---

### **TOP 3 CHANGES**
1. **P1: Fix race conditions in `state_reaper.py` and scratch file writes**
   - Add explicit cross-process locking (e.g., `fcntl`/`msvcrt` file locks) for scratch file writes in `session_state.py`.
   - Ensure `state_reaper.py` uses the same lock to detect live sessions, and document the retention window (e.g., 30 days).

2. **P1: Document the scratch file schema and validation rules**
   - Add a **## Scratch File Schema** section with:
     - Full JSON schema (required/optional fields, types, bounds).
     - Validation rules (e.g., `schema_version` must match, `repo` must be a valid git path).
     - Behavior for malformed/unrecognized files (treat as absent, log error).

3. **P1: Bound all external calls (git, `truthctl`) with timeouts and budgets**
   - Add explicit timeouts (e.g., 500ms for git calls, 1s for `truthctl`) in `session_router.py` and `curator_claims.py`.
   - Document these in **## Token budget** and **## Performance**.
   - Add a `subprocess.TimeoutExpired` row to the **Error and rescue map** for `truthctl`.