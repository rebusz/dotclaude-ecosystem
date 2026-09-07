# Prompt protocols v2 — maintained role source candidate

Source draft; NOT_INSTALLED. Owner release specification:
[authorized activation appendix](https://github.com/rebusz/apps-shared/blob/fb485e5/design/visions/astra-instructions-v1/protocols-v2/ACTIVATION.md).
This committed reference remains readable before the release reaches the primary
checkout. Current delivery status is maintained in apps-shared PR73.
Initial content is from apps-shared PR72, commit
c9ee38db3258e806bc72db23108c1dd5cc2f60f6. Future maintained edits belong here;
that document package remains the historical comparison baseline.

Load 00-contract.md once plus the requested role. Local core modes are audit,
architect, quant, debug and implement. Workflow roles are ceo-review,
cdp-plan-audit, synthesis, eng-review and implementation-review. full-workflow.md
is the integration design until the installed command/renderer supports it.

The source router improves core fallback loading. It does not install gstack
adapters, change repo Prompts/master_agent.md, change a model roster or make
plan-audit/v2 callable through the existing legacy parser. CDP integration must
change its producer and parser together; retain implementation-review/v1.
Install the complete reference tree using the maintained manifest, snapshot
only owned targets, check hashes and prove discovery in a fresh harmless task.

No behavioral A/B or independent exact-head review has yet qualified this draft.

Maintained [host entry templates](../host-adapters/README.md) contain the CEO,
eng, review and shared diagnosis adapters. The [plan-audit/v2 contract](plan-audit-v2-contract.md)
defines the coordinated renderer/consumer boundary. The [dispatch handoff](workflow-dispatch.md)
documents current commands and their required policy readback; it adds no runner.
