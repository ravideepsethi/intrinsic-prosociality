#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Packaging revision r3 recognizes that certified user_events intentionally omit game result.
# C2/C3 use user_events directly; C1 bridges only the needed preceding game IDs to the
# certified selected-game/header layer. Rating-difference sign is never used as a result proxy.

PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
EXPECTED_HISTORY_ROWS = 309_961_276
EXPECTED_TARGET_ROWS = 685_731
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_HISTORY_SUCCESS_SHA = "62e4b8335b188f374f83bf1debedc19c62a91769f89a7c12368a628cb26d6de5"
BASE_SHA = "ded9965994b6c00ed613adc90eaff3f976b257e9eb6dafdda61819916dde49fe"
AMD101_SHA = "01c0ed96bfca62b1659a98d978bedaaf9a4540fcdc5a30a075e2f032e35e05ee"
AMD102_SHA = "7eeca3ab8591620a196badbd1b9d3184236d67a031cf9eff06b76584995c0049"
AMD103_SHA = "96530f7ffd43b7d68ff84c794200f7db98b2b455ea2994efb5b73ce5cb370a07"

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha256_file(p: Path, chunk=8*1024*1024):
    h=hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b=f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def q(s: str):
    return '"' + s.replace('"','""') + '"'

def sqls(s: str):
    return "'" + str(s).replace("'","''") + "'"

def write_csv(path: Path, rows: list[dict[str,Any]]):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as f:
        w=csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

def run(cmd, cwd=None):
    p=subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    return p.stdout.strip()

def first_col(cols, aliases, contains=None):
    low={c.lower():c for c in cols}
    for a in aliases:
        if a.lower() in low:
            return low[a.lower()]
    if contains:
        cand=[c for c in cols if all(t.lower() in c.lower() for t in contains)]
        if len(cand)==1:
            return cand[0]
    return None

def must(label, value, cols):
    if value is None:
        raise RuntimeError(f"Could not resolve {label}; available columns={cols}")
    return value

def parquet_schema(p: Path):
    import pyarrow.parquet as pq
    pf=pq.ParquetFile(p)
    return {
        "rows": int(pf.metadata.num_rows),
        "columns": list(pf.schema_arrow.names),
        "types": {f.name:str(f.type) for f in pf.schema_arrow},
    }

def total_rows(paths):
    import pyarrow.parquet as pq
    return sum(int(pq.ParquetFile(p).metadata.num_rows) for p in paths)

def time_expr(col: str, typ: str):
    lc=typ.lower()
    if "timestamp" in lc or "date" in lc:
        return f"epoch_ms({q(col)})"
    if any(x in lc for x in ("int","double","float","decimal")):
        # Production chronology millisecond fields are integral; if a generic
        # numeric datetime is supplied, require millisecond scale in QA below.
        return f"CAST({q(col)} AS BIGINT)"
    return f"epoch_ms(CAST({q(col)} AS TIMESTAMP))"

def infer_result_case(col: str, color_col: str|None, observed_values: list[str]):
    """Resolve history result semantics without guessing whether numeric zero is loss or draw."""
    vals={str(x).strip().lower() for x in observed_values if x is not None}
    v=f"lower(trim(CAST({q(col)} AS VARCHAR)))"
    color=f"lower(trim(CAST({q(color_col)} AS VARCHAR)))" if color_col else "''"

    raw_tokens={"1-0","0-1","1/2-1/2","½-½"}
    text_tokens={"win","w","loss","lose","l","draw","d"}
    if vals & raw_tokens:
        if color_col is None:
            raise RuntimeError(
                f"History result field {col} contains raw game results but no user-color column was resolved"
            )
        return f"""CASE
          WHEN {v} IN ('1/2-1/2','½-½') THEN 0
          WHEN {v}='1-0' AND {color} IN ('white','w') THEN 1
          WHEN {v}='1-0' AND {color} IN ('black','b') THEN -1
          WHEN {v}='0-1' AND {color} IN ('black','b') THEN 1
          WHEN {v}='0-1' AND {color} IN ('white','w') THEN -1
          ELSE NULL
        END"""
    if vals & text_tokens:
        return f"""CASE
          WHEN {v} IN ('win','w') THEN 1
          WHEN {v} IN ('loss','lose','l') THEN -1
          WHEN {v} IN ('draw','d') THEN 0
          ELSE NULL
        END"""

    numeric=set()
    numeric_ok=True
    for x in vals:
        try:
            numeric.add(float(x))
        except Exception:
            numeric_ok=False
            break
    if numeric_ok and numeric:
        if numeric.issubset({-1.0,0.0,1.0}) and -1.0 in numeric:
            return f"""CASE
              WHEN CAST({q(col)} AS DOUBLE)>0.5 THEN 1
              WHEN CAST({q(col)} AS DOUBLE)<-0.5 THEN -1
              WHEN abs(CAST({q(col)} AS DOUBLE))<=0.5 THEN 0
              ELSE NULL
            END"""
        if numeric.issubset({0.0,0.5,1.0}) and 0.5 in numeric:
            return f"""CASE
              WHEN CAST({q(col)} AS DOUBLE)>0.75 THEN 1
              WHEN CAST({q(col)} AS DOUBLE)<0.25 THEN -1
              WHEN CAST({q(col)} AS DOUBLE) BETWEEN 0.25 AND 0.75 THEN 0
              ELSE NULL
            END"""
        if numeric.issubset({0.0,1.0}):
            raise RuntimeError(
                f"Ambiguous binary history result coding in {col}: values={sorted(numeric)}; "
                "cannot tell whether zero means loss or draw without guessing"
            )
    raise RuntimeError(f"Unrecognized history result coding in {col}: sample values={sorted(vals)[:30]}")


def resolve_selected_game_result_schema(cols: list[str]) -> dict[str, str|None]:
    """Resolve an authoritative game-level result schema; never infer result from rating change."""
    game=first_col(cols,["game_id","id","event_game_id"],["game","id"])
    result=first_col(cols,[
        "result","pgn_result","game_result","raw_result","realized_outcome_branch",
        "outcome_branch","winner","api_winner"
    ])
    white=first_col(cols,["white_id","white_user_id","white_user","white_player_id"])
    black=first_col(cols,["black_id","black_user_id","black_user","black_player_id"])
    return {"game_id":game,"result":result,"white_id":white,"black_id":black}

def selected_result_sign_sql(result_col: str, user_expr: str,
                             white_col: str|None, black_col: str|None) -> str:
    """
    Map authoritative game-level result to the sampled user's win/draw/loss sign.

    Rating-difference sign is deliberately forbidden here because draws can move
    rating positively or negatively.
    """
    v=f"lower(trim(CAST({q(result_col)} AS VARCHAR)))"
    if white_col and black_col:
        w=f"CAST({q(white_col)} AS VARCHAR)"
        b=f"CAST({q(black_col)} AS VARCHAR)"
        return f"""CASE
          WHEN {v} IN ('1/2-1/2','½-½','draw','d') THEN 0
          WHEN {v} IN ('white_win','white','1-0')
               AND CAST({user_expr} AS VARCHAR)={w} THEN 1
          WHEN {v} IN ('white_win','white','1-0')
               AND CAST({user_expr} AS VARCHAR)={b} THEN -1
          WHEN {v} IN ('black_win','black','0-1')
               AND CAST({user_expr} AS VARCHAR)={b} THEN 1
          WHEN {v} IN ('black_win','black','0-1')
               AND CAST({user_expr} AS VARCHAR)={w} THEN -1
          ELSE NULL
        END"""
    # Accept a user-relative result only when it is explicitly coded as such.
    return f"""CASE
      WHEN {v} IN ('win','w','1') THEN 1
      WHEN {v} IN ('draw','d','0.5','1/2-1/2','½-½') THEN 0
      WHEN {v} IN ('loss','lose','l','-1') THEN -1
      ELSE NULL
    END"""

def setup_duckdb(tempdir: Path, threads: int, memory: str):
    import duckdb
    con=duckdb.connect()
    con.execute(f"SET threads={int(threads)}")
    con.execute(f"SET memory_limit={sqls(memory)}")
    tempdir.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory={sqls(str(tempdir))}")
    con.execute("SET preserve_insertion_order=false")
    try:
        con.execute("PRAGMA enable_progress_bar")
    except Exception:
        pass
    return con

def build_mapping(target_cols, target_types, hist_cols, hist_types, s7_cols, s7_types):
    # Sampled-target table: only chooser key + game id are required.
    tk_user=first_col(target_cols,[
        "chooser_user_id","chooser_index","candidate_chooser_index","chooser_user_index",
        "target_user_index","user_index","sampled_user_index","chooser_hash",
        "candidate_chooser","chooser_username_norm"
    ],["chooser","index"])
    tk_game=first_col(target_cols,["game_id","target_game_id","event_game_id"],["game","id"])
    tk_user_sample=first_col(target_cols,[
        "user_sample","is_user_sample","sampled_user"
    ])

    # Whole-user history.
    h_user=first_col(hist_cols,[
        "chooser_user_id","user_index","target_user_index","sampled_user_index","chooser_index",
        "history_user_index","user_hash","user_id_hash64","username_norm","user_id","user_key"
    ],["user","index"])
    h_game=first_col(hist_cols,["game_id","event_game_id"],["game","id"])
    h_time=first_col(hist_cols,[
        "event_utc_ms","game_start_utc_ms","start_utc_ms","utc_ms",
        "game_datetime","event_datetime","utc_datetime","start_ms"
    ])
    h_start=first_col(hist_cols,[
        "game_start_utc_ms","start_utc_ms","first_move_utc_ms","start_ms",
        "game_datetime","event_datetime","event_utc_ms","utc_ms"
    ])
    h_end=first_col(hist_cols,[
        "game_end_utc_ms","end_utc_ms","last_move_utc_ms","last_move_at_ms",
        "end_ms"
    ])
    h_result=first_col(hist_cols,[
        "user_result_sign","result_sign","user_result","result_for_user","user_score",
        "result_code","outcome_code","realized_outcome","result","score"
    ])
    h_color=first_col(hist_cols,["user_color","player_color","color"])
    h_diff=first_col(hist_cols,[
        "user_rating_diff","rating_diff","rating_delta","rating_change","user_delta",
        "user_rating_delta","rating_diff_for_user"
    ],["rating","diff"])
    h_speed=first_col(hist_cols,[
        "speed_code","event_speed_code","speed","inferred_speed","perf","perf_key"
    ],["speed"])

    # Certified Stage07: current opportunity controls/outcome.
    s_game=first_col(s7_cols,["game_id","id"],["game","id"])
    s_kind=first_col(s7_cols,["outcome_kind_draw","kind_draw","is_kind_draw"],["kind","draw"])
    s_eval=first_col(s7_cols,[
        "engine_eval_cp_disconnected","current_eval_cp","eval_cp_disconnected","engine_eval_cp"
    ],["eval","cp"])
    s_pay=first_col(s7_cols,[
        "chooser_draw_payoff_v2","current_draw_payoff","chooser_draw_payoff"
    ],["draw","payoff"])
    s_winprem=first_col(s7_cols,[
        "chooser_win_premium_v2","current_win_premium","chooser_win_premium","win_premium"
    ],["win","premium"])
    s_celo=first_col(s7_cols,[
        "candidate_chooser_elo","current_chooser_elo","chooser_elo","chooser_rating"
    ],["chooser","elo"])
    s_oelo=first_col(s7_cols,[
        "likely_disconnected_elo","current_opponent_elo","opponent_elo",
        "disconnected_elo","opponent_rating"
    ])
    s_crd=first_col(s7_cols,[
        "chooser_pre_rd_v2","chooser_rd_pre","candidate_chooser_rd",
        "current_chooser_rd","chooser_rd"
    ],["chooser","rd"])
    s_ord=first_col(s7_cols,[
        "disconnected_pre_rd_v2","opponent_rd_pre","disconnected_rd_pre",
        "current_opponent_rd","opponent_rd","likely_disconnected_rd",
        "likely_disconnected_rd_pre"
    ])
    s_cclock=first_col(s7_cols,[
        "chooser_clock_last_obs_s","current_chooser_clock_s","chooser_clock_s"
    ],["chooser","clock"])
    s_oclock=first_col(s7_cols,[
        "disconnected_clock_last_obs_s","current_opponent_clock_s","opponent_clock_s"
    ])
    s_speed=first_col(s7_cols,["api_speed","speed","current_speed_code","speed_code"],["speed"])
    s_tourn=first_col(s7_cols,[
        "tournament_like_event","current_tournament_like","tournament_like"
    ],["tournament"])
    s_month=first_col(s7_cols,["archive_month","month","current_month_code"],["month"])
    s_time=first_col(s7_cols,[
        "api_last_move_at_ms","utc_ms","event_utc_ms","last_move_at_ms"
    ])

    mapping={
        "target":{
            "chooser_key":must("sampled-target chooser key",tk_user,target_cols),
            "game_id":must("sampled-target game id",tk_game,target_cols),
            "user_sample":tk_user_sample,
        },
        "history":{
            "user_key":must("history user key",h_user,hist_cols),
            "game_id":must("history game id",h_game,hist_cols),
            "start_time":must("history event/start timestamp",h_start or h_time,hist_cols),
            "end_time":h_end,
            "result":h_result,
            "user_color":h_color,
            "rating_diff":must("history user rating diff",h_diff,hist_cols),
            "speed":must("history speed",h_speed,hist_cols),
        },
        "stage07":{
            "game_id":must("Stage07 game id",s_game,s7_cols),
            "kind_draw":must("Stage07 kind outcome",s_kind,s7_cols),
            "eval_cp":must("Stage07 evaluation",s_eval,s7_cols),
            "draw_payoff":must("Stage07 draw payoff",s_pay,s7_cols),
            "win_premium":must("Stage07 win premium",s_winprem,s7_cols),
            "chooser_elo":must("Stage07 chooser Elo",s_celo,s7_cols),
            "opponent_elo":must("Stage07 opponent Elo",s_oelo,s7_cols),
            "chooser_rd":must("Stage07 chooser RD",s_crd,s7_cols),
            "opponent_rd":must("Stage07 opponent RD",s_ord,s7_cols),
            "chooser_clock":must("Stage07 chooser clock",s_cclock,s7_cols),
            "opponent_clock":must("Stage07 opponent clock",s_oclock,s7_cols),
            "speed":must("Stage07 speed",s_speed,s7_cols),
            "tournament":must("Stage07 tournament flag",s_tourn,s7_cols),
            "month":s_month,
            "time_ms":must("Stage07 timestamp",s_time,s7_cols),
        }
    }
    return mapping


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function."""
    maxit = 200
    eps = 3.0e-14
    fpmin = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c

        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    raise RuntimeError("Incomplete-beta continued fraction did not converge")

def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if not (0.0 <= x <= 1.0):
        raise ValueError("x must be in [0,1]")
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0
    bt = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b

def student_t_two_sided_p(t_value: float, df: int) -> float:
    """Exact two-sided Student-t p-value using only the Python standard library."""
    if not math.isfinite(t_value):
        return math.nan
    if df <= 0:
        raise ValueError("Student-t degrees of freedom must be positive")
    x = float(df) / (float(df) + float(t_value) * float(t_value))
    p = _regularized_incomplete_beta(float(df) / 2.0, 0.5, x)
    return min(1.0, max(0.0, float(p)))

def fit_fe_cluster(df, exposure_cols, extra_cat=None, label="model"):
    import numpy as np
    import pandas as pd

    extra_cat=extra_cat or []
    base_num=[
        "draw_payoff","win_premium","chooser_clock","opponent_clock",
        "chooser_elo","opponent_elo","chooser_rd","opponent_rd","tournament"
    ]
    cats=["eval_bin","speed","month","hour_of_week"] + list(extra_cat)
    needed=["kind","chooser_key"] + list(exposure_cols) + base_num + cats
    d=df[needed].copy().replace([np.inf,-np.inf],np.nan).dropna()
    if len(d)<1000:
        raise RuntimeError(f"{label}: fewer than 1000 complete-case rows")

    y=d["kind"].astype(float).to_numpy()
    groups, uniques=pd.factorize(d["chooser_key"].astype(str), sort=False)
    G=len(uniques)
    if G<100:
        raise RuntimeError(f"{label}: too few chooser clusters ({G})")

    mats=[]
    names=[]
    for c in exposure_cols:
        mats.append(d[c].astype(float).to_numpy()[:,None])
        names.append(c)

    # Standardize continuous current-state controls for numerical stability.
    for c in base_num:
        x=d[c].astype(float).to_numpy()
        sd=float(np.std(x))
        if not np.isfinite(sd) or sd<=0:
            continue
        mats.append(((x-float(np.mean(x)))/sd)[:,None])
        names.append("z_"+c)

    if cats:
        z=pd.get_dummies(d[cats].astype(str), prefix=cats, drop_first=True, dtype=float)
        if z.shape[1]:
            mats.append(z.to_numpy(dtype=float))
            names.extend(list(z.columns))

    X=np.concatenate(mats,axis=1).astype(np.float64,copy=False)
    n=X.shape[0]

    # Exact one-way within transformation.
    counts=np.bincount(groups,minlength=G).astype(float)
    ymeans=np.bincount(groups,weights=y,minlength=G)/counts
    yw=y-ymeans[groups]
    for j in range(X.shape[1]):
        means=np.bincount(groups,weights=X[:,j],minlength=G)/counts
        X[:,j]-=means[groups]

    norms=np.sqrt(np.sum(X*X,axis=0))
    keep=norms>1e-10
    # Never silently lose an exposure.
    for c in exposure_cols:
        j=names.index(c)
        if not keep[j]:
            raise RuntimeError(f"{label}: exposure {c} has no within-chooser variation")
    X=X[:,keep]
    kept_names=[nm for nm,k in zip(names,keep) if k]

    xtx=X.T@X
    xty=X.T@yw
    bread=np.linalg.pinv(xtx,rcond=1e-10)
    beta=bread@xty
    resid=yw-X@beta

    # Chooser-clustered sandwich, accumulated column-wise to limit temporary memory.
    scores=np.zeros((G,X.shape[1]),dtype=np.float64)
    for j in range(X.shape[1]):
        scores[:,j]=np.bincount(groups,weights=X[:,j]*resid,minlength=G)
    meat=scores.T@scores
    cov=bread@meat@bread
    k=X.shape[1]
    if G>1 and n>k:
        cov*= (G/(G-1))*((n-1)/(n-k))
    se=np.sqrt(np.maximum(np.diag(cov),0))
    dof=max(G-1,1)

    out=[]
    for c in exposure_cols:
        j=kept_names.index(c)
        b=float(beta[j]); s=float(se[j])
        tval=b/s if s>0 else math.nan
        p=student_t_two_sided_p(tval,dof) if np.isfinite(tval) else math.nan
        out.append({
            "model":label,
            "term":c,
            "effect_pp":100*b,
            "se_pp":100*s,
            "t_cluster":tval,
            "p_value_two_sided":p,
            "rows":int(n),
            "chooser_clusters":int(G),
            "design_columns_after_absorption":int(k),
        })
    return out, d

def raw_rate(d, mask):
    x=d.loc[mask,"kind"]
    return None if len(x)==0 else float(x.mean())

def session_bin(idx):
    if idx==1: return "1"
    if idx<=3: return "2-3"
    if idx<=6: return "4-6"
    if idx<=10: return "7-10"
    return "11+"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root",type=Path,default=PROJECT)
    ap.add_argument("--threads",type=int,default=8)
    ap.add_argument("--memory-limit",default="12GB")
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()

    if args.self_test:
        import numpy as np, pandas as pd
        rng=np.random.default_rng(1234)
        G=300; per=8; n=G*per
        d=pd.DataFrame({
            "chooser_key":np.repeat(np.arange(G),per),
            "kind":rng.binomial(1,.05,n),
            "loss":rng.binomial(1,.45,n),
            "draw_payoff":rng.normal(size=n),
            "win_premium":rng.normal(size=n),
            "chooser_clock":rng.uniform(1,300,n),
            "opponent_clock":rng.uniform(1,300,n),
            "chooser_elo":rng.normal(1800,250,n),
            "opponent_elo":rng.normal(1800,250,n),
            "chooser_rd":rng.uniform(30,120,n),
            "opponent_rd":rng.uniform(30,120,n),
            "tournament":rng.binomial(1,.1,n),
            "eval_bin":rng.choice(["equal","better"],n),
            "speed":rng.choice(["blitz","rapid"],n),
            "month":rng.choice(["2025-01","2025-02"],n),
            "hour_of_week":rng.integers(0,168,n),
        })
        p_ref=student_t_two_sided_p(2.0,10)
        if abs(p_ref-0.0733880347707404)>1e-12:
            raise RuntimeError(f"dependency-free Student-t self-test failed: {p_ref}")
        r,_=fit_fe_cluster(d,["loss"],label="synthetic")
        if len(r)!=1 or not np.isfinite(r[0]["effect_pp"]) or not np.isfinite(r[0]["p_value_two_sided"]):
            raise RuntimeError("synthetic FE test failed")
        print("DYNAMICS_CAMPAIGN1_WAVE1_SELF_TEST_OK")
        return

    project=args.project_root
    repo=project/"replication_package"
    history_public=project/"output/dynamic_second_wave_history_v100/20260822T150914Z"
    private=project/"derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    hist_root=private/"user_events"
    selected_games_root=private/"selected_games"
    target_path=private/"stage07_sampled_targets_private.parquet"
    hist_receipt=private/"user_events_receipt.json"
    target_receipt=private/"stage07_sampled_targets_receipt.json"
    stage07=project/"derived/replication/analysis_panel_24m_sf100k"

    run_id=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outbase=project/"output/dynamics_campaign1_wave1_c1_c3_v100"
    final=outbase/run_id
    staging=outbase/f".{run_id}.tmp.{os.getpid()}"
    staging.mkdir(parents=True,exist_ok=False)
    tempdir=staging/"duckdb_tmp"
    started=time.time()

    try:
        print("WAVE1_C1_C3_AUTHORITY_PREFLIGHT_BEGIN",flush=True)
        # Git clean / remote synchronized.
        run(["git","fetch","origin","main","--quiet"],cwd=repo)
        head=run(["git","rev-parse","HEAD"],cwd=repo)
        remote=run(["git","rev-parse","origin/main"],cwd=repo)
        if head!=remote: raise RuntimeError("local HEAD != origin/main")
        if run(["git","status","--porcelain"],cwd=repo): raise RuntimeError("dirty Git worktree")

        plan_paths={
            "base":repo/"docs/dynamics_paper2_campaign1_analysis_plan_v1_0_0.md",
            "amd101":repo/"docs/dynamics_paper2_campaign1_analysis_plan_v1_0_1_amendment.md",
            "amd102":repo/"docs/dynamics_paper2_campaign1_analysis_plan_v1_0_2_amendment.md",
            "amd103":repo/"docs/dynamics_paper2_campaign1_analysis_plan_v1_0_3_amendment.md",
        }
        exp={"base":BASE_SHA,"amd101":AMD101_SHA,"amd102":AMD102_SHA,"amd103":AMD103_SHA}
        for k,p in plan_paths.items():
            if not p.is_file() or sha256_file(p)!=exp[k]:
                raise RuntimeError(f"Campaign plan layer missing/SHA mismatch: {k}")

        hs=history_public/"_SUCCESS.json"
        if not hs.is_file() or sha256_file(hs)!=EXPECTED_HISTORY_SUCCESS_SHA:
            raise RuntimeError("second-wave history _SUCCESS SHA mismatch")
        if "DYNAMIC_SECOND_WAVE_HISTORY_V100_OK" not in hs.read_text():
            raise RuntimeError("second-wave history status mismatch")

        hr=json.loads(hist_receipt.read_text())
        tr=json.loads(target_receipt.read_text())
        if hr.get("status")!="DYNAMIC_SECOND_WAVE_USER_EVENTS_OK" or int(hr.get("rows",-1))!=EXPECTED_HISTORY_ROWS:
            raise RuntimeError("user-history receipt mismatch")
        if tr.get("status")!="DYNAMIC_SECOND_WAVE_STAGE07_SAMPLED_TARGETS_OK" or int(tr.get("rows",-1))!=EXPECTED_TARGET_ROWS:
            raise RuntimeError("sampled-target receipt mismatch")

        hist_paths=sorted(hist_root.rglob("*.parquet"))
        if not hist_paths: raise RuntimeError("user-history Parquets missing")
        if total_rows(hist_paths)!=EXPECTED_HISTORY_ROWS:
            raise RuntimeError("user-history Parquet row total mismatch")
        if parquet_schema(target_path)["rows"]!=EXPECTED_TARGET_ROWS:
            raise RuntimeError("sampled-target Parquet row total mismatch")
        s7_paths=sorted(p for p in stage07.rglob("*.parquet") if "_manifests" not in p.parts and not any(x.startswith(".") for x in p.parts))
        month_paths=[p for p in s7_paths if any(x.startswith("month=") for x in p.parts)]
        if month_paths: s7_paths=month_paths
        if not s7_paths or total_rows(s7_paths)!=EXPECTED_STAGE07_ROWS:
            raise RuntimeError("Stage07 Parquet authority mismatch")

        ts=parquet_schema(target_path)
        hsamp=parquet_schema(hist_paths[0])
        s7s=parquet_schema(s7_paths[0])

        # Write/print the schemas before field resolution so a fail-closed mapping error
        # never requires another standalone schema-audit run.
        (staging/"schema_inventory_pre_mapping.json").write_text(json.dumps({
            "target":ts,
            "history_sample":hsamp,
            "stage07_sample":s7s,
        },indent=2,sort_keys=True)+"\n")
        print("SAMPLED_TARGET_SCHEMA:",",".join(ts["columns"]),flush=True)
        print("USER_HISTORY_SCHEMA:",",".join(hsamp["columns"]),flush=True)
        print("STAGE07_SCHEMA:",",".join(s7s["columns"]),flush=True)

        mapping=build_mapping(
            ts["columns"],ts["types"],
            hsamp["columns"],hsamp["types"],
            s7s["columns"],s7s["types"]
        )
        print("WAVE1_FIELD_MAPPING:",json.dumps(mapping,sort_keys=True),flush=True)
        (staging/"schema_and_mapping.json").write_text(json.dumps({
            "target":ts,"history_sample":hsamp,"stage07_sample":s7s,"mapping":mapping
        },indent=2,sort_keys=True)+"\n")

        # Choose exact end-to-start if available; otherwise v1.0.3 start-to-start.
        hmap=mapping["history"]
        if hmap["end_time"]:
            session_mode="explicit_end_to_start"
        else:
            session_mode="start_to_start_v1_0_3_fallback"
        print("SESSION_TIMESTAMP_MODE:",session_mode,flush=True)

        con=setup_duckdb(tempdir,args.threads,args.memory_limit)
        hist_sql="["+",".join(sqls(str(p)) for p in hist_paths)+"]"
        s7_sql="["+",".join(sqls(str(p)) for p in s7_paths)+"]"

        # Time expressions.
        h_start_expr=time_expr(hmap["start_time"],hsamp["types"][hmap["start_time"]])
        if hmap["end_time"]:
            h_end_expr=time_expr(hmap["end_time"],hsamp["types"][hmap["end_time"]])
        else:
            h_end_expr=h_start_expr

        # Basic timestamp scale/ordering QA before any Campaign outcome is read.
        qa=con.execute(f"""
        SELECT min({h_start_expr}), max({h_start_expr}),
               sum(CASE WHEN {h_start_expr} IS NULL THEN 1 ELSE 0 END)
        FROM read_parquet({hist_sql}, union_by_name=true)
        """).fetchone()
        if qa[0] is None or qa[1] is None or int(qa[1])<1_000_000_000_000:
            raise RuntimeError(f"history timestamp does not appear to be epoch milliseconds: {qa}")

        # Normalize sampled target keys.
        #
        # The certified sampled-target file carries both user_sample and pair_sample.
        # C1-C3 use the whole-user history layer, so pair-only targets must not be
        # treated as missing user-history matches.
        tmap=mapping["target"]
        user_sample_filter = (
            f"AND coalesce(CAST({q(tmap['user_sample'])} AS BOOLEAN), FALSE)"
            if tmap["user_sample"] else ""
        )
        source_count=con.execute(f"""
        SELECT count(*)
        FROM read_parquet({sqls(str(target_path))})
        WHERE {q(tmap["chooser_key"])} IS NOT NULL
          AND {q(tmap["game_id"])} IS NOT NULL
          {user_sample_filter}
        """).fetchone()[0]
        con.execute(f"""
        CREATE TEMP TABLE sample_keys AS
        SELECT DISTINCT
          CAST({q(tmap["chooser_key"])} AS VARCHAR) AS chooser_key,
          CAST({q(tmap["game_id"])} AS VARCHAR) AS game_id
        FROM read_parquet({sqls(str(target_path))})
        WHERE {q(tmap["chooser_key"])} IS NOT NULL
          AND {q(tmap["game_id"])} IS NOT NULL
          {user_sample_filter}
        """)
        key_count=con.execute("SELECT count(*) FROM sample_keys").fetchone()[0]
        if source_count <= 0 or key_count <= 0:
            raise RuntimeError("no usable whole-user sampled Stage07 targets")
        if key_count/source_count < 0.999:
            raise RuntimeError(
                f"unexpected duplicate chooser-game keys in user-sampled targets: "
                f"rows={source_count}, distinct={key_count}"
            )
        print(
            f"WAVE1_USER_SAMPLED_TARGET_KEYS_OK rows={source_count} distinct={key_count} "
            f"user_sample_filter={'YES' if tmap['user_sample'] else 'UNAVAILABLE'}",
            flush=True,
        )

        # Build session features using the full 309.96M whole-user history, but emit
        # only sampled Stage07 target games. No outcome from Stage07 is referenced here.
        print("WAVE1_SESSION_FEATURE_BUILD_BEGIN",flush=True)
        gap_base = "start_ms - prev_end_ms" if session_mode=="explicit_end_to_start" else "start_ms - prev_start_ms"
        con.execute(f"""
        CREATE TEMP TABLE target_session_features AS
        WITH base AS (
          SELECT
            CAST({q(hmap["user_key"])} AS VARCHAR) AS chooser_key,
            CAST({q(hmap["game_id"])} AS VARCHAR) AS game_id,
            CAST({h_start_expr} AS BIGINT) AS start_ms,
            CAST({h_end_expr} AS BIGINT) AS end_ms,
            CAST({q(hmap["speed"])} AS VARCHAR) AS hist_speed,
            CAST({q(hmap["rating_diff"])} AS DOUBLE) AS rating_diff
          FROM read_parquet({hist_sql}, union_by_name=true)
          WHERE {q(hmap["user_key"])} IS NOT NULL
            AND {q(hmap["game_id"])} IS NOT NULL
            AND {q(hmap["start_time"])} IS NOT NULL
        ),
        lagged AS (
          SELECT *,
            lag(start_ms) OVER w AS prev_start_ms,
            lag(end_ms) OVER w AS prev_end_ms,
            lag(game_id,1) OVER w AS prev_game_id_1,
            lag(game_id,2) OVER w AS prev_game_id_2,
            lag(game_id,3) OVER w AS prev_game_id_3,
            lag(hist_speed,1) OVER w AS prev_speed
          FROM base
          WINDOW w AS (
            PARTITION BY chooser_key
            ORDER BY start_ms, game_id
          )
        ),
        session_ids AS (
          SELECT *,
            sum(CASE WHEN prev_start_ms IS NULL OR ({gap_base}) >= 15*60*1000 THEN 1 ELSE 0 END)
              OVER w AS session15,
            sum(CASE WHEN prev_start_ms IS NULL OR ({gap_base}) >= 30*60*1000 THEN 1 ELSE 0 END)
              OVER w AS session30,
            sum(CASE WHEN prev_start_ms IS NULL OR ({gap_base}) >= 60*60*1000 THEN 1 ELSE 0 END)
              OVER w AS session60
          FROM lagged
          WINDOW w AS (
            PARTITION BY chooser_key
            ORDER BY start_ms, game_id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
          )
        ),
        feats AS (
          SELECT *,
            row_number() OVER (PARTITION BY chooser_key,session15 ORDER BY start_ms,game_id) AS idx15,
            row_number() OVER (PARTITION BY chooser_key,session30 ORDER BY start_ms,game_id) AS idx30,
            row_number() OVER (PARTITION BY chooser_key,session60 ORDER BY start_ms,game_id) AS idx60,
            min(start_ms) OVER (PARTITION BY chooser_key,session30) AS session30_start_ms,
            sum(coalesce(rating_diff,0.0)) OVER (
              PARTITION BY chooser_key,session15 ORDER BY start_ms,game_id
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS pnl15,
            sum(coalesce(rating_diff,0.0)) OVER (
              PARTITION BY chooser_key,session30 ORDER BY start_ms,game_id
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS pnl30,
            sum(coalesce(rating_diff,0.0)) OVER (
              PARTITION BY chooser_key,session60 ORDER BY start_ms,game_id
              ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
            ) AS pnl60
          FROM session_ids
        )
        SELECT
          f.chooser_key,f.game_id,f.start_ms,f.hist_speed,f.prev_speed,
          f.prev_game_id_1,f.prev_game_id_2,f.prev_game_id_3,
          f.idx15,f.idx30,f.idx60,
          f.pnl15,f.pnl30,f.pnl60,
          (f.start_ms-f.session30_start_ms)/3600000.0 AS elapsed30_hours
        FROM feats f
        INNER JOIN sample_keys s USING(chooser_key,game_id)
        """)
        matched=con.execute("SELECT count(*) FROM target_session_features").fetchone()[0]
        if matched < 0.90*key_count:
            raise RuntimeError(f"session-history target match rate too low: {matched}/{key_count}")
        print(f"WAVE1_SESSION_FEATURE_BUILD_OK matched={matched}",flush=True)

        # Normalize current Stage07 opportunity rows only now.
        sm=mapping["stage07"]
        s7_time_expr=time_expr(sm["time_ms"],s7s["types"][sm["time_ms"]])
        month_expr=(f"CAST({q(sm['month'])} AS VARCHAR)" if sm["month"]
                    else f"strftime(to_timestamp(({s7_time_expr})/1000.0),'%Y-%m')")
        con.execute(f"""
        CREATE TEMP TABLE current_targets AS
        SELECT
          k.chooser_key,
          CAST(s.{q(sm["game_id"])} AS VARCHAR) AS game_id,
          CAST(s.{q(sm["kind_draw"])} AS DOUBLE) AS kind,
          CAST(s.{q(sm["eval_cp"])} AS DOUBLE) AS eval_cp,
          CAST(s.{q(sm["draw_payoff"])} AS DOUBLE) AS draw_payoff,
          CAST(s.{q(sm["win_premium"])} AS DOUBLE) AS win_premium,
          CAST(s.{q(sm["chooser_elo"])} AS DOUBLE) AS chooser_elo,
          CAST(s.{q(sm["opponent_elo"])} AS DOUBLE) AS opponent_elo,
          CAST(s.{q(sm["chooser_rd"])} AS DOUBLE) AS chooser_rd,
          CAST(s.{q(sm["opponent_rd"])} AS DOUBLE) AS opponent_rd,
          CAST(s.{q(sm["chooser_clock"])} AS DOUBLE) AS chooser_clock,
          CAST(s.{q(sm["opponent_clock"])} AS DOUBLE) AS opponent_clock,
          CAST(s.{q(sm["speed"])} AS VARCHAR) AS speed,
          CAST(s.{q(sm["tournament"])} AS DOUBLE) AS tournament,
          {month_expr} AS event_month,
          CAST({s7_time_expr} AS BIGINT) AS current_utc_ms
        FROM read_parquet({s7_sql}, union_by_name=true) s
        INNER JOIN sample_keys k
          ON CAST(s.{q(sm["game_id"])} AS VARCHAR)=k.game_id
        """)
        cur_n=con.execute("SELECT count(*) FROM current_targets").fetchone()[0]
        if cur_n != key_count:
            raise RuntimeError(f"Stage07 sampled target join is not 1:1: current={cur_n}, keys={key_count}")

        # Support counts are frozen before tabulating outcome by exposure.
        support=con.execute("""
        SELECT
          count(*) FILTER (WHERE eval_cp>=-100) AS fair_rows,
          count(*) FILTER (WHERE eval_cp>=-100 AND f.idx30>=2) AS fair_prior_same_session_30,
          count(*) FILTER (WHERE eval_cp>=-100 AND f.idx15>=2) AS fair_prior_same_session_15,
          count(*) FILTER (WHERE eval_cp>=-100 AND f.idx60>=2) AS fair_prior_same_session_60,
          count(DISTINCT c.chooser_key) FILTER (WHERE eval_cp>=-100) AS fair_choosers
        FROM current_targets c
        LEFT JOIN target_session_features f USING(chooser_key,game_id)
        """).fetchone()
        support_obj={
            "status":"C1_C3_SESSION_SUPPORT_FROZEN_BEFORE_EXPOSURE_OUTCOME_TABULATION",
            "session_timestamp_mode":session_mode,
            "fair_rows":int(support[0]),
            "fair_with_prior_same_session_30":int(support[1]),
            "share_30":float(support[1]/support[0]) if support[0] else None,
            "fair_with_prior_same_session_15":int(support[2]),
            "share_15":float(support[2]/support[0]) if support[0] else None,
            "fair_with_prior_same_session_60":int(support[3]),
            "share_60":float(support[3]/support[0]) if support[0] else None,
            "fair_choosers":int(support[4]),
            "kindness_by_history_exposure_tabulated_at_gate":False,
        }
        (staging/"session_support_frozen.json").write_text(json.dumps(support_obj,indent=2,sort_keys=True)+"\n")
        print("WAVE1_SESSION_SUPPORT_FROZEN_OK",flush=True)

        # C1 authoritative prior-result bridge. The certified user_events layer
        # contains rating trajectories but intentionally no result field. Do not
        # substitute rating_diff sign. Bridge only the preceding game IDs needed
        # for C1 to the selected-game/header layer.
        c1_bridge={
            "status":"PENDING",
            "selected_games_root":str(selected_games_root),
            "rating_diff_used_to_infer_result":False,
        }
        c1_available=False
        selected_paths=sorted(selected_games_root.rglob("*.parquet")) if selected_games_root.exists() else []

        if selected_paths:
            sg_schema=parquet_schema(selected_paths[0])
            sg_map=resolve_selected_game_result_schema(sg_schema["columns"])
            (staging/"c1_selected_games_schema.json").write_text(json.dumps({
                "sample_schema":sg_schema,
                "mapping":sg_map,
                "parquet_files":len(selected_paths),
            },indent=2,sort_keys=True)+"\n")
            print("C1_SELECTED_GAMES_SCHEMA:",",".join(sg_schema["columns"]),flush=True)
            print("C1_SELECTED_GAMES_MAPPING:",json.dumps(sg_map,sort_keys=True),flush=True)

            if sg_map["game_id"] and sg_map["result"]:
                sg_sql="["+",".join(sqls(str(p)) for p in selected_paths)+"]"
                con.execute("""
                CREATE TEMP TABLE c1_needed_games AS
                SELECT DISTINCT chooser_key, prev_game_id_1 AS game_id
                FROM target_session_features WHERE prev_game_id_1 IS NOT NULL
                UNION
                SELECT DISTINCT chooser_key, prev_game_id_2 AS game_id
                FROM target_session_features WHERE prev_game_id_2 IS NOT NULL
                UNION
                SELECT DISTINCT chooser_key, prev_game_id_3 AS game_id
                FROM target_session_features WHERE prev_game_id_3 IS NOT NULL
                """)
                result_sign=selected_result_sign_sql(
                    sg_map["result"], "n.chooser_key", sg_map["white_id"], sg_map["black_id"]
                )
                con.execute(f"""
                CREATE TEMP TABLE c1_game_results AS
                SELECT
                  n.chooser_key,
                  n.game_id,
                  {result_sign} AS result_sign
                FROM c1_needed_games n
                INNER JOIN read_parquet({sg_sql}, union_by_name=true) g
                  ON CAST(g.{q(sg_map["game_id"])} AS VARCHAR)=n.game_id
                """)
                dup=con.execute("""
                SELECT count(*) FROM (
                  SELECT chooser_key,game_id,count(*) n
                  FROM c1_game_results GROUP BY 1,2 HAVING count(*)>1
                )
                """).fetchone()[0]
                if dup:
                    raise RuntimeError(f"C1 selected-game result lookup is not unique: {dup}")

                con.execute("""
                CREATE TEMP TABLE target_session_results AS
                SELECT
                  f.*,
                  r1.result_sign AS prev_result_sign_1,
                  r2.result_sign AS prev_result_sign_2,
                  r3.result_sign AS prev_result_sign_3
                FROM target_session_features f
                LEFT JOIN c1_game_results r1
                  ON r1.chooser_key=f.chooser_key AND r1.game_id=f.prev_game_id_1
                LEFT JOIN c1_game_results r2
                  ON r2.chooser_key=f.chooser_key AND r2.game_id=f.prev_game_id_2
                LEFT JOIN c1_game_results r3
                  ON r3.chooser_key=f.chooser_key AND r3.game_id=f.prev_game_id_3
                """)
                br=con.execute("""
                SELECT
                  count(*) FILTER (WHERE idx30>=2) AS eligible30,
                  count(*) FILTER (
                    WHERE idx30>=2 AND prev_result_sign_1 IS NOT NULL
                  ) AS resolved30,
                  count(*) FILTER (
                    WHERE idx30>=4
                      AND prev_result_sign_1 IS NOT NULL
                      AND prev_result_sign_2 IS NOT NULL
                      AND prev_result_sign_3 IS NOT NULL
                  ) AS resolved_streak30
                FROM target_session_results
                """).fetchone()
                share=float(br[1]/br[0]) if br[0] else 0.0
                c1_bridge.update({
                    "status":"RESOLVED" if share>=0.95 else "INSUFFICIENT_RESULT_MATCH",
                    "eligible_prior_same_session_30":int(br[0]),
                    "resolved_prior_result_30":int(br[1]),
                    "resolved_share_30":share,
                    "resolved_three_prior_results_30":int(br[2]),
                    "selected_games_parquet_files":len(selected_paths),
                })
                c1_available=share>=0.95
            else:
                c1_bridge.update({
                    "status":"BLOCKED_SELECTED_GAMES_RESULT_SCHEMA_UNRESOLVED",
                    "selected_game_mapping":sg_map,
                })
        else:
            c1_bridge["status"]="BLOCKED_SELECTED_GAMES_LAYER_MISSING"

        (staging/"c1_prior_result_bridge.json").write_text(
            json.dumps(c1_bridge,indent=2,sort_keys=True)+"\n"
        )
        print("C1_PRIOR_RESULT_BRIDGE_STATUS:",c1_bridge["status"],flush=True)

        # Actual Campaign1 outcomes now. C2/C3 do not depend on the C1 result bridge.
        print("CAMPAIGN1_WAVE1_OUTCOME_ANALYSIS_BEGIN",flush=True)
        df=con.execute("""
        SELECT
          c.*, f.hist_speed,f.prev_speed,
          f.idx15,f.idx30,f.idx60,f.pnl15,f.pnl30,f.pnl60,f.elapsed30_hours
        FROM current_targets c
        LEFT JOIN target_session_features f USING(chooser_key,game_id)
        WHERE c.eval_cp>=-100
        """).fetchdf()

        import numpy as np
        import pandas as pd
        df["kind"]=pd.to_numeric(df["kind"],errors="coerce")
        # Fair-state evaluation bins used in the frozen current-state vector.
        df["eval_bin"]=pd.cut(
            df["eval_cp"],
            bins=[-np.inf,100,299,np.inf],
            labels=["roughly_equal","disconnected_better","disconnected_clearly_better"]
        ).astype(str)
        ts=pd.to_datetime(df["current_utc_ms"],unit="ms",utc=True,errors="coerce")
        df["hour_of_week"]=(ts.dt.dayofweek*24+ts.dt.hour).astype("Int64").astype(str)
        df["month"]=df["event_month"].astype(str)

        # C1 primary and timestamp sensitivities. Estimate only if the
        # authoritative selected-game bridge resolves at least 95% of primary rows.
        c1_rows=[]
        c1_streak_rows=[]
        if c1_available:
            c1df=con.execute("""
            SELECT
              c.*, r.hist_speed,r.prev_speed,
              r.prev_result_sign_1,r.prev_result_sign_2,r.prev_result_sign_3,
              r.idx15,r.idx30,r.idx60,r.pnl15,r.pnl30,r.pnl60,r.elapsed30_hours
            FROM current_targets c
            LEFT JOIN target_session_results r USING(chooser_key,game_id)
            WHERE c.eval_cp>=-100
            """).fetchdf()
            c1df["kind"]=pd.to_numeric(c1df["kind"],errors="coerce")
            c1df["eval_bin"]=pd.cut(
                c1df["eval_cp"],
                bins=[-np.inf,100,299,np.inf],
                labels=["roughly_equal","disconnected_better","disconnected_clearly_better"]
            ).astype(str)
            c1ts=pd.to_datetime(c1df["current_utc_ms"],unit="ms",utc=True,errors="coerce")
            c1df["hour_of_week"]=(c1ts.dt.dayofweek*24+c1ts.dt.hour).astype("Int64").astype(str)
            c1df["month"]=c1df["event_month"].astype(str)

            for mins,idxc in [(30,"idx30"),(15,"idx15"),(60,"idx60")]:
                s=c1df[(c1df[idxc]>=2)&c1df["prev_result_sign_1"].isin([-1,0,1])].copy()
                s["prev_loss"]=(s["prev_result_sign_1"]==-1).astype(float)
                s["prev_draw"]=(s["prev_result_sign_1"]==0).astype(float)
                result,used=fit_fe_cluster(
                    s,["prev_loss","prev_draw"],label=f"C1_{mins}min"
                )
                primary=[r for r in result if r["term"]=="prev_loss"][0]
                loss_rate=raw_rate(used,used["prev_loss"]==1)
                win_rate=raw_rate(
                    used,(used["prev_loss"]==0)&(used["prev_draw"]==0)
                )
                primary.update({
                    "epistemic_label":"C",
                    "contrast":"loss_preceded_minus_win_preceded",
                    "session_minutes":mins,
                    "raw_loss_rate_pct":100*loss_rate if loss_rate is not None else None,
                    "raw_win_rate_pct":100*win_rate if win_rate is not None else None,
                    "effect_relative_to_raw_win_mean_pct":
                        (primary["effect_pp"]/(100*win_rate)*100) if win_rate else None,
                    "holm_adjusted_p_value":"PENDING_FULL_FIVE_MEMBER_FAMILY",
                })
                c1_rows.append(primary)

            # Frozen same-pool sensitivity.
            s=c1df[
                (c1df["idx30"]>=2)&
                c1df["prev_result_sign_1"].isin([-1,0,1])&
                (c1df["prev_speed"].astype(str)==c1df["speed"].astype(str))
            ].copy()
            s["prev_loss"]=(s["prev_result_sign_1"]==-1).astype(float)
            s["prev_draw"]=(s["prev_result_sign_1"]==0).astype(float)
            r,used=fit_fe_cluster(
                s,["prev_loss","prev_draw"],label="C1_30min_same_pool"
            )
            rr=[x for x in r if x["term"]=="prev_loss"][0]
            loss_rate=raw_rate(used,used["prev_loss"]==1)
            win_rate=raw_rate(
                used,(used["prev_loss"]==0)&(used["prev_draw"]==0)
            )
            rr.update({
                "epistemic_label":"C_sensitivity",
                "contrast":"loss_preceded_minus_win_preceded",
                "session_minutes":30,
                "raw_loss_rate_pct":100*loss_rate if loss_rate is not None else None,
                "raw_win_rate_pct":100*win_rate if win_rate is not None else None,
                "holm_adjusted_p_value":"NOT_A_FAMILY_MEMBER_SENSITIVITY",
            })
            c1_rows.append(rr)

            # Prespecified secondary: three immediately consecutive losses / wins.
            st=c1df[
                (c1df["idx30"]>=4)&
                c1df["prev_result_sign_1"].isin([-1,0,1])&
                c1df["prev_result_sign_2"].isin([-1,0,1])&
                c1df["prev_result_sign_3"].isin([-1,0,1])
            ].copy()
            st["loss_streak3"]=(
                (st["prev_result_sign_1"]==-1)&
                (st["prev_result_sign_2"]==-1)&
                (st["prev_result_sign_3"]==-1)
            ).astype(float)
            st["win_streak3"]=(
                (st["prev_result_sign_1"]==1)&
                (st["prev_result_sign_2"]==1)&
                (st["prev_result_sign_3"]==1)
            ).astype(float)
            sr,_=fit_fe_cluster(
                st,["loss_streak3","win_streak3"],
                label="C1_secondary_streak3"
            )
            for row in sr:
                row["epistemic_label"]="S"
                row["reference"]="all_other_resolved_three-game_histories"
            c1_streak_rows=sr

            write_csv(staging/"c1_prior_result_state_dependence.csv",c1_rows)
            write_csv(staging/"c1_secondary_streak3.csv",c1_streak_rows)
        else:
            (staging/"c1_prior_result_state_dependence_STATUS.json").write_text(
                json.dumps({
                    "status":"C1_NOT_ESTIMATED_RESULT_BRIDGE_UNRESOLVED",
                    "bridge":c1_bridge,
                    "rating_diff_substitution_used":False,
                    "holm_family_member_status":"PENDING_NOT_TESTED",
                },indent=2,sort_keys=True)+"\n"
            )

        # C2 primary, 15/60 sensitivities.
        c2_rows=[]
        for mins,idxc,pnlc in [(30,"idx30","pnl30"),(15,"idx15","pnl15"),(60,"idx60","pnl60")]:
            s=df[(df[idxc]>=2)&df[pnlc].notna()].copy()
            s["ahead"]=(s[pnlc]>0).astype(float)
            s["even"]=(s[pnlc]==0).astype(float)
            s["session_position_bin"]=s[idxc].astype(int).map(session_bin)
            result,used=fit_fe_cluster(
                s,["ahead","even"],extra_cat=["session_position_bin"],label=f"C2_{mins}min"
            )
            primary=[r for r in result if r["term"]=="ahead"][0]
            primary.update({
                "epistemic_label":"C",
                "contrast":"ahead_minus_behind",
                "session_minutes":mins,
                "raw_ahead_rate_pct":100*raw_rate(used,used["ahead"]==1),
                "raw_behind_rate_pct":100*raw_rate(used,(used["ahead"]==0)&(used["even"]==0)),
                "holm_adjusted_p_value":"PENDING_FULL_FIVE_MEMBER_FAMILY",
            })
            c2_rows.append(primary)
        # Frozen secondary continuous P&L, winsorized at +/-50, primary 30m session.
        s=df[(df["idx30"]>=2)&df["pnl30"].notna()].copy()
        s["pnl_w50"]=s["pnl30"].clip(-50,50).astype(float)
        s["session_position_bin"]=s["idx30"].astype(int).map(session_bin)
        result,used=fit_fe_cluster(
            s,["pnl_w50"],extra_cat=["session_position_bin"],label="C2_30min_continuous_pnl_w50"
        )
        sec=result[0]
        sec.update({
            "epistemic_label":"S",
            "contrast":"effect_per_rating_point_session_pnl_winsorized_50",
            "session_minutes":30,
            "holm_adjusted_p_value":"NOT_A_FAMILY_MEMBER_SECONDARY",
        })
        c2_rows.append(sec)
        write_csv(staging/"c2_session_pnl_state_dependence.csv",c2_rows)

        # C3 exploratory session-position profile and elapsed-time slope.
        c3=df[df["idx30"].notna()].copy()
        c3["session_position_bin"]=c3["idx30"].astype(int).map(session_bin)
        raw=[]
        for b in ["1","2-3","4-6","7-10","11+"]:
            z=c3[c3["session_position_bin"]==b]
            raw.append({
                "session_position_bin":b,
                "rows":int(len(z)),
                "choosers":int(z["chooser_key"].nunique()),
                "kind_draws":float(z["kind"].sum()),
                "kind_rate_pct":100*float(z["kind"].mean()) if len(z) else None,
            })
        write_csv(staging/"c3_session_position_raw.csv",raw)

        c3["idx_2_3"]=(c3["session_position_bin"]=="2-3").astype(float)
        c3["idx_4_6"]=(c3["session_position_bin"]=="4-6").astype(float)
        c3["idx_7_10"]=(c3["session_position_bin"]=="7-10").astype(float)
        c3["idx_11p"]=(c3["session_position_bin"]=="11+").astype(float)
        c3_adj,_=fit_fe_cluster(
            c3,["idx_2_3","idx_4_6","idx_7_10","idx_11p"],label="C3_position_vs_game1"
        )
        for r in c3_adj:
            r["epistemic_label"]="X"
            r["reference"]="session_game_1"
        write_csv(staging/"c3_session_position_adjusted.csv",c3_adj)

        c3e=c3[c3["elapsed30_hours"].notna()].copy()
        c3e["elapsed_hours"]=c3e["elapsed30_hours"].astype(float)
        elapsed,_=fit_fe_cluster(c3e,["elapsed_hours"],label="C3_elapsed_hours")
        elapsed[0]["epistemic_label"]="X"
        elapsed[0]["interpretation_caveat"]="conditions_on_session_continuation"
        write_csv(staging/"c3_session_elapsed_adjusted.csv",elapsed)

        # Final aggregate summary.
        summary={
            "status":"DYNAMICS_CAMPAIGN1_WAVE1_C1_C3_V100_OK",
            "created_utc":now(),
            "git_head":head,
            "session_timestamp_mode":session_mode,
            "authorities":{
                "history_success_sha256":sha256_file(hs),
                "user_events_receipt_sha256":sha256_file(hist_receipt),
                "sampled_targets_receipt_sha256":sha256_file(target_receipt),
                "stage07_rows":EXPECTED_STAGE07_ROWS,
                "user_history_rows":EXPECTED_HISTORY_ROWS,
                "sampled_target_rows":EXPECTED_TARGET_ROWS,
                "user_history_parquet_files":len(hist_paths),
            },
            "support":support_obj,
            "modules":{
                "C1":{
                    "status":"ESTIMATED" if c1_available else "PENDING_RESULT_BRIDGE",
                    "label":"C",
                    "bridge":c1_bridge,
                    "primary_file":"c1_prior_result_state_dependence.csv" if c1_available else None,
                },
                "C2":{"status":"ESTIMATED","label":"C","primary_file":"c2_session_pnl_state_dependence.csv"},
                "C3":{"status":"ESTIMATED","label":"X","files":[
                    "c3_session_position_raw.csv","c3_session_position_adjusted.csv",
                    "c3_session_elapsed_adjusted.csv"]},
            },
            "holm_family_note":(
                "C1 and C2 raw p-values are reported; Holm adjustment awaits C5,C6,C9."
                if c1_available else
                "C2 raw p-value is reported. C1 remains untested because no rating-diff proxy is allowed; Holm adjustment awaits C1,C5,C6,C9."
            ),
            "causal_claim":False,
            "account_level_output":False,
            "patron_status_read":False,
            "api_requests":0,
            "runtime_seconds":time.time()-started,
        }
        (staging/"summary.json").write_text(json.dumps(summary,indent=2,sort_keys=True)+"\n")

        hashes=[]
        for p in sorted(staging.iterdir()):
            if p.is_file() and p.name not in {"_SUCCESS.json","report_file_hashes.csv"}:
                hashes.append({"sha256":sha256_file(p),"bytes":p.stat().st_size,"file":p.name})
        write_csv(staging/"report_file_hashes.csv",hashes)
        success={
            "status":"DYNAMICS_CAMPAIGN1_WAVE1_C1_C3_V100_OK",
            "created_utc":summary["created_utc"],
            "git_head":head,
            "summary_sha256":sha256_file(staging/"summary.json"),
            "report_file_hashes_sha256":sha256_file(staging/"report_file_hashes.csv"),
            "c1_estimated":bool(c1_available),
            "c2_estimated":True,
            "c3_estimated":True,
            "holm_family_adjustment_complete":False,
            "account_level_output":False,
        }
        (staging/"_SUCCESS.json").write_text(json.dumps(success,indent=2,sort_keys=True)+"\n")
        if tempdir.exists(): shutil.rmtree(tempdir,ignore_errors=True)
        os.replace(staging,final)
        print(f"DYNAMICS_CAMPAIGN1_WAVE1_C1_C3_V100_OK: {final}",flush=True)
        print(f"runtime_seconds: {time.time()-started:.1f}",flush=True)

    except Exception as exc:
        # Preserve only schema/provenance diagnostics; no account rows.
        diag={
            "status":"DYNAMICS_CAMPAIGN1_WAVE1_C1_C3_FAIL_CLOSED",
            "created_utc":now(),
            "error":f"{type(exc).__name__}: {exc}",
            "account_level_output":False,
        }
        try:
            (staging/"FAILURE_DIAGNOSTIC.json").write_text(json.dumps(diag,indent=2)+"\n")
            fail=outbase/f"{run_id}_FAILED"
            if fail.exists(): shutil.rmtree(fail)
            if tempdir.exists(): shutil.rmtree(tempdir,ignore_errors=True)
            os.replace(staging,fail)
            print(f"Failure diagnostic: {fail/'FAILURE_DIAGNOSTIC.json'}",file=sys.stderr)
            if (fail/"schema_inventory_pre_mapping.json").exists():
                print(f"Pre-mapping schema diagnostic: {fail/'schema_inventory_pre_mapping.json'}",file=sys.stderr)
            if (fail/"schema_and_mapping.json").exists():
                print(f"Schema diagnostic: {fail/'schema_and_mapping.json'}",file=sys.stderr)
        except Exception:
            pass
        raise

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        print(f"DYNAMICS_CAMPAIGN1_WAVE1_C1_C3_FAIL_CLOSED: {type(e).__name__}: {e}",file=sys.stderr,flush=True)
        raise
