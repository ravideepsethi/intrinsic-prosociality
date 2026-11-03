#!/usr/bin/env python3
"""Test F: out-of-period persistence by board-state of granted draws.

No Lichess API, Stockfish, Glicko replay or new downloads. Builds purely from the
certified pool/nonadjacent 24-month analysis sample. Input checks fail closed.
Account-level artifacts are PRIVATE; zipped report contains aggregates only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback

import numpy as np
import pandas as pd
from run_bc import ALIASES, candidate_paths, connect, ident, input_sql, lit, announce

PAPER = {
    "rows": 41_534_331,
    "grants": 570_091,
    "comp_n": 15_207_423,
    "comp_y": 419_463,
    "lost_n": 22_664_818,
    "lost_y": 106_556,
}
STATES = ("C", "L", "M")
GROUPS = ("NEI", "CO", "LO", "BOTH")


def save_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.9g")


def choose_columns(cn, source_sql: str):
    allcols = {r[0].lower(): r[0] for r in cn.execute(
        "DESCRIBE SELECT * FROM " + source_sql + " LIMIT 0").fetchall()}
    need = ("chooser", "grant", "v", "ply", "speed", "month", "rating_chooser", "rating_opponent")
    actual = {}
    for key in need:
        found = next((allcols[x.lower()] for x in ALIASES[key] if x.lower() in allcols), None)
        if not found:
            raise ValueError(f"Missing required F input field '{key}'. Available fields: {sorted(allcols)}")
        actual[key] = found
    parts = []
    for key, typ in (("chooser", "VARCHAR"), ("grant", "INTEGER"), ("v", "DOUBLE"),
                     ("ply", "INTEGER"), ("speed", "VARCHAR"), ("month", "VARCHAR"),
                     ("rating_chooser", "DOUBLE"), ("rating_opponent", "DOUBLE")):
        val = f"TRY_CAST({ident(actual[key])} AS {typ})"
        if key == "speed":
            val = "LOWER(" + val + ")"
        elif key == "month":
            val = "SUBSTR(" + val + ", 1, 7)"
        parts.append(f"{val} AS {ident(key)}")
    cn.execute("CREATE OR REPLACE TEMP VIEW f_norm AS SELECT " + ", ".join(parts) + " FROM " + source_sql)
    return actual


def preflight(cn):
    row = cn.execute("""
        SELECT COUNT(*) n, SUM(grant) ny,
               COUNT(*) FILTER (WHERE v >= -100) nc,
               SUM(grant) FILTER (WHERE v >= -100) yc,
               COUNT(*) FILTER (WHERE v <= -300) nl,
               SUM(grant) FILTER (WHERE v <= -300) yl,
               MIN(month), MAX(month),
               COUNT(*) FILTER (WHERE chooser IS NULL OR grant IS NULL OR grant NOT IN (0,1)
                        OR v IS NULL OR NOT isfinite(v) OR ply IS NULL OR month IS NULL
                        OR rating_chooser IS NULL OR rating_opponent IS NULL OR speed IS NULL
                        OR NOT isfinite(rating_chooser) OR NOT isfinite(rating_opponent)),
               COUNT(*) FILTER (WHERE speed NOT IN ('ultrabullet','bullet','blitz','rapid','classical'))
        FROM f_norm
    """).fetchone()
    fieldnames = ("rows", "grants", "comp_n", "comp_y", "lost_n", "lost_y",
                  "first_month", "last_month", "invalid", "bad_speed")
    result = dict(zip(fieldnames, row))
    wrong = [k for k in PAPER if result[k] != PAPER[k]]
    if wrong:
        raise ValueError("FAIL-CLOSED: not the paper's pool/nonadjacent sample: "
                         + ", ".join(f"{k}: actual={result[k]}, expected={PAPER[k]}" for k in wrong))
    if result["first_month"] != "2023-11" or result["last_month"] != "2025-10":
        raise ValueError("FAIL-CLOSED: incorrect panel dates: " + str(result))
    if result["invalid"] or result["bad_speed"]:
        raise ValueError("FAIL-CLOSED: input missingness or bad speed: " + str(result))
    return result


def build_account_panel(cn, private: Path):
    """One scan, one group-by; annual features derived from same eligible rows."""
    announce("[25%] F: aggregate all 41.5m choices by chooser, year and board state")
    annual = private / "account_year_state_private.parquet"
    query = """
    SELECT chooser,
      CASE WHEN month <= '2024-10' THEN 1 ELSE 2 END AS period,
      CASE WHEN v >= -100 THEN 'C' WHEN v <= -300 THEN 'L' ELSE 'M' END AS region,
      COUNT(*) AS n, SUM(grant) AS y,
      COUNT(*) FILTER (WHERE ply>10) AS n_late,
      COALESCE(SUM(grant) FILTER (WHERE ply>10),0) AS y_late,
      AVG(GREATEST(-600.0, LEAST(600.0,v))) AS mean_vclip,
      AVG(CAST(ply AS DOUBLE)) AS mean_ply,
      AVG(rating_chooser) AS mean_rating,
      AVG(rating_opponent-rating_chooser) AS mean_gap,
      AVG(CASE WHEN speed='ultrabullet' THEN 1.0 ELSE 0.0 END) AS share_ultrabullet,
      AVG(CASE WHEN speed='bullet' THEN 1.0 ELSE 0.0 END) AS share_bullet,
      AVG(CASE WHEN speed='blitz' THEN 1.0 ELSE 0.0 END) AS share_blitz,
      AVG(CASE WHEN speed='rapid' THEN 1.0 ELSE 0.0 END) AS share_rapid,
      AVG(CASE WHEN speed='classical' THEN 1.0 ELSE 0.0 END) AS share_classical
    FROM f_norm
    GROUP BY chooser, period, region
    """
    cn.execute("COPY (" + query + ") TO " + lit(str(annual))
               + " (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 200000)")
    cn.execute("CREATE OR REPLACE VIEW f_annual AS SELECT * FROM read_parquet(" + lit(str(annual)) + ")")
    wide = private / "account_year_wide_private.parquet"
    columns = ["chooser"]
    for yr in (1, 2):
        for state in STATES:
            suffix = f"{state.lower()}{yr}"
            for col in ("n", "y", "n_late", "y_late"):
                columns.append(f"COALESCE(MAX(CASE WHEN period={yr} AND region='{state}' THEN {col} END),0) AS {col}_{suffix}")
            if yr == 2:
                for col in ("mean_vclip", "mean_ply", "mean_rating", "mean_gap",
                            "share_bullet", "share_blitz", "share_rapid", "share_classical"):
                    columns.append(f"MAX(CASE WHEN period={yr} AND region='{state}' THEN {col} END) AS {col}_{suffix}")
    qry = "SELECT " + ", ".join(columns) + " FROM f_annual GROUP BY chooser"
    cn.execute("COPY (" + qry + ") TO " + lit(str(wide)) + " (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)")
    cn.execute("CREATE OR REPLACE VIEW f_wide AS SELECT * FROM read_parquet(" + lit(str(wide)) + ")")
    # Check the private aggregation conserved counts for all six year/state cells.
    counter = cn.execute("SELECT SUM(n_c1+n_l1+n_m1+n_c2+n_l2+n_m2), "
                         "SUM(y_c1+y_l1+y_m1+y_c2+y_l2+y_m2) FROM f_wide").fetchone()
    if counter != (PAPER["rows"], PAPER["grants"]):
        raise ValueError(f"FAIL-CLOSED: aggregation failed to conserve rows/grants: {counter}")
    return annual, wide


def year_state_summary(cn, public):
    data = cn.execute("""SELECT period,region,SUM(n) opportunities,SUM(y) grants,
          COUNT(*) AS accounts_with_opportunity,
          COUNT(*) FILTER (WHERE y > 0) AS accounts_with_grant,
          100.0*SUM(y)/SUM(n) AS grant_rate_pp
          FROM f_annual GROUP BY period,region ORDER BY period,region""").fetchdf()
    save_csv(public / "tabF1_opportunities_by_year_state.csv", data)
    coverage=cn.execute("""SELECT
      CASE WHEN n_c1>0 THEN 1 ELSE 0 END AS C1_exposed,
      CASE WHEN n_l1>0 THEN 1 ELSE 0 END AS L1_exposed,
      CASE WHEN n_c2>0 THEN 1 ELSE 0 END AS C2_exposed,
      CASE WHEN n_l2>0 THEN 1 ELSE 0 END AS L2_exposed,
      COUNT(*) AS accounts
      FROM f_wide GROUP BY ALL ORDER BY ALL""").fetchdf()
    save_csv(public / "tabF1_region_exposure_support.csv", coverage)
    return data


def rate(y, n):
    return np.divide(np.asarray(y, dtype=float), np.asarray(n, dtype=float),
                     out=np.full(np.shape(y), np.nan, dtype=float), where=np.asarray(n)>0)


def wcor(a, b, weights=None):
    a=np.asarray(a,dtype=float); b=np.asarray(b,dtype=float)
    if weights is None: weights=np.ones(len(a),dtype=float)
    w=np.asarray(weights,dtype=float)
    keep=np.isfinite(a)&np.isfinite(b)&np.isfinite(w)&(w>0)
    a=a[keep];b=b[keep];w=w[keep]
    if len(a)<2: return float('nan')
    am=np.average(a,weights=w);bm=np.average(b,weights=w)
    da=a-am;db=b-bm
    den=float(np.sqrt(np.dot(w,da*da)*np.dot(w,db*db)))
    return float(np.dot(w,da*db)/den) if den>0 else float('nan')


def year_group(yc, yl):
    yc=np.asarray(yc); yl=np.asarray(yl)
    return np.select([(yc>0)&(yl==0), (yc==0)&(yl>0), (yc>0)&(yl>0)],
                     ["CO","LO","BOTH"], default="NEI")


def pair_correlations(df, threshold, label, src1="c", src2="l", late=False):
    pre = "y_late_" if late else "y_"
    size = "n_late_" if late else "n_"
    # Same state names in two years. Output rows for all four direction pairs.
    result=[]
    for s1 in (src1, src2):
        for s2 in (src1,src2):
            n1=df[f"{size}{s1}1"].to_numpy(dtype=float)
            n2=df[f"{size}{s2}2"].to_numpy(dtype=float)
            keep=(n1>0)&(n2>0)
            a=rate(df[f"{pre}{s1}1"].to_numpy(),n1)
            b=rate(df[f"{pre}{s2}2"].to_numpy(),n2)
            harmonic=np.where(keep,2*n1*n2/np.maximum(n1+n2,1),0)
            result.append(dict(sample=label, min_opportunities_each_year_and_state=threshold,
                    period1_state=s1, period2_state=s2, accounts=int(keep.sum()),
                    correlation_equal_account=wcor(a[keep],b[keep]),
                    correlation_harmonic_opportunities=wcor(a[keep],b[keep],harmonic[keep]),
                    observation_basis="after ply 10" if late else "all plies"))
    return result


def sample_account_panel(cn, threshold=4, cols="*", state1="l"):
    if state1 == "l":
        filter_=f"n_c1>={threshold} AND n_l1>={threshold} AND n_c2>={threshold} AND n_l2>={threshold}"
    elif state1 == "noncomp":
        filter_=f"n_c1>={threshold} AND (n_l1+n_m1)>={threshold} AND n_c2>={threshold} AND (n_l2+n_m2)>={threshold}"
    else:
        raise ValueError(state1)
    return cn.execute("SELECT " + cols + " FROM f_wide WHERE " + filter_).fetchdf()


def f0_published_reconciliation(cn,public):
    announce("[50%] F: reproduce published competitive-only persistence cohort")
    df=cn.execute("""SELECT n_c1,y_c1,n_c2,y_c2 FROM f_wide
         WHERE n_c1>=1 AND n_c2>=1 AND n_c1+n_c2>=4""").fetchdf()
    c1=rate(df.y_c1,df.n_c1);c2=rate(df.y_c2,df.n_c2)
    w=(df.n_c1+df.n_c2).to_numpy(dtype=float)
    row={"accounts":len(df),"pearson_equal_account":wcor(c1,c2),
         "pearson_total_comp_opportunities_weighted":wcor(c1,c2,w),
         "paper_accounts":666131,"paper_equal_account":0.545,"paper_weighted":0.618,
         "matches_paper_N":len(df)==666131,
         "matches_paper_correlations_to_0p005":abs(wcor(c1,c2)-.545)<.005 and abs(wcor(c1,c2,w)-.618)<.005}
    save_csv(public/"tabF0_original_competitive_reconciliation.csv",pd.DataFrame([row]))
    if not row["matches_paper_N"] or not row["matches_paper_correlations_to_0p005"]:
        announce("WARN: Manuscript C-persistence benchmark differs. F results should not be interpreted until sample alignment is investigated: "+str(row))
    return row


def retention(cn,public):
    df=cn.execute("""SELECT
    CASE WHEN y_c1>0 AND y_l1>0 THEN 'BOTH'
         WHEN y_c1>0 THEN 'CO' WHEN y_l1>0 THEN 'LO' ELSE 'NEI' END p1_grp,
    COUNT(*) AS p1_accounts,
    COUNT(*) FILTER(WHERE n_c2>0 OR n_l2>0) AS p2_either_region_accounts,
    COUNT(*) FILTER(WHERE n_c2>=1 AND n_l2>=1) AS p2_at_least_one_both_regions,
    COUNT(*) FILTER(WHERE n_c2>=4 AND n_l2>=4) AS p2_primary_eligible,
    COUNT(*) FILTER(WHERE n_c2>=10 AND n_l2>=10) AS p2_ten_each_eligible,
    SUM(n_c1) AS p1_comp_opportunities, SUM(n_l1) AS p1_lost_opportunities,
    SUM(n_c2) AS p2_comp_opportunities, SUM(n_l2) AS p2_lost_opportunities
    FROM f_wide WHERE n_c1>=4 AND n_l1>=4 GROUP BY p1_grp ORDER BY p1_grp""").fetchdf()
    df["p2_primary_eligibility_share"]=df.p2_primary_eligible/df.p1_accounts
    save_csv(public/"tabF2_retention.csv",df)
    return df


def transition_rows(df, label, state2="l", stage="all plies"):
    """Generate exact 4x4 counts; no IDs in outputs."""
    yr1=year_group(df["y_c1"],df["y_"+state2+"1"])
    yr2=year_group(df["y_c2"],df["y_"+state2+"2"])
    if stage != "all plies":
        yr1=year_group(df["y_late_c1"],df["y_late_"+state2+"1"])
        yr2=year_group(df["y_late_c2"],df["y_late_"+state2+"2"])
    rows=[]
    for g1 in GROUPS:
        tot=int(np.sum(yr1==g1))
        for g2 in GROUPS:
            n=int(np.sum((yr1==g1)&(yr2==g2)))
            rows.append(dict(sample=label,p1_group=g1,p2_group=g2,accounts=n,
                   p1_group_accounts=tot,p2_share_percent=100*n/tot if tot else float('nan'),
                   P1_P2_group_definition=("competitive vs clearly worse" if state2=="l" else "competitive vs all noncompetitive"),
                   decision_stage=stage))
    return rows


def p2_rates(df,label,stage="all plies"):
    g1=year_group(df.y_c1,df.y_l1)
    rows=[]
    prefix="" if stage == "all plies" else "late_"
    for g in GROUPS:
        d=df[g1==g]
        for st in STATES:
            n=d[f"n_{prefix}{st.lower()}2"].to_numpy(dtype=float)
            y=d[f"y_{prefix}{st.lower()}2"].to_numpy(dtype=float)
            has=n>0
            rows.append(dict(sample=label,stage=stage,P1_group=g,P2_region=st,
                    accounts=int(len(d)),accounts_with_P2_region=int(has.sum()),
                    P2_opportunities=int(n.sum()),P2_grants=int(y.sum()),
                    P2_pooled_rate_pp=100*y.sum()/n.sum() if n.sum()>0 else float('nan'),
                    P2_equal_account_mean_rate_pp=100*float(np.nanmean(rate(y[has],n[has]))) if has.any() else float('nan')))
    return rows


def weighted_wls(X,y,w):
    """One record/account; stable weighted QR, account-robust sandwich.

    v1.0.1 checked rank(X'WX). Forming normal equations squares the
    condition number, so this can spuriously diagnose collinearity and is
    numerically less stable than working with sqrt(W)X.
    """
    X=np.asarray(X,dtype=float);y=np.asarray(y,dtype=float);w=np.asarray(w,dtype=float)
    if (len(X)<X.shape[1]+2 or len(y)!=len(X) or len(w)!=len(X)
            or np.any(w<=0) or not np.isfinite(X).all()
            or not np.isfinite(y).all() or not np.isfinite(w).all()):
        raise ValueError("Bad F primary regression support or nonfinite design")
    sw=np.sqrt(w)
    q,r=np.linalg.qr(X*sw[:,None],mode="reduced")
    sv=np.linalg.svd(r,compute_uv=False)
    if sv[-1] <= sv[0]*1e-12:
        raise ValueError("F model not identified even after deterministic nuisance pruning; "
                         f"weighted QR singular ratio={sv[-1]/sv[0]:.3g}")
    beta=np.linalg.solve(r,q.T@(y*sw))
    # (X'WX)^-1 computed using QR rather than squaring the condition number
    rinv=np.linalg.solve(r,np.eye(len(beta)))
    bread=rinv@rinv.T
    resid=y-X@beta
    scores=X*(w*resid)[:,None]
    factor=len(X)/(len(X)-1)
    vcov=factor*bread@(scores.T@scores)@bread
    vcov=(vcov+vcov.T)/2.0
    return beta,vcov,scores,bread


def keep_identified_covariates(X, weights, names, protected_count, tolerance=1e-9):
    """Keep ALL preregistered focal terms; prune ONLY redundant nuisance terms.

    Weighted, twice re-orthogonalized modified Gram-Schmidt makes column-rank
    decisions on sqrt(W)X, avoiding the ill-conditioned X'WX rank check.
    One of the speed shares can equal the complement of the others exactly
    when ultrabullet is absent; this is nuisance redundancy, not evidence that
    the focal persistence coefficients are unidentified.

    Returns an unchanged-column subset (no rotation of model coefficients).
    """
    X=np.asarray(X,dtype=float);w=np.asarray(weights,dtype=float)
    if X.ndim!=2 or X.shape[1]!=len(names):
        raise ValueError("Design column/name mismatch")
    sw=np.sqrt(w)
    basis=[]; retained=[]; drops=[]
    for j,name in enumerate(names):
        v=X[:,j]*sw
        original_norm=float(np.linalg.norm(v))
        if not np.isfinite(original_norm):
            raise ValueError("Nonfinite weighted design norm: "+name)
        remainder=v.copy()
        for _ in range(2):
            if basis:
                Q=np.column_stack(basis)
                remainder-=Q@(Q.T@remainder)
        residual_norm=float(np.linalg.norm(remainder))
        ratio=residual_norm/original_norm if original_norm>0 else 0.0
        if ratio < tolerance:
            if j<protected_count:
                raise ValueError("FAIL CLOSED: focal year-one predictor not separately "
                                 f"identified: {name}; residual_ratio={ratio:.3g}")
            drops.append(dict(dropped_covariate=name, weighted_relative_residual=ratio,
                              reason="linearly redundant with earlier protected/retained columns"))
            continue
        basis.append(remainder/residual_norm)
        retained.append(j)
    return X[:,retained], [names[j] for j in retained], drops


def design(df, region, continuous=False, return_drops=False):
    n1c=df.n_c1.to_numpy(dtype=float);n1l=df.n_l1.to_numpy(dtype=float)
    c=(100*rate(df.y_c1,n1c) if continuous else (df.y_c1>0).to_numpy(dtype=float))
    l=(100*rate(df.y_l1,n1l) if continuous else (df.y_l1>0).to_numpy(dtype=float))
    features=[np.ones(len(df)),c,l]
    names=["intercept","P1_competitive_rate_pp" if continuous else "P1_ever_C",
           "P1_lost_rate_pp" if continuous else "P1_ever_L"]
    if not continuous:
        features.append(c*l);names.append("P1_both_interaction")
    suffix="_"+region+"2"
    for name,arr in (
        ("ln_nC1",np.log1p(n1c)),
        ("ln_nL1",np.log1p(n1l)),
        ("ln_nC2",np.log1p(df.n_c2.to_numpy(dtype=float))),
        ("ln_nL2",np.log1p(df.n_l2.to_numpy(dtype=float))),
        ("P2_mean_chooser_rating",df["mean_rating"+suffix].to_numpy(dtype=float)),
        ("P2_mean_opponent_rating_gap",df["mean_gap"+suffix].to_numpy(dtype=float)),
        ("P2_mean_capped_engine_eval",df["mean_vclip"+suffix].to_numpy(dtype=float)),
        ("P2_mean_plies",df["mean_ply"+suffix].to_numpy(dtype=float)),
        ("P2_bullet_share",df["share_bullet"+suffix].to_numpy(dtype=float)),
        ("P2_blitz_share",df["share_blitz"+suffix].to_numpy(dtype=float)),
        ("P2_rapid_share",df["share_rapid"+suffix].to_numpy(dtype=float)),
        ("P2_classical_share",df["share_classical"+suffix].to_numpy(dtype=float))):
        if not np.isfinite(arr).all():
            raise ValueError("Missing compositional F controls: "+name)
        # Center and scale descriptive controls; leave historical grant variables in native units.
        w=np.asarray(df["n_"+region+"2"],dtype=float)
        avg=float(np.average(arr,weights=w));std=float(np.sqrt(np.average((arr-avg)**2,weights=w)))
        if std<1e-10:
            continue
        features.append((arr-avg)/std);names.append(name+"_standardized")
    X=np.column_stack(features)
    y=100*rate(df["y_"+region+"2"],df["n_"+region+"2"])
    w=df["n_"+region+"2"].to_numpy(dtype=float)
    # The intercept and year-one C/L/(C x L) coefficients are never dropped.
    protected_count=3 if continuous else 4
    X,names,dropped=keep_identified_covariates(X,w,names,protected_count)
    if return_drops:
        return X,y,w,names,dropped
    return X,y,w,names


def normal_p(z):
    return math.erfc(abs(float(z))/math.sqrt(2))


def cross_predict(df, public):
    announce("[75%] F: two year-two outcome models with joint chooser-level covariance")
    results=[]; fits={}; dropped_controls=[]
    means={s:100*df["y_"+s+"2"].sum()/df["n_"+s+"2"].sum() for s in ("c","l")}
    for cont in (False,True):
        modeltype="continuous_first_year_rates" if cont else "binary_year_one_grant_history"
        for s in ("c","l"):
            X,y,w,names,dropped=design(df,s,continuous=cont,return_drops=True)
            for item in dropped:
                dropped_controls.append(dict(model=modeltype,P2_outcome=s,**item))
            if dropped:
                announce("F collinearity audit: "+modeltype+" / "+s+": omitted only redundant nuisance controls: "+", ".join(item['dropped_covariate'] for item in dropped))
            beta,vcov,scores,bread=weighted_wls(X,y,w)
            fits[(cont,s)]=(X,y,w,names,beta,vcov,scores,bread)
            for j,name in enumerate(names):
                est=float(beta[j]);se=math.sqrt(max(0,float(vcov[j,j])))
                if j>=4 and not cont or (cont and j>=3):
                    # Avoid filling table with nuisance standardized controls.
                    continue
                results.append(dict(model=modeltype,P2_outcome=s,estimand=name,estimate=est,
                       se=se,ci95_low=est-1.96*se,ci95_high=est+1.96*se,p_value=normal_p(est/se) if se>0 else float('nan'),
                       second_year_mean_pp=float(means[s]), accounts=int(len(df)),
                       second_year_opportunities=int(w.sum()),scale="pp of P2 grant rate per P1 indicator" if not cont else "pp P2 per pp P1"))
        a=fits[(cont,"c")];b=fits[(cont,"l")]
        cross=a[7]@(a[6].T@b[6])@b[7]*(len(df)/(len(df)-1))
        if not cont:
            # Proportional differences in same-state vs cross-state predictive associations.
            # Effects refer to P1 accounts with neither other-state grant (since interaction=0).
            tests=(("C1_predicts_C2_more_than_L2", "P1_ever_C", +1),
                   ("L1_predicts_L2_more_than_C2", "P1_ever_L", -1))
            for key,name,sgn in tests:
                ia=a[3].index(name);ib=b[3].index(name)
                estc=float(a[4][ia])/means["c"]
                estl=float(b[4][ib])/means["l"]
                v=(float(a[5][ia,ia])/(means["c"]**2) +
                   float(b[5][ib,ib])/(means["l"]**2) -
                   2*float(cross[ia,ib])/(means["c"]*means["l"]))
                est=(estc-estl)*sgn
                se=math.sqrt(max(0,v))
                results.append(dict(model=modeltype,P2_outcome="outcome_normalized_comparison",estimand=key,
                      estimate=est,se=se,ci95_low=est-1.96*se,ci95_high=est+1.96*se,
                      p_value=normal_p(est/se) if se>0 else float('nan'),
                      second_year_mean_pp=float('nan'),accounts=int(len(df)),
                      second_year_opportunities=int(df.n_c2.sum()+df.n_l2.sum()),
                      scale="difference in P2 effects divided by own P2 outcome mean"))
    tab=pd.DataFrame(results)
    mask=(tab.model=="binary_year_one_grant_history")&(tab.P2_outcome=="outcome_normalized_comparison")
    if int(mask.sum())==2:
        p=tab.loc[mask,"p_value"].to_numpy(float)
        sorted_idx=np.argsort(p)
        corrected=np.zeros(2)
        corrected[sorted_idx[0]]=min(1.,2*p[sorted_idx[0]])
        corrected[sorted_idx[1]]=max(corrected[sorted_idx[0]],p[sorted_idx[1]])
        tab.loc[mask,"holm_p_two_comparisons"]=corrected
    save_csv(public/"tabF5_cross_prediction.csv",tab)
    save_csv(public/"tabF5_collinearity_audit.csv",pd.DataFrame(
        dropped_controls,columns=["model","P2_outcome","dropped_covariate",
                                 "weighted_relative_residual","reason"]))
    return tab


def threshold_table(cn,public):
    rows=[];allcors=[]; selectivity=[];transition_sensitivity=[]
    cols="n_c1,y_c1,n_l1,y_l1,n_m1,y_m1,n_c2,y_c2,n_l2,y_l2,n_m2,y_m2"
    for threshold in (1,4,10):
        d=sample_account_panel(cn,threshold,cols)
        if d.empty:
            raise ValueError(f"No accounts satisfy Test F threshold {threshold}; input likely wrong")
        cors=pair_correlations(d,threshold,f"balanced_C_L_each_year_min_{threshold}")
        allcors.extend(cors)
        transition_sensitivity.extend(transition_rows(d,f"balanced_C_L_each_year_min_{threshold}"))
        pC1=rate(d.y_c1,d.n_c1);pC2=rate(d.y_c2,d.n_c2)
        pL1=rate(d.y_l1,d.n_l1);pL2=rate(d.y_l2,d.n_l2)
        select1=pC1-pL1;select2=pC2-pL2
        overall1=(pC1+pL1)/2;overall2=(pC2+pL2)/2
        exposure=4/(1/d.n_c1+1/d.n_l1+1/d.n_c2+1/d.n_l2)
        selectivity.append(dict(threshold=threshold,accounts=len(d),
              corr_selectivity_rate_difference=wcor(select1,select2),
              corr_selectivity_harmonic=wcor(select1,select2,exposure),
              corr_overall_two_state_rate=wcor(overall1,overall2),
              corr_overall_two_state_rate_harmonic=wcor(overall1,overall2,exposure),
              selectivity_definition='competitive grant rate minus clearly-worse grant rate; raw account shares',
              overall_definition='arithmetic mean of competitive and clearly-worse rates; descriptive'))
        corrmap={(r["period1_state"],r["period2_state"]):r["correlation_equal_account"] for r in cors}
        rows.append(dict(threshold=threshold,accounts=len(d),
                 corr_C1_C2=corrmap[("c","c")],corr_L1_L2=corrmap[("l","l")],
                 corr_C1_L2=corrmap[("c","l")],corr_L1_C2=corrmap[("l","c")],
                 P2_comp_opportunities=int(d.n_c2.sum()),P2_lost_opportunities=int(d.n_l2.sum()),
                 P2_comp_grants=int(d.y_c2.sum()),P2_lost_grants=int(d.y_l2.sum())))
    save_csv(public/"tabF6_threshold_sensitivity.csv",pd.DataFrame(rows))
    save_csv(public/"tabF6_transition_thresholds.csv",pd.DataFrame(transition_sensitivity))
    save_csv(public/"tabF4_cross_year_correlations.csv",pd.DataFrame(allcors))
    save_csv(public/"tabF4_selectivity_persistence.csv",pd.DataFrame(selectivity))
    return rows


def sensitivities(cn,public):
    # C vs (L+M). Never treat M as competitive in the primary model.
    d=sample_account_panel(cn,4,"n_c1,y_c1,n_l1,y_l1,n_m1,y_m1,n_c2,y_c2,n_l2,y_l2,n_m2,y_m2",state1="noncomp")
    if d.empty:
        raise ValueError("No full-noncompetitive sensitivity support")
    d=d.copy()
    for yr in (1,2):
        d[f"n_n{yr}"]=d[f"n_l{yr}"]+d[f"n_m{yr}"]
        d[f"y_n{yr}"]=d[f"y_l{yr}"]+d[f"y_m{yr}"]
    rows=transition_rows(d,"balanced_comp_vs_noncomp_4",state2="n")
    save_csv(public/"tabF7_noncompetitive_and_stage_sensitivity.csv",pd.DataFrame(rows))
    save_csv(public/"tabF7_noncompetitive_correlations.csv",pd.DataFrame(
        pair_correlations(d,4,"balanced_comp_vs_noncomp_4",src1="c",src2="n")))
    # P2 counterpart rates by P1 group using all noncompetitive (M+L) grants and opportunities.
    group_non=year_group(d.y_c1,d.y_n1)
    nonrows=[]
    for gg in GROUPS:
        dd=d[group_non==gg]
        for state in ('c','n'):
            nn=dd[f'n_{state}2'].to_numpy(float)
            yy=dd[f'y_{state}2'].to_numpy(float)
            nonrows.append(dict(P1_group=gg,P2_region='competitive' if state=='c' else 'all_noncompetitive',
                 accounts=len(dd),P2_opportunities=int(nn.sum()),P2_grants=int(yy.sum()),
                 P2_rate_pp=100*yy.sum()/nn.sum() if nn.sum()>0 else float('nan'),
                 P2_equal_account_rate_pp=100*float(np.nanmean(rate(yy,nn))) if len(dd)>0 else float('nan')))
    save_csv(public/"tabF7_noncompetitive_P2_rates.csv",pd.DataFrame(nonrows))
    # Same original 4+4 all-stage cohort; classify grants that occurred after ply 10.
    d2=sample_account_panel(cn,4,
         "n_c1,y_c1,n_l1,y_l1,n_m1,y_m1,n_c2,y_c2,n_l2,y_l2,n_m2,y_m2,"
         "n_late_c1,y_late_c1,n_late_l1,y_late_l1,n_late_c2,y_late_c2,n_late_l2,y_late_l2")
    after=transition_rows(d2,"balanced_C_L_primary_cohort_after10",state2="l",stage="after ply 10")
    # Require at least one after-ply-10 exposure in EACH region/year for the correlation sensitivity.
    good=d2[(d2.n_late_c1>0)&(d2.n_late_l1>0)&(d2.n_late_c2>0)&(d2.n_late_l2>0)]
    cors=pair_correlations(good,4,"primary_eligible_with_positive_after10_exposure",late=True)
    save_csv(public/"tabF7_stage_transition_after10.csv",pd.DataFrame(after))
    save_csv(public/"tabF7_stage_correlations_after10.csv",pd.DataFrame(cors))
    return {"noncompetitive_balanced_accounts":len(d),"after10_primary_cohort":len(d2),
            "after10_positive_exposure_accounts":len(good)}


def figure_transition(df,public):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        announce("Matplotlib absent: transition-heatmap PDF skipped; CSV remains authoritative")
        return False
    a=pd.DataFrame(transition_rows(df,"primary"))
    p=a.pivot(index="p1_group",columns="p2_group",values="p2_share_percent").reindex(index=GROUPS,columns=GROUPS)
    fig,ax=plt.subplots(figsize=(7,5.6))
    m=ax.imshow(p.to_numpy(float),cmap="Blues",vmin=0,vmax=100)
    ax.set(xticks=range(4),yticks=range(4),xticklabels=GROUPS,yticklabels=GROUPS,
           xlabel="Year 2 granting group",ylabel="Year 1 granting group",
           title="Year-to-year transitions (share of Year 1 group)")
    for i in range(4):
        for j in range(4):
            val=float(p.iloc[i,j]);ax.text(j,i,f"{val:.1f}%",ha="center",va="center",
                                        color="white" if val>55 else "black",fontsize=10)
    fig.colorbar(m,ax=ax,label="Row percentage")
    fig.tight_layout();fig.savefig(public/"figF1_transition_heatmap.pdf");plt.close(fig)
    return True


def make_receipt(public:Path, inputpath, start, preflightdata, rec, nt):
    files=[]
    for fp in sorted(public.iterdir()):
        if fp.is_file() and fp.name!="_SUCCESS.json":
            files.append(dict(name=fp.name,sha256=hashlib.sha256(fp.read_bytes()).hexdigest(),bytes=fp.stat().st_size))
    ledger={"status":"TEST_F_ANALYSIS_COMPLETE_AGGREGATES_ONLY",
            "script_version":"v1.0.2", "timestamp_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "source_file_basename":Path(inputpath).name,"source_verified_against_manuscript":True,
            "preflight":preflightdata,"published_competitive_reconciliation":rec,
            "F_primary_balanced_accounts":nt,
            "private_account_level_outputs_included":False,
            "interpretation":"Predictive year-to-year associations, not identified latent types.",
            "runtime_minutes":round((time.monotonic()-start)/60,2),
            "files":files}
    (public/"_SUCCESS.json").write_text(json.dumps(ledger,indent=2,default=str)+"\n")
    return ledger


def main():
    ap=argparse.ArgumentParser(description="Test F year-to-year state-specific granting persistence")
    ap.add_argument("--root",default="/Volumes/XT_Pro/lichess_kindness")
    ap.add_argument("--main",help="Frozen 41.53m POOL/NONADJACENT sample Parquet path or .duckdb")
    ap.add_argument("--view",help="Required if --main is a DuckDB file")
    ap.add_argument("--out",help="Fresh immutable output folder")
    ap.add_argument("--workers",type=int,default=10)
    ap.add_argument("--memory-gb",type=int,default=11)
    ap.add_argument("--discover",action="store_true")
    args=ap.parse_args()
    if args.discover:
        print("Candidate POOL/NONADJACENT datasets (verify exact input manifest before use):")
        print("\n".join(candidate_paths(args.root)) or "(no automatic candidates)")
        return
    if not args.main:ap.error("--main path is required (must be 41,534,331-row sample)")
    if not args.out:ap.error("--out immutable output path is required")
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=False)
    (out/"private").mkdir(); (out/"public").mkdir()
    start=time.monotonic()
    announce("Test F begins. Private account-level data remain on local Mac drive.")
    (out/"private"/"SOURCE_PATH.txt").write_text(args.main+"\n")
    cn=connect(out,args.workers,args.memory_gb)
    try:
        source,kind=input_sql(args.main,args.view)
        if kind=="duckdb":
            cn.execute("ATTACH "+lit(str(args.main))+" AS main_data (READ_ONLY)")
        matched=choose_columns(cn,source)
        (out/"private"/"INPUT_COLUMNS.json").write_text(json.dumps(matched,indent=2)+"\n")
        preflightdata=preflight(cn)
        announce("F preflight passed: exact 24-month paper sample and primary region counts")
        build_account_panel(cn,out/"private")
        year_state_summary(cn,out/"public")
        rec=f0_published_reconciliation(cn,out/"public")
        retention(cn,out/"public")
        primary=sample_account_panel(cn,4)
        if primary.empty:raise ValueError("No primary cohort with 4+ in each state in each year")
        save_csv(out/"public"/"tabF2_transition_4x4.csv",pd.DataFrame(transition_rows(primary,"primary_balanced_C_L_4")))
        save_csv(out/"public"/"tabF3_P2_rates_by_P1_group.csv",pd.DataFrame(p2_rates(primary,"primary_balanced_C_L_4")))
        figure_transition(primary,out/"public")
        threshold_table(cn,out/"public")
        cross_predict(primary,out/"public")
        sens=sensitivities(cn,out/"public")
        ledger=make_receipt(out/"public",args.main,start,preflightdata,rec,len(primary))
        (out/"private"/"SECONDARY_NOTES.json").write_text(json.dumps(sens,indent=2)+"\n")
        announce("[100%] Test F completed: "+str(out/"public"))
        announce("F runtime: %.1f minutes"%((time.monotonic()-start)/60))
    except Exception:
        (out/"private"/"FAILED.txt").write_text(traceback.format_exc())
        announce("F FAILED CLOSED; see private FAILED.txt (outputs not certified)")
        raise
    finally:
        cn.close()


if __name__ == "__main__":
    main()
