#!/usr/bin/env python3
"""Exact streamed chooser-FE LPMs on the authenticated 24-month pool panel.

Two joint models on identical complete-case support; no network or API calls.
Sorted private Parquet makes every chooser contiguous. Both passes process
complete chooser groups, so no iterative FE approximation or group splitting.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
from scipy import stats
from threadpoolctl import threadpool_limits

from vendor import wave1_common as authority

VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parent
BOARD = ["clearly_worse", "modestly_worse_excluded", "roughly_equal",
         "disconnected_better", "disconnected_clearly_better"]
BOARD_LABELS = ["Clearly losing", "Modestly worse", "Roughly equal",
                "Better", "Clearly better"]
PLY = ["0_4", "5_6", "7_8", "9_10", "11_20", "21_40", "41_80", "81_plus"]
CORE = ["board_" + s for s in BOARD[1:]] + ["ply_" + s for s in PLY[1:]]
EXPECTED_BINS = dict(zip(BOARD, [22664818, 3662090, 9244704, 2919470, 3043249]))
EXPECTED_DRAWS = dict(zip(BOARD, [106556, 44072, 240825, 69801, 108837]))
EXPECTED_HEADLINES = {"rows": 41534331, "kind_draws": 570091, "choosers": 3224173}
CACHE_COLUMNS = ["chooser", "y", "board", "ply", "month_code", "speed_code",
                 "winprem10", "log_chooser_clock", "log_disconnected_clock", "clock_missing"]


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def log(message):
    print(f"[{stamp()}] {message}", flush=True)


def sqlstr(value):
    return "'" + str(value).replace("'", "''") + "'"


def write_json(path, value):
    authority.atomic_json(Path(path), value)


def write_csv(path, rows, fieldnames=None):
    rows = list(rows)
    fields = fieldnames or (list(rows[0]) if rows else [])
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def query_rows(con, sql):
    cur = con.execute(sql)
    fields = [x[0] for x in cur.description]
    return [dict(zip(fields, r)) for r in cur.fetchall()]


def verify_package():
    manifest = ROOT / "SHA256SUMS.txt"
    if not manifest.is_file():
        raise RuntimeError("Missing package SHA256SUMS.txt")
    for line in manifest.read_text().splitlines():
        digest, relative = line.split("  ", 1)
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise RuntimeError(f"Invalid package manifest member: {relative}")
        if authority.sha256_file(path) != digest:
            raise RuntimeError(f"Package changed: {relative}")


def board_sql(col="engine_eval_cp_disconnected"):
    return (f"CASE WHEN {col} <= -300 THEN 0 WHEN {col} < -100 THEN 1 "
            f"WHEN {col} <= 100 THEN 2 WHEN {col} < 300 THEN 3 ELSE 4 END")


def ply_sql(col="ply_count"):
    return (f"CASE WHEN {col} <= 4 THEN 0 WHEN {col} <= 6 THEN 1 "
            f"WHEN {col} <= 8 THEN 2 WHEN {col} <= 10 THEN 3 "
            f"WHEN {col} <= 20 THEN 4 WHEN {col} <= 40 THEN 5 "
            f"WHEN {col} <= 80 THEN 6 ELSE 7 END")


def prepare_cache(con, paths, private, public):
    source = "read_parquet([" + ",".join(sqlstr(p) for p in paths) + "], hive_partitioning=false)"
    con.execute(f"CREATE VIEW panel AS SELECT * FROM {source}")
    required = ["chooser_user_id", "outcome_kind_draw", "engine_fairness_bin",
                "engine_eval_cp_disconnected", "ply_count", "month", "api_speed",
                "chooser_win_premium_v2", "chooser_clock_last_obs_s",
                "disconnected_clock_last_obs_s"]
    names = {r[0] for r in con.execute("DESCRIBE panel").fetchall()}
    if set(required) - names:
        raise RuntimeError(f"Required fields absent: {sorted(set(required)-names)}")
    state_mapping = "CASE engine_fairness_bin " + " ".join(
        f"WHEN {sqlstr(b)} THEN {i}" for i, b in enumerate(BOARD)) + " ELSE NULL END"
    # Invalid clocks are retained with zero imputation and an any-clock missing flag.
    con.execute(f"""CREATE VIEW tagged AS SELECT *,
      {state_mapping} AS board_code,
      (chooser_user_id IS NOT NULL AND outcome_kind_draw IS NOT NULL
       AND engine_fairness_bin IN ({','.join(sqlstr(x) for x in BOARD)})
       AND engine_eval_cp_disconnected IS NOT NULL
       AND isfinite(engine_eval_cp_disconnected)
       AND ply_count IS NOT NULL AND isfinite(CAST(ply_count AS DOUBLE))
       AND ply_count >= 0 AND ply_count=floor(ply_count)) AS core_ok,
      (month IS NOT NULL AND length(CAST(month AS VARCHAR))=7
       AND api_speed IS NOT NULL AND length(trim(api_speed))>0
       AND chooser_win_premium_v2 IS NOT NULL
       AND isfinite(chooser_win_premium_v2)) AS controls_ok,
      (chooser_clock_last_obs_s IS NULL OR NOT isfinite(chooser_clock_last_obs_s)) AS cm,
      (disconnected_clock_last_obs_s IS NULL OR NOT isfinite(disconnected_clock_last_obs_s)) AS dm
      FROM panel""")
    raw = query_rows(con, """SELECT count(*) AS rows,
      sum(outcome_kind_draw::INTEGER) AS kind_draws,
      count(DISTINCT chooser_user_id) AS choosers FROM tagged""")[0]
    if raw != EXPECTED_HEADLINES:
        raise RuntimeError(f"Panel headline counts do not match authority: {raw}")
    raw_bins = query_rows(con, """SELECT engine_fairness_bin AS board_state,
      count(*) AS rows, sum(outcome_kind_draw::INTEGER) AS kind_draws
      FROM tagged GROUP BY engine_fairness_bin ORDER BY engine_fairness_bin""")
    if ({r["board_state"]: r["rows"] for r in raw_bins} != EXPECTED_BINS or
        {r["board_state"]: r["kind_draws"] for r in raw_bins} != EXPECTED_DRAWS):
        raise RuntimeError("Frozen five-bin sample counts do not reproduce")
    write_csv(public / "raw_five_state_counts.csv", raw_bins)
    mismatches = con.execute(f"""SELECT count(*) FROM tagged
      WHERE core_ok AND board_code != {board_sql()}""").fetchone()[0]
    if mismatches:
        raise RuntimeError(f"Stored board bins disagree with frozen boundaries: {mismatches}")
    flow = query_rows(con, """SELECT
      CASE WHEN NOT coalesce(core_ok,false) THEN 'missing_or_invalid_core'
           WHEN NOT coalesce(controls_ok,false) THEN 'missing_or_invalid_controls'
           ELSE 'included_common_sample' END AS category,
      count(*) AS rows, sum(outcome_kind_draw::INTEGER) AS kind_draws
      FROM tagged GROUP BY category ORDER BY category""")
    write_csv(public / "sample_flow.csv", flow)
    common_n = next((r["rows"] for r in flow if r["category"] == "included_common_sample"), 0)
    if common_n == 0:
        raise RuntimeError("Empty common estimation sample")
    con.execute("CREATE VIEW eligible AS SELECT * FROM tagged WHERE core_ok AND controls_ok")
    missing = query_rows(con, """SELECT count(*) AS rows,
      sum(cm::INT) AS chooser_clock_missing_or_nonfinite,
      sum(dm::INT) AS disconnected_clock_missing_or_nonfinite,
      sum((cm OR dm)::INT) AS any_clock_missing_or_nonfinite,
      count(*) FILTER (WHERE NOT cm AND chooser_clock_last_obs_s<0) AS chooser_clock_negative_clamped,
      count(*) FILTER (WHERE NOT dm AND disconnected_clock_last_obs_s<0) AS disconnected_clock_negative_clamped
      FROM eligible""")
    write_csv(public / "clock_handling.csv", missing)
    months = [r[0] for r in con.execute("SELECT DISTINCT CAST(month AS VARCHAR) FROM eligible ORDER BY 1").fetchall()]
    speeds = [r[0] for r in con.execute("SELECT DISTINCT CAST(api_speed AS VARCHAR) FROM eligible ORDER BY 1").fetchall()]
    month_case = "CASE CAST(month AS VARCHAR) " + " ".join(f"WHEN {sqlstr(x)} THEN {i}" for i,x in enumerate(months)) + " END"
    speed_case = "CASE CAST(api_speed AS VARCHAR) " + " ".join(f"WHEN {sqlstr(x)} THEN {i}" for i,x in enumerate(speeds)) + " END"
    cells = query_rows(con, f"""SELECT engine_fairness_bin AS board_state,
      {ply_sql()} AS ply_code, count(*) AS rows,
      sum(outcome_kind_draw::INTEGER) AS kind_draws,
      100*avg(outcome_kind_draw::DOUBLE) AS kind_rate_pct
      FROM eligible GROUP BY engine_fairness_bin,ply_code ORDER BY engine_fairness_bin,ply_code""")
    for r in cells:
        r["ply_band"] = PLY[r.pop("ply_code")]
    write_csv(public / "common_sample_board_by_ply.csv", cells)
    cache = private / "sorted_model_PRIVATE.parquet"
    log(f"Writing sorted private cache for {common_n:,} observations")
    con.execute(f"""COPY (SELECT
      chooser_user_id::BIGINT AS chooser, outcome_kind_draw::DOUBLE AS y,
      board_code::TINYINT AS board, ({ply_sql()})::TINYINT AS ply,
      ({month_case})::SMALLINT AS month_code, ({speed_case})::TINYINT AS speed_code,
      chooser_win_premium_v2::DOUBLE/10.0 AS winprem10,
      CASE WHEN cm THEN 0 ELSE ln(1+greatest(chooser_clock_last_obs_s,0)) END::DOUBLE AS log_chooser_clock,
      CASE WHEN dm THEN 0 ELSE ln(1+greatest(disconnected_clock_last_obs_s,0)) END::DOUBLE AS log_disconnected_clock,
      (cm OR dm)::DOUBLE AS clock_missing
      FROM eligible ORDER BY chooser_user_id) TO {sqlstr(cache)}
      (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 131072)""")
    meta = {"rows": common_n, "months": months, "speeds": speeds,
            "raw_counts": raw, "sample_flow": flow,
            "cache_sha256": authority.sha256_file(cache)}
    write_json(private / "cache_receipt.json", meta)
    return cache, meta


def complete_group_batches(cache, batch_size=131072):
    """Never split a chooser across yielded arrays; bounded by batch + max group."""
    pending = None
    previous = None
    for batch in pq.ParquetFile(cache).iter_batches(batch_size=batch_size, columns=CACHE_COLUMNS):
        current = {n: batch.column(n).to_numpy(zero_copy_only=False) for n in CACHE_COLUMNS}
        if pending is not None:
            current = {n: np.concatenate([pending[n], current[n]]) for n in CACHE_COLUMNS}
        ids = current["chooser"]
        if np.any(ids[1:] < ids[:-1]) or (previous is not None and ids[0] <= previous):
            raise RuntimeError("Private cache is not sorted into complete chooser groups")
        # Keep the final (possibly incomplete) chooser for the next Arrow batch.
        cut = int(np.searchsorted(ids, ids[-1], side="left"))
        if cut:
            yield {n: v[:cut] for n,v in current.items()}
            previous = ids[cut-1]
        pending = {n: v[cut:].copy() for n,v in current.items()}
    if pending is not None and len(pending["chooser"]):
        yield pending


def term_names(meta):
    return (CORE + ["winprem10", "log_chooser_clock", "log_disconnected_clock", "clock_missing"]
            + ["month_"+x for x in meta["months"][1:]]
            + ["speed_"+x for x in meta["speeds"][1:]])


def demean_batch(data, meta):
    n = len(data["y"])
    columns = [data["board"]==j for j in range(1,5)] + [data["ply"]==j for j in range(1,8)]
    columns += [data[x] for x in ["winprem10", "log_chooser_clock", "log_disconnected_clock", "clock_missing"]]
    columns += [data["month_code"]==j for j in range(1,len(meta["months"]))]
    columns += [data["speed_code"]==j for j in range(1,len(meta["speeds"]))]
    Z = np.empty((n, len(columns)+1), dtype=np.float64)
    Z[:,0] = data["y"]
    for j,c in enumerate(columns, 1):
        Z[:,j] = c
    if not np.isfinite(Z).all():
        raise RuntimeError("Nonfinite outcome or design in model cache")
    starts = np.r_[0, np.flatnonzero(data["chooser"][1:] != data["chooser"][:-1])+1]
    counts = np.diff(np.r_[starts, n])
    means = np.add.reduceat(Z, starts, axis=0)/counts[:,None]
    Z -= np.repeat(means, counts, axis=0)
    return Z, starts, counts


def solve_system(xx, xy, names, allow_drop=True):
    """Equilibrated normal equations; fail on nonidentified target terms."""
    diag = np.diag(xx)
    if np.any(diag < -1e-8):
        raise RuntimeError("Negative centered design sum of squares")
    active = np.flatnonzero(diag > 1e-12)
    dropped = [names[j] for j in range(len(names)) if j not in active]
    if any(x in CORE for x in dropped) or (dropped and not allow_drop):
        raise RuntimeError(f"Unidentified target terms: {dropped}")
    scale = np.sqrt(diag[active])
    A = xx[np.ix_(active, active)] / scale[:,None] / scale[None,:]
    eigen = np.linalg.eigvalsh(A)
    if eigen[0] <= 1e-11*eigen[-1]:
        raise RuntimeError(f"Collinear within design (scaled eigenvalues {eigen[0]}, {eigen[-1]}); no silent pseudoinverse")
    inv = np.linalg.inv(A) / scale[:,None] / scale[None,:]
    beta = inv @ xy[active]
    residual = np.max(np.abs(xx[np.ix_(active,active)] @ beta-xy[active]))
    relative = float(residual / max(1.0,np.max(np.abs(xy[active]))))
    if relative > 1e-7:
        raise RuntimeError(f"Normal equations failed: {relative}")
    return {"active": active, "beta": beta, "bread": inv, "dropped": dropped,
            "condition_scaled": float(eigen[-1]/eigen[0]), "normal_equation_relative_error": relative}


def fit_models(cache, meta, private, batch_size=131072):
    names = term_names(meta)
    cross = np.zeros((len(names)+1,len(names)+1))
    variation = np.zeros(len(names), dtype=np.int64)
    counters = {"rows": 0, "choosers": 0, "singleton_choosers": 0,
                "zero_grant_choosers": 0, "board_varying_choosers": 0, "ply_varying_choosers": 0}
    last_log = time.monotonic()
    for data in complete_group_batches(cache, batch_size):
        Z, starts, counts = demean_batch(data, meta)
        cross += Z.T @ Z
        group_ss = np.add.reduceat(Z[:,1:]**2, starts, axis=0)
        variation += np.sum(group_ss>1e-14,axis=0)
        counters["rows"] += len(Z)
        counters["choosers"] += len(starts)
        counters["singleton_choosers"] += int(np.sum(counts==1))
        counters["zero_grant_choosers"] += int(np.sum(np.add.reduceat(data["y"],starts)==0))
        counters["board_varying_choosers"] += int(np.sum(np.sum(group_ss[:,:4],axis=1)>1e-14))
        counters["ply_varying_choosers"] += int(np.sum(np.sum(group_ss[:,4:11],axis=1)>1e-14))
        if time.monotonic()-last_log > 25:
            log(f"PASS 1/2: {counters['rows']:,}/{meta['rows']:,} observations")
            last_log=time.monotonic()
    if counters["rows"] != meta["rows"] or counters["choosers"] < 2:
        raise RuntimeError("Regression row/cluster conservation failure")
    np.savez(private / "centered_cross_products.npz", cross=cross, variation=variation)
    models=[]
    for model_id, p in [("M1_joint_chooser_FE",11),("M2_joint_adjusted",len(names))]:
        fit = solve_system(cross[1:p+1,1:p+1],cross[1:p+1,0],names[:p])
        fit.update(model=model_id, terms=[names[j] for j in fit["active"]],
                   meat=np.zeros_like(fit["bread"]), score_sum=np.zeros(len(fit["beta"])), sse=0.)
        models.append(fit)
    done=0
    for data in complete_group_batches(cache, batch_size):
        Z, starts, counts=demean_batch(data, meta)
        for fit in models:
            X=Z[:,fit["active"]+1]
            resid=Z[:,0]-X@fit["beta"]
            scores=np.add.reduceat(X*resid[:,None],starts,axis=0)
            fit["meat"] += scores.T@scores
            fit["score_sum"] += scores.sum(axis=0)
            fit["sse"] += float(resid@resid)
        done+=len(Z)
        if time.monotonic()-last_log>25:
            log(f"PASS 2/2: {done:,}/{meta['rows']:,} observations")
            last_log=time.monotonic()
    for fit in models:
        g=counters["choosers"]
        fit["cov"] = g/(g-1) * fit["bread"]@fit["meat"]@fit["bread"]
        fit["cov"]=(fit["cov"]+fit["cov"].T)/2
        fit["se"]=np.sqrt(np.maximum(0,np.diag(fit["cov"])))
        fit["within_r2"]=1-fit["sse"]/cross[0,0] if cross[0,0]>0 else None
        fit["score_relative_error"] = float(np.max(np.abs(fit["score_sum"]))/max(1.,np.max(np.abs(cross[1:,0]))))
        if fit["score_relative_error"]>1e-7 or np.any(fit["se"]<=0):
            raise RuntimeError("Cluster-score/standard-error audit failed")
    return models,counters,variation


def export_results(models, counters, variation, meta, public):
    coefficients=[]
    receipts=[]
    tests=[]
    for fit in models:
        g=counters["choosers"]
        for j,name in enumerate(fit["terms"]):
            b,se=float(fit["beta"][j]),float(fit["se"][j])
            t=b/se
            critical=float(stats.t.ppf(.975,g-1))
            coefficients.append({"model":fit["model"],"term":name,"coef_pp":100*b,
                "se_pp":100*se,"t":t,"p_value":float(2*stats.t.sf(abs(t),g-1)),
                "ci_low_pp":100*(b-critical*se),"ci_high_pp":100*(b+critical*se)})
        covariance=[dict(term=name,**{n:float(fit["cov"][i,j]*10000) for j,n in enumerate(fit["terms"])})
                    for i,name in enumerate(fit["terms"])]
        write_csv(public/(fit["model"]+"_covariance_pp2.csv"),covariance)
        for block,terms in [("board_state",CORE[:4]),("ply_band",CORE[4:])]:
            ix=[fit["terms"].index(t) for t in terms]
            b=fit["beta"][ix]; V=fit["cov"][np.ix_(ix,ix)]
            W=float(b@np.linalg.solve(V,b)); q=len(ix)
            tests.append({"model":fit["model"],"block":block,"wald_chi2":W,"df":q,
                          "p_chi2":float(stats.chi2.sf(W,q)),"F":W/q,"df_denom":g-1,
                          "p_F":float(stats.f.sf(W/q,q,g-1))})
        receipts.append({"model":fit["model"],**counters,"terms_estimated":len(fit["terms"]),
            "dropped_zero_within_controls":";".join(fit["dropped"]),
            "within_r2":fit["within_r2"],"condition_scaled":fit["condition_scaled"],
            "normal_equation_relative_error":fit["normal_equation_relative_error"],
            "score_relative_error":fit["score_relative_error"],
            "covariance":"chooser-cluster CR1 = CR0 * G/(G-1); absorbed chooser df not counted"})
    write_csv(public/"coefficients.csv",coefficients)
    write_csv(public/"model_receipts.csv",receipts)
    write_csv(public/"joint_tests.csv",tests)
    write_csv(public/"within_variation_support.csv",[dict(term=t,choosers_with_within_variation=int(n))
        for t,n in zip(term_names(meta),variation)])
    # Conventional tables: all coefficients/controls remain in the CSV. Compact
    # slide selects middle/late bands without refitting or merging their bins.
    lookup={(r["model"],r["term"]):r for r in coefficients}
    labels=dict(zip(CORE,BOARD_LABELS[1:]+[s.replace("_","--").replace("81--plus","81+") for s in PLY[1:]]))
    def values(term):
        return [f"{lookup[(m['model'],term)]['coef_pp']:.3f} ({lookup[(m['model'],term)]['se_pp']:.3f})" for m in models]
    def table(terms, tex):
        if not tex:
            lines=["| | (1) Chooser FE | (2) Adjusted |","|---|---:|---:|"]
            lines += ["| "+labels[t]+" | "+" | ".join(values(t))+" |" for t in terms]
            lines += ["| Chooser FE | Yes | Yes |", "| Month and speed FE | No | Yes |",
                      "| Win premium and clocks | No | Yes |",
                      f"| Opportunities | {counters['rows']:,} | {counters['rows']:,} |",
                      f"| Choosers | {counters['choosers']:,} | {counters['choosers']:,} |"]
            return "\n".join(lines)
        lines=[r"\begin{tabular}{@{}lcc@{}}",r"\toprule",r" & (1) & (2) \\",r"\midrule",
               r"\multicolumn{3}{@{}l}{\textit{Board state (reference: clearly losing)}} \\"]
        for t in terms:
            if t==next((s for s in terms if s.startswith("ply_")),None):
                lines += [r"\addlinespace[0.4em]",r"\multicolumn{3}{@{}l}{\textit{Plies (reference: 0--4)}} \\"]
            lines.append(labels[t]+" & "+" & ".join(values(t))+r" \\")
        lines += [r"\midrule",r"Chooser FE & Yes & Yes \\",r"Month and speed FE & No & Yes \\",
                  r"Win premium and clocks & No & Yes \\",
                  f"Opportunities & {counters['rows']:,} & {counters['rows']:,}"+r" \\",
                  r"\bottomrule",r"\end{tabular}"]
        return "\n".join(lines)
    (public/"regression_table_full.tex").write_text(table(CORE,True)+"\n")
    selected=CORE[:4]+["ply_11_20","ply_21_40","ply_41_80"]
    (public/"regression_table_slide.tex").write_text(table(selected,True)+"\n")
    notes=("Outcome: Call draw. Coefficients and chooser-clustered SEs in percentage points. "
      "Both columns use the identical common sample and include all four nonreference board indicators "
      "and all seven nonreference ply indicators. Column (2) adds month and exact API-speed fixed effects, "
      "forgone-win premium / 10, log(1 + max(clock seconds,0)) for each player, and an indicator "
      "for either clock missing/nonfinite (these logs are zero-imputed). No first/repeat-meeting term. "
      "No draw-payoff, RD, rating-gap, or board-by-ply interaction terms. No selection on ever granting. "
      "Baseline states: disconnected player <= -300 cp; 0--4 plies. Board effects are common across "
      "ply bands and ply effects common across board states in these additive specifications. "
      "Estimates describe conditional within-chooser associations, not causal effects. "
      "The compact slide displays only three of seven included ply coefficients. "
      "Joint tests cover all four board coefficients or all seven ply coefficients. "
      "P-values can underflow to zero; this means below numerical precision, not literally zero.")
    summary="# Joint board state and game length\n\n"+table(CORE,False)+"\n\n"+notes+"\n"
    (public/"RESULTS.md").write_text(summary)
    (public/"TABLE_NOTES.txt").write_text(notes+"\n")


def run(args):
    verify_package()
    project=args.project_root.expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError(f"Project drive is not mounted or path is wrong: {project}")
    sample=(args.sample_root or project/"derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE").resolve()
    log(f"Authenticating current sample: {sample}")
    auth=authority.authenticate_sample(sample,verify_hashes=True,hash_workers=min(args.threads,10))
    files=[r["path"] for r in auth["month_records"]]
    before={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in files}
    runid=stamp()+"_"+str(os.getpid())
    base=project/"derived/replication/joint_state_ply_v100_PRIVATE"
    base.mkdir(parents=True,exist_ok=True)
    private=Path(tempfile.mkdtemp(prefix=runid+"_",dir=base))
    public=private/("POOL_JOINT_STATE_PLY_RESULTS_v100_"+runid)
    public.mkdir()
    log(f"Working directory (private): {private}")
    write_json(public/"SAMPLE_LINEAGE.json",authority.compact_sample_lineage(auth))
    write_json(public/"ENVIRONMENT.json",{"python":sys.version,"platform":platform.platform(),
        "duckdb":duckdb.__version__,"numpy":np.__version__,"pyarrow":pa.__version__,
        "scipy":scipy.__version__,"threads":args.threads,"memory_limit":args.memory_limit})
    try:
        con=duckdb.connect(str(private/"working.duckdb"))
        con.execute(f"SET threads={args.threads}")
        con.execute(f"SET memory_limit={sqlstr(args.memory_limit)}")
        con.execute(f"SET temp_directory={sqlstr(private/'duckdb_spill')}")
        con.execute("SET preserve_insertion_order=true")
        # Sorting must preserve global chooser order in the written Parquet.
        cache,meta=prepare_cache(con,files,private,public)
        con.close()
        log("Estimating both joint models with exact within-chooser demeaning")
        with threadpool_limits(limits=args.threads):
            models,counters,variation=fit_models(cache,meta,private,args.batch_size)
        export_results(models,counters,variation,meta,public)
        write_json(public/"MODEL_SPECIFICATION.json",{
            "version":VERSION,"common_support":True,"outcome":"outcome_kind_draw",
            "board_bins":dict(zip(BOARD,["cp<=-300","-300<cp<-100","-100<=cp<=100","100<cp<300","cp>=300"])),
            "ply_bins":PLY,"terms":term_names(meta),"month_reference":meta["months"][0],
            "speed_reference":meta["speeds"][0],"months":meta["months"],"speeds":meta["speeds"],
            "weights":"one per opportunity","first_meeting_included":False,
            "sample_support":counters,"cache_sha256":meta["cache_sha256"],
            "covariance":"chooser clustered CR1, G/(G-1) only; no absorbed FE df penalty"})
        after={str(p):(p.stat().st_size,p.stat().st_mtime_ns) for p in files}
        if after != before:
            raise RuntimeError("A source file changed while this job ran")
        # Return aggregates and reproducible code only; never private rows/IDs.
        source_dir=public/"code"
        source_dir.mkdir()
        package_files=[line.split("  ",1)[1] for line in (ROOT/"SHA256SUMS.txt").read_text().splitlines()]
        for name in package_files+["SHA256SUMS.txt"]:
            destination=source_dir/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(ROOT/name,destination)
        write_json(public/"_SUCCESS.json",{"status":"POOL_JOINT_STATE_PLY_OK","version":VERSION,
            "completed_utc":stamp(),"sample_fingerprint":auth["fingerprint"],
            "panel_rows":auth["authority"]["rows"],"estimated_rows":counters["rows"],
            "inputs_unchanged_by_stat":True,"input_full_sha256_verified_at_start":True,
            "models":[m["model"] for m in models],"private_records_in_archive":False})
        authority.write_manifest_tsv(public)
        target=args.transfer_root.expanduser().resolve()
        target.mkdir(parents=True,exist_ok=True)
        archive=target/(public.name+".zip")
        if archive.exists():
            raise RuntimeError(f"Refusing to overwrite result archive: {archive}")
        authority.zip_tree(public,archive)
        archive.with_suffix(".zip.sha256").write_text(authority.sha256_file(archive)+"  "+archive.name+"\n")
        log(f"SUCCESS. Return these two files:\n{archive}\n{archive}.sha256")
        log("Private sorted cache retained locally. No source files were modified.")
    except Exception as exc:
        write_json(private/"FAILED.json",{"status":"FAILED","error":str(exc),"traceback":traceback.format_exc()})
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--project-root",type=Path,default=Path("/Volumes/XT_Pro/lichess_kindness"))
    p.add_argument("--sample-root",type=Path)
    p.add_argument("--transfer-root",type=Path,default=Path.home()/"Desktop/Lichess_Desktop")
    p.add_argument("--threads",type=int,default=10)
    p.add_argument("--memory-limit",default="6GB")
    p.add_argument("--batch-size",type=int,default=131072)
    args=p.parse_args()
    if not 1<=args.threads<=10 or args.batch_size<16:
        p.error("threads must be 1..10 and batch-size >=16")
    if args.self_test:
        from test_joint_state_ply import run_tests
        with threadpool_limits(limits=min(args.threads,2)):
            run_tests()
        return
    run(args)


if __name__=="__main__":
    main()
