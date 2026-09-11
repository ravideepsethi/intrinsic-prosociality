#!/usr/bin/env python3
"""Fail-closed preflight for pool-main Wave 2B2A."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

from runner import common


EXPECTED_SAMPLE_FINGERPRINT = "a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30"
EXPECTED_WAVE2B1_STATUS_SHA256 = "d3010bb7b4dd41fbb486b4ce829dcde9d58e6c2f8c14e45c16b3093d77eebc67"
EXPECTED_HISTORY_SUCCESS_SHA256 = "2e5ba421a1c628591e5004e6a60a89a39d7d017a3f5578ba88b4809f6853b417"
EXPECTED_HISTORY_SUMMARY_SHA256 = "61400d62e8b92bc0b8fe7e7a9746f650e37144fd63de49d92699aaf0e1f103d7"
EXPECTED_HISTORY_CONFIG_SHA256 = "08b276df68d7bd5a424f8813f6300c4e3f8db1c9d362883c322288e62b476349"
EXPECTED_PROCESSED_PAIR_ROWS = 66_236_172
EXPECTED_RAW_PAIR_EVENT_ROWS = 154_693_194


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave2b1-private", type=Path, required=True)
    parser.add_argument("--wave2b1-public", type=Path, required=True)
    parser.add_argument("--wave2b2a-private", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--hash-workers", type=int, default=10)
    parser.add_argument("--min-free-gb", type=int, default=70)
    return parser.parse_args()


def _require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"Missing {label}: {path}")
    observed = common.sha256_file(path)
    if observed != expected:
        raise RuntimeError(
            f"{label} changed: expected={expected}; observed={observed}; path={path}"
        )


def _history_state(private: Path) -> Path:
    return (
        private
        / "project_view/derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    package = common.verify_package_manifest()
    environment = common.verify_runtime_dependencies()
    auth = common.authenticate_sample(
        args.sample_root, verify_hashes=True, hash_workers=args.hash_workers
    )
    if auth["fingerprint"] != EXPECTED_SAMPLE_FINGERPRINT:
        raise RuntimeError("Selected panel is not the frozen pool/non-adjacent authority")

    project = args.project_root.expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError(f"Project root is missing: {project}")
    wave2b1_private = args.wave2b1_private.expanduser().resolve()
    wave2b1_public = args.wave2b1_public.expanduser().resolve()
    status_path = wave2b1_public / "WAVE2B1_RUN_STATUS.json"
    _require_hash(status_path, EXPECTED_WAVE2B1_STATUS_SHA256, "Wave 2B1 status receipt")
    status = common.load_json(status_path)
    if status.get("status") != "POOL_MAIN_WAVE2B1_ALL_STAGES_OK":
        raise RuntimeError("Wave 2B1 is not certified complete")
    if (status.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Wave 2B1 and Wave 2B2A sample authorities differ")

    history_public = Path(status["result_roots"]["second_wave_histories"])
    _require_hash(
        history_public / "_SUCCESS.json",
        EXPECTED_HISTORY_SUCCESS_SHA256,
        "Wave 2B1 history success receipt",
    )
    _require_hash(
        history_public / "summary.json",
        EXPECTED_HISTORY_SUMMARY_SHA256,
        "Wave 2B1 history summary",
    )
    history_summary = common.load_json(history_public / "summary.json")
    if (
        history_summary.get("checkpoint_config_sha256")
        != EXPECTED_HISTORY_CONFIG_SHA256
        or int(history_summary.get("processed_pair_rows", -1))
        != EXPECTED_PROCESSED_PAIR_ROWS
    ):
        raise RuntimeError("Wave 2B1 pair-history authority changed")

    history_state = _history_state(wave2b1_private)
    processed = [
        history_state / "pair_history_processed" / f"bucket_{index:02d}.parquet"
        for index in range(16)
    ]
    receipts = [
        history_state / "pair_bucket_receipts" / f"bucket_{index:02d}.json"
        for index in range(16)
    ]
    missing = [str(path) for path in processed + receipts if not path.is_file()]
    if missing:
        raise RuntimeError(f"Wave 2B1 private pair history is incomplete: {missing[:4]}")
    event_receipt = history_state / "pair_events_receipt.json"
    if not event_receipt.is_file() or not any(
        path.is_file() for path in (history_state / "pair_events").rglob("*.parquet")
    ):
        raise RuntimeError("Wave 2B1 raw sampled pair-event state is incomplete")
    event_payload = common.load_json(event_receipt)
    if (
        event_payload.get("config_sha256") != EXPECTED_HISTORY_CONFIG_SHA256
        or int(event_payload.get("rows", -1)) != EXPECTED_RAW_PAIR_EVENT_ROWS
    ):
        raise RuntimeError("Wave 2B1 raw pair-event receipt changed")

    destination = args.wave2b2a_private.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(destination).free
    if free_bytes < args.min_free_gb * 1024**3:
        raise RuntimeError(
            f"Wave 2B2A requires at least {args.min_free_gb} GiB free; "
            f"observed={free_bytes / 1024**3:.1f} GiB"
        )

    result = {
        "status": "POOL_MAIN_WAVE2B2A_PREFLIGHT_READY",
        "created_at_utc": common.utc_now(),
        "package": package,
        "environment": environment,
        "sample_authority": common.compact_sample_lineage(auth),
        "wave2b1_status": str(status_path),
        "wave2b1_status_sha256": EXPECTED_WAVE2B1_STATUS_SHA256,
        "history_public": str(history_public),
        "history_success_sha256": EXPECTED_HISTORY_SUCCESS_SHA256,
        "history_summary_sha256": EXPECTED_HISTORY_SUMMARY_SHA256,
        "history_state": str(history_state),
        "processed_pair_rows": EXPECTED_PROCESSED_PAIR_ROWS,
        "raw_pair_event_rows": EXPECTED_RAW_PAIR_EVENT_ROWS,
        "free_gib": free_bytes / 1024**3,
        "network_requests": 0,
    }
    common.atomic_json(args.receipt, result)
    print(result["status"], flush=True)
    return result


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
