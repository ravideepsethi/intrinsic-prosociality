#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq


BLOCKS = [
    {
        "label": "early_11m",
        "months": [
            "2023-11", "2023-12", "2024-01", "2024-02", "2024-03", "2024-04",
            "2024-05", "2024-06", "2024-07", "2024-08", "2024-09",
        ],
        "expected_rows": 21_600_308,
    },
    {
        "label": "bridge_10m",
        "months": [
            "2024-10", "2024-11", "2024-12", "2025-01", "2025-02",
            "2025-03", "2025-04", "2025-05", "2025-06", "2025-07",
        ],
        "expected_rows": 20_175_915,
    },
    {
        "label": "late_3m",
        "months": ["2025-08", "2025-09", "2025-10"],
        "expected_rows": 5_810_797,
    },
]

EXPECTED_TOTAL_ROWS = 47_587_020
EXPECTED_MONTHS = [m for b in BLOCKS for m in b["months"]]

NODE_CANDIDATES = [
    "sf_nodes_requested",
    "stockfish_nodes",
    "nodes_requested",
    "nodes",
    "node_limit",
]

FEN_CANDIDATES = [
    "fen_after_last_move",
    "final_fen",
    "final_observed_fen",
    "fen",
]

OK_CANDIDATES = [
    "sf_ok",
    "stockfish_ok",
    "ok",
]

ERROR_CANDIDATES = [
    "sf_error",
    "sf_error_message",
    "stockfish_error",
    "error",
    "error_message",
]

EVAL_CANDIDATES = [
    "sf_eval_cp_disconnected",
    "stockfish_eval_cp_disconnected",
    "eval_cp_disconnected",
    "disconnected_eval_cp",
    "sf_eval_cp",
    "stockfish_cp",
    "eval_cp",
]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024 * 8) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_read_error": repr(e), "_path": str(path)}


def find_first(cols: list[str], candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def unique_values(path: Path, col: str, max_values: int = 20) -> list[Any]:
    vals = set()
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(columns=[col], batch_size=200_000):
        arr = batch.column(0)
        for v in pc.unique(arr).to_pylist():
            vals.add(v)
            if len(vals) > max_values:
                return sorted([str(x) for x in vals])[:max_values] + ["<MORE_THAN_LIMIT>"]
    return sorted([str(x) for x in vals])


def nonempty_error_count(path: Path, col: str) -> int:
    # Counts non-null, non-empty error strings if an error column exists.
    n = 0
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(columns=[col], batch_size=200_000):
        s = batch.column(0).to_pandas()
        n += int(s.notna().sum())
        if s.dtype == object:
            n = int(((s.notna()) & (s.astype(str).str.len() > 0)).sum())
    return n


def false_ok_count(path: Path, col: str) -> int:
    n = 0
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(columns=[col], batch_size=200_000):
        s = batch.column(0).to_pandas()
        n += int((s != True).sum())
    return n


def audit_file(path: Path, expected_month: str, block_label: str) -> dict[str, Any]:
    pf = pq.ParquetFile(path)
    cols = pf.schema_arrow.names
    rows = int(pf.metadata.num_rows)

    node_col = find_first(cols, NODE_CANDIDATES)
    fen_col = find_first(cols, FEN_CANDIDATES)
    ok_col = find_first(cols, OK_CANDIDATES)
    error_col = find_first(cols, ERROR_CANDIDATES)
    eval_col = find_first(cols, EVAL_CANDIDATES)

    missing_required = []
    if "game_id" not in cols:
        missing_required.append("game_id")
    if "month" not in cols:
        missing_required.append("month")
    if not fen_col:
        missing_required.append("fen_any")
    if not node_col:
        missing_required.append("nodes_any")

    month_values = unique_values(path, "month") if "month" in cols else []
    node_values = unique_values(path, node_col) if node_col else []

    false_ok_rows = false_ok_count(path, ok_col) if ok_col else 0
    nonempty_error_rows = nonempty_error_count(path, error_col) if error_col else 0

    return {
        "block_label": block_label,
        "month": expected_month,
        "path": str(path),
        "rows": rows,
        "n_columns": len(cols),
        "missing_required": ";".join(missing_required),
        "fen_col": fen_col or "",
        "node_col": node_col or "",
        "ok_col": ok_col or "",
        "error_col": error_col or "",
        "eval_col_detected": eval_col or "",
        "month_values": ";".join(map(str, month_values)),
        "node_values": ";".join(map(str, node_values)),
        "month_values_match_folder": month_values == [expected_month],
        "nodes_all_100000": node_values == ["100000"],
        "false_ok_rows_if_ok_col": false_ok_rows,
        "nonempty_error_rows_if_error_col": nonempty_error_rows,
        "file_sha256": sha256_file(path),
    }


def audit_month(root: Path, month: str, block_label: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    mdir = root / f"month={month}"
    parquet_files = sorted(mdir.glob("part_*.parquet"))
    done_files = sorted(mdir.glob("part_*.done.json"))

    file_rows = []
    paths = []

    for p in parquet_files:
        file_rows.append(audit_file(p, month, block_label))
        paths.append(str(p))

    done_rows = 0
    ok_rows = 0
    error_rows = 0
    malformed_done_files = 0
    for d in done_files:
        j = read_json(d)
        if not isinstance(j, dict):
            malformed_done_files += 1
            continue
        try:
            done_rows += int(j.get("rows", 0))
            ok_rows += int(j.get("ok_rows", 0))
            error_rows += int(j.get("error_rows", 0))
        except Exception:
            malformed_done_files += 1

    parquet_rows = int(sum(r["rows"] for r in file_rows))

    month_status_csv = root / "month_status.csv"
    status_row = {}
    if month_status_csv.exists():
        try:
            ms = pd.read_csv(month_status_csv)
            one = ms[ms["month"].astype(str) == month]
            if len(one) == 1:
                status_row = one.iloc[0].to_dict()
        except Exception as e:
            status_row = {"_month_status_read_error": repr(e)}

    expected_rows = int(status_row.get("expected_rows", parquet_rows)) if status_row else parquet_rows
    expected_parts = int(status_row.get("expected_parts", math.ceil(expected_rows / 100000))) if status_row else math.ceil(expected_rows / 100000)
    status_complete = bool(status_row.get("complete", False)) if status_row else False

    row = {
        "block_label": block_label,
        "root": str(root),
        "month": month,
        "month_dir_exists": mdir.exists(),
        "parquet_files": len(parquet_files),
        "done_files": len(done_files),
        "expected_parts": expected_parts,
        "expected_rows": expected_rows,
        "parquet_rows": parquet_rows,
        "done_rows": done_rows,
        "ok_rows": ok_rows,
        "error_rows": error_rows,
        "malformed_done_files": malformed_done_files,
        "status_complete": status_complete,
        "parts_match_expected": len(parquet_files) == expected_parts and len(done_files) == expected_parts,
        "parquet_equals_done": parquet_rows == done_rows,
        "ok_equals_done": ok_rows == done_rows,
        "no_error_rows": error_rows == 0,
        "parquet_equals_expected": parquet_rows == expected_rows,
    }
    return row, file_rows, paths


def duckdb_duplicate_audit(paths: list[str]) -> dict[str, Any]:
    try:
        import duckdb  # type: ignore
    except Exception as e:
        return {
            "status": "duckdb_not_available",
            "error": repr(e),
            "total_rows": None,
            "distinct_game_ids": None,
            "duplicate_game_id_rows": None,
        }

    escaped = "[" + ",".join("'" + p.replace("'", "''") + "'" for p in paths) + "]"
    query = f"""
        SELECT
          COUNT(*)::UBIGINT AS total_rows,
          COUNT(DISTINCT game_id)::UBIGINT AS distinct_game_ids,
          (COUNT(*) - COUNT(DISTINCT game_id))::UBIGINT AS duplicate_game_id_rows
        FROM read_parquet({escaped}, union_by_name=true);
    """
    try:
        con = duckdb.connect(database=":memory:")
        row = con.execute(query).fetchone()
        return {
            "status": "ok",
            "total_rows": int(row[0]),
            "distinct_game_ids": int(row[1]),
            "duplicate_game_id_rows": int(row[2]),
        }
    except Exception as e:
        return {
            "status": "duckdb_failed",
            "error": repr(e),
            "total_rows": None,
            "distinct_game_ids": None,
            "duplicate_game_id_rows": None,
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--early-root", required=True)
    ap.add_argument("--bridge-root", required=True)
    ap.add_argument("--late-root", required=True)
    ap.add_argument("--output-root", required=True)
    args = ap.parse_args()

    roots = {
        "early_11m": Path(args.early_root).resolve(),
        "bridge_10m": Path(args.bridge_root).resolve(),
        "late_3m": Path(args.late_root).resolve(),
    }

    out = Path(args.output_root).resolve()
    out.mkdir(parents=True, exist_ok=True)

    all_month_rows = []
    all_file_rows = []
    all_paths = []

    for block in BLOCKS:
        label = block["label"]
        root = roots[label]
        print(f"\nAuditing block {label}: {root}", flush=True)

        block_rows_before = len(all_month_rows)
        for month in block["months"]:
            print(f"  {month}", flush=True)
            month_row, file_rows, paths = audit_month(root, month, label)
            all_month_rows.append(month_row)
            all_file_rows.extend(file_rows)
            all_paths.extend(paths)

        block_df = pd.DataFrame(all_month_rows[block_rows_before:])
        got = int(block_df["parquet_rows"].sum())
        print(f"  block rows: {got:,}", flush=True)

    path_list = out / "sf100k_full_24m_parquet_paths.txt"
    path_list.write_text("".join(p + "\n" for p in all_paths))

    month_df = pd.DataFrame(all_month_rows)
    file_df = pd.DataFrame(all_file_rows)

    month_csv = out / "sf100k_full_24m_month_audit.csv"
    file_csv = out / "sf100k_full_24m_file_audit.csv"

    month_df.to_csv(month_csv, index=False)
    file_df.to_csv(file_csv, index=False)

    print("\nRunning global duplicate game_id audit with DuckDB, if available...", flush=True)
    dup = duckdb_duplicate_audit(all_paths)

    observed_months = month_df.loc[month_df["month_dir_exists"], "month"].astype(str).tolist()
    missing_months = [m for m in EXPECTED_MONTHS if m not in observed_months]
    extra_months = sorted(set(observed_months) - set(EXPECTED_MONTHS))

    checks = {
        "all_expected_months_present": len(missing_months) == 0,
        "no_extra_months": len(extra_months) == 0,
        "all_months_complete": bool(month_df["status_complete"].all()),
        "all_parts_match_expected": bool(month_df["parts_match_expected"].all()),
        "all_parquet_equals_done": bool(month_df["parquet_equals_done"].all()),
        "all_ok_equals_done": bool(month_df["ok_equals_done"].all()),
        "no_error_rows": bool(month_df["no_error_rows"].all()),
        "all_parquet_equals_expected": bool(month_df["parquet_equals_expected"].all()),
        "total_rows_match_expected": int(month_df["parquet_rows"].sum()) == EXPECTED_TOTAL_ROWS,
        "all_files_required_cols_present": bool((file_df["missing_required"].fillna("") == "").all()),
        "all_files_month_values_match_folder": bool(file_df["month_values_match_folder"].all()),
        "all_files_nodes_100000": bool(file_df["nodes_all_100000"].all()),
        "all_files_no_false_ok_if_ok_col": bool((file_df["false_ok_rows_if_ok_col"].fillna(0) == 0).all()),
        "all_files_no_nonempty_error_if_error_col": bool((file_df["nonempty_error_rows_if_error_col"].fillna(0) == 0).all()),
        "duckdb_duplicate_audit_ok": dup.get("status") == "ok",
        "global_game_ids_unique": dup.get("status") == "ok" and int(dup.get("duplicate_game_id_rows") or -1) == 0,
    }

    block_totals = month_df.groupby("block_label")["parquet_rows"].sum().to_dict()

    summary = {
        "status": "ok" if all(checks.values()) else "needs_review",
        "output_root": str(out),
        "roots": {k: str(v) for k, v in roots.items()},
        "expected_months": EXPECTED_MONTHS,
        "missing_months": missing_months,
        "extra_months": extra_months,
        "n_months": int(len(month_df)),
        "n_parquet_files": int(len(file_df)),
        "expected_total_rows": EXPECTED_TOTAL_ROWS,
        "total_parquet_rows": int(month_df["parquet_rows"].sum()),
        "total_done_rows": int(month_df["done_rows"].sum()),
        "total_ok_rows": int(month_df["ok_rows"].sum()),
        "total_error_rows": int(month_df["error_rows"].sum()),
        "block_totals": {k: int(v) for k, v in block_totals.items()},
        "checks": checks,
        "duplicate_audit": dup,
        "path_list": str(path_list),
        "month_audit_csv": str(month_csv),
        "file_audit_csv": str(file_csv),
    }

    summary_path = out / "summary_sf100k_full_24m_audit.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))

    pd.set_option("display.max_rows", 200)
    pd.set_option("display.max_columns", 120)
    pd.set_option("display.width", 260)

    print("\nDONE full 24-month 100k audit")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("\nMONTH AUDIT:")
    print(month_df.to_string(index=False))
    print("\nFILE AUDIT HEAD:")
    print(file_df.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
