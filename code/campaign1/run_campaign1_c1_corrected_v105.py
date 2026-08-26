#!/usr/bin/env python3
"""
Campaign 1 C1 corrected completion v1.0.5.

This post-outcome technical correction replaces two invalid C1 lineages. A physical
query of the exact chronology and its authenticated historical producer establish the
raw encoding unambiguously:

    result_code = 2 White win, 1 draw, 0 Black win.

The producer first decodes raw code to White-signed {-1,0,+1}, then converts that sign
to the chooser's perspective. It never treats the raw code as already signed.

Important implementation protections:
  * NEVER construct result from ratingDiff; use its sign only as a validator.
  * Authenticate and re-run the physical result-code decider before estimation.
  * Reject every bridge code outside {0,1,2} and every unmatched chooser side.
  * Report raw-code and chooser-result marginals before reading current kindness.
  * Match sampled user_id directly to chronology white_id / black_id.
  * Build only the lags C1 actually needs.
  * Restrict history to the Campaign-1 window plus a two-hour left boundary buffer.
  * Result lookup is limited to prior games that satisfy a 60-minute sensitivity
    or are among the three immediately prior games in a valid 30-minute streak.
  * Freeze bridge coverage before reading kindness by preceding result.
  * No persistent private-cache mutation; all row-level intermediates are temporary.
  * Aggregate outputs only. No API. No raw PGN download. No Git mutation.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import wave1_common_v100 as wc

PROJECT = Path("/Volumes/XT_Pro/lichess_kindness")
EXPECTED_GIT = "46abb7409621e98c74dc8aa3eb3b3885a644080d"
EXPECTED_AMD103_SHA = "96530f7ffd43b7d68ff84c794200f7db98b2b455ea2994efb5b73ce5cb370a07"
EXPECTED_AMD105_SHA = "14cb718408788ea15f94d555eaabc84c27f2dc42b1ca85c03b46daf43e366787"
EXPECTED_HISTORICAL_PRODUCER_SHA = "02a14d3de5ef7fadf59909b703ad481ca23625fea39c43a5d09cdc86cfbc4458"
EXPECTED_PHYSICAL_DECIDER_JSON_SHA = "f5cfb8836f1425a7083f55a41934a843fd143a15fbca9ff59bd6661a4385b7b2"
EXPECTED_PHYSICAL_DECIDER_TEXT_SHA = "299cd137b96acf1ac5d3051be6b17dba8028a0bce2b76fdbef2dfc8b62e27b11"
EXPECTED_HANDOFF_SHA = "a0ad057d122606a40fec659a0239020f7a14884a4081306ffe55f2315f43b32a"

PAYLOAD_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PRIOR_EVIDENCE = {
    "prior_evidence/c1_run_b_v101/FAILURE_DIAGNOSTIC.json":
        "e43d4c1d6e877ca1a0e05518af1c7e600aee00ac0cd75d5f2d02845dad320378",
    "prior_evidence/c1_run_b_v101/c1_chronology_authority.json":
        "ed0d5f67110da8f7860034ea89c7dbe6798c5a17b7ac417de2a0434f12cd48a8",
    "prior_evidence/c1_run_b_v101/c1_prior_result_state_dependence.csv":
        "45fe1b81a1838462a5bbec15c3a1c13a8da8eb249123a3bd9d8d3a5b86ce6eeb",
    "prior_evidence/c1_run_b_v101/c1_result_bridge_coverage.json":
        "cacbefa519441d03c9e9f1aebbb7ac92e5cb8935b247254c8daa8bd5b2c0449d",
    "prior_evidence/c1_run_b_v102/_SUCCESS.json":
        "04e24374b931549b4721e416bb4b29c0b1744b7ece6e822e40f3aa1d9e6175e6",
    "prior_evidence/c1_run_b_v102/c1_chronology_authority.json":
        "ed0d5f67110da8f7860034ea89c7dbe6798c5a17b7ac417de2a0434f12cd48a8",
    "prior_evidence/c1_run_b_v102/c1_prior_result_state_dependence.csv":
        "ec1bc91b012f63205192160b29377344d83e65c195ac9b6ed7176732c34c5ee9",
    "prior_evidence/c1_run_b_v102/c1_secondary_streak3_STATUS.json":
        "ee6c3e417ad1ee52c474004f8fad28881d0c1cbd14185eed9dcfab68504967e4",
    "prior_evidence/c1_run_b_v102/summary.json":
        "770ba886f5417c4b186736408965f4d07596d99002a1169dd7b541df67416c7d",
}

EXPECTED_PHYSICAL_COUNTS = {0: 20_340_159, 1: 1_916_130, 2: 21_888_082}
EXPECTED_PHYSICAL_TOTAL = 44_144_371
MIN_PRIMARY_COVERAGE_SHARE = 0.99
MIN_PRIMARY_ESTIMATION_PRESERVATION_SHARE = 0.90
MIN_DECISIVE_RATING_SIGN_ALIGNMENT = 0.99
MIN_STREAK_DIRECT_CANDIDATES = 1_000
MIN_STREAK_CANDIDATES_PER_ARM = 250

EXPECTED_CHRON_FILES = 852
EXPECTED_CHRON_ROWS = 7_763_847_245
EXPECTED_HISTORY_ROWS = 309_961_276
EXPECTED_TARGET_ROWS = 685_731
EXPECTED_STAGE07_ROWS = 47_587_020
EXPECTED_USER_TARGETS = 345_624
EXPECTED_WAVE1_SUMMARY_SHA = "66e1b1a9cc59be928d8535a8887c81e2241b021b6c0e1c38c2ca314463308e2f"

CAMPAIGN_START_MS = int(dt.datetime(2023,11,1,tzinfo=dt.timezone.utc).timestamp()*1000)
CAMPAIGN_END_MS = int(dt.datetime(2025,11,1,tzinfo=dt.timezone.utc).timestamp()*1000)
# Three prior games in one <30m session can reach almost 90 minutes leftward.
HISTORY_LEFT_MS = CAMPAIGN_START_MS - 2*60*60*1000

CHRON_PATH_RE = re.compile(r"/speed=([^/]+)/month=(20\d{2}-\d{2})/")

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha256_file(path: Path, chunk=8*1024*1024):
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def run(cmd, cwd=None):
    p=subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,check=True)
    return p.stdout.strip()

def parquet_rows(path: Path):
    import pyarrow.parquet as pq
    return int(pq.ParquetFile(path).metadata.num_rows)

def total_rows(paths):
    import pyarrow.parquet as pq
    return sum(int(pq.ParquetFile(p).metadata.num_rows) for p in paths)

def parse_chronology_manifest(path: Path):
    rows=[]
    with path.open(newline="") as f:
        r=csv.DictReader(f,delimiter="\t")
        for row in r:
            p=Path(row["path"])
            m=CHRON_PATH_RE.search(str(p))
            if not m:
                raise RuntimeError(f"Cannot parse speed/month from chronology path: {p}")
            rows.append({
                "path":p,
                "bytes":int(row["bytes"]),
                "rows":int(row["rows"]),
                "speed":m.group(1),
                "month":m.group(2),
                "footer_signature_sha256":row["footer_signature_sha256"],
            })
    return rows

def relevant_chronology_paths(manifest_rows, groups):
    by={(x["month"],x["speed"]):x for x in manifest_rows}
    chosen=[]
    missing=[]
    for month,speed,n in groups:
        key=(str(month),str(speed))
        if key not in by:
            missing.append({"month":str(month),"speed":str(speed),"needed_rows":int(n)})
        else:
            chosen.append(by[key])
    if missing:
        raise RuntimeError(f"Chronology partition(s) missing for needed result groups: {missing}")
    # deterministic, unique
    d={str(x["path"]):x for x in chosen}
    return [d[k] for k in sorted(d)]

def raw_to_white_result_sql(expr="c.result_code"):
    """Decode the physical 0/1/2 chronology code to White-signed result."""
    return f"""CASE CAST({expr} AS INTEGER)
      WHEN 2 THEN 1
      WHEN 1 THEN 0
      WHEN 0 THEN -1
      ELSE NULL
    END"""

def decode_raw_result_code(raw_code: int, chooser_is_white: bool) -> int:
    """Pure-Python mirror used only for unit testing the explicit decoder."""
    white_sign={2:1,1:0,0:-1}.get(raw_code)
    if white_sign is None:
        raise ValueError(f"Unexpected raw result_code={raw_code}")
    return white_sign if chooser_is_white else -white_sign

def relative_result_sql():
    white_sign=raw_to_white_result_sql("c.result_code")
    return f"""CASE
      WHEN CAST(n.chooser_key AS BIGINT)=CAST(c.white_id AS BIGINT)
        THEN ({white_sign})
      WHEN CAST(n.chooser_key AS BIGINT)=CAST(c.black_id AS BIGINT)
        THEN -({white_sign})
      ELSE NULL
    END"""

def chooser_rating_diff_sql():
    return """CASE
      WHEN CAST(n.chooser_key AS BIGINT)=CAST(c.white_id AS BIGINT)
        THEN CAST(c.white_rating_diff AS INTEGER)
      WHEN CAST(n.chooser_key AS BIGINT)=CAST(c.black_id AS BIGINT)
        THEN CAST(c.black_rating_diff AS INTEGER)
      ELSE NULL
    END"""

def authenticate_packaged_c1_evidence():
    authority_dir=PAYLOAD_ROOT/"authorities"/"c1"
    paths={
        "historical_producer":(
            authority_dir/"032_make_sorted_replay_events_v2_time.py",
            EXPECTED_HISTORICAL_PRODUCER_SHA,
        ),
        "physical_decider_json":(
            authority_dir/"result_code_physical_decider.json",
            EXPECTED_PHYSICAL_DECIDER_JSON_SHA,
        ),
        "physical_decider_text":(
            authority_dir/"result_code_physical_counts.txt",
            EXPECTED_PHYSICAL_DECIDER_TEXT_SHA,
        ),
        "campaign1_handoff":(
            authority_dir/"Kindness_Lichess_Campaign1_detailed_handoff_2026-08-25.md",
            EXPECTED_HANDOFF_SHA,
        ),
        "postoutcome_correction_v105":(
            PAYLOAD_ROOT/"docs"/"dynamics_paper2_campaign1_v1_0_5_postoutcome_correction.md",
            EXPECTED_AMD105_SHA,
        ),
    }
    for rel, expected in EXPECTED_PRIOR_EVIDENCE.items():
        paths["prior_"+rel.replace("/","_")]=(PAYLOAD_ROOT/rel,expected)
    report={}
    for label,(path,expected) in paths.items():
        if not path.is_file():
            raise RuntimeError(f"Packaged C1 authority missing: {label}: {path}")
        actual=sha256_file(path)
        if actual!=expected:
            raise RuntimeError(
                f"Packaged C1 authority SHA mismatch {label}: "
                f"expected={expected} actual={actual}"
            )
        report[label]={"path":str(path),"sha256":actual}

    producer=(authority_dir/"032_make_sorted_replay_events_v2_time.py").read_text()
    for token in ("WHEN '1-0' THEN 2","WHEN '1/2-1/2' THEN 1","WHEN '0-1' THEN 0"):
        if token not in producer:
            raise RuntimeError(f"Historical chronology producer mapping token missing: {token}")

    decider=json.loads((authority_dir/"result_code_physical_decider.json").read_text())
    expected_decider={
        "status":"C1_RESULT_CODE_PHYSICAL_DECIDER_COMPLETED",
        "decision_branch":"RAW_0_1_2",
        "physical_support":[0,1,2],
        "total_rows":EXPECTED_PHYSICAL_TOTAL,
        "nonnull_result_code_rows":EXPECTED_PHYSICAL_TOTAL,
        "null_result_code_rows":0,
        "row_conservation_pass":True,
    }
    for key,value in expected_decider.items():
        if decider.get(key)!=value:
            raise RuntimeError(f"Physical decider record mismatch: {key}")
    got_counts={int(k):int(v) for k,v in decider.get("result_code_counts",{}).items()}
    if got_counts!=EXPECTED_PHYSICAL_COUNTS:
        raise RuntimeError(f"Physical decider count mismatch: {got_counts}")
    return report,decider

def aggregate_tree_digest(root: Path) -> dict[str,Any]:
    records=[]
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        records.append({
            "file":str(path.relative_to(root)),
            "bytes":path.stat().st_size,
            "sha256":sha256_file(path),
        })
    canonical=json.dumps(records,sort_keys=True,separators=(",",":"))
    return {
        "root":str(root),
        "file_count":len(records),
        "total_bytes":sum(x["bytes"] for x in records),
        "tree_manifest_sha256":hashlib.sha256(canonical.encode()).hexdigest(),
    }

def scan_prior_c1_outputs(project: Path) -> dict[str,Any]:
    """Discover prior aggregate C1 primaries by coefficient, never by colliding name."""
    output=project/"output"
    csvs=[]
    if output.is_dir():
        for family in sorted(output.glob("dynamics_campaign1_c1*")):
            if family.is_dir():
                csvs.extend(sorted(family.rglob("c1_prior_result_state_dependence.csv")))
    found=[]
    unknown=[]
    for path in sorted(set(csvs)):
        with path.open(newline="") as f:
            rows=list(csv.DictReader(f))
        primary=[
            row for row in rows
            if row.get("term")=="prev_loss"
            and str(row.get("session_minutes")) in {"30","30.0"}
            and "same_pool" not in str(row.get("model",""))
        ]
        if len(primary)!=1:
            unknown.append({"path":str(path),"reason":"primary row not unique"})
            continue
        effect=float(primary[0]["effect_pp"])
        if "dynamics_campaign1_c1_corrected_v105" in path.parts:
            unknown.append({
                "path":str(path),
                "reason":"a prior corrected v1.0.5 primary attempt already exposed",
                "effect_pp":effect,
            })
            continue
        if 0.15<effect<0.35:
            lineage="Run_A_audit_lineage"
        elif -0.90<effect<-0.75:
            lineage="Run_B_production_lineage"
        else:
            unknown.append({
                "path":str(path),"reason":"unrecognized prior C1 effect",
                "effect_pp":effect,
            })
            continue
        found.append({
            "lineage":lineage,
            "classification":"INVALID_RESULT_CODE_SEMANTICS",
            "primary_effect_pp":effect,
            "primary_csv":str(path),
            "primary_csv_sha256":sha256_file(path),
            "result_tree":aggregate_tree_digest(path.parent),
        })
    if unknown:
        raise RuntimeError(
            "Unreconciled prior C1 primary output(s) found; refusing duplicate build: "
            f"{unknown}"
        )
    return {
        "status":"C1_PRIOR_OUTPUT_INVENTORY_COMPLETE",
        "discovery_rule":"coefficient fingerprint, not colliding package/folder name",
        "prior_primary_csvs_found":len(found),
        "runs":found,
        "run_A_found":any(x["lineage"]=="Run_A_audit_lineage" for x in found),
        "run_B_found":any(x["lineage"]=="Run_B_production_lineage" for x in found),
        "unknown_prior_primaries":0,
        "all_discovered_prior_primaries_invalidated":True,
    }

def self_test():
    pure=[]
    for raw in (2,1,0):
        pure.extend((
            (raw,decode_raw_result_code(raw,True)),
            (raw,decode_raw_result_code(raw,False)),
        ))
    if pure!=[(2,1),(2,-1),(1,0),(1,0),(0,-1),(0,1)]:
        raise RuntimeError(f"C1 pure result decoder self-test failed: {pure}")
    try:
        decode_raw_result_code(3,True)
    except ValueError:
        pass
    else:
        raise RuntimeError("C1 pure decoder accepted invalid raw code")

    try:
        import duckdb
    except ModuleNotFoundError:
        print("DYNAMICS_CAMPAIGN1_C1_V105_PURE_DECODER_SELF_TEST_OK_DUCKDB_NOT_INSTALLED")
        return
    con=duckdb.connect()
    con.execute("""
    CREATE TEMP TABLE n(seq INTEGER, chooser_key BIGINT, result_code INTEGER, white_id BIGINT, black_id BIGINT);
    INSERT INTO n VALUES
      (1,10,2,10,20),(2,20,2,10,20),
      (3,10,1,10,20),(4,20,1,10,20),
      (5,10,0,10,20),(6,20,0,10,20),
      (7,10,-1,10,20),(8,10,3,10,20);
    """)
    sql=relative_result_sql()
    got=con.execute(f"""
    SELECT n.result_code,{sql} AS chooser_result
    FROM n
    JOIN n c ON c.seq=n.seq
    ORDER BY n.seq
    """).fetchall()
    expected=[(2,1),(2,-1),(1,0),(1,0),(0,-1),(0,1),(-1,None),(3,None)]
    if got!=expected:
        raise RuntimeError(f"C1 result decoder self-test failed: got={got}")
    con.close()
    print("DYNAMICS_CAMPAIGN1_C1_V105_RESULT_DECODER_SELF_TEST_OK")

def write_execution_pointer(path: Path|None, obj: dict[str,Any]):
    if path is None:
        return
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,sort_keys=True)+"\n")

def make_current_targets(con, stage07_paths, target_path):
    s7_sql="["+",".join(wc.sqls(str(p)) for p in stage07_paths)+"]"
    con.execute(f"""
    CREATE TEMP TABLE current_targets AS
    SELECT
      CAST(t.chooser_user_id AS BIGINT) AS chooser_key,
      CAST(t.game_id AS VARCHAR) AS game_id,
      CAST(s.outcome_kind_draw AS DOUBLE) AS kind,
      CAST(s.engine_eval_cp_disconnected AS DOUBLE) AS eval_cp,
      CAST(s.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
      CAST(s.chooser_win_premium_v2 AS DOUBLE) AS win_premium,
      CAST(s.chooser_elo AS DOUBLE) AS chooser_elo,
      CAST(s.disconnected_elo AS DOUBLE) AS opponent_elo,
      CAST(s.chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
      CAST(s.disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
      CAST(s.chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock,
      CAST(s.disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock,
      CAST(s.api_speed AS VARCHAR) AS speed,
      CAST(s.tournament_like_event AS DOUBLE) AS tournament,
      CAST(s.month AS VARCHAR) AS event_month,
      CAST(s.api_last_move_at_ms AS BIGINT) AS current_utc_ms
    FROM read_parquet({wc.sqls(str(target_path))}) t
    INNER JOIN read_parquet({s7_sql}, union_by_name=true) s
      ON CAST(s.game_id AS VARCHAR)=CAST(t.game_id AS VARCHAR)
    WHERE coalesce(CAST(t.user_sample AS BOOLEAN),FALSE)
      AND CAST(s.engine_eval_cp_disconnected AS DOUBLE)>=-100
    """)
    n=con.execute("SELECT count(*) FROM current_targets").fetchone()[0]
    if int(n)!=EXPECTED_USER_TARGETS:
        raise RuntimeError(f"Current user-sample target count changed: {n}")

def prepare_model_frame(df):
    import numpy as np
    import pandas as pd
    df=df.copy()
    df["kind"]=pd.to_numeric(df["kind"],errors="coerce")
    df["eval_bin"]=pd.cut(
        df["eval_cp"],
        bins=[-np.inf,100,299,np.inf],
        labels=["roughly_equal","disconnected_better","disconnected_clearly_better"]
    ).astype(str)
    tt=pd.to_datetime(df["current_utc_ms"],unit="ms",utc=True,errors="coerce")
    df["hour_of_week"]=(tt.dt.dayofweek*24+tt.dt.hour).astype("Int64").astype(str)
    df["month"]=df["event_month"].astype(str)
    return df

def add_primary_result(rows, used, term, label, mins, family):
    loss_rate=float(used.loc[used["prev_loss"]==1,"kind"].mean())
    win_rate=float(used.loc[
        (used["prev_loss"]==0)&(used["prev_draw"]==0),"kind"
    ].mean())
    row=[x for x in rows if x["term"]==term][0]
    row.update({
        "epistemic_label":label,
        "contrast":"loss_preceded_minus_win_preceded",
        "session_minutes":mins,
        "raw_loss_rate_pct":100*loss_rate,
        "raw_win_rate_pct":100*win_rate,
        "effect_relative_to_raw_win_mean_pct":
            100*row["effect_pp"]/(100*win_rate) if win_rate else None,
        "holm_adjusted_p_value":family,
    })
    return row

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--project-root",type=Path,default=PROJECT)
    ap.add_argument("--threads",type=int,default=8)
    ap.add_argument("--memory-limit",default="12GB")
    ap.add_argument("--execution-pointer",type=Path)
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()

    if args.self_test:
        self_test()
        return

    project=args.project_root
    repo=project/"replication_package"
    private=project/"derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    hist_root=private/"user_events"
    target_path=private/"stage07_sampled_targets_private.parquet"
    hist_receipt=private/"user_events_receipt.json"
    target_receipt=private/"stage07_sampled_targets_receipt.json"
    stage07=project/"derived/replication/analysis_panel_24m_sf100k"

    amd103=repo/"docs/dynamics_paper2_campaign1_analysis_plan_v1_0_3_amendment.md"
    chron_manifest=(project/"output/dynamic_prosociality_a3_chronology_gate_v100/"
                    "20260821T234626Z/chronology_input_manifest.tsv")
    prior_wave=project/"output/dynamics_campaign1_wave1_c1_c3_v100/20260825T015903Z"

    run_id=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    outbase=project/"output/dynamics_campaign1_c1_corrected_v105"
    existing_successes=[
        p for p in outbase.glob("*/_SUCCESS.json")
        if p.is_file()
    ] if outbase.exists() else []
    if existing_successes:
        raise RuntimeError(
            "A corrected C1 v1.0.5 success already exists; refusing an unauthorized "
            f"duplicate corrected primary: {existing_successes}"
        )
    staging=outbase/f".{run_id}.tmp.{os.getpid()}"
    final=outbase/run_id
    staging.mkdir(parents=True,exist_ok=False)
    tempdir=staging/"duckdb_tmp"
    started=time.time()

    try:
        print("C1_V105_CORRECTIVE_AUTHORITY_PREFLIGHT_BEGIN",flush=True)

        packaged_authorities,physical_decider=authenticate_packaged_c1_evidence()

        run(["git","fetch","origin","main","--quiet"],cwd=repo)
        head=run(["git","rev-parse","HEAD"],cwd=repo)
        remote=run(["git","rev-parse","origin/main"],cwd=repo)
        if head!=remote or head!=EXPECTED_GIT:
            raise RuntimeError(f"Git authority changed: local={head} remote={remote}")
        if run(["git","status","--porcelain"],cwd=repo):
            raise RuntimeError("Git worktree dirty")

        if sha256_file(amd103)!=EXPECTED_AMD103_SHA:
            raise RuntimeError("v1.0.3 session amendment SHA mismatch")

        pws=prior_wave/"_SUCCESS.json"
        pwsum=prior_wave/"summary.json"
        if not pws.is_file() or not pwsum.is_file():
            raise RuntimeError("Certified Wave1 result missing")
        js=json.loads(pws.read_text())
        if js.get("status")!="DYNAMICS_CAMPAIGN1_WAVE1_C1_C3_V100_OK":
            raise RuntimeError("Wave1 status mismatch")
        if js.get("c1_estimated") is not False:
            raise RuntimeError("Wave1 C1 pending-state authority changed")
        if sha256_file(pwsum)!=EXPECTED_WAVE1_SUMMARY_SHA:
            raise RuntimeError("Wave1 summary SHA mismatch")

        hr=json.loads(hist_receipt.read_text())
        tr=json.loads(target_receipt.read_text())
        if hr.get("status")!="DYNAMIC_SECOND_WAVE_USER_EVENTS_OK" or int(hr.get("rows",-1))!=EXPECTED_HISTORY_ROWS:
            raise RuntimeError("user_events receipt mismatch")
        if tr.get("status")!="DYNAMIC_SECOND_WAVE_STAGE07_SAMPLED_TARGETS_OK" or int(tr.get("rows",-1))!=EXPECTED_TARGET_ROWS:
            raise RuntimeError("sample target receipt mismatch")

        hist_paths=sorted(hist_root.rglob("*.parquet"))
        if total_rows(hist_paths)!=EXPECTED_HISTORY_ROWS:
            raise RuntimeError("user_events Parquet row authority mismatch")
        if parquet_rows(target_path)!=EXPECTED_TARGET_ROWS:
            raise RuntimeError("target Parquet row authority mismatch")

        s7_paths=sorted(
            p for p in stage07.rglob("*.parquet")
            if "_manifests" not in p.parts and not any(x.startswith(".") for x in p.parts)
        )
        month_paths=[p for p in s7_paths if any(x.startswith("month=") for x in p.parts)]
        if month_paths:
            s7_paths=month_paths
        if total_rows(s7_paths)!=EXPECTED_STAGE07_ROWS:
            raise RuntimeError("Stage07 row authority mismatch")

        cm=parse_chronology_manifest(chron_manifest)
        if len(cm)!=EXPECTED_CHRON_FILES or sum(x["rows"] for x in cm)!=EXPECTED_CHRON_ROWS:
            raise RuntimeError("Chronology manifest count authority mismatch")
        for x in cm:
            if not x["path"].is_file():
                raise RuntimeError(f"Chronology file missing: {x['path']}")

        con=wc.setup_duckdb(tempdir,args.threads,args.memory_limit)

        # Re-run the physical decider against the exact file before reading any current
        # kindness outcome. The packaged decider is a frozen record; this query binds
        # that record to the still-present physical bytes on this machine.
        physical_path=Path(physical_decider["physical_file"])
        if not physical_path.is_file():
            raise RuntimeError(f"Physical result-code decider file missing: {physical_path}")
        if int(physical_path.stat().st_size)!=int(physical_decider["file_size_bytes"]):
            raise RuntimeError("Physical result-code decider file size changed")
        if parquet_rows(physical_path)!=EXPECTED_PHYSICAL_TOTAL:
            raise RuntimeError("Physical result-code decider Parquet row count changed")
        physical_rows=con.execute(f"""
        SELECT CAST(result_code AS INTEGER) AS result_code,count(*)
        FROM read_parquet({wc.sqls(str(physical_path))})
        GROUP BY 1 ORDER BY 1
        """).fetchall()
        physical_counts={int(code):int(n) for code,n in physical_rows if code is not None}
        physical_nulls=sum(int(n) for code,n in physical_rows if code is None)
        physical_total=sum(int(n) for _,n in physical_rows)
        if (
            physical_counts!=EXPECTED_PHYSICAL_COUNTS or
            physical_nulls!=0 or
            physical_total!=EXPECTED_PHYSICAL_TOTAL
        ):
            raise RuntimeError(
                f"Physical result-code revalidation failed: counts={physical_counts} "
                f"nulls={physical_nulls} total={physical_total}"
            )
        physical_revalidation={
            "status":"C1_PHYSICAL_RESULT_CODE_REVALIDATED_V105",
            "physical_file":str(physical_path),
            "physical_file_size_bytes":physical_path.stat().st_size,
            "physical_file_rows":EXPECTED_PHYSICAL_TOTAL,
            "result_code_counts":{str(k):v for k,v in physical_counts.items()},
            "null_result_code_rows":physical_nulls,
            "decision_branch":"RAW_0_1_2",
            "performed_before_current_kindness_read":True,
        }
        (staging/"c1_physical_result_code_revalidation.json").write_text(
            json.dumps(physical_revalidation,indent=2,sort_keys=True)+"\n"
        )

        authority={
            "status":"C1_CHRONOLOGY_AUTHORITY_AUTHENTICATED_V105",
            "chronology_manifest":str(chron_manifest),
            "chronology_manifest_sha256":sha256_file(chron_manifest),
            "chronology_files":len(cm),
            "chronology_rows":sum(x["rows"] for x in cm),
            "historical_producer":packaged_authorities["historical_producer"],
            "physical_decider_json":packaged_authorities["physical_decider_json"],
            "physical_revalidation":physical_revalidation,
            "postoutcome_correction_v105":packaged_authorities["postoutcome_correction_v105"],
            "different_artifact_explicitly_rejected_as_semantic_authority":
                "replication_package/code/02_extract_rating_replay_inputs.py",
            "raw_result_code_semantics":{
                "2":"White win","1":"draw","0":"Black win"
            },
            "white_signed_decode":{"2":1,"1":0,"0":-1},
            "chooser_result_mapping":
                "decode raw code to White-signed result, then negate only for Black chooser",
            "rating_diff_used_to_infer_result":False,
            "rating_diff_used_for_validation_only":True,
        }
        (staging/"c1_chronology_authority.json").write_text(
            json.dumps(authority,indent=2,sort_keys=True)+"\n"
        )
        print("C1_CHRONOLOGY_AUTHORITY_AUTHENTICATED_V105_OK",flush=True)

        prior_output_inventory=scan_prior_c1_outputs(project)
        (staging/"c1_prior_output_inventory.json").write_text(
            json.dumps(prior_output_inventory,indent=2,sort_keys=True)+"\n"
        )

        invalidation={
            "status":"C1_PRIOR_LINEAGES_INVALIDATED_RESULT_CODE_SEMANTICS",
            "created_utc":now(),
            "physical_decision_branch":"RAW_0_1_2",
            "run_A_audit_lineage":{
                "reported_primary_effect_pp":0.245,
                "reported_mapping":
                    "raw result_code for White; negated raw result_code for Black; retain {-1,0,+1}",
                "classification":"INVALID_RESULT_CODE_SEMANTICS",
                "source_package_sha256":
                    "cb2798b1cfbc6e14dca222c932f29cf77cfe2589eb284056474adc6be55e9caa",
                "exact_artifact_present_in_corrective_collection":False,
                "fingerprint_autopsy_required_for_validity":False,
            },
            "run_B_production_lineage":{
                "primary_effect_pp":-0.8317125360007347,
                "resolved_primary_bridge_rows":217589,
                "regression_rows":108543,
                "resolved_streak_triples":112725,
                "direct_loss_or_win_streak_rows":2,
                "classification":"INVALID_RESULT_CODE_SEMANTICS",
            },
            "mechanism":{
                "true_white_wins_raw_2":"mapped to +/-2 and filtered out",
                "true_draws_raw_1":"mislabeled as chooser win/loss according to color",
                "true_black_wins_raw_0":"mislabeled as draw",
            },
            "old_outputs_mutated":False,
            "invalid_results_enter_holm":False,
            "corrected_rebuild_authorized_by":
                "v1.0.5 post-outcome technical correction",
            "packaged_prior_evidence":{
                k:v for k,v in packaged_authorities.items() if k.startswith("prior_")
            },
            "machine_prior_output_inventory":prior_output_inventory,
        }
        (staging/"c1_prior_lineages_invalidation.json").write_text(
            json.dumps(invalidation,indent=2,sort_keys=True)+"\n"
        )

        hist_sql="["+",".join(wc.sqls(str(p)) for p in hist_paths)+"]"

        # Target keys and users — no kindness read.
        con.execute(f"""
        CREATE TEMP TABLE sample_keys AS
        SELECT DISTINCT
          CAST(chooser_user_id AS BIGINT) AS chooser_key,
          CAST(game_id AS VARCHAR) AS game_id
        FROM read_parquet({wc.sqls(str(target_path))})
        WHERE coalesce(CAST(user_sample AS BOOLEAN),FALSE)
          AND CAST(eval_cp AS DOUBLE)>=-100
          AND chooser_user_id IS NOT NULL
          AND game_id IS NOT NULL
        """)
        nk=con.execute("SELECT count(*) FROM sample_keys").fetchone()[0]
        if int(nk)!=EXPECTED_USER_TARGETS:
            raise RuntimeError(f"user-sample target keys changed: {nk}")
        con.execute("CREATE TEMP TABLE sample_users AS SELECT DISTINCT chooser_key FROM sample_keys")

        # C1 only needs local lags, not users' entire lifetime histories.
        print("C1_LOCAL_LAG_BUILD_BEGIN",flush=True)
        con.execute(f"""
        CREATE TEMP TABLE c1_lags AS
        WITH h AS (
          SELECT
            CAST(u.user_id AS BIGINT) AS chooser_key,
            CAST(u.game_id AS VARCHAR) AS game_id,
            CAST(u.utc_ms AS BIGINT) AS start_ms,
            CAST(u.speed AS VARCHAR) AS speed,
            lag(CAST(u.game_id AS VARCHAR),1) OVER w AS pg1,
            lag(CAST(u.game_id AS VARCHAR),2) OVER w AS pg2,
            lag(CAST(u.game_id AS VARCHAR),3) OVER w AS pg3,
            lag(CAST(u.utc_ms AS BIGINT),1) OVER w AS pt1,
            lag(CAST(u.utc_ms AS BIGINT),2) OVER w AS pt2,
            lag(CAST(u.utc_ms AS BIGINT),3) OVER w AS pt3,
            lag(CAST(u.speed AS VARCHAR),1) OVER w AS ps1,
            lag(CAST(u.speed AS VARCHAR),2) OVER w AS ps2,
            lag(CAST(u.speed AS VARCHAR),3) OVER w AS ps3
          FROM read_parquet({hist_sql},union_by_name=true) u
          INNER JOIN sample_users su
            ON CAST(u.user_id AS BIGINT)=su.chooser_key
          WHERE CAST(u.utc_ms AS BIGINT)>={HISTORY_LEFT_MS}
            AND CAST(u.utc_ms AS BIGINT)<{CAMPAIGN_END_MS}
          WINDOW w AS (
            PARTITION BY CAST(u.user_id AS BIGINT)
            ORDER BY CAST(u.utc_ms AS BIGINT), CAST(u.game_id AS VARCHAR)
          )
        )
        SELECT
          h.*,
          start_ms-pt1 AS gap1_ms,
          pt1-pt2 AS gap2_ms,
          pt2-pt3 AS gap3_ms
        FROM h
        INNER JOIN sample_keys k USING(chooser_key,game_id)
        """)
        nl=con.execute("SELECT count(*) FROM c1_lags").fetchone()[0]
        if int(nl)!=EXPECTED_USER_TARGETS:
            raise RuntimeError(f"C1 local lag target match changed: {nl}")
        print("C1_LOCAL_LAG_BUILD_OK",flush=True)

        # Pre-outcome support and needed results. Lag1 needed for 60m sensitivity.
        # Lag2/3 needed only when all three preceding games can form a valid 30m streak.
        support=con.execute("""
        SELECT
          count(*) FILTER (WHERE gap1_ms>=0 AND gap1_ms<15*60*1000) eligible15,
          count(*) FILTER (WHERE gap1_ms>=0 AND gap1_ms<30*60*1000) eligible30,
          count(*) FILTER (WHERE gap1_ms>=0 AND gap1_ms<60*60*1000) eligible60,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<30*60*1000
              AND gap2_ms>=0 AND gap2_ms<30*60*1000
              AND gap3_ms>=0 AND gap3_ms<30*60*1000
          ) eligible_streak3
        FROM c1_lags
        """).fetchone()
        support_obj={
            "status":"C1_SESSION_SUPPORT_FROZEN_BEFORE_RESULT_OUTCOME_TABULATION",
            "session_timestamp_mode":"start_to_start_v1_0_3_fallback",
            "history_left_buffer_hours":2,
            "eligible15":int(support[0]),
            "eligible30":int(support[1]),
            "eligible60":int(support[2]),
            "eligible_three_prior_games_same_30m_session":int(support[3]),
            "kindness_by_prior_result_tabulated":False,
        }
        (staging/"c1_session_support_frozen.json").write_text(
            json.dumps(support_obj,indent=2,sort_keys=True)+"\n"
        )
        print("C1_SESSION_SUPPORT_FROZEN_OK",flush=True)

        con.execute("""
        CREATE TEMP TABLE needed_results AS
        SELECT DISTINCT
          chooser_key, pg1 AS game_id,
          strftime(to_timestamp(pt1/1000.0),'%Y-%m') AS event_month,
          ps1 AS speed
        FROM c1_lags
        WHERE pg1 IS NOT NULL
          AND gap1_ms>=0 AND gap1_ms<60*60*1000

        UNION

        SELECT DISTINCT
          chooser_key, pg2,
          strftime(to_timestamp(pt2/1000.0),'%Y-%m'),
          ps2
        FROM c1_lags
        WHERE pg2 IS NOT NULL
          AND gap1_ms>=0 AND gap1_ms<30*60*1000
          AND gap2_ms>=0 AND gap2_ms<30*60*1000
          AND gap3_ms>=0 AND gap3_ms<30*60*1000

        UNION

        SELECT DISTINCT
          chooser_key, pg3,
          strftime(to_timestamp(pt3/1000.0),'%Y-%m'),
          ps3
        FROM c1_lags
        WHERE pg3 IS NOT NULL
          AND gap1_ms>=0 AND gap1_ms<30*60*1000
          AND gap2_ms>=0 AND gap2_ms<30*60*1000
          AND gap3_ms>=0 AND gap3_ms<30*60*1000
        """)
        badmonths=con.execute("""
        SELECT event_month,count(*)
        FROM needed_results
        WHERE event_month<'2023-10' OR event_month>'2025-10'
        GROUP BY 1 ORDER BY 1
        """).fetchall()
        if badmonths:
            raise RuntimeError(f"C1 needed-result month invariant failed: {badmonths}")

        groups=con.execute("""
        SELECT event_month,speed,count(*) n
        FROM needed_results
        GROUP BY 1,2
        ORDER BY 1,2
        """).fetchall()
        chosen=relevant_chronology_paths(cm,groups)
        if str(physical_path) not in {str(x["path"]) for x in chosen}:
            raise RuntimeError(
                "The exact physical decider partition is absent from the C1 result "
                "source set; artifact binding cannot be established"
            )
        # Authenticate only files actually read against the certified manifest.
        for x in chosen:
            st=x["path"].stat()
            if int(st.st_size)!=int(x["bytes"]):
                raise RuntimeError(f"Chronology source size mismatch: {x['path']}")
            if parquet_rows(x["path"])!=int(x["rows"]):
                raise RuntimeError(f"Chronology source row mismatch: {x['path']}")

        source_report={
            "status":"C1_RESULT_SOURCE_SET_FROZEN_BEFORE_KINDNESS_BY_RESULT",
            "needed_result_rows":int(con.execute(
                "SELECT count(*) FROM needed_results").fetchone()[0]),
            "needed_month_min":min(str(x[0]) for x in groups) if groups else None,
            "needed_month_max":max(str(x[0]) for x in groups) if groups else None,
            "needed_month_speed_groups":len(groups),
            "chronology_files_selected":len(chosen),
            "chronology_rows_selected_metadata":sum(x["rows"] for x in chosen),
            "physical_decider_partition_in_selected_source_set":True,
            "partitions":[
                {"month":str(m),"speed":str(s),"needed_rows":int(n)}
                for m,s,n in groups
            ],
            "kindness_by_prior_result_tabulated":False,
        }
        (staging/"c1_result_source_set.json").write_text(
            json.dumps(source_report,indent=2,sort_keys=True)+"\n"
        )
        print(
            f"C1_RESULT_SOURCE_SET_FROZEN_OK files={len(chosen)} "
            f"metadata_rows={sum(x['rows'] for x in chosen):,}",
            flush=True
        )

        # Actual authoritative result bridge. Raw result code is game-level. Decode
        # 0/1/2 to White-signed {-1,0,+1} before applying chooser side.
        print("C1_RESULT_BRIDGE_BUILD_BEGIN",flush=True)
        chron_sql="["+",".join(wc.sqls(str(x["path"])) for x in chosen)+"]"
        white_sign=raw_to_white_result_sql("c.result_code")
        result_sign=relative_result_sql()
        chooser_rating_diff=chooser_rating_diff_sql()
        con.execute(f"""
        CREATE TEMP TABLE result_bridge AS
        SELECT
          n.chooser_key,
          n.game_id,
          n.event_month,
          n.speed,
          CAST(c.result_code AS INTEGER) AS raw_result_code,
          {white_sign} AS white_result_sign,
          {result_sign} AS result_sign,
          {chooser_rating_diff} AS chooser_rating_diff
        FROM needed_results n
        INNER JOIN read_parquet(
          {chron_sql},
          union_by_name=true,
          hive_partitioning=true
        ) c
          ON CAST(c.game_id AS VARCHAR)=n.game_id
         AND CAST(c.month AS VARCHAR)=n.event_month
         AND CAST(c.speed AS VARCHAR)=n.speed
        """)
        dup=con.execute("""
        SELECT count(*) FROM (
          SELECT chooser_key,game_id,count(*) n
          FROM result_bridge
          GROUP BY 1,2 HAVING count(*)>1
        )
        """).fetchone()[0]
        if int(dup)!=0:
            raise RuntimeError(f"C1 result bridge duplicate chooser-game keys: {dup}")

        needed_n=int(con.execute("SELECT count(*) FROM needed_results").fetchone()[0])
        bridge_n=int(con.execute("SELECT count(*) FROM result_bridge").fetchone()[0])
        bridge_invalid=con.execute("""
        SELECT
          count(*) FILTER (WHERE raw_result_code NOT IN (0,1,2)) AS invalid_raw_code,
          count(*) FILTER (WHERE white_result_sign IS NULL) AS null_white_decode,
          count(*) FILTER (WHERE result_sign IS NULL) AS null_result_or_side,
          count(*) FILTER (WHERE result_sign NOT IN (-1,0,1)) AS invalid_chooser_sign
        FROM result_bridge
        """).fetchone()
        if any(int(x)!=0 for x in bridge_invalid):
            raise RuntimeError(
                "C1 result bridge invalid code/side rows: "
                f"invalid_raw={bridge_invalid[0]} null_white={bridge_invalid[1]} "
                f"null_side={bridge_invalid[2]} invalid_sign={bridge_invalid[3]}"
            )
        if bridge_n>needed_n:
            raise RuntimeError(f"C1 result bridge exceeds needed rows: {bridge_n}>{needed_n}")

        raw_counts=con.execute("""
        SELECT raw_result_code,count(*) AS rows
        FROM result_bridge
        GROUP BY 1 ORDER BY 1
        """).fetchall()
        chooser_counts=con.execute("""
        SELECT result_sign,count(*) AS rows
        FROM result_bridge
        GROUP BY 1 ORDER BY 1
        """).fetchall()
        if sum(int(n) for _,n in raw_counts)!=bridge_n:
            raise RuntimeError("C1 raw-code bridge row conservation failed")
        if sum(int(n) for _,n in chooser_counts)!=bridge_n:
            raise RuntimeError("C1 chooser-result bridge row conservation failed")
        if {int(code) for code,_ in raw_counts}!={0,1,2}:
            raise RuntimeError(f"C1 bridge raw support is not exactly 0/1/2: {raw_counts}")
        if {int(code) for code,_ in chooser_counts}!={-1,0,1}:
            raise RuntimeError(f"C1 bridge chooser support is not exactly -1/0/1: {chooser_counts}")

        raw_count_map={int(k):int(v) for k,v in raw_counts}
        chooser_count_map={int(k):int(v) for k,v in chooser_counts}
        raw_draw_share=raw_count_map[1]/bridge_n
        chooser_draw_share=chooser_count_map[0]/bridge_n
        for label,share in (
            ("raw_white_win",raw_count_map[2]/bridge_n),
            ("raw_black_win",raw_count_map[0]/bridge_n),
            ("chooser_win",chooser_count_map[1]/bridge_n),
            ("chooser_loss",chooser_count_map[-1]/bridge_n),
        ):
            if not 0.30<share<0.65:
                raise RuntimeError(f"C1 decoded decisive marginal is implausible: {label}={share}")
        if not 0.005<raw_draw_share<0.20 or not 0.005<chooser_draw_share<0.20:
            raise RuntimeError(
                f"C1 decoded draw marginal is implausible: raw={raw_draw_share} "
                f"chooser={chooser_draw_share}"
            )

        perspective=con.execute("""
        SELECT
          count(*) FILTER (WHERE result_sign<>0) AS decisive_rows,
          count(*) FILTER (
            WHERE result_sign<>0 AND chooser_rating_diff IS NOT NULL
          ) AS decisive_rating_diff_nonnull,
          count(*) FILTER (
            WHERE result_sign<>0 AND chooser_rating_diff=0
          ) AS decisive_rating_diff_zero,
          count(*) FILTER (
            WHERE result_sign<>0 AND chooser_rating_diff<>0
          ) AS decisive_rating_diff_nonzero,
          count(*) FILTER (
            WHERE (result_sign=1 AND chooser_rating_diff>0)
               OR (result_sign=-1 AND chooser_rating_diff<0)
          ) AS decisive_sign_aligned,
          count(*) FILTER (
            WHERE (result_sign=1 AND chooser_rating_diff<0)
               OR (result_sign=-1 AND chooser_rating_diff>0)
          ) AS decisive_sign_contradictory
        FROM result_bridge
        """).fetchone()
        nonzero=int(perspective[3])
        aligned=int(perspective[4])
        alignment_share=aligned/nonzero if nonzero else None
        if alignment_share is None or alignment_share<MIN_DECISIVE_RATING_SIGN_ALIGNMENT:
            raise RuntimeError(
                f"C1 chooser-perspective rating-diff validation failed: {alignment_share}"
            )
        perspective_report={
            "status":"C1_CHOOSER_PERSPECTIVE_VALIDATION_OK",
            "result_constructed_from_rating_diff":False,
            "rating_diff_validation_only":True,
            "decisive_rows":int(perspective[0]),
            "decisive_rating_diff_nonnull":int(perspective[1]),
            "decisive_rating_diff_zero":int(perspective[2]),
            "decisive_rating_diff_nonzero":nonzero,
            "decisive_sign_aligned":aligned,
            "decisive_sign_contradictory":int(perspective[5]),
            "alignment_share_among_nonzero":alignment_share,
            "minimum_alignment_share":MIN_DECISIVE_RATING_SIGN_ALIGNMENT,
        }
        (staging/"c1_chooser_perspective_validation.json").write_text(
            json.dumps(perspective_report,indent=2,sort_keys=True)+"\n"
        )

        marginals=con.execute("""
        SELECT
          'ALL' AS speed,
          count(*) AS bridge_rows,
          count(*) FILTER (WHERE raw_result_code=0) AS raw_0_black_win,
          count(*) FILTER (WHERE raw_result_code=1) AS raw_1_draw,
          count(*) FILTER (WHERE raw_result_code=2) AS raw_2_white_win,
          count(*) FILTER (WHERE result_sign=-1) AS chooser_loss,
          count(*) FILTER (WHERE result_sign=0) AS chooser_draw,
          count(*) FILTER (WHERE result_sign=1) AS chooser_win
        FROM result_bridge
        UNION ALL
        SELECT
          speed,
          count(*),
          count(*) FILTER (WHERE raw_result_code=0),
          count(*) FILTER (WHERE raw_result_code=1),
          count(*) FILTER (WHERE raw_result_code=2),
          count(*) FILTER (WHERE result_sign=-1),
          count(*) FILTER (WHERE result_sign=0),
          count(*) FILTER (WHERE result_sign=1)
        FROM result_bridge
        GROUP BY speed
        ORDER BY speed
        """).fetchdf()
        for col in (
            "raw_0_black_win","raw_1_draw","raw_2_white_win",
            "chooser_loss","chooser_draw","chooser_win",
        ):
            marginals[col+"_share"]=marginals[col]/marginals["bridge_rows"]
        marginals.to_csv(staging/"c1_result_marginals_overall_by_speed.csv",index=False)

        bridge_validation={
            "status":"C1_RESULT_BRIDGE_DECODE_AND_ROW_CONSERVATION_OK",
            "needed_result_rows":needed_n,
            "resolved_bridge_rows":bridge_n,
            "unresolved_needed_rows":needed_n-bridge_n,
            "raw_result_code_counts":{str(k):v for k,v in raw_count_map.items()},
            "chooser_result_counts":{str(k):v for k,v in chooser_count_map.items()},
            "raw_support":[0,1,2],
            "chooser_support":[-1,0,1],
            "decoder":"2->+1, 1->0, 0->-1 White-signed; negate for Black chooser",
            "row_conservation_pass":True,
            "perspective_validation":perspective_report,
            "kindness_by_prior_result_tabulated":False,
        }
        (staging/"c1_result_bridge_validation.json").write_text(
            json.dumps(bridge_validation,indent=2,sort_keys=True)+"\n"
        )
        print(
            f"C1_RESULT_BRIDGE_BUILD_OK rows={bridge_n:,} "
            f"raw_counts={raw_count_map} chooser_counts={chooser_count_map}",
            flush=True,
        )

        # Attach the three preceding results to target rows, still without kindness.
        con.execute("""
        CREATE TEMP TABLE lag_results AS
        SELECT
          l.*,
          r1.result_sign AS prev_result_1,
          r2.result_sign AS prev_result_2,
          r3.result_sign AS prev_result_3
        FROM c1_lags l
        LEFT JOIN result_bridge r1
          ON r1.chooser_key=l.chooser_key AND r1.game_id=l.pg1
        LEFT JOIN result_bridge r2
          ON r2.chooser_key=l.chooser_key AND r2.game_id=l.pg2
        LEFT JOIN result_bridge r3
          ON r3.chooser_key=l.chooser_key AND r3.game_id=l.pg3
        """)

        cov=con.execute("""
        SELECT
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<15*60*1000
          ) AS e15,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<15*60*1000
              AND prev_result_1 IS NOT NULL
          ) AS r15,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<30*60*1000
          ) AS e30,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<30*60*1000
              AND prev_result_1 IS NOT NULL
          ) AS r30,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<60*60*1000
          ) AS e60,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<60*60*1000
              AND prev_result_1 IS NOT NULL
          ) AS r60,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<30*60*1000
              AND gap2_ms>=0 AND gap2_ms<30*60*1000
              AND gap3_ms>=0 AND gap3_ms<30*60*1000
          ) AS es,
          count(*) FILTER (
            WHERE gap1_ms>=0 AND gap1_ms<30*60*1000
              AND gap2_ms>=0 AND gap2_ms<30*60*1000
              AND gap3_ms>=0 AND gap3_ms<30*60*1000
              AND prev_result_1 IS NOT NULL
              AND prev_result_2 IS NOT NULL
              AND prev_result_3 IS NOT NULL
          ) AS rs
        FROM lag_results
        """).fetchone()
        coverage={
            "status":"C1_RESULT_BRIDGE_COVERAGE_FROZEN_BEFORE_KINDNESS_BY_RESULT",
            "minimum_resolution_share":MIN_PRIMARY_COVERAGE_SHARE,
            "session_15":{
                "eligible":int(cov[0]),"resolved":int(cov[1]),
                "resolved_share":float(cov[1]/cov[0]) if cov[0] else None,
            },
            "session_30_primary":{
                "eligible":int(cov[2]),"resolved":int(cov[3]),
                "resolved_share":float(cov[3]/cov[2]) if cov[2] else None,
            },
            "session_60":{
                "eligible":int(cov[4]),"resolved":int(cov[5]),
                "resolved_share":float(cov[5]/cov[4]) if cov[4] else None,
            },
            "streak3":{
                "eligible":int(cov[6]),"resolved_all_three":int(cov[7]),
                "resolved_share":float(cov[7]/cov[6]) if cov[6] else None,
            },
            "rating_diff_used_to_infer_result":False,
            "raw_result_code_decoder":"2->+1, 1->0, 0->-1 White-signed",
            "bridge_validation":bridge_validation,
            "kindness_by_prior_result_tabulated":False,
        }
        (staging/"c1_result_bridge_coverage.json").write_text(
            json.dumps(coverage,indent=2,sort_keys=True)+"\n"
        )
        for key in ("session_15","session_30_primary","session_60","streak3"):
            sh=coverage[key]["resolved_share"]
            if sh is None or sh<MIN_PRIMARY_COVERAGE_SHARE:
                raise RuntimeError(
                    f"C1 result coverage below {MIN_PRIMARY_COVERAGE_SHARE:.0%} "
                    f"for {key}: {sh}"
                )
        print("C1_RESULT_BRIDGE_COVERAGE_FROZEN_OK",flush=True)

        # Only now read the kindness outcome and estimate C1.
        print("C1_CONFIRMATORY_OUTCOME_ESTIMATION_BEGIN",flush=True)
        make_current_targets(con,s7_paths,target_path)
        df=con.execute("""
        SELECT
          c.*,
          l.ps1 AS prev_speed,
          l.gap1_ms,l.gap2_ms,l.gap3_ms,
          l.prev_result_1,l.prev_result_2,l.prev_result_3
        FROM current_targets c
        INNER JOIN lag_results l USING(chooser_key,game_id)
        """).fetchdf()
        df=prepare_model_frame(df)

        output=[]
        estimation_conservation=[]
        for mins in (30,15,60):
            lim=mins*60*1000
            s=df[
                (df["gap1_ms"]>=0)&(df["gap1_ms"]<lim)&
                df["prev_result_1"].isin([-1,0,1])
            ].copy()
            s["prev_loss"]=(s["prev_result_1"]==-1).astype(float)
            s["prev_draw"]=(s["prev_result_1"]==0).astype(float)
            res,used=wc.fit_fe_cluster(
                s,["prev_loss","prev_draw"],label=f"C1_{mins}min"
            )
            row=add_primary_result(
                res,used,"prev_loss",
                "C" if mins==30 else "C_sensitivity",
                mins,
                "PENDING_FULL_FIVE_MEMBER_FAMILY"
                if mins==30 else "NOT_A_FAMILY_MEMBER_SENSITIVITY"
            )
            preservation=float(len(used)/len(s)) if len(s) else None
            row.update({
                "decoded_rows_before_complete_case_filter":int(len(s)),
                "complete_case_preservation_share":preservation,
            })
            output.append(row)
            estimation_conservation.append({
                "specification":f"session_{mins}",
                "decoded_rows_before_complete_case_filter":int(len(s)),
                "complete_case_rows":int(len(used)),
                "complete_case_preservation_share":preservation,
            })
            if mins==30 and (
                preservation is None or
                preservation<MIN_PRIMARY_ESTIMATION_PRESERVATION_SHARE
            ):
                raise RuntimeError(
                    "Corrected C1 primary lost too many decoded bridge rows after "
                    f"complete-case filtering: {preservation}"
                )

        # Same-pool sensitivity at the frozen 30m session.
        s=df[
            (df["gap1_ms"]>=0)&(df["gap1_ms"]<30*60*1000)&
            df["prev_result_1"].isin([-1,0,1])&
            (df["prev_speed"].astype(str)==df["speed"].astype(str))
        ].copy()
        s["prev_loss"]=(s["prev_result_1"]==-1).astype(float)
        s["prev_draw"]=(s["prev_result_1"]==0).astype(float)
        res,used=wc.fit_fe_cluster(
            s,["prev_loss","prev_draw"],label="C1_30min_same_pool"
        )
        same_pool_row=add_primary_result(
            res,used,"prev_loss","C_sensitivity",30,
            "NOT_A_FAMILY_MEMBER_SENSITIVITY"
        )
        same_pool_preservation=float(len(used)/len(s)) if len(s) else None
        same_pool_row.update({
            "decoded_rows_before_complete_case_filter":int(len(s)),
            "complete_case_preservation_share":same_pool_preservation,
        })
        output.append(same_pool_row)
        estimation_conservation.append({
            "specification":"session_30_same_pool",
            "decoded_rows_before_complete_case_filter":int(len(s)),
            "complete_case_rows":int(len(used)),
            "complete_case_preservation_share":same_pool_preservation,
        })
        wc.write_csv(staging/"c1_prior_result_state_dependence.csv",output)

        # Prespecified secondary: >=3 consecutive losses versus >=3 consecutive wins.
        st=df[
            (df["gap1_ms"]>=0)&(df["gap1_ms"]<30*60*1000)&
            (df["gap2_ms"]>=0)&(df["gap2_ms"]<30*60*1000)&
            (df["gap3_ms"]>=0)&(df["gap3_ms"]<30*60*1000)&
            df["prev_result_1"].isin([-1,0,1])&
            df["prev_result_2"].isin([-1,0,1])&
            df["prev_result_3"].isin([-1,0,1])
        ].copy()
        st["loss_streak3"]=(
            (st["prev_result_1"]==-1)&
            (st["prev_result_2"]==-1)&
            (st["prev_result_3"]==-1)
        )
        st["win_streak3"]=(
            (st["prev_result_1"]==1)&
            (st["prev_result_2"]==1)&
            (st["prev_result_3"]==1)
        )
        direct=st[st["loss_streak3"]|st["win_streak3"]].copy()
        direct["loss_streak3_vs_win"]=(direct["loss_streak3"]).astype(float)
        secondary_status={
            "status":"PENDING",
            "epistemic_label":"S",
            "contrast":"three_or_more_consecutive_losses_minus_three_or_more_consecutive_wins",
            "candidate_rows_before_complete_case_filter":int(len(direct)),
            "candidate_loss_streak_rows":int(direct["loss_streak3_vs_win"].sum()),
            "candidate_win_streak_rows":int(
                len(direct)-direct["loss_streak3_vs_win"].sum()
            ),
            "candidate_choosers":int(direct["chooser_key"].nunique()),
            "minimum_complete_case_rows_for_frozen_FE_producer":1000,
            "minimum_sane_direct_candidates":MIN_STREAK_DIRECT_CANDIDATES,
            "minimum_sane_candidates_per_arm":MIN_STREAK_CANDIDATES_PER_ARM,
        }
        if (
            secondary_status["candidate_rows_before_complete_case_filter"]
                < MIN_STREAK_DIRECT_CANDIDATES or
            secondary_status["candidate_loss_streak_rows"]
                < MIN_STREAK_CANDIDATES_PER_ARM or
            secondary_status["candidate_win_streak_rows"]
                < MIN_STREAK_CANDIDATES_PER_ARM
        ):
            raise RuntimeError(
                "Corrected C1 streak-support sanity gate failed: "
                f"{secondary_status}"
            )
        secondary_status["streak_support_sanity_gate"]="PASS"
        try:
            sr,sused=wc.fit_fe_cluster(
                direct,["loss_streak3_vs_win"],
                label="C1_secondary_streak3_loss_minus_win"
            )
            srow=sr[0]
            lossrate=float(
                sused.loc[sused["loss_streak3_vs_win"]==1,"kind"].mean()
            )
            winrate=float(
                sused.loc[sused["loss_streak3_vs_win"]==0,"kind"].mean()
            )
            srow.update({
                "epistemic_label":"S",
                "contrast":"three_or_more_consecutive_losses_minus_three_or_more_consecutive_wins",
                "raw_loss_streak_rate_pct":100*lossrate,
                "raw_win_streak_rate_pct":100*winrate,
                "effect_relative_to_raw_win_streak_mean_pct":
                    100*srow["effect_pp"]/(100*winrate) if winrate else None,
            })
            wc.write_csv(staging/"c1_secondary_streak3.csv",[srow])
            secondary_status.update({
                "status":"ESTIMATED",
                "complete_case_rows":int(srow["rows"]),
                "complete_case_preservation_share":
                    float(len(sused)/len(direct)) if len(direct) else None,
                "chooser_clusters":int(srow["chooser_clusters"]),
                "output":"c1_secondary_streak3.csv",
            })
        except RuntimeError as exc:
            # This is a SECONDARY/SUPPORT issue only. The frozen C1 primary has
            # already been estimated under its unchanged specification and must not
            # be discarded merely because the prespecified streak comparison is too
            # thin for the generic >=1000-row FE producer.
            if "fewer than 1000 complete-case rows" not in str(exc):
                raise
            secondary_status.update({
                "status":"NOT_ESTIMATED_INSUFFICIENT_COMPLETE_CASE_SUPPORT",
                "reason":str(exc),
                "output":None,
                "primary_C1_affected":False,
            })
        (staging/"c1_secondary_streak3_STATUS.json").write_text(
            json.dumps(secondary_status,indent=2,sort_keys=True)+"\n"
        )
        primary_row=next(x for x in output if x["model"]=="C1_30min")
        estimation_validation={
            "status":"C1_CORRECTED_ESTIMATION_ROW_CONSERVATION_OK",
            "minimum_primary_complete_case_preservation_share":
                MIN_PRIMARY_ESTIMATION_PRESERVATION_SHARE,
            "specifications":estimation_conservation,
            "primary_decoded_rows":
                int(primary_row["decoded_rows_before_complete_case_filter"]),
            "primary_complete_case_rows":int(primary_row["rows"]),
            "primary_complete_case_preservation_share":
                float(primary_row["complete_case_preservation_share"]),
            "prior_invalid_run_B_complete_case_rows":108543,
            "prior_invalid_run_B_not_used":True,
            "secondary_streak3":secondary_status,
        }
        (staging/"c1_estimation_row_conservation.json").write_text(
            json.dumps(estimation_validation,indent=2,sort_keys=True)+"\n"
        )

        summary={
            "status":"DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_OK",
            "created_utc":now(),
            "git_head":head,
            "producer_source":{
                "path":str(Path(__file__).resolve()),
                "sha256":sha256_file(Path(__file__).resolve()),
                "wave1_common_sha256":sha256_file(Path(wc.__file__).resolve()),
            },
            "prior_wave1_summary_sha256":EXPECTED_WAVE1_SUMMARY_SHA,
            "session_timestamp_mode":"start_to_start_v1_0_3_fallback",
            "chronology_authority":authority,
            "prior_lineages_invalidation":invalidation,
            "physical_result_code_revalidation":physical_revalidation,
            "session_support":support_obj,
            "result_source_set":source_report,
            "result_bridge_validation":bridge_validation,
            "result_bridge_coverage":coverage,
            "estimation_row_conservation":estimation_validation,
            "C1":{
                "status":"ESTIMATED",
                "epistemic_label":"C",
                "primary":"30-minute loss-preceded minus win-preceded chooser-FE contrast",
                "primary_output":"c1_prior_result_state_dependence.csv",
                "secondary_status":secondary_status,
                "secondary_output":(
                    "c1_secondary_streak3.csv"
                    if secondary_status["status"]=="ESTIMATED"
                    else None
                ),
            },
            "holm_family_note":
                "Corrected C1 and prior C2 raw p-values are available. Invalid C1 "
                "lineages are excluded. Holm adjustment remains pending family completion.",
            "account_level_output":False,
            "persistent_private_cache_mutation":False,
            "api_requests":0,
            "patron_status_read":False,
            "runtime_seconds":time.time()-started,
        }
        (staging/"summary.json").write_text(
            json.dumps(summary,indent=2,sort_keys=True)+"\n"
        )

        hashes=[]
        for p in sorted(staging.iterdir()):
            if p.is_file() and p.name not in {"_SUCCESS.json","report_file_hashes.csv"}:
                hashes.append({
                    "sha256":sha256_file(p),
                    "bytes":p.stat().st_size,
                    "file":p.name,
                })
        wc.write_csv(staging/"report_file_hashes.csv",hashes)
        success={
            "status":"DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_OK",
            "created_utc":summary["created_utc"],
            "git_head":head,
            "summary_sha256":sha256_file(staging/"summary.json"),
            "report_file_hashes_sha256":sha256_file(staging/"report_file_hashes.csv"),
            "c1_estimated":True,
            "prior_c1_lineages_invalidated":True,
            "raw_result_code_semantics":"0/1/2 decoded explicitly",
            "physical_decider_revalidated":True,
            "holm_family_adjustment_complete":False,
            "account_level_output":False,
        }
        (staging/"_SUCCESS.json").write_text(
            json.dumps(success,indent=2,sort_keys=True)+"\n"
        )

        if tempdir.exists():
            shutil.rmtree(tempdir,ignore_errors=True)
        os.replace(staging,final)
        write_execution_pointer(args.execution_pointer,{
            "status":"DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_OK",
            "result_root":str(final),
            "success_sha256":sha256_file(final/"_SUCCESS.json"),
        })
        print(f"DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_OK: {final}",flush=True)
        print(f"runtime_seconds: {time.time()-started:.1f}",flush=True)

    except Exception as exc:
        diag={
            "status":"DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_FAIL_CLOSED",
            "created_utc":now(),
            "error":f"{type(exc).__name__}: {exc}",
            "account_level_output":False,
        }
        try:
            (staging/"FAILURE_DIAGNOSTIC.json").write_text(
                json.dumps(diag,indent=2)+"\n"
            )
            if tempdir.exists():
                shutil.rmtree(tempdir,ignore_errors=True)
            fail=outbase/f"{run_id}_FAILED"
            if fail.exists():
                shutil.rmtree(fail)
            os.replace(staging,fail)
            write_execution_pointer(args.execution_pointer,{
                "status":"DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_FAIL_CLOSED",
                "result_root":str(fail),
                "failure_diagnostic_sha256":sha256_file(fail/"FAILURE_DIAGNOSTIC.json"),
            })
            print(f"Failure root: {fail}",file=sys.stderr,flush=True)
        except Exception:
            pass
        raise

if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"DYNAMICS_CAMPAIGN1_C1_CORRECTED_V105_FAIL_CLOSED: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,flush=True
        )
        raise
