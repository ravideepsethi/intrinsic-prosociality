#!/usr/bin/env python3
"""Estimate the highest-priority Patron families with explicit missing outcomes."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import math
import os
import platform
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
import patron_stage10_common as common
from source import cache_builder_v101 as builder
from source import chooser_models_v101 as models
from source import pool_sample_common_v100 as auth
from source import wave3a_design as prior

VERSION = "3B1-1.0.1"
WAVE3A_ZIP_SHA = "f56407f3de5bdd02366df28858e689da5f10a05c657f6c5e2feb71a7e227a592"
WAVE3A_CONFIG = "f9dfa2718056083161d58175b5907e1a8b2dfbbc58a1244c45c878c78c3bd238"
q = common.sql_string
log = prior.log
records = prior.records
eq = prior.require_equal
PROFILE_FEATURES = ["queried_at_utc", "title", "disabled", "tos_violation", "created_at_ms",
    "seen_at_ms", "play_time_total_seconds", "count_all", "count_rated", "count_win",
    "count_loss", "count_draw", "perfs_json"]


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def save_json(path, value):
    auth.atomic_json(path, clean(value))


def get_wave3a_authority():
    path = ROOT / "evidence/WAVE3A_RESULTS.zip"
    eq(auth.sha256_file(path), WAVE3A_ZIP_SHA, "Wave-3A report ZIP")
    with zipfile.ZipFile(path) as archive:
        eq(archive.testzip(), None, "Wave-3A CRC")
        manifest = next(n for n in archive.namelist() if n.endswith("/REPORT_FILE_HASHES.tsv"))
        prefix = manifest.rsplit("/", 1)[0] + "/"
        rows = list(csv.DictReader(io.StringIO(archive.read(manifest).decode()), delimiter="\t"))
        for row in rows:
            data = archive.read(prefix + row["relative_path"])
            eq(len(data), int(row["bytes"]), "Wave-3A report bytes")
            eq(hashlib.sha256(data).hexdigest(), row["sha256"], "Wave-3A report member")
        status = json.loads(archive.read(prefix + "WAVE3A_RUN_STATUS.json"))
        config = json.loads(archive.read(prefix + "CONFIGURATION.json"))
    eq(hashlib.sha256(auth.canonical_json(config).encode()).hexdigest(), WAVE3A_CONFIG, "Wave-3A config")
    eq(status["status"], "PATRON_WAVE3A_DESIGN_INPUTS_COMPLETE", "Wave-3A status")
    return status, config


def authenticate_wave3a(project):
    status, config = get_wave3a_authority()
    state = project / "derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3a_patron" / WAVE3A_CONFIG[:12]
    eq(auth.load_json(state / "CONFIGURATION.json"), config, "local Wave-3A configuration")
    log("Authenticating the completed Wave-3A histories, matches and coverage checkpoints")
    for name, expected in status["checkpoint_receipts"].items():
        local = prior.read_checkpoint(state / name, WAVE3A_CONFIG)
        eq(local, expected, "local Wave-3A " + name)
    return state, status


def verify_new_cache(db, path, expected_rows):
    pairs = [("total_opps", "panel_total_opps"), ("total_kind_count", "panel_total_kind_count"),
        ("fair_opps", "panel_fair_opps"), ("fair_kind_count", "panel_fair_kind_count"),
        ("clearly_worse_opps", "panel_clearly_worse_opps"), ("clearly_worse_kind_count", "panel_clearly_worse_kind_count"),
        ("excluded_middle_opps", "panel_excluded_middle_opps"), ("excluded_middle_kind_count", "panel_excluded_middle_kind_count")]
    mismatch = " OR ".join(f"{a} IS DISTINCT FROM {b}" for a, b in pairs)
    result = records(db, f"""SELECT count(*) AS rows, count(DISTINCT username_norm) AS unique_users,
        count(*) FILTER (WHERE {mismatch}) AS history_mismatches,
        count(*) FILTER (WHERE panel_total_opps IS NULL OR
          panel_total_opps != panel_fair_opps+panel_clearly_worse_opps+panel_excluded_middle_opps OR
          fair_nonnegative_opps+fair_costly_opps != panel_fair_opps OR
          eval_bin_disconnected_clearly_better_n+eval_bin_disconnected_better_n+eval_bin_roughly_equal_n+
          eval_bin_modestly_worse_n+eval_bin_clearly_worse_n != panel_total_opps) AS partition_failures
        FROM read_parquet({q(path)}, hive_partitioning=false)""")[0]
    eq(result["rows"], expected_rows, "new cache target rows")
    eq(result["unique_users"], expected_rows, "new cache unique identities")
    eq(result["history_mismatches"], 0, "new histories vs rebuilt cache")
    eq(result["partition_failures"], 0, "new cache partition failures")
    return result


def build_design(directory, args, sample, acquisition, snapshot, expected_rows):
    database_path = directory / "build.duckdb"
    db = prior.connect(database_path, args, directory / "spill")
    try:
        bridge = directory / "new_design_profile_covariates_private.parquet"
        # Every design/exposure field comes from the frozen NEW matches. Only
        # profile covariates come from August; no Patron outcome is decoded.
        columns = ", ".join("s." + name for name in PROFILE_FEATURES)
        db.execute(f"""COPY (SELECT a.*, {columns}
            FROM read_parquet({q(acquisition)}, hive_partitioning=false) a
            LEFT JOIN read_parquet({q(snapshot)}, hive_partitioning=false) s USING(username_norm)
            ORDER BY a.query_index) TO {q(bridge)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
        panel_input = directory / "exact_panel_inputs"
        # The unchanged cache producer accepts a glob. Confine that glob to
        # exactly the 24 authenticated files, without copying or modifying them.
        for item in sample["month_records"]:
            target = panel_input / ("month=" + item["month"]) / "analysis_panel.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(Path(item["path"]).resolve())
        cache = directory / "chooser_design_features_private.parquet"
        builder.build_cache(db, {"snapshot": bridge, "stage07_glob": panel_input / "month=*/analysis_panel.parquet"}, cache)
        qa = verify_new_cache(db, cache, expected_rows)
        support = builder.build_support_receipt(db, cache)
        support.update({"lineage": "frozen_v101_functions_on_new_Wave3A_matches", "version": VERSION,
            "primary_ratio": "up to 1:3; structural two-control groups retained",
            "matching_authority": WAVE3A_CONFIG, "patron_fields_read": False})
        save_json(directory / "preoutcome_support_receipt.json", support)
        save_json(directory / "cache_validation.json", qa)
    finally:
        db.close()
    database_path.unlink()
    shutil.rmtree(directory / "spill", ignore_errors=True)
    shutil.rmtree(panel_input)
    # The full design cache now contains these columns; retain only its input
    # receipt rather than a second redundant chooser-level covariate file.
    bridge.unlink()
    return qa


def load_frames(db, cache, snapshot):
    return db.execute(f"""
      WITH joined AS (
        SELECT d.*, (s.username_norm IS NOT NULL) AS august_planned,
          coalesce(s.returned,false) AS returned, s.patron,
          CASE WHEN s.username_norm IS NULL THEN 'not_planned_in_august'
            WHEN NOT s.returned THEN 'queried_nonreturn' ELSE 'observed_outcome' END AS outcome_status,
          CASE WHEN d.created_at_ms IS NULL OR try_cast(d.queried_at_utc AS TIMESTAMPTZ) IS NULL THEN NULL
            ELSE greatest(0.0,(epoch_ms(try_cast(d.queried_at_utc AS TIMESTAMPTZ))-d.created_at_ms)/86400000.0) END AS corrected_account_age,
          CASE WHEN d.seen_at_ms IS NULL OR try_cast(d.queried_at_utc AS TIMESTAMPTZ) IS NULL THEN NULL
            ELSE greatest(0.0,(epoch_ms(try_cast(d.queried_at_utc AS TIMESTAMPTZ))-d.seen_at_ms)/86400000.0) END AS corrected_recency
        FROM read_parquet({q(cache)}, hive_partitioning=false) d
        LEFT JOIN read_parquet({q(snapshot)}, hive_partitioning=false) s USING(username_norm)
      ) SELECT *,
        max(CASE WHEN is_kind_role=1 THEN returned::INTEGER ELSE 0 END)
          OVER(PARTITION BY matched_kind_chooser_id)::BOOLEAN AS group_kind_returned,
        sum(returned::INTEGER) OVER(PARTITION BY matched_kind_chooser_id)::SMALLINT AS group_returned_count,
        max(CASE WHEN is_kind_role=1 THEN fair_opps ELSE NULL END)
          OVER(PARTITION BY matched_kind_chooser_id)::BIGINT AS group_kind_fair_opps
      FROM joined ORDER BY query_index
    """).fetchdf()


def missing_outcome_bounds(frame):
    """Sharp binary-outcome bounds for the full-target raw and cell-FE gaps."""
    d = frame.loc[frame["group_ever_kind_fair"].astype(bool), ["is_kind_role", "match_cell", "returned", "patron", "outcome_status"]].copy()
    known = d["returned"].to_numpy(dtype=bool)
    y = pd.to_numeric(d["patron"], errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    if not np.array_equal(np.isfinite(y), known):
        raise RuntimeError("Unknown Patron outcomes were lost or filled")
    if not np.isin(y[known], [0, 1]).all():
        raise RuntimeError("Nonbinary Patron outcomes")
    treated = d["is_kind_role"].to_numpy(dtype=bool)
    lower = np.where(known, y, np.where(treated, 0.0, 1.0))
    upper = np.where(known, y, np.where(treated, 1.0, 0.0))
    n_t, n_c = int(treated.sum()), int((~treated).sum())
    if min(n_t,n_c)==0:
        raise RuntimeError("No treatment or control in full target")
    raw = lambda v: 100.0*(float(v[treated].mean())-float(v[~treated].mean()))
    d["lower"] = lower
    d["upper"] = upper
    cells = []
    numerator_low = numerator_high = denominator = 0.0
    for cell, group in d.groupby("match_cell", observed=True, sort=True):
        k = group["is_kind_role"].astype(bool)
        nt, nc = int(k.sum()), int((~k).sum())
        if min(nt,nc)==0:
            continue  # These cells provide no within-cell treatment variation.
        weight = nt*nc/(nt+nc)
        lo = 100.0*(group.loc[k,"lower"].mean()-group.loc[~k,"lower"].mean())
        hi = 100.0*(group.loc[k,"upper"].mean()-group.loc[~k,"upper"].mean())
        numerator_low += weight*lo
        numerator_high += weight*hi
        denominator += weight
        cells.append({"match_cell": cell, "kind_target": nt, "control_target": nc,
            "kind_missing": int((k & ~group["returned"].astype(bool)).sum()),
            "control_missing": int((~k & ~group["returned"].astype(bool)).sum()),
            "weight": weight, "lower_gap_pp": lo, "upper_gap_pp": hi})
    if denominator<=0:
        raise RuntimeError("No within-cell support for bounds")
    return {"scope": "all fixed primary target accounts, including unavailable focal profiles",
        "assumptions": "Unknown Patron indicators lie in {0,1}; all target memberships and new match cells are fixed.",
        "not_confidence_intervals": True, "not_bounds_on_full_profile_covariate_models": True,
        "target_kind": n_t, "target_control": n_c,
        "kind_missing": int((treated & ~known).sum()), "control_missing": int((~treated & ~known).sum()),
        "raw_lower_pp": raw(lower), "raw_upper_pp": raw(upper),
        "cell_fe_lower_pp": numerator_low/denominator, "cell_fe_upper_pp": numerator_high/denominator,
        "by_cell": cells}


class CheckpointCollector(models.ModelCollector):
    def __init__(self, state, config_hash):
        super().__init__()
        self.state = state
        self.state.mkdir(parents=True, exist_ok=True)
        self.config_hash = config_hash

    def run(self, frame, *, name, regressors, standardize, covariance="HC1", estimand_class="secondary", differences=()):
        standardize = list(standardize)
        classification = "frozen_primary_family_new_sample" if estimand_class=="confirmatory" else estimand_class
        specification = {"name": name, "regressors": list(regressors), "standardize": standardize,
            "covariance": covariance, "estimand_class": classification, "differences": list(differences),
            "input_rows": len(frame), "parent_config_sha256": self.config_hash}
        sig = hashlib.sha256(auth.canonical_json(specification).encode()).hexdigest()
        def estimate(directory):
            log(f"Estimating {name} ({len(frame):,} candidate accounts)")
            fit = common.fit_absorbed_ols(frame, model_name=name, y_col="patron_pp", regressors=regressors,
                fe_col="match_cell", covariance=covariance, cluster_col="match_cell" if covariance=="CR1" else None,
                standardize=standardize, estimand_class=classification)
            save_json(directory / "fit.json", {"model": fit.model, "coefficients": fit.coefficients.to_dict(orient="records"),
                "covariance": fit.covariance, "kept_names": fit.kept_names})
            return {"model": name, "n": fit.model["n"], "rank": fit.model["rank"]}
        directory, _ = prior.checkpoint(self.state, name, sig, estimate)
        value = auth.load_json(directory / "fit.json")
        fit = common.OLSResult(model=value["model"], coefficients=pd.DataFrame(value["coefficients"]),
            covariance=np.asarray(value["covariance"], dtype=float), kept_names=value["kept_names"])
        self.models.append(fit.model)
        self.coefficients.append(fit.coefficients)
        for first, second, label in differences:
            contrast = common.coefficient_difference(fit, first, second, label)
            contrast["estimand_class"] = classification
            self.contrasts.append(contrast)
        return fit


def save_collector(public, prefix, collector):
    common.write_csv(public / f"{prefix}_coefficients.csv", pd.concat(collector.coefficients, ignore_index=True))
    common.write_csv(public / f"{prefix}_contrasts.csv", pd.DataFrame(collector.contrasts))
    save_json(public / f"{prefix}_models.json", collector.models)


def main_models(frame, state, config_hash, public, support):
    public.mkdir(parents=True, exist_ok=True)
    returned = frame.loc[frame["returned"].astype(bool)].copy()
    if returned["patron"].isna().any():
        raise RuntimeError("A returned profile has no typed Patron outcome")
    returned, groups, imputation = models.prepare_features(returned)
    save_json(public / "covariate_imputation_receipt.json", {"outcome_used": False, "diagnostics": imputation})
    main = returned.loc[returned["group_ever_kind_fair"].astype(bool) & returned["group_kind_returned"].astype(bool)].copy()
    complete4 = main.loc[main["group_returned_count"]==4].copy()
    available_all = returned.loc[returned["group_ever_kind_fair"].astype(bool)].copy()
    raw = [models.raw_row(data, label, "is_kind_role", classification) for data,label,classification in (
        (main, "primary_available_outcomes_with_returned_kind_focal", "frozen_primary_family_new_sample"),
        (complete4, "complete_four_account_groups", "missingness_sensitivity"),
        (available_all, "all_available_target_outcomes_including_unreturned_focal_groups", "missingness_sensitivity"),
        (returned, "broad_any_kind_target_roles", "qa_secondary"))]
    common.write_csv(public / "raw_matched_patron_comparisons.csv", pd.DataFrame(raw))
    flows = [{"sample": label, "accounts": len(data), "kind_accounts": int(data["is_kind_role"].sum()),
        "control_accounts": int((data["is_kind_role"]==0).sum()), "match_cells": int(data["match_cell"].nunique())}
        for data,label in ((frame,"all_any_kind_target"),(returned,"all_any_kind_returned"),
            (available_all,"primary_all_returned"),(main,"primary_source_family_group_rule"),(complete4,"primary_complete_four_groups"))]
    common.write_csv(public / "sample_flow.csv", pd.DataFrame(flows))
    collector = CheckpointCollector(state / "primary_models", config_hash)
    # Frozen main covariate ladder, with the duplicate final full-control fit
    # estimated only once. Each row is independently checkpointed.
    ladders = [
        ("01_match_cell_fe_only", []),
        ("02_plus_exposure_volume", groups["exposure_volume"]),
        ("03_plus_profile_tenure", groups["exposure_volume"]+groups["profile_tenure"]),
        ("04_plus_board_state", groups["exposure_volume"]+groups["profile_tenure"]+groups["board_state"]),
        ("05_plus_price", groups["exposure_volume"]+groups["profile_tenure"]+groups["board_state"]+groups["price"]),
        ("06_plus_engagement", groups["exposure_volume"]+groups["profile_tenure"]+groups["board_state"]+groups["price"]+groups["engagement"]),
        ("08_all_controls", groups["all"])]
    for label, controls in ladders:
        controls = list(dict.fromkeys(controls))
        collector.run(main, name=f"main_fair_kind_1to3_{label}_HC1", regressors=["is_kind_role"]+controls,
            standardize=[c for c in controls if c in groups["standardize"]],
            estimand_class="confirmatory" if label in {"01_match_cell_fe_only","08_all_controls"} else "secondary")
    for label, data, controls, covariance in (
        ("match_cell_fe_only_CR1", main, [], "CR1"),
        ("all_controls_CR1", main, groups["all"], "CR1"),
        ("complete_four_groups_all_controls_HC1", complete4, groups["all"], "HC1"),
        ("all_available_target_outcomes_cell_FE_HC1", available_all, [], "HC1"),
        ("all_controls_exclude_bot_HC1", main.loc[main["bot_title"]==0], groups["all"], "HC1")):
        collector.run(data, name="main_fair_kind_"+label, regressors=["is_kind_role"]+controls,
            standardize=[c for c in controls if c in groups["standardize"]], covariance=covariance, estimand_class="sensitivity")
    # Cheap support and stored-control-slot sensitivities; 100 full rematches
    # and opportunity-level models remain a separate lower-priority run.
    overlap = {row["match_cell"] for row in support["cell_support"] if row["overlap_cell_min20"]}
    for label, data in (("legacy_2_20", main.loc[main["group_kind_fair_opps"].between(2,20)]),
        ("duration_2_40", main.loc[main["group_kind_fair_opps"].between(2,40)]),
        ("overlap_cells_min20", main.loc[main["match_cell"].isin(overlap)])):
        collector.run(data, name=f"main_{label}_full_HC1", regressors=["is_kind_role"]+groups["all"], standardize=groups["standardize"])
    for slot in (1,2,3):
        data = models.matched_one_to_one(main, slot)
        collector.run(data, name=f"main_fixed_control_slot_{slot}_full_HC1", regressors=["is_kind_role"]+groups["all"], standardize=groups["standardize"])
    dose, _ = models.dose_tables(returned, collector, groups)
    diagnostic, diagnostic_support = models.diagnostic_models(returned, collector, groups)
    price_support = models.price_side_models(returned, collector, groups)
    for name,data in (("dose_response_raw_rates.csv",dose),("diagnostic_kindness_raw_groups.csv",diagnostic),
        ("diagnostic_kindness_support.csv",diagnostic_support),("price_side_support.csv",price_support)):
        common.write_csv(public/name, data)
    save_collector(public, "chooser", collector)
    # Require the core treatment terms and covariance-based desert contrast.
    required = {
        "main_fair_kind_1to3_01_match_cell_fe_only_HC1": ["is_kind_role"],
        "main_fair_kind_1to3_08_all_controls_HC1": ["is_kind_role"],
        "diagnostic_horse_race_min4_full_match_cell_fe_HC1": ["ever_kind_fair_state","ever_kind_clearly_worse_state"],
        "diagnostic_horse_race_min4_full_match_cell_fe_CR1": ["ever_kind_fair_state","ever_kind_clearly_worse_state"]}
    coefficients = pd.concat(collector.coefficients, ignore_index=True)
    for name, terms in required.items():
        for term in terms:
            selected = coefficients[(coefficients["model"]==name)&(coefficients["variable"]==term)&(coefficients["status"]=="estimated")]
            if len(selected)!=1 or not np.isfinite(selected.iloc[0]["coefficient_pp"]):
                raise RuntimeError(f"Required main-paper estimate is not identified: {name} / {term}")
    return {"models": len(collector.models), "primary_accounts": len(main),
        "primary_kind_accounts": int(main["is_kind_role"].sum()), "primary_control_accounts": int((main["is_kind_role"]==0).sum())}


def corrected_date_models(frame, state, config_hash, public):
    returned = frame.loc[frame["returned"].astype(bool)].copy()
    returned["account_age_days_at_query"] = returned["corrected_account_age"]
    returned["days_since_seen_at_query"] = returned["corrected_recency"]
    returned, groups, imputation = models.prepare_features(returned)
    main = returned.loc[returned["group_ever_kind_fair"].astype(bool)&returned["group_kind_returned"].astype(bool)]
    collector = CheckpointCollector(state / "corrected_date_models", config_hash)
    for covariance in ("HC1","CR1"):
        collector.run(main, name="corrected_dates_main_full_"+covariance, regressors=["is_kind_role"]+groups["all"],
            standardize=groups["standardize"], covariance=covariance, estimand_class="postcertification_date_sensitivity_reset")
        sample = returned.loc[(returned["fair_opps"]>=4)&(returned["clearly_worse_opps"]>=4)]
        controls = list(dict.fromkeys(["log_fair_opps","log_clearly_worse_opps"]+groups["all"]))
        collector.run(sample, name="corrected_dates_diagnostic_min4_full_"+covariance,
            regressors=["ever_kind_fair_state","ever_kind_clearly_worse_state"]+controls,
            standardize=[c for c in controls if c in groups["standardize"]+["log_clearly_worse_opps"]],
            covariance=covariance, estimand_class="postcertification_date_sensitivity_reset",
            differences=[("ever_kind_fair_state","ever_kind_clearly_worse_state","fair_minus_clearly_worse")])
    save_collector(public, "corrected_dates", collector)
    save_json(public / "corrected_dates_imputation.json", {"rule":"missing source dates stay missing; observed negative ages/recencies clipped to zero", "diagnostics":imputation})
    return {"models":len(collector.models)}


def estimate_stage(directory, args, state, config_hash, design, snapshot, expected_qa):
    directory.mkdir(parents=True,exist_ok=True)
    db = common.connect_database(None, args.threads, args.memory_limit)
    try:
        # Authenticate original snapshot outcome semantics against its original
        # totals, before joining it to new-design rows. No --fixture bypass.
        qa, _, _ = models.outcome_qa(db, snapshot, fixture=False)
        save_json(directory / "original_snapshot_outcome_qa.json", qa)
        frame = load_frames(db, design / "chooser_design_features_private.parquet", snapshot)
    finally:
        db.close()
    eq(len(frame), expected_qa["target_users"], "new joined target rows")
    eq(frame["username_norm"].nunique(), expected_qa["target_users"], "joined target identities")
    primary = frame.loc[frame["group_ever_kind_fair"].astype(bool)]
    eq(len(primary), 851428, "primary frozen target rows")
    eq(int((primary["outcome_status"]=="not_planned_in_august").sum()),77,"primary unqueried")
    eq(int((primary["outcome_status"]=="queried_nonreturn").sum()),130,"primary nonreturns")
    bounds = missing_outcome_bounds(frame)
    eq(bounds["kind_missing"],30,"primary kind missing")
    eq(bounds["control_missing"],177,"primary control missing")
    save_json(directory / "missing_outcome_bounds.json", bounds)
    coverage = frame.groupby(["group_ever_kind_fair","acquisition_role","outcome_status"],observed=True).agg(
        accounts=("username_norm","size"),opportunities=("total_opps","sum"),kind_draws=("total_kind_count","sum")).reset_index()
    common.write_csv(directory / "outcome_coverage_flow.csv",coverage)
    support = auth.load_json(design / "preoutcome_support_receipt.json")
    shutil.copy2(design / "preoutcome_support_receipt.json",directory / "preoutcome_support_receipt.json")
    primary_summary = main_models(frame,state,config_hash,directory,support)
    # Separate result files preserve primary-v101 vs corrected-date lineage.
    corrected_summary = corrected_date_models(frame,state,config_hash,directory)
    eq(primary_summary["primary_accounts"],851131,"source-family primary sample flow")
    eq(primary_summary["primary_kind_accounts"],212829,"primary returned kind")
    eq(primary_summary["primary_control_accounts"],638302,"primary eligible returned controls")
    return {"primary":primary_summary,"date_sensitivity":corrected_summary,
        "missing_bounds":{k:v for k,v in bounds.items() if k!="by_cell"}}


def collect_report(public, estimates, config, sample, summary, transfer):
    public.mkdir(parents=True,exist_ok=True)
    names=[]
    for path in sorted(estimates.iterdir()):
        if path.is_file() and path.name!="CHECKPOINT.json":
            shutil.copy2(path,public/path.name)
            names.append(path.name)
    status={"status":"PATRON_WAVE3B1_CORE_ESTIMATES_COMPLETE","version":VERSION,
        "created_utc":auth.utc_now(),"sample":auth.compact_sample_lineage(sample),
        "source_wave3a_coverage_gate":"BLOCKED_INCOMPLETE_AUGUST_PROFILE_COVERAGE",
        "coverage_resolution":"August-only source-family estimates and a separately labelled sensitivity adding 122 September profiles (77 primary controls). Full-target bounds are reported for each cohort; 130 primary outcomes remain unknown after supplementation. No replacement matches or API fetch.",
        "summary":summary,
        "still_pending":["100 deterministic full-control rematches","five-bin postcertification chooser models","Patron opportunity-level and ply/dyad sensitivities","integrated manuscript figures and tables"]}
    save_json(public/"WAVE3B1_RUN_STATUS.json",status)
    save_json(public/"CONFIGURATION.json",config)
    shutil.copy2(ROOT/"ANALYSIS_SCOPE_AND_MISSINGNESS_AMENDMENT.md",public/"ANALYSIS_SCOPE_AND_MISSINGNESS_AMENDMENT.md")
    names += ["WAVE3B1_RUN_STATUS.json","CONFIGURATION.json","ANALYSIS_SCOPE_AND_MISSINGNESS_AMENDMENT.md"]
    manifest=[{"relative_path":n,"bytes":(public/n).stat().st_size,"sha256":auth.sha256_file(public/n)} for n in sorted(names)]
    prior.write_tsv(public/"REPORT_FILE_HASHES.tsv",manifest)
    names.append("REPORT_FILE_HASHES.tsv")
    transfer.mkdir(parents=True,exist_ok=True)
    stamp=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())
    archive=transfer/f"POOL_MAIN_PATRON_WAVE3B1_RESULTS_{stamp}.zip"
    temporary=archive.with_suffix(".zip.partial")
    with zipfile.ZipFile(temporary,"w",compression=zipfile.ZIP_DEFLATED) as z:
        for name in sorted(names):z.write(public/name,archive.stem+"/"+name)
    with zipfile.ZipFile(temporary) as z:eq(z.testzip(),None,"new report CRC")
    os.replace(temporary,archive)
    auth.atomic_text(Path(str(archive)+".sha256"),auth.sha256_file(archive)+"  "+archive.name+"\n")
    log("PATRON_WAVE3B1_CORE_ESTIMATES_COMPLETE")
    print(f"Upload:\n{archive}\n{archive}.sha256",flush=True)


def parse_args():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root",type=Path,required=True)
    p.add_argument("--transfer-dir",type=Path,required=True)
    p.add_argument("--threads",type=int,default=8)
    p.add_argument("--hash-workers",type=int,default=10)
    p.add_argument("--memory-limit",default="12GB")
    return p.parse_args()


def run(args):
    from runner import gap_sensitivity as gap
    os.umask(0o077)
    if not 1<=args.threads<=10 or not 1<=args.hash_workers<=10:
        raise RuntimeError("Use at most 10 threads/hash workers")
    project=args.project_root.expanduser().resolve()
    if not project.is_dir():raise RuntimeError("Connect the project volume: "+str(project))
    package=auth.verify_package_manifest(ROOT)
    snapshot=prior.authenticate_snapshot(project)
    previous,status=authenticate_wave3a(project)
    supplement,gap_receipt=gap.authenticate(project,previous,ROOT)
    sample=auth.authenticate_sample(project/"derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE",hash_workers=args.hash_workers)
    eq(sample["fingerprint"],status["sample"]["fingerprint"],"Wave-3A/new sample fingerprint")
    config={"version":VERSION,"package_manifest_sha256":package["manifest_sha256"],
        "sample_fingerprint":sample["fingerprint"],"wave3a_config_sha256":WAVE3A_CONFIG,
        "snapshot_sha256":prior.SNAPSHOT_SHA,"missingness_amendment_sha256":auth.sha256_file(ROOT/"ANALYSIS_SCOPE_AND_MISSINGNESS_AMENDMENT.md"),
        "gap_fill":gap_receipt,"profile_cohorts":["august_only","mixed_date_profile_gap_fill_sensitivity"],
        "threads":args.threads,"memory_limit":args.memory_limit,
        "runtime":{"python":platform.python_version(),"duckdb":duckdb.__version__,"numpy":np.__version__,"pandas":pd.__version__,"pyarrow":pyarrow.__version__,"platform":platform.platform()}}
    digest=hashlib.sha256(auth.canonical_json(config).encode()).hexdigest()
    state=project/"derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3b1_patron"/digest[:12]
    state.mkdir(parents=True,exist_ok=True)
    with (state/"RUN.lock").open("a") as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise RuntimeError("This exact configuration is already running") from e
        save_json(state/"CONFIGURATION.json",config)
        # Freeze the explicit attrition rule BEFORE reading outcomes.
        shutil.copy2(ROOT/"ANALYSIS_SCOPE_AND_MISSINGNESS_AMENDMENT.md",state/"ANALYSIS_SCOPE_AND_MISSINGNESS_AMENDMENT.md")
        target_qa=status["checkpoint_receipts"]["matching"]["summary"]
        acquisition=previous/"matching/acquisition_users_private.parquet"
        design,_=prior.checkpoint(state,"design",digest,lambda d:build_design(d,args,sample,acquisition,snapshot,target_qa["target_users"]))
        estimates,receipt=prior.checkpoint(state,"estimates",digest,lambda d:estimate_stage(d,args,state,digest,design,snapshot,target_qa))
        log("August-only estimates complete; preparing the separately dated profile sensitivity")
        supplemented_design,_=prior.checkpoint(state,"supplemented_design",digest,
            lambda d:gap.build_design(d,args,sample,acquisition,snapshot,supplement,target_qa["target_users"]))
        supplemented_estimates,supplemented_receipt=prior.checkpoint(state,"supplemented_estimates",digest,
            lambda d:gap.estimate(d,args,state/"supplemented_models",digest,supplemented_design,target_qa))
        merged,merge_receipt=prior.checkpoint(state,"combined_public_results",digest,
            lambda d:gap.merge_public(d,estimates,supplemented_estimates))
        eq(auth.sha256_file(snapshot),prior.SNAPSHOT_SHA,"August snapshot unchanged after estimation")
        public=project/"output/pool_main_reanalysis_v100/wave3b1_patron"/digest[:12]
        summary={"august_only":receipt,"supplemented_sensitivity":supplemented_receipt,
            "output_inventory":merge_receipt,"profile_gap_fill":gap_receipt}
        collect_report(public,merged,config,sample,summary,args.transfer_dir.expanduser().resolve())


if __name__=="__main__":
    run(parse_args())
