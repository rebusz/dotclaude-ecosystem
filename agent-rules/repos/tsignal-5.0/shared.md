# Tsignal 5.0 Shared Rules

## System Role

- Tsignal 5.0 is a live-trading system for US index futures.
- Runtime stability is the highest priority.
- Tsignal is execution authority; WatchF, TsignalLAB, Obsidian Flow, Discord, and OpusF inputs are advisory unless the operator explicitly approves a live decision-path change.

## Local Ports

- Read `D:/APPS/_shared/PORTS.md` before changing or starting local servers.
- React GUI: `http://127.0.0.1:6175`.
- HTTP/API/webhooks: `http://127.0.0.1:6101`.
- WebSocket: `ws://127.0.0.1:6102`.
- Manual levels webhook: `http://127.0.0.1:6103`.
- Do not use legacy ports `5173`, `5174`, `5178`, `5179`, `9001`, or `9002`.
- Do not let Vite auto-select another port; Tsignal must fail loudly if `6175` is occupied.

## Non-Negotiables

- No blocking I/O on tick callbacks.
- No GUI-thread network work; use async or a thread pool.
- No `shared_memory` unless profiler evidence justifies it.
- SQLite WAL is write master; cloud/network is never the live path.
- No LLM/agent access to broker API or order path.
- Manual approval is required for live decision changes.
- Bridge events require idempotency key, schema version, timestamp, and provenance.
- Use atomic write-temp-rename for persistence files.
- GUI work belongs in React under `tsignal-gui/`, not PySide6 widgets.
