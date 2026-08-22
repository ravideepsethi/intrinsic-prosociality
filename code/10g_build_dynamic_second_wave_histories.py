#!/usr/bin/env python3
"""Build resumable private chronology histories for frozen F2 and E1 analyses.

The 7.76-billion-row canonical chronology is projected once into deterministic
user- and pair-cluster samples. Source-file, event-layer, and identifier-bucket
checkpoints are independently authenticated. No hypothesis coefficient is estimated.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_VERSION = "1.0.1"
PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
EXPECTED_GIT_BASE = "55124c10f746a6de6e5c186c8ddf7796fef5fb2a"
EXPECTED_PLAN_SHA256 = (
    "4f572bb8da7531bfa1b894cfde92da280a936d695bdee72d9bbde6ca4545f039"
)
EXPECTED_SOURCE_AMENDMENT_SHA256 = (
    "79d300c3b1b7b6272b26452c016820b31df8430887fa17a3fc669c69fb92a6bf"
)
EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256 = (
    "1ec12b336344f46a2dc9f4429366bbe526d36202b7949293fac55da32eec9b8b"
)
EXPECTED_FEASIBILITY_SUCCESS_SHA256 = (
    "944380e1f8f8d56ab2bcdb15a2461ac9bf6332e1e6d39d3207511dcc535a34cc"
)
EXPECTED_A3_SUCCESS_SHA256 = (
    "bb6592a31fae8af34a6537e843386d6e5423ea31338be4d1bb4a78b0808e7b4f"
)
EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = (
    "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
)
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_CHRONOLOGY_FILES = 852
EXPECTED_CHRONOLOGY_ROWS = 7_763_847_245
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_STAGE07_FAIR_ROWS = 17_328_130

# Production v1.0.0 selected identifiers with hash(...) % 50 = 0 and then
# partitioned the same hash modulo 16. Because gcd(50, 16) = 2, only even
# bucket numbers can occur. The v1.0.1 recovery treats the mathematically
# impossible odd buckets as typed, zero-row structural checkpoints.
LEGACY_HISTORY_SCRIPT_SHA256 = (
    "668c8f158bcb3c67462b2eb748ed71ca4810fddf16b6dd02caef44f47e910649"
)
LEGACY_HISTORY_PRODUCER_COMMIT = (
    "1418976974e1b7857407f1b2a717a5c11f9c88a1"
)

USER_SEED = 2026082202
PAIR_SEED = 2026082203
SAMPLE_DENOMINATOR = 50
IDENTIFIER_BUCKETS = 16
DAY_MS = 86_400_000
MAIN_START_MS = 1_698_796_800_000
MAIN_END_EXCLUSIVE_MS = 1_761_955_200_000
E1_TRAIN_START_MS = MAIN_START_MS - 395 * DAY_MS
E1_TRAIN_END_EXCLUSIVE_MS = 1_756_684_800_000  # 2025-10-01 minus 30 days
ORDINARY_SPEEDS = ("ultrabullet", "bullet", "blitz", "rapid", "classical")
MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 34)
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--analysis-plan", type=Path)
    parser.add_argument("--source-amendment", type=Path)
    parser.add_argument("--implementation-amendment", type=Path)
    parser.add_argument("--stage07-root", type=Path)
    parser.add_argument("--a3-root", type=Path)
    parser.add_argument("--feasibility-root", type=Path)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--worker-memory", default="3GB")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk_size):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def structurally_empty_bucket(bucket: int) -> bool:
    """Return whether congruence makes this identifier bucket impossible.

    Every retained identifier satisfies H % SAMPLE_DENOMINATOR == 0 and was
    partitioned using the same H % IDENTIFIER_BUCKETS. Therefore its bucket
    must be divisible by gcd(SAMPLE_DENOMINATOR, IDENTIFIER_BUCKETS).
    """

    divisor = math.gcd(SAMPLE_DENOMINATOR, IDENTIFIER_BUCKETS)
    return bucket % divisor != 0


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_tsv(path: Path, rows: Iterable[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(fields), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def command_output(args: Sequence[str], cwd: Path | None = None) -> str:
    return subprocess.run(
        list(args), cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def path_list_literal(paths: Sequence[Path]) -> str:
    return "[" + ",".join(sql_literal(path) for path in paths) + "]"


def authenticate_git(repo: Path, script_path: Path) -> str:
    head = command_output(["git", "rev-parse", "HEAD"], cwd=repo)
    if command_output(["git", "branch", "--show-current"], cwd=repo) != "main":
        raise RuntimeError("History producer requires branch main")
    if command_output(["git", "status", "--porcelain=v1"], cwd=repo):
        raise RuntimeError("History producer requires a clean repository")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", EXPECTED_GIT_BASE, head],
        cwd=repo,
        check=True,
    )
    relative = script_path.resolve().relative_to(repo.resolve()).as_posix()
    subprocess.run(
        ["git", "ls-files", "--error-unmatch", relative],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", relative],
        cwd=repo,
        check=True,
    )
    producer_commit = command_output(
        ["git", "log", "-1", "--format=%H", "--", relative], cwd=repo
    )
    if not producer_commit:
        raise RuntimeError("History producer has no committed Git authority")
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", producer_commit, head],
        cwd=repo,
        check=True,
    )
    return producer_commit


def configure(connection: Any, memory: str, temp: Path, threads: int = 1) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET threads={int(threads)}")
    connection.execute(f"SET memory_limit={sql_literal(memory)}")
    connection.execute(f"SET temp_directory={sql_literal(temp)}")
    connection.execute("SET preserve_insertion_order=false")


def parse_partition(path: str) -> tuple[str | None, str | None]:
    speed = next(
        (part.split("=", 1)[1] for part in Path(path).parts if part.startswith("speed=")),
        None,
    )
    month = next(
        (part.split("=", 1)[1] for part in Path(path).parts if part.startswith("month=")),
        None,
    )
    return speed, month


def read_chronology_manifest(path: Path) -> list[dict[str, Any]]:
    if sha256_file(path) != EXPECTED_CHRONOLOGY_MANIFEST_SHA256:
        raise RuntimeError("Chronology manifest SHA mismatch")
    with path.open(encoding="utf-8", newline="") as stream:
        raw = list(csv.DictReader(stream, delimiter="\t"))
    if len(raw) != EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError("Chronology file count changed")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(raw):
        candidate = Path(row["path"])
        speed, month = parse_partition(row["path"])
        if int(row["file_index"]) != index or not candidate.is_file():
            raise RuntimeError(f"Chronology manifest/path mismatch at {index}")
        if candidate.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Chronology source size mismatch at {index}")
        rows.append(
            {
                "file_index": index,
                "path": str(candidate),
                "bytes": int(row["bytes"]),
                "rows": int(row["rows"]),
                "footer_signature_sha256": row["footer_signature_sha256"],
                "speed": speed,
                "month": month,
            }
        )
    if sum(row["rows"] for row in rows) != EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError("Chronology row total changed")
    ordinary = [row for row in rows if row["speed"] in ORDINARY_SPEEDS]
    if not ordinary:
        raise RuntimeError("No ordinary-speed chronology files were found")
    return ordinary


def stage07_paths(root: Path) -> list[Path]:
    success = root / "_SUCCESS.json"
    if not success.is_file() or sha256_file(success) != EXPECTED_STAGE07_SUCCESS_SHA256:
        raise RuntimeError("Stage 07 success authority mismatch")
    saved = load_json(success)
    if int(saved["global_qa"]["rows"]) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage 07 row authority changed")
    if int(saved["global_qa"]["fair_rows"]) != EXPECTED_STAGE07_FAIR_ROWS:
        raise RuntimeError("Stage 07 fair-row authority changed")
    paths = [root / f"month={month}/analysis_panel.parquet" for month in MAIN_MONTHS]
    if not all(path.is_file() for path in paths):
        raise RuntimeError("Stage 07 monthly input is incomplete")
    return paths


def make_payload(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    project = args.project_root.resolve()
    repo = project / "replication_package"
    plan = (
        args.analysis_plan
        or repo / "docs/dynamic_prosociality_second_wave_analysis_plan.md"
    ).resolve()
    source_amendment = (
        args.source_amendment
        or repo / "docs/dynamic_prosociality_second_wave_source_contract_amendment.md"
    ).resolve()
    implementation = (
        args.implementation_amendment
        or repo / "docs/dynamic_prosociality_second_wave_implementation_amendment.md"
    ).resolve()
    stage07 = (
        args.stage07_root
        or project / "derived/replication/analysis_panel_24m_sf100k"
    ).resolve()
    a3 = (
        args.a3_root
        or project
        / "output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z"
    ).resolve()
    feasibility = (
        args.feasibility_root
        or project / "output/dynamic_second_wave_feasibility_v100/20260822T134125Z"
    ).resolve()
    state = (
        args.state_root
        or project / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    ).resolve()
    output = (
        args.output_root or project / "output/dynamic_second_wave_history_v100"
    ).resolve()
    authorities = {
        "script_sha256": sha256_file(script_path),
        "git_head": authenticate_git(repo, script_path),
        "analysis_plan_sha256": sha256_file(plan),
        "source_amendment_sha256": sha256_file(source_amendment),
        "implementation_amendment_sha256": sha256_file(implementation),
        "feasibility_success_sha256": sha256_file(feasibility / "_SUCCESS.json"),
        "a3_success_sha256": sha256_file(a3 / "_SUCCESS.json"),
        "chronology_manifest_sha256": sha256_file(
            a3 / "chronology_input_manifest.tsv"
        ),
        "stage07_success_sha256": sha256_file(stage07 / "_SUCCESS.json"),
    }
    expected = {
        "analysis_plan_sha256": EXPECTED_PLAN_SHA256,
        "source_amendment_sha256": EXPECTED_SOURCE_AMENDMENT_SHA256,
        "implementation_amendment_sha256": EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256,
        "feasibility_success_sha256": EXPECTED_FEASIBILITY_SUCCESS_SHA256,
        "a3_success_sha256": EXPECTED_A3_SUCCESS_SHA256,
        "chronology_manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
    }
    for key, value in expected.items():
        if authorities[key] != value:
            raise RuntimeError(f"History authority mismatch: {key}")
    config = {
        "script_version": SCRIPT_VERSION,
        **authorities,
        "user_seed": USER_SEED,
        "pair_seed": PAIR_SEED,
        "sample_denominator": SAMPLE_DENOMINATOR,
        "identifier_buckets": IDENTIFIER_BUCKETS,
        "ordinary_speeds": list(ORDINARY_SPEEDS),
        "main_start_ms": MAIN_START_MS,
        "main_end_exclusive_ms": MAIN_END_EXCLUSIVE_MS,
        "e1_train_start_ms": E1_TRAIN_START_MS,
        "e1_train_end_exclusive_ms": E1_TRAIN_END_EXCLUSIVE_MS,
        "duckdb_version": "1.5.2",
    }
    return {
        "project": project,
        "repo": repo,
        "plan": plan,
        "source_amendment": source_amendment,
        "implementation": implementation,
        "stage07": stage07,
        "stage07_paths": stage07_paths(stage07),
        "a3": a3,
        "chronology_manifest": a3 / "chronology_input_manifest.tsv",
        "feasibility": feasibility,
        "state": state,
        "output": output,
        "run_id": args.run_id or default_run_id(),
        "workers": args.workers,
        "worker_memory": args.worker_memory,
        "authorities": authorities,
        "config": config,
        "producer_config_sha256": sha256_json(config),
        "config_sha256": sha256_json(config),
        "state_recovery_mode": "native_v101",
    }


def initialize_state(payload: dict[str, Any]) -> None:
    state = payload["state"]
    state.mkdir(parents=True, exist_ok=True)
    config_path = state / "CONFIG.json"
    if config_path.is_file():
        saved = load_json(config_path)
        saved_config = saved.get("config")
        saved_sha = saved.get("config_sha256")
        if (
            saved.get("status") != "DYNAMIC_SECOND_WAVE_HISTORY_PRIVATE_STATE_OK"
            or not isinstance(saved_config, dict)
            or saved_sha != sha256_json(saved_config)
        ):
            raise RuntimeError("Private history CONFIG.json is not self-authenticating")

        if saved_sha == payload["producer_config_sha256"] and saved_config == payload["config"]:
            print("DYNAMIC_SECOND_WAVE_HISTORY_STATE_AUTHENTICATED_OK", flush=True)
            return

        legacy_config = dict(payload["config"])
        legacy_config.update(
            {
                "script_version": "1.0.0",
                "script_sha256": LEGACY_HISTORY_SCRIPT_SHA256,
                "git_head": LEGACY_HISTORY_PRODUCER_COMMIT,
            }
        )
        legacy_sha = sha256_json(legacy_config)
        if saved_sha != legacy_sha or saved_config != legacy_config:
            raise RuntimeError("Private history state belongs to another configuration")

        # Preserve the authenticated v1.0.0 checkpoint namespace. Existing
        # source, target, and event-layer receipts all bind to this digest;
        # new bucket receipts must use the same digest to form one coherent
        # resumable state. The final aggregate receipt separately records the
        # v1.0.1 producer configuration and recovery mode.
        payload["config_sha256"] = legacy_sha
        payload["state_recovery_mode"] = "authenticated_v100_empty_bucket_recovery"
        print(
            "DYNAMIC_SECOND_WAVE_HISTORY_V100_STATE_RECOVERY_AUTHENTICATED_OK",
            flush=True,
        )
        return
    if any(state.iterdir()):
        raise RuntimeError("Nonempty history state has no CONFIG.json")
    for relative in (
        "selected_games",
        "selected_game_receipts",
        "duckdb_temp/source",
        "duckdb_temp/reductions",
        "user_bucket_receipts",
        "pair_bucket_receipts",
    ):
        (state / relative).mkdir(parents=True, exist_ok=True)
    atomic_json(
        config_path,
        {
            "status": "DYNAMIC_SECOND_WAVE_HISTORY_PRIVATE_STATE_OK",
            "created_utc": utc_now(),
            "config": payload["config"],
            "config_sha256": payload["config_sha256"],
            "privacy": "PRIVATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print("DYNAMIC_SECOND_WAVE_HISTORY_STATE_CREATED", flush=True)


def source_paths(state: Path, index: int) -> tuple[Path, Path]:
    output = state / "selected_games" / f"source_{index:04d}.parquet"
    receipt = state / "selected_game_receipts" / f"source_{index:04d}.json"
    return output, receipt


def authenticate_source_checkpoint(
    row: dict[str, Any], state: Path, config_sha: str
) -> dict[str, Any] | None:
    import pyarrow.parquet as pq

    output, receipt = source_paths(state, row["file_index"])
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial selected-game checkpoint {row['file_index']}")
    saved = load_json(receipt)
    expected = {
        "status": "DYNAMIC_SECOND_WAVE_SELECTED_SOURCE_OK",
        "config_sha256": config_sha,
        "file_index": row["file_index"],
        "input_path": row["path"],
        "input_footer_signature_sha256": row["footer_signature_sha256"],
        "output_path": str(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(
                f"Selected-game checkpoint mismatch {row['file_index']}: {key}"
            )
    return saved


def source_worker(
    row: dict[str, Any], state_text: str, config_sha: str, memory: str
) -> dict[str, Any]:
    import duckdb
    import pyarrow.parquet as pq

    state = Path(state_text)
    output, receipt = source_paths(state, row["file_index"])
    if output.exists() or receipt.exists():
        raise RuntimeError(f"Worker received existing source {row['file_index']}")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}.parquet")
    temp_root = state / "duckdb_temp/source" / f"{row['file_index']:04d}"
    started = time.time()
    connection = duckdb.connect()
    configure(connection, memory, temp_root, threads=1)
    source = sql_literal(row["path"])
    speed = sql_literal(row["speed"])
    query = f"""
      COPY (
        SELECT
          CAST(utc_ms AS BIGINT) AS utc_ms,
          CAST(archive_ordinal AS BIGINT) AS archive_ordinal,
          CAST(game_id AS VARCHAR) AS game_id,
          CAST(white_id AS BIGINT) AS white_id,
          CAST(black_id AS BIGINT) AS black_id,
          CAST(white_elo AS INTEGER) AS white_elo,
          CAST(black_elo AS INTEGER) AS black_elo,
          CAST(white_rating_diff AS INTEGER) AS white_rating_diff,
          CAST(black_rating_diff AS INTEGER) AS black_rating_diff,
          {speed}::VARCHAR AS speed
        FROM read_parquet({source})
        WHERE utc_ms > 0
          AND white_id IS NOT NULL AND black_id IS NOT NULL
          AND CAST(white_id AS BIGINT) > 0 AND CAST(black_id AS BIGINT) > 0
          AND CAST(white_id AS BIGINT) <> CAST(black_id AS BIGINT)
          AND white_elo IS NOT NULL AND black_elo IS NOT NULL
          AND (
            hash(CAST(white_id AS BIGINT), {USER_SEED}) % {SAMPLE_DENOMINATOR} = 0
            OR hash(CAST(black_id AS BIGINT), {USER_SEED}) % {SAMPLE_DENOMINATOR} = 0
            OR hash(
                 LEAST(CAST(white_id AS BIGINT), CAST(black_id AS BIGINT)),
                 GREATEST(CAST(white_id AS BIGINT), CAST(black_id AS BIGINT)),
                 {PAIR_SEED}
               ) % {SAMPLE_DENOMINATOR} = 0
          )
      ) TO {sql_literal(temporary)} (
        FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000
      )
    """
    connection.execute(query)
    connection.close()
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_SECOND_WAVE_SELECTED_SOURCE_OK",
        "created_utc": utc_now(),
        "config_sha256": config_sha,
        "file_index": row["file_index"],
        "input_path": row["path"],
        "input_rows": row["rows"],
        "input_footer_signature_sha256": row["footer_signature_sha256"],
        "speed": row["speed"],
        "month": row["month"],
        "output_path": str(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "runtime_seconds": time.time() - started,
    }
    atomic_json(receipt, saved)
    shutil.rmtree(temp_root, ignore_errors=True)
    return saved


def extract_selected_games(payload: dict[str, Any], rows: list[dict[str, Any]]) -> list[Path]:
    pending = [
        row
        for row in rows
        if authenticate_source_checkpoint(
            row, payload["state"], payload["config_sha256"]
        )
        is None
    ]
    print(
        "SELECTED_GAME_SOURCE_CHECKPOINTS "
        f"existing={len(rows) - len(pending)} pending={len(pending)} "
        f"workers={payload['workers']}",
        flush=True,
    )
    if pending:
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=min(payload["workers"], len(pending)), mp_context=context
        ) as executor:
            futures = {
                executor.submit(
                    source_worker,
                    row,
                    str(payload["state"]),
                    payload["config_sha256"],
                    payload["worker_memory"],
                ): row
                for row in pending
            }
            completed = 0
            for future in as_completed(futures):
                saved = future.result()
                completed += 1
                if completed <= 10 or completed % 25 == 0 or completed == len(pending):
                    print(
                        "SELECTED_GAME_SOURCE_COMPLETE "
                        f"new={completed}/{len(pending)} "
                        f"source={saved['file_index']} rows={saved['output_rows']:,} "
                        f"seconds={saved['runtime_seconds']:.1f}",
                        flush=True,
                    )
    paths: list[Path] = []
    for row in rows:
        authenticate_source_checkpoint(row, payload["state"], payload["config_sha256"])
        paths.append(source_paths(payload["state"], row["file_index"])[0])
    return paths


def directory_manifest(root: Path) -> list[dict[str, Any]]:
    import pyarrow.parquet as pq

    rows = []
    for path in sorted(root.rglob("*.parquet")):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "rows": int(pq.ParquetFile(path).metadata.num_rows),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def authenticate_directory_checkpoint(
    root: Path, receipt: Path, config_sha: str, status: str
) -> dict[str, Any] | None:
    if not root.exists() and not receipt.exists():
        return None
    if not root.is_dir() or not receipt.is_file():
        raise RuntimeError(f"Partial directory checkpoint: {root}")
    saved = load_json(receipt)
    rows = directory_manifest(root)
    if saved.get("status") != status or saved.get("config_sha256") != config_sha:
        raise RuntimeError(f"Directory checkpoint configuration mismatch: {root}")
    if saved.get("file_manifest_sha256") != sha256_json(rows):
        raise RuntimeError(f"Directory checkpoint content mismatch: {root}")
    if saved.get("rows") != sum(row["rows"] for row in rows):
        raise RuntimeError(f"Directory checkpoint row mismatch: {root}")
    return saved


def materialize_event_layers(payload: dict[str, Any], selected: list[Path]) -> tuple[Path, Path]:
    import duckdb

    state = payload["state"]
    sources = path_list_literal(selected)
    specifications = (
        (
            "user",
            state / "user_events",
            state / "user_events_receipt.json",
            "DYNAMIC_SECOND_WAVE_USER_EVENTS_OK",
            f"""
              SELECT
                hash(user_id, {USER_SEED}) % {IDENTIFIER_BUCKETS} AS user_bucket,
                user_id, opponent_id, utc_ms, archive_ordinal, game_id, color_order,
                speed, pre_rating, rating_diff,
                CASE WHEN rating_diff IS NULL THEN NULL ELSE pre_rating + rating_diff END
                  AS post_rating
              FROM (
                SELECT white_id AS user_id, black_id AS opponent_id, utc_ms,
                       archive_ordinal, game_id, 0::TINYINT AS color_order, speed,
                       white_elo AS pre_rating, white_rating_diff AS rating_diff
                FROM read_parquet({sources})
                WHERE hash(white_id, {USER_SEED}) % {SAMPLE_DENOMINATOR} = 0
                UNION ALL
                SELECT black_id AS user_id, white_id AS opponent_id, utc_ms,
                       archive_ordinal, game_id, 1::TINYINT AS color_order, speed,
                       black_elo AS pre_rating, black_rating_diff AS rating_diff
                FROM read_parquet({sources})
                WHERE hash(black_id, {USER_SEED}) % {SAMPLE_DENOMINATOR} = 0
              )
            """,
            "user_bucket",
        ),
        (
            "pair",
            state / "pair_events",
            state / "pair_events_receipt.json",
            "DYNAMIC_SECOND_WAVE_PAIR_EVENTS_OK",
            f"""
              SELECT
                hash(low_id, high_id, {PAIR_SEED}) % {IDENTIFIER_BUCKETS} AS pair_bucket,
                low_id, high_id, utc_ms, archive_ordinal, game_id, speed,
                CAST(FLOOR((white_elo + black_elo) / 2.0) AS INTEGER) AS average_rating
              FROM (
                SELECT LEAST(white_id, black_id) AS low_id,
                       GREATEST(white_id, black_id) AS high_id,
                       utc_ms, archive_ordinal, game_id, speed, white_elo, black_elo
                FROM read_parquet({sources})
              )
              WHERE hash(low_id, high_id, {PAIR_SEED}) % {SAMPLE_DENOMINATOR} = 0
            """,
            "pair_bucket",
        ),
    )
    for label, root, receipt, status, query, partition in specifications:
        if authenticate_directory_checkpoint(
            root, receipt, payload["config_sha256"], status
        ):
            print(f"{label.upper()}_EVENT_LAYER_CHECKPOINT_OK", flush=True)
            continue
        if root.exists() or receipt.exists():
            raise RuntimeError(f"Partial {label} event layer exists")
        temporary = root.with_name(root.name + f".tmp.{uuid.uuid4().hex}")
        temp_root = state / "duckdb_temp/reductions" / label
        connection = duckdb.connect()
        configure(connection, "10GB", temp_root, threads=8)
        print(f"{label.upper()}_EVENT_LAYER_BUILD_BEGIN", flush=True)
        connection.execute(
            f"COPY ({query}) TO {sql_literal(temporary)} "
            f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000, "
            f"PARTITION_BY ({partition}), OVERWRITE_OR_IGNORE)"
        )
        connection.close()
        os.replace(temporary, root)
        rows = directory_manifest(root)
        saved = {
            "status": status,
            "created_utc": utc_now(),
            "config_sha256": payload["config_sha256"],
            "root": str(root),
            "files": len(rows),
            "rows": sum(row["rows"] for row in rows),
            "bytes": sum(row["bytes"] for row in rows),
            "file_manifest_sha256": sha256_json(rows),
        }
        atomic_json(receipt, saved)
        shutil.rmtree(temp_root, ignore_errors=True)
        print(
            f"{label.upper()}_EVENT_LAYER_BUILD_OK rows={saved['rows']:,}",
            flush=True,
        )
    return state / "user_events", state / "pair_events"


def build_stage07_targets(payload: dict[str, Any]) -> Path:
    import duckdb
    import pyarrow.parquet as pq

    state = payload["state"]
    output = state / "stage07_sampled_targets_private.parquet"
    receipt = state / "stage07_sampled_targets_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        if (
            saved.get("config_sha256") != payload["config_sha256"]
            or saved.get("output_sha256") != sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
        ):
            raise RuntimeError("Stage 07 sampled-target checkpoint mismatch")
        print("STAGE07_SAMPLED_TARGETS_CHECKPOINT_OK", flush=True)
        return output
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial Stage 07 sampled-target checkpoint exists")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}.parquet")
    paths = path_list_literal(payload["stage07_paths"])
    connection = duckdb.connect()
    configure(connection, "10GB", state / "duckdb_temp/stage07", threads=8)
    query = f"""
      COPY (
        SELECT
          CAST(game_id AS VARCHAR) AS game_id,
          CAST(archive_ordinal AS BIGINT) AS archive_ordinal,
          CAST(utc_ms AS BIGINT) AS utc_ms,
          CAST(month AS VARCHAR) AS month,
          CAST(chooser_user_id AS BIGINT) AS chooser_user_id,
          CAST(disconnected_user_id AS BIGINT) AS opponent_user_id,
          LEAST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT))
            AS low_id,
          GREATEST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT))
            AS high_id,
          hash(CAST(chooser_user_id AS BIGINT), {USER_SEED})
            % {SAMPLE_DENOMINATOR} = 0 AS user_sample,
          hash(
            LEAST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
            GREATEST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
            {PAIR_SEED}
          ) % {SAMPLE_DENOMINATOR} = 0 AS pair_sample,
          CAST(chooser_elo AS DOUBLE) AS chooser_elo,
          CAST(disconnected_elo AS DOUBLE) AS opponent_elo,
          CAST(chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
          CAST(disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
          CAST(engine_eval_cp_disconnected AS DOUBLE) AS eval_cp,
          CAST(chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
          CAST(chooser_win_premium_v2 AS DOUBLE) AS win_premium,
          CAST(chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock_s,
          CAST(disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock_s,
          CAST(ply_count AS DOUBLE) AS ply_count,
          CAST(material_advantage_chooser AS DOUBLE) AS material_advantage,
          CAST(tc_base_s AS DOUBLE) AS tc_base_s,
          CAST(tc_inc_s AS DOUBLE) AS tc_inc_s,
          CAST(api_speed AS VARCHAR) AS speed,
          CAST(tournament_like_event AS BOOLEAN) AS tournament_like
        FROM read_parquet({paths}, union_by_name=true)
        WHERE CAST(fair_competitive AS BOOLEAN)
          AND chooser_user_id IS NOT NULL AND disconnected_user_id IS NOT NULL
          AND CAST(chooser_user_id AS BIGINT) <> CAST(disconnected_user_id AS BIGINT)
          AND (
            hash(CAST(chooser_user_id AS BIGINT), {USER_SEED})
              % {SAMPLE_DENOMINATOR} = 0
            OR hash(
                 LEAST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
                 GREATEST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
                 {PAIR_SEED}
               ) % {SAMPLE_DENOMINATOR} = 0
          )
      ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
    """
    connection.execute(query)
    connection.close()
    os.replace(temporary, output)
    rows = int(pq.ParquetFile(output).metadata.num_rows)
    saved = {
        "status": "DYNAMIC_SECOND_WAVE_STAGE07_SAMPLED_TARGETS_OK",
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": rows,
        "privacy": "PRIVATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_json(receipt, saved)
    print(f"STAGE07_SAMPLED_TARGETS_BUILD_OK rows={rows:,}", flush=True)
    return output


def user_bucket_worker(
    bucket: int,
    user_root_text: str,
    target_text: str,
    state_text: str,
    config_sha: str,
    memory: str,
) -> dict[str, Any]:
    import duckdb
    import pyarrow.parquet as pq

    state = Path(state_text)
    root = Path(user_root_text)
    target = Path(target_text)
    output = state / "user_history_processed" / f"bucket_{bucket:02d}.parquet"
    receipt = state / "user_bucket_receipts" / f"bucket_{bucket:02d}.json"
    if output.exists() or receipt.exists():
        raise RuntimeError(f"Worker received existing user bucket {bucket}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}.parquet")
    inputs = sorted((root / f"user_bucket={bucket}").glob("*.parquet"))
    structural_empty = not inputs
    input_file_count = len(inputs)
    if structural_empty:
        if not structurally_empty_bucket(bucket):
            raise RuntimeError(f"No user event files for populated bucket {bucket}")
        representatives = sorted(root.glob("user_bucket=*/*.parquet"))
        if not representatives:
            raise RuntimeError("No representative user event file exists")
        inputs = [representatives[0]]
    connection = duckdb.connect()
    configure(connection, memory, state / "duckdb_temp" / f"user_{bucket:02d}", 1)
    sources = path_list_literal(inputs)
    target_sql = sql_literal(target)
    query = f"""
      COPY (
        WITH history AS (
          SELECT
            *,
            LEAD(utc_ms) OVER (
              PARTITION BY user_id
              ORDER BY utc_ms, archive_ordinal, game_id, color_order
            ) AS next_any_utc_ms,
            LEAD(utc_ms) OVER (
              PARTITION BY user_id, speed
              ORDER BY utc_ms, archive_ordinal, game_id, color_order
            ) AS next_same_speed_utc_ms,
            COUNT(*) OVER (
              PARTITION BY user_id, speed
              ORDER BY utc_ms, archive_ordinal, game_id, color_order
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS prior_same_pool_games,
            MIN(utc_ms) OVER (
              PARTITION BY user_id, speed
              ORDER BY utc_ms, archive_ordinal, game_id, color_order
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS first_prior_pool_utc_ms,
            MAX(post_rating) OVER (
              PARTITION BY user_id, speed
              ORDER BY utc_ms, archive_ordinal, game_id, color_order
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS prior_pool_peak
          FROM read_parquet({sources}, union_by_name=true)
        ), marked AS (
          SELECT h.*, t.game_id IS NOT NULL AS is_stage07_target
          FROM history h
          LEFT JOIN read_parquet({target_sql}) t
            ON CAST(t.user_sample AS BOOLEAN)
           AND t.chooser_user_id = h.user_id
           AND t.game_id = h.game_id
        ), eligible AS (
          SELECT *,
            ABS(post_rating - (ROUND(post_rating / 100.0) * 100.0)) <= 20
              AND ROUND(post_rating / 100.0) * 100 BETWEEN 1000 AND 2600
              AS near_round100,
            ABS(post_rating - (ROUND((post_rating - 50) / 100.0) * 100.0 + 50)) <= 20
              AS near_round50,
            ABS(post_rating - (ROUND((post_rating - 37) / 100.0) * 100.0 + 37)) <= 20
              AS near_shift37,
            prior_pool_peak IS NOT NULL AND (
              ABS(post_rating - prior_pool_peak) <= 20
              OR ABS(post_rating - (prior_pool_peak + 37)) <= 20
              OR ABS(post_rating - (prior_pool_peak + 50)) <= 20
            ) AS near_personal_grid
          FROM marked
        )
        SELECT *
        FROM eligible
        WHERE (
          is_stage07_target
          OR (
            utc_ms >= {MAIN_START_MS} AND utc_ms < {MAIN_END_EXCLUSIVE_MS}
            AND rating_diff IS NOT NULL AND rating_diff > 0
            AND post_rating IS NOT NULL
            AND COALESCE(prior_same_pool_games, 0) >= 25
            AND utc_ms - first_prior_pool_utc_ms >= {365 * DAY_MS}
            AND (near_round100 OR near_round50 OR near_shift37 OR near_personal_grid)
          )
        )
        {"AND FALSE" if structural_empty else ""}
      ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
    """
    started = time.time()
    connection.execute(query)
    connection.close()
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_SECOND_WAVE_USER_BUCKET_OK",
        "created_utc": utc_now(),
        "config_sha256": config_sha,
        "bucket": bucket,
        "input_files": input_file_count,
        "structural_empty_bucket": structural_empty,
        "output_path": str(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "runtime_seconds": time.time() - started,
    }
    atomic_json(receipt, saved)
    return saved


def pair_bucket_worker(
    bucket: int,
    pair_root_text: str,
    target_text: str,
    state_text: str,
    config_sha: str,
    memory: str,
) -> dict[str, Any]:
    import duckdb
    import pyarrow.parquet as pq

    state = Path(state_text)
    root = Path(pair_root_text)
    target = Path(target_text)
    output = state / "pair_history_processed" / f"bucket_{bucket:02d}.parquet"
    receipt = state / "pair_bucket_receipts" / f"bucket_{bucket:02d}.json"
    if output.exists() or receipt.exists():
        raise RuntimeError(f"Worker received existing pair bucket {bucket}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}.parquet")
    inputs = sorted((root / f"pair_bucket={bucket}").glob("*.parquet"))
    structural_empty = not inputs
    input_file_count = len(inputs)
    if structural_empty:
        if not structurally_empty_bucket(bucket):
            raise RuntimeError(f"No pair event files for populated bucket {bucket}")
        representatives = sorted(root.glob("pair_bucket=*/*.parquet"))
        if not representatives:
            raise RuntimeError("No representative pair event file exists")
        inputs = [representatives[0]]
    connection = duckdb.connect()
    configure(connection, memory, state / "duckdb_temp" / f"pair_{bucket:02d}", 1)
    sources = path_list_literal(inputs)
    target_sql = sql_literal(target)
    query = f"""
      COPY (
        WITH history AS (
          SELECT
            *,
            LEAD(utc_ms) OVER (
              PARTITION BY low_id, high_id
              ORDER BY utc_ms, archive_ordinal, game_id
            ) AS next_pair_utc_ms,
            ROW_NUMBER() OVER (
              PARTITION BY low_id, high_id
              ORDER BY utc_ms, archive_ordinal, game_id
            ) AS pair_sequence
          FROM read_parquet({sources}, union_by_name=true)
        ), marked AS (
          SELECT h.*, t.game_id IS NOT NULL AS is_stage07_target
          FROM history h
          LEFT JOIN read_parquet({target_sql}) t
            ON CAST(t.pair_sample AS BOOLEAN)
           AND t.low_id = h.low_id AND t.high_id = h.high_id
           AND t.game_id = h.game_id
        )
        SELECT
          *,
          next_pair_utc_ms IS NOT NULL
            AND next_pair_utc_ms > utc_ms
            AND next_pair_utc_ms <= utc_ms + {30 * DAY_MS} AS repeat_within_30d,
          CAST(FLOOR(average_rating / 100.0) * 100 AS INTEGER) AS rating_band_100,
          CAST(FLOOR(average_rating / 200.0) * 200 AS INTEGER) AS rating_band_200,
          CAST(FLOOR(EXTRACT('hour' FROM TO_TIMESTAMP(utc_ms / 1000.0)) / 6) AS INTEGER)
            AS utc_block_6h,
          EXTRACT('isodow' FROM TO_TIMESTAMP(utc_ms / 1000.0)) IN (6, 7)
            AS weekend
        FROM marked
        WHERE (
          is_stage07_target
          OR (utc_ms >= {E1_TRAIN_START_MS} AND utc_ms < {E1_TRAIN_END_EXCLUSIVE_MS})
        )
        {"AND FALSE" if structural_empty else ""}
        ORDER BY utc_ms, low_id, high_id, archive_ordinal, game_id
      ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
    """
    started = time.time()
    connection.execute(query)
    connection.close()
    os.replace(temporary, output)
    saved = {
        "status": "DYNAMIC_SECOND_WAVE_PAIR_BUCKET_OK",
        "created_utc": utc_now(),
        "config_sha256": config_sha,
        "bucket": bucket,
        "input_files": input_file_count,
        "structural_empty_bucket": structural_empty,
        "output_path": str(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
        "runtime_seconds": time.time() - started,
    }
    atomic_json(receipt, saved)
    return saved


def authenticate_bucket(
    state: Path, label: str, bucket: int, config_sha: str
) -> dict[str, Any] | None:
    import pyarrow.parquet as pq

    output = state / f"{label}_history_processed" / f"bucket_{bucket:02d}.parquet"
    receipt = state / f"{label}_bucket_receipts" / f"bucket_{bucket:02d}.json"
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial {label} bucket {bucket}")
    saved = load_json(receipt)
    expected_status = {
        "user": "DYNAMIC_SECOND_WAVE_USER_BUCKET_OK",
        "pair": "DYNAMIC_SECOND_WAVE_PAIR_BUCKET_OK",
    }[label]
    expected = {
        "status": expected_status,
        "config_sha256": config_sha,
        "bucket": bucket,
        "output_path": str(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
        "output_bytes": output.stat().st_size,
        "output_sha256": sha256_file(output),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"{label} bucket mismatch {bucket}: {key}")
    if bool(saved.get("structural_empty_bucket", False)):
        if not structurally_empty_bucket(bucket) or expected["output_rows"] != 0:
            raise RuntimeError(f"Invalid structural-empty {label} bucket {bucket}")
    return saved


def process_buckets(
    payload: dict[str, Any], user_root: Path, pair_root: Path, target: Path
) -> tuple[list[Path], list[Path]]:
    state = payload["state"]
    context = mp.get_context("spawn")
    for label, worker, root in (
        ("user", user_bucket_worker, user_root),
        ("pair", pair_bucket_worker, pair_root),
    ):
        pending = [
            bucket
            for bucket in range(IDENTIFIER_BUCKETS)
            if authenticate_bucket(state, label, bucket, payload["config_sha256"])
            is None
        ]
        print(
            f"{label.upper()}_HISTORY_BUCKETS existing={IDENTIFIER_BUCKETS - len(pending)} "
            f"pending={len(pending)} workers={payload['workers']}",
            flush=True,
        )
        if pending:
            with ProcessPoolExecutor(
                max_workers=min(payload["workers"], len(pending)), mp_context=context
            ) as executor:
                futures = {
                    executor.submit(
                        worker,
                        bucket,
                        str(root),
                        str(target),
                        str(state),
                        payload["config_sha256"],
                        payload["worker_memory"],
                    ): bucket
                    for bucket in pending
                }
                for future in as_completed(futures):
                    saved = future.result()
                    print(
                        f"{label.upper()}_HISTORY_BUCKET_OK bucket={saved['bucket']} "
                        f"rows={saved['output_rows']:,} seconds={saved['runtime_seconds']:.1f}",
                        flush=True,
                    )
        for bucket in range(IDENTIFIER_BUCKETS):
            authenticate_bucket(state, label, bucket, payload["config_sha256"])
    return (
        [
            state / "user_history_processed" / f"bucket_{bucket:02d}.parquet"
            for bucket in range(IDENTIFIER_BUCKETS)
        ],
        [
            state / "pair_history_processed" / f"bucket_{bucket:02d}.parquet"
            for bucket in range(IDENTIFIER_BUCKETS)
        ],
    )


def write_public_receipt(
    payload: dict[str, Any], chronology: list[dict[str, Any]], user: list[Path], pair: list[Path]
) -> Path:
    import pyarrow.parquet as pq

    final = payload["output"] / payload["run_id"]
    if final.exists():
        raise RuntimeError(f"History aggregate run already exists: {final}")
    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    source_receipts = [
        load_json(source_paths(payload["state"], row["file_index"])[1])
        for row in chronology
    ]
    user_rows = sum(int(pq.ParquetFile(path).metadata.num_rows) for path in user)
    pair_rows = sum(int(pq.ParquetFile(path).metadata.num_rows) for path in pair)
    selected_rows = sum(int(row["output_rows"]) for row in source_receipts)
    summary = {
        "status": "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK",
        "created_utc": utc_now(),
        "script_version": SCRIPT_VERSION,
        "authorities": payload["authorities"],
        "config_sha256": payload["producer_config_sha256"],
        "checkpoint_config_sha256": payload["config_sha256"],
        "state_recovery_mode": payload["state_recovery_mode"],
        "ordinary_chronology_files": len(chronology),
        "ordinary_chronology_rows": sum(row["rows"] for row in chronology),
        "selected_game_rows": selected_rows,
        "selected_game_share": selected_rows / sum(row["rows"] for row in chronology),
        "processed_user_rows": user_rows,
        "processed_pair_rows": pair_rows,
        "user_sample_denominator": SAMPLE_DENOMINATOR,
        "pair_sample_denominator": SAMPLE_DENOMINATOR,
        "identifier_buckets": IDENTIFIER_BUCKETS,
        "private_state_root": str(payload["state"]),
        "hypothesis_effect_estimated": False,
        "patron_profile_input_read": False,
        "privacy": "Only aggregate build metadata; histories remain private on XT_Pro.",
    }
    atomic_json(staging / "summary.json", summary)
    manifest = [
        {
            "sha256": sha256_file(staging / "summary.json"),
            "bytes": (staging / "summary.json").stat().st_size,
            "path": "summary.json",
        }
    ]
    write_tsv(staging / "report_file_hashes.tsv", manifest, ("sha256", "bytes", "path"))
    success = {
        "status": "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_sha256": payload["authorities"]["script_sha256"],
        "git_head": payload["authorities"]["git_head"],
        "config_sha256": payload["producer_config_sha256"],
        "checkpoint_config_sha256": payload["config_sha256"],
        "state_recovery_mode": payload["state_recovery_mode"],
        "summary_sha256": sha256_file(staging / "summary.json"),
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "private_target_sha256": sha256_file(
            payload["state"] / "stage07_sampled_targets_private.parquet"
        ),
        "private_user_bucket_bundle_sha256": sha256_json(
            [sha256_file(path) for path in user]
        ),
        "private_pair_bucket_bundle_sha256": sha256_json(
            [sha256_file(path) for path in pair]
        ),
    }
    atomic_json(staging / "_SUCCESS.json", success)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    return final


def execute(payload: dict[str, Any]) -> Path:
    started = time.time()
    initialize_state(payload)
    chronology = read_chronology_manifest(payload["chronology_manifest"])
    selected = extract_selected_games(payload, chronology)
    target = build_stage07_targets(payload)
    user_root, pair_root = materialize_event_layers(payload, selected)
    user, pair = process_buckets(payload, user_root, pair_root, target)
    final = write_public_receipt(payload, chronology, user, pair)
    print(f"DYNAMIC_SECOND_WAVE_HISTORY_V100_OK: {final}", flush=True)
    print(f"runtime_seconds: {time.time() - started:.1f}", flush=True)
    return final


def self_test() -> None:
    import duckdb

    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        WITH x(user_id, low_id, high_id) AS (
          VALUES (1::BIGINT, 1::BIGINT, 2::BIGINT),
                 (2::BIGINT, 1::BIGINT, 3::BIGINT),
                 (3::BIGINT, 2::BIGINT, 3::BIGINT)
        )
        SELECT
          user_id,
          hash(user_id, {USER_SEED}) % {SAMPLE_DENOMINATOR} AS user_mod,
          hash(low_id, high_id, {PAIR_SEED}) % {SAMPLE_DENOMINATOR} AS pair_mod
        FROM x ORDER BY user_id
        """
    ).fetchall()
    assert len(rows) == 3
    assert all(0 <= row[1] < SAMPLE_DENOMINATOR for row in rows)
    assert all(0 <= row[2] < SAMPLE_DENOMINATOR for row in rows)
    assert math.gcd(SAMPLE_DENOMINATOR, IDENTIFIER_BUCKETS) == 2
    assert all(structurally_empty_bucket(bucket) == (bucket % 2 == 1) for bucket in range(16))
    assert parse_partition("/x/speed=blitz/month=2024-01/a.parquet") == (
        "blitz",
        "2024-01",
    )
    assert E1_TRAIN_START_MS < MAIN_START_MS < MAIN_END_EXCLUSIVE_MS
    print("DYNAMIC_SECOND_WAVE_HISTORY_V100_SELF_TEST_OK")


def print_plan(payload: dict[str, Any]) -> None:
    print("DYNAMIC_SECOND_WAVE_HISTORY_V100_PLAN_OK")
    print("script_version:", SCRIPT_VERSION)
    print("script_sha256:", payload["authorities"]["script_sha256"])
    print("git_head:", payload["authorities"]["git_head"])
    print("analysis_plan_sha256:", payload["authorities"]["analysis_plan_sha256"])
    print(
        "implementation_amendment_sha256:",
        payload["authorities"]["implementation_amendment_sha256"],
    )
    print("chronology_rows:", f"{EXPECTED_CHRONOLOGY_ROWS:,}")
    print("sample_denominator:", SAMPLE_DENOMINATOR)
    print("identifier_buckets:", IDENTIFIER_BUCKETS)
    print("source_workers:", payload["workers"])
    print("worker_memory:", payload["worker_memory"])
    print("private_state:", payload["state"])
    print("aggregate_output:", payload["output"])
    print("resumability: source-file, event-layer, user-bucket, and pair-bucket")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return
    if not 1 <= args.workers <= 8:
        raise SystemExit("--workers must be between 1 and 8")
    payload = make_payload(args, Path(__file__).resolve())
    print_plan(payload)
    if not args.execute:
        print("No chronology row was read. Re-run with --execute.")
        return
    execute(payload)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"DYNAMIC_SECOND_WAVE_HISTORY_FAIL_CLOSED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
