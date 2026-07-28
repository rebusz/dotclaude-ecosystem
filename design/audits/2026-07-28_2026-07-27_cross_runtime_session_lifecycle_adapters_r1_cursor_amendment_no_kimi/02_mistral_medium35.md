# Audit — Mistral Medium 3.5

Model: `mistralai/mistral-medium-3-5`  
Tokens: 17,442  
Latency: 44.5s

---

Here’s the audit of the **Cross-Runtime Session Lifecycle Adapters** plan, structured by your criteria. Findings are specific, graded, and actionable.

---

---

### **1. Architectural Soundness**
#### **Findings:**
- **P1 (Blocker) — ## Cursor adapter boundary and delivery slices > Missing ownership for `preCompact` event handling**
  - The plan states `preCompact` should delegate to "the existing checkpoint/start-context recovery seam," but **no owner is explicitly named** for this seam. The `session_router.py` and `session_lifecycle.py` are cited for start/end, but `preCompact` is a Cursor-specific event not covered in the existing Claude/Codex contracts.
  - **Risk**: Unclear ownership could lead to `preCompact` being silently ignored or improperly handled, breaking Cursor’s compaction flow.
  - **Fix**: Explicitly assign `preCompact` to a module (e.g., `session_router.py` with a new method) and document its contract.

- **P2 (Important) — ## Architecture > Implicit dependency on `session_router.py`/`session_lifecycle.py` stability**
  - The adapter delegates directly to these modules, but **no version compatibility guarantees** are enforced between the adapter and the router/lifecycle. If the router’s interface changes (e.g., `handle_event` signature), the adapter could break without detection.
  - **Risk**: Runtime failures in production due to contract drift.
  - **Fix**: Add a **contract test** in `CU0-L` that validates the router/lifecycle interface (e.g., via `inspect.signature`) before delegating.

- **P2 (Important) — ## Repository registry scope > Registry expansion is a side effect of Codex activation**
  - The plan notes that expanding the registry for Codex **also affects Claude sessions** in those repos (switching them from "unregistered minimal" to "full advisory"). This is a **behavioral change** but is buried in the registry scope section.
  - **Risk**: Unintended side effects for existing Claude users.
  - **Fix**: Call this out in the **Definition of Done** for Cursor (CU4) and add a **regression test** for Claude sessions in expanded-registry repos.

- **P3 (Nice-to-Have) — ## Architecture > Diagram omits `transcript_projection.py` in the Cursor flow**
  - The Cursor adapter diagram shows delegation to `session_router.py`/`session_lifecycle.py` but **omits the projection layer** for Cursor transcripts (CU2). This could mislead implementers into thinking transcripts are handled by the router.
  - **Fix**: Update the Cursor flow diagram to include `transcript_projection.py` as a conditional path (if CU2 is implemented).

---

### **2. Threading/Async Safety**
#### **Findings:**
- **P1 (Blocker) — ## C1 — Thin Codex event adapter > No mention of concurrent session handling**
  - The adapter reads from `stdin` and processes one JSON event, but **no locking or concurrency controls** are specified for cases where:
    - Multiple Codex sessions trigger `SessionStart`/`SessionEnd` simultaneously.
    - The same session ID is reused (e.g., `resume` after `startup`).
  - **Risk**: Race conditions in state writes (e.g., `session.binding.v1` corruption) or log interleaving.
  - **Fix**: Explicitly state that:
    - The adapter is **single-event, process-per-invocation** (Codex runs hooks synchronously, so no in-process concurrency).
    - The existing `session_lifecycle.py`/`session_router.py` **must handle concurrent writes** (e.g., via file locks or atomic writes). Verify this in the **Definition of Done** for C1.

- **P2 (Important) — ## C3 — Global hook template and activation > Atomic replacement of `~/.codex/hooks.json` and `~/.claude/session_registry.json`**
  - The installer uses `fsync` + atomic replacement, but **no cross-process locking** is mentioned for:
    - Codex writing to `hooks.json` during activation.
    - Concurrent lifecycle sessions writing to `session_registry.json`.
  - **Risk**: Partial writes or corruption if Codex/adapter and installer clash.
  - **Fix**: Add **file locking** (e.g., `fcntl.flock` on Unix, `msvcrt.locking` on Windows) for both targets during installer operations.

- **P2 (Important) — ## Failure map and rollback > No timeout for `SessionStart`/`SessionEnd` subprocesses**
  - The plan states Codex runs hooks synchronously with timeouts (2s/3s), but **the adapter itself has no internal timeout** for delegation to `session_router.py`/`session_lifecycle.py`.
  - **Risk**: A hung router/lifecycle could block the adapter indefinitely, exceeding Codex’s timeout and causing Codex to kill the process.
  - **Fix**: Add a **subprocess timeout** in the adapter (e.g., 1.5s for start, 2.5s for end) to ensure it fails fast and lets Codex handle the timeout.

- **P3 (Nice-to-Have) — ## CU1 — Thin Cursor adapter > No mention of IDE/CLI process isolation**
  - Cursor IDE and CLI are separate processes, but the plan doesn’t specify whether:
    - The adapter runs in the same process as the IDE/CLI (unlikely, since hooks are subprocesses).
    - Multiple Cursor instances (IDE + CLI) could trigger the same adapter concurrently.
  - **Fix**: Clarify that the adapter is **process-per-event** (like Codex) and that concurrent IDE/CLI sessions are handled by the existing router/lifecycle locks.

---

### **3. Edge Cases**
#### **Findings:**
- **P1 (Blocker) — ## Definition of done — Cursor slice > Missing handling for `preCompact` without a prior `sessionStart`**
  - The plan states `preCompact` "delegates to the existing checkpoint/start-context recovery seam," but **no behavior is defined** if `preCompact` fires without a prior `sessionStart` (e.g., Cursor resumes a session and compacts before the adapter sees a start).
  - **Risk**: Unbounded state or errors.
  - **Fix**: Explicitly define `preCompact` as a **no-op** if no valid binding exists for the `conversation_id`.

- **P1 (Blocker) — ## Failure map and rollback > No handling for `transcript_path` pointing to a non-existent file**
  - The plan covers `transcript_path: null` but **not cases where the path exists in the event but the file is missing/deleted**.
  - **Risk**: Adapter crashes or fails to write state.
  - **Fix**: Treat missing files as **degraded mode** (log bounded error, no state write) and add a test case.

- **P2 (Important) — ## Definition of done — Cursor slice > No explicit behavior for `workspace_roots` containing non-Git directories**
  - The registry scope section says non-Git directories are **not silently added**, but the Cursor adapter’s behavior is undefined if `workspace_roots` includes:
    - Non-Git paths.
    - Paths outside the registry.
    - Symlinks or junctions (Windows).
  - **Risk**: Inconsistent registration or failed lookups.
  - **Fix**: Explicitly state that the adapter **filters `workspace_roots` to only registered Git repos** and logs a bounded warning for others.

- **P2 (Important) — ## CU4 — Exact live acceptance > No test for `SessionEnd` without a prior `SessionStart`**
  - The live acceptance matrix includes "abrupt CLI termination" but **not a `SessionEnd` for a session the adapter never saw start**.
  - **Risk**: Missing coverage for a real-world edge case (e.g., Cursor crashes and restarts, then ends a session).
  - **Fix**: Add a test case where `SessionEnd` is received for an unknown `conversation_id` (should be a no-op with bounded log).

- **P3 (Nice-to-Have) — ## C2 — Dual-format transcript projection > No handling for `call_id` collisions between Claude and Codex formats**
  - The projection allows mixed-format files, but **no behavior is defined** if a Claude `tool_use` and a Codex `function_call` share the same `call_id`.
  - **Risk**: Incorrect pairing or double-counting of tool calls.
  - **Fix**: Explicitly state that **duplicate `call_id`s across formats are treated as a single call** (or ignored, with a bounded log).

---

### **4. Cost/Performance**
#### **Findings:**
- **P1 (Blocker) — ## C1 — Thin Codex event adapter > No performance budget for adapter overhead**
  - The plan measures p95 for start/end (565ms/777ms) but **doesn’t allocate a budget for the adapter itself**. The adapter’s overhead (JSON parsing, validation, delegation) could push the total over Codex’s 2s/3s timeout.
  - **Risk**: Timeouts in production.
  - **Fix**: Set explicit **adapter-only budgets** (e.g., 100ms p95 for start, 150ms for end) and measure them in C1 tests.

- **P2 (Important) — ## CU3 — Idempotent user-level activation and rollback > No limit on registry size**
  - The installer expands the registry to include **all verified Git roots on the machine** (10+ in the example). For large ecosystems, this could:
    - Slow down `session_router.py` (if it scans the registry per event).
    - Increase memory usage for in-process caches.
  - **Risk**: Performance degradation at scale.
  - **Fix**: Add a **registry size limit** (e.g., 100 repos) and log a warning if exceeded. Alternatively, prove that registry lookups are O(1).

- **P2 (Important) — ## C2 — Dual-format transcript projection > No benchmark for mixed-format files**
  - The projection must handle mixed Claude/Codex records, but **no performance test** is defined for this case.
  - **Risk**: Mixed files could be significantly slower (e.g., due to per-record format detection).
  - **Fix**: Add a **performance test** for mixed-format files (e.g., 1000 records, 50/50 split) and ensure it stays under 500ms.

- **P3 (Nice-to-Have) — ## Performance review — 2 measured gates > No cold-start measurement for adapter**
  - The plan measures p50/p95 but **doesn’t specify cold vs. warm starts**. Cold starts (e.g., first session after boot) could be slower due to Python import overhead.
  - **Fix**: Add a **cold-start measurement** (e.g., after `reboot` or `python -c "import sys; sys.exit(0)"` to clear the import cache).

---

### **5. Integration Risks**
#### **Findings:**
- **P1 (Blocker) — ## Cursor adapter boundary and delivery slices > No contract for `conversation_id` stability across IDE/CLI**
  - The plan assumes `conversation_id` is stable, but **no evidence** is provided that the same ID is used for:
    - IDE sessions resumed in the CLI.
    - CLI sessions resumed in the IDE.
  - **Risk**: Duplicate bindings or failed lookups.
  - **Fix**: Add a **live test in CU4** where a session is started in the IDE and resumed in the CLI (or vice versa), and verify the `conversation_id` matches.

- **P2 (Important) — ## CU0-L — Native contract fixtures and executable probe > No validation of `workspace_roots` against registry**
  - The probe captures `workspace_roots` but **doesn’t check** if they match the registry’s canonical Git roots.
  - **Risk**: Mismatched paths could cause the adapter to fail in production.
  - **Fix**: Add a **validation step in CU0-L** to ensure `workspace_roots` are either:
    - Already in the registry.
    - Eligible for addition (exists, Git root, etc.).

- **P2 (Important) — ## C3 — Global hook template and activation > No handling for Codex CLI updates breaking the hook contract**
  - The installer **pins the Codex version** during preflight but **doesn’t handle** cases where:
    - Codex auto-updates and breaks the hook schema.
    - The user downgrades Codex.
  - **Risk**: Silent failures or adapter crashes.
  - **Fix**: Add a **version compatibility check** in the adapter (e.g., reject events with unknown fields or log a warning for unrecognized `cursor_version`).

- **P3 (Nice-to-Have) — ## Architecture > No contract for `session_router.py`/`session_lifecycle.py` errors**
  - The adapter delegates to these modules but **doesn’t define** how errors (e.g., `ValueError`, `OSError`) are propagated.
  - **Risk**: Unbounded error messages or crashes.
  - **Fix**: Explicitly state that the adapter **catches all exceptions from delegates**, logs a bounded error (with `CODEX_ADAPTER_DELEGATE_ERROR`), and exits 0.

---

### **6. Underspecified Areas**
#### **Findings:**
- **P1 (Blocker) — ## CU1 — Thin Cursor adapter > No definition of "degraded mode" for missed nonce**
  - The plan states: "Hook execution without delivered context is recorded as degraded, not parity." But **no details** are given on:
    - What "degraded" entails (e.g., no binding? partial context?).
    - How it’s surfaced to the operator.
  - **Risk**: Inconsistent behavior or silent failures.
  - **Fix**: Define degraded mode explicitly:
    - No `session.binding.v1` is created.
    - A bounded log entry is written (e.g., `CURSOR_ADAPTER_DEGRADED_NO_CONTEXT`).
    - The session continues without injected context.

- **P1 (Blocker) — ## CU2 — Cursor transcript projection, conditional > No criteria for "stable format"**
  - The slice is conditional on a "stable, explicit, readable native `transcript_path`," but **no stability criteria** are defined (e.g., schema version, field presence, or backward compatibility guarantees).
  - **Risk**: CU2 could be blocked indefinitely or implemented against an unstable contract.
  - **Fix**: Define stability as:
    - The `transcript_path` points to a **JSONL file** (not a database).
    - The schema includes `conversation_id`, `timestamp`, and `type` (e.g., `message`, `function_call`).
    - The format is **documented by Cursor** (not reverse-engineered).

- **P2 (Important) — ## CU3 — Idempotent user-level activation and rollback > No handling for partial writes during atomic replacement**
  - The installer uses atomic replacement, but **no details** are given on:
    - How partial writes are detected (e.g., file size checks? checksums?).
    - What happens if the atomic replace fails mid-write (e.g., disk full).
  - **Risk**: Corrupted hook/registry files.
  - **Fix**: Explicitly state:
    - The installer writes to a **temp file**, `fsync`s it, then renames it to the target.
    - If the rename fails, the **original file is restored from backup**.

- **P2 (Important) — ## Failure map and rollback > No handling for `SessionEnd` with a `transcript_path` that differs from `SessionStart`**
  - The plan covers `transcript_path: null` but **not cases where the path changes** between start and end (e.g., Cursor moves the transcript).
  - **Risk**: State inconsistency or failed close.
  - **Fix**: Explicitly state that the adapter **uses the `transcript_path` from `SessionStart`** for the binding, and logs a warning if `SessionEnd`’s path differs.

- **P3 (Nice-to-Have) — ## CU4 — Exact live acceptance > No criteria for "exact matching identity/workspace"**
  - The plan requires "exact matching identity/workspace" but **doesn’t define** what "exact" means (e.g., string equality? canonical path resolution?).
  - **Fix**: Define exact matching as:
    - `conversation_id` is identical (string equality).
    - `workspace_roots` are **canonicalized** (resolved symlinks, normalized separators, case-insensitive on Windows).

---

---

## **TOP 3 CHANGES**
1. **P1 (Blocker) — Define `preCompact` behavior and ownership**
   - **Action**: Explicitly assign `preCompact` to `session_router.py` with a no-op fallback if no binding exists. Add a test case for `preCompact` without prior `sessionStart`.
   - **Impact**: Prevents undefined behavior in Cursor’s compaction flow.

2. **P1 (Blocker) — Add concurrency and timeout guarantees for the adapter**
   - **Action**:
     - Clarify that the adapter is **process-per-event** (no in-process concurrency).
     - Add a **subprocess timeout** (1.5s/2.5s) for delegation to router/lifecycle.
     - Add **file locking** for installer operations on `hooks.json` and `session_registry.json`.
   - **Impact**: Prevents race conditions, hangs, and corruption.

3. **P1 (Blocker) — Define stability criteria for Cursor transcript format (CU2 gate)**
   - **Action**: Explicitly define "stable format" as a **documented JSONL schema** with required fields (`conversation_id`, `timestamp`, `type`). Defer CU2 until this is proven.
   - **Impact**: Prevents CU2 from being blocked or implemented against an unstable contract.