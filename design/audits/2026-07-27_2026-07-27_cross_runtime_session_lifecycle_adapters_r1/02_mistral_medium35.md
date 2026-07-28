# Audit — Mistral Medium 3.5

Model: `mistralai/mistral-medium-3-5`  
Tokens: 7,796  
Latency: 36.5s

---

Here’s the audit of the **Cross-Runtime Session Lifecycle Adapters — Codex First** plan, graded against the specified criteria:

---

---

### **1. Architectural Soundness**
**Findings:**
- **P1 (Blocker)** — **## Architecture > Diagram**: The architecture diagram shows `codex_session_adapter.py` delegating to `session_router.py`/`session_lifecycle.py`, but **ownership of the adapter’s failure modes is unclear**. The plan states the adapter "fails open" but does not explicitly assign responsibility for logging/telemetry of failures (e.g., `CODEX_ADAPTER_*` reason codes). **Who owns the bounded error logging?** The adapter or the router/lifecycle?
  - *Cite*: "Fail open and log bounded reason codes without transcript contents" (## C1) vs. "router/lifecycle delegate | expected validation failure" (## Error and rescue registry).
  - *Risk*: If the adapter logs but the router also logs, this could lead to duplicate or conflicting error handling.

- **P2 (Important)** — **## Frozen boundaries**: The plan explicitly prohibits "transcript globbing or fallback to another session," but **does not specify how the adapter handles concurrent sessions** (e.g., two Codex sessions starting simultaneously). The existing Claude lifecycle engine may assume sequential events, and the adapter’s behavior here is underspecified.
  - *Cite*: No mention of concurrency in ## C1 or ## Architecture.

- **P3 (Nice-to-have)** — **## Repository registry scope**: The list of candidate Git roots is hardcoded (e.g., `D:/APPS/TSU`). This is brittle for future machines/environments. Consider making this configurable or dynamically discovered.

---

### **2. Threading/Async Safety**
**Findings:**
- **P1 (Blocker)** — **## C1 > Thin Codex event adapter**: The adapter reads from `stdin` and delegates to `session_router.py`/`session_lifecycle.py`. **No mention of thread safety or lock inversion risks** if the router/lifecycle is not thread-safe.
  - *Cite*: The existing Claude lifecycle engine (predecessor plan) may not be designed for concurrent calls. The adapter must either:
    - Guarantee sequential invocation (e.g., via Codex’s hook contract), or
    - Add locking around shared state (e.g., `session.plan.v1` writes).
  - *Risk*: Race conditions if two Codex sessions trigger `SessionStart`/`SessionEnd` simultaneously.

- **P2 (Important)** — **## C2 > Dual-format transcript projection**: The projection logic for Codex transcripts (e.g., `response_item.payload.type=message`) **may block on I/O** if parsing large JSONL files. The plan does not specify:
  - Whether parsing is streamed or buffered.
  - Timeouts for malformed/unusually large transcripts.
  - *Cite*: "Oversized sources... degrade to incomplete/unverified evidence" (## Failure map) but no performance guardrails.

- **P3 (Nice-to-have)** — **## C3 > Global hook template**: The activation script’s backup/restore logic (e.g., atomic file operations) is not specified. **Potential for partial writes or corruption** if interrupted (e.g., power loss).

---

### **3. Edge Cases**
**Findings:**
- **P1 (Blocker)** — **## Failure map > "Repo is unregistered"**: The plan states unregistered repos receive "minimal advisory context," but **does not define what "minimal" entails**. Could this leak sensitive data (e.g., `cwd`) or violate the fail-closed posture?
  - *Cite*: "Unregistered repositories receive a short advisory/minimal context" (## Definition of done) is vague.
  - *Risk*: Inconsistent behavior if "minimal context" is not strictly bounded.

- **P1 (Blocker)** — **## C2 > Function call/result pairing**: The plan requires "exact `call_id`" matching, but **does not handle `call_id` collisions** (e.g., reused IDs across sessions or malformed IDs). The failure mode ("no command evidence") is correct, but the edge case of duplicate IDs in a single transcript is untested.
  - *Cite*: "Codex function calls/results pair only by exact `call_id`" (## C2).

- **P2 (Important)** — **## C1 > `transcript_path: null`**: The adapter treats this as a no-op, but **what if `transcript_path` is a non-null but invalid path (e.g., `/dev/null` or a symlink to a non-existent file)?** The plan only covers `null` explicitly.
  - *Cite*: "Treat a null/empty `transcript_path` as an intentional no-op" (## C1).

- **P3 (Nice-to-have)** — **## Live acceptance**: The plan does not test **interrupted sessions** (e.g., Codex crash mid-session). The adapter should handle `SessionEnd` without a prior `SessionStart`.

---

### **4. Cost/Performance**
**Findings:**
- **P2 (Important)** — **## C2 > Transcript projection**: The plan does not specify **memory limits** for parsing Codex transcripts. Large sessions could exhaust memory if the entire JSONL is loaded at once.
  - *Cite*: "Existing transcript byte limits remain the performance boundary" (## Performance) but no explicit limits for Codex.
  - *Risk*: Memory bloat if Codex transcripts are significantly larger than Claude’s.

- **P2 (Important)** — **## C1 > Adapter overhead**: The adapter adds a **new process per hook event** (Codex spawns a Python script per `SessionStart`/`SessionEnd`). At scale (e.g., 100s of sessions), this could introduce latency.
  - *Mitigation*: The plan notes "hook timeout" enforcement, but does not specify the timeout value or how it’s configured.

- **P3 (Nice-to-have)** — **## C3 > Activation script**: The registry template expansion (step 4) could be slow if scanning many repos. **No performance constraints** are defined.

---
---
### **5. Integration Risks**
**Findings:**
- **P1 (Blocker)** — **## Verified current state > Transcript readers**: The plan acknowledges that **Codex transcripts use `type=response_item` vs. Claude’s `type=assistant`**, but **does not verify backward compatibility** with existing Curator claims.
  - *Cite*: "Existing transcript readers only recognize Claude records... this is the only proven parser gap."
  - *Risk*: If Curator expects `type=assistant` and the projection misses edge cases, claims could be silently unverified.

- **P2 (Important)** — **## Architecture > `.claude/state`**: The plan reuses `.claude/state` for Codex, but **does not confirm that Codex respects this directory’s permissions/ownership**. If Codex runs as a different user, file access could fail.
  - *Cite*: "The `.claude/state` name is retained as the existing cross-host lifecycle store."

- **P3 (Nice-to-have)** — **## C3 > Hook template**: The template uses **absolute Windows commands**, but the plan does not test **non-Windows paths** (e.g., macOS/Linux). This could break cross-platform activation.

---
---
### **6. Underspecified Areas**
**Findings:**
- **P1 (Blocker)** — **## C1 > Adapter input validation**: The adapter "allows only `SessionStart` and `SessionEnd`," but **does not define how it rejects other events**. Does it:
  - Exit silently?
  - Log a warning?
  - Return a non-zero exit code?
  - *Cite*: "Treat a null/empty `transcript_path` as an intentional no-op" implies other events may not be no-ops.

- **P1 (Blocker)** — **## C2 > Projection for mixed-format files**: The plan states that **mixed Claude/Codex records degrade to incomplete/unverified**, but **does not specify how the projection handles a file with both formats**. Does it:
  - Skip non-Codex records?
  - Fail the entire file?
  - *Cite*: "Malformed arguments, unmatched results, oversized sources, and mixed-format files degrade to incomplete/unverified evidence."

- **P2 (Important)** — **## C3 > Registry template expansion**: The plan does not specify **how the registry template is "verified"** (step 4). Is this a manual step, or does the activation script validate repo existence/Git roots?

- **P2 (Important)** — **## Live acceptance > "normal trusted new Codex session"**: The plan does not define **what "normal hook trust" entails**. Is this a Codex-specific trust mechanism, or does it rely on filesystem permissions?

---
---
---
### **TOP 3 CHANGES**
1. **P1 (Architectural/Threading)** — Clarify ownership of error logging and concurrency guarantees in the adapter. Explicitly state whether the adapter is single-threaded (sequential hooks) or requires locks around shared state (e.g., `session.plan.v1` writes). *Cite: ## C1, ## Architecture*.
2. **P1 (Edge Cases/Integration)** — Define "minimal advisory context" for unregistered repos and add explicit tests for `transcript_path` edge cases (invalid paths, symlinks, etc.). *Cite: ## Failure map, ## C1*.
3. **P1 (Integration Risks)** — Add a backward-compatibility test for Curator claims with Codex-projected transcripts to ensure no silent failures. *Cite: ## Verified current state, ## C2*.