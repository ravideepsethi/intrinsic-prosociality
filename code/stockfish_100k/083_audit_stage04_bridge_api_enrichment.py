#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


STATUS_CANDIDATES = [
    "status",
    "api_status",
    "game_status",
    "lichess_status",
]

ID_CANDIDATES = [
    "id",
    "game_id",
    "api_id",
    "lichess_id",
]


def read_json_maybe(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"_json_read_error": repr(e), "_path": str(path)}


def parquet_rows(path: Path) -> int:
    try:
        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        return -1


def parquet_schema(path: Path) -> list[str]:
    try:
        return pq.ParquetFile(path).schema_arrow.names
    except Exception:
        return []


def sum_rows(files: list[Path]) -> int:
    return int(sum(max(parquet_rows(p), 0) for p in files))


def detect_col(cols: list[str], candidates: list[str]) -> str | None:
    lower = {c.lower(): c for c in cols}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]
    return None


def value_counts_for_col(files: list[Path], candidate_cols: list[str]) -> tuple[str | None, dict[str, int]]:
    detected: str | None = None
    counts: collections.Counter[str] = collections.Counter()

    for path in files:
        cols = parquet_schema(path)
        if detected is None:
            detected = detect_col(cols, candidate_cols)
        if detected is None or detected not in cols:
            continue

        pf = pq.ParquetFile(path)
        for rg in range(pf.num_row_groups):
            t = pf.read_row_groups([rg], columns=[detected])
            s = t.to_pandas()[detected]
            vc = s.astype("string").fillna("<NA>").value_counts(dropna=False)
            for k, v in vc.items():
                counts[str(k)] += int(v)

    return detected, dict(sorted(counts.items()))


def sample_schema_rows(files: list[Path], max_files: int = 5) -> list[dict[str, Any]]:
    rows = []
    for p in files[:max_files]:
        cols = parquet_schema(p)
        rows.append({
            "path": str(p),
            "rows": parquet_rows(p),
            "n_columns": len(cols),
            "columns": ",".join(cols),
            "status_col": detect_col(cols, STATUS_CANDIDATES),
            "id_col": detect_col(cols, ID_CANDIDATES),
        })
    return rows


def month_audit(api_root: Path, month: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    mdir = api_root / f"month={month}"

    request_files = sorted((mdir / "requests").glob("*.parquet")) if mdir.exists() else []
    response_files = sorted((mdir / "responses").glob("*.parquet")) if mdir.exists() else []
    missing_files = sorted((mdir / "missing").glob("*.parquet")) if mdir.exists() else []
    checkpoint_files = sorted((mdir / "_checkpoints").glob("*.success.json")) if mdir.exists() else []
    telemetry_files = sorted((mdir / "telemetry").glob("*.json")) if mdir.exists() else []
    raw_files = sorted((mdir / "raw").glob("*.ndjson.zst")) if mdir.exists() else []

    plan = read_json_maybe(mdir / "_plan.json") or {}
    success = read_json_maybe(mdir / "_SUCCESS.json") or {}

    request_rows = sum_rows(request_files)
    response_rows = sum_rows(response_files)
    missing_rows = sum_rows(missing_files)

    status_col, status_counts = value_counts_for_col(response_files, STATUS_CANDIDATES)

    row = {
        "month": month,
        "month_dir_exists": bool(mdir.exists()),
        "has_plan_json": bool((mdir / "_plan.json").exists()),
        "has_success_json": bool((mdir / "_SUCCESS.json").exists()),
        "request_units": len(request_files),
        "response_units": len(response_files),
        "missing_units": len(missing_files),
        "checkpoint_success_units": len(checkpoint_files),
        "telemetry_units": len(telemetry_files),
        "raw_units": len(raw_files),
        "request_rows": request_rows,
        "response_rows": response_rows,
        "missing_rows": missing_rows,
        "response_plus_missing_rows": response_rows + missing_rows,
        "request_equals_response_plus_missing": bool(request_rows == response_rows + missing_rows and request_rows > 0),
        "response_units_equal_request_units": bool(len(response_files) == len(request_files) and len(request_files) > 0),
        "checkpoint_units_equal_request_units": bool(len(checkpoint_files) == len(request_files) and len(request_files) > 0),
        "strict_complete_no_missing": bool(
            mdir.exists()
            and request_rows > 0
            and request_rows == response_rows + missing_rows
            and missing_rows == 0
            and len(response_files) == len(request_files)
            and len(checkpoint_files) == len(request_files)
            and (mdir / "_SUCCESS.json").exists()
        ),
        "complete_with_missing_ledger": bool(
            mdir.exists()
            and request_rows > 0
            and request_rows == response_rows + missing_rows
            and len(response_files) == len(request_files)
            and len(checkpoint_files) == len(request_files)
            and (mdir / "_SUCCESS.json").exists()
        ),
        "status_col": status_col,
        "timeout_rows": int(status_counts.get("timeout", 0)),
        "outoftime_rows": int(status_counts.get("outoftime", 0)),
        "other_status_rows": int(sum(v for k, v in status_counts.items() if k not in {"timeout", "outoftime"})),
        "plan_keys": ",".join(sorted(plan.keys())) if isinstance(plan, dict) else "",
        "success_keys": ",".join(sorted(success.keys())) if isinstance(success, dict) else "",
    }

    status_rows = [
        {"month": month, "status_col": status_col, "status": k, "rows": v}
        for k, v in status_counts.items()
    ]

    schema_rows = []
    schema_rows += [
        {"month": month, "folder": "requests", **r}
        for r in sample_schema_rows(request_files)
    ]
    schema_rows += [
        {"month": month, "folder": "responses", **r}
        for r in sample_schema_rows(response_files)
    ]
    schema_rows += [
        {"month": month, "folder": "missing", **r}
        for r in sample_schema_rows(missing_files)
    ]

    return row, status_rows, schema_rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-root", required=True)
    ap.add_argument("--months", required=True)
    ap.add_argument("--output-root", required=True)
    args = ap.parse_args()

    api_root = Path(args.api_root).expanduser().resolve()
    out = Path(args.output_root).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    months = [m.strip() for m in args.months.split(",") if m.strip()]

    rows = []
    status_rows = []
    schema_rows = []

    for month in months:
        print(f"Auditing {month}...", flush=True)
        r, sr, scr = month_audit(api_root, month)
        rows.append(r)
        status_rows.extend(sr)
        schema_rows.extend(scr)

    month_df = pd.DataFrame(rows)
    status_df = pd.DataFrame(status_rows)
    schema_df = pd.DataFrame(schema_rows)

    month_csv = out / "stage04_bridge_month_audit.csv"
    status_csv = out / "stage04_bridge_status_counts.csv"
    schema_csv = out / "stage04_bridge_schema_samples.csv"

    month_df.to_csv(month_csv, index=False)
    status_df.to_csv(status_csv, index=False)
    schema_df.to_csv(schema_csv, index=False)

    expected_months_present = bool(month_df["month_dir_exists"].all())
    strict_all_complete = bool(month_df["strict_complete_no_missing"].all()) if len(month_df) else False
    ledger_all_complete = bool(month_df["complete_with_missing_ledger"].all()) if len(month_df) else False

    summary = {
        "status": "ok" if expected_months_present and ledger_all_complete else "incomplete_or_needs_transfer",
        "api_root": str(api_root),
        "output_root": str(out),
        "months": months,
        "missing_month_dirs": month_df.loc[~month_df["month_dir_exists"], "month"].tolist(),
        "months_not_complete_with_ledger": month_df.loc[~month_df["complete_with_missing_ledger"], "month"].tolist(),
        "months_with_missing_rows": month_df.loc[month_df["missing_rows"] > 0, ["month", "missing_rows"]].to_dict(orient="records"),
        "total_request_rows": int(month_df["request_rows"].sum()),
        "total_response_rows": int(month_df["response_rows"].sum()),
        "total_missing_rows": int(month_df["missing_rows"].sum()),
        "total_timeout_rows": int(month_df["timeout_rows"].sum()),
        "total_outoftime_rows": int(month_df["outoftime_rows"].sum()),
        "expected_months_present": expected_months_present,
        "strict_all_complete_no_missing": strict_all_complete,
        "all_complete_with_missing_ledger": ledger_all_complete,
        "month_audit_csv": str(month_csv),
        "status_counts_csv": str(status_csv),
        "schema_samples_csv": str(schema_csv),
    }

    (out / "summary_stage04_bridge_audit.json").write_text(json.dumps(summary, indent=2, sort_keys=True))

    pd.set_option("display.max_rows", 200)
    pd.set_option("display.max_columns", 120)
    pd.set_option("display.width", 260)

    print("\nDONE Stage 04 bridge audit")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("\nMONTH AUDIT:")
    print(month_df.to_string(index=False))
    print("\nSTATUS COUNTS:")
    if len(status_df):
        print(status_df.to_string(index=False))
    else:
        print("(no status counts found)")
    print("\nSCHEMA SAMPLES:")
    print(schema_df.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
