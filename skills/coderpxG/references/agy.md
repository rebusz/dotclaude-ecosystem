# Antigravity model selection

Within CoderPX G, choose the AGY model when assigning a new task.

| Assignment | AGY selection | Effort |
|---|---|---|
| Hard diagnosis, coupled changes, or difficult integration | Orchestrator (Carbon) | Let the orchestrator choose automatically. Omit an explicit effort override. |
| Other implementation, testing, review, or research assigned to AGY | Gemini 4 Hydrogen | Select High explicitly. |
| Direct Gemini 4 Carbon requested for a task | Gemini 4 Carbon | Use the requested level or choose a supported level appropriate to the task. Low, Medium and High are distinct direct selections. |

Use the existing CoderPX dispatcher and verify the native model identity in the receipt. The Hydrogen High selector is `gemini-4-hydrogen-high`. For the orchestrated route, verify that the installed selector maps to **Orchestrator (Carbon)**. The direct Carbon and Orchestrator (Argon) selections are distinct. When the orchestrator does not report its internal effort, record requested effort as automatic and actual effort as unknown. Preserve the model and owner of work already submitted and the normal independent-review rules.
