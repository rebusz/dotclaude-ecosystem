# Trading Data-Flow Seam — full contract (read on demand)

Pointer target from `agent-rules/core.md` → `## Ecosystem`. The core.md invariant is the one-way flow + gated seam + "nothing writes live order state except the live brain". This file holds the full contract and the forbidden-coupling specifics, loaded only when wiring anything that touches the research↔live boundary.

- Trading data flow defaults one-way: **Tsignal → TsignalLAB → Obsidian Flow**.
- Reverse contribution of DATA/insight is allowed ONLY through a validated, async, gated seam: **candidate store + validation gate + shadow + signed operator GO**.
- The live path owns its own state, never synchronously depends on research/cloud, and **nothing writes live decision/order state except the live brain**.
- Forbidden control-coupling: a research/LAB process writing the live store directly; the live path blocking on a research call; a shared mutable store on the live path.
- This data-flow seam is **distinct from, and additional to**, the absolute **LLM-never-on-order-path** boundary in `core.md` → `## Risk Classes`.
