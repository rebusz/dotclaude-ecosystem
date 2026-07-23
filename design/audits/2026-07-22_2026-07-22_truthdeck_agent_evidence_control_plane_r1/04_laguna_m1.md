# Audit — Poolside Laguna M.1 (free)

Model: `poolside/laguna-m.1:free`  
Tokens: 15,429  
Latency: 92.0s  
Packet Context: none; model=poolside/laguna-m.1:free

---


## Audit Findings

### 1. Architectural Soundness

**P1 - Missing concurrent writer collision handling specification**  
Section "Storage and concurrency" states concurrent writers create separate immutable artifacts but doesn't specify the exact mechanism for preventing race conditions during the "exclusive-create semantics" phase. The atomic latest pointer replacement failure is mentioned but the recovery path for partial writes or filesystem-level race conditions is underspecified.

**P2 - Insufficient git_hygiene reuse boundary definition**  
Section "S2 - Generic collectors" mentions reusing `git_hygiene` read logic but doesn't specify which exact functions/modules are safe to import. The plan needs explicit import boundaries to prevent accidental invocation of apply/deploy paths.

**P2 - Registry security enforcement mechanism undefined**  
Section "Registry and policy" states users cannot add argv/executables/modules but doesn't specify the validation mechanism. How is the registry schema enforced to prevent injection of arbitrary commands?

### 2. Threading/Async Safety

**P1 - Race condition in latest.json atomic replacement**  
Section "Storage and concurrency" describes atomic replacement but doesn't address what happens if the filesystem doesn't support atomic renames (e.g., cross-filesystem moves) or if the process crashes mid-replacement. The recovery path for a corrupted or stale `latest.json` is missing.

**P3 - No specification for subprocess cleanup on Windows**  
Section "Collector contract" mentions terminating subprocesses on timeout but doesn't specify Windows-specific process tree cleanup (e.g., child processes that may outlive the parent).

### 3. Edge Cases

**P1 - Registry corruption recovery undefined**  
Section "Error and rescue registry" doesn't cover what happens when `~/.truthdeck/registry.json` is corrupted, malformed, or has an unsupported schema version. The fail-closed behavior needs explicit handling.

**P2 - Partial write handling in concurrent scenarios**  
If a snapshot write is interrupted (power failure, process kill), the plan doesn't specify how incomplete artifacts are detected and cleaned up during subsequent reads.

**P2 - Cross-filesystem symlink handling**  
Section "Collector contract" mentions symlink resolution but doesn't address cross-filesystem symlinks which could bypass containment checks.

### 4. Cost/Performance

**P2 - No caching strategy for repeated identical requests**  
The plan explicitly rejects caching-derived PASS in v1, but doesn't address performance implications for repeated identical snapshot requests within TTL windows. This could lead to excessive GitHub API calls.

**P3 - Missing performance degradation handling**  
If individual collectors exceed their timeouts repeatedly, there's no circuit-breaker or backoff mechanism specified, potentially leading to resource exhaustion.

### 5. Integration Risks

**P1 - MCP configuration schema discovery underspecified**  
Section "S5 - Skill, MCP adapter, and installation" states "discover and fixture-test the exact active Claude/Codex configuration schemas" but doesn't specify what these schemas are, how they're discovered, or what happens if they change. This is a critical integration point.

**P2 - Registry template version migration path**  
The plan mentions installer preserves existing user configuration and writes `.from-template` candidate when template version advances, but doesn't specify the merge strategy or conflict resolution for user-modified registry entries.

### 6. Underspecified Areas

**P1 - Exact git_hygiene module boundaries**  
Before implementation, the plan needs to explicitly list which functions from `git_hygiene.py` are safe to import and how to extract them without mutation capabilities.

**P1 - MCP registration rollback atomicity**  
Section "Activation and rollback" describes MCP removal using ownership marker but doesn't specify how to handle partial failures during registration (e.g., skill copied but MCP registration fails).

**P2 - Registry schema validation implementation**  
The plan needs more detail on how the registry JSON schema validation works, particularly for rejecting unknown executable paths and ensuring probe IDs map to code-owned implementations.

---

## TOP 3 CHANGES

1. **Add explicit concurrent write handling specification** - Define the exact mechanism for exclusive-create semantics including filesystem-level atomicity guarantees, partial write detection, and recovery procedures for interrupted snapshot creation.

2. **Specify git_hygiene import boundaries** - Create a clear list of safe read-only functions from `git_hygiene.py` with explicit module boundaries, and add regression tests ensuring no mutation paths are accidentally invoked.

3. **Define MCP configuration schema discovery and handling** - Document the exact Claude/Codex configuration schemas, specify how they're discovered and validated, and define behavior for schema version mismatches including fail-closed handling.
