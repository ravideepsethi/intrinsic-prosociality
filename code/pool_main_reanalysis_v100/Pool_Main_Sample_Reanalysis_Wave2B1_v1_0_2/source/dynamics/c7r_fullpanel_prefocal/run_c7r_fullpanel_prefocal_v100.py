#!/usr/bin/env python3
"""
Full-panel C7R pre-focal rated-meeting census.

Purpose
-------
Replace the historical deterministic 1-in-50 focal-pair sample used for the
C7R first-versus-repeat robustness exercise with all 47,587,020 certified
Stage-07 opportunities, while preserving the original pre-focal definition:

    first rated meeting = no earlier rated meeting for the unordered pair
    in the authenticated 2013+ ordinary-speed chronology.

Pair ordering is lexicographic in (utc_ms, archive_ordinal, game_id), matching
the historical C7R pair-sequence authority.

The expensive history pass is outcome-blind. Stage-07 kindness outcomes are
joined only after the first/repeat support is frozen and receipted.

This program is append-only. It does not modify Stage 07, the canonical
chronology, the old 2% pair-history layer, C7R v1.0.2, or the manuscript.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable, Sequence

SCRIPT_VERSION = "1.0.0"
STATUS = "C7R_FULLPANEL_PREFOCAL_V100_OK"

PROJECT_ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
DESKTOP_ROOT = Path("/Users/u6025368/Desktop/Lichess_Desktop")

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

ORDINARY_SPEEDS = ("ultrabullet", "bullet", "blitz", "rapid", "classical")
MAIN_MONTHS = tuple(
    f"{absolute // 12:04d}-{absolute % 12 + 1:02d}"
    for absolute in range(2023 * 12 + 10, 2023 * 12 + 34)
)
LAST_FOCAL_MONTH = "2025-10"

# Historical sampled C7R benchmark, used only for comparison in the report.
OLD_SAMPLE_N = 951_517
OLD_FIRST_N = 831_622
OLD_REPEAT_N = 119_895
OLD_REPEAT_SHARE = 0.126004
OLD_FAIR_FIRST_RATE_PCT = 2.8431
OLD_FAIR_REPEAT_RATE_PCT = 2.8602
OLD_FIRST_GRADIENT_PP = 1.5669
OLD_REPEAT_GRADIENT_PP = 1.3342
OLD_INTERACTION_PP = -0.0087
OLD_INTERACTION_P = 0.938


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    p.add_argument("--desktop-root", type=Path, default=DESKTOP_ROOT)
    p.add_argument("--state-root", type=Path)
    p.add_argument("--output-root", type=Path)
    p.add_argument("--run-id")
    p.add_argument("--threads", type=int, default=10)
    p.add_argument("--memory", default="11GB")
    p.add_argument("--shards", type=int, default=8)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p.parse_args(argv)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run_id_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            d.update(b)
    return d.hexdigest()


def canonical_json(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"))


def sha256_json(x: Any) -> str:
    return hashlib.sha256(canonical_json(x).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_json(path: Path, obj: Any) -> None:
    atomic_text(path, json.dumps(obj, indent=2, sort_keys=True) + "\n")


def sql_literal(x: str | Path) -> str:
    return "'" + str(x).replace("'", "''") + "'"


def path_list_literal(paths: Sequence[Path]) -> str:
    return "[" + ",".join(sql_literal(p) for p in paths) + "]"


def parse_partition(path: str) -> tuple[str | None, str | None]:
    parts = Path(path).parts
    speed = next((z.split("=", 1)[1] for z in parts if z.startswith("speed=")), None)
    month = next((z.split("=", 1)[1] for z in parts if z.startswith("month=")), None)
    return speed, month


def configure(con: Any, memory: str, temp_dir: Path, threads: int) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET memory_limit={sql_literal(memory)}")
    con.execute(f"SET temp_directory={sql_literal(temp_dir)}")
    con.execute("SET preserve_insertion_order=false")
    try:
        con.execute("SET enable_progress_bar=true")
    except Exception:
        pass


def parquet_rows(path: Path) -> int:
    import pyarrow.parquet as pq
    return int(pq.ParquetFile(path).metadata.num_rows)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    os.replace(tmp, path)


def read_chronology_manifest(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.is_file():
        raise RuntimeError(f"Chronology manifest missing: {path}")
    if sha256_file(path) != EXPECTED_CHRONOLOGY_MANIFEST_SHA256:
        raise RuntimeError("Chronology manifest SHA-256 mismatch")
    with path.open(encoding="utf-8", newline="") as f:
        raw = list(csv.DictReader(f, delimiter="\t"))
    if len(raw) != EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError(
            f"Chronology file count changed: {len(raw)} != {EXPECTED_CHRONOLOGY_FILES}"
        )
    rows: list[dict[str, Any]] = []
    for idx, row in enumerate(raw):
        if int(row["file_index"]) != idx:
            raise RuntimeError(f"Chronology file_index mismatch at {idx}")
        candidate = Path(row["path"])
        if not candidate.is_file():
            raise RuntimeError(f"Chronology source missing: {candidate}")
        if candidate.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Chronology source byte-size mismatch: {candidate}")
        speed, month = parse_partition(row["path"])
        rows.append(
            {
                "file_index": idx,
                "path": candidate,
                "rows": int(row["rows"]),
                "bytes": int(row["bytes"]),
                "footer_signature_sha256": row.get("footer_signature_sha256", ""),
                "speed": speed,
                "month": month,
            }
        )
    if sum(r["rows"] for r in rows) != EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError("Chronology row total changed")
    ordinary = [
        r for r in rows
        if r["speed"] in ORDINARY_SPEEDS
        and r["month"] is not None
        and r["month"] <= LAST_FOCAL_MONTH
    ]
    if not ordinary:
        raise RuntimeError("No ordinary-speed chronology files through 2025-10")
    return rows, ordinary


def stage07_paths(root: Path) -> list[Path]:
    success = root / "_SUCCESS.json"
    if not success.is_file():
        raise RuntimeError(f"Stage-07 success receipt missing: {success}")
    if sha256_file(success) != EXPECTED_STAGE07_SUCCESS_SHA256:
        raise RuntimeError("Stage-07 success receipt SHA-256 mismatch")
    saved = load_json(success)
    if int(saved["global_qa"]["rows"]) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Stage-07 row authority changed")
    if int(saved["global_qa"]["fair_rows"]) != EXPECTED_STAGE07_FAIR_ROWS:
        raise RuntimeError("Stage-07 fair-row authority changed")
    paths = [root / f"month={m}/analysis_panel.parquet" for m in MAIN_MONTHS]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        raise RuntimeError(f"Stage-07 monthly panel incomplete; first missing={missing[0]}")
    return paths


def balanced_shards(rows: list[dict[str, Any]], n: int) -> list[list[dict[str, Any]]]:
    """Greedy row-balanced sharding. Ordering is irrelevant because each shard emits local minima."""
    n = max(1, min(int(n), len(rows)))
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(n)]
    loads = [0] * n
    for row in sorted(rows, key=lambda z: (z["rows"], z["file_index"]), reverse=True):
        j = min(range(n), key=lambda k: loads[k])
        buckets[j].append(row)
        loads[j] += int(row["rows"])
    for b in buckets:
        b.sort(key=lambda z: z["file_index"])
    return buckets


def checkpoint_ok(path: Path, receipt: Path, config_sha: str, status: str) -> dict[str, Any] | None:
    if not path.exists() and not receipt.exists():
        return None
    if not path.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial checkpoint: {path}")
    saved = load_json(receipt)
    expected = {
        "status": status,
        "config_sha256": config_sha,
        "output_path": str(path),
        "rows": parquet_rows(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    for k, v in expected.items():
        if saved.get(k) != v:
            raise RuntimeError(f"Checkpoint mismatch {path.name}: {k}")
    return saved


def make_payload(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project_root.resolve()
    stage07_root = project / "derived/replication/analysis_panel_24m_sf100k"
    a3_root = (
        project
        / "output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z"
    )
    manifest = a3_root / "chronology_input_manifest.tsv"
    stage_paths = stage07_paths(stage07_root)
    all_chr, ordinary_chr = read_chronology_manifest(manifest)
    state = (
        args.state_root
        or project / "derived/replication/c7r_fullpanel_prefocal_v100_PRIVATE"
    ).resolve()
    out_parent = (
        args.output_root
        or project / "output/c7r_fullpanel_prefocal_v100"
    ).resolve()
    run_id = args.run_id or run_id_now()
    shards = balanced_shards(ordinary_chr, args.shards)
    config = {
        "script_version": SCRIPT_VERSION,
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "chronology_manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
        "chronology_files_all": len(all_chr),
        "chronology_rows_all": sum(r["rows"] for r in all_chr),
        "chronology_files_scanned": len(ordinary_chr),
        "chronology_rows_scanned_manifest": sum(r["rows"] for r in ordinary_chr),
        "ordinary_speeds": list(ORDINARY_SPEEDS),
        "latest_chronology_partition_scanned": LAST_FOCAL_MONTH,
        "stage07_rows": EXPECTED_STAGE07_ROWS,
        "stage07_fair_rows": EXPECTED_STAGE07_FAIR_ROWS,
        "ordering": ["utc_ms", "archive_ordinal", "game_id"],
        "threads": int(args.threads),
        "memory": args.memory,
        "shards": len(shards),
        "shard_file_indices": [[r["file_index"] for r in s] for s in shards],
    }
    return {
        "project": project,
        "stage07_root": stage07_root,
        "stage07_paths": stage_paths,
        "a3_root": a3_root,
        "manifest": manifest,
        "all_chronology": all_chr,
        "chronology": ordinary_chr,
        "shards": shards,
        "state": state,
        "output_parent": out_parent,
        "run_id": run_id,
        "threads": int(args.threads),
        "memory": args.memory,
        "desktop": args.desktop_root.resolve(),
        "config": config,
        "config_sha256": sha256_json(config),
    }


def initialize_state(payload: dict[str, Any]) -> None:
    state = payload["state"]
    state.mkdir(parents=True, exist_ok=True)
    cfg = state / "CONFIG.json"
    if cfg.is_file():
        saved = load_json(cfg)
        if saved.get("status") != "C7R_FULLPANEL_PREFOCAL_PRIVATE_STATE_OK":
            raise RuntimeError("Private state status mismatch")
        if saved.get("config_sha256") != payload["config_sha256"]:
            raise RuntimeError(
                "Existing private state belongs to another configuration. "
                "Do not overwrite it; use a new --state-root."
            )
        if saved.get("config") != payload["config"]:
            raise RuntimeError("Private state config content mismatch")
        print("C7R_FULLPANEL_PRIVATE_STATE_AUTHENTICATED_OK", flush=True)
        return
    if any(state.iterdir()):
        raise RuntimeError("Nonempty private state has no CONFIG.json; fail closed")
    atomic_json(
        cfg,
        {
            "status": "C7R_FULLPANEL_PREFOCAL_PRIVATE_STATE_OK",
            "created_utc": utc_now(),
            "config_sha256": payload["config_sha256"],
            "config": payload["config"],
            "privacy": "Identifier-bearing row-level state; never transfer or publish.",
        },
    )
    for name in ("shard_first_events", "shard_receipts", "duckdb_temp", "model_groups"):
        (state / name).mkdir(parents=True, exist_ok=True)


def build_focal_support(payload: dict[str, Any]) -> tuple[Path, Path]:
    import duckdb

    state = payload["state"]
    paths = path_list_literal(payload["stage07_paths"])
    temp = state / "duckdb_temp/focal"
    support = state / "stage07_focal_support_private.parquet"
    support_receipt = state / "stage07_focal_support_receipt.json"
    pairs = state / "stage07_focal_pairs_private.parquet"
    pairs_receipt = state / "stage07_focal_pairs_receipt.json"

    got = checkpoint_ok(
        support, support_receipt, payload["config_sha256"], "C7R_FULLPANEL_FOCAL_SUPPORT_OK"
    )
    if got is None:
        con = duckdb.connect()
        configure(con, payload["memory"], temp, payload["threads"])
        tmp = support.with_name(support.name + f".tmp.{uuid.uuid4().hex}")
        print("C7R_FULLPANEL_FOCAL_SUPPORT_BUILD_BEGIN", flush=True)
        con.execute(
            f"""
            COPY (
              SELECT
                CAST(game_id AS VARCHAR) AS game_id,
                CAST(utc_ms AS BIGINT) AS utc_ms,
                CAST(archive_ordinal AS BIGINT) AS archive_ordinal,
                LEAST(CAST(white_id AS BIGINT), CAST(black_id AS BIGINT)) AS low_id,
                GREATEST(CAST(white_id AS BIGINT), CAST(black_id AS BIGINT)) AS high_id,
                CAST(chooser_user_id AS BIGINT) AS chooser_user_id
              FROM read_parquet({paths})
              WHERE game_id IS NOT NULL
                AND utc_ms IS NOT NULL AND utc_ms > 0
                AND archive_ordinal IS NOT NULL
                AND white_id IS NOT NULL AND black_id IS NOT NULL
                AND CAST(white_id AS BIGINT) > 0
                AND CAST(black_id AS BIGINT) > 0
                AND CAST(white_id AS BIGINT) <> CAST(black_id AS BIGINT)
                AND chooser_user_id IS NOT NULL
            ) TO {sql_literal(tmp)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        qa = con.execute(
            f"""
            SELECT
              COUNT(*)::BIGINT,
              COUNT(DISTINCT game_id)::BIGINT,
              COUNT(*) FILTER (WHERE low_id >= high_id)::BIGINT
            FROM read_parquet({sql_literal(tmp)})
            """
        ).fetchone()
        con.close()
        if int(qa[0]) != EXPECTED_STAGE07_ROWS or int(qa[1]) != EXPECTED_STAGE07_ROWS:
            raise RuntimeError(f"Focal support row/uniqueness gate failed: {qa}")
        if int(qa[2]) != 0:
            raise RuntimeError("Invalid unordered pair ids in focal support")
        os.replace(tmp, support)
        saved = {
            "status": "C7R_FULLPANEL_FOCAL_SUPPORT_OK",
            "created_utc": utc_now(),
            "config_sha256": payload["config_sha256"],
            "output_path": str(support),
            "rows": parquet_rows(support),
            "bytes": support.stat().st_size,
            "sha256": sha256_file(support),
            "outcome_read": False,
        }
        atomic_json(support_receipt, saved)
        shutil.rmtree(temp, ignore_errors=True)
        print(f"C7R_FULLPANEL_FOCAL_SUPPORT_BUILD_OK rows={saved['rows']:,}", flush=True)

    got_pairs = checkpoint_ok(
        pairs, pairs_receipt, payload["config_sha256"], "C7R_FULLPANEL_FOCAL_PAIRS_OK"
    )
    if got_pairs is None:
        con = duckdb.connect()
        configure(con, payload["memory"], temp, payload["threads"])
        tmp = pairs.with_name(pairs.name + f".tmp.{uuid.uuid4().hex}")
        print("C7R_FULLPANEL_FOCAL_PAIR_SET_BUILD_BEGIN", flush=True)
        con.execute(
            f"""
            COPY (
              SELECT DISTINCT low_id, high_id
              FROM read_parquet({sql_literal(support)})
            ) TO {sql_literal(tmp)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        con.close()
        os.replace(tmp, pairs)
        saved = {
            "status": "C7R_FULLPANEL_FOCAL_PAIRS_OK",
            "created_utc": utc_now(),
            "config_sha256": payload["config_sha256"],
            "output_path": str(pairs),
            "rows": parquet_rows(pairs),
            "bytes": pairs.stat().st_size,
            "sha256": sha256_file(pairs),
            "outcome_read": False,
        }
        atomic_json(pairs_receipt, saved)
        shutil.rmtree(temp, ignore_errors=True)
        print(f"C7R_FULLPANEL_FOCAL_PAIR_SET_BUILD_OK pairs={saved['rows']:,}", flush=True)
    return support, pairs


def build_shard_minima(payload: dict[str, Any], focal_pairs: Path) -> list[Path]:
    import duckdb

    state = payload["state"]
    outputs: list[Path] = []
    total = len(payload["shards"])
    for idx, shard in enumerate(payload["shards"]):
        output = state / "shard_first_events" / f"shard_{idx:02d}.parquet"
        receipt = state / "shard_receipts" / f"shard_{idx:02d}.json"
        status = "C7R_FULLPANEL_SHARD_FIRST_EVENT_OK"
        existing = checkpoint_ok(output, receipt, payload["config_sha256"], status)
        if existing is not None:
            print(
                f"C7R_FULLPANEL_SHARD_CHECKPOINT_OK shard={idx+1}/{total} "
                f"pairs={existing['rows']:,}",
                flush=True,
            )
            outputs.append(output)
            continue

        source_paths = [r["path"] for r in shard]
        source_rows = sum(int(r["rows"]) for r in shard)
        temp = state / "duckdb_temp" / f"shard_{idx:02d}"
        shutil.rmtree(temp, ignore_errors=True)
        con = duckdb.connect()
        configure(con, payload["memory"], temp, payload["threads"])
        tmp = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
        started = time.time()
        print(
            f"C7R_FULLPANEL_SHARD_BEGIN shard={idx+1}/{total} "
            f"files={len(shard)} manifest_rows={source_rows:,}",
            flush=True,
        )
        src = path_list_literal(source_paths)
        pair_path = sql_literal(focal_pairs)
        con.execute(
            f"""
            COPY (
              WITH matched AS MATERIALIZED (
                SELECT
                  f.low_id,
                  f.high_id,
                  CAST(c.utc_ms AS BIGINT) AS utc_ms,
                  CAST(c.archive_ordinal AS BIGINT) AS archive_ordinal,
                  CAST(c.game_id AS VARCHAR) AS game_id
                FROM read_parquet({src}) AS c
                INNER JOIN read_parquet({pair_path}) AS f
                  ON f.low_id = LEAST(CAST(c.white_id AS BIGINT), CAST(c.black_id AS BIGINT))
                 AND f.high_id = GREATEST(CAST(c.white_id AS BIGINT), CAST(c.black_id AS BIGINT))
                WHERE c.utc_ms IS NOT NULL AND CAST(c.utc_ms AS BIGINT) > 0
                  AND c.archive_ordinal IS NOT NULL
                  AND c.game_id IS NOT NULL
                  AND c.white_id IS NOT NULL AND c.black_id IS NOT NULL
                  AND CAST(c.white_id AS BIGINT) > 0
                  AND CAST(c.black_id AS BIGINT) > 0
                  AND CAST(c.white_id AS BIGINT) <> CAST(c.black_id AS BIGINT)
              ),
              t0 AS (
                SELECT low_id, high_id, MIN(utc_ms)::BIGINT AS first_utc_ms
                FROM matched
                GROUP BY low_id, high_id
              ),
              t1 AS (
                SELECT
                  m.low_id, m.high_id, t.first_utc_ms,
                  MIN(m.archive_ordinal)::BIGINT AS first_archive_ordinal
                FROM matched m
                INNER JOIN t0 t
                  ON m.low_id=t.low_id AND m.high_id=t.high_id
                 AND m.utc_ms=t.first_utc_ms
                GROUP BY m.low_id, m.high_id, t.first_utc_ms
              )
              SELECT
                m.low_id,
                m.high_id,
                t.first_utc_ms,
                t.first_archive_ordinal,
                MIN(m.game_id)::VARCHAR AS first_game_id
              FROM matched m
              INNER JOIN t1 t
                ON m.low_id=t.low_id AND m.high_id=t.high_id
               AND m.utc_ms=t.first_utc_ms
               AND m.archive_ordinal=t.first_archive_ordinal
              GROUP BY
                m.low_id, m.high_id, t.first_utc_ms, t.first_archive_ordinal
            ) TO {sql_literal(tmp)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        con.close()
        os.replace(tmp, output)
        elapsed = time.time() - started
        saved = {
            "status": status,
            "created_utc": utc_now(),
            "config_sha256": payload["config_sha256"],
            "shard_index": idx,
            "shard_count": total,
            "source_file_indices": [r["file_index"] for r in shard],
            "source_files": len(shard),
            "source_manifest_rows": source_rows,
            "output_path": str(output),
            "rows": parquet_rows(output),
            "bytes": output.stat().st_size,
            "sha256": sha256_file(output),
            "runtime_seconds": elapsed,
            "outcome_read": False,
        }
        atomic_json(receipt, saved)
        shutil.rmtree(temp, ignore_errors=True)
        outputs.append(output)
        print(
            f"C7R_FULLPANEL_SHARD_OK shard={idx+1}/{total} "
            f"pairs={saved['rows']:,} seconds={elapsed:.1f}",
            flush=True,
        )
    return outputs


def merge_global_minima(payload: dict[str, Any], shard_paths: list[Path], focal_pairs: Path) -> Path:
    import duckdb

    state = payload["state"]
    output = state / "pair_first_rated_event_private.parquet"
    receipt = state / "pair_first_rated_event_receipt.json"
    status = "C7R_FULLPANEL_PAIR_FIRST_EVENT_OK"
    existing = checkpoint_ok(output, receipt, payload["config_sha256"], status)
    if existing is not None:
        print(f"C7R_FULLPANEL_GLOBAL_MIN_CHECKPOINT_OK pairs={existing['rows']:,}", flush=True)
        return output

    temp = state / "duckdb_temp/global_min"
    con = duckdb.connect()
    configure(con, payload["memory"], temp, payload["threads"])
    tmp = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    src = path_list_literal(shard_paths)
    print("C7R_FULLPANEL_GLOBAL_MIN_BUILD_BEGIN", flush=True)
    con.execute(
        f"""
        COPY (
          WITH local AS MATERIALIZED (
            SELECT * FROM read_parquet({src})
          ),
          t0 AS (
            SELECT low_id, high_id, MIN(first_utc_ms)::BIGINT AS first_utc_ms
            FROM local GROUP BY low_id, high_id
          ),
          t1 AS (
            SELECT
              l.low_id, l.high_id, t.first_utc_ms,
              MIN(l.first_archive_ordinal)::BIGINT AS first_archive_ordinal
            FROM local l
            INNER JOIN t0 t
              ON l.low_id=t.low_id AND l.high_id=t.high_id
             AND l.first_utc_ms=t.first_utc_ms
            GROUP BY l.low_id,l.high_id,t.first_utc_ms
          )
          SELECT
            l.low_id,
            l.high_id,
            t.first_utc_ms,
            t.first_archive_ordinal,
            MIN(l.first_game_id)::VARCHAR AS first_game_id
          FROM local l
          INNER JOIN t1 t
            ON l.low_id=t.low_id AND l.high_id=t.high_id
           AND l.first_utc_ms=t.first_utc_ms
           AND l.first_archive_ordinal=t.first_archive_ordinal
          GROUP BY l.low_id,l.high_id,t.first_utc_ms,t.first_archive_ordinal
        ) TO {sql_literal(tmp)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    pair_n = int(
        con.execute(f"SELECT COUNT(*) FROM read_parquet({sql_literal(focal_pairs)})").fetchone()[0]
    )
    global_n = int(
        con.execute(f"SELECT COUNT(*) FROM read_parquet({sql_literal(tmp)})").fetchone()[0]
    )
    con.close()
    if global_n != pair_n:
        raise RuntimeError(
            f"Not every focal pair was found in authenticated chronology: "
            f"global={global_n:,} focal={pair_n:,}"
        )
    os.replace(tmp, output)
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "output_path": str(output),
        "rows": parquet_rows(output),
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "focal_pairs": pair_n,
        "outcome_read": False,
    }
    atomic_json(receipt, saved)
    shutil.rmtree(temp, ignore_errors=True)
    print(f"C7R_FULLPANEL_GLOBAL_MIN_BUILD_OK pairs={saved['rows']:,}", flush=True)
    return output


def build_flags_and_freeze(payload: dict[str, Any], support: Path, pair_first: Path) -> tuple[Path, dict[str, Any]]:
    import duckdb

    state = payload["state"]
    flags = state / "stage07_prefocal_first_repeat_flags_private.parquet"
    receipt = state / "stage07_prefocal_first_repeat_flags_receipt.json"
    status = "C7R_FULLPANEL_PREFOCAL_FLAGS_FROZEN_OK"
    freeze_path = state / "PREOUTCOME_SUPPORT_FROZEN.json"

    existing = checkpoint_ok(flags, receipt, payload["config_sha256"], status)
    if existing is not None:
        if not freeze_path.is_file():
            raise RuntimeError("Flags exist but pre-outcome freeze receipt is missing")
        freeze = load_json(freeze_path)
        if freeze.get("flags_sha256") != sha256_file(flags):
            raise RuntimeError("Pre-outcome freeze does not authenticate flags")
        print("C7R_FULLPANEL_PREOUTCOME_SUPPORT_CHECKPOINT_OK", flush=True)
        return flags, freeze

    temp = state / "duckdb_temp/flags"
    con = duckdb.connect()
    configure(con, payload["memory"], temp, payload["threads"])
    tmp = flags.with_name(flags.name + f".tmp.{uuid.uuid4().hex}")
    print("C7R_FULLPANEL_PREFOCAL_FLAGS_BUILD_BEGIN", flush=True)
    con.execute(
        f"""
        COPY (
          SELECT
            s.game_id,
            (
              s.utc_ms = p.first_utc_ms
              AND s.archive_ordinal = p.first_archive_ordinal
              AND s.game_id = p.first_game_id
            ) AS first_rated_meeting,
            NOT (
              s.utc_ms = p.first_utc_ms
              AND s.archive_ordinal = p.first_archive_ordinal
              AND s.game_id = p.first_game_id
            ) AS repeat_rated_meeting
          FROM read_parquet({sql_literal(support)}) s
          INNER JOIN read_parquet({sql_literal(pair_first)}) p
            USING (low_id, high_id)
        ) TO {sql_literal(tmp)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = con.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT game_id)::BIGINT AS unique_games,
          COUNT(*) FILTER (
            WHERE CAST(first_rated_meeting AS INTEGER)
                + CAST(repeat_rated_meeting AS INTEGER) <> 1
          )::BIGINT AS partition_errors,
          COUNT(*) FILTER (WHERE first_rated_meeting)::BIGINT AS first_rows,
          COUNT(*) FILTER (WHERE repeat_rated_meeting)::BIGINT AS repeat_rows
        FROM read_parquet({sql_literal(tmp)})
        """
    ).fetchone()

    impossible = int(
        con.execute(
            f"""
            SELECT COUNT(*)
            FROM read_parquet({sql_literal(support)}) s
            INNER JOIN read_parquet({sql_literal(pair_first)}) p USING(low_id,high_id)
            WHERE
              p.first_utc_ms > s.utc_ms
              OR (
                p.first_utc_ms = s.utc_ms
                AND p.first_archive_ordinal > s.archive_ordinal
              )
              OR (
                p.first_utc_ms = s.utc_ms
                AND p.first_archive_ordinal = s.archive_ordinal
                AND p.first_game_id > s.game_id
              )
            """
        ).fetchone()[0]
    )
    con.close()

    if int(qa[0]) != EXPECTED_STAGE07_ROWS or int(qa[1]) != EXPECTED_STAGE07_ROWS:
        raise RuntimeError(f"Flag row/uniqueness gate failed: {qa}")
    if int(qa[2]) != 0:
        raise RuntimeError("First/repeat flags do not form an exhaustive partition")
    if impossible != 0:
        raise RuntimeError(
            f"Chronology minimum occurs after focal event for {impossible} rows; fail closed"
        )

    os.replace(tmp, flags)
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "output_path": str(flags),
        "rows": parquet_rows(flags),
        "bytes": flags.stat().st_size,
        "sha256": sha256_file(flags),
        "outcome_read": False,
    }
    atomic_json(receipt, saved)
    first_n, repeat_n = int(qa[3]), int(qa[4])
    freeze = {
        "status": "C7R_FULLPANEL_PREOUTCOME_SUPPORT_FROZEN_OK",
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "flags_path": str(flags),
        "flags_sha256": saved["sha256"],
        "rows": int(qa[0]),
        "first_rows": first_n,
        "repeat_rows": repeat_n,
        "repeat_share": repeat_n / int(qa[0]),
        "outcome_read_before_freeze": False,
        "definition": (
            "First iff focal (utc_ms, archive_ordinal, game_id) equals the "
            "earliest authenticated ordinary-speed rated event for its unordered pair."
        ),
        "ordering": ["utc_ms", "archive_ordinal", "game_id"],
    }
    atomic_json(freeze_path, freeze)
    shutil.rmtree(temp, ignore_errors=True)
    print(
        f"C7R_FULLPANEL_PREOUTCOME_SUPPORT_FROZEN_OK "
        f"first={first_n:,} repeat={repeat_n:,} "
        f"repeat_share={100*freeze['repeat_share']:.4f}%",
        flush=True,
    )
    return flags, freeze


def build_analysis_minimal(payload: dict[str, Any], flags: Path) -> Path:
    import duckdb

    state = payload["state"]
    output = state / "analysis_fair_worse_minimal_private.parquet"
    receipt = state / "analysis_fair_worse_minimal_receipt.json"
    status = "C7R_FULLPANEL_ANALYSIS_MINIMAL_OK"
    existing = checkpoint_ok(output, receipt, payload["config_sha256"], status)
    if existing is not None:
        return output

    temp = state / "duckdb_temp/analysis"
    con = duckdb.connect()
    configure(con, payload["memory"], temp, payload["threads"])
    src = path_list_literal(payload["stage07_paths"])
    tmp = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    print("C7R_FULLPANEL_OUTCOME_JOIN_BEGIN", flush=True)
    con.execute(
        f"""
        COPY (
          SELECT
            CAST(s.chooser_user_id AS BIGINT) AS chooser_user_id,
            CAST(s.outcome_kind_draw AS INTEGER) * 100.0 AS y_pp,
            CAST(s.fair_competitive AS INTEGER) AS fair,
            CAST(f.repeat_rated_meeting AS INTEGER) AS repeat
          FROM read_parquet({src}) s
          INNER JOIN read_parquet({sql_literal(flags)}) f USING(game_id)
          WHERE s.fair_competitive OR s.clearly_worse
        ) TO {sql_literal(tmp)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    con.close()
    os.replace(tmp, output)
    saved = {
        "status": status,
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "output_path": str(output),
        "rows": parquet_rows(output),
        "bytes": output.stat().st_size,
        "sha256": sha256_file(output),
        "outcome_read": True,
    }
    atomic_json(receipt, saved)
    shutil.rmtree(temp, ignore_errors=True)
    print(f"C7R_FULLPANEL_OUTCOME_JOIN_OK fair_or_worse_rows={saved['rows']:,}", flush=True)
    return output


def one_reg_fe(payload: dict[str, Any], analysis: Path, sample: str, where: str) -> dict[str, Any]:
    """Exact one-way chooser-FE slope with chooser-clustered CR1 from sufficient statistics."""
    import duckdb

    state = payload["state"]
    groups = state / "model_groups" / f"one_reg_{sample}.parquet"
    temp = state / "duckdb_temp" / f"fe_{sample}"
    con = duckdb.connect()
    configure(con, payload["memory"], temp, payload["threads"])

    if not groups.is_file():
        tmp = groups.with_name(groups.name + f".tmp.{uuid.uuid4().hex}")
        con.execute(
            f"""
            COPY (
              SELECT
                chooser_user_id,
                COUNT(*)::BIGINT AS n,
                SUM(y_pp)::DOUBLE AS sy,
                SUM(fair)::DOUBLE AS sx,
                SUM(fair * y_pp)::DOUBLE AS sxy,
                SUM(fair * fair)::DOUBLE AS sxx
              FROM read_parquet({sql_literal(analysis)})
              WHERE {where}
              GROUP BY chooser_user_id
            ) TO {sql_literal(tmp)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        os.replace(tmp, groups)

    agg = con.execute(
        f"""
        SELECT
          SUM(n)::BIGINT AS n,
          COUNT(*)::BIGINT AS g,
          SUM(sxx - sx*sx/n)::DOUBLE AS b,
          SUM(sxy - sx*sy/n)::DOUBLE AS a
        FROM read_parquet({sql_literal(groups)})
        """
    ).fetchone()
    n, g, b, a = int(agg[0]), int(agg[1]), float(agg[2]), float(agg[3])
    if not math.isfinite(b) or b <= 0:
        raise RuntimeError(f"No within-chooser identifying variation for {sample}")
    beta = a / b
    meat = float(
        con.execute(
            f"""
            SELECT SUM(POWER(
              (sxy - sx*sy/n) - (sxx - sx*sx/n) * {beta:.17g},
              2
            ))::DOUBLE
            FROM read_parquet({sql_literal(groups)})
            """
        ).fetchone()[0]
    )
    con.close()
    p = 1
    k = g + p
    if g <= 1 or n <= k:
        raise RuntimeError(f"Insufficient FE degrees of freedom for {sample}: N={n}, G={g}")
    cr1 = (g / (g - 1.0)) * ((n - 1.0) / (n - k))
    se = math.sqrt(cr1 * meat / (b * b))
    t = beta / se
    pval = math.erfc(abs(t) / math.sqrt(2.0))
    return {
        "sample": sample,
        "estimate_pp": beta,
        "se_cr1_pp": se,
        "t": t,
        "p_normal": pval,
        "rows": n,
        "chooser_clusters": g,
        "regressors_after_fe": p,
        "finite_sample_correction": cr1,
        "specification": "y_pp ~ fair + chooser FE; chooser-clustered CR1",
    }


def interaction_fe(payload: dict[str, Any], analysis: Path) -> list[dict[str, Any]]:
    import duckdb
    import numpy as np

    state = payload["state"]
    groups = state / "model_groups/interaction.parquet"
    temp = state / "duckdb_temp/fe_interaction"
    con = duckdb.connect()
    configure(con, payload["memory"], temp, payload["threads"])

    if not groups.is_file():
        tmp = groups.with_name(groups.name + f".tmp.{uuid.uuid4().hex}")
        con.execute(
            f"""
            COPY (
              SELECT
                chooser_user_id,
                COUNT(*)::BIGINT AS n,
                SUM(y_pp)::DOUBLE AS sy,
                SUM(fair)::DOUBLE AS sx1,
                SUM(repeat)::DOUBLE AS sx2,
                SUM(fair*repeat)::DOUBLE AS sx3,
                SUM(fair*y_pp)::DOUBLE AS sxy1,
                SUM(repeat*y_pp)::DOUBLE AS sxy2,
                SUM(fair*repeat*y_pp)::DOUBLE AS sxy3,
                SUM(fair*fair)::DOUBLE AS s11,
                SUM(fair*repeat)::DOUBLE AS s12,
                SUM(fair*fair*repeat)::DOUBLE AS s13,
                SUM(repeat*repeat)::DOUBLE AS s22,
                SUM(fair*repeat*repeat)::DOUBLE AS s23,
                SUM(fair*repeat*fair*repeat)::DOUBLE AS s33
              FROM read_parquet({sql_literal(analysis)})
              GROUP BY chooser_user_id
            ) TO {sql_literal(tmp)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        os.replace(tmp, groups)

    r = con.execute(
        f"""
        SELECT
          SUM(n)::BIGINT AS n,
          COUNT(*)::BIGINT AS g,
          SUM(s11-sx1*sx1/n)::DOUBLE,
          SUM(s12-sx1*sx2/n)::DOUBLE,
          SUM(s13-sx1*sx3/n)::DOUBLE,
          SUM(s22-sx2*sx2/n)::DOUBLE,
          SUM(s23-sx2*sx3/n)::DOUBLE,
          SUM(s33-sx3*sx3/n)::DOUBLE,
          SUM(sxy1-sx1*sy/n)::DOUBLE,
          SUM(sxy2-sx2*sy/n)::DOUBLE,
          SUM(sxy3-sx3*sy/n)::DOUBLE
        FROM read_parquet({sql_literal(groups)})
        """
    ).fetchone()
    n, g = int(r[0]), int(r[1])
    B = np.array(
        [[r[2], r[3], r[4]], [r[3], r[5], r[6]], [r[4], r[6], r[7]]],
        dtype=float,
    )
    a = np.array([r[8], r[9], r[10]], dtype=float)
    if np.linalg.matrix_rank(B) < 3:
        raise RuntimeError("Interaction FE model is rank deficient")
    beta = np.linalg.solve(B, a)

    b1, b2, b3 = (float(x) for x in beta)
    meat_row = con.execute(
        f"""
        WITH s AS (
          SELECT
            (sxy1-sx1*sy/n)
              - (s11-sx1*sx1/n)*{b1:.17g}
              - (s12-sx1*sx2/n)*{b2:.17g}
              - (s13-sx1*sx3/n)*{b3:.17g} AS q1,
            (sxy2-sx2*sy/n)
              - (s12-sx1*sx2/n)*{b1:.17g}
              - (s22-sx2*sx2/n)*{b2:.17g}
              - (s23-sx2*sx3/n)*{b3:.17g} AS q2,
            (sxy3-sx3*sy/n)
              - (s13-sx1*sx3/n)*{b1:.17g}
              - (s23-sx2*sx3/n)*{b2:.17g}
              - (s33-sx3*sx3/n)*{b3:.17g} AS q3
          FROM read_parquet({sql_literal(groups)})
        )
        SELECT
          SUM(q1*q1)::DOUBLE, SUM(q1*q2)::DOUBLE, SUM(q1*q3)::DOUBLE,
          SUM(q2*q2)::DOUBLE, SUM(q2*q3)::DOUBLE, SUM(q3*q3)::DOUBLE
        FROM s
        """
    ).fetchone()
    con.close()
    M = np.array(
        [
            [meat_row[0], meat_row[1], meat_row[2]],
            [meat_row[1], meat_row[3], meat_row[4]],
            [meat_row[2], meat_row[4], meat_row[5]],
        ],
        dtype=float,
    )
    p = 3
    k = g + p
    if g <= 1 or n <= k:
        raise RuntimeError(f"Insufficient interaction FE degrees of freedom: N={n}, G={g}")
    cr1 = (g / (g - 1.0)) * ((n - 1.0) / (n - k))
    Binv = np.linalg.inv(B)
    V = cr1 * Binv @ M @ Binv
    se = np.sqrt(np.diag(V))
    names = ["fair", "repeat", "fair_x_repeat"]
    out = []
    for j, name in enumerate(names):
        t = float(beta[j] / se[j])
        out.append(
            {
                "term": name,
                "estimate_pp": float(beta[j]),
                "se_cr1_pp": float(se[j]),
                "t": t,
                "p_normal": math.erfc(abs(t) / math.sqrt(2.0)),
                "rows": n,
                "chooser_clusters": g,
                "finite_sample_correction": cr1,
                "specification": (
                    "y_pp ~ fair + repeat + fair×repeat + chooser FE; chooser-clustered CR1"
                ),
            }
        )
    # Linear combination: repeat-meeting fair-vs-worse gradient = beta_fair + beta_interaction.
    c = np.array([1.0, 0.0, 1.0])
    est = float(c @ beta)
    var = float(c @ V @ c)
    se_c = math.sqrt(max(var, 0.0))
    t_c = est / se_c
    out.append(
        {
            "term": "repeat_fair_gradient=fair+fair_x_repeat",
            "estimate_pp": est,
            "se_cr1_pp": se_c,
            "t": t_c,
            "p_normal": math.erfc(abs(t_c) / math.sqrt(2.0)),
            "rows": n,
            "chooser_clusters": g,
            "finite_sample_correction": cr1,
            "specification": "linear combination from interaction model",
        }
    )
    return out


def make_public_results(
    payload: dict[str, Any],
    flags: Path,
    freeze: dict[str, Any],
    analysis: Path,
) -> Path:
    import duckdb

    final = payload["output_parent"] / payload["run_id"]
    if final.exists():
        success = final / "_SUCCESS.json"
        if success.is_file() and load_json(success).get("status") == STATUS:
            print(f"C7R_FULLPANEL_PUBLIC_RESULT_ALREADY_COMPLETE {final}", flush=True)
            return final
        raise RuntimeError(f"Output root already exists but is not certified: {final}")

    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    staging.mkdir(parents=True, exist_ok=False)
    temp = payload["state"] / "duckdb_temp/public"
    con = duckdb.connect()
    configure(con, payload["memory"], temp, payload["threads"])
    stage = path_list_literal(payload["stage07_paths"])

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW joined AS
        SELECT
          CAST(s.outcome_kind_draw AS INTEGER) AS kind,
          CAST(s.fair_competitive AS INTEGER) AS fair,
          CAST(s.clearly_worse AS INTEGER) AS worse,
          CAST(f.first_rated_meeting AS INTEGER) AS first,
          CAST(f.repeat_rated_meeting AS INTEGER) AS repeat
        FROM read_parquet({stage}) s
        INNER JOIN read_parquet({sql_literal(flags)}) f USING(game_id)
        """
    )

    raw = con.execute(
        """
        WITH expanded AS (
          SELECT 'all' AS meeting, * FROM joined
          UNION ALL
          SELECT 'first' AS meeting, * FROM joined WHERE first=1
          UNION ALL
          SELECT 'repeat' AS meeting, * FROM joined WHERE repeat=1
        ),
        cells AS (
          SELECT meeting, 'overall' AS state, COUNT(*)::BIGINT AS rows,
                 SUM(kind)::BIGINT AS kind_draws
          FROM expanded GROUP BY meeting
          UNION ALL
          SELECT meeting, 'competitive' AS state, COUNT(*)::BIGINT,
                 SUM(kind)::BIGINT
          FROM expanded WHERE fair=1 GROUP BY meeting
          UNION ALL
          SELECT meeting, 'clearly_worse' AS state, COUNT(*)::BIGINT,
                 SUM(kind)::BIGINT
          FROM expanded WHERE worse=1 GROUP BY meeting
        )
        SELECT meeting, state, rows, kind_draws,
               100.0*kind_draws/rows AS kindness_rate_pct
        FROM cells
        ORDER BY CASE meeting WHEN 'all' THEN 0 WHEN 'first' THEN 1 ELSE 2 END,
                 CASE state WHEN 'overall' THEN 0 WHEN 'competitive' THEN 1 ELSE 2 END
        """
    ).fetchall()
    raw_rows = [
        {
            "meeting": r[0],
            "state": r[1],
            "rows": int(r[2]),
            "kind_draws": int(r[3]),
            "kindness_rate_pct": float(r[4]),
        }
        for r in raw
    ]
    write_csv(
        staging / "first_repeat_raw_rates.csv",
        raw_rows,
        ("meeting", "state", "rows", "kind_draws", "kindness_rate_pct"),
    )

    by_meeting = {}
    for r in raw_rows:
        by_meeting.setdefault(r["meeting"], {})[r["state"]] = r
    gap_rows = []
    for m in ("all", "first", "repeat"):
        gap = (
            by_meeting[m]["competitive"]["kindness_rate_pct"]
            - by_meeting[m]["clearly_worse"]["kindness_rate_pct"]
        )
        gap_rows.append({"meeting": m, "raw_desert_gap_pp": gap})
    write_csv(staging / "raw_desert_gaps.csv", gap_rows, ("meeting", "raw_desert_gap_pp"))

    prevalence = con.execute(
        """
        SELECT
          SUM(repeat)::BIGINT AS repeat_all,
          COUNT(*)::BIGINT AS n_all,
          SUM(repeat) FILTER (WHERE fair=1)::BIGINT AS repeat_fair,
          COUNT(*) FILTER (WHERE fair=1)::BIGINT AS n_fair,
          SUM(repeat) FILTER (WHERE worse=1)::BIGINT AS repeat_worse,
          COUNT(*) FILTER (WHERE worse=1)::BIGINT AS n_worse
        FROM joined
        """
    ).fetchone()
    con.close()
    prevalence_rows = [
        {
            "state": "overall",
            "repeat_rows": int(prevalence[0]),
            "rows": int(prevalence[1]),
            "repeat_share_pct": 100 * int(prevalence[0]) / int(prevalence[1]),
        },
        {
            "state": "competitive",
            "repeat_rows": int(prevalence[2]),
            "rows": int(prevalence[3]),
            "repeat_share_pct": 100 * int(prevalence[2]) / int(prevalence[3]),
        },
        {
            "state": "clearly_worse",
            "repeat_rows": int(prevalence[4]),
            "rows": int(prevalence[5]),
            "repeat_share_pct": 100 * int(prevalence[4]) / int(prevalence[5]),
        },
    ]
    write_csv(
        staging / "repeat_prevalence.csv",
        prevalence_rows,
        ("state", "repeat_rows", "rows", "repeat_share_pct"),
    )

    print("C7R_FULLPANEL_MINIMAL_CHOOSER_FE_MODELS_BEGIN", flush=True)
    fe_rows = [
        one_reg_fe(payload, analysis, "all", "TRUE"),
        one_reg_fe(payload, analysis, "first", "repeat=0"),
        one_reg_fe(payload, analysis, "repeat", "repeat=1"),
    ]
    write_csv(
        staging / "minimal_chooser_fe_desert.csv",
        fe_rows,
        (
            "sample", "estimate_pp", "se_cr1_pp", "t", "p_normal", "rows",
            "chooser_clusters", "regressors_after_fe", "finite_sample_correction",
            "specification",
        ),
    )
    interaction_rows = interaction_fe(payload, analysis)
    write_csv(
        staging / "minimal_chooser_fe_interaction.csv",
        interaction_rows,
        (
            "term", "estimate_pp", "se_cr1_pp", "t", "p_normal", "rows",
            "chooser_clusters", "finite_sample_correction", "specification",
        ),
    )
    print("C7R_FULLPANEL_MINIMAL_CHOOSER_FE_MODELS_OK", flush=True)

    benchmark = {
        "historical_sampled_c7r": {
            "sample_n": OLD_SAMPLE_N,
            "first_n": OLD_FIRST_N,
            "repeat_n": OLD_REPEAT_N,
            "repeat_share": OLD_REPEAT_SHARE,
            "fair_first_rate_pct": OLD_FAIR_FIRST_RATE_PCT,
            "fair_repeat_rate_pct": OLD_FAIR_REPEAT_RATE_PCT,
            "adjusted_first_gradient_pp": OLD_FIRST_GRADIENT_PP,
            "adjusted_repeat_gradient_pp": OLD_REPEAT_GRADIENT_PP,
            "adjusted_interaction_pp": OLD_INTERACTION_PP,
            "adjusted_interaction_p": OLD_INTERACTION_P,
            "note": (
                "Historical adjusted coefficients came from the frozen C7R v1.0.2 "
                "model family. The new minimal chooser-FE census models are a separate, "
                "transparent specification and must not be mislabeled as an exact "
                "C7R-v1.0.2 model reproduction."
            ),
        }
    }
    atomic_json(staging / "historical_sampled_benchmark.json", benchmark)

    summary = {
        "status": STATUS,
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_version": SCRIPT_VERSION,
        "config_sha256": payload["config_sha256"],
        "full_stage07_rows": EXPECTED_STAGE07_ROWS,
        "first_rows": freeze["first_rows"],
        "repeat_rows": freeze["repeat_rows"],
        "repeat_share_pct": 100 * freeze["repeat_share"],
        "repeat_share_competitive_pct": prevalence_rows[1]["repeat_share_pct"],
        "repeat_share_clearly_worse_pct": prevalence_rows[2]["repeat_share_pct"],
        "fair_first_rate_pct": by_meeting["first"]["competitive"]["kindness_rate_pct"],
        "fair_repeat_rate_pct": by_meeting["repeat"]["competitive"]["kindness_rate_pct"],
        "raw_first_desert_gap_pp": next(
            x["raw_desert_gap_pp"] for x in gap_rows if x["meeting"] == "first"
        ),
        "raw_repeat_desert_gap_pp": next(
            x["raw_desert_gap_pp"] for x in gap_rows if x["meeting"] == "repeat"
        ),
        "minimal_fe_first_gradient_pp": next(
            x["estimate_pp"] for x in fe_rows if x["sample"] == "first"
        ),
        "minimal_fe_repeat_gradient_pp": next(
            x["estimate_pp"] for x in fe_rows if x["sample"] == "repeat"
        ),
        "minimal_fe_interaction_pp": next(
            x["estimate_pp"] for x in interaction_rows if x["term"] == "fair_x_repeat"
        ),
        "minimal_fe_interaction_p_normal": next(
            x["p_normal"] for x in interaction_rows if x["term"] == "fair_x_repeat"
        ),
        "preoutcome_support_receipt": freeze,
        "private_flags_path": str(flags),
        "private_pair_first_event_path": str(
            payload["state"] / "pair_first_rated_event_private.parquet"
        ),
        "chronology_scope": (
            "Authenticated ordinary-speed chronology files through 2025-10; "
            "later files are unnecessary for a pre-focal classification."
        ),
        "ordering": ["utc_ms", "archive_ordinal", "game_id"],
        "public_privacy": "Aggregate-only; no account IDs or game IDs are included.",
    }
    atomic_json(staging / "summary.json", summary)

    readme = f"""C7R FULL-PANEL PRE-FOCAL FIRST/REPEAT CENSUS

Status: {STATUS}
Run ID: {payload['run_id']}

This bundle replaces the historical 1-in-50 focal-pair support with all
{EXPECTED_STAGE07_ROWS:,} certified Stage-07 opportunities.

Definition:
  first = the focal event is the earliest rated event for its unordered pair
          in the authenticated C7R-compatible ordinary-speed chronology,
          ordered by (utc_ms, archive_ordinal, game_id).
  repeat = at least one earlier rated event exists for that pair.

Important:
- The expensive history classification was frozen BEFORE Stage-07 kindness
  outcomes were read.
- The row-level flags and pair histories remain private on XT_Pro.
- `first_repeat_raw_rates.csv` and `repeat_prevalence.csv` are census aggregates.
- `minimal_chooser_fe_desert.csv` and `minimal_chooser_fe_interaction.csv`
  are new transparent one-way chooser-FE census models with chooser-clustered
  CR1 inference.
- The historical +1.5669 / +1.3342 / -0.0087 C7R coefficients came from the
  frozen C7R v1.0.2 model family. Do NOT claim the new minimal FE coefficients
  are exact reproductions of that old adjusted model unless the old model
  engine is explicitly rerun on these full-sample flags.

Public files contain no row-level identifiers.
"""
    atomic_text(staging / "README_results.md", readme)

    # Hash all public report files except the manifest and success receipt.
    files = sorted(
        p for p in staging.iterdir()
        if p.is_file() and p.name not in {"report_file_hashes.tsv", "_SUCCESS.json"}
    )
    manifest_rows = [
        {
            "sha256": sha256_file(p),
            "bytes": p.stat().st_size,
            "path": p.name,
        }
        for p in files
    ]
    with (staging / "report_file_hashes.tsv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["sha256", "bytes", "path"], delimiter="\t", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(manifest_rows)

    success = {
        "status": STATUS,
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "config_sha256": payload["config_sha256"],
        "summary_sha256": sha256_file(staging / "summary.json"),
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "private_flags_sha256": sha256_file(flags),
        "preoutcome_support_frozen": True,
        "full_stage07_rows": EXPECTED_STAGE07_ROWS,
        "private_row_level_files_transferred": False,
    }
    atomic_json(staging / "_SUCCESS.json", success)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    shutil.rmtree(temp, ignore_errors=True)
    return final


def verify_public(final: Path) -> None:
    success = load_json(final / "_SUCCESS.json")
    if success.get("status") != STATUS:
        raise RuntimeError("Public success status mismatch")
    if success.get("summary_sha256") != sha256_file(final / "summary.json"):
        raise RuntimeError("Public summary hash mismatch")
    if success.get("report_manifest_sha256") != sha256_file(
        final / "report_file_hashes.tsv"
    ):
        raise RuntimeError("Public report-manifest hash mismatch")
    with (final / "report_file_hashes.tsv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        p = final / r["path"]
        if not p.is_file():
            raise RuntimeError(f"Missing public report file: {p}")
        if p.stat().st_size != int(r["bytes"]) or sha256_file(p) != r["sha256"]:
            raise RuntimeError(f"Public report authentication failed: {p.name}")
    print("C7R_FULLPANEL_PUBLIC_INDEPENDENT_VERIFICATION_OK", flush=True)


def package_public(payload: dict[str, Any], final: Path) -> tuple[Path, Path]:
    desktop = payload["desktop"]
    desktop.mkdir(parents=True, exist_ok=True)
    zip_path = desktop / f"C7R_FULLPANEL_PREFOCAL_RESULTS_{payload['run_id']}.zip"
    sidecar = zip_path.with_suffix(zip_path.suffix + ".sha256")
    if zip_path.exists() or sidecar.exists():
        raise RuntimeError(f"Transfer artifact already exists: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(final.iterdir()):
            if p.is_file():
                zf.write(p, arcname=f"{final.name}/{p.name}")
    digest = sha256_file(zip_path)
    atomic_text(sidecar, f"{digest}  {zip_path.name}\n")
    print(f"RESULT_ZIP: {zip_path}", flush=True)
    print(f"RESULT_SIDECAR: {sidecar}", flush=True)
    print(f"RESULT_SHA256: {digest}", flush=True)
    return zip_path, sidecar


def self_test() -> None:
    """Dependency and algebra test; production path is additionally fail-closed on authorities."""
    import duckdb
    import numpy as np
    import pyarrow
    import pandas

    con = duckdb.connect()
    # Exact lexicographic minimum logic used by production, on synthetic repeated pairs.
    con.execute(
        """
        CREATE TABLE x(low_id BIGINT, high_id BIGINT, utc_ms BIGINT,
                       archive_ordinal BIGINT, game_id VARCHAR);
        INSERT INTO x VALUES
          (1,2,100,2,'b'), (1,2,100,1,'c'), (1,2,100,1,'a'),
          (3,4,50,5,'x'), (3,4,60,1,'y');
        """
    )
    got = con.execute(
        """
        WITH t0 AS (
          SELECT low_id,high_id,MIN(utc_ms) first_utc_ms
          FROM x GROUP BY 1,2
        ), t1 AS (
          SELECT x.low_id,x.high_id,t.first_utc_ms,
                 MIN(x.archive_ordinal) first_archive_ordinal
          FROM x JOIN t0 t
            ON x.low_id=t.low_id AND x.high_id=t.high_id AND x.utc_ms=t.first_utc_ms
          GROUP BY x.low_id,x.high_id,t.first_utc_ms
        )
        SELECT x.low_id,x.high_id,t.first_utc_ms,t.first_archive_ordinal,
               MIN(x.game_id) first_game_id
        FROM x JOIN t1 t
          ON x.low_id=t.low_id AND x.high_id=t.high_id
         AND x.utc_ms=t.first_utc_ms
         AND x.archive_ordinal=t.first_archive_ordinal
        GROUP BY x.low_id,x.high_id,t.first_utc_ms,t.first_archive_ordinal
        ORDER BY 1,2
        """
    ).fetchall()
    con.close()
    assert got == [(1, 2, 100, 1, "a"), (3, 4, 50, 5, "x")], got

    # Basic linear algebra sanity.
    B = np.array([[2.0, 0.2], [0.2, 3.0]])
    a = np.array([1.0, 2.0])
    b = np.linalg.solve(B, a)
    assert np.all(np.isfinite(b))
    versions = {
        "duckdb": duckdb.__version__,
        "numpy": np.__version__,
        "pandas": pandas.__version__,
        "pyarrow": pyarrow.__version__,
    }
    print("C7R_FULLPANEL_SELF_TEST_OK", json.dumps(versions, sort_keys=True), flush=True)


def execute(args: argparse.Namespace) -> None:
    started = time.time()
    payload = make_payload(args)
    print("C7R FULL-PANEL PRE-FOCAL FIRST/REPEAT CENSUS", flush=True)
    print(f"Stage-07 rows: {EXPECTED_STAGE07_ROWS:,}", flush=True)
    print(
        f"Authenticated chronology: {EXPECTED_CHRONOLOGY_ROWS:,} rows / "
        f"{EXPECTED_CHRONOLOGY_FILES} files",
        flush=True,
    )
    print(
        f"C7R-compatible source scan: "
        f"{payload['config']['chronology_rows_scanned_manifest']:,} manifest rows "
        f"across {payload['config']['chronology_files_scanned']} ordinary-speed files "
        f"through {LAST_FOCAL_MONTH}",
        flush=True,
    )
    print(
        f"DuckDB: {payload['threads']} threads, memory limit {payload['memory']}, "
        f"{len(payload['shards'])} resumable source shards",
        flush=True,
    )
    print("Expected production runtime: approximately 6-18 hours with clean Parquets.", flush=True)
    print("Relaunching the same command safely resumes authenticated shard checkpoints.", flush=True)

    initialize_state(payload)
    support, focal_pairs = build_focal_support(payload)
    shard_min = build_shard_minima(payload, focal_pairs)
    pair_first = merge_global_minima(payload, shard_min, focal_pairs)
    flags, freeze = build_flags_and_freeze(payload, support, pair_first)

    # From here on, outcomes may be read.
    analysis = build_analysis_minimal(payload, flags)
    final = make_public_results(payload, flags, freeze, analysis)
    verify_public(final)
    package_public(payload, final)

    print(
        f"C7R_FULLPANEL_PREFOCAL_EXECUTION_FINISHED seconds={time.time()-started:.1f}",
        flush=True,
    )
    print(f"PUBLIC_OUTPUT: {final}", flush=True)
    print(f"PRIVATE_FLAGS: {flags}", flush=True)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return
    if not args.execute:
        raise SystemExit("Refusing production run without --execute")
    execute(args)


if __name__ == "__main__":
    main()
