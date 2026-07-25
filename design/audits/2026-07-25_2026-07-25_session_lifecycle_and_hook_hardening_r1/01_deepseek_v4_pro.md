# Audit — DeepSeek V4 Pro

Model: `deepseek/deepseek-v4-pro`  
Tokens: 13,921  
Latency: 72.9s

---

## Audit Findings

### 1. Architectural Soundness (P1)
**Section:** Architecture diagram and S4 (`/curator`)

The plan repeatedly states “the handoff is always written” (Architecture, S4) but never specifies *where* or in *what format* the handoff is produced. The session scratch file (`session_plan_<id>.json`) includes a `claims[]` field, yet the curator’s claim verdicts (VERIFIED/REFUTED/UNVERIFIED) are described as output of the `/curator` skill only, without indicating whether they land in the scratch file, a separate handoff file, or inline in the session transcript. This is a missing artifact definition – without it, the curator’s primary deliverable cannot be built. **Grade: P1 (blocker).**

### 2. Threading/Async Safety (P2)
**Section:** Phase 0 (CEO Review findings), S3 reaper description

The CEO review resolved a critical liveness issue for the reaper: “age alone never authorises a delete” and the reaper must exclude live sessions. The plan now says it will exclude sessions whose `session_id` appears in “the harness’s live-session list **when that list is obtainable.**” No mechanism is specified for obtaining this list; in many Claude Code deployments, no such API exists. If the list is unobtainable, the reaper must fall back to mtime only, which can still delete a long‑running session that has not modified its scratch file recently. The specification is insufficient to guarantee live‑session safety in all environments. **Grade: P2 (important).**

### 3. Cost/Performance (P2)
**Section:** S4 `/curator`

The curator’s claim extraction (the new model step reading a bounded transcript window) is acknowledged as “cost paid once per session close,” but no token budget or window size is set. A long session could produce a very large transcript (thousands of lines), and an unbounded model call at session end risks surprising cost and latency. This contradicts the plan’s own principle of measurable budgets for all hooks; while it is not a hook, it is a permanent session‑close tax and must be constrained. **Grade: P2 (important).**

### 4. Integration Risks (P3)
**Section:** S1 Repo registry, non‑goal 5

The registry is a static file; new repositories that are not added receive minimal router treatment (one line). This is an explicit non‑goal, but the plan acknowledges that “autodetection was rejected in D7 as a worse trade.” The resulting gap means that a developer starting a new project will silently lose the full router benefits until they manually update the registry. This is a friction point that could be mitigated with a lightweight “last‑chance” heuristic (e.g., detect if there’s a `PLANS.md`) without violating D7. **Grade: P3 (nice‑to‑have).**

### 5. Underspecified Areas (P3)
**Section:** S3 `state_reaper.py`

The retention window for `turn_counter_*` and `session_plan_*` is not defined (only “older than a retention window”). Without a concrete value (or configuration mechanism), the reaper may be too aggressive or never clean up. The plan should specify a default (e.g., 7 days) and document how it can be changed. **Grade: P3 (nice‑to‑have).**

### 6. Edge Cases (P2)
**Section:** S3 PreCompact, CEO finding 1.3 (resolved)

The resolution makes the drift check the write path for updated goals, so PreCompact can re‑inject the latest version. However, the drift check itself fires only on `PostToolBatch`, which is throttled. If the model changes the goal *between* two drift‑check invocations and compaction happens immediately afterward, PreCompact could still re‑inject a slightly stale goal (the time window is small but non‑zero). This is not a safety issue thanks to the `updated_at` stamp, but the invariant that “the goal survives compaction exactly as last set” has a narrow gap. The plan should consider forcing a drift flush (update the scratch file) immediately before PreCompact if the file’s `updated_at` is older than the last model message that changed the goal. **Grade: P2 (important).**

## TOP 3 CHANGES

1. **Define the handoff artifact (P1).** Specify where the curator writes the handoff (a file, a `session_handoff_<id>.json` in `~/.claude/state/`, an update to the scratch file, etc.) and its exact structure. This is a blocker for S4 implementation.
2. **Design a concrete liveness detection mechanism for the re