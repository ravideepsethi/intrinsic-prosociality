#!/usr/bin/env python3
"""Rebuild Patron design inputs; inspect fixed-August coverage before outcomes."""
from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import duckdb
import pyarrow
import pyarrow.parquet as pq

from source import acquisition_planner_v100 as planner
from source import pool_sample_common_v100 as auth

ROOT = Path(__file__).resolve().parents[1]
VERSION = "3A-1.0.0"
SNAPSHOT_SHA = "f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238"
PLAN_SHA = "2838aa942e20027561763855c387a454d74bb0a92d0a8b62ca47343511897e57"
AUDIT_SHA = "be1b69ac46d2a0e44180868e0ccead43ad0043299cffeb0203346c6c0c28aa3e"
# Only these profile columns are decoded. Patron outcomes and profile covariates
# are not read; hashing the whole file authenticates the frozen source bytes.
PROFILE_COLUMNS = (
    "username_norm", "returned", "acquisition_role", "match_cell",
    "matched_kind_chooser_id", "control_slot",
)
q = planner.sql_string


def log(message):
    print(f"[{auth.utc_now()}] {message}", flush=True)


def records(db, sql):
    result = db.execute(sql)
    names = [x[0] for x in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def require_equal(actual, expected, label):
    if actual != expected:
        raise RuntimeError(f"{label}: observed={actual!r}, expected={expected!r}")


def authenticate_snapshot(project):
    base = project / "derived/replication"
    root = base / "patron_profile_snapshot_24m_v100_FINAL_CERTIFIED"
    path = root / "profile_snapshot_24m_private_lossless.parquet"
    log("Authenticating the fixed August profile snapshot and acquisition receipt")
    for label, candidate, expected in (
        ("snapshot", path, SNAPSHOT_SHA),
        ("snapshot audit manifest", root / "audit_file_hashes.tsv", AUDIT_SHA),
        ("acquisition success", base / "patron_profile_acquisition_24m_plan_v100/_SUCCESS.json", PLAN_SHA),
    ):
        require_equal(auth.sha256_file(candidate), expected, label + " SHA-256")
    success = auth.load_json(root / "_SUCCESS.json")
    require_equal(success.get("status"), "PROFILE_SNAPSHOT_24M_CERTIFIED_OK", "snapshot status")
    footer = pq.ParquetFile(path)
    require_equal(footer.metadata.num_rows, 1_305_872, "snapshot rows")
    require_equal(len(footer.schema_arrow.names), 81, "snapshot columns")
    if not set(PROFILE_COLUMNS).issubset(footer.schema_arrow.names):
        raise RuntimeError("Snapshot lacks required acquisition/membership columns")
    return path


def check_summary(db, expected):
    values = records(db, """
        SELECT count(*) AS choosers, sum(total_opps)::BIGINT AS rows,
          sum(total_kind_count)::BIGINT AS kind_draws,
          sum(fair_opps)::BIGINT AS fair_rows,
          sum(fair_kind_count)::BIGINT AS fair_kind_draws,
          count(*) FILTER (WHERE fair_opps > 0) AS fair_choosers,
          count(*) FILTER (WHERE fair_kind_count > 0) AS fair_kind_choosers,
          count(*) FILTER (WHERE total_kind_count > 0) AS any_kind_choosers,
          count(*) - count(DISTINCT chooser_id) AS duplicate_choosers,
          count(*) FILTER (WHERE chooser_id IS NULL OR chooser_id = '' OR
              total_opps != fair_opps + clearly_worse_opps + excluded_middle_opps OR
              total_kind_count != fair_kind_count + clearly_worse_kind_count + excluded_middle_kind_count
              OR fair_kind_count > fair_opps OR clearly_worse_kind_count > clearly_worse_opps
              OR excluded_middle_kind_count > excluded_middle_opps) AS invalid_summaries
        FROM chooser_summary
    """)[0]
    for name in ("choosers", "rows", "kind_draws", "fair_rows", "fair_kind_draws", "fair_choosers", "fair_kind_choosers"):
        require_equal(values[name], expected[name], "new chooser census " + name)
    require_equal(values["duplicate_choosers"], 0, "duplicate choosers")
    require_equal(values["invalid_summaries"], 0, "invalid summary rows")
    return values


def check_matching(db):
    result = records(db, """
        SELECT (SELECT count(*) FROM acquisition_users) AS target_users,
          (SELECT count(*) FROM kind_groups) AS kind_groups,
          (SELECT count(*) FROM matching_pairs) AS selected_controls,
          (SELECT count(*) FROM kind_groups WHERE selected_controls=3) AS exact_three_groups,
          (SELECT count(*) FROM kind_groups WHERE selected_controls=0) AS unsupported_groups,
          (SELECT count(*) - count(DISTINCT username_norm) FROM acquisition_users) AS duplicate_users,
          (SELECT count(*) FROM matching_pairs p
            JOIN chooser_summary k ON k.chooser_id=p.kind_chooser_id
            JOIN chooser_summary c ON c.chooser_id=p.control_chooser_id
            WHERE NOT k.ever_kind_any_state OR c.ever_kind_any_state
              OR c.match_cell != k.match_cell OR p.control_slot NOT BETWEEN 1 AND 3) AS invalid_pairs,
          (SELECT count(*) FROM kind_groups WHERE selected_controls NOT BETWEEN 0 AND 3) AS invalid_groups
    """)[0]
    for key in ("duplicate_users", "invalid_pairs", "invalid_groups"):
        require_equal(result[key], 0, "matching " + key)
    require_equal(result["target_users"], result["kind_groups"] + result["selected_controls"], "matching conservation")
    require_equal(result["kind_groups"], db.execute("SELECT count(*) FROM chooser_summary WHERE ever_kind_any_state").fetchone()[0], "all any-kind accounts retained")
    return result


def load_profile_membership(db, path, *, certify=True):
    names = ", ".join(PROFILE_COLUMNS)
    db.execute(f"CREATE OR REPLACE TABLE snapshot_membership AS SELECT {names} FROM read_parquet({q(path)}, hive_partitioning=false)")
    result = records(db, """
        SELECT count(*) AS planned, count(*) FILTER (WHERE returned) AS returned,
          count(*) FILTER (WHERE NOT returned) AS nonreturned,
          count(*) FILTER (WHERE acquisition_role='kind') AS kind_role,
          count(*) FILTER (WHERE acquisition_role='control') AS control_role,
          count(*) - count(DISTINCT username_norm) AS duplicate_or_null_ids,
          count(*) FILTER (WHERE returned IS NULL OR username_norm != lower(trim(username_norm))
             OR username_norm='' OR acquisition_role IS NULL OR acquisition_role NOT IN ('kind','control')
             OR matched_kind_chooser_id IS NULL OR match_cell IS NULL OR control_slot IS NULL
             OR (acquisition_role='kind' AND (control_slot!=0 OR matched_kind_chooser_id!=username_norm))
             OR (acquisition_role='control' AND control_slot NOT BETWEEN 1 AND 3)) AS invalid_rows
        FROM snapshot_membership
    """)[0]
    require_equal(result["duplicate_or_null_ids"], 0, "snapshot identity uniqueness")
    require_equal(result["invalid_rows"], 0, "snapshot membership rows")
    if certify:
        for name, number in {"planned": 1305872, "returned": 1305683, "nonreturned": 189, "kind_role": 326468, "control_role": 979404}.items():
            require_equal(result[name], number, "snapshot " + name)
    return result


def build_coverage(db):
    db.execute("""
        CREATE OR REPLACE TABLE target_coverage AS
        SELECT a.username_norm, a.acquisition_role AS new_role, a.match_cell AS new_match_cell,
          a.matched_kind_chooser_id, a.control_slot,
          k.ever_kind_fair_state AS primary_fair_kind_group,
          a.selected_controls,
          s.acquisition_role AS august_role, s.match_cell AS august_match_cell,
          (s.username_norm IS NOT NULL) AS august_planned,
          s.returned AS august_returned
        FROM acquisition_users a
        JOIN chooser_summary k ON k.chooser_id=a.matched_kind_chooser_id
        LEFT JOIN snapshot_membership s USING (username_norm)
    """)
    require_equal(db.execute("SELECT count(*) FROM target_coverage").fetchone()[0], db.execute("SELECT count(*) FROM acquisition_users").fetchone()[0], "coverage join conservation")
    db.execute("""
        CREATE OR REPLACE TABLE group_coverage AS
        SELECT matched_kind_chooser_id, primary_fair_kind_group,
          max(selected_controls)::BIGINT AS selected_controls,
          bool_and(august_planned) AS all_planned,
          bool_and(coalesce(august_returned, false)) AS all_returned,
          count(*) FILTER (WHERE NOT august_planned) AS unplanned_members,
          count(*) FILTER (WHERE august_planned AND NOT august_returned) AS nonreturned_members
        FROM target_coverage GROUP BY matched_kind_chooser_id, primary_fair_kind_group
    """)
    coverage = records(db, """
        WITH scoped AS (
          SELECT 'all_any_kind_groups' AS scope, * FROM target_coverage
          UNION ALL SELECT 'primary_fair_kind_groups' AS scope, * FROM target_coverage WHERE primary_fair_kind_group
        ) SELECT scope, new_role, count(*) AS target_accounts,
          count(*) FILTER (WHERE august_planned) AS august_planned,
          count(*) FILTER (WHERE august_returned) AS august_returned,
          count(*) FILTER (WHERE august_planned AND NOT august_returned) AS august_nonreturned,
          count(*) FILTER (WHERE NOT august_planned) AS never_queried_in_august,
          count(*) FILTER (WHERE august_role='kind' AND new_role='control') AS formerly_kind_now_control,
          count(*) FILTER (WHERE august_planned AND august_match_cell != new_match_cell) AS changed_match_cell
        FROM scoped GROUP BY scope, new_role ORDER BY scope, new_role
    """)
    support = records(db, """
        SELECT primary_fair_kind_group, selected_controls, count(*) AS groups,
          count(*) FILTER (WHERE all_planned) AS all_members_august_planned,
          count(*) FILTER (WHERE all_returned) AS all_members_august_returned,
          sum(unplanned_members)::BIGINT AS unplanned_members,
          sum(nonreturned_members)::BIGINT AS nonreturned_members
        FROM group_coverage GROUP BY primary_fair_kind_group, selected_controls
        ORDER BY primary_fair_kind_group DESC, selected_controls
    """)
    by_cell = records(db, """
        SELECT new_match_cell, new_role, primary_fair_kind_group, count(*) AS target_accounts,
          count(*) FILTER (WHERE NOT august_planned) AS never_queried_in_august,
          count(*) FILTER (WHERE august_planned AND NOT august_returned) AS august_nonreturned,
          count(*) FILTER (WHERE august_returned) AS august_returned
        FROM target_coverage GROUP BY new_match_cell, new_role, primary_fair_kind_group
        ORDER BY new_match_cell, new_role, primary_fair_kind_group
    """)
    population = records(db, """
        SELECT c.ever_kind_any_state AS new_any_kind, c.ever_kind_fair_state AS new_fair_kind,
          coalesce(s.acquisition_role, 'not_planned') AS august_role, count(*) AS choosers,
          count(*) FILTER (WHERE s.returned) AS returned_profiles,
          sum(c.total_opps)::BIGINT AS opportunities, sum(c.total_kind_count)::BIGINT AS kind_draws
        FROM chooser_summary c LEFT JOIN snapshot_membership s ON s.username_norm=c.chooser_id
        GROUP BY new_any_kind, new_fair_kind, august_role ORDER BY new_any_kind, new_fair_kind, august_role
    """)
    transitions = records(db, """
        SELECT s.acquisition_role AS august_role,
          CASE WHEN c.chooser_id IS NULL THEN 'absent_from_new_panel'
            WHEN c.ever_kind_any_state THEN 'kind_in_new_panel' ELSE 'never_kind_in_new_panel' END AS new_status,
          count(*) AS accounts, count(*) FILTER (WHERE s.returned) AS returned_profiles
        FROM snapshot_membership s LEFT JOIN chooser_summary c ON c.chooser_id=s.username_norm
        GROUP BY august_role, new_status ORDER BY august_role, new_status
    """)
    retained_groups = records(db, """
        SELECT s.acquisition_role AS august_role, count(*) AS old_group_members,
          count(*) FILTER (WHERE c.chooser_id IS NOT NULL) AS active_in_new_panel,
          count(*) FILTER (WHERE c.chooser_id IS NOT NULL AND s.returned) AS active_with_returned_profile,
          count(*) FILTER (WHERE c.match_cell=k.match_cell) AS now_in_same_cell_as_new_fair_kind,
          count(*) FILTER (WHERE c.match_cell!=k.match_cell) AS now_in_different_cell,
          count(*) FILTER (WHERE s.acquisition_role='control' AND c.ever_kind_any_state) AS formerly_control_now_kind
        FROM snapshot_membership s
        JOIN chooser_summary k ON k.chooser_id=s.matched_kind_chooser_id AND k.ever_kind_fair_state
        LEFT JOIN chooser_summary c ON c.chooser_id=s.username_norm
        GROUP BY august_role ORDER BY august_role
    """)
    gates = {}
    for scope in ("all_any_kind_groups", "primary_fair_kind_groups"):
        selected = [r for r in coverage if r["scope"] == scope]
        missing = sum(r["never_queried_in_august"] for r in selected)
        gates[scope] = {"status": "BLOCKED_INCOMPLETE_AUGUST_PROFILE_COVERAGE" if missing else "PASS_PLANNED_MEMBERSHIP_ONLY",
            "unplanned_target_accounts": missing,
            "planned_nonreturns": sum(r["august_nonreturned"] for r in selected),
            "models_estimated": False}
        if not selected or not any(r["new_role"] == "control" for r in selected):
            gates[scope]["status"] = "BLOCKED_NO_MATCHED_COMPARISON"
    return {"coverage": coverage, "group_support": support, "coverage_by_cell": by_cell,
        "population_coverage": population, "august_role_transitions": transitions,
        "original_group_retention_diagnostic": retained_groups, "gates": gates}


def export_private(db, directory, tables):
    for table in tables:
        path = directory / f"{table}_private.parquet"
        db.execute(f"COPY {table} TO {q(path)} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)")


def read_checkpoint(directory, config_hash):
    receipt_path = directory / "CHECKPOINT.json"
    if not receipt_path.is_file():
        raise RuntimeError(f"Incomplete committed checkpoint: {directory}; preserve it for inspection")
    receipt = auth.load_json(receipt_path)
    require_equal(receipt["config_sha256"], config_hash, "checkpoint configuration")
    for item in receipt["files"]:
        path = directory / item["name"]
        require_equal(path.stat().st_size, item["bytes"], "checkpoint byte size")
        require_equal(auth.sha256_file(path), item["sha256"], "checkpoint file hash")
    return receipt


def checkpoint(state, name, config_hash, function):
    target = state / name
    if target.exists():
        log(f"Verifying/reusing {name} checkpoint")
        return target, read_checkpoint(target, config_hash)
    temporary = Path(tempfile.mkdtemp(prefix=name + ".partial_", dir=state))
    started = time.monotonic()
    log(f"Building {name}")
    result = function(temporary)
    files = [{"name": p.name, "bytes": p.stat().st_size, "sha256": auth.sha256_file(p)}
        for p in sorted(temporary.iterdir()) if p.is_file()]
    receipt = {"status": "CHECKPOINT_COMPLETE", "config_sha256": config_hash,
        "created_utc": auth.utc_now(), "elapsed_seconds": time.monotonic()-started,
        "files": files, "summary": result}
    auth.atomic_json(temporary / "CHECKPOINT.json", receipt)
    os.replace(temporary, target)
    return target, receipt


def connect(path, args, temporary):
    db = duckdb.connect(str(path))
    planner.configure_database(db, temporary, args.threads, args.memory_limit)
    return db


def run_summary(directory, args, sample):
    path = directory / "work.duckdb"
    db = connect(path, args, directory / "spill")
    try:
        paths = ", ".join(q(row["path"]) for row in sample["month_records"])
        db.execute(f"CREATE VIEW stage07 AS SELECT * FROM read_parquet([{paths}], union_by_name=true, hive_partitioning=false)")
        planner.build_chooser_summary(db)
        result = check_summary(db, sample["authority"])
        export_private(db, directory, ("chooser_summary",))
    finally:
        db.close()
    path.unlink()
    shutil.rmtree(directory / "spill", ignore_errors=True)
    return result


def run_matching(directory, args, summary_path):
    path = directory / "work.duckdb"
    db = connect(path, args, directory / "spill")
    try:
        db.execute(f"CREATE VIEW chooser_summary AS SELECT * FROM read_parquet({q(summary_path)}, hive_partitioning=false)")
        planner.build_matching(db, planner.DESIGN_SEED)
        result = check_matching(db)
        export_private(db, directory, ("acquisition_users", "matching_pairs", "kind_groups", "cell_counts"))
    finally:
        db.close()
    path.unlink()
    shutil.rmtree(directory / "spill", ignore_errors=True)
    return result


def run_coverage(directory, args, summary_path, matches, snapshot_path):
    path = directory / "work.duckdb"
    db = connect(path, args, directory / "spill")
    try:
        for name, source in (("chooser_summary", summary_path), ("acquisition_users", matches / "acquisition_users_private.parquet")):
            db.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet({q(source)}, hive_partitioning=false)")
        snapshot_qa = load_profile_membership(db, snapshot_path)
        result = build_coverage(db)
        # New panel is a subset of the old panel: a new kind chooser must have
        # been acquired as old kind, and an old never-kind cannot become kind.
        invalid = db.execute("""SELECT count(*) FROM chooser_summary c LEFT JOIN snapshot_membership s
            ON s.username_norm=c.chooser_id WHERE c.ever_kind_any_state
            AND (s.username_norm IS NULL OR s.acquisition_role!='kind')""").fetchone()[0]
        require_equal(invalid, 0, "new kind accounts must belong to the old all-kind acquisition universe")
        export_private(db, directory, ("target_coverage", "group_coverage"))
        result["snapshot_membership_qa"] = snapshot_qa
        auth.atomic_json(directory / "aggregate_coverage.json", result)
    finally:
        db.close()
    path.unlink()
    shutil.rmtree(directory / "spill", ignore_errors=True)
    return {"gates": result["gates"], "snapshot_membership_qa": snapshot_qa}


def write_tsv(path, rows):
    if not rows:
        auth.atomic_text(path, "")
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def make_report(directory, configuration, sample, receipts, coverage, elapsed):
    directory.mkdir(parents=True, exist_ok=True)
    public_names = []
    for name in ("coverage", "group_support", "coverage_by_cell", "population_coverage", "august_role_transitions", "original_group_retention_diagnostic"):
        filename = name + ".tsv"
        write_tsv(directory / filename, coverage[name])
        public_names.append(filename)
    status = {"status": "PATRON_WAVE3A_DESIGN_INPUTS_COMPLETE", "version": VERSION,
        "created_utc": auth.utc_now(), "elapsed_seconds_this_invocation": elapsed,
        "models_estimated": False, "profile_outcome_columns_decoded": [],
        "profile_membership_columns_decoded": list(PROFILE_COLUMNS),
        "sample": auth.compact_sample_lineage(sample), "coverage_gates": coverage["gates"],
        "checkpoint_receipts": receipts}
    for filename, value in (("WAVE3A_RUN_STATUS.json", status), ("CONFIGURATION.json", configuration), ("COVERAGE_GATES.json", coverage["gates"])):
        auth.atomic_json(directory / filename, value)
        public_names.append(filename)
    primary = coverage["gates"]["primary_fair_kind_groups"]
    text = ("# New-main-sample Patron design rebuild\n\n"
        "The 24-month chooser histories and deterministic matches have been rebuilt on the certified pool nonadjacent sample. "
        "The original acquisition planner's chooser-summary and matching functions and SHA-256 seed were used unchanged.\n\n"
        f"Primary fair-kind target membership gate: **{primary['status']}**. "
        f"{primary['unplanned_target_accounts']:,} target accounts were never queried in August; "
        f"{primary['planned_nonreturns']:,} were queried but did not return a profile. These are separate kinds of missingness.\n\n"
        "This package estimates no Patron coefficients and does not update manuscript Patron numbers. "
        "It decodes acquisition identities, return flags and stored match fields only. "
        "A membership pass does not certify an estimation sample: return attrition, structural match support, covariate construction and statistical estimation still need their recorded gates.\n\n"
        "If target membership is incomplete, do not silently rematch inside the available August profiles or treat unqueried accounts as non-Patrons. "
        "The old snapshot sampled all old kind choosers but only selected old never-kind controls; some old kind accounts are now controls. "
        "The coverage/transition tables show this selection mechanism. A redesign using this historical acquired cohort must label its population and justify sampling/weighting. "
        "A fresh snapshot would measure Patron status at a different date and must not be mixed into the August outcome unnoticed.\n\n"
        "original_group_retention_diagnostic.tsv describes retention of the original acquired groups with a now-fair-kind focal chooser; "
        "it does not select an alternative main analysis. Only the fresh target uses the new match cells. "
        "No profile API requests were made. Account-level artifacts and identifiers remain in private project state.\n\n"
        "The sample reset was requested after seeing old-sample results. This is a deterministic reset/coverage diagnostic, not a new preregistration.\n")
    auth.atomic_text(directory / "SUMMARY.md", text)
    public_names.append("SUMMARY.md")
    hashes = [{"relative_path": name, "bytes": (directory/name).stat().st_size, "sha256": auth.sha256_file(directory/name)} for name in sorted(public_names)]
    write_tsv(directory / "REPORT_FILE_HASHES.tsv", hashes)
    return sorted(public_names + ["REPORT_FILE_HASHES.tsv"])


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--transfer-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--hash-workers", type=int, default=10)
    parser.add_argument("--memory-limit", default="12GB")
    return parser.parse_args()


def run(args):
    started = time.monotonic()
    os.umask(0o077)
    if not (1 <= args.threads <= 10 and 1 <= args.hash_workers <= 10):
        raise RuntimeError("Use between 1 and 10 threads/hash workers")
    project = args.project_root.expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError(f"Connect the project volume: {project}")
    # Reuse the unchanged authentication function; its Wave-2B2B1 status label
    # is deliberately not propagated as a Wave-3 result status.
    package = auth.verify_package_manifest(ROOT)
    snapshot = authenticate_snapshot(project)
    sample = auth.authenticate_sample(project / "derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE", hash_workers=args.hash_workers)
    missing_columns = set(planner.REQUIRED_COLUMNS) - set(sample["schema"])
    if missing_columns:
        raise RuntimeError(f"Panel lacks planner columns: {sorted(missing_columns)}")
    configuration = {"version": VERSION, "package_manifest_sha256": package["manifest_sha256"],
        "sample_fingerprint": sample["fingerprint"], "snapshot_sha256": SNAPSHOT_SHA,
        "plan_success_sha256": PLAN_SHA, "design_seed": planner.DESIGN_SEED,
        "profile_membership_columns": list(PROFILE_COLUMNS),
        "matching_population": "full_new_panel; all any-kind versus never-kind; original bin x speed cells; up to 3 controls without replacement",
        "primary_group_subset": "new fair-kind focal chooser; matched under all-any-kind acquisition design",
        "threads": args.threads, "memory_limit": args.memory_limit,
        "runtime": {"python": platform.python_version(), "duckdb": duckdb.__version__, "pyarrow": pyarrow.__version__, "platform": platform.platform()}}
    config_hash = hashlib.sha256(auth.canonical_json(configuration).encode()).hexdigest()
    state = project / "derived/replication/pool_main_reanalysis_v100_PRIVATE/wave3a_patron" / config_hash[:12]
    state.mkdir(parents=True, exist_ok=True)
    with (state / "RUN.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This exact Patron rebuild is already running") from exc
        auth.atomic_json(state / "CONFIGURATION.json", configuration)
        summaries, summary_receipt = checkpoint(state, "chooser_summary", config_hash, lambda d: run_summary(d, args, sample))
        summary_path = summaries / "chooser_summary_private.parquet"
        matches, matching_receipt = checkpoint(state, "matching", config_hash, lambda d: run_matching(d, args, summary_path))
        covered, coverage_receipt = checkpoint(state, "coverage", config_hash, lambda d: run_coverage(d, args, summary_path, matches, snapshot))
        coverage = auth.load_json(covered / "aggregate_coverage.json")
        receipts = {"chooser_summary": summary_receipt, "matching": matching_receipt, "coverage": coverage_receipt}
        public = project / "output/pool_main_reanalysis_v100/wave3a_patron" / config_hash[:12]
        names = make_report(public, configuration, sample, receipts, coverage, time.monotonic()-started)
        args.transfer_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        archive = args.transfer_dir / f"POOL_MAIN_PATRON_WAVE3A_RESULTS_{stamp}_{config_hash[:12]}.zip"
        temporary = archive.with_suffix(".zip.partial")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as handle:
            for name in names:
                handle.write(public / name, archive.stem + "/" + name)
        with zipfile.ZipFile(temporary) as handle:
            require_equal(handle.testzip(), None, "report ZIP CRC")
        os.replace(temporary, archive)
        auth.atomic_text(Path(str(archive)+".sha256"), f"{auth.sha256_file(archive)}  {archive.name}\n")
        log("PATRON_WAVE3A_DESIGN_INPUTS_COMPLETE")
        print(json.dumps(coverage["gates"], indent=2), flush=True)
        print(f"\nUpload these two files:\n{archive}\n{archive}.sha256", flush=True)


if __name__ == "__main__":
    run(parse_args())
