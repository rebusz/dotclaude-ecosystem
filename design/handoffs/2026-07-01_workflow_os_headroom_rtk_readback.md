# Workflow OS Headroom/RTK Benchmark Readback

Date: 2026-07-01
Risk: R1 measurement-only
Status: completed, decision PARK

## Scope

This benchmark used the existing B0 mixed-session baseline and did not install hooks, wrap agents, start a proxy, set `ANTHROPIC_BASE_URL`, or touch TSU/Tsignal runtime/order paths.

Machine-readable report:

```text
design/measurements/2026-07-01_headroom_rtk_benchmark_report.json
```

Harness:

```text
scripts/headroom_rtk_benchmark.py
```

## Inputs

B0 baseline:

```text
design/baselines/workflow_os_b0_mixed_sessions.json
```

Selected sessions:

- `read_heavy_audit`
- `multi_file_edit`
- `research_plan`

## Headroom Result

Headroom was installed only in an isolated temporary virtual environment and run through:

```powershell
headroom audit-reads --path <temp-b0-jsonls> --format json
```

Observed B0 read-traffic metrics:

- sessions: `3`
- read calls: `73`
- read bytes: `670533`
- line-number overhead bytes: `27907`
- stale read calls: `17`
- stale bytes: `88427`
- identical dedup bytes: `0`
- subset bytes: `0`

Interpretation: Headroom found measurable read traffic and some stale/line-number overhead, but the selected B0 sessions did not show identical/subset read dedup opportunity. This is an opportunity audit, not a full replay proving total-cost reduction or artifact equivalence.

## RTK Result

RTK was not available locally:

```text
rtk executable not found on PATH
```

The npm package named `rtk` is not the RTK AI command-output proxy; it is a release-tool package. Native Windows RTK also has hook limitations, so no RTK command-output benchmark was run in this slice.

## Decision

Decision: `PARK`.

Do not enable Headroom or RTK by default.

Reason:

- Workflow OS ship gate requires total cost reduction of at least 15 percent, not input-only opportunity.
- This run did not replay the three B0 sessions through a proxy and compare output tokens, total cost, and functionally equivalent artifacts.
- RTK was not locally available as the intended executable.

Future reopen condition: a separate explicit proxy-replay plan that can safely run representative sessions and prove total-cost reduction with no quality regression.
