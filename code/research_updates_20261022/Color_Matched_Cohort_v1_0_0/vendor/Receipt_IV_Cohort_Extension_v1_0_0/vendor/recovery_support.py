#!/usr/bin/env python3
"""Read-only recovery of API game source for the certified Stage 07 IDs.

No HTTP client, API requests, estimator, or rematch classifier is included.
Private row outputs remain on the user's disk; report ZIPs contain metadata only.
"""
from __future__ import annotations

import argparse
import bz2
import concurrent.futures as futures
import contextlib
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import traceback
import zipfile
from collections import Counter

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import zstandard as zstd

VERSION = "1.0.0"
PACKAGE = Path(__file__).resolve().parent
ROW_SCHEMA = pa.schema([
    ("game_id", pa.string()), ("api_source_raw", pa.string()),
    ("source_present", pa.bool_()), ("source_invalid", pa.bool_()),
    ("raw_status", pa.string()), ("raw_winner", pa.string()),
    ("winner_invalid", pa.bool_()), ("input_file_id", pa.int32()),
    ("input_line", pa.int64()),
])
PANEL_FIELDS = ["month", "game_id", "api_status", "api_winner",
                "outcome_kind_draw", "engine_eval_cp_disconnected"]
MAX_LINE = 16 * 1024 * 1024
RAW_NAMES = tuple("enriched_games_raw.ndjson" + suffix for suffix in ("", ".zst", ".gz", ".bz2"))


def qs(value):
    """Quote a SQL string literal, never a shell command."""
    return "'" + str(value).replace("'", "''") + "'"


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def atomic_parquet(path, table):
    path = Path(path)
    temporary = path.with_name(path.name + ".partial")
    pq.write_table(table, temporary, compression="zstd")
    os.replace(temporary, path)


def fingerprint(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Symlink input is not an accepted authority: " + str(path))
    stat = path.stat()
    if not path.is_file():
        raise ValueError("Not a regular file: " + str(path))
    if getattr(stat, "st_flags", 0) & 0x40000000:
        raise ValueError("Cloud-only input is not locally readable: " + str(path))
    return {"size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def require_fingerprint(item):
    observed = fingerprint(item["path"])
    expected = {k: item[k] for k in ("size_bytes", "mtime_ns")}
    if observed != expected:
        raise ValueError("Input changed since inventory: " + item["path"])
    return observed


def decoded_chunks(path, raw_hash):
    """Yield decompressed bytes, hashing the physical input and checking frames.

    Explicit EOF checks reject truncated Zstandard input, including a truncated
    final frame after one or more complete frames. Concatenated frames work.
    """
    path = Path(path)
    if path.suffix in (".gz", ".bz2"):
        # Late legacy fallback. Hash the physical file before standard CRC readers.
        with path.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                raw_hash.update(block)
        opener = gzip.open if path.suffix == ".gz" else bz2.open
        with opener(path, "rb") as f:
            yield from iter(lambda: f.read(1024 * 1024), b"")
        return
    decompressor = None
    frames = 0
    with path.open("rb") as f:
        while True:
            block = f.read(64 * 1024 if path.suffix == ".zst" else 1024 * 1024)
            if not block:
                break
            raw_hash.update(block)
            if path.suffix != ".zst":
                yield block
                continue
            while block:
                if decompressor is None:
                    decompressor = zstd.ZstdDecompressor().decompressobj()
                output = decompressor.decompress(block)
                if output:
                    yield output
                if decompressor.eof:
                    frames += 1
                    block = decompressor.unused_data
                    decompressor = None
                else:
                    block = b""
    if path.suffix == ".zst" and (decompressor is not None or frames == 0):
        raise ValueError("Incomplete or empty Zstandard stream")


def ndjson_lines(path, raw_hash):
    tail = b""
    for block in decoded_chunks(path, raw_hash):
        parts = (tail + block).split(b"\n")
        tail = parts.pop()
        if len(tail) > MAX_LINE:
            raise ValueError("NDJSON line exceeds 16 MiB")
        for line in parts:
            if len(line) > MAX_LINE:
                raise ValueError("NDJSON line exceeds 16 MiB")
            yield line
    if tail:
        yield tail


def parse_game(obj):
    """Accept one top-level API/legacy game, never merge wrapper fields."""
    if not isinstance(obj, dict):
        return None
    game_id = obj.get("id", obj.get("game_id"))
    if not isinstance(game_id, str) or not re.fullmatch(r"[A-Za-z0-9]{8}", game_id):
        return None
    if "id" in obj and "game_id" in obj and obj["id"] != obj["game_id"]:
        return None
    status = obj.get("status")
    if not isinstance(status, str) or not status:
        return None
    # Both documented producers retain at least one of these game attributes.
    if not any(key in obj for key in ("players", "speed", "perf", "rated", "variant", "createdAt", "created_at_ms")):
        return None
    source = obj.get("source")
    source_invalid = source is not None and (not isinstance(source, str) or not source or source.strip() != source)
    winner = obj.get("winner")
    winner_invalid = winner is not None and winner not in ("white", "black")
    return {"game_id": game_id, "api_source_raw": None if source_invalid else source,
            "source_present": "source" in obj, "source_invalid": source_invalid,
            "raw_status": status, "raw_winner": None if winner_invalid else winner,
            "winner_invalid": winner_invalid}


def scan_raw(item, targets, directory, binding, verify_resume=False):
    """Commit a file checkpoint only after complete decompression and hashing."""
    file_id = item["file_id"]
    output = Path(directory) / f"file-{file_id:06d}.parquet"
    receipt_path = output.with_suffix(".json")
    require_fingerprint(item)
    if receipt_path.exists():
        saved = json.loads(receipt_path.read_text())
        valid = saved.get("binding") == binding and saved.get("input") == item
        valid = valid and output.exists() and digest(output) == saved.get("output_sha256")
        if valid and verify_resume:
            valid = digest(item["path"]) == saved["input_sha256"]
        if valid:
            saved["reused_checkpoint"] = True
            saved["resume_input_check"] = "sha256" if verify_resume else "size_and_mtime"
            return saved
        raise ValueError("Checkpoint does not match its input/output; use a new run: " + str(receipt_path))
    temporary = output.with_name(output.name + ".partial")
    stats = Counter()
    source_counts, keys = Counter(), Counter()
    first_bad_lines = []
    h = hashlib.sha256()
    rows = []
    with pq.ParquetWriter(temporary, ROW_SCHEMA, compression="zstd") as writer:
        for number, line in enumerate(ndjson_lines(item["path"], h), 1):
            stats["physical_lines"] += 1
            if not line.strip():
                stats["blank_lines"] += 1
                continue
            try:
                obj = json.loads(line)
            except (ValueError, UnicodeError, RecursionError):
                stats["parse_errors"] += 1
                if len(first_bad_lines) < 5:
                    first_bad_lines.append(number)
                continue
            if isinstance(obj, dict) and stats["key_sample_records"] < 1000:
                keys.update(obj.keys())
                stats["key_sample_records"] += 1
            game = parse_game(obj)
            if game is None:
                stats["non_game_records"] += 1
                continue
            stats["game_records"] += 1
            stats["source_present_records"] += int(game["source_present"])
            stats["source_invalid_records"] += int(game["source_invalid"])
            source = game["api_source_raw"]
            if source is not None:
                stats["source_known_records"] += 1
                source_counts[source] += 1
            if game["game_id"] not in targets:
                stats["non_target_game_records"] += 1
                continue
            stats["matched_records"] += 1
            game.update(input_file_id=file_id, input_line=number)
            rows.append(game)
            if len(rows) >= 25000:
                writer.write_table(pa.Table.from_pylist(rows, schema=ROW_SCHEMA))
                rows.clear()
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=ROW_SCHEMA))
    require_fingerprint(item)
    os.replace(temporary, output)
    receipt = {"input": item, "input_sha256": h.hexdigest(), "binding": binding,
               "output_sha256": digest(output), "output_path": str(output),
               "counts": dict(stats), "source_record_counts": dict(source_counts),
               "top_level_key_sample": dict(keys.most_common(60)),
               "first_parse_error_line_numbers": first_bad_lines, "reused_checkpoint": False}
    atomic_json(receipt_path, receipt)
    return receipt


def load_targets(panel):
    require_fingerprint(panel)
    panel_hash = digest(panel["path"])
    reader = pq.ParquetFile(panel["path"])
    missing = set(PANEL_FIELDS) - set(reader.schema_arrow.names)
    if missing:
        raise ValueError("Stage 07 schema missing required fields: " + str(sorted(missing)))
    if not pa.types.is_boolean(reader.schema_arrow.field("outcome_kind_draw").type):
        raise ValueError("outcome_kind_draw must be Boolean")
    if not pa.types.is_integer(reader.schema_arrow.field("engine_eval_cp_disconnected").type):
        raise ValueError("engine_eval_cp_disconnected must be integer centipawns")
    targets = set()
    count = 0
    for batch in reader.iter_batches(columns=["game_id"], batch_size=131072, use_threads=False):
        ids = batch.column(0).to_pylist()
        targets.update(ids)
        count += len(ids)
    if None in targets or "" in targets or len(targets) != count:
        raise ValueError("Stage 07 null/empty/duplicate game IDs in " + panel["month"])
    if any(not isinstance(g, str) or not re.fullmatch(r"[A-Za-z0-9]{8}", g) for g in targets):
        raise ValueError("Stage 07 contains an unexpected game ID format")
    require_fingerprint(panel)
    return targets, panel_hash


def recover_month(task):
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    month = task["month"]
    directory = Path(task["run_dir"]) / "private" / month
    directory.mkdir(parents=True, exist_ok=True)
    print(f"{month}: loading and hashing certified target IDs", flush=True)
    targets, panel_hash = load_targets(task["panel"])
    binding = {"code_sha256": task["code_sha256"], "catalog_sha256": task["catalog_sha256"],
               "panel_sha256": panel_hash, "month": month}
    receipts, errors = [], []
    started, last_progress = time.monotonic(), time.monotonic()
    processed_bytes = 0
    for index, item in enumerate(task["inputs"], 1):
        try:
            receipt = scan_raw(item, targets, directory, binding, task["verify_resume"])
            receipts.append(receipt)
            processed_bytes += item["size_bytes"]
        except Exception as exc:
            errors.append({"month": month, "file_id": item["file_id"], "path": item["path"], "error": str(exc)})
            print(f"{month}: input {item['file_id']} failed; recorded for report: {exc}", flush=True)
        if time.monotonic() - last_progress >= 30 or index == len(task["inputs"]):
            print(f"{month}: {index}/{len(task['inputs'])} files, {processed_bytes / 1e9:.2f} GB, "
                  f"{(time.monotonic() - started) / 60:.1f} minutes; errors={len(errors)}", flush=True)
            last_progress = time.monotonic()
    result = {"month": month, "panel": task["panel"], "panel_sha256": panel_hash,
              "panel_target_count": len(targets), "receipts": receipts, "errors": errors,
              "planned_files": len(task["inputs"]), "elapsed_seconds": time.monotonic() - started}
    atomic_json(directory / "MONTH_RECOVERY.json", result)
    return result


def inspect_late(config, project, legacy_project, first_id):
    """Only inspect known lookup run roots and their immediate shard folders."""
    found, observations = [], []
    for month, run_name in sorted(config["late_lookup_runs"].items()):
        chosen = False
        roots = list(dict.fromkeys([str(Path(legacy_project) / "output" / run_name),
                                    str(Path(project) / "output" / run_name)]))
        for root_string in roots:
            root = Path(root_string)
            observation = {"month": month, "run_root": root_string, "exists": root.is_dir(),
                           "summaries": [], "raw_files_found": 0, "selected": False, "errors": []}
            observations.append(observation)
            if not root.is_dir() or root.is_symlink():
                continue
            try:
                dirs = [root] + sorted(p for p in root.iterdir()
                                       if re.fullmatch(r"shard_\d{2}", p.name) and p.is_dir() and not p.is_symlink())
                candidates = set()
                for directory in dirs:
                    for name in RAW_NAMES:
                        p = directory / name
                        if p.exists():
                            candidates.add(p)
                    summary = directory / "summary.json"
                    if summary.is_file() and not summary.is_symlink():
                        sm = {"path": str(summary)}
                        try:
                            if fingerprint(summary)["size_bytes"] > 8 * 1024 * 1024:
                                raise ValueError("Summary exceeds 8 MiB diagnostic limit")
                            obj = json.loads(summary.read_text())
                            sm["sha256"] = digest(summary)
                            sm["raw_ndjson_fields"] = []
                            # Read only specifically named retention fields. No scripts are executed.
                            def visit(value, trail=""):
                                if isinstance(value, dict):
                                    for key, val in value.items():
                                        if key in ("raw_ndjson", "skip_raw_ndjson"):
                                            sm["raw_ndjson_fields"].append({"key_path": trail + key, "value": val})
                                            if key == "raw_ndjson" and isinstance(val, str):
                                                pointer = Path(val)
                                                if not pointer.is_absolute():
                                                    pointer = directory / pointer
                                                # Explicit pointer must stay in this known run and use a known raw filename.
                                                resolved = pointer.resolve()
                                                unsafe_part = any("partial" in p.lower() or "quarantine" in p.lower() for p in resolved.parts)
                                                if root.resolve() in resolved.parents and resolved.name in RAW_NAMES and pointer.exists() and not unsafe_part:
                                                    candidates.add(pointer)
                                        elif isinstance(val, (dict, list)):
                                            visit(val, trail + key + ".")
                                elif isinstance(value, list):
                                    for index, val in enumerate(value):
                                        visit(val, trail + str(index) + ".")
                            visit(obj)
                        except Exception as exc:
                            sm["error"] = str(exc)
                        observation["summaries"].append(sm)
                observation["raw_files_found"] = len(candidates)
                if candidates and not chosen:
                    for p in sorted(candidates):
                        info = fingerprint(p)
                        found.append({"month": month, "kind": "late_legacy_ndjson", "path": str(p),
                                      "relative_path": None, "file_id": first_id + len(found), **info})
                    chosen = True
                    observation["selected"] = True
            except Exception as exc:
                observation["errors"].append(str(exc))
    return found, observations


def sql_parquets(paths):
    return "read_parquet([" + ",".join(qs(p) for p in paths) + "], hive_partitioning=false)"


def query_dict(con, sql):
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def copy_query(con, query, destination):
    destination = Path(destination)
    temporary = destination.with_name(destination.name + ".partial")
    if temporary.exists():
        temporary.unlink()  # Only this run's uncommitted output.
    con.execute(f"COPY ({query}) TO {qs(temporary)} (FORMAT PARQUET, COMPRESSION ZSTD)")
    os.replace(temporary, destination)


def reduce_month(con, result, run_dir):
    month = result["month"]
    directory = Path(run_dir) / "private" / month
    panel = result["panel"]
    require_fingerprint(panel)
    con.execute(f"CREATE OR REPLACE TEMP VIEW panel AS SELECT {','.join(PANEL_FIELDS)} FROM {sql_parquets([panel['path']])}")
    paths = [r["output_path"] for r in result["receipts"]]
    if not paths:
        empty = directory / "empty.parquet"
        atomic_parquet(empty, pa.Table.from_pylist([], schema=ROW_SCHEMA))
        paths = [str(empty)]
    con.execute(f"CREATE OR REPLACE TEMP VIEW raw AS SELECT * FROM {sql_parquets(paths)}")
    unique = directory / "source_index.parquet"
    copy_query(con, """
        SELECT game_id, count(*) AS raw_rows, count(DISTINCT api_source_raw) AS source_values,
               CASE WHEN count(DISTINCT api_source_raw)=1 THEN min(api_source_raw) END AS api_source,
               count(DISTINCT raw_status) AS status_values, min(raw_status) AS raw_status,
               count(DISTINCT coalesce(raw_winner, '<NULL>')) AS winner_values,
               min(raw_winner) AS raw_winner,
               bool_or(source_present) AS any_source_field,
               bool_or(source_invalid) AS any_source_invalid,
               bool_or(winner_invalid) AS any_winner_invalid,
               min(input_file_id) AS first_input_file_id,
               min(input_file_id) FILTER (WHERE api_source_raw IS NOT NULL) AS source_input_file_id
        FROM raw GROUP BY game_id
    """, unique)
    con.execute(f"CREATE OR REPLACE TEMP VIEW recovered AS SELECT * FROM {sql_parquets([unique])}")
    flags = directory / "stage07_source_flags.parquet"
    copy_query(con, """
        WITH joined AS (
            SELECT p.month, p.game_id, p.outcome_kind_draw,
                   p.engine_eval_cp_disconnected >= -100 AS fair_region,
                   r.api_source, coalesce(r.raw_rows, 0) AS raw_rows,
                   coalesce(r.source_values, 0) AS source_values,
                   coalesce(r.source_values > 1, false) AS source_conflict,
                   coalesce(r.status_values > 1, false) AS status_conflict,
                   coalesce(r.winner_values > 1, false) AS winner_conflict,
                   coalesce(r.any_source_field, false) AS any_source_field,
                   coalesce(r.any_source_invalid, false) AS any_source_invalid,
                   coalesce(r.any_winner_invalid, false) AS any_winner_invalid,
                   r.first_input_file_id, r.source_input_file_id,
                   CASE WHEN r.game_id IS NULL THEN false ELSE
                       r.status_values=1 AND r.raw_status IS NOT DISTINCT FROM p.api_status
                       AND r.winner_values=1 AND r.raw_winner IS NOT DISTINCT FROM p.api_winner
                       AND NOT r.any_winner_invalid END AS api_consistent
            FROM panel p LEFT JOIN recovered r USING (game_id)
        ), verified AS (
            SELECT *, (source_values=1 AND api_consistent AND NOT any_source_invalid) AS source_verified
            FROM joined
        )
        SELECT *, (source_verified AND api_source='pool') AS pool_verified
        FROM verified
    """, flags)
    con.execute(f"CREATE OR REPLACE TEMP VIEW flags AS SELECT * FROM {sql_parquets([flags])}")
    baseline = query_dict(con, f"""
        SELECT count(*) AS opportunities, count(*) FILTER (WHERE outcome_kind_draw) AS kind_draws,
               count(*) FILTER (WHERE engine_eval_cp_disconnected>=-100) AS fair_rows,
               count(*) FILTER (WHERE month IS DISTINCT FROM {qs(month)}) AS wrong_month_rows,
               count(*) FILTER (WHERE api_status IS DISTINCT FROM 'timeout') AS non_timeout_rows,
               count(*) FILTER (WHERE outcome_kind_draw IS NULL OR engine_eval_cp_disconnected IS NULL) AS null_outcome_or_eval,
               count(*) FILTER (WHERE api_winner IS NOT NULL AND api_winner NOT IN ('white','black')) AS invalid_panel_winner
        FROM panel
    """)[0]
    coverage = query_dict(con, """
        SELECT count(*) AS output_rows, count(DISTINCT game_id) AS unique_game_ids,
               count(*) FILTER (WHERE raw_rows>0) AS matched_games,
               count(*) FILTER (WHERE raw_rows>1) AS games_with_retry_duplicates,
               coalesce(sum(greatest(raw_rows-1, 0)),0)::BIGINT AS duplicate_raw_rows,
               count(*) FILTER (WHERE any_source_field) AS games_with_source_field,
               count(*) FILTER (WHERE source_values=1) AS games_with_unique_source,
               count(*) FILTER (WHERE source_conflict) AS source_conflicts,
               count(*) FILTER (WHERE status_conflict) AS status_conflicts,
               count(*) FILTER (WHERE winner_conflict) AS winner_conflicts,
               count(*) FILTER (WHERE any_source_invalid OR any_winner_invalid) AS invalid_target_field_games,
               count(*) FILTER (WHERE raw_rows>0 AND NOT api_consistent) AS api_inconsistent_games,
               count(*) FILTER (WHERE source_verified) AS source_verified_games,
               count(*) FILTER (WHERE pool_verified) AS pool_verified_games
        FROM flags
    """)[0]
    summaries = query_dict(con, " UNION ALL ".join(f"""
        SELECT {qs(month)} AS month, {qs(sample)} AS sample, count(*) AS opportunities,
               count(*) FILTER (WHERE outcome_kind_draw) AS kind_draws,
               count(*) FILTER (WHERE fair_region) AS fair_rows,
               count(*) FILTER (WHERE fair_region AND outcome_kind_draw) AS fair_kind_draws,
               avg(outcome_kind_draw::DOUBLE) AS kindness_rate
        FROM flags WHERE {condition}
    """ for sample, condition in (("current_certified", "true"), ("source_verified", "source_verified"),
                                  ("pool_verified_observed", "pool_verified"))))
    source_counts = query_dict(con, f"""
        SELECT {qs(month)} AS month, api_source, source_verified, count(*) AS games
        FROM flags GROUP BY api_source, source_verified ORDER BY api_source NULLS FIRST, source_verified
    """)
    stats = Counter()
    for receipt in result["receipts"]:
        stats.update(receipt["counts"])
    row = {"month": month, **baseline, **coverage,
           "planned_files": result["planned_files"], "completed_files": len(result["receipts"]),
           "failed_files": len(result["errors"]), "parse_errors": stats["parse_errors"],
           "non_game_records": stats["non_game_records"], "raw_game_records": stats["game_records"],
           "raw_source_known_records": stats["source_known_records"],
           "raw_source_invalid_records": stats["source_invalid_records"],
           "source_coverage": coverage["source_verified_games"] / baseline["opportunities"] if baseline["opportunities"] else 0.0}
    structural_ok = (row["output_rows"] == row["unique_game_ids"] == row["opportunities"] == result["panel_target_count"]
                     and not any(row[k] for k in ("wrong_month_rows", "non_timeout_rows", "null_outcome_or_eval", "invalid_panel_winner")))
    row["panel_and_join_ok"] = structural_ok
    row["month_source_ready"] = (structural_ok and row["opportunities"] > 0 and row["source_coverage"] == 1.0
                                  and not row["failed_files"] and not row["parse_errors"] and not row["non_game_records"]
                                  and not row["raw_source_invalid_records"])
    outputs = [{"relative_path": str(p.relative_to(run_dir)), "sha256": digest(p), "rows": pq.ParquetFile(p).metadata.num_rows}
               for p in (unique, flags)]
    atomic_json(directory / "MONTH_REDUCTION.json", {"coverage": row, "outputs": outputs})
    return row, summaries, source_counts, outputs


def evaluate_status(coverage, baseline_expected, months, global_distinct, errors):
    totals = {k: sum(row[k] for row in coverage) for k in baseline_expected}
    baseline_ok = (len(coverage) == len(months) and {r["month"] for r in coverage} == set(months)
                   and totals == baseline_expected and global_distinct == totals["opportunities"]
                   and all(row["panel_and_join_ok"] for row in coverage))
    ready = baseline_ok and not errors and all(row["month_source_ready"] for row in coverage)
    return ("SOURCE_RECOVERY_READY_24M" if ready else "SOURCE_RECOVERY_PARTIAL" if baseline_ok else "SOURCE_RECOVERY_BLOCKED"), baseline_ok, totals


def build_tasks(config, catalog, project, legacy_project, run_dir, verify_resume):
    items = []
    for entry in catalog:
        rel = Path(entry["relative_path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Invalid relative path in catalog")
        items.append({**entry, "path": str(Path(project) / rel)})
    late, late_report = inspect_late(config, project, legacy_project, max(x["file_id"] for x in items) + 1)
    items += late
    tasks = []
    for month in config["months"]:
        panels = [x for x in items if x["month"] == month and x["kind"] == "panel"]
        if len(panels) != 1:
            raise ValueError("Expected one certified panel for " + month)
        tasks.append({"month": month, "panel": panels[0],
                      "inputs": [x for x in items if x["month"] == month and x["kind"] != "panel"],
                      "run_dir": str(run_dir), "verify_resume": verify_resume,
                      "code_sha256": digest(__file__), "catalog_sha256": config["catalog_sha256"]})
    return tasks, items, late_report


def save_report(run_dir, report):
    """Deliberate metadata-only allowlist; no game IDs or private row outputs."""
    run_dir = Path(run_dir)
    destination = run_dir / "report"
    destination.mkdir(exist_ok=True)
    atomic_json(destination / "SOURCE_RECOVERY_REPORT.json", report)
    included = [destination / "SOURCE_RECOVERY_REPORT.json"]
    for key, name in (("coverage", "MONTH_COVERAGE.parquet"), ("descriptives", "OBSERVED_SAMPLE_COUNTS.parquet"),
                      ("source_counts", "SOURCE_COUNTS.parquet")):
        if report.get(key):
            atomic_parquet(destination / name, pa.Table.from_pylist(report[key]))
            included.append(destination / name)
    ready = [r["month"] for r in report.get("coverage", []) if r["month_source_ready"]]
    unresolved = [m for m in report["months"] if m not in ready]
    text = (f"Source recovery {VERSION}\nStatus: {report['status']}\n"
            f"Certified baseline verified: {report.get('baseline_ok', False)}\n"
            f"Months with complete verified source coverage: {', '.join(ready) or 'none'}\n"
            f"Unresolved months: {', '.join(unresolved) or 'none'}\n\n"
            "This report recovers game source for existing Stage 07 opportunities.\n"
            "Pool counts use verified observed coverage and may be incomplete.\n"
            "Rematch analysis and empirical re-estimation: NOT RUN.\n"
            "No API requests, engine work, rating work, or certified input writes.\n"
            "Missing source remains unknown. source_block is never used as API source.\n"
            "Raw response and per-game flags remain in the private directory on the local disk.\n"
            "This private diagnostic contains input paths and hashes, but no per-game rows.\n")
    (destination / "README_REPORT.txt").write_text(text, encoding="utf-8")
    included.append(destination / "README_REPORT.txt")
    included.sort()
    manifest = destination / "REPORT_MANIFEST.sha256"
    manifest.write_text("".join(digest(p) + "  " + p.name + "\n" for p in included), encoding="utf-8")
    archive = run_dir / ("Source_Recovery_24M_Report_" + run_dir.name + ".zip")
    temporary = archive.with_name(archive.name + ".partial")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as z:
        for p in included + [manifest]:
            z.write(p, arcname=run_dir.name + "/" + p.name)
    os.replace(temporary, archive)
    sidecar = archive.with_name(archive.name + ".sha256")
    sidecar.write_text(digest(archive) + "  " + archive.name + "\n", encoding="utf-8")
    print("\n" + report["status"], flush=True)
    print(f"Baseline verified: {report.get('baseline_ok', False)}; source-complete months: {len(ready)}/{len(report['months'])}", flush=True)
    print("Rematch audit and re-estimation: NOT RUN", flush=True)
    print("UPLOAD: " + str(archive), flush=True)
    print("UPLOAD: " + str(sidecar), flush=True)
    return archive


def run_pipeline(config, catalog, project, legacy_project, run_dir, workers=4, threads=8,
                 memory="10GB", verify_resume=False):
    """Library entry point also used by deterministic synthetic regression tests."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    report = {"version": VERSION, "status": "SOURCE_RECOVERY_BLOCKED", "months": config["months"],
              "config": config, "project_root": str(project), "legacy_project_root": str(legacy_project),
              "environment": {"python": sys.version, "executable": sys.executable, "platform": platform.platform(),
                              "duckdb": duckdb.__version__, "pyarrow": pa.__version__, "zstandard": zstd.__version__},
              "settings": {"workers": workers, "threads": threads, "memory": memory, "verify_resume_input_sha256": verify_resume},
              "recovery_code_sha256": digest(__file__), "coverage": [], "descriptives": [], "source_counts": [],
              "errors": [], "empirical_audit": "NOT_RUN", "started_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
    started = time.monotonic()
    con = None
    try:
        tasks, inputs, late_report = build_tasks(config, catalog, project, legacy_project, run_dir, verify_resume)
        report["late_retention_inspection"] = late_report
        report["input_plan"] = inputs
        contract = {"code_sha256": digest(__file__), "config": config, "inputs": inputs}
        contract_path = run_dir / "RUN_CONTRACT.json"
        if contract_path.exists() and json.loads(contract_path.read_text()) != contract:
            raise ValueError("Run contract changed. Use a fresh run directory; existing checkpoints are preserved.")
        atomic_json(contract_path, contract)
        report["producer_checks"] = []
        for relative, expected in config.get("producer_sha256", {}).items():
            p = Path(project) / relative
            observed = digest(p) if p.is_file() else None
            report["producer_checks"].append({"path": str(p), "expected_sha256": expected, "actual_sha256": observed})
            if observed != expected:
                raise ValueError("Producer missing or changed from the locator report: " + str(p))
        for task in tasks:
            require_fingerprint(task["panel"])
        print(f"Recovery plan: {len(tasks)} monthly panels, {sum(len(t['inputs']) for t in tasks)} exact raw files", flush=True)
        results = []
        with futures.ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            pending = {pool.submit(recover_month, task): task["month"] for task in tasks}
            while pending:
                done, _ = futures.wait(pending, timeout=30, return_when=futures.FIRST_COMPLETED)
                if not done:
                    print(f"Recovery active: {len(results)}/{len(tasks)} months finished; {(time.monotonic()-started)/60:.1f} minutes elapsed", flush=True)
                for future in done:
                    month = pending.pop(future)
                    try:
                        result = future.result()
                        results.append(result)
                        report["errors"].extend(result["errors"])
                    except Exception as exc:
                        report["errors"].append({"month": month, "phase": "monthly_recovery", "error": str(exc)})
                        print(f"{month}: month blocked; error recorded: {exc}", flush=True)
        report["file_receipts"] = [{k: v for k, v in receipt.items() if k != "binding"}
                                   for result in sorted(results, key=lambda r: r["month"]) for receipt in result["receipts"]]
        report["panel_receipts"] = [{"month": r["month"], "path": r["panel"]["path"], "sha256": r["panel_sha256"],
                                     "target_ids": r["panel_target_count"]} for r in results]
        spill = run_dir / "private" / "duckdb_spill"
        spill.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect()
        con.execute(f"SET threads={int(threads)}")
        con.execute(f"SET memory_limit={qs(memory)}")
        con.execute(f"SET temp_directory={qs(spill)}")
        con.execute("SET preserve_insertion_order=false")
        report["private_outputs"] = []
        for result in sorted(results, key=lambda r: r["month"]):
            print(result["month"] + ": checking duplicates, source coverage, and Stage 07 join", flush=True)
            coverage, descriptives, sources, outputs = reduce_month(con, result, run_dir)
            report["coverage"].append(coverage)
            report["descriptives"].extend(descriptives)
            report["source_counts"].extend(sources)
            report["private_outputs"].extend(outputs)
            print(f"{result['month']}: verified source {coverage['source_verified_games']:,}/{coverage['opportunities']:,} "
                  f"({coverage['source_coverage']:.2%}); pool {coverage['pool_verified_games']:,}", flush=True)
        flags = [str(run_dir / "private" / r["month"] / "stage07_source_flags.parquet") for r in results]
        global_distinct = 0
        if flags:
            print("Checking game-ID uniqueness across all completed months", flush=True)
            global_distinct = con.execute(f"SELECT count(DISTINCT game_id) FROM {sql_parquets(flags)}").fetchone()[0]
        report["global_distinct_game_ids"] = global_distinct
        report["status"], report["baseline_ok"], report["baseline_totals"] = evaluate_status(
            report["coverage"], config["expected_baseline"], config["months"], global_distinct, report["errors"])
    except Exception as exc:
        report["status"] = "SOURCE_RECOVERY_BLOCKED"
        report["errors"].append({"phase": "pipeline", "error": str(exc), "traceback": traceback.format_exc()})
        print("Recovery blocked; saving diagnostic report: " + str(exc), flush=True)
    finally:
        if con is not None:
            con.close()
    report["elapsed_seconds"] = time.monotonic() - started
    report["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_report(run_dir, report)
    return report


@contextlib.contextmanager
def run_lock(run_dir):
    path = Path(run_dir) / "RUN.lock"
    with path.open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This run is already active in another process") from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default="/Volumes/XT_Pro/lichess_kindness")
    parser.add_argument("--legacy-project-root", default=str(Path.home() / "projects/lichess_kindness"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory", default="10GB")
    parser.add_argument("--resume", help="Existing run directory under this package's output root")
    parser.add_argument("--verify-resume-input-sha256", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 10 or not 1 <= args.threads <= 10:
        parser.error("Workers and DuckDB threads must each be between 1 and 10; phases do not overlap")
    if not re.fullmatch(r"[1-9]\d*(MB|GB)", args.memory):
        parser.error("Memory must have the form 10GB or 4096MB")
    project = Path(args.project_root).expanduser().resolve()
    if not project.is_dir():
        parser.error("Project is not mounted: " + str(project))
    config = json.loads((PACKAGE / "CONFIG.json").read_text())
    catalog_path = PACKAGE / "INPUT_CATALOG.parquet"
    if digest(catalog_path) != config["catalog_sha256"]:
        parser.error("Input catalog checksum mismatch")
    catalog = pq.ParquetFile(catalog_path).read().to_pylist()
    base = project / "output/source_recovery_24m_v1_0_0"
    base.mkdir(parents=True, exist_ok=True)
    if args.resume:
        run_dir = Path(args.resume).expanduser().resolve()
        if run_dir.parent != base.resolve() or not (run_dir / "RUN_CONTRACT.json").is_file():
            parser.error("Resume must name this package's existing owned run directory")
    else:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = base / f"{stamp}_{os.getpid()}"
        run_dir.mkdir(exist_ok=False)
    print("RUN DIRECTORY: " + str(run_dir), flush=True)
    print(f"Free output disk: {shutil.disk_usage(run_dir).free / 1e9:.1f} GB", flush=True)
    print("Inputs are read-only. Source recovery only; empirical audit NOT RUN.", flush=True)
    with run_lock(run_dir):
        atomic_json(run_dir / "INVOCATION.json", {"argv": sys.argv, "cwd": str(Path.cwd()), "executable": sys.executable})
        report = run_pipeline(config, catalog, project, Path(args.legacy_project_root).expanduser().resolve(), run_dir,
                              workers=args.workers, threads=args.threads, memory=args.memory,
                              verify_resume=args.verify_resume_input_sha256)
    return {"SOURCE_RECOVERY_READY_24M": 0, "SOURCE_RECOVERY_PARTIAL": 2, "SOURCE_RECOVERY_BLOCKED": 1}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
