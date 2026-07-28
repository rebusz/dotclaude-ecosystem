# TSU Claude Overlay

## Entry Points

- `python -m tsu.supervisor` - main supervisor process (P0)
- `python -m pytest` - validation test suite

## Ports

- HTTP/API: `10100`
- WebSocket: `10102`
- GUI: `10175`
- Supervisor health: `10104`
- Read `D:/APPS/_shared/PORTS.md` before starting servers. Fail loudly if a port is occupied.

## Code Intelligence & Skill Routing

Use code intelligence/graph tools for impact analysis before cross-module edits.
Load-on-demand `tsu-*` skills for deep domain procedures:
- `tsu-arming-chain-campaign`: Arming readiness triage
- `tsu-custody-exit-integrity`: Close-lifecycle & custody verification
- `tsu-failure-archaeology`: Incident investigation
- `tsu-order-path-change-control`: Risk classification & ADR-008 checks
- `tsu-cockpit-gui-conventions`: ISA-101 GUI rules & authority guards
- `tsu-depth-and-inputs-reference`: Depth/DOM capabilities & input registry
- `tsu-run-and-operate`: Launch & process mutual exclusion
- `tsu-build-validate-and-docs`: Test/lint commands & doc layout
- `tsu-brain-authority-and-confidence`: Decision authority seams
- `tsu-architecture-contract`: System structural map & boot spine
