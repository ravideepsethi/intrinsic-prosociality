#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


EXPECTED_TOTAL_ROWS = 47_587_020

NODE_NAME_HINTS = ("node", "nodes")
FEN_NAME_HINTS = ("fen",)
EVAL_NAME_HINTS = ("eval", "score", "cp", "mate")
OK_NAME_HINTS = ("ok",)
ERROR_NAME_HINTS = ("error",)


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def hint_cols(cols: list[str], hints: tuple[str, ...]) -> list[str]:
    out = []
    for c in cols:
        lc = c.lower()
        if any(h in lc for h in hints):
            out.append(c)
    return out


def unique_values_for_col(path: Path, col: str, limit: int = 20) -> list[str]:
    vals = set()
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(columns=[col], batch_size=200_000):
        for v in batch.column(0).to_pylist():
            vals.add(str(v))
            if len(vals) > limit:
                return sorted(vals)[:limit] + ["<MORE_THAN_LIMIT>"]
    return sorted(vals)


def schema_review(paths: list[Path], out: Path) -> dict:
    rows = []
    node_cols_seen = {}
    missing_basic = []

    for i, p in enumerate(paths, 1):
        pf = pq.ParquetFile(p)
        cols = pf.schema_arrow.names

        node_cols = hint_cols(cols, NODE_NAME_HINTS)
        fen_cols = hint_cols(cols, FEN_NAME_HINTS)
        eval_cols = hint_cols(cols, EVAL_NAME_HINTS)
        ok_cols = hint_cols(cols, OK_NAME_HINTS)
        error_cols = hint_cols(cols, ERROR_NAME_HINTS)

        month = ""
        parts = [part for part in p.parts if part.startswith("month=")]
        if parts:
            month = parts[-1].split("=", 1)[1]

        node_values = {}
        for c in node_cols:
            vals = unique_values_for_col(p, c)
            node_values[c] = vals
            node_cols_seen.setdefault(c, set()).update(vals)

        basic_missing = []
        for c in ["game_id", "month"]:
            if c not in cols:
                basic_missing.append(c)
        if not fen_cols:
            basic_missing.append("fen_like_column")
        if not eval_cols:
            basic_missing.append("eval_like_column")

        if basic_missing:
            missing_basic.append(str(p))

        rows.append({
            "path": str(p),
            "month": month,
            "rows": pf.metadata.num_rows,
            "n_columns": len(cols),
            "basic_missing": ";".join(basic_missing),
            "node_cols": ";".join(node_cols),
            "node_values_json": json.dumps(node_values, sort_keys=True),
            "fen_cols": ";".join(fen_cols),
            "eval_cols": ";".join(eval_cols),
            "ok_cols": ";".join(ok_cols),
            "error_cols": ";".join(error_cols),
            "columns": ",".join(cols),
        })

        if i % 50 == 0:
            print(f"schema reviewed {i}/{len(paths)} files", flush=True)

    schema_csv = out / "schema_node_review.csv"
    pd.DataFrame(rows).to_csv(schema_csv, index=False)

    node_cols_seen_clean = {k: sorted(v) for k, v in node_cols_seen.items()}
    files_with_node_col = sum(1 for r in rows if r["node_cols"])
    files_without_node_col = len(rows) - files_with_node_col

    # Root-level provenance: logs and folder names should show this was a 100k run
    # even if not every parquet carries a node-count column.
    prior_summary = read_json(out.parent / "summary_sf100k_full_24m_audit.json")
    root_provenance = []
    if isinstance(prior_summary, dict):
        roots = prior_summary.get("roots", {})
    else:
        roots = {}

    for label, root_s in roots.items():
        root = Path(root_s)
        log_hits = []
        for name in ["plan.log", "pilot.log", "production.log", "run.log"]:
            lp = root / name
            if lp.exists():
                txt = lp.read_text(errors="ignore")
                if "nodes=100000" in txt or "100000 nodes" in txt or "nodes 100000" in txt:
                    log_hits.append(str(lp))
        root_provenance.append({
            "label": label,
            "root": str(root),
            "root_name_contains_100k": "100K" in root.name.upper() or "100000" in root.name,
            "log_files_with_100k": log_hits,
            "has_log_node_proof": bool(log_hits),
        })

    root_prov_csv = out / "root_node_provenance.csv"
    pd.DataFrame(root_provenance).to_csv(root_prov_csv, index=False)

    all_explicit_node_values_100k = False
    if files_with_node_col == len(rows) and node_cols_seen_clean:
        all_vals = []
        for vals in node_cols_seen_clean.values():
            all_vals.extend(vals)
        all_explicit_node_values_100k = set(all_vals) == {"100000"}

    all_roots_have_100k_provenance = bool(root_provenance) and all(
        r["root_name_contains_100k"] or r["has_log_node_proof"]
        for r in root_provenance
    )

    return {
        "schema_csv": str(schema_csv),
        "root_node_provenance_csv": str(root_prov_csv),
        "files": len(rows),
        "files_with_node_col": files_with_node_col,
        "files_without_node_col": files_without_node_col,
        "node_cols_seen": node_cols_seen_clean,
        "all_explicit_node_values_100k": all_explicit_node_values_100k,
        "all_roots_have_100k_provenance": all_roots_have_100k_provenance,
        "root_provenance": root_provenance,
        "files_missing_basic_columns": len(missing_basic),
        "basic_columns_ok": len(missing_basic) == 0,
    }


def write_game_ids(paths: list[Path], ids_path: Path) -> dict:
    total = 0
    missing = 0

    with ids_path.open("wb") as out:
        for i, p in enumerate(paths, 1):
            pf = pq.ParquetFile(p)
            cols = pf.schema_arrow.names
            if "game_id" not in cols:
                raise RuntimeError(f"missing game_id in {p}")

            for batch in pf.iter_batches(columns=["game_id"], batch_size=250_000):
                arr = batch.column(0)
                for v in arr.to_pylist():
                    total += 1
                    if v is None:
                        missing += 1
                        out.write(b"\n")
                    else:
                        out.write(str(v).encode("utf-8") + b"\n")

            if i % 25 == 0:
                print(f"wrote game_ids from {i}/{len(paths)} files; rows={total:,}", flush=True)

    return {"total_ids_written": total, "missing_game_ids": missing}


def sort_and_count_duplicates(ids_path: Path, sorted_path: Path, tmp_dir: Path, samples_csv: Path) -> dict:
    print("sorting game_id list with external sort...", flush=True)
    cmd = ["/usr/bin/env", "LC_ALL=C", "sort", "-T", str(tmp_dir), str(ids_path), "-o", str(sorted_path)]
    subprocess.run(cmd, check=True)

    print("scanning sorted game_id list for duplicates...", flush=True)

    total = 0
    distinct = 0
    duplicate_game_ids = 0
    duplicate_rows = 0
    samples = []

    prev = None
    run_count = 0

    def finish_run(value: bytes | None, count: int):
        nonlocal distinct, duplicate_game_ids, duplicate_rows, samples
        if value is None:
            return
        distinct += 1
        if count > 1:
            duplicate_game_ids += 1
            duplicate_rows += count - 1
            if len(samples) < 50:
                samples.append((value.decode("utf-8", errors="replace"), count))

    with sorted_path.open("rb") as f:
        for line in f:
            total += 1
            val = line.rstrip(b"\n")
            if prev is None:
                prev = val
                run_count = 1
            elif val == prev:
                run_count += 1
            else:
                finish_run(prev, run_count)
                prev = val
                run_count = 1

    finish_run(prev, run_count)

    with samples_csv.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_id", "count"])
        w.writerows(samples)

    return {
        "total_rows_seen": total,
        "distinct_game_ids": distinct,
        "duplicate_game_ids": duplicate_game_ids,
        "duplicate_game_id_rows": duplicate_rows,
        "duplicate_samples_csv": str(samples_csv),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prior-audit-root", required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--keep-temp-id-lists", action="store_true")
    args = ap.parse_args()

    prior = Path(args.prior_audit_root).resolve()
    out = Path(args.output_root).resolve()
    out.mkdir(parents=True, exist_ok=True)

    prior_summary_path = prior / "summary_sf100k_full_24m_audit.json"
    prior_summary = read_json(prior_summary_path)
    if not isinstance(prior_summary, dict):
        raise SystemExit(f"Could not read prior summary: {prior_summary_path}")

    path_list = Path(prior_summary["path_list"])
    paths = [Path(x.strip()) for x in path_list.read_text().splitlines() if x.strip()]

    print(f"Loaded {len(paths)} parquet paths from {path_list}", flush=True)

    schema = schema_review(paths, out)

    tmp = out / "_tmp_duplicate_game_id_sort"
    tmp.mkdir(parents=True, exist_ok=True)
    ids_path = tmp / "game_ids_unsorted.txt"
    sorted_path = tmp / "game_ids_sorted.txt"
    samples_csv = out / "duplicate_game_id_samples.csv"

    write_summary = write_game_ids(paths, ids_path)
    duplicate_summary = sort_and_count_duplicates(ids_path, sorted_path, tmp, samples_csv)

    if not args.keep_temp_id_lists:
        try:
            ids_path.unlink()
        except FileNotFoundError:
            pass
        try:
            sorted_path.unlink()
        except FileNotFoundError:
            pass
        try:
            shutil.rmtree(tmp)
        except FileNotFoundError:
            pass

    row_checks_from_prior = {
        k: v for k, v in prior_summary.get("checks", {}).items()
        if k not in {
            "all_files_nodes_100000",
            "all_files_required_cols_present",
            "duckdb_duplicate_audit_ok",
            "global_game_ids_unique",
        }
    }

    row_checks_clean = all(row_checks_from_prior.values())
    duplicates_clean = (
        duplicate_summary["total_rows_seen"] == EXPECTED_TOTAL_ROWS
        and duplicate_summary["distinct_game_ids"] == EXPECTED_TOTAL_ROWS
        and duplicate_summary["duplicate_game_id_rows"] == 0
        and duplicate_summary["duplicate_game_ids"] == 0
    )

    # Node status:
    # explicit_node_column_ok if every parquet contains a node column with only 100000.
    # external_node_provenance_ok if explicit per-file column is absent but roots/logs establish 100k provenance.
    explicit_node_column_ok = schema["all_explicit_node_values_100k"]
    external_node_provenance_ok = schema["all_roots_have_100k_provenance"]

    status = "ok"
    review_notes = []

    if not row_checks_clean:
        status = "needs_review"
        review_notes.append("Prior row/month/part checks were not all clean.")

    if not schema["basic_columns_ok"]:
        status = "needs_review"
        review_notes.append("Some files are missing basic game_id/month/fen/eval-like columns.")

    if not duplicates_clean:
        status = "needs_review"
        review_notes.append("Global duplicate game_id audit did not pass.")

    if not explicit_node_column_ok:
        if external_node_provenance_ok:
            review_notes.append(
                "Parquet files do not all expose a detected node-count column; node=100000 is supported by root/log provenance rather than per-row metadata."
            )
        else:
            status = "needs_review"
            review_notes.append(
                "Could not establish node=100000 from either explicit columns or root/log provenance."
            )

    summary = {
        "status": status,
        "prior_audit_root": str(prior),
        "output_root": str(out),
        "expected_total_rows": EXPECTED_TOTAL_ROWS,
        "prior_total_rows": prior_summary.get("total_parquet_rows"),
        "prior_row_checks_excluding_node_and_duckdb": row_checks_from_prior,
        "row_month_part_checks_clean": row_checks_clean,
        "schema_review": schema,
        "game_id_extract": write_summary,
        "duplicate_audit": duplicate_summary,
        "duplicates_clean": duplicates_clean,
        "explicit_node_column_ok": explicit_node_column_ok,
        "external_node_provenance_ok": external_node_provenance_ok,
        "review_notes": review_notes,
        "temp_id_lists_kept": bool(args.keep_temp_id_lists),
    }

    summary_path = out / "summary_sf100k_full_24m_review.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    print("\nDONE corrective full 24m review")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
