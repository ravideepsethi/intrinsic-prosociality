"""Bind the completed profile acquisition and estimate dated sensitivities."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from source import pool_sample_common_v100 as auth
from source import wave3a_design as prior

GAP_ZIP_SHA = "99938ce0e0ebc2306e449148f76b50d87771677805ea4c35afc45066889b8737"
GAP_CONFIG = "2c3aaceee64b55d9efcfd718bc91b4b59ddb0670c36e32a5657700fec066195b"
GAP_OBSERVATION = "2026-09-11T15:30:44.718996+00:00"
q, eq, log = prior.q, prior.require_equal, prior.log
LABEL = "mixed_date_profile_gap_fill_sensitivity"


def authority(root):
    path = root / "evidence/GAP_FILL_RESULTS.zip"
    eq(auth.sha256_file(path), GAP_ZIP_SHA, "gap report ZIP SHA-256")
    with zipfile.ZipFile(path) as z:
        eq(z.testzip(), None, "gap report CRC")
        manifest = next(n for n in z.namelist() if n.endswith("/REPORT_FILE_HASHES.tsv"))
        prefix = manifest.rsplit("/", 1)[0] + "/"
        rows = list(csv.DictReader(io.StringIO(z.read(manifest).decode()), delimiter="\t"))
        eq(len(rows), 4, "gap report member count")
        eq(set(z.namelist()), {prefix + r["relative_path"] for r in rows} | {manifest}, "gap report inventory")
        for row in rows:
            data = z.read(prefix + row["relative_path"])
            eq(len(data), int(row["bytes"]), "gap report member size")
            eq(hashlib.sha256(data).hexdigest(), row["sha256"], "gap report member hash")
        config = json.loads(z.read(prefix + "CONFIGURATION.json"))
        status = json.loads(z.read(prefix + "GAP_FILL_RUN_STATUS.json"))
    eq(hashlib.sha256(auth.canonical_json(config).encode()).hexdigest(), GAP_CONFIG, "gap configuration")
    eq(status["config_sha256"], GAP_CONFIG, "gap status config")
    eq(status["status"], "COMPLETE_WITH_UNAVAILABLE_ACCOUNTS", "gap fetch disposition")
    for key, value in {"current_profiles_returned": 122, "still_unavailable": 163,
        "primary_current_profiles_returned": 77, "primary_still_unavailable": 130,
        "successful_response_rounds": 3, "august_snapshot_modified": False,
        "observation_start_utc": GAP_OBSERVATION, "observation_end_utc": GAP_OBSERVATION}.items():
        eq(status[key], value, "gap report " + key)
    return config, status


def validate_membership(db, coverage, supplement):
    qa = prior.records(db, f"""WITH gaps AS (
        SELECT *, CASE WHEN NOT august_planned THEN 'not_planned_in_august'
            ELSE 'queried_nonreturn' END AS gap_reason
        FROM read_parquet({q(coverage)}, hive_partitioning=false)
        WHERE NOT coalesce(august_returned,false)
      ), joined AS (
        SELECT g.username_norm AS expected_user, s.username_norm AS actual_user,
          g.new_role AS expected_role, s.new_role AS actual_role,
          g.new_match_cell AS expected_cell, s.new_match_cell AS actual_cell,
          g.primary_fair_kind_group AS expected_primary, s.primary_fair_kind_group AS actual_primary,
          g.gap_reason AS expected_reason, s.gap_reason AS actual_reason,
          s.returned, s.observation_source, s.august_outcome_recovered, s.queried_at_utc, s.request_count
        FROM gaps g FULL OUTER JOIN read_parquet({q(supplement)}, hive_partitioning=false) s USING(username_norm)
      ) SELECT count(*) AS rows, count(DISTINCT actual_user) AS unique_users,
        count(*) FILTER (WHERE expected_user IS NULL OR actual_user IS NULL OR
          expected_role IS DISTINCT FROM actual_role OR expected_cell IS DISTINCT FROM actual_cell OR
          expected_primary IS DISTINCT FROM actual_primary OR expected_reason IS DISTINCT FROM actual_reason) AS mismatches,
        count(*) FILTER (WHERE observation_source IS DISTINCT FROM 'current_profile_gap_fill'
          OR august_outcome_recovered IS DISTINCT FROM false) AS bad_provenance,
        count(*) FILTER (WHERE returned) AS recovered,
        count(*) FILTER (WHERE returned AND actual_primary) AS recovered_primary,
        count(*) FILTER (WHERE returned AND (actual_role IS DISTINCT FROM 'control' OR
          actual_reason IS DISTINCT FROM 'not_planned_in_august' OR
          queried_at_utc IS DISTINCT FROM {q(GAP_OBSERVATION)} OR request_count IS DISTINCT FROM 1)) AS recovery_mismatch,
        count(*) FILTER (WHERE NOT returned AND (actual_reason IS DISTINCT FROM 'queried_nonreturn' OR
          request_count IS DISTINCT FROM 3)) AS nonreturn_mismatch
      FROM joined""")[0]
    expected = {"rows":285,"unique_users":285,"mismatches":0,"bad_provenance":0,
        "recovered":122,"recovered_primary":77,"recovery_mismatch":0,"nonreturn_mismatch":0}
    eq(qa, expected, "supplement vs frozen missing-account membership")
    return qa


def authenticate(project, previous, root):
    config, status = authority(root)
    private = project / "derived/replication/pool_main_reanalysis_v100_PRIVATE/patron_gap_fill_v100" / GAP_CONFIG[:12]
    eq(auth.load_json(private / "CONFIGURATION.json"), config, "local gap configuration")
    log("Authenticating the 122 recovered profiles and three saved request rounds")
    for entry in status["private_file_receipts"]:
        path = private / entry["name"]
        eq(path.stat().st_size, entry["bytes"], "gap private file size")
        eq(auth.sha256_file(path), entry["sha256"], "gap private file hash")
    requests = json.loads((private / "REQUEST_FILE_HASHES.json").read_text())
    for entry in requests:
        path = (private / entry["relative_path"]).resolve()
        if not path.is_relative_to(private.resolve()):
            raise RuntimeError("Request inventory escapes private directory")
        eq(path.stat().st_size, entry["bytes"], "request file size")
        eq(auth.sha256_file(path), entry["sha256"], "request file hash")
    supplement = private / "current_profile_gap_supplement_private.parquet"
    with duckdb.connect() as db:
        membership = validate_membership(db, previous / "coverage/target_coverage_private.parquet", supplement)
    return supplement, {"config_sha256":GAP_CONFIG,"report_sha256":GAP_ZIP_SHA,
        "supplement_sha256":auth.sha256_file(supplement),"membership":membership,
        "observed_at_utc":GAP_OBSERVATION}


def combined_profiles(db, snapshot, supplement, output, features):
    # No existing August row may be replaced. All recovered users in this run
    # were absent from the August acquisition plan, so a strict append suffices.
    duplicate = db.execute(f"""SELECT count(*) FROM read_parquet({q(snapshot)}, hive_partitioning=false) a
        JOIN read_parquet({q(supplement)}, hive_partitioning=false) g USING(username_norm) WHERE g.returned""").fetchone()[0]
    eq(duplicate, 0, "recovered profiles must not overwrite August users")
    qa = prior.records(db, f"""SELECT count(*) AS rows, count(DISTINCT username_norm) AS unique_users,
        count(*) FILTER (WHERE returned) AS returned,
        count(*) FILTER (WHERE returned AND (patron IS NULL OR http_status IS DISTINCT FROM 200 OR
          (patron AND patron_field_present IS DISTINCT FROM true) OR
          (NOT patron AND patron_color IS NOT NULL))) AS bad_returned_outcome,
        count(*) FILTER (WHERE NOT returned AND patron IS NOT NULL) AS imputed_missing_outcome
        FROM read_parquet({q(supplement)}, hive_partitioning=false)""")[0]
    if qa["rows"] != qa["unique_users"] or qa["bad_returned_outcome"] or qa["imputed_missing_outcome"]:
        raise RuntimeError("Recovered profile identity/outcome semantics failed")
    columns = ", ".join(["username_norm", "returned", "patron"] + features)
    output.parent.mkdir(parents=True, exist_ok=True)
    db.execute(f"""COPY (
      SELECT {columns}, true AS august_planned, returned AS august_returned,
        CASE WHEN returned THEN 'august_2026' ELSE 'unavailable' END AS profile_observation_source
      FROM read_parquet({q(snapshot)}, hive_partitioning=false)
      UNION ALL
      SELECT {columns}, false AS august_planned, false AS august_returned,
        'september_11_gap_fill' AS profile_observation_source
      FROM read_parquet({q(supplement)}, hive_partitioning=false) WHERE returned
    ) TO {q(output)} (FORMAT PARQUET, COMPRESSION ZSTD)""")
    return qa


def build_design(directory, args, sample, acquisition, snapshot, supplement, expected_rows):
    from runner import run as core
    combined = directory / "dated_combined_profiles_private.parquet"
    with duckdb.connect() as db:
        db.execute("SET threads=2")
        qa = combined_profiles(db, snapshot, supplement, combined, core.PROFILE_FEATURES)
    eq(qa["rows"], 285, "supplement account count")
    eq(qa["returned"], 122, "supplement returned count")
    result = core.build_design(directory, args, sample, acquisition, combined, expected_rows)
    result["profile_dates"] = "August plus 122 profiles observed on September 11, 2026"
    result["gap_outcome_qa"] = qa
    return result


def load_frame(db, design):
    from runner import run as core
    profiles = design / "dated_combined_profiles_private.parquet"
    frame = core.load_frames(db, design / "chooser_design_features_private.parquet", profiles)
    dates = db.execute(f"SELECT username_norm, august_planned, august_returned, profile_observation_source FROM read_parquet({q(profiles)}, hive_partitioning=false)").fetchdf()
    # Restore the real August acquisition flag: the appended rows are observed
    # today but remain absent from August. Do not inherit the join's proxy flag.
    frame = frame.drop(columns=["august_planned"]).merge(dates, on="username_norm", how="left", validate="one_to_one", sort=False)
    frame["outcome_status"] = np.where(frame["profile_observation_source"] == "september_11_gap_fill",
        "observed_september_gap_fill", frame["outcome_status"])
    return frame


def core_models(frame, state, config_hash, public):
    from runner import run as core
    public.mkdir(parents=True, exist_ok=True)
    returned = frame.loc[frame["returned"].astype(bool)].copy()
    if returned["patron"].isna().any():
        raise RuntimeError("Supplemented returned profile lacks Patron outcome")
    returned, groups, imputation = core.models.prepare_features(returned)
    main = returned.loc[returned["group_ever_kind_fair"].astype(bool) & returned["group_kind_returned"].astype(bool)].copy()
    available = returned.loc[returned["group_ever_kind_fair"].astype(bool)]
    diagnostic = returned.loc[(returned["fair_opps"]>=4) & (returned["clearly_worse_opps"]>=4)]
    collector = core.CheckpointCollector(state / "core_models", config_hash)
    for covariance in ("HC1", "CR1"):
        for full in (False, True):
            controls = groups["all"] if full else []
            if covariance == "HC1":
                label = "main_fair_kind_1to3_" + ("08_all_controls" if full else "01_match_cell_fe_only") + "_HC1"
            else:
                label = "main_fair_kind_" + ("all_controls" if full else "match_cell_fe_only") + "_CR1"
            collector.run(main, name=label, regressors=["is_kind_role"]+controls,
                standardize=[c for c in controls if c in groups["standardize"]], covariance=covariance, estimand_class=LABEL)
        controls = list(dict.fromkeys(["log_fair_opps", "log_clearly_worse_opps"] + groups["all"]))
        collector.run(diagnostic, name="diagnostic_horse_race_min4_full_match_cell_fe_"+covariance,
            regressors=["ever_kind_fair_state","ever_kind_clearly_worse_state"]+controls,
            standardize=[c for c in controls if c in groups["standardize"]+["log_clearly_worse_opps"]],
            covariance=covariance, estimand_class=LABEL,
            differences=[("ever_kind_fair_state","ever_kind_clearly_worse_state","fair_minus_clearly_worse")])
    coefficients = pd.concat(collector.coefficients, ignore_index=True)
    for model in collector.models:
        name = model["model"]
        terms = ["ever_kind_fair_state", "ever_kind_clearly_worse_state"] if name.startswith("diagnostic") else ["is_kind_role"]
        for term in terms:
            found = coefficients[(coefficients["model"]==name)&(coefficients["variable"]==term)&(coefficients["status"]=="estimated")]
            if len(found)!=1 or not np.isfinite(found.iloc[0]["coefficient_pp"]):
                raise RuntimeError("Required supplemented estimate is not identified: " + name + " / " + term)
    core.save_collector(public, "chooser", collector)
    core.save_json(public / "covariate_imputation_receipt.json", {"cohort":LABEL,"diagnostics":imputation})
    raw = [core.models.raw_row(data, label, "is_kind_role", LABEL) for data, label in (
        (main,"primary_source_family_group_rule"), (available,"primary_all_available"), (returned,"broad_target"))]
    core.common.write_csv(public / "raw_matched_patron_comparisons.csv", pd.DataFrame(raw))
    flows = [{"sample":label,"accounts":len(data),"kind_accounts":int(data["is_kind_role"].sum()),
        "control_accounts":int((data["is_kind_role"]==0).sum())} for data,label in (
        (frame,"all_target"),(returned,"all_returned"),(available,"primary_all_returned"),(main,"primary_group_rule"))]
    core.common.write_csv(public / "sample_flow.csv", pd.DataFrame(flows))
    corrected = core.corrected_date_models(frame, state, config_hash, public)
    # Keep the original date-function implementation but annotate every result
    # with this explicitly mixed-date cohort, including its corrected-date fits.
    for suffix in ("coefficients.csv", "contrasts.csv"):
        path = public / ("corrected_dates_" + suffix)
        table = pd.read_csv(path)
        table["estimand_class"] = LABEL + "_corrected_dates"
        core.common.write_csv(path, table)
    corrected_models = auth.load_json(public / "corrected_dates_imputation.json")
    corrected_models["profile_cohort"] = LABEL
    core.save_json(public / "corrected_dates_imputation.json", corrected_models)
    metadata = json.loads((public / "corrected_dates_models.json").read_text())
    for item in metadata:
        item["estimand_class"] = LABEL + "_corrected_dates"
    core.save_json(public / "corrected_dates_models.json", metadata)
    return {"models":len(collector.models),"corrected_date_models":corrected["models"],
        "primary_accounts":len(main),"primary_kind_accounts":int(main["is_kind_role"].sum()),
        "primary_control_accounts":int((main["is_kind_role"]==0).sum())}


def estimate(directory, args, state, config_hash, design, target_qa):
    from runner import run as core
    with core.common.connect_database(None, args.threads, args.memory_limit) as db:
        frame = load_frame(db, design)
    eq(len(frame), target_qa["target_users"], "supplemented target rows")
    eq(frame["username_norm"].nunique(), len(frame), "supplemented unique identities")
    eq(int(frame["returned"].sum()), 1105756, "supplemented returned accounts")
    eq(int((frame["profile_observation_source"]=="september_11_gap_fill").sum()),122,"newly dated accounts")
    primary = frame.loc[frame["group_ever_kind_fair"].astype(bool)]
    eq(len(primary),851428,"supplemented primary target")
    eq(int(primary["returned"].sum()),851298,"supplemented primary returned")
    eq(int((primary["profile_observation_source"]=="september_11_gap_fill").sum()),77,"supplemented primary dated controls")
    bounds = core.missing_outcome_bounds(frame)
    eq(bounds["kind_missing"],30,"remaining kind missing")
    eq(bounds["control_missing"],100,"remaining control missing")
    directory.mkdir(parents=True,exist_ok=True)
    core.save_json(directory / "missing_outcome_bounds.json", bounds)
    flow = frame.groupby(["group_ever_kind_fair","acquisition_role","profile_observation_source","outcome_status"],observed=True).agg(
        accounts=("username_norm","size"),opportunities=("total_opps","sum"),kind_draws=("total_kind_count","sum")).reset_index()
    core.common.write_csv(directory / "outcome_coverage_flow.csv", flow)
    summary = core_models(frame,state,config_hash,directory)
    eq(summary["primary_accounts"],851208,"supplemented source-family primary rows")
    eq(summary["primary_kind_accounts"],212829,"supplemented kind rows")
    eq(summary["primary_control_accounts"],638379,"supplemented eligible control rows")
    core.save_json(directory / "PROFILE_OBSERVATION_LINEAGE.json", {"classification":LABEL,
        "august_snapshot_unchanged":True,"supplement_observed_at_utc":GAP_OBSERVATION,
        "supplemented_primary_controls":77,"supplemented_broad_controls":122,
        "remaining_primary_unknown_outcomes":130,"remaining_broad_unknown_outcomes":163,
        "old_group_assignments_reused":False,"new_Wave3A_matches_fixed":True,
        "interpretation":"Available-outcome association on a mixed-date profile cohort; not an August-complete estimate."})
    summary["missing_bounds"] = {k:v for k,v in bounds.items() if k!="by_cell"}
    return summary


def merge_public(directory, original, supplemented):
    from runner import run as core
    directory.mkdir(parents=True,exist_ok=True)
    for source, prefix in ((original,""),(supplemented,"supplemented_")):
        for path in sorted(source.iterdir()):
            if path.is_file() and path.name != "CHECKPOINT.json":
                shutil.copy2(path, directory / (prefix + path.name))
    comparisons = []
    for source, cohort in ((original,"august_only"),(supplemented,LABEL)):
        for prefix in ("chooser", "corrected_dates"):
            table = pd.read_csv(source / (prefix + "_coefficients.csv"))
            if prefix == "chooser":
                wanted = {
                    "main_fair_kind_1to3_01_match_cell_fe_only_HC1", "main_fair_kind_1to3_08_all_controls_HC1",
                    "main_fair_kind_match_cell_fe_only_CR1", "main_fair_kind_all_controls_CR1",
                    "diagnostic_horse_race_min4_full_match_cell_fe_HC1", "diagnostic_horse_race_min4_full_match_cell_fe_CR1"}
                table = table.loc[table["model"].isin(wanted)]
            table = table.loc[table["variable"].isin(["is_kind_role","ever_kind_fair_state","ever_kind_clearly_worse_state"])].copy()
            table.insert(0,"profile_cohort",cohort)
            comparisons.append(table)
    core.common.write_csv(directory / "CORE_PATRON_COMPARISON.csv", pd.concat(comparisons,ignore_index=True))
    counts = [sum(len(json.loads((source/(prefix+"_models.json")).read_text()))
        for prefix in ("chooser","corrected_dates")) for source in (original,supplemented)]
    eq(counts,[38,10],"estimated model inventory")
    return {"august_models":counts[0],"supplemented_models":counts[1],"total_models":sum(counts),
        "source_results_separate":True,"dates_not_pooled_without_labels":True}
