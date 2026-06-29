# Workflow OS B0 Candidate Inventory

Date: 2026-06-29
Risk: R1, measurement-only
Scope: redacted Claude JSONL usage inventory for TSU B0 selection. No TSU/Tsignal runtime, broker, order-path, or trading-config writes.

## Status

`workflow_os_b0_mixed_sessions.json` is still intentionally absent. This report is only a candidate inventory for selecting the three required B0 session classes:

- `read_heavy_audit`
- `multi_file_edit`
- `research_plan`

The JSONL files provide token/cache/output counters, but not `cost_usd`. A metadata-only scan of the local TSU JSONL records found `cost_keys_count=0`, so `/cost` remains the required external readback before any real B0 baseline can be generated.

## Inventory Command

```powershell
python scripts/session_cost_probe.py jsonl-inventory `
  --dir "$env:USERPROFILE\.claude\projects\D--APPS-TSU" `
  --limit 12
```

The command emits filenames, timestamps, models, file sizes, message counts, and usage counters only. Prompt/content text is omitted.

## Top Candidates

Sorted by `usage.total_tokens` descending:

| Rank | JSONL file | Usage records | First usage | Last usage | Input | Output | Cache read | Cache create | Total tokens |
| ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | `a2789764-b080-4b74-be74-bb17db55652e.jsonl` | 859 | 2026-06-15T18:44:10.004Z | 2026-06-16T17:28:20.603Z | 185467 | 2586321 | 464281517 | 10750029 | 477803334 |
| 2 | `e3c378d6-d4fd-4397-834a-9ca6ed35378f.jsonl` | 370 | 2026-06-16T14:35:03.071Z | 2026-06-20T19:56:29.508Z | 147295 | 1377761 | 140265784 | 24423317 | 166214157 |
| 3 | `5844f91a-68e0-4252-97e6-fae3702ca4f0.jsonl` | 340 | 2026-06-16T18:56:07.866Z | 2026-06-20T03:04:27.766Z | 100658 | 962177 | 75841719 | 8450745 | 85355299 |
| 4 | `f0b6fcbb-cf29-4d3f-90cb-056d0728f893.jsonl` | 192 | 2026-06-18T17:42:35.899Z | 2026-06-18T22:49:48.749Z | 86482 | 874505 | 36881796 | 3290497 | 41133280 |
| 5 | `876bdecb-94c0-43f4-bba6-01d742a7c78e.jsonl` | 19 | 2026-06-12T19:20:18.838Z | 2026-06-12T19:21:51.726Z | 10906 | 25944 | 1652560 | 907974 | 2597384 |
| 6 | `25685eab-5640-4c3a-be35-299a2fc41f24.jsonl` | 29 | 2026-06-17T03:20:23.872Z | 2026-06-17T04:04:47.723Z | 27411 | 44021 | 1708913 | 225699 | 2006044 |
| 7 | `e5df5060-871c-4043-b20b-7bc2aa7bd0ca.jsonl` | 7 | 2026-06-12T15:47:13.351Z | 2026-06-12T15:47:22.850Z | 1053 | 17343 | 0 | 788138 | 806534 |
| 8 | `c648e11b-85ef-4709-bb81-0cf587efabdd.jsonl` | 18 | 2026-06-12T18:06:07.055Z | 2026-06-12T18:08:05.858Z | 360 | 240174 | 0 | 504720 | 745254 |
| 9 | `f40d646d-d01a-47ec-ba77-da57905bc259.jsonl` | 2 | 2026-06-12T18:59:55.516Z | 2026-06-12T19:00:03.927Z | 446 | 12854 | 0 | 213648 | 226948 |
| 10 | `8ccbb587-bad5-44ae-a4f6-4e49de3f91b6.jsonl` | 2 | 2026-06-12T19:23:41.202Z | 2026-06-12T19:23:49.131Z | 1876 | 7932 | 0 | 169192 | 179000 |
| 11 | `6dc4335b-a9d0-47bd-8741-1d102b88b56c.jsonl` | 3 | 2026-06-12T15:46:13.102Z | 2026-06-12T15:46:14.750Z | 732 | 9936 | 0 | 139401 | 150069 |
| 12 | `165485fd-5b77-4296-98c6-7babf3020dcf.jsonl` | 2 | 2026-06-12T18:10:10.975Z | 2026-06-12T18:10:32.229Z | 40 | 20056 | 0 | 56660 | 76756 |

## Next B0 Collection Steps

1. Pick exactly one real session for each B0 class: `read_heavy_audit`, `multi_file_edit`, `research_plan`.
2. For each picked session, obtain the exact Claude `/cost` readback from the corresponding session context.
3. Run `jsonl-session` once per picked session with the explicit `--cost-usd`, `--startup-context-tokens`, quality summary, validation commands, and expected artifacts.
4. Run `mixed-baseline` only after all three measured session JSON files exist.
5. Re-run `workflow-triggers`; only then should `headroom-rtk-benchmark` stop being deferred.

## Boundary

This inventory does not choose the three B0 classes, does not estimate price from tokens, and does not create `design/baselines/workflow_os_b0_mixed_sessions.json`.
