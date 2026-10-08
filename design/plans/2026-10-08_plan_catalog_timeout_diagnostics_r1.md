---
title: Plan catalog timeout diagnostics and full-scope performance
date: 2026-10-08
status: in-progress
risk: R1
repos: [dotclaude-ecosystem]
tags: [catalog, performance, diagnostics]
---

# Plan catalog timeout diagnostics and full-scope performance

The post-commit plan updater currently loses useful catalog progress when its global scan exceeds the existing60-second deadline. The goal is a complete, timely global catalog plus retained phase/count diagnostics on failure, preserving the last valid output and continuing the existing vision update.

Source owner: scripts/plan_catalog.py and scripts/plan_context_updater.py. Focused controls: scripts/tests/test_plan_catalog_diagnostics.py. Base446bdf681116325667d4a022d1052e1e7dd4bacf on main; owned branch codex/plan-catalog-diagnostics-main-20261008-01a10bd5. The operator's unrelated dirty primary remains untouched. The earlier431cb branch is not an ancestor of current main and must not be published with unrelated GUI ancestry.

Risk R1, non-live tooling. No trading runtime/account/order changes. Keep BASE=d:/APPS, the complete discovered repository/file set, strict shared YAML parser and its100-content-line cap, BOM/CRLF/invalid-encoding behavior, metadata precedence and filename/body/mtime fallback, warnings, deterministic ordering,60-second updater timeout and atomic os.replace publication. Do not solve the deadline by excluding inputs, increasing it or serving stale cached results.

Implementation: flushed monotonic phase/counter checkpoints, bounded retained TimeoutExpired stdout/stderr tails, conditional single-read fallback and bounded parallel file parsing. Eight threads process at most256 outstanding files; results and per-file faults are consumed in discovery order. The actual parser and shared strict YAML helper remain unchanged from the single-read source. The first single-read correction timed out; a streamed line-reading successor also timed out and was withdrawn after profiling. The current bounded-I/O version completed the full84,954-file scan in28.1381s; focused12 controls and affected-file lint passed. Required independent review and CI remain open.

Validation: actual native focused pytest through the canonical WatchF interpreter, retained Popen/shell=False, owned temporary root and JUnit; affected-file lint; then actual full d:/APPS native catalog scan with only OUTPUT redirected into owned scratch, deadline60s. Verify all input coverage, completed render/publication, source hashes and installed/global output before/after. A passing focused suite alone does not prove global performance. Repeat only after a relevant source change.

Delivery: existing /fwf R1 lifecycle, independent exact-head review and required self-hosted CI. This public repository requires an operator-controlled isolated dotclaude-isolated runner; registered runners currently0 and workflows disabled. Keep draft CI_BLOCKED; never route public code to the trusted trading runners or use hosted CI. No Ready/merge/install clearance follows from local tests.

Rollback: revert the scoped source/test unit through its PR. Installed scripts and ~/.claude/PLANS.md remain unchanged until authorized, reviewed landing and normal installation.

Definition of done: original parser/output contracts preserved, focused checks and full-scope60-second probe successful, diagnostics retained on real failure, independent review and required CI complete, scoped change committed/pushed/merged and source checkout synchronized. Performance and landing remain open.
