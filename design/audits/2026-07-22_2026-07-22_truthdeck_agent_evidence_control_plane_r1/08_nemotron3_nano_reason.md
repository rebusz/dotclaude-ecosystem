# Audit — Nemotron 3 Nano Omni 30B reasoning (free)

Model: `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`  
Tokens: 17,932  
Latency: 74.8s  
Packet Context: none; model=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free

---

**Architectural soundness**  
- **P1** – *Missing explicit collector contract* – The “Collector contract” (section **## Collector contract**) only describes the function signature `collect(scope, policy, deadline) -> CollectorResult`. No base class, protocol, or enforced interface is defined, leaving ownership and correctness to documentation alone. This is a blocker because it opens the door to collectors that do not respect the deadline, return malformed results, or write outside the allowed paths. *(cited: ## Collector contract)*  
- **P2** – *Insufficient registry validation detail* – The “Registry and policy” section (## Registry and policy) states that the registry is validated before collectors run, but it does not specify how unknown major schema versions, missing required fields, or version mismatches are handled. Without a clear validation policy, the system could silently accept incompatible configurations, causing subtle correctness bugs. *(cited: ## Registry and policy)*  
- **P3** – *Concurrent snapshot write race* – The “Storage and concurrency” section (## Storage and concurrency) notes atomic exclusive‑create semantics but does not describe how two collectors could attempt to replace the same `latest.json` pointer simultaneously. The current design risks a lost‑update scenario where the latest pointer points to a partially written or duplicate artifact. *(cited: ## Storage and concurrency)*  

**Threading/async safety**  
- **P1** – *No synchronization for concurrent snapshot writes* – As above, the lack of a lock or atomic rename around the `latest.json` update creates a race condition when multiple agents produce snapshots for the same scope. This is a blocker because it can corrupt the canonical pointer and break reproducibility. *(cited: ## Storage and concurrency)*  
- **P2** – *Blocking I/O in collectors not bounded* – The “Performance acceptance” section (## Performance acceptance) caps per‑collector timeouts but does not guarantee that a collector that blocks (e.g., long‑running `git` enumeration) will not hold up the CLI or cause the total snapshot deadline to be exceeded. This could violate the 2‑second p95 target for local snapshots. *(cited: ## Performance acceptance)*  

**Edge cases**  
- **P1** – *Unclear mapping of collector failure modes to reason codes* – The “Failure and rescue registry” (## Failure and rescue registry) lists many reason codes, but it does not specify which collector exit status or internal error maps to which code (e.g., non‑zero exit vs. timeout vs. output‑limit). Ambiguous mapping can cause a `PASS` when the intent was `UNKNOWN` or `BLOCKED`. *(cited: ## Failure and rescue registry)*  
- **P2** – *TTL and freshness handling for runtime probes* – The “Data contract” (## Data contract) mentions `fresh_until_utc` but does not define how a probe that expires after the snapshot is sealed should be treated. If a stale probe result is cached beyond its TTL, the system could report `PASS` incorrectly. *(cited: ## Data contract)*  

**Cost/performance**  
- **P1** – *No total deadline enforcement for snapshot collection* – The “Performance acceptance” section caps individual collector timeouts but does not bound the overall wall‑clock time for a multi‑collector snapshot (e.g., Git + GitHub + runtime probes). Without a global deadline, a slow collector could push the snapshot beyond the 2‑second p95 budget. *(cited: ## Performance acceptance)*  
- **P2** – *Potential excessive API calls* – The “Collector contract” (## Collector contract) allows a `gh` JSON collector, but there is no guidance on how many calls are made per snapshot or how rate‑limiting is enforced. Unbounded API usage could increase latency and cost, violating the 10‑second p95 target for GitHub‑inclusive snapshots. *(cited: ## Collector contract, ## Performance acceptance)*  

**Integration risks**  
- **P1** – *Missing guarantee that snapshots embed the registry version/digest* – The “Data contract” (## Data contract) states that the snapshot records the registry/policy digest, yet the design does not enforce that the digest is immutable for the lifetime of the snapshot. If the registry changes after a snapshot is taken, later validation could become inconsistent. *(cited: ## Data contract)*  
- **P2** – *Potential collector‑allowlist mismatch* – The “Registry and policy” (## Registry and policy) permits disabling or narrowing collectors per profile, but it does not spell out how the system validates that a requested collector is actually allowed for the given scope. A mis‑configuration could cause a prohibited collector to run, breaking the read‑only guarantee. *(cited: ## Registry and policy)*  

**Underspecified areas**  
- **P1** – *Multi‑repo scope handling and fact namespace* – The “Stage model” (## Stage model) and “Data contract” (## Data contract) assume a single repository scope, but the CLI supports bounded multi‑repo requests. The plan does not define how fact keys are namespaced per repo, how required stages are ordered across repos, or how the “one next action” is selected when multiple repos have pending gates. *(cited: ## Stage model, ## Data contract)*  
- **P2** – *Path placeholder resolution with Unicode and spaces* – The “Collector contract” (## Collector contract) mentions that placeholders are resolved without command substitution, but it does not specify how Windows paths containing spaces, Unicode characters, or reparse points are canonicalized. This omission could lead to `BOUNDARY_REFUSAL` or incorrect repository detection. *(cited: ## Collector contract)*  
- **P3** – *Tie‑breaking rules for next‑action selection* – The “Next‑action algorithm” (## Next‑action algorithm) describes the deterministic selection process but does not detail how ties (e.g., two equally early `HOLD` stages) are resolved. Without a deterministic tie‑breaker, the output could be nondeterministic, violating the “deterministic core” invariant. *(cited: ## Next‑action algorithm)*  

---

### TOP 3 CHANGES  

1. **Introduce an explicit collector interface (base class or protocol)** that enforces the `collect(scope, policy, deadline) -> CollectorResult` contract, validates deadline usage, and guarantees that all collectors run under the same deadline semantics. This resolves ownership ambiguity and prevents accidental violations of the read‑only / no‑write rules. *(cited: ## Collector contract)*  

2. **Implement atomic snapshot creation with a safe latest‑pointer update** – use a temporary file, write the JSON atomically, then rename it, and perform the `latest.json` pointer replacement only after the snapshot validates. Add a file‑system lock or version check to avoid concurrent write races. *(cited: ## Storage and concurrency)*  

3. **Define clear TTL‑based freshness enforcement and reason‑code mapping** – specify that any collector timeout, non‑zero exit, or output‑limit condition maps to the appropriate reason code (`COLLECTOR_TIMEOUT`, `COLLECTOR_OUTPUT_LIMIT`, etc.) and that runtime probes whose `fresh_until_utc` has passed are treated as `UNKNOWN`/`NO_SAMPLE`. Include a global snapshot deadline (e.g., 2 s p95) that aborts the collection pipeline if any collector exceeds its per‑collector or total budget. *(cited: ## Failure and rescue registry, ## Data contract, ## Performance acceptance)*