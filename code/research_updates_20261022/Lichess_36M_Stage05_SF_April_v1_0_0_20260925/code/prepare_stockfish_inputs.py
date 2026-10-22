#!/usr/bin/env python3
"""Prepare compact, typed Stockfish inputs from Stage-05 extension outputs."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCRIPT_VERSION = "1.0.0"
ALLOWED_MONTHS = ("2026-04",)


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path, block_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(block_size):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def parse_months(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() == "all":
        return ALLOWED_MONTHS
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    if not values or len(values) != len(set(values)):
        raise SystemExit("--months must be a nonempty, duplicate-free list")
    bad = [value for value in values if value not in ALLOWED_MONTHS]
    if bad:
        raise SystemExit(f"unsupported months: {bad}")
    wanted = set(values)
    return tuple(month for month in ALLOWED_MONTHS if month in wanted)


def source_manifest(stage05_root: Path, month: str) -> tuple[Path, Mapping[str, Any], str]:
    month_root = stage05_root / f"month={month}"
    source = month_root / "timeout_opportunities.parquet"
    receipt_path = month_root / "_SUCCESS.json"
    if not source.is_file() or not receipt_path.is_file():
        raise RuntimeError(f"{month}: Stage-05 output or receipt missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("final_ok") is not True or receipt.get("month") != month:
        raise RuntimeError(f"{month}: Stage-05 receipt is not final")
    source_sha = sha256_file(source)
    if source_sha != (receipt.get("output") or {}).get("sha256"):
        raise RuntimeError(f"{month}: Stage-05 output SHA-256 mismatch")
    return source, receipt, source_sha


def build_month(task: Mapping[str, Any]) -> dict[str, Any]:
    import duckdb

    month = str(task["month"])
    source = Path(str(task["source"]))
    source_sha = str(task["source_sha"])
    expected_rows = int(task["expected_rows"])
    output_root = Path(str(task["output_root"]))
    threads = int(task["threads"])
    memory_limit = str(task["memory_limit"])

    output = output_root / f"month={month}.parquet"
    receipt_path = output_root / f"month={month}.SUCCESS.json"
    output_root.mkdir(parents=True, exist_ok=True)

    if output.exists() or receipt_path.exists():
        if not output.is_file() or not receipt_path.is_file():
            raise RuntimeError(f"{month}: incomplete existing Stockfish input checkpoint")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("final_ok") is not True:
            raise RuntimeError(f"{month}: existing Stockfish input receipt is not final")
        if receipt.get("source_sha256") != source_sha:
            raise RuntimeError(f"{month}: existing Stockfish input came from different Stage-05 bytes")
        if receipt.get("output_sha256") != sha256_file(output):
            raise RuntimeError(f"{month}: existing Stockfish input hash mismatch")
        return {**receipt, "run_status": "reused"}

    temporary = output.with_name(output.name + f".partial-{os.getpid()}")
    connection = duckdb.connect(database=":memory:")
    connection.execute(f"SET threads={threads}")
    connection.execute(f"SET memory_limit={sql_string(memory_limit)}")
    try:
        source_sql = f"read_parquet({sql_string(source)}, hive_partitioning=false)"
        columns = {row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM {source_sql}").fetchall()}
        required = {
            "month", "game_id", "site", "chooser_username", "chooser_color",
            "disconnected_username", "disconnected_color", "side_to_move_after_last",
            "fen_after_last_move", "ply_count", "pgn_result", "pgn_termination",
            "api_status", "api_speed", "api_perf", "api_rated", "timeout_draw",
            "outcome_kind_draw", "chooser_has_mating_material", "chooser_elo",
            "disconnected_elo", "disconnected_clock_last_obs_s",
            "chooser_clock_last_obs_s", "tournament_like_event",
        }
        missing = sorted(required - columns)
        if missing:
            raise RuntimeError(f"{month}: Stage-05 columns missing: {missing}")

        connection.execute(
            f"""
            COPY (
              SELECT
                month AS archive_month,
                month,
                game_id,
                site,
                chooser_username AS candidate_chooser,
                chooser_color AS candidate_chooser_color,
                chooser_color AS candidate_chooser_color_norm,
                disconnected_username AS likely_disconnected_player,
                disconnected_color AS likely_disconnected_color,
                side_to_move_after_last,
                fen_after_last_move,
                ply_count,
                pgn_result AS result,
                pgn_termination AS termination,
                api_status,
                api_speed,
                api_perf,
                api_rated,
                timeout_draw,
                outcome_kind_draw,
                chooser_has_mating_material,
                chooser_elo AS candidate_chooser_elo,
                disconnected_elo AS likely_disconnected_elo,
                disconnected_clock_last_obs_s,
                chooser_clock_last_obs_s,
                tournament_like_event
              FROM {source_sql}
            ) TO {sql_string(temporary)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
            """
        )
        output_sql = f"read_parquet({sql_string(temporary)}, hive_partitioning=false)"
        values = connection.execute(
            f"""
            SELECT
              COUNT(*)::BIGINT,
              COUNT(DISTINCT game_id)::BIGINT,
              SUM((month <> {sql_string(month)})::INTEGER)::BIGINT,
              SUM((api_status <> 'timeout')::INTEGER)::BIGINT,
              SUM((fen_after_last_move IS NULL OR trim(fen_after_last_move) = '')::INTEGER)::BIGINT,
              SUM((likely_disconnected_color <> side_to_move_after_last)::INTEGER)::BIGINT
            FROM {output_sql}
            """
        ).fetchone()
        observed = tuple(int(value or 0) for value in values)
        expected = (expected_rows, expected_rows, 0, 0, 0, 0)
        if observed != expected:
            raise RuntimeError(f"{month}: prepared Stockfish input gates failed: observed={observed}, expected={expected}")
        os.replace(temporary, output)
        receipt = {
            "contract": "stockfish100k_stage05_extension_input_v1",
            "script_version": SCRIPT_VERSION,
            "final_ok": True,
            "month": month,
            "rows": expected_rows,
            "unique_game_ids": expected_rows,
            "source_path": str(source),
            "source_sha256": source_sha,
            "output_path": str(output),
            "output_size_bytes": output.stat().st_size,
            "output_sha256": sha256_file(output),
            "compression": "zstd",
            "created_at_utc": utc_now(),
            "run_status": "built",
        }
        atomic_json(receipt_path, receipt)
        return receipt
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare ZSTD Parquet Stockfish inputs from Stage-05 extension outputs.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--months", default="all")
    parser.add_argument("--stage05-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--memory-limit", default="3GB")
    args = parser.parse_args()

    months = parse_months(args.months)
    if not (1 <= args.workers <= 10):
        raise SystemExit("--workers must be between 1 and 10")
    project_root = args.project_root.expanduser().resolve()
    stage05_root = (args.stage05_root or project_root / "derived/replication_36m/timeout_opportunity_extension").expanduser().resolve()
    output_root = (args.output_root or project_root / "derived/replication_36m/stockfish100k_extension_inputs").expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    parallel_months = min(len(months), args.workers)
    threads_per_month = max(1, args.workers // parallel_months)
    tasks = []
    for month in months:
        source, receipt, source_sha = source_manifest(stage05_root, month)
        tasks.append(
            {
                "month": month,
                "source": str(source),
                "source_sha": source_sha,
                "expected_rows": int(receipt["gates"]["rows"]),
                "output_root": str(output_root),
                "threads": threads_per_month,
                "memory_limit": args.memory_limit,
            }
        )

    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=parallel_months) as executor:
        futures = {executor.submit(build_month, task): task["month"] for task in tasks}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    by_month = {row["month"]: row for row in results}
    ordered = [by_month[month] for month in months]

    paths_file = output_root / "sf100k_input_paths_2026-04.txt"
    temporary = paths_file.with_name(paths_file.name + f".partial-{os.getpid()}")
    temporary.write_text("".join(f"{row['output_path']}\n" for row in ordered), encoding="utf-8")
    os.replace(temporary, paths_file)
    summary = {
        "certificate": "LICHESS_36M_SF_INPUTS_2026_04_OK",
        "final_ok": True,
        "script_version": SCRIPT_VERSION,
        "months": list(months),
        "rows": sum(int(row["rows"]) for row in ordered),
        "parallel_month_processes": parallel_months,
        "duckdb_threads_per_process": threads_per_month,
        "worker_budget": args.workers,
        "storage": "typed ZSTD Parquet",
        "paths_file": str(paths_file),
        "outputs": ordered,
        "created_at_utc": utc_now(),
    }
    atomic_json(output_root / "CHECKPOINT_2026-04_SUCCESS.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
