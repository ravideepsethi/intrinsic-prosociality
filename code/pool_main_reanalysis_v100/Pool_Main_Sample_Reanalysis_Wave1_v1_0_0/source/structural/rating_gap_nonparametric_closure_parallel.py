#!/usr/bin/env python3
"""
Rating-gap nonparametric closure — Parquet-first parallel production v1.1.0.

WHY v1.1.0
----------
This is a performance/engineering revision of the v1.0.x scientific design.

Scientific estimands are unchanged:
  * 50-Elo nonparametric relative-rating bins;
  * chooser fixed effects;
  * chooser-clustered CR1 inference;
  * K20 primary controls;
  * K50, stable-RD/K, year replication, and common-support closure;
  * separate all / <=10 / >10 ply analyses by five board-evaluation bands.

Engineering changes:
  1. Parquet-first for every tabular output and every intermediate.
  2. Parallel model execution with independent worker processes.
  3. Automatic worker/thread/memory sizing from CPU and physical RAM.
  4. DuckDB spill directories per worker to prevent RAM oversubscription.
  5. Model-level atomic Parquet writes + SHA-256 authenticated resume.
  6. Partitioned private Parquet cache by eval_band and month.
  7. Consolidation directly with DuckDB read_parquet/COPY, avoiding CSV roundtrips.
  8. Progress ledger and model receipts preserved across interruption.
  9. Preprocessing uses 8 DuckDB threads; model workers avoid nested oversubscription.

SCIENTIFIC STATUS
-----------------
Exploratory closure prompted by the observed 3D surface and completed K/RD
decomposition. This is NOT a new confirmatory family.

PRIVACY
-------
Private caches contain chooser identifiers. Never upload/commit private_cache/.
All public tabular outputs are aggregate/model-level Parquet files.

SOURCE
------
The package authenticates and reuses:
/Volumes/XT_Pro/lichess_kindness/output/
rating_gap_krd_decomposition_20260831T183339Z/private_cache/
rating_gap_krd_derived_private.parquet
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import duckdb
import numpy as np
import pandas as pd

ROOT = Path("/Volumes/XT_Pro/lichess_kindness")
SOURCE_ROOT = ROOT / "output/rating_gap_krd_decomposition_20260831T183339Z"
SOURCE_SETTINGS = SOURCE_ROOT / "settings.json"
SOURCE_CACHE = SOURCE_ROOT / "private_cache/rating_gap_krd_derived_private.parquet"

EXPECTED_ROWS = 47_587_020
EXPECTED_SOURCE_STATUS = "RATING_GAP_KRD_DECOMPOSITION_OK"

EVAL_BANDS = [
    "m600_m300",
    "m300_m100",
    "m100_p100",
    "p100_p300",
    "p300_p600",
]
COMPETITIVE_BANDS = ["m100_p100", "p100_p300", "p300_p600"]
STAGES = ["all", "ply_le_10", "ply_gt_10"]
GAP_BIN_IDS = list(range(-11, 12))
GAP_BASE = 0

CS_EQUAL = "rating_gap >= -50 AND rating_gap < 50"
CS_WEAKER = "rating_gap >= -350 AND rating_gap < -150"
CS_STRONGER = "rating_gap >= 150 AND rating_gap < 350"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def q(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def repl(s: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in s)


def sha256_file(path: Path, chunk=8 * 1024 * 1024):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def atomic_parquet(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    df.to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, path)


def atomic_json(obj, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(obj, indent=2, default=str) + "\n")
    os.replace(tmp, path)


def physical_ram_gb() -> float:
    try:
        if sys.platform == "darwin":
            b = int(subprocess.check_output(["/usr/sbin/sysctl", "-n", "hw.memsize"]).decode().strip())
            return b / (1024**3)
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return (pages * size) / (1024**3)
    except Exception:
        return 16.0


def cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def auto_parallel_config(requested_workers: int, requested_threads: int, requested_mem: str | None):
    cpus = cpu_count()
    ram = physical_ram_gb()

    if requested_workers > 0:
        workers = requested_workers
    else:
        # Each FE worker can build a large chooser-cluster sufficient-stat table.
        # Reserve ~4 GiB for OS/coordinator and ~2.5 GiB per active worker.
        ram_workers = max(2, int(max(4.0, ram - 4.0) // 2.5))
        workers = min(8, max(2, cpus - 1), ram_workers)

    if requested_threads > 0:
        wthreads = requested_threads
    else:
        # On 8-ish core machines: 4 workers x 2 threads; on larger-memory
        # machines: 6-8 workers x 1 thread. Avoid nested oversubscription.
        if workers <= max(2, cpus // 2):
            wthreads = min(2, max(1, cpus // workers))
        else:
            wthreads = 1

    if requested_mem:
        mem = requested_mem
    else:
        usable = max(4.0, ram - 4.0)
        per = max(1.25, min(3.0, usable * 0.72 / workers))
        mem = f"{per:.2f}GB"

    return {
        "physical_ram_gb": ram,
        "logical_cpus": cpus,
        "model_workers": workers,
        "worker_threads": wthreads,
        "worker_memory_limit": mem,
    }


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--out-root", type=Path)
    p.add_argument("--prep-threads", type=int, default=8)
    p.add_argument("--prep-memory-limit", default="12GB")
    p.add_argument("--model-workers", type=int, default=0, help="0=auto")
    p.add_argument("--worker-threads", type=int, default=0, help="0=auto")
    p.add_argument("--worker-memory-limit", default=None, help="e.g. 2.5GB; omitted=auto")
    p.add_argument("--self-test", action="store_true")
    return p.parse_args()


def source_authenticate(con):
    if not SOURCE_SETTINGS.is_file():
        raise SystemExit(f"Missing source settings: {SOURCE_SETTINGS}")
    if not SOURCE_CACHE.is_file():
        raise SystemExit(f"Missing private source cache: {SOURCE_CACHE}")

    s = json.loads(SOURCE_SETTINGS.read_text())
    if s.get("status") != EXPECTED_SOURCE_STATUS:
        raise SystemExit(f"Source status mismatch: {s.get('status')}")
    if int(s.get("authority", {}).get("rows", -1)) != EXPECTED_ROWS:
        raise SystemExit("Source settings row authority mismatch.")

    cache = q(str(SOURCE_CACHE))
    row = con.execute(f"""
      SELECT
        count(*) AS n,
        count(DISTINCT month) AS months,
        min(month) AS min_month,
        max(month) AS max_month,
        max(abs(draw_payoff-predicted_draw_payoff)) AS max_identity_error
      FROM read_parquet({cache})
    """).fetchdf().iloc[0].to_dict()

    if int(row["n"]) != EXPECTED_ROWS:
        raise SystemExit(f"Source private cache row mismatch: {int(row['n']):,}")
    if int(row["months"]) != 24 or row["min_month"] != "2023-11" or row["max_month"] != "2025-10":
        raise SystemExit(f"Source month authority mismatch: {row}")
    if float(row["max_identity_error"]) > 1e-8:
        raise SystemExit(f"Mechanical identity failed: {row['max_identity_error']}")
    return s, row


def get_quantiles(con, expr: str, probs: List[float]) -> List[float]:
    ptxt = "[" + ",".join(str(float(x)) for x in probs) + "]"
    vals = con.execute(f"SELECT approx_quantile(k_scale,{ptxt}) FROM {expr}").fetchone()[0]
    return [float(x) for x in vals]


def quantile_case(col: str, cuts: List[float], alias: str) -> str:
    bits = ["CASE"]
    for i, c in enumerate(cuts):
        bits.append(f"WHEN {col} <= {float(c)} THEN {i}")
    bits.append(f"ELSE {len(cuts)} END AS {alias}")
    return " ".join(bits)


def cache_glob(cache_dir: Path):
    return str(cache_dir / "eval_band=*" / "month=*" / "*.parquet")


def table_for_band(cache_dir: Path, eb: str) -> str:
    patt = str(cache_dir / f"eval_band={eb}" / "month=*" / "*.parquet")
    files = list((cache_dir / f"eval_band={eb}").glob("month=*/*.parquet"))
    if not files:
        raise RuntimeError(f"No closure-cache files for eval band {eb}")
    return f"read_parquet({q(patt)}, hive_partitioning=true, union_by_name=true)"


def build_private_cache(con, out_root: Path):
    cache_dir = out_root / "private_cache" / "closure_model_base"
    receipt_path = out_root / "00_private_cache_receipt.json"

    if receipt_path.is_file() and cache_dir.is_dir():
        r = json.loads(receipt_path.read_text())
        if r.get("status") == "PRIVATE_CACHE_OK":
            patt = cache_glob(cache_dir)
            n = int(con.execute(f"SELECT count(*) FROM read_parquet({q(patt)}, hive_partitioning=true)").fetchone()[0])
            if n == int(r["rows"]):
                print("PRIVATE_CACHE_AUTHENTICATED_AND_SKIPPED", n, flush=True)
                return cache_dir, r
        raise SystemExit("Existing private-cache receipt failed authentication.")

    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        print("INCOMPLETE_PRIVATE_CACHE_REMOVED_FOR_SAFE_REBUILD", cache_dir, flush=True)

    src = f"read_parquet({q(str(SOURCE_CACHE))})"
    k20 = get_quantiles(con, src, [i / 20 for i in range(1, 20)])
    k50 = get_quantiles(con, src, [i / 50 for i in range(1, 50)])
    k95 = float(get_quantiles(con, src, [0.95])[0])
    k20_case = quantile_case("k_scale", k20, "k20")
    k50_case = quantile_case("k_scale", k50, "k50")

    cache_dir.parent.mkdir(parents=True, exist_ok=True)

    # Partition by BOTH evaluation band and month. This turns the cache into
    # 5 x 24 natural Parquet shards, improves pruning, and lets concurrent
    # workers stream independent small files instead of fighting over five
    # monolithic partitions.
    con.execute(f"""
      COPY (
        SELECT
          chooser, kind, eval, win_premium, rating_gap, chooser_rd, opp_rd,
          ply, speed, month, year_half, ply_band, eval_band,
          k_scale, log_k, expected_score, score_distance,
          {k20_case},
          {k50_case},
          CAST(floor((rating_gap + 25.0)/50.0) AS INTEGER) AS gap_bin50
        FROM {src}
        WHERE eval_band IS NOT NULL
          AND rating_gap >= -600 AND rating_gap < 600
      ) TO {q(str(cache_dir))}
      (
        FORMAT PARQUET,
        PARTITION_BY(eval_band, month),
        COMPRESSION ZSTD,
        ROW_GROUP_SIZE 150000,
        OVERWRITE_OR_IGNORE false
      )
    """)

    patt = cache_glob(cache_dir)
    tab = f"read_parquet({q(patt)}, hive_partitioning=true)"
    n = int(con.execute(f"SELECT count(*) FROM {tab}").fetchone()[0])
    band_month = con.execute(f"""
      SELECT eval_band, month, count(*) AS n
      FROM {tab}
      GROUP BY eval_band, month
      ORDER BY eval_band, month
    """).fetchdf()

    inv_path = out_root / "private_cache_inventory.parquet"
    atomic_parquet(band_month, inv_path)

    r = {
        "status": "PRIVATE_CACHE_OK",
        "created_utc": utc_now(),
        "rows": n,
        "parquet_shards": int(len(list(cache_dir.glob("eval_band=*/month=*/*.parquet")))),
        "k20_cutpoints": k20,
        "k50_cutpoints": k50,
        "k95": k95,
        "inventory_parquet": str(inv_path),
        "source_cache": str(SOURCE_CACHE),
        "privacy": "contains chooser identifiers; never upload or commit",
    }
    atomic_json(r, receipt_path)
    print("PRIVATE_CACHE_OK", n, "shards", r["parquet_shards"], "K95", k95, flush=True)
    return cache_dir, r


def stage_filter(stage: str) -> str:
    if stage == "all":
        return "TRUE"
    if stage == "ply_le_10":
        return "ply <= 10"
    if stage == "ply_gt_10":
        return "ply > 10"
    raise ValueError(stage)


def categories(con, cache_dir: Path):
    patt = cache_glob(cache_dir)
    tab = f"read_parquet({q(patt)}, hive_partitioning=true)"
    months = [str(x[0]) for x in con.execute(f"SELECT DISTINCT month FROM {tab} ORDER BY month").fetchall()]
    speeds = [str(x[0]) for x in con.execute(f"SELECT DISTINCT speed FROM {tab} WHERE speed IS NOT NULL ORDER BY speed").fetchall()]
    return months, speeds


def nuisance_terms(stage: str, kfamily: str, months: List[str], speeds: List[str]):
    terms = []
    if kfamily == "k20":
        terms += [(f"k20_{i}", f"CASE WHEN k20={i} THEN 1.0 ELSE 0.0 END") for i in range(1, 20)]
    elif kfamily == "k50":
        terms += [(f"k50_{i}", f"CASE WHEN k50={i} THEN 1.0 ELSE 0.0 END") for i in range(1, 50)]
    else:
        raise ValueError(kfamily)

    terms += [
        (f"m_{m.replace('-', '_')}", f"CASE WHEN month={q(m)} THEN 1.0 ELSE 0.0 END")
        for m in months[1:]
    ]
    terms += [
        (f"speed_{repl(s)}", f"CASE WHEN speed={q(s)} THEN 1.0 ELSE 0.0 END")
        for s in speeds[1:]
    ]

    if stage == "ply_le_10":
        cats = ["p0_4", "p5_6", "p7_8", "p9_10"]
    elif stage == "ply_gt_10":
        cats = ["p11_20", "p21_40", "p41_80", "p81p"]
    else:
        cats = ["p0_4", "p5_6", "p7_8", "p9_10", "p11_20", "p21_40", "p41_80", "p81p"]

    terms += [
        (f"ply_{c}", f"CASE WHEN ply_band={q(c)} THEN 1.0 ELSE 0.0 END")
        for c in cats[1:]
    ]

    terms += [
        ("eval100", "eval/100.0"),
        ("eval100_sq", "(eval/100.0)*(eval/100.0)"),
        ("eval100_cu", "(eval/100.0)*(eval/100.0)*(eval/100.0)"),
        ("winprem10", "win_premium/10.0"),
    ]
    return terms


def gap_terms():
    return [
        (
            f"gap_{i:+d}".replace("+", "p").replace("-", "m"),
            f"CASE WHEN gap_bin50={i} THEN 1.0 ELSE 0.0 END",
        )
        for i in GAP_BIN_IDS
        if i != GAP_BASE
    ]


def raw_cross_query(table: str, filt: str, terms):
    names = [n for n, _ in terms]
    expr = dict(terms)
    pieces = ["count(*) AS n", "sum(kind) AS sy"]
    for n in names:
        pieces.append(f"sum(({expr[n]})) AS s_{n}")
        pieces.append(f"sum(({expr[n]})*kind) AS sy_{n}")
    for i, a in enumerate(names):
        for b in names[i:]:
            pieces.append(f"sum(({expr[a]})*({expr[b]})) AS s_{a}__{b}")
    return f"SELECT {','.join(pieces)} FROM {table} WHERE {filt}"


def make_cluster_sums(con, table: str, filt: str, terms, temp_name: str):
    pieces = ["chooser", "count(*) AS n", "sum(kind) AS sy"]
    for n, e in terms:
        pieces.append(f"sum(({e})) AS s_{n}")
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE {temp_name} AS "
        f"SELECT {','.join(pieces)} FROM {table} WHERE {filt} GROUP BY chooser"
    )


def correction_query(temp_name: str, terms):
    names = [n for n, _ in terms]
    pieces = ["count(*) AS clusters", "sum(n) AS n"]
    for n in names:
        pieces.append(f"sum(s_{n}*sy/n) AS cy_{n}")
    for i, a in enumerate(names):
        for b in names[i:]:
            pieces.append(f"sum(s_{a}*s_{b}/n) AS c_{a}__{b}")
    return f"SELECT {','.join(pieces)} FROM {temp_name}"


def fit_fe_targeted(con, table: str, filt: str, terms, key_terms: List[str], model_id: str):
    t0 = time.time()
    names = [n for n, _ in terms]
    expr = dict(terms)
    tmp = "cs_" + hashlib.sha1(model_id.encode()).hexdigest()[:12]

    raw = con.execute(raw_cross_query(table, filt, terms)).fetchdf().iloc[0].to_dict()
    make_cluster_sums(con, table, filt, terms, tmp)
    corr = con.execute(correction_query(tmp, terms)).fetchdf().iloc[0].to_dict()

    p = len(names)
    XX = np.zeros((p, p), float)
    Xy = np.zeros(p, float)
    for i, a in enumerate(names):
        Xy[i] = float(raw.get(f"sy_{a}") or 0) - float(corr.get(f"cy_{a}") or 0)
        for j, b in enumerate(names[i:], start=i):
            v = float(raw.get(f"s_{a}__{b}") or 0) - float(corr.get(f"c_{a}__{b}") or 0)
            XX[i, j] = XX[j, i] = v

    diag = np.diag(XX)
    maxdiag = float(np.nanmax(diag)) if len(diag) else 0.0
    keep = diag > max(1e-11, maxdiag * 1e-13)
    kept = [names[i] for i in range(p) if keep[i]]
    if not kept:
        raise RuntimeError(f"{model_id}: no identifying variation")

    XXk = XX[np.ix_(keep, keep)]
    Xyk = Xy[keep]
    rank = int(np.linalg.matrix_rank(XXk))
    inv = np.linalg.pinv(XXk, rcond=1e-10)
    beta = inv @ Xyk
    beta_map = {n: float(beta[i]) for i, n in enumerate(kept)}

    residual = "(c.kind - s.sy/s.n"
    for n in kept:
        residual += f" - ({beta_map[n]:.17g})*(({expr[n]})-(s.s_{n}/s.n))"
    residual += ")"

    usable_keys = [k for k in key_terms if k in kept]
    score_exprs = []
    for k in usable_keys:
        j = kept.index(k)
        qrow = inv[j, :]
        hparts = []
        for m, n in enumerate(kept):
            coef = float(qrow[m])
            if abs(coef) > 1e-16:
                hparts.append(f"({coef:.17g})*(({expr[n]})-(s.s_{n}/s.n))")
        h = "(" + "+".join(hparts) + ")" if hparts else "(0.0)"
        score_exprs.append(f"sum(({h})*{residual}) AS sc_{k}")

    if score_exprs:
        score_sql = f"""
          WITH scores AS (
            SELECT c.chooser, {','.join(score_exprs)}
            FROM {table} c
            JOIN {tmp} s USING (chooser)
            WHERE {filt}
            GROUP BY c.chooser
          )
          SELECT {','.join([f"sum(sc_{k}*sc_{k}) AS ss_{k}" for k in usable_keys])}
          FROM scores
        """
        srow = con.execute(score_sql).fetchdf().iloc[0].to_dict()
    else:
        srow = {}

    G = int(corr["clusters"])
    cr1 = G / (G - 1) if G > 1 else 1.0
    rows = []
    for n in names:
        if n not in kept:
            rows.append(
                dict(model_id=model_id, term=n, coef_pp=np.nan, se_pp=np.nan, z=np.nan, identified=0)
            )
            continue
        i = kept.index(n)
        b = float(beta[i])
        if n in usable_keys:
            se = math.sqrt(max(0.0, cr1 * float(srow[f"ss_{n}"])))
            z = b / se if se > 0 else np.nan
        else:
            se = np.nan
            z = np.nan
        rows.append(
            dict(
                model_id=model_id,
                term=n,
                coef_pp=100 * b,
                se_pp=100 * se if np.isfinite(se) else np.nan,
                z=z,
                identified=1,
            )
        )

    con.execute(f"DROP TABLE IF EXISTS {tmp}")
    receipt = {
        "status": "MODEL_OK",
        "model_id": model_id,
        "rows": int(raw["n"]),
        "clusters": G,
        "terms_requested": p,
        "terms_kept": len(kept),
        "rank": rank,
        "condition_number": float(np.linalg.cond(XXk)) if rank == len(kept) else float("inf"),
        "runtime_seconds": time.time() - t0,
        "dropped_terms": [n for n in names if n not in kept],
        "key_terms": usable_keys,
    }
    return pd.DataFrame(rows), receipt


def model_paths(out_root: Path, model_id: str):
    md = out_root / "models"
    md.mkdir(parents=True, exist_ok=True)
    safe = repl(model_id)
    return md / f"{safe}_coefficients.parquet", md / f"{safe}_receipt.json"


def model_valid(out_root: Path, model_id: str):
    cp, rp = model_paths(out_root, model_id)
    if not (cp.is_file() and rp.is_file()):
        return False
    try:
        r = json.loads(rp.read_text())
        return (
            r.get("status") == "MODEL_OK"
            and r.get("model_id") == model_id
            and r.get("coefficient_parquet_sha256") == sha256_file(cp)
        )
    except Exception:
        return False


def build_model_plan(months, speeds, cache_receipt):
    plan = []
    gaps = gap_terms()
    key = [n for n, _ in gaps]

    for eb in EVAL_BANDS:
        for stage in STAGES:
            plan.append(
                dict(
                    family="primary_k20",
                    model_id=f"primary_k20__{stage}__{eb}",
                    eb=eb,
                    stage=stage,
                    kfamily="k20",
                    extra_filter="gap_bin50 BETWEEN -11 AND 11",
                    key_terms=key,
                    terms=gaps + nuisance_terms(stage, "k20", months, speeds),
                )
            )

    for eb in COMPETITIVE_BANDS:
        plan.append(
            dict(
                family="k50",
                model_id=f"k50__ply_gt_10__{eb}",
                eb=eb,
                stage="ply_gt_10",
                kfamily="k50",
                extra_filter="gap_bin50 BETWEEN -11 AND 11",
                key_terms=key,
                terms=gaps + nuisance_terms("ply_gt_10", "k50", months, speeds),
            )
        )

    k95 = float(cache_receipt["k95"])
    for eb in COMPETITIVE_BANDS:
        plan.append(
            dict(
                family="stable_rating",
                model_id=f"stableRD_K95__ply_gt_10__{eb}",
                eb=eb,
                stage="ply_gt_10",
                kfamily="k20",
                extra_filter=f"gap_bin50 BETWEEN -11 AND 11 AND chooser_rd<=100 AND k_scale<={k95}",
                key_terms=key,
                terms=gaps + nuisance_terms("ply_gt_10", "k20", months, speeds),
            )
        )

    for yr in ["year1", "year2"]:
        for eb in COMPETITIVE_BANDS:
            plan.append(
                dict(
                    family="year_replication",
                    model_id=f"{yr}__ply_gt_10__{eb}",
                    eb=eb,
                    stage="ply_gt_10",
                    kfamily="k20",
                    extra_filter=f"gap_bin50 BETWEEN -11 AND 11 AND year_half={q(yr)}",
                    key_terms=key,
                    terms=gaps + nuisance_terms("ply_gt_10", "k20", months, speeds),
                )
            )

    for eb in COMPETITIVE_BANDS:
        for side, side_sql in [("weaker", CS_WEAKER), ("stronger", CS_STRONGER)]:
            keyterm = (f"is_{side}", f"CASE WHEN {side_sql} THEN 1.0 ELSE 0.0 END")
            plan.append(
                dict(
                    family="common_support",
                    model_id=f"common_support_{side}__ply_gt_10__{eb}",
                    eb=eb,
                    stage="ply_gt_10",
                    kfamily="k20",
                    pair_side=side,
                    pair_side_sql=side_sql,
                    key_terms=[keyterm[0]],
                    terms=[keyterm] + nuisance_terms("ply_gt_10", "k20", months, speeds),
                )
            )
    return plan


def plan_public_df(plan):
    rows = []
    for i, x in enumerate(plan, 1):
        rows.append(
            {
                "plan_order": i,
                "model_id": x["model_id"],
                "family": x["family"],
                "eval_band": x["eb"],
                "stage": x["stage"],
                "kfamily": x["kfamily"],
                "extra_filter": x.get("extra_filter"),
                "pair_side": x.get("pair_side"),
                "term_count": len(x["terms"]),
                "key_term_count": len(x["key_terms"]),
                "term_names": ";".join(n for n, _ in x["terms"]),
                "key_terms": ";".join(x["key_terms"]),
            }
        )
    return pd.DataFrame(rows)


def worker_run_model(task):
    out_root = Path(task["out_root"])
    cache_dir = Path(task["cache_dir"])
    item = task["item"]
    worker_threads = int(task["worker_threads"])
    worker_memory = str(task["worker_memory"])
    spill_root = Path(task["spill_root"])

    model_id = item["model_id"]
    if model_valid(out_root, model_id):
        return {"status": "SKIPPED", "model_id": model_id, "pid": os.getpid()}

    spill_dir = spill_root / f"pid_{os.getpid()}"
    spill_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(":memory:")
    con.execute(f"SET threads={worker_threads}")
    con.execute(f"SET memory_limit={q(worker_memory)}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory={q(str(spill_dir))}")

    table = table_for_band(cache_dir, item["eb"])
    sf = stage_filter(item["stage"])

    if item["family"] != "common_support":
        filt = f"({sf}) AND ({item['extra_filter']})"
    else:
        side_sql = item["pair_side_sql"]
        elig = f"""
          chooser IN (
            SELECT chooser FROM {table}
            WHERE ply>10 AND (({CS_EQUAL}) OR ({side_sql}))
            GROUP BY chooser
            HAVING count(*) FILTER (WHERE {CS_EQUAL})>=1
               AND count(*) FILTER (WHERE {side_sql})>=1
          )
        """
        filt = f"ply>10 AND (({CS_EQUAL}) OR ({side_sql})) AND ({elig})"

    try:
        coef, receipt = fit_fe_targeted(
            con, table, filt, item["terms"], item["key_terms"], model_id
        )
        con.close()

        cp, rp = model_paths(out_root, model_id)
        atomic_parquet(coef, cp)
        receipt.update(
            {
                "coefficient_parquet": str(cp),
                "coefficient_parquet_sha256": sha256_file(cp),
                "worker_pid": os.getpid(),
                "worker_threads": worker_threads,
                "worker_memory_limit": worker_memory,
            }
        )
        atomic_json(receipt, rp)
        return {
            "status": "OK",
            "model_id": model_id,
            "pid": os.getpid(),
            "seconds": receipt["runtime_seconds"],
            "rows": receipt["rows"],
            "clusters": receipt["clusters"],
        }
    except Exception as e:
        try:
            con.close()
        except Exception:
            pass
        return {
            "status": "ERROR",
            "model_id": model_id,
            "pid": os.getpid(),
            "error": repr(e),
            "traceback": traceback.format_exc(),
        }


def descriptive_curves(con, cache_dir: Path, out_root: Path):
    out = out_root / "00_descriptive_rating_gap_curves.parquet"
    if out.is_file():
        print("DESCRIPTIVE_CURVES_SKIPPED", flush=True)
        return
    rows = []
    for eb in EVAL_BANDS:
        tab = table_for_band(cache_dir, eb)
        for stage in STAGES:
            sf = stage_filter(stage)
            for yh in ["all", "year1", "year2"]:
                yf = "TRUE" if yh == "all" else f"year_half={q(yh)}"
                df = con.execute(f"""
                  SELECT
                    gap_bin50,
                    gap_bin50*50.0 AS gap_mid,
                    count(*) AS n,
                    sum(kind) AS kind_draws,
                    100.0*avg(kind) AS rate_pct
                  FROM {tab}
                  WHERE ({sf}) AND ({yf}) AND gap_bin50 BETWEEN -11 AND 11
                  GROUP BY gap_bin50
                  ORDER BY gap_bin50
                """).fetchdf()
                if len(df):
                    df.insert(0, "year_half", yh)
                    df.insert(0, "stage", stage)
                    df.insert(0, "eval_band", eb)
                    rows.append(df)
    atomic_parquet(pd.concat(rows, ignore_index=True), out)
    print("DESCRIPTIVE_CURVES_OK", flush=True)


def common_support_descriptives(con, cache_dir: Path, out_root: Path):
    out = out_root / "common_support_chooser_equal_differences.parquet"
    if out.is_file():
        print("COMMON_SUPPORT_DESCRIPTIVES_SKIPPED", flush=True)
        return
    rows = []
    for eb in COMPETITIVE_BANDS:
        tab = table_for_band(cache_dir, eb)
        for side, side_sql in [("weaker", CS_WEAKER), ("stronger", CS_STRONGER)]:
            d = con.execute(f"""
              WITH agg AS (
                SELECT chooser,
                  count(*) FILTER (WHERE {CS_EQUAL}) AS n_equal,
                  sum(kind) FILTER (WHERE {CS_EQUAL}) AS k_equal,
                  count(*) FILTER (WHERE {side_sql}) AS n_side,
                  sum(kind) FILTER (WHERE {side_sql}) AS k_side
                FROM {tab}
                WHERE ply>10 AND (({CS_EQUAL}) OR ({side_sql}))
                GROUP BY chooser
              )
              SELECT
                count(*) AS choosers,
                avg(k_side/n_side - k_equal/n_equal) AS mean_diff,
                stddev_samp(k_side/n_side - k_equal/n_equal)/sqrt(count(*)) AS se_diff,
                sum(n_equal) AS equal_rows,
                sum(n_side) AS side_rows
              FROM agg
              WHERE n_equal>=1 AND n_side>=1
            """).fetchdf().iloc[0].to_dict()
            rows.append(
                {
                    "eval_band": eb,
                    "side": side,
                    "choosers": int(d["choosers"] or 0),
                    "equal_rows": int(d["equal_rows"] or 0),
                    "side_rows": int(d["side_rows"] or 0),
                    "chooser_equal_diff_pp": 100 * float(d["mean_diff"]) if d["mean_diff"] is not None else np.nan,
                    "se_pp": 100 * float(d["se_diff"]) if d["se_diff"] is not None else np.nan,
                }
            )
    atomic_parquet(pd.DataFrame(rows), out)
    print("COMMON_SUPPORT_DESCRIPTIVES_OK", flush=True)


def parallel_models(plan, out_root: Path, cache_dir: Path, parallel):
    incomplete = [x for x in plan if not model_valid(out_root, x["model_id"])]
    total = len(plan)
    done_before = total - len(incomplete)
    print(
        "MODEL_PARALLEL_PLAN",
        f"total={total}",
        f"authenticated_complete={done_before}",
        f"remaining={len(incomplete)}",
        f"workers={parallel['model_workers']}",
        f"threads_per_worker={parallel['worker_threads']}",
        f"memory_per_worker={parallel['worker_memory_limit']}",
        flush=True,
    )
    if not incomplete:
        return

    spill_root = out_root / "private_cache" / "duckdb_spill"
    spill_root.mkdir(parents=True, exist_ok=True)

    tasks = [
        {
            "out_root": str(out_root),
            "cache_dir": str(cache_dir),
            "item": item,
            "worker_threads": parallel["worker_threads"],
            "worker_memory": parallel["worker_memory_limit"],
            "spill_root": str(spill_root),
        }
        for item in incomplete
    ]

    progress_path = out_root / "parallel_progress.json"
    completed = done_before
    failures = []

    with cf.ProcessPoolExecutor(max_workers=parallel["model_workers"]) as ex:
        futs = {ex.submit(worker_run_model, t): t["item"]["model_id"] for t in tasks}
        for fut in cf.as_completed(futs):
            model_id = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"status": "ERROR", "model_id": model_id, "error": repr(e)}
            if res["status"] in {"OK", "SKIPPED"}:
                completed += 1
                print(
                    "MODEL_PARALLEL_COMPLETE",
                    f"{completed}/{total}",
                    res["status"],
                    model_id,
                    f"pid={res.get('pid')}",
                    f"sec={res.get('seconds','')}",
                    flush=True,
                )
            else:
                failures.append(res)
                print("MODEL_PARALLEL_ERROR", model_id, res.get("error"), flush=True)

            atomic_json(
                {
                    "status": "RUNNING" if not failures else "ERROR_PRESENT",
                    "updated_utc": utc_now(),
                    "completed": completed,
                    "total": total,
                    "failures": failures,
                    "parallel_config": parallel,
                },
                progress_path,
            )

    if failures:
        raise RuntimeError(
            "One or more parallel models failed. Completed model Parquets are "
            "preserved and will authenticate/skip on rerun. First failure: "
            + str(failures[0])
        )


def consolidate_models(con, out_root: Path):
    coeff_files = sorted((out_root / "models").glob("*_coefficients.parquet"))
    receipt_files = sorted((out_root / "models").glob("*_receipt.json"))
    if not coeff_files or not receipt_files:
        raise SystemExit("No model outputs to consolidate.")

    coeff_list = ",".join(q(str(p)) for p in coeff_files)
    coeff_out = out_root / "fe_nonparametric_coefficients.parquet"
    con.execute(f"""
      COPY (
        SELECT * FROM read_parquet([{coeff_list}], union_by_name=true)
        ORDER BY model_id, term
      ) TO {q(str(coeff_out))}
      (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    receipts = pd.DataFrame([json.loads(p.read_text()) for p in receipt_files])
    receipts_out = out_root / "fe_nonparametric_receipts.parquet"
    atomic_parquet(receipts, receipts_out)

    coeff = pd.read_parquet(coeff_out)
    g = coeff[coeff["term"].astype(str).str.startswith("gap_")].copy()

    def parse_gap(term):
        s = term.replace("gap_", "")
        if s.startswith("p"):
            return int(s[1:])
        if s.startswith("m"):
            return -int(s[1:])
        return int(s)

    if len(g):
        g["gap_bin50"] = g["term"].map(parse_gap)
        g["gap_mid"] = g["gap_bin50"] * 50.0
        g["ci_lo_pp"] = g["coef_pp"] - 1.96 * g["se_pp"]
        g["ci_hi_pp"] = g["coef_pp"] + 1.96 * g["se_pp"]
        zeros = []
        for mid in g["model_id"].unique():
            zeros.append(
                {
                    "model_id": mid,
                    "term": "gap_0",
                    "coef_pp": 0.0,
                    "se_pp": 0.0,
                    "z": np.nan,
                    "identified": 1,
                    "gap_bin50": 0,
                    "gap_mid": 0.0,
                    "ci_lo_pp": 0.0,
                    "ci_hi_pp": 0.0,
                }
            )
        g = pd.concat([g, pd.DataFrame(zeros)], ignore_index=True)
        g.sort_values(["model_id", "gap_mid"], inplace=True)
        atomic_parquet(g, out_root / "fe_nonparametric_curves.parquet")


def self_test():
    rng = np.random.default_rng(20260831)
    G = 500
    per = 14
    n = G * per
    chooser = np.repeat(np.arange(G), per)
    alpha = rng.normal(0, 0.03, G)[chooser]
    gap_bin = rng.integers(-2, 3, n)
    x1 = (gap_bin == -1).astype(float)
    x2 = (gap_bin == 1).astype(float)
    z = rng.normal(size=n)
    p = np.clip(0.12 + alpha - 0.025 * x1 + 0.04 * x2 + 0.01 * z, 0.01, 0.8)
    y = rng.binomial(1, p)

    con = duckdb.connect(":memory:")
    df = pd.DataFrame({"chooser": chooser, "kind": y, "gap_bin50": gap_bin, "z": z})
    con.register("synthetic", df)
    terms = [
        ("gap_m1", "CASE WHEN gap_bin50=-1 THEN 1.0 ELSE 0.0 END"),
        ("gap_p1", "CASE WHEN gap_bin50=1 THEN 1.0 ELSE 0.0 END"),
        ("z", "z"),
    ]
    c, _ = fit_fe_targeted(con, "synthetic", "TRUE", terms, ["gap_m1", "gap_p1"], "synthetic")
    con.close()
    d = {row.term: row for row in c.itertuples()}
    if not (d["gap_m1"].coef_pp < 0 and d["gap_p1"].coef_pp > 0):
        raise SystemExit("SELF_TEST_FAIL: coefficient signs incorrect")
    if not (np.isfinite(d["gap_m1"].se_pp) and np.isfinite(d["gap_p1"].se_pp)):
        raise SystemExit("SELF_TEST_FAIL: targeted CR1 SE missing")
    print("SELF_TEST_OK", flush=True)


def main():
    a = parse_args()
    if a.self_test:
        self_test()
        return
    if a.out_root is None:
        raise SystemExit("--out-root required outside --self-test")

    out = a.out_root
    out.mkdir(parents=True, exist_ok=True)

    parallel = auto_parallel_config(
        a.model_workers, a.worker_threads, a.worker_memory_limit
    )

    con = duckdb.connect(":memory:")
    con.execute(f"SET threads={a.prep_threads}")
    con.execute(f"SET memory_limit={q(a.prep_memory_limit)}")
    con.execute("SET preserve_insertion_order=false")

    src_settings, src_auth = source_authenticate(con)
    auth = {
        "status": "SOURCE_AUTHENTICATED_OK",
        "created_utc": utc_now(),
        "source_settings": str(SOURCE_SETTINGS),
        "source_cache": str(SOURCE_CACHE),
        "source_settings_sha256": sha256_file(SOURCE_SETTINGS),
        "authority": src_auth,
    }
    atomic_json(auth, out / "source_authentication.json")
    print("SOURCE_AUTHENTICATED_OK", src_auth, flush=True)

    cache_dir, cache_receipt = build_private_cache(con, out)
    months, speeds = categories(con, cache_dir)

    descriptive_curves(con, cache_dir, out)
    common_support_descriptives(con, cache_dir, out)

    plan = build_model_plan(months, speeds, cache_receipt)
    atomic_parquet(plan_public_df(plan), out / "model_plan.parquet")

    # Close the coordinator connection before spawning workers so no inherited
    # DuckDB state/file descriptors exist under fork/spawn.
    con.close()

    print("PARALLEL_CONFIG", parallel, flush=True)
    parallel_models(plan, out, cache_dir, parallel)

    con = duckdb.connect(":memory:")
    con.execute(f"SET threads={a.prep_threads}")
    con.execute(f"SET memory_limit={q(a.prep_memory_limit)}")
    consolidate_models(con, out)
    con.close()

    settings = {
        "status": "RATING_GAP_NONPARAMETRIC_CLOSURE_V110_OK",
        "created_utc": utc_now(),
        "scientific_status": "exploratory closure; scientific design unchanged from v1.0.x",
        "storage_policy": "Parquet-first for all tabular inputs/intermediates/outputs",
        "parallel_config": parallel,
        "prep_threads": a.prep_threads,
        "prep_memory_limit": a.prep_memory_limit,
        "source_authentication": auth,
        "primary_gap_definition": "disconnected_elo - chooser_elo",
        "gap_bin_definition": "50-Elo bins; omitted [-25,+25); modeled centers -550..+550",
        "primary_controls": "chooser FE; chooser-clustered CR1; K20 FE; month FE; speed FE; ply FE; cubic within-band eval; win premium",
        "private_cache": str(out / "private_cache"),
        "privacy": "private_cache contains chooser identifiers; never upload or commit",
        "software": {
            "python": sys.version,
            "duckdb": duckdb.__version__,
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "platform": platform.platform(),
        },
    }
    atomic_json(settings, out / "settings.json")

    # Fail-closed public-output gate.
    required = [
        "00_descriptive_rating_gap_curves.parquet",
        "common_support_chooser_equal_differences.parquet",
        "model_plan.parquet",
        "fe_nonparametric_coefficients.parquet",
        "fe_nonparametric_curves.parquet",
        "fe_nonparametric_receipts.parquet",
        "settings.json",
    ]
    for name in required:
        p = out / name
        if not p.is_file() or p.stat().st_size == 0:
            raise SystemExit(f"Missing/empty required output: {p}")

    print("RATING_GAP_NONPARAMETRIC_CLOSURE_V110_OK")
    print("Output root:", out)


if __name__ == "__main__":
    main()
