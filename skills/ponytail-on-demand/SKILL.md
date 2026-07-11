---
name: ponytail-on-demand
description: Find the smallest correct implementation for bounded R0/R1 coding, refactoring, dependency, or design tasks. Use when the operator explicitly invokes Ponytail, asks for a minimal/YAGNI solution, or when the owning ARCHITECT, FWF, or FWP workflow selects a Ponytail checkpoint after identifying a concrete simplification opportunity. Never apply to audits, reviews, security, QUANT, persistence/ingestion contracts, R2/R3 work, or any live trading path.
---

# Ponytail On Demand

Minimize the solution only after understanding the real flow. Repo instructions,
the approved plan, validation contracts, and operator scope always outrank this
skill.

## Gate

1. Classify the task before minimizing it.
2. Continue only for R0/R1 work when either the operator explicitly requested
   Ponytail or the owning ARCHITECT/FWF/FWP workflow selected the checkpoint.
3. Stop using this skill for audit, review, security, QUANT, R2/R3, broker,
   order-path, live-runtime, persistence, ingestion-contract, or destructive
   work. Follow the owning repo workflow instead.
4. Do not inject this skill into subagents or install lifecycle hooks.

## Workflow Decision

ARCHITECT, FWF, and FWP must decide rather than run this skill as a ritual.
Select the checkpoint only after naming at least one concrete candidate such as
an avoidable dependency, duplicate abstraction, speculative interface, redundant
configuration, or unnecessary file/module. Otherwise record
`PONYTAIL: SKIPPED - no concrete simplification candidate` and continue.

When selected, record `PONYTAIL: USED` plus the candidate, the simplification,
and the constraints preserved. The owning workflow's normal architecture or Eng
Review must run after the checkpoint so the smaller proposal is independently
validated.

## Ladder

After reading the touched exports, callers, tests, and shared utilities, stop at
the first rung that fully satisfies the task:

1. Skip work that is not actually required.
2. Reuse an existing codebase pattern or helper.
3. Prefer the standard library or native platform capability.
4. Prefer an already-installed dependency over adding another one.
5. Delete or simplify before adding an abstraction.
6. Implement the smallest production-shaped change that passes the real gate.

Do not introduce speculative factories, interfaces, configuration, wrappers,
flags, or scaffolding. Few files is a useful signal, not a target that overrides
correct ownership.

## Integrity

Never minimize away:

- trust-boundary validation;
- error handling that prevents data loss or false success;
- security, privacy, accessibility, custody, or provenance controls;
- realistic tests and validation required by the repo or approved plan;
- rollback, review, or operator-GO gates.

Fix the root cause at the narrowest shared seam. A tiny patch in the wrong layer
is not a minimal solution; it is deferred rework.

## Delivery

Implement the approved behavior, run proportionate validation, and report:

- what was reused or deleted;
- what complexity or dependency was avoided;
- which condition would justify a larger solution later.

Do not challenge or silently shrink an explicit requirement after the operator
has approved it.

## Provenance

Adapted as an explicit, ecosystem-safe subset of
`DietrichGebert/ponytail` (MIT), reviewed 2026-07-10:
https://github.com/DietrichGebert/ponytail
