---
title: H0 exact-head review resolution — CP-3 resource key
date: 2026-09-08
status: resolved_by_source_inspection
risk_class: R0
---

# Zakres

Resolution dotyczy jednego zarzutu z receipt CoderPX Kimi K3
`42dfadcc20964e39d7c80c46b9cf27739ff938ed953418c787fd9c85bad20788`,
reviewowanego exact HEAD `f70884080dede7c18f60a0596926aa8e5301303d` PR #110.
Nie zmienia runtime ani ścieżki brokera.

## Ustalenie

Review twierdzi, że plan wymaga wywołań bez `--resource-key` i że
`conductorctl` musi wyprowadzać klucz z roli. Aktualny plan
`design/plans/2026-08-27_cdp_admission_pool_split_r2.md` podaje jednak jawne
argv dla każdej puli:

```text
resource-request --purpose cdp_provider --resource-key cdp:chatgpt --role chrome_gpt --priority 50
resource-request --purpose cdp_provider --resource-key cdp:perplexity --role chrome_ppl --slot-key <model>
resource-request --purpose cdp_provider --resource-key cdp:gemini --role chrome_gemini
```

Wymagany kontrakt jest więc spełniony przez jawne klucze. Brak klucza pozostaje
obsługiwanym fallbackiem przez processor, ale nie jest wymaganym argv planu.

## Dowody exact HEAD

- `scripts/conductorctl.py` przenosi `args.resource_key` do envelope bez
  ukrytej zamiany na `host:heavy`.
- `scripts/conductor_resources.py::resolve_resource_key` odrzuca CDP z
  `host:heavy`, a zgodną rolę może rozwiązać do nazwanej puli.
- `scripts/tests/test_conductor_cli.py` sprawdza jawne `cdp_perplexity`,
  fallback `cdp_chatgpt` po roli oraz stale `host:heavy` z i bez roli.
- H0 focused validation: 67 tests passed, exit 0.

Wniosek: finding o „breaks the plan's required argv” jest nieważny po
porównaniu z aktualnym planem i źródłem. Nie przywracać wywołania
`resolve_resource_key` w CLI tylko po to, by spełnić błędną przesłankę review;
nie zmieniać dokumentowanego jawnego argv.

## Status bramki

Receipt pozostaje ważnym niezależnym exact-head review, ale jego
`MERGE-AFTER-FIX` należy traktować jako rozstrzygnięty przez source inspection;
nie ma potwierdzonego ship-blockera w H0. Consumer-side CP-3 jest osobno
udokumentowany w `design/handoffs/2026-09-08_cdp_cp3_consumer_adoption_evidence.md`.

