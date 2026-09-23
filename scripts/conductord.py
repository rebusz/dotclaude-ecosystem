"""Port-free single-writer coordinator daemon for TruthDeck Conductor.

Acquires leader lock, polls inbox envelopes, processes state transitions, and performs liveness reconciles.
All environment variables use TDCONDUCTOR_* to avoid collision with 3rd-party host variables.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time

_repo_root = pathlib.Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from scripts.conductor_commands import ConductorCommandProcessor  # noqa: E402
from scripts.conductor_model import CommandEnvelope  # noqa: E402
from scripts.conductor_store import ConductorStore  # noqa: E402


def run_coordinator_loop(poll_interval_seconds: float = 1.0, single_pass: bool = False) -> None:
    store = ConductorStore()
    processor = ConductorCommandProcessor(store=store)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(store.logs_dir / "conductord.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logging.info(f"Starting conductord (Leader ID: {store.leader_id})")

    while True:
        if not store.acquire_leader_lock("primary_coordinator"):
            logging.warning("Failed to acquire/renew leader lock. Retrying...")
            if single_pass:
                break
            time.sleep(poll_interval_seconds)
            continue

        # Poll inbox files
        inbox_files = store.poll_inbox_envelopes()
        for filepath in inbox_files:
            try:
                content = filepath.read_text(encoding="utf-8")
                envelope_dict = json.loads(content)
                envelope = CommandEnvelope(
                    command_id=envelope_dict["command_id"],
                    command_type=envelope_dict["command_type"],
                    payload=envelope_dict.get("payload", {}),
                    idempotency_key=envelope_dict["idempotency_key"],
                    issued_at_utc=envelope_dict.get("issued_at_utc", ""),
                )

                receipt = processor.process_envelope(envelope)
                logging.info(f"Processed envelope {envelope.command_id} ({envelope.command_type}) -> {receipt.status}")

                # Remove inbox file after processing
                filepath.unlink(missing_ok=True)
            except Exception as err:
                # The file is only unlinked on the success path above, so a
                # truncated or malformed envelope was re-read on every poll --
                # one error line per second, forever, with no forward progress
                # (audit C13). Move it aside so the loop can continue and the
                # operator still has the evidence.
                logging.error(f"Error processing inbox file {filepath}: {err}")
                try:
                    quarantine = filepath.parent / "quarantine"
                    quarantine.mkdir(parents=True, exist_ok=True)
                    filepath.replace(quarantine / filepath.name)
                    logging.error(f"Quarantined unprocessable envelope -> {quarantine / filepath.name}")
                except OSError as move_err:
                    logging.error(f"Could not quarantine {filepath}: {move_err}")

        # Periodic reconcile. This is the coordinator's own housekeeping, not a
        # command anyone issued, so it does not go through the envelope path:
        # that path persists a receipt row AND a receipt file per call, and at
        # the default 1s poll it wrote ~86,400 of each per day for a no-op
        # (audit C12). Real work still leaves a trace, in the log.
        try:
            outcome = processor._handle_reconcile({"dry_run": False})
            if outcome.get("expired_count"):
                logging.warning(
                    f"Work-item reconcile expired {outcome['expired_count']} lease(s): "
                    f"{outcome.get('reconciled_items')}"
                )
        except Exception as err:
            logging.error(f"Error running auto reconcile: {err}")

        try:
            expired = processor.resources.reconcile()
            if expired.get("expired_count"):
                logging.warning(f"Host-resource reconcile fenced {expired['expired_count']} lease(s)")
        except Exception as err:
            logging.error(f"Error running host-resource reconcile: {err}")

        if single_pass:
            break

        time.sleep(poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="TruthDeck Conductor Coordinator Daemon")
    parser.add_argument("--single-pass", action="store_true", help="Run a single poll/reconcile loop pass and exit")
    parser.add_argument("--interval", type=float, default=1.0, help="Loop sleep interval in seconds")
    args = parser.parse_args()

    run_coordinator_loop(poll_interval_seconds=args.interval, single_pass=args.single_pass)


if __name__ == "__main__":
    main()
