# Audit — Cohere North Mini Code (free)

Model: `cohere/north-mini-code:free`  
Tokens: 16,573  
Latency: 73.1s  
Quality: DEGENERATE — truncated_mid_sentence  
Packet Context: none; model=cohere/north-mini-code:free

---

## Architectural soundness

| Finding | Location | Grade | Detail |
|---|---|---|---|
| **Missing registry schema & template** | ## Registry and policy → “`~/.truthdeck/registry.json` is user‑owned configuration created from `templates/truthdeck.registry.json.template` only when absent.” | **P1** | No JSON schema, validation rules, or example template are provided. Without a contract, a malformed registry could silently disable required collectors or enable unsafe argv, breaking the “fail‑closed” guarantee. |
| **No explicit guard against importing application repos** | ## Module layout → “No module may import an application repo.” | **P2** | The plan states the rule but does not enforce it at import time (e.g., via `sys.modules` checks or static analysis). A future developer could inadvertently import a repo‑specific module, violating the read‑only boundary. |
| **Ownership of `plan_context_loader.py` limitation not addressed** | ## Current‑state evidence and reuse map → “`plan_context_loader.py` currently detects only repositories directly under `D:/APPS`, so it does not detect this repository under `D:/dotclaude`.” | **P1** | TruthDeck must collect facts for its own repository (`dotclaude-ecosystem`). The existing loader cannot discover it, so the Git/plan/GitHub/review collectors will miss the host repo unless a separate discovery path is added. |
| **Atomic‑write semantics lack explicit cross‑platform locking** | ## Storage and concurrency → “Each snapshot is immutable and created with exclusive‑create semantics.” | **P2** | “Exclusive‑create” is not defined for Windows (e.g., `CreateFile` with `CREATE_EXCLUSIVE`). Without a documented lock (e.g., `msvcrt.locking` or `portalocker`), concurrent writers could corrupt `latest.json` or produce duplicate content IDs. |
| **Profile predicate evaluation is underspecified** | ## Module layout → `scripts/truthdeck_profiles.py` (no content shown) | **P2** | The plan says profiles define “code‑owned probe allowlist and profile predicates” but does