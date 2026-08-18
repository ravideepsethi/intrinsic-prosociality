#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


MATE_SENTINEL = 10000

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


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def sha256_file(path: Path, block_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(block_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_paths_file(path: Path) -> list[Path]:
    rows = []
    for line in path.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            rows.append(Path(s))
    return rows


def month_from_path(path: Path) -> str | None:
    s = str(path)
    m = re.search(r"month=([0-9]{4}-[0-9]{2})", s)
    if m:
        return m.group(1)
    m = re.search(r"([0-9]{4}-[0-9]{2})", path.name)
    if m:
        return m.group(1)
    return None


def select_paths(paths_file: Path, months_csv: str) -> list[dict[str, Any]]:
    wanted = [m.strip() for m in months_csv.split(",") if m.strip()]
    wanted_set = set(wanted)
    paths = read_paths_file(paths_file)

    found: dict[str, Path] = {}
    for p in paths:
        m = month_from_path(p)
        if m in wanted_set:
            found[m] = p

    missing = [m for m in wanted if m not in found]
    if missing:
        raise SystemExit(f"Missing requested months in paths file: {missing}")

    selected = []
    for m in wanted:
        p = found[m]
        if not p.exists():
            raise SystemExit(f"Selected parquet does not exist: {p}")
        pf = pq.ParquetFile(p)
        selected.append(
            {
                "month": m,
                "path": str(p),
                "rows": int(pf.metadata.num_rows),
                "columns": pf.schema_arrow.names,
                "file_sha256": sha256_file(p),
            }
        )
    return selected


def available_columns(path: Path) -> list[str]:
    return pq.ParquetFile(path).schema_arrow.names


def columns_to_read(path: Path) -> list[str]:
    cols = available_columns(path)
    keep = [c for c in CANDIDATE_COLS if c in cols]
    required = ["game_id", "fen_after_last_move"]
    missing = [c for c in required if c not in keep]
    if missing:
        raise SystemExit(f"Missing required columns {missing} in {path}")
    return keep


def read_head_parquet(path: Path, columns: list[str], n: int) -> pd.DataFrame:
    pf = pq.ParquetFile(path)
    pieces = []
    got = 0
    for rg in range(pf.num_row_groups):
        t = pf.read_row_groups([rg], columns=columns)
        d = t.to_pandas()
        pieces.append(d)
        got += len(d)
        if got >= n:
            break
    if not pieces:
        return pd.DataFrame(columns=columns)
    return pd.concat(pieces, ignore_index=True).head(n).copy()


def detect_stockfish(path_arg: str | None) -> Path:
    candidates = []
    if path_arg:
        candidates.append(path_arg)
    if os.environ.get("STOCKFISH_BIN"):
        candidates.append(os.environ["STOCKFISH_BIN"])
    found = shutil.which("stockfish")
    if found:
        candidates.append(found)
    candidates.extend(
        [
            "/opt/homebrew/bin/stockfish",
            "/usr/local/bin/stockfish",
        ]
    )

    for c in candidates:
        if not c:
            continue
        p = Path(c).expanduser()
        if p.exists() and os.access(p, os.X_OK):
            return p
    raise SystemExit("Could not find executable Stockfish. Pass --stockfish-bin or set STOCKFISH_BIN.")


class StockfishUCI:
    def __init__(self, bin_path: str, threads: int, hash_mb: int):
        self.proc = subprocess.Popen(
            [bin_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("Could not open Stockfish pipes.")
        self.name = "Stockfish_UNKNOWN"

        self._send("uci")
        for line in self._read_until("uciok"):
            if line.startswith("id name "):
                self.name = line.replace("id name ", "", 1).strip()

        self._send(f"setoption name Threads value {threads}")
        self._send(f"setoption name Hash value {hash_mb}")
        self._send("setoption name UCI_AnalyseMode value true")
        self._send("isready")
        self._read_until("readyok")
        self._send("ucinewgame")
        self._send("isready")
        self._read_until("readyok")

    def _send(self, cmd: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def _read_until(self, token: str) -> list[str]:
        assert self.proc.stdout is not None
        lines = []
        while True:
            line = self.proc.stdout.readline()
            if line == "":
                raise RuntimeError(f"Stockfish exited before {token}.")
            s = line.strip()
            lines.append(s)
            if s == token or s.startswith(token + " "):
                return lines

    def evaluate(self, fen: str, nodes: int) -> dict[str, Any]:
        assert self.proc.stdout is not None

        self._send(f"position fen {fen}")
        self._send(f"go nodes {nodes}")

        latest: dict[str, Any] = {
            "score_type": None,
            "score_value": None,
            "depth": None,
            "seldepth": None,
            "nodes": None,
            "nps": None,
            "time_ms": None,
            "bestmove": None,
        }

        while True:
            line = self.proc.stdout.readline()
            if line == "":
                raise RuntimeError("Stockfish exited during evaluation.")
            s = line.strip()

            if s.startswith("info "):
                m = re.search(r"\bscore (cp|mate) (-?\d+)", s)
                if m:
                    latest["score_type"] = m.group(1)
                    latest["score_value"] = int(m.group(2))
                for key, out_key in [
                    ("depth", "depth"),
                    ("seldepth", "seldepth"),
                    ("nodes", "nodes"),
                    ("nps", "nps"),
                    ("time", "time_ms"),
                ]:
                    mm = re.search(rf"\b{key} (-?\d+)", s)
                    if mm:
                        latest[out_key] = int(mm.group(1))

            elif s.startswith("bestmove"):
                parts = s.split()
                latest["bestmove"] = parts[1] if len(parts) > 1 else None
                break

        if latest["score_type"] is None:
            raise RuntimeError("Stockfish returned no score.")
        return latest

    def close(self) -> None:
        try:
            self._send("quit")
        except Exception:
            pass
        try:
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()


def stockfish_name(bin_path: Path, threads: int, hash_mb: int) -> str:
    e = StockfishUCI(str(bin_path), threads=threads, hash_mb=hash_mb)
    name = e.name
    e.close()
    return name


def norm_color(x: Any) -> str | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip().lower()
    if s in {"w", "white"}:
        return "white"
    if s in {"b", "black"}:
        return "black"
    return None


def fen_turn_color(fen: str) -> str | None:
    try:
        token = fen.split()[1]
    except Exception:
        return None
    if token == "w":
        return "white"
    if token == "b":
        return "black"
    return None


def fairness_bin(eval_cp: float | int | None) -> str | None:
    if eval_cp is None or not np.isfinite(eval_cp):
        return None
    v = float(eval_cp)
    if v >= 300:
        return "disconnected_clearly_better"
    if v >= 101:
        return "disconnected_better"
    if v >= -100:
        return "roughly_equal"
    if v >= -299:
        return "modestly_worse_excluded"
    return "clearly_worse"


def eval_one_record(
    row: dict[str, Any],
    engine: StockfishUCI,
    nodes: int,
    stockfish_name_value: str,
    stockfish_sha256: str,
    stockfish_bin: str,
    threads: int,
    hash_mb: int,
) -> dict[str, Any]:
    base = {k: row.get(k) for k in CANDIDATE_COLS if k in row}
    base["_source_row_number"] = row.get("_source_row_number")
    base["_source_path"] = row.get("_source_path")

    fen = str(row.get("fen_after_last_move", "")).strip()
    if not fen:
        raise RuntimeError("Missing FEN.")

    turn = fen_turn_color(fen)
    disc = norm_color(row.get("likely_disconnected_color")) or norm_color(row.get("side_to_move_after_last"))
    assumption = "explicit_disconnected_color"
    if disc is None:
        disc = turn
        assumption = "assumed_fen_side_to_move_is_disconnected"

    raw = engine.evaluate(fen, nodes=nodes)
    score_type = raw["score_type"]
    score_value = int(raw["score_value"])

    if turn is None or disc is None:
        sign = 1
        perspective_ok = False
    else:
        sign = 1 if turn == disc else -1
        perspective_ok = (turn == disc)

    score_cp_side = score_value if score_type == "cp" else None
    mate_ply_side = score_value if score_type == "mate" else None

    if score_type == "cp":
        eval_raw_disc = sign * score_value
        eval_disc = eval_raw_disc
        mate_ply_disc = None
        is_mate = False
    else:
        mate_ply_disc = sign * score_value
        eval_raw_disc = MATE_SENTINEL if mate_ply_disc > 0 else -MATE_SENTINEL
        eval_disc = eval_raw_disc
        is_mate = True

    capped = max(-600, min(600, int(eval_disc)))
    bin_name = fairness_bin(eval_disc)

    base.update(
        {
            "sf100k_ok": True,
            "sf100k_error": None,
            "sf100k_stockfish_bin": stockfish_bin,
            "sf100k_stockfish_name": stockfish_name_value,
            "sf100k_stockfish_sha256": stockfish_sha256,
            "sf100k_nodes_requested": nodes,
            "sf100k_threads": threads,
            "sf100k_hash_mb": hash_mb,
            "sf100k_eval_method": "uci_go_nodes",
            "sf100k_evaluated_at_utc": utc_now(),
            "sf100k_fen_turn_color": turn,
            "sf100k_disconnected_color_for_perspective": disc,
            "sf100k_perspective_assumption": assumption,
            "sf100k_fen_turn_matches_disconnected_color": bool(perspective_ok),
            "sf100k_score_type_side_to_move": score_type,
            "sf100k_score_value_side_to_move": score_value,
            "sf100k_score_cp_side_to_move": score_cp_side,
            "sf100k_mate_ply_side_to_move": mate_ply_side,
            "sf100k_eval_cp_disconnected_raw": int(eval_raw_disc),
            "sf100k_eval_cp_disconnected": int(eval_disc),
            "sf100k_eval_cp_disconnected_capped600": int(capped),
            "sf100k_eval_is_mate": bool(is_mate),
            "sf100k_eval_mate_ply_disconnected": mate_ply_disc,
            "sf100k_engine_fairness_bin": bin_name,
            "sf100k_fair_subset_main": bool(eval_disc >= -100),
            "sf100k_clearly_worse_subset": bool(eval_disc <= -300),
            "sf100k_excluded_middle_subset": bool((-299 <= eval_disc <= -101)),
            "sf100k_depth": raw.get("depth"),
            "sf100k_seldepth": raw.get("seldepth"),
            "sf100k_nodes_searched": raw.get("nodes"),
            "sf100k_nps": raw.get("nps"),
            "sf100k_time_ms": raw.get("time_ms"),
            "sf100k_bestmove": raw.get("bestmove"),
        }
    )
    return base


def eval_record_batch(records: list[dict[str, Any]], cfg: dict[str, Any], worker_id: int) -> list[dict[str, Any]]:
    engine = StockfishUCI(
        cfg["stockfish_bin"],
        threads=int(cfg["threads"]),
        hash_mb=int(cfg["hash_mb"]),
    )
    out = []
    try:
        for row in records:
            try:
                r = eval_one_record(
                    row=row,
                    engine=engine,
                    nodes=int(cfg["nodes"]),
                    stockfish_name_value=cfg["stockfish_name"],
                    stockfish_sha256=cfg["stockfish_sha256"],
                    stockfish_bin=cfg["stockfish_bin"],
                    threads=int(cfg["threads"]),
                    hash_mb=int(cfg["hash_mb"]),
                )
                r["_worker_id"] = worker_id
                out.append(r)
            except Exception as e:
                base = {k: row.get(k) for k in CANDIDATE_COLS if k in row}
                base["_source_row_number"] = row.get("_source_row_number")
                base["_source_path"] = row.get("_source_path")
                base["_worker_id"] = worker_id
                base.update(
                    {
                        "sf100k_ok": False,
                        "sf100k_error": repr(e),
                        "sf100k_nodes_requested": int(cfg["nodes"]),
                        "sf100k_threads": int(cfg["threads"]),
                        "sf100k_hash_mb": int(cfg["hash_mb"]),
                        "sf100k_eval_method": "uci_go_nodes",
                        "sf100k_evaluated_at_utc": utc_now(),
                    }
                )
                out.append(base)
    finally:
        engine.close()
    return out


def split_records(records: list[dict[str, Any]], n: int) -> list[list[dict[str, Any]]]:
    if not records:
        return []
    n = max(1, min(n, len(records)))
    size = math.ceil(len(records) / n)
    return [records[i : i + size] for i in range(0, len(records), size)]


def evaluate_dataframe(df: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    records = df.to_dict(orient="records")
    chunks = split_records(records, int(cfg["workers"]))

    results = []
    with ProcessPoolExecutor(max_workers=len(chunks)) as ex:
        futures = [
            ex.submit(eval_record_batch, chunk, cfg, i)
            for i, chunk in enumerate(chunks)
        ]
        for fut in as_completed(futures):
            results.extend(fut.result())

    out = pd.DataFrame(results)
    if "_source_row_number" in out.columns:
        out = out.sort_values("_source_row_number").reset_index(drop=True)
    return out


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))


def build_cfg(args: argparse.Namespace, stockfish_bin: Path, stockfish_sha: str, sf_name: str) -> dict[str, Any]:
    return {
        "stockfish_bin": str(stockfish_bin),
        "stockfish_sha256": stockfish_sha,
        "stockfish_name": sf_name,
        "nodes": int(args.nodes),
        "threads": int(args.threads_per_engine),
        "hash_mb": int(args.hash_mb),
        "workers": int(args.workers),
    }


def run_plan(args: argparse.Namespace, selected: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    out_root = Path(args.output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    plan = {
        "created_at_utc": utc_now(),
        "mode": "plan",
        "input_paths_file": str(Path(args.input_paths_file).resolve()),
        "months_csv": args.months,
        "months": [x["month"] for x in selected],
        "n_months": len(selected),
        "total_rows": int(sum(x["rows"] for x in selected)),
        "nodes": int(args.nodes),
        "workers": int(args.workers),
        "threads_per_engine": int(args.threads_per_engine),
        "hash_mb": int(args.hash_mb),
        "part_rows": int(args.part_rows),
        "stockfish": cfg,
        "selected_inputs": selected,
        "warning": "This is an 11-month 100k precompute from existing prior outputs, not the final frozen 24-month paper layer.",
    }
    for x in plan["selected_inputs"]:
        x["n_parts_expected"] = int(math.ceil(int(x["rows"]) / int(args.part_rows)))

    write_json(out_root / "plan_manifest.json", plan)
    pd.DataFrame(plan["selected_inputs"]).to_csv(out_root / "input_month_manifest.csv", index=False)

    log("PLAN")
    log(f"months={plan['months']}")
    log(f"total_rows={plan['total_rows']:,}")
    log(f"workers={args.workers}; threads_per_engine={args.threads_per_engine}; hash_mb={args.hash_mb}; nodes={args.nodes}")
    log(f"stockfish={cfg['stockfish_name']}")
    log(f"output_root={out_root}")
    return plan


def summarize_progress(out_root: Path) -> dict[str, Any]:
    plan_path = out_root / "plan_manifest.json"
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else {}
    expected = {x["month"]: x for x in plan.get("selected_inputs", [])}

    rows = []
    path_rows = []
    for month, meta in sorted(expected.items()):
        mdir = out_root / f"month={month}"
        done_files = sorted(mdir.glob("part_*.done.json")) if mdir.exists() else []
        done_rows = 0
        ok_rows = 0
        error_rows = 0
        seconds = 0.0
        for df in done_files:
            try:
                d = json.loads(df.read_text())
            except Exception:
                continue
            done_rows += int(d.get("rows", 0))
            ok_rows += int(d.get("ok_rows", 0))
            error_rows += int(d.get("error_rows", 0))
            seconds += float(d.get("seconds", 0.0))
        parquet_files = sorted(mdir.glob("part_*.parquet")) if mdir.exists() else []
        for p in parquet_files:
            path_rows.append({"month": month, "path": str(p)})
        rows.append(
            {
                "month": month,
                "expected_rows": int(meta.get("rows", 0)),
                "expected_parts": int(meta.get("n_parts_expected", 0)),
                "done_parts": len(done_files),
                "done_rows": done_rows,
                "ok_rows": ok_rows,
                "error_rows": error_rows,
                "seconds_in_completed_parts": seconds,
                "complete": bool(done_rows == int(meta.get("rows", 0)) and error_rows == 0),
            }
        )

    status = pd.DataFrame(rows)
    if len(status):
        status.to_csv(out_root / "month_status.csv", index=False)

    with (out_root / "sf100k_parquet_paths.txt").open("w") as f:
        for r in path_rows:
            f.write(r["path"] + "\n")

    total_expected = int(sum(r["expected_rows"] for r in rows)) if rows else 0
    total_done = int(sum(r["done_rows"] for r in rows)) if rows else 0
    total_errors = int(sum(r["error_rows"] for r in rows)) if rows else 0
    complete = bool(total_expected > 0 and total_done == total_expected and total_errors == 0)

    summary = {
        "updated_at_utc": utc_now(),
        "output_root": str(out_root),
        "total_expected_rows": total_expected,
        "total_done_rows": total_done,
        "total_error_rows": total_errors,
        "complete": complete,
        "path_list": str(out_root / "sf100k_parquet_paths.txt"),
        "month_status": str(out_root / "month_status.csv"),
    }
    write_json(out_root / "summary.json", summary)
    return summary


def run_pilot(args: argparse.Namespace, selected: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
    out_root = Path(args.output_root)
    pilot_dir = out_root / "pilot"
    pilot_dir.mkdir(parents=True, exist_ok=True)

    per_month = max(1, math.ceil(int(args.pilot_rows) / len(selected)))
    pieces = []
    for x in selected:
        p = Path(x["path"])
        cols = columns_to_read(p)
        d = read_head_parquet(p, cols, per_month)
        d["_source_path"] = str(p)
        d["_source_row_number"] = np.arange(len(d), dtype=np.int64)
        d["_pilot_month"] = x["month"]
        pieces.append(d)

    df = pd.concat(pieces, ignore_index=True).head(int(args.pilot_rows)).copy()
    df["_source_row_number"] = np.arange(len(df), dtype=np.int64)

    log(f"PILOT evaluating {len(df):,} positions at {args.nodes:,} nodes with {args.workers} workers")
    t0 = time.time()
    out = evaluate_dataframe(df, cfg)
    seconds = time.time() - t0

    pilot_path = pilot_dir / "sf100k_pilot.parquet"
    out.to_parquet(pilot_path, index=False, compression="zstd")

    ok = int(out["sf100k_ok"].fillna(False).sum()) if "sf100k_ok" in out.columns else 0
    errors = int(len(out) - ok)
    rows_per_sec = len(out) / seconds if seconds > 0 else None
    total_rows = sum(int(x["rows"]) for x in selected)
    eta_seconds = total_rows / rows_per_sec if rows_per_sec else None

    summary = {
        "pilot_rows": int(len(out)),
        "ok_rows": ok,
        "error_rows": errors,
        "seconds": seconds,
        "rows_per_second": rows_per_sec,
        "estimated_total_rows": int(total_rows),
        "estimated_production_seconds": eta_seconds,
        "estimated_production_hours": eta_seconds / 3600 if eta_seconds else None,
        "estimated_production_days": eta_seconds / 86400 if eta_seconds else None,
        "pilot_path": str(pilot_path),
    }
    write_json(pilot_dir / "pilot_summary.json", summary)

    log("PILOT SUMMARY")
    log(json.dumps(summary, indent=2, sort_keys=True))
    if errors:
        err_path = pilot_dir / "pilot_errors.csv"
        out.loc[~out["sf100k_ok"].fillna(False)].to_csv(err_path, index=False)
        log(f"Pilot had errors; see {err_path}")


def run_production(args: argparse.Namespace, selected: list[dict[str, Any]], cfg: dict[str, Any]) -> None:
    out_root = Path(args.output_root)
    log("PRODUCTION START")
    log(f"output_root={out_root}")

    for x in selected:
        month = x["month"]
        path = Path(x["path"])
        cols = columns_to_read(path)
        mdir = out_root / f"month={month}"
        mdir.mkdir(parents=True, exist_ok=True)

        log(f"{month}: reading input columns from {path}")
        df = pd.read_parquet(path, columns=cols)
        df["_source_path"] = str(path)
        df["_source_row_number"] = np.arange(len(df), dtype=np.int64)

        expected_rows = len(df)
        n_parts = math.ceil(expected_rows / int(args.part_rows))
        log(f"{month}: rows={expected_rows:,}; parts={n_parts:,}")

        for part_idx, start in enumerate(range(0, expected_rows, int(args.part_rows))):
            end = min(start + int(args.part_rows), expected_rows)
            part_path = mdir / f"part_{part_idx:05d}.parquet"
            done_path = mdir / f"part_{part_idx:05d}.done.json"

            if part_path.exists() and done_path.exists():
                log(f"{month}: SKIP part {part_idx+1}/{n_parts} rows {start:,}-{end:,}; already done")
                continue

            chunk = df.iloc[start:end].copy()
            log(f"{month}: START part {part_idx+1}/{n_parts}; rows={len(chunk):,}; source rows {start:,}-{end-1:,}")
            t0 = time.time()
            out = evaluate_dataframe(chunk, cfg)
            seconds = time.time() - t0

            tmp_path = Path(str(part_path) + ".tmp")
            out.to_parquet(tmp_path, index=False, compression="zstd")
            tmp_path.replace(part_path)

            ok = int(out["sf100k_ok"].fillna(False).sum()) if "sf100k_ok" in out.columns else 0
            err = int(len(out) - ok)

            done = {
                "month": month,
                "part_idx": part_idx,
                "rows": int(len(out)),
                "ok_rows": ok,
                "error_rows": err,
                "seconds": seconds,
                "rows_per_second": float(len(out) / seconds) if seconds > 0 else None,
                "part_path": str(part_path),
                "completed_at_utc": utc_now(),
            }
            write_json(done_path, done)
            log(f"{month}: COMPLETE part {part_idx+1}/{n_parts}; ok={ok:,}; errors={err:,}; elapsed={seconds/60:.1f} min")

            prog = summarize_progress(out_root)
            log(f"OVERALL progress: {prog['total_done_rows']:,}/{prog['total_expected_rows']:,}; errors={prog['total_error_rows']:,}")

    final = summarize_progress(out_root)
    log("PRODUCTION SUMMARY")
    log(json.dumps(final, indent=2, sort_keys=True))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-paths-file", required=True)
    ap.add_argument("--months", required=True)
    ap.add_argument("--output-root", required=True)
    ap.add_argument("--stockfish-bin", default=None)
    ap.add_argument("--nodes", type=int, default=100000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--threads-per-engine", type=int, default=1)
    ap.add_argument("--hash-mb", type=int, default=64)
    ap.add_argument("--part-rows", type=int, default=100000)
    ap.add_argument("--pilot-rows", type=int, default=2000)
    ap.add_argument("--mode", choices=["plan", "pilot", "production", "summarize"], required=True)
    args = ap.parse_args()

    out_root = Path(args.output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    selected = select_paths(Path(args.input_paths_file), args.months)
    stockfish_bin = detect_stockfish(args.stockfish_bin)
    stockfish_sha = sha256_file(stockfish_bin)
    sf_name = stockfish_name(stockfish_bin, threads=args.threads_per_engine, hash_mb=args.hash_mb)
    cfg = build_cfg(args, stockfish_bin, stockfish_sha, sf_name)

    command = {
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "created_at_utc": utc_now(),
    }
    write_json(out_root / f"command_{args.mode}.json", command)

    if args.mode == "plan":
        run_plan(args, selected, cfg)
    elif args.mode == "pilot":
        if not (out_root / "plan_manifest.json").exists():
            run_plan(args, selected, cfg)
        run_pilot(args, selected, cfg)
        summarize_progress(out_root)
    elif args.mode == "production":
        if not (out_root / "plan_manifest.json").exists():
            run_plan(args, selected, cfg)
        run_production(args, selected, cfg)
    elif args.mode == "summarize":
        summary = summarize_progress(out_root)
        log(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
