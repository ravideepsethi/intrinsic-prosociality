#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


CANDIDATE_COLS = [
    "archive_month",
    "month",
    "game_id",
    "site",
    "candidate_chooser",
    "candidate_chooser_color",
    "candidate_chooser_color_norm",
    "likely_disconnected_player",
    "likely_disconnected_color",
    "side_to_move_after_last",
    "fen_after_last_move",
    "ply_count",
    "result",
    "termination",
    "api_status",
    "api_speed",
    "api_perf",
    "api_rated",
    "timeout_draw",
    "outcome_kind_draw",
    "chooser_has_mating_material",
    "chooser_draw_payoff_v2",
    "chooser_win_payoff_v2",
    "chooser_win_premium_v2",
    "candidate_chooser_elo",
    "likely_disconnected_elo",
    "disconnected_clock_last_obs_s",
    "chooser_clock_last_obs_s",
    "tournament_like_event",
]


def read_paths(root: Path) -> list[Path]:
    preferred = [
        root / "patched_parquet_paths.txt",
        root / "timeout_api_v2_outcome_fairness_nodes10000_parquet_paths.txt",
        root / "parquet_paths.txt",
    ]
    for p in preferred:
        if p.exists():
            rows = [Path(x.strip()) for x in p.read_text().splitlines() if x.strip() and not x.strip().startswith("#")]
            rows = [x for x in rows if x.exists()]
            if rows:
                return rows

    txts = sorted(root.rglob("*parquet_paths*.txt"))
    for t in txts:
        rows = [Path(x.strip()) for x in t.read_text().splitlines() if x.strip() and not x.strip().startswith("#")]
        rows = [x for x in rows if x.exists()]
        if rows:
            return rows

    candidates = []
    for p in sorted(root.rglob("*.parquet")):
        try:
            cols = pq.ParquetFile(p).schema_arrow.names
        except Exception:
            continue
        if "game_id" in cols and "fen_after_last_move" in cols:
            candidates.append(p)

    if not candidates:
        raise SystemExit(f"No usable input parquets found under {root}")
    return candidates


def detect_month_col(cols: list[str]) -> str:
    for c in ["month", "archive_month", "rawv2_month"]:
        if c in cols:
            return c
    raise SystemExit(f"No usable month column in schema: {cols}")


def norm_month_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.extract(r"([0-9]{4}-[0-9]{2})", expand=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--months", required=True)
    ap.add_argument("--output-root", required=True)
    args = ap.parse_args()

    source_root = Path(args.source_root).expanduser().resolve()
    out_root = Path(args.output_root).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    wanted = [m.strip() for m in args.months.split(",") if m.strip()]
    wanted_set = set(wanted)

    paths = read_paths(source_root)

    print(f"Found {len(paths)} candidate source parquet files.")
    for p in paths[:20]:
        print(f"  {p}")
    if len(paths) > 20:
        print(f"  ... {len(paths)-20} more")

    writers: dict[str, pq.ParquetWriter] = {}
    out_paths = {m: out_root / f"month={m}.parquet" for m in wanted}

    # Remove stale partial outputs if this prep root is reused.
    for p in out_paths.values():
        if p.exists():
            p.unlink()

    audit_rows = []
    month_counts = {m: 0 for m in wanted}

    try:
        for path in paths:
            pf = pq.ParquetFile(path)
            cols = pf.schema_arrow.names
            if "game_id" not in cols or "fen_after_last_move" not in cols:
                continue

            month_col = detect_month_col(cols)
            read_cols = [c for c in CANDIDATE_COLS if c in cols]
            if month_col not in read_cols:
                read_cols.append(month_col)

            source_rows = 0
            kept_rows = 0

            for rg in range(pf.num_row_groups):
                table = pf.read_row_groups([rg], columns=read_cols)
                df = table.to_pandas()
                source_rows += len(df)

                mm = norm_month_series(df[month_col])
                keep = mm.isin(wanted_set)
                if not keep.any():
                    continue

                df = df.loc[keep].copy()
                df["month"] = mm.loc[keep].values

                # Keep only columns used by the 100k evaluator.
                output_cols = [c for c in CANDIDATE_COLS if c in df.columns]
                if "game_id" not in output_cols or "fen_after_last_move" not in output_cols:
                    raise SystemExit(f"Required columns missing after filtering {path}")

                for m in wanted:
                    sub = df[df["month"] == m].copy()
                    if sub.empty:
                        continue

                    sub = sub[output_cols]
                    t = pa.Table.from_pandas(sub, preserve_index=False)

                    if m not in writers:
                        writers[m] = pq.ParquetWriter(out_paths[m], t.schema, compression="zstd")
                    writers[m].write_table(t)

                    n = len(sub)
                    kept_rows += n
                    month_counts[m] += n

            audit_rows.append({
                "source_path": str(path),
                "source_rows_scanned": int(source_rows),
                "kept_rows": int(kept_rows),
                "month_col": month_col,
            })
            print(f"scanned {path.name}: source_rows={source_rows:,}; kept_rows={kept_rows:,}", flush=True)

    finally:
        for w in writers.values():
            w.close()

    missing = [m for m in wanted if month_counts[m] == 0 or not out_paths[m].exists()]
    if missing:
        raise SystemExit(f"Prepared zero rows or missing output for months: {missing}")

    paths_file = out_root / "aug_oct_2025_sf100k_input_paths.txt"
    with paths_file.open("w") as f:
        for m in wanted:
            f.write(str(out_paths[m]) + "\n")

    audit = {
        "source_root": str(source_root),
        "output_root": str(out_root),
        "months": wanted,
        "month_counts": month_counts,
        "paths_file": str(paths_file),
        "total_rows": int(sum(month_counts.values())),
        "source_files": [str(p) for p in paths],
    }

    pd.DataFrame(audit_rows).to_csv(out_root / "input_prep_source_audit.csv", index=False)
    pd.DataFrame([{"month": m, "rows": month_counts[m], "path": str(out_paths[m])} for m in wanted]).to_csv(
        out_root / "input_prep_month_counts.csv", index=False
    )
    (out_root / "input_prep_summary.json").write_text(json.dumps(audit, indent=2, sort_keys=True))

    print("\nDONE input prep")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
