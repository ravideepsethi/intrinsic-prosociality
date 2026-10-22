#!/usr/bin/env python3
"""Audit the completed extension run and collect compact result evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"required JSON missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    args = parser.parse_args()

    project = args.project_root.expanduser().resolve()
    result = args.result_root.expanduser().resolve()
    result.mkdir(parents=True, exist_ok=True)

    stage05 = project / "derived/replication_36m/timeout_opportunity_extension/_manifests/CHECKPOINT_2026-04_SUCCESS.json"
    sf_inputs = project / "derived/replication_36m/stockfish100k_extension_inputs/CHECKPOINT_2026-04_SUCCESS.json"
    sf_root = project / "derived/replication_36m/stockfish100k_extension_new_api_2026_04"
    sf_summary = sf_root / "summary.json"
    plan_path = sf_root / "plan_manifest.json"

    stage05_data = read_json(stage05)
    input_data = read_json(sf_inputs)
    summary_data = read_json(sf_summary)
    plan_data = read_json(plan_path)
    if stage05_data.get("final_ok") is not True:
        raise RuntimeError("Stage-05 checkpoint is not final")
    if input_data.get("final_ok") is not True:
        raise RuntimeError("Stockfish input checkpoint is not final")
    if stage05_data.get("months") != ["2026-04"]:
        raise RuntimeError("Stage-05 checkpoint does not certify April alone")
    if input_data.get("months") != ["2026-04"]:
        raise RuntimeError("Stockfish input checkpoint does not certify April alone")
    if plan_data.get("months") != ["2026-04"]:
        raise RuntimeError("Stockfish plan does not select April alone")
    if int(plan_data.get("nodes", -1)) != 100_000:
        raise RuntimeError("Stockfish plan does not request exactly 100,000 nodes")
    if int(plan_data.get("threads_per_engine", -1)) != 1:
        raise RuntimeError("Stockfish plan does not use one thread per engine")
    if int(plan_data.get("hash_mb", -1)) != 64:
        raise RuntimeError("Stockfish plan does not use 64 MiB hash per engine")
    stockfish = plan_data.get("stockfish") or {}
    if "Stockfish 18" not in str(stockfish.get("stockfish_name", "")):
        raise RuntimeError("Stockfish plan does not identify Stockfish 18")
    if int(input_data.get("rows", -1)) != int(stage05_data.get("total_timeout_opportunities", -2)):
        raise RuntimeError("Stage-05 and Stockfish input row totals differ")
    expected = int(summary_data.get("total_expected_rows", -1))
    done = int(summary_data.get("total_done_rows", -1))
    errors = int(summary_data.get("total_error_rows", -1))
    invalid = summary_data.get("invalid_parts") or []
    if expected <= 0 or done != expected or errors != 0 or invalid:
        raise RuntimeError(
            f"Stockfish is not complete: expected={expected}, done={done}, errors={errors}, invalid_parts={len(invalid)}"
        )
    if expected != int(input_data["rows"]):
        raise RuntimeError("Stockfish plan and prepared-input row totals differ")
    if int(plan_data.get("total_rows", -1)) != expected:
        raise RuntimeError("Stockfish plan row total differs from completed summary")
    selected = plan_data.get("selected_inputs") or []
    outputs = input_data.get("outputs") or []
    if len(selected) != 1 or len(outputs) != 1:
        raise RuntimeError("April plan/input checkpoints must each contain one month")
    if selected[0].get("file_sha256") != outputs[0].get("output_sha256"):
        raise RuntimeError("Stockfish plan input hash differs from prepared April input")

    path_list = sf_root / "sf100k_parquet_paths.txt"
    part_paths = [Path(line.strip()) for line in path_list.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(part_paths) != len(set(part_paths)):
        raise RuntimeError("Stockfish path list contains duplicate parts")
    expected_parts = math.ceil(expected / int(plan_data.get("part_rows", 100_000)))
    if len(part_paths) != expected_parts:
        raise RuntimeError(f"Stockfish part count {len(part_paths)} != expected {expected_parts}")
    if any("month=2026-04" not in str(path) for path in part_paths):
        raise RuntimeError("Stockfish path list contains a non-April part")
    verified_rows = 0
    for part in part_paths:
        receipt_path = part.with_name(part.stem + ".done.json")
        receipt = read_json(receipt_path)
        if receipt.get("final_ok") is not True or int(receipt.get("error_rows", -1)) != 0:
            raise RuntimeError(f"uncertified Stockfish part: {part}")
        if int(receipt.get("part_size_bytes", -1)) != part.stat().st_size:
            raise RuntimeError(f"Stockfish part size mismatch: {part}")
        if receipt.get("part_sha256") != sha256_file(part):
            raise RuntimeError(f"Stockfish part SHA-256 mismatch: {part}")
        footer_rows = int(pq.ParquetFile(part).metadata.num_rows)
        if footer_rows != int(receipt.get("rows", -1)):
            raise RuntimeError(f"Stockfish part footer row mismatch: {part}")
        verified_rows += footer_rows
    if verified_rows != expected:
        raise RuntimeError(f"verified Stockfish part rows {verified_rows} != expected {expected}")

    sources = [
        stage05,
        sf_inputs,
        plan_path,
        sf_root / "pilot/pilot_summary.json",
        sf_summary,
        sf_root / "month_status.csv",
        sf_root / "sf100k_parquet_paths.txt",
        sf_root / "command_plan.json",
        sf_root / "command_pilot.json",
        sf_root / "command_production.json",
        sf_root / "command_summarize.json",
    ]
    copied = []
    for source in sources:
        if not source.is_file():
            raise RuntimeError(f"required result evidence missing: {source}")
        destination = result / source.name
        if destination.exists():
            destination = result / f"{source.parent.name}_{source.name}"
        shutil.copy2(source, destination)
        copied.append(
            {
                "source_path": str(source),
                "result_path": str(destination),
                "size_bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
            }
        )

    certificate = {
        "certificate": "LICHESS_36M_STAGE05_SF_APRIL_OK",
        "final_ok": True,
        "scope": "2026-04",
        "months": stage05_data["months"],
        "stage05_timeout_opportunities": int(stage05_data["total_timeout_opportunities"]),
        "stockfish_positions_expected": expected,
        "stockfish_positions_completed": done,
        "stockfish_error_rows": errors,
        "stockfish_parts_verified": len(part_paths),
        "stockfish_part_hashes_verified": True,
        "nodes_per_position": 100_000,
        "stockfish_name": stockfish["stockfish_name"],
        "stockfish_sha256": stockfish["stockfish_sha256"],
        "workers": int(plan_data["workers"]),
        "threads_per_engine": int(plan_data["threads_per_engine"]),
        "hash_mb_per_engine": int(plan_data["hash_mb"]),
        "storage": "typed ZSTD Parquet",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence": copied,
    }
    (result / "_SUCCESS.json").write_text(json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(certificate, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
