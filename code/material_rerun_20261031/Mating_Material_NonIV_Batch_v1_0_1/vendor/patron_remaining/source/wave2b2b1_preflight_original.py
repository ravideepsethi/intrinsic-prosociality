#!/usr/bin/env python3
"""Fail-closed preflight for pool-main Wave 2B2B1."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import shutil
from pathlib import Path
from typing import Any

from runner import common


EXPECTED_SAMPLE_FINGERPRINT = "a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30"
EXPECTED_WAVE2B1_STATUS_SHA256 = "d3010bb7b4dd41fbb486b4ce829dcde9d58e6c2f8c14e45c16b3093d77eebc67"
EXPECTED_WAVE2B2A_STATUS_SHA256 = "7a154fd57833fb15d333b7d0183d5d070919d59f5e15f91dd1c1685207101910"
EXPECTED_RECIPIENT_SHA256 = "55ffdfae9179007fa6437930e3a838f112b28c7906c36ff6438521214cce261b"
EXPECTED_RECIPIENT_ROWS = 2_369_530
EXPECTED_A2_SHA256 = "23c0fc7c07bbab8c59d91ce314c4ad358b29e33127e56a71d137a21fca24bac9"
EXPECTED_A2_ROWS = 1_527_217
EXPECTED_REMAINING_SUCCESS_SHA256 = "fdf62efba7739d5e985f6b3d350157d9a348cf8be7bef4cf51fcfd156dd5e0c9"
EXPECTED_HISTORY_SUCCESS_SHA256 = "2e5ba421a1c628591e5004e6a60a89a39d7d017a3f5578ba88b4809f6853b417"
EXPECTED_USER_EVENT_ROWS = 309_961_276
EXPECTED_C7X_CLASSIFICATION_SHA256 = "27e351f5bd8c493c022e2c261590d5e21e8e32ed6ab5c51d20aae8bcec46912c"
EXPECTED_C7X_ROWS = 10_481
EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
EXPECTED_CHRONOLOGY_FILES = 852
EXPECTED_CHRONOLOGY_ROWS = 7_763_847_245
EXPECTED_DYAD_SCRIPT_SHA256 = "de468744408ebb29107d09c00e11d407dfc6ded036caf78f4b3e86077a2309aa"
EXPECTED_DYAD_GAMES = 2_229_237_137
EXPECTED_DYAD_THRESHOLDS = [2, 3, 5, 10]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave2b1-private", type=Path, required=True)
    parser.add_argument("--wave2b1-public", type=Path, required=True)
    parser.add_argument("--wave2b2a-private", type=Path, required=True)
    parser.add_argument("--wave2b2a-public", type=Path, required=True)
    parser.add_argument("--old-frequent-state", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--hash-workers", type=int, default=10)
    parser.add_argument("--min-free-gb", type=int, default=80)
    return parser.parse_args()


def require_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise RuntimeError(f"Missing {label}: {path}")
    observed = common.sha256_file(path)
    if observed != expected:
        raise RuntimeError(
            f"{label} changed: expected={expected}; observed={observed}; path={path}"
        )


def parquet_rows(path: Path) -> int:
    import pyarrow.parquet as pq

    return int(pq.ParquetFile(path).metadata.num_rows)


def authenticate_chronology(project: Path) -> dict[str, Any]:
    path = (
        project
        / "output/dynamic_prosociality_a3_chronology_gate_v100"
        / "20260821T234626Z/chronology_input_manifest.tsv"
    )
    require_hash(path, EXPECTED_CHRONOLOGY_MANIFEST_SHA256, "canonical chronology manifest")
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if len(rows) != EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError(f"Chronology file count changed: {len(rows)}")
    if sum(int(row["rows"]) for row in rows) != EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError("Chronology row authority changed")
    missing = [row["path"] for row in rows if not Path(row["path"]).is_file()]
    if missing:
        raise RuntimeError(f"Chronology files are missing: {missing[:4]}")
    return {
        "path": str(path),
        "sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
        "files": len(rows),
        "rows": EXPECTED_CHRONOLOGY_ROWS,
    }


def _authenticate_bucket(payload: tuple[Path, Path, str, int]) -> dict[str, Any]:
    output, receipt, config_sha, bucket = payload
    import pyarrow.parquet as pq

    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Frequent-dyad bucket {bucket:03d} is incomplete")
    saved = common.load_json(receipt)
    expected = {
        "status": "FREQUENT_DYAD_EXACT_BUCKET_PRIVATE_OK",
        "config_sha256": config_sha,
        "bucket": bucket,
        "output_rows": parquet_rows(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": common.sha256_file(output),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"Frequent-dyad bucket {bucket:03d} failed {key}")
    names = set(pq.ParquetFile(output).schema_arrow.names)
    if names != {"pair_bucket", "low_id", "high_id", "pair_games_24m"}:
        raise RuntimeError(f"Frequent-dyad bucket schema changed: {bucket}: {sorted(names)}")
    thresholds = saved.get("threshold_counts") or {}
    if sorted(map(int, thresholds)) != EXPECTED_DYAD_THRESHOLDS:
        raise RuntimeError(f"Frequent-dyad thresholds changed in bucket {bucket}")
    if int(saved["output_rows"]) != int(thresholds["2"]["pairs"]):
        raise RuntimeError(f"Frequent-dyad repeated-pair conservation failed: {bucket}")
    return saved


def authenticate_frequent_state(state: Path, workers: int) -> dict[str, Any]:
    state = state.resolve()
    config_path = state / "state_config.json"
    if not config_path.is_file():
        raise RuntimeError(
            "The invariant exact frequent-dyad state is missing. Re-run the certified "
            "v1.0.1 census before Wave 2B2B1: " + str(config_path)
        )
    envelope = common.load_json(config_path)
    config = envelope.get("config") or {}
    config_sha = str(envelope.get("config_sha256") or "")
    if envelope.get("status") != "FREQUENT_DYAD_CENSUS_PRIVATE_CONFIG_V101":
        raise RuntimeError("Frequent-dyad state status changed")
    checks = {
        "script_sha256": EXPECTED_DYAD_SCRIPT_SHA256,
        "buckets": 128,
        "thresholds": EXPECTED_DYAD_THRESHOLDS,
        "expected_chronology_games": EXPECTED_DYAD_GAMES,
    }
    for key, value in checks.items():
        if config.get(key) != value:
            raise RuntimeError(f"Frequent-dyad invariant authority changed: {key}")
    tasks = []
    for bucket in range(128):
        tasks.append(
            (
                state / f"frequent_pairs/pair_bucket={bucket:03d}/part-00000.parquet",
                state / f"bucket_receipts/bucket_{bucket:03d}.json",
                config_sha,
                bucket,
            )
        )
    results: list[dict[str, Any]] = []
    maximum_workers = max(1, min(int(workers), 10))
    print(f"Authenticating 128 invariant dyad buckets with {maximum_workers} hash workers.", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=maximum_workers) as executor:
        futures = [executor.submit(_authenticate_bucket, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            results.append(future.result())
            if index % 16 == 0 or index == len(futures):
                print(f"DYAD_BUCKET_SHA256_PROGRESS {index}/128", flush=True)
    if sum(int(row["all_games"]) for row in results) != EXPECTED_DYAD_GAMES:
        raise RuntimeError("Invariant frequent-dyad buckets do not conserve chronology games")

    player = state / "frequent_players_private.parquet"
    player_receipt_path = state / "frequent_players_receipt.json"
    if not player.is_file() or not player_receipt_path.is_file():
        raise RuntimeError("Frequent-player index is missing")
    player_receipt = common.load_json(player_receipt_path)
    player_expected = {
        "status": "FREQUENT_DYAD_PLAYERS_PRIVATE_OK",
        "config_sha256": config_sha,
        "output_rows": parquet_rows(player),
        "output_bytes": player.stat().st_size,
        "output_sha256": common.sha256_file(player),
    }
    for key, value in player_expected.items():
        if player_receipt.get(key) != value:
            raise RuntimeError(f"Frequent-player index failed {key}")
    import pyarrow.parquet as pq

    player_names = set(pq.ParquetFile(player).schema_arrow.names)
    required = {"player_id", "maximum_pair_games_24m", "dyads_ge_2", "dyads_ge_3", "dyads_ge_5", "dyads_ge_10"}
    if player_names != required:
        raise RuntimeError(f"Frequent-player schema changed: {sorted(player_names)}")
    return {
        "status": "INVARIANT_FREQUENT_DYAD_INDEX_AUTHENTICATED_OK",
        "state_root": str(state),
        "config_sha256": config_sha,
        "buckets": 128,
        "chronology_games": EXPECTED_DYAD_GAMES,
        "repeated_pair_rows": sum(int(row["output_rows"]) for row in results),
        "player_rows": int(player_receipt["output_rows"]),
        "player_sha256": player_receipt["output_sha256"],
        "source_state_mutated": False,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    package = common.verify_package_manifest()
    environment = common.verify_runtime_dependencies()
    auth = common.authenticate_sample(
        args.sample_root, verify_hashes=True, hash_workers=args.hash_workers
    )
    if auth["fingerprint"] != EXPECTED_SAMPLE_FINGERPRINT:
        raise RuntimeError("Selected panel is not the frozen pool/non-adjacent authority")

    project = args.project_root.expanduser().resolve()
    wave2b1_private = args.wave2b1_private.expanduser().resolve()
    wave2b1_public = args.wave2b1_public.expanduser().resolve()
    wave2b2a_private = args.wave2b2a_private.expanduser().resolve()
    wave2b2a_public = args.wave2b2a_public.expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError(f"Project root is missing: {project}")

    b1_status_path = wave2b1_public / "WAVE2B1_RUN_STATUS.json"
    require_hash(b1_status_path, EXPECTED_WAVE2B1_STATUS_SHA256, "Wave 2B1 status")
    b1 = common.load_json(b1_status_path)
    if b1.get("status") != "POOL_MAIN_WAVE2B1_ALL_STAGES_OK":
        raise RuntimeError("Wave 2B1 is not complete")
    if (b1.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Wave 2B1 belongs to another sample")
    b1_view = wave2b1_private / "project_view"
    recipient = b1_view / "derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet"
    a2 = b1_view / "derived/replication/remaining_dynamic_completion_v100_PRIVATE/a2_account_windows_private.parquet"
    require_hash(recipient, EXPECTED_RECIPIENT_SHA256, "Wave 2B1 recipient file")
    require_hash(a2, EXPECTED_A2_SHA256, "Wave 2B1 A2 file")
    if parquet_rows(recipient) != EXPECTED_RECIPIENT_ROWS or parquet_rows(a2) != EXPECTED_A2_ROWS:
        raise RuntimeError("Wave 2B1 private row authorities changed")
    remaining = Path(b1["result_roots"]["remaining_a1_a2"])
    history_public = Path(b1["result_roots"]["second_wave_histories"])
    require_hash(remaining / "_SUCCESS.json", EXPECTED_REMAINING_SUCCESS_SHA256, "Wave 2B1 A1/A2 success")
    require_hash(history_public / "_SUCCESS.json", EXPECTED_HISTORY_SUCCESS_SHA256, "Wave 2B1 history success")
    history_state = b1_view / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    user_receipt = common.load_json(history_state / "user_events_receipt.json")
    if int(user_receipt.get("rows", -1)) != EXPECTED_USER_EVENT_ROWS:
        raise RuntimeError("Wave 2B1 user-event history changed")
    if not any((history_state / "user_events").rglob("*.parquet")):
        raise RuntimeError("Wave 2B1 user-event history files are missing")

    b2a_status_path = wave2b2a_public / "WAVE2B2A_RUN_STATUS.json"
    require_hash(b2a_status_path, EXPECTED_WAVE2B2A_STATUS_SHA256, "Wave 2B2A status")
    b2a = common.load_json(b2a_status_path)
    if b2a.get("status") != "POOL_MAIN_WAVE2B2A_ALL_STAGES_OK":
        raise RuntimeError("Wave 2B2A is not complete")
    if (b2a.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Wave 2B2A belongs to another sample")
    classification = wave2b2a_private / "c7x_state_v101/c7x_classification_private.parquet"
    require_hash(classification, EXPECTED_C7X_CLASSIFICATION_SHA256, "Wave 2B2A C7X classification")
    if parquet_rows(classification) != EXPECTED_C7X_ROWS:
        raise RuntimeError("Wave 2B2A C7X classification rows changed")

    chronology = authenticate_chronology(project)
    dyad = authenticate_frequent_state(
        args.old_frequent_state.expanduser().resolve(), args.hash_workers
    )
    destination = args.private_base.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(destination).free
    if free_bytes < args.min_free_gb * 1024**3:
        raise RuntimeError(
            f"Wave 2B2B1 requires at least {args.min_free_gb} GiB free; "
            f"observed={free_bytes / 1024**3:.1f} GiB"
        )

    result = {
        "status": "POOL_MAIN_WAVE2B2B1_PREFLIGHT_READY",
        "created_at_utc": common.utc_now(),
        "package": package,
        "environment": environment,
        "sample_authority": common.compact_sample_lineage(auth),
        "wave2b1": {
            "status_path": str(b1_status_path),
            "status_sha256": EXPECTED_WAVE2B1_STATUS_SHA256,
            "recipient": str(recipient),
            "recipient_sha256": EXPECTED_RECIPIENT_SHA256,
            "recipient_rows": EXPECTED_RECIPIENT_ROWS,
            "a2": str(a2),
            "a2_sha256": EXPECTED_A2_SHA256,
            "a2_rows": EXPECTED_A2_ROWS,
            "remaining_result": str(remaining),
            "history_public": str(history_public),
            "history_state": str(history_state),
        },
        "wave2b2a": {
            "status_path": str(b2a_status_path),
            "status_sha256": EXPECTED_WAVE2B2A_STATUS_SHA256,
            "classification": str(classification),
            "classification_sha256": EXPECTED_C7X_CLASSIFICATION_SHA256,
            "classification_rows": EXPECTED_C7X_ROWS,
        },
        "chronology": chronology,
        "invariant_frequent_dyad_index": dyad,
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
