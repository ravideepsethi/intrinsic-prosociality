#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


EXPECTED_MONTHS = [
    "2023-11","2023-12",
    "2024-01","2024-02","2024-03","2024-04","2024-05","2024-06","2024-07","2024-08","2024-09",
    "2025-08","2025-09","2025-10",
]


REQUIRED_COLS = [
    "game_id",
    "fen_after_last_move",
    "sf100k_ok",
    "sf100k_error",
    "sf100k_eval_cp_disconnected",
    "sf100k_eval_cp_disconnected_capped600",
    "sf100k_engine_fairness_bin",
    "sf100k_fair_subset_main",
    "sf100k_clearly_worse_subset",
    "sf100k_nodes_requested",
    "sf100k_stockfish_name",
    "sf100k_stockfish_sha256",
]


def sha256_file(path: Path, block_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(block_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def read_paths(path: Path) -> list[Path]:
    return [Path(x.strip()) for x in path.read_text().splitlines() if x.strip() and not x.strip().startswith("#")]


def audit_root(root: Path, label: str) -> tuple[pd.DataFrame, list[Path], dict]:
    summary_path = root / "summary.json"
    month_status_path = root / "month_status.csv"
    paths_file = root / "sf100k_parquet_paths.txt"

    if not summary_path.exists():
        raise SystemExit(f"Missing summary.json: {summary_path}")
    if not month_status_path.exists():
        raise SystemExit(f"Missing month_status.csv: {month_status_path}")
    if not paths_file.exists():
        raise SystemExit(f"Missing path list: {paths_file}")

    summary = read_json(summary_path)
    status = pd.read_csv(month_status_path)
    paths = read_paths(paths_file)

    missing_files = [str(p) for p in paths if not p.exists()]
    if missing_files:
        raise SystemExit(f"Missing parquet files in {label}: {missing_files[:10]}")

    status["block_label"] = label
    status["root"] = str(root)

    return status, paths, summary


def file_level_audit(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for p in paths:
        pf = pq.ParquetFile(p)
        cols = pf.schema_arrow.names
        missing_cols = [c for c in REQUIRED_COLS if c not in cols]

        # Small column read for cheap row-level stats.
        read_cols = [c for c in ["game_id", "month", "archive_month", "sf100k_ok", "sf100k_error", "sf100k_nodes_requested", "sf100k_engine_fairness_bin"] if c in cols]
        df = pd.read_parquet(p, columns=read_cols)

        if "month" in df.columns:
            month_vals = sorted(df["month"].astype(str).unique().tolist())
        elif "archive_month" in df.columns:
            month_vals = sorted(df["archive_month"].astype(str).unique().tolist())
        else:
            month_vals = []

        ok_rows = int(df["sf100k_ok"].fillna(False).sum()) if "sf100k_ok" in df.columns else None
        err_rows = int((~df["sf100k_ok"].fillna(False)).sum()) if "sf100k_ok" in df.columns else None
        nodes_vals = sorted(df["sf100k_nodes_requested"].dropna().unique().tolist()) if "sf100k_nodes_requested" in df.columns else []

        rows.append({
            "path": str(p),
            "rows": int(pf.metadata.num_rows),
            "columns": len(cols),
            "missing_required_cols": ",".join(missing_cols),
            "month_values": ",".join(month_vals),
            "ok_rows": ok_rows,
            "error_rows": err_rows,
            "nodes_values": ",".join(str(x) for x in nodes_vals),
            "file_sha256": sha256_file(p),
        })
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root-11m", required=True)
    ap.add_argument("--root-augoct", required=True)
    ap.add_argument("--output-root", required=True)
    args = ap.parse_args()

    out = Path(args.output_root).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    root_11m = Path(args.root_11m).expanduser().resolve()
    root_augoct = Path(args.root_augoct).expanduser().resolve()

    status_11m, paths_11m, summary_11m = audit_root(root_11m, "2023-11_to_2024-09")
    status_augoct, paths_augoct, summary_augoct = audit_root(root_augoct, "2025-08_to_2025-10")

    status = pd.concat([status_11m, status_augoct], ignore_index=True)
    status.to_csv(out / "combined_month_status_14m.csv", index=False)

    all_paths = paths_11m + paths_augoct
    with (out / "sf100k_completed_14m_parquet_paths.txt").open("w") as f:
        for p in all_paths:
            f.write(str(p) + "\n")

    file_audit = file_level_audit(all_paths)
    file_audit.to_csv(out / "file_level_audit_14m.csv", index=False)

    observed_months = sorted(status["month"].astype(str).tolist())
    expected_set = set(EXPECTED_MONTHS)
    observed_set = set(observed_months)

    total_expected = int(status["expected_rows"].sum())
    total_done = int(status["done_rows"].sum())
    total_ok = int(status["ok_rows"].sum())
    total_errors = int(status["error_rows"].sum())

    checks = {
        "root_11m_complete": bool(summary_11m.get("complete")),
        "root_augoct_complete": bool(summary_augoct.get("complete")),
        "all_month_status_complete": bool(status["complete"].all()),
        "all_required_months_present": observed_set == expected_set,
        "no_extra_months": observed_set <= expected_set,
        "no_missing_months": expected_set <= observed_set,
        "no_error_rows": total_errors == 0,
        "done_equals_expected": total_done == total_expected,
        "ok_equals_done": total_ok == total_done,
        "all_file_required_cols_present": bool((file_audit["missing_required_cols"].fillna("") == "").all()),
        "all_nodes_requested_100000": bool(file_audit["nodes_values"].eq("100000").all()),
    }

    summary = {
        "status": "ok" if all(checks.values()) else "check_failed",
        "output_root": str(out),
        "root_11m": str(root_11m),
        "root_augoct": str(root_augoct),
        "expected_months": EXPECTED_MONTHS,
        "observed_months": observed_months,
        "missing_months": sorted(expected_set - observed_set),
        "extra_months": [],
        "total_expected_rows": total_expected,
        "total_done_rows": total_done,
        "total_ok_rows": total_ok,
        "total_error_rows": total_errors,
        "n_parquet_files": len(all_paths),
        "combined_path_list": str(out / "sf100k_completed_14m_parquet_paths.txt"),
        "combined_month_status": str(out / "combined_month_status_14m.csv"),
        "file_level_audit": str(out / "file_level_audit_14m.csv"),
        "checks": checks,
    }

    # Fix Python syntax for extra_months after JSON dict construction.
    summary["extra_months"] = sorted(observed_set - expected_set)

    (out / "summary_14m_audit.json").write_text(json.dumps(summary, indent=2, sort_keys=True))

    print("\nDONE 14-month 100k audit")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("\nMONTH STATUS:")
    print(status.to_string(index=False))
    print("\nFILE AUDIT HEAD:")
    print(file_audit.head(20).to_string(index=False))


if __name__ == "__main__":
    main()
