from __future__ import annotations
import concurrent.futures
from pathlib import Path
from typing import Any
from source import pool_sample_common_v100 as common

EXPECTED_DYAD_SCRIPT_SHA256 = "de468744408ebb29107d09c00e11d407dfc6ded036caf78f4b3e86077a2309aa"
EXPECTED_DYAD_GAMES=2_229_237_137
EXPECTED_DYAD_THRESHOLDS=[2,3,5,10]

def parquet_rows(path: Path) -> int:
    import pyarrow.parquet as pq

    return int(pq.ParquetFile(path).metadata.num_rows)

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
