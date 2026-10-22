#!/usr/bin/env python3
"""Run the original C9 estimator on the authenticated pool-main B1 sample."""
from __future__ import annotations

import argparse
import ast
import csv
import fcntl
import hashlib
import io
import json
import os
import platform
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from runner import common

PACKAGE = Path(__file__).resolve().parents[1]
SPEC = common.load_json(PACKAGE / "authority/C9_INPUT_AUTHORITY.json")
SCIENCE_FUNCTIONS = (
    "b1_stage07_mapping", "build_session_cache", "outcome_blind_support",
    "c9_totals", "initialize_worker", "worker_batch", "observed_totals",
    "run_randomizations", "b2_validation", "summarize_c9",
)


def log(message):
    print(f"[{common.utc_now()}] {message}", flush=True)


@contextmanager
def heartbeat(label):
    started = time.monotonic()
    stop = threading.Event()
    def report():
        while not stop.wait(30):
            log(f"{label}: still running; elapsed {(time.monotonic()-started)/60:.1f} min")
    thread = threading.Thread(target=report, daemon=True)
    thread.start()
    log(label + ": started")
    try:
        yield
    finally:
        stop.set()
        thread.join()
        log(f"{label}: elapsed {(time.monotonic()-started)/60:.1f} min")


def require_hash(path, expected, label):
    if not path.is_file():
        raise RuntimeError(f"Missing {label}: {path}")
    actual = common.sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"Changed {label}: {path}; expected {expected}; got {actual}")
    return {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}


def load_c9():
    path = PACKAGE / "source/run_campaign1_c9_v100.py"
    require_hash(path, SPEC["original_c9_source_sha256"], "original C9 producer")
    module = common.load_source_module(path, "run_campaign1_c9_v100")
    # These constants govern sample cardinality checks, not the estimator or RNG.
    module.EXPECTED_B1_ROWS = SPEC["b1_rows"]
    module.EXPECTED_B1_CHOOSERS = SPEC["b1_choosers"]
    module.EXPECTED_B1_KIND = SPEC["b1_kind"]
    module.EXPECTED_STAGE07_ROWS = 41_534_331
    return module


def function_hashes(path, names):
    nodes = {n.name: n for n in ast.parse(path.read_text()).body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    return {name: hashlib.sha256(ast.dump(nodes[name], include_attributes=False).encode()).hexdigest()
            for name in names}


def write_csv(path, rows):
    """One union schema, including primary-only fields that broke original C9."""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    common.atomic_text(path, stream.getvalue())


def paths_for(project):
    private_base = project / "derived/replication/pool_main_reanalysis_v100_PRIVATE"
    view = private_base / "wave2b1/project_view"
    core = view / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    return {
        "sample": project / "derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE",
        "wave_status": project / "output/pool_main_reanalysis_v100/wave2b1/WAVE2B1_RUN_STATUS.json",
        "b1": core / "b1_repeat_granter_private.parquet",
        "prop": core / "b1_crossfit_propensity_private.parquet",
        "b2_script": view / "replication_package/code/10f_estimate_b2_first_grant_dynamics.py",
        "b2_public": view / "output/dynamic_second_wave_b2_v100/POOL_MAIN_WAVE2B1_SECOND",
        "b2_state": view / "derived/replication/dynamic_second_wave_b2_v100_PRIVATE",
        "chron_manifest": view / "output/dynamic_prosociality_a3_chronology_gate_v100/POOL_MAIN_WAVE2B1_A3/chronology_input_manifest.tsv",
        "private_base": private_base / "c9_fresh_v100",
        "public_base": project / "output/pool_main_reanalysis_v100/c9_fresh_v100",
    }


def check_chronology_row(row):
    import pyarrow.parquet as pq
    path = row["path"]
    if not path.is_file() or path.stat().st_size != row["bytes"]:
        raise RuntimeError(f"Chronology file missing or changed size: {path}")
    file = pq.ParquetFile(path)
    if file.metadata.num_rows != row["rows"]:
        raise RuntimeError(f"Chronology row count changed: {path}")
    names = file.schema_arrow.names
    if not {"white_id", "black_id", "game_id", "utc_ms"} <= set(names):
        raise RuntimeError(f"Chronology schema changed: {path}")
    idx = list(file.metadata.schema.names).index("utc_ms")
    stats = [file.metadata.row_group(i).column(idx).statistics
             for i in range(file.metadata.num_row_groups)]
    if any(s is None or not s.has_min_max for s in stats):
        raise RuntimeError(f"Chronology UTC footer support changed: {path}")
    if min(s.min for s in stats) != row["utc_ms_min"] or max(s.max for s in stats) != row["utc_ms_max"]:
        raise RuntimeError(f"Chronology timestamp range changed: {path}")
    return True


def preflight(paths, workers, c9):
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
    import duckdb
    package_receipt = common.verify_package_manifest()
    inputs = {}
    checks = [
        (paths["wave_status"], SPEC["wave2b1_status_sha256"], "Wave 2B1 status"),
        (paths["b1"], SPEC["b1_sample_sha256"], "new-sample B1"),
        (paths["prop"], SPEC["b1_propensity_sha256"], "new-sample B1 propensities"),
        (paths["b2_script"], SPEC["b2_script_sha256"], "executed Wave 2B1 B2 producer"),
        (paths["b2_public"] / "_SUCCESS.json", SPEC["b2_success_sha256"], "new-sample B2 success"),
        (paths["b2_public"] / "summary.json", SPEC["b2_summary_sha256"], "new-sample B2 summary"),
        (paths["b2_public"] / "b2_first_grant_horizons.csv", SPEC["b2_horizons_sha256"], "new-sample B2 horizons"),
        (paths["chron_manifest"], SPEC["chronology_manifest_sha256"], "Wave 2B1 chronology manifest"),
    ]
    for path, expected, label in checks:
        inputs[label] = require_hash(path, expected, label)
    auth = common.authenticate_sample(paths["sample"], verify_hashes=True, hash_workers=workers)
    if auth["fingerprint"] != SPEC["sample_fingerprint"]:
        raise RuntimeError("Main-sample fingerprint changed")
    if pq.ParquetFile(paths["b1"]).metadata.num_rows != SPEC["b1_rows"]:
        raise RuntimeError("B1 rows changed")
    chronology = c9.chronology_manifest_rows(paths["chron_manifest"])
    if len(chronology) != SPEC["chronology_files"] or sum(x["rows"] for x in chronology) != SPEC["chronology_rows"]:
        raise RuntimeError("Chronology inventory changed")
    selected = c9.campaign_chron_paths(chronology)
    if len(selected) != SPEC["selected_chronology_files"] or sum(x["rows"] for x in selected) != SPEC["selected_chronology_rows"]:
        raise RuntimeError("C9 chronology-window selection changed")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(check_chronology_row, selected))
    b2 = common.load_source_module(paths["b2_script"], "pool_main_executed_b2")
    for name, expected in [("EXPECTED_ROWS", SPEC["b1_rows"]), ("EXPECTED_CHOOSERS", SPEC["b1_choosers"]),
                           ("EXPECTED_KIND_DRAWS", SPEC["b1_kind"]), ("B2_SEED", SPEC["seed"]),
                           ("RANDOMIZATIONS", 4999), ("RANDOMIZATION_BATCH", 250)]:
        if getattr(b2, name) != expected:
            raise RuntimeError(f"B2 authority constant changed: {name}")
    # Authenticate ALL reference batches now; compare their arrays after fresh C9 draws.
    for start in range(0, 4999, 250):
        stop = min(start + 250, 4999)
        path = paths["b2_state"] / "randomizations" / f"b2_{start:04d}_{stop-1:04d}.npz"
        if b2.authenticate_checkpoint(path, path.with_suffix(".json"), start, stop, SPEC["b2_config_sha256"]) is None:
            raise RuntimeError(f"The certified B2 reference checkpoint is missing: {path}")
    receipt = {
        "status": "POOL_MAIN_C9_PREFLIGHT_READY",
        "package": package_receipt, "inputs": inputs,
        "sample_authority": common.compact_sample_lineage(auth),
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "pandas": pd.__version__, "pyarrow": pa.__version__, "duckdb": duckdb.__version__},
        "chronology": {"selected_files": len(selected), "selected_rows": sum(x["rows"] for x in selected),
                       "selected_bytes": sum(x["bytes"] for x in selected),
                       "verification": "SHA-256 of frozen manifest; file sizes, Parquet row counts, required columns and UTC ranges; not whole-file chronology SHA-256"},
        "reference_b2_batches_authenticated": 20,
        "original_c9_sha256": SPEC["original_c9_source_sha256"],
        "original_estimator_function_bodies_changed": False,
        "science_function_ast_sha256": function_hashes(PACKAGE / "source/run_campaign1_c9_v100.py", SCIENCE_FUNCTIONS),
        "cardinality_constant_rebindings": {"EXPECTED_B1_ROWS": SPEC["b1_rows"],
                                          "EXPECTED_B1_CHOOSERS": SPEC["b1_choosers"],
                                          "EXPECTED_B1_KIND": SPEC["b1_kind"], "EXPECTED_STAGE07_ROWS": 41534331},
        "network_requests": 0,
    }
    return auth, chronology, b2, receipt


def get_sessions(c9, paths, auth, chronology, state, config_sha, workers, memory):
    import pyarrow.parquet as pq
    final = state / "sessions"
    receipt_path = final / "SESSION_CHECKPOINT.json"
    if final.exists():
        receipt = common.load_json(receipt_path)
        if receipt.get("config_sha256") != config_sha:
            raise RuntimeError("C9 session configuration changed")
        for row in receipt["files"]:
            require_hash(final / row["relative_path"], row["sha256"], "C9 session checkpoint")
        log("Authenticated completed all-game session cache; resuming")
        return final / "b1_c9_session_private.parquet", receipt
    free = shutil.disk_usage(state).free / 1024**3
    if free < 80:
        raise RuntimeError(f"Session construction needs 80 GiB free workspace; available {free:.1f} GiB")
    temporary = Path(tempfile.mkdtemp(prefix="sessions.partial_", dir=state))
    spill = temporary / "duckdb_spill"
    con = c9.setup_duckdb(spill, workers, memory)
    try:
        with heartbeat("Resolving new B1 rows to games using non-outcome fields"):
            mapping = c9.b1_stage07_mapping(con, paths["b1"], [x["path"] for x in auth["month_records"]], temporary)
        with heartbeat("Building sessions from all rated games (150 chronology files)"):
            cache, report = c9.build_session_cache(con, paths["b1"], paths["prop"], chronology, temporary, temporary)
        # Never silently classify unresolved sessions as equal or unequal.
        session_col = pq.read_table(cache, columns=["session_id"])["session_id"]
        if session_col.null_count or report["b1_rows_with_session"] != SPEC["b1_rows"]:
            raise RuntimeError("Some B1 sessions are unresolved; no C9 estimate will be published")
        with heartbeat("Freezing outcome-blind partition support"):
            support = c9.outcome_blind_support(paths["b1"], cache, temporary)
    finally:
        con.close()
    if spill.exists():
        shutil.rmtree(spill)  # This run's closed DuckDB scratch only.
    report["persisted_private_cache"] = str(final / cache.name)
    common.atomic_json(temporary / "c9_session_mapping.json", report)
    receipt = {"status": "POOL_MAIN_C9_SESSION_CHECKPOINT_OK", "config_sha256": config_sha,
               "files": common.output_manifest(temporary), "mapping": mapping, "session": report, "support": support}
    common.atomic_json(temporary / "SESSION_CHECKPOINT.json", receipt)
    os.replace(temporary, final)
    return final / cache.name, receipt


def preserve_incomplete_batches(state, c9):
    """Preserve interrupted one-sided checkpoints from THIS new run before retry."""
    preserved = []
    for start in range(0, 4999, 250):
        stop = min(start + 250, 4999)
        path, receipt = c9.batch_checkpoint_paths(state, start, stop)
        if path.exists() != receipt.exists():
            destination = Path(tempfile.mkdtemp(prefix=f"batch_{start:04d}_", dir=state / "interrupted_checkpoints"))
            for f in (path, receipt):
                if f.exists():
                    os.replace(f, destination / f.name)
            preserved.append({"start": start, "stop": stop, "preserved_at": str(destination)})
    return preserved


def compare_b2_batches(paths, simulated, b2):
    import numpy as np
    checked = []
    for start in range(0, 4999, 250):
        stop = min(start + 250, 4999)
        path = paths["b2_state"] / "randomizations" / f"b2_{start:04d}_{stop-1:04d}.npz"
        b2.authenticate_checkpoint(path, path.with_suffix(".json"), start, stop, SPEC["b2_config_sha256"])
        with np.load(path, allow_pickle=False) as saved:
            for new, old in [("b2_num", "numerators"), ("b2_den", "denominators")]:
                if not np.array_equal(simulated[new][start:stop], saved[old]):
                    raise RuntimeError(f"Fresh C9 draws do not reproduce new-sample B2: {start}:{stop} {old}")
        checked.append({"start": start, "stop_exclusive": stop, "all_three_horizon_arrays_equal": True})
    return {"status": "C9_NEW_SAMPLE_B2_ALL_DRAW_ARRAYS_IDENTICAL", "draws": 4999,
            "reference_config_sha256": SPEC["b2_config_sha256"], "batches": checked,
            "old_sample_draws_used": False, "reference_arrays_used_only_for_validation": True}


def validate_partitions(values):
    import numpy as np
    for suffix in ("num", "den"):
        if not np.array_equal(values[f"same7_{suffix}"] + values[f"later7_{suffix}"], values[f"b2_{suffix}"][:, 2]):
            raise RuntimeError("Session partitions do not conserve the seven-day B2 totals")
        if not np.array_equal(values[f"samepool24_{suffix}"] + values[f"crosspool24_{suffix}"], values[f"b2_{suffix}"][:, 1]):
            raise RuntimeError("Pool partitions do not conserve the 24-hour B2 totals")
    for key in ("same7", "later7", "samepool24", "crosspool24"):
        if np.any(values[f"{key}_num"] > values[f"{key}_den"]) or np.any(values[f"{key}_den"] <= 0):
            raise RuntimeError(f"Invalid or unsupported pooled C9 partition: {key}")


def verify_public(root):
    path = root / "REPORT_FILE_HASHES.tsv"
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for row in rows:
        file = root / row["relative_path"]
        require_hash(file, row["sha256"], "published C9 file")
        if file.stat().st_size != int(row["bytes"]):
            raise RuntimeError("Published C9 byte size mismatch")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != {x["relative_path"] for x in rows} | {path.name}:
        raise RuntimeError("Published C9 inventory differs from its manifest")


def collect(public, desktop, config_sha):
    verify_public(public)
    desktop.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    archive = desktop / f"POOL_MAIN_C9_FRESH_RESULTS_{stamp}_{config_sha[:12]}.zip"
    common.zip_tree(public, archive)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError("Collected C9 archive failed CRC")
    common.atomic_text(Path(str(archive) + ".sha256"), common.sha256_file(archive) + "  " + archive.name + "\n")
    log(f"POOL_MAIN_C9_COMPLETE\nUpload: {archive}\nUpload: {archive}.sha256")


def execute(args):
    started = time.monotonic()
    paths = paths_for(args.project_root.resolve())
    paths["private_base"].mkdir(parents=True, exist_ok=True)
    with (paths["private_base"] / "runner.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("A C9 run is already active; do not launch another")
        c9 = load_c9()
        with heartbeat("Authenticating frozen sample, B1 inputs, chronology, and B2 reference"):
            auth, chronology, b2, pre = preflight(paths, args.workers, c9)
        config = {"authority": SPEC, "package_manifest_sha256": pre["package"]["manifest_sha256"],
                  "versions": pre["versions"], "session_gap_ms": 1800000,
                  "session_rule": "all-rated-game consecutive start gaps <30 minutes",
                  "pseudo_first_recomputed_each_draw": True, "randomization_law": "B2 fixed-total conditional Bernoulli with fixed cross-fitted propensities",
                  "new_sample": True, "ply_retrofit_included": False, "session_15_60_sensitivities_included": False}
        config_sha = hashlib.sha256(common.canonical_json(config).encode()).hexdigest()
        state = paths["private_base"] / config_sha[:12]
        public = paths["public_base"] / config_sha[:12]
        for sub in (state, state / "randomizations", state / "interrupted_checkpoints", public.parent):
            sub.mkdir(parents=True, exist_ok=True)
        envelope = {"config_sha256": config_sha, "config": config}
        config_path = state / "CONFIGURATION.json"
        if config_path.exists() and common.load_json(config_path) != envelope:
            raise RuntimeError("Existing C9 configuration differs; refusing mixed restart state")
        if not config_path.exists():
            common.atomic_json(config_path, envelope)
        common.atomic_json(state / "PREFLIGHT.json", pre)
        log(f"POOL_MAIN_C9_PREFLIGHT_READY; private restart state: {state}")
        if args.preflight_only:
            return
        if public.exists():
            success = common.load_json(public / "_SUCCESS.json")
            if success.get("config_sha256") != config_sha:
                raise RuntimeError("C9 public configuration mismatch")
            collect(public, args.desktop, config_sha)
            return
        try:
            session_cache, session_receipt = get_sessions(c9, paths, auth, chronology, state, config_sha, args.workers, args.memory_limit)
            data, _ = b2.load_inputs(paths["b1"], paths["prop"])
            chooser, sequence, session, speed = c9.load_session_vectors(session_cache)
            import numpy as np
            if not np.array_equal(chooser, data["chooser_index"]) or not np.array_equal(sequence, data["sequence_index"]):
                raise RuntimeError("B1/session row order mismatch")
            observed = c9.observed_totals(data, session, speed)
            validate_partitions(observed)
            del data, chooser, sequence, session, speed
            preserved = preserve_incomplete_batches(state, c9)
            with heartbeat("Fresh C9 randomizations: 4,999 draws, 20 checkpointed batches"):
                simulated = c9.run_randomizations(paths["b1"], paths["prop"], session_cache, paths["b2_script"], state, config_sha, args.workers)
            validate_partitions(simulated)
            array_check = compare_b2_batches(paths, simulated, b2)
            summary_check = c9.b2_validation(observed, simulated, paths["b2_public"])
            log("C9_NEW_SAMPLE_B2_ALL_4999_DRAWS_AND_SUMMARY_REPRODUCED")
            rows, contrasts, summary = c9.summarize_c9(observed, simulated)
            for row in rows:
                if row.get("epistemic_label") == "C":
                    row["holm_adjusted_p_value"] = "PENDING_NEW_SAMPLE_COMPLETE_FAMILY_RECONCILIATION"
                    row["interpretation"] = "Timing association beyond the initiating observed session; not a causal effect or unique mechanism identification"
            staging = Path(tempfile.mkdtemp(prefix="report.partial_", dir=public.parent))
            write_csv(staging / "c9_partition_components.csv", rows)
            write_csv(staging / "c9_secondary_contrasts.csv", contrasts)
            primary = next(r for r in rows if r["category"] == "later_session_7d")
            common.atomic_json(staging / "c9_primary_later_session.json", primary)
            common.atomic_json(staging / "c9_exact_b2_reproduction.json", summary_check)
            common.atomic_json(staging / "c9_b2_draw_array_reproduction.json", array_check)
            common.atomic_json(staging / "PREFLIGHT.json", pre)
            common.atomic_json(staging / "CONFIGURATION.json", {"config_sha256": config_sha, "config": config})
            for name in ("c9_b1_stage07_mapping.json", "c9_b1_stage07_mapping_attempts.json", "c9_session_mapping.json", "c9_support_frozen.json"):
                shutil.copy2(state / "sessions" / name, staging / name)
            checkpoints = []
            for start in range(0, 4999, 250):
                stop = min(start+250, 4999)
                path, receipt = c9.batch_checkpoint_paths(state, start, stop)
                checkpoints.append(c9.authenticate_checkpoint(path, receipt, start, stop, config_sha))
            common.atomic_json(staging / "CHECKPOINT_INVENTORY.json", {"batches": checkpoints, "incomplete_batches_preserved": preserved,
                               "old_C9_checkpoints_used": False, "all_batches_bound_to_new_sample": True})
            summary.update({"status": "POOL_MAIN_C9_FRESH_RANDOMIZATION_OK", "created_utc": common.utc_now(),
                            "config_sha256": config_sha, "sample_authority": pre["sample_authority"], "b1_support": {k:SPEC[k] for k in ("b1_rows","b1_choosers","b1_kind")},
                            "primary": primary, "secondary_contrasts": contrasts,
                            "original_c9_producer_recovered": True, "original_c9_source_sha256": SPEC["original_c9_source_sha256"],
                            "randomizations":4999,"new_sample_B2_draw_reproduction": True,"network_requests":0,
                            "account_level_output":False,"holm_family_adjustment_complete":False,
                            "session_15_60_sensitivities_complete":False,"ply_retrofit_complete":False,
                            "inherited_caveats":["first observed grant in the locked panel, not necessarily first lifetime grant", "repeat-granter scope", "timing evidence, not a causal claim",
                              "30-minute start-to-start session definition, not observed end-to-start", "The benchmark does not fix within-chooser game-stage composition; ply retrofit remains open"],
                            "runtime_seconds_this_invocation":time.monotonic()-started})
            common.atomic_json(staging / "summary.json", summary)
            common.atomic_json(staging / "_SUCCESS.json", {"status": summary["status"], "config_sha256":config_sha,
                               "summary_sha256":common.sha256_file(staging/"summary.json"),"randomizations":4999,
                               "exact_new_sample_b2_reproduction":True,"old_sample_draws_used":False,"account_level_output":False})
            shutil.copy2(PACKAGE / "C9_POOL_MAIN_REBINDING.md", staging / "C9_POOL_MAIN_REBINDING.md")
            common.write_manifest_tsv(staging)
            verify_public(staging)
            os.replace(staging, public)
            collect(public, args.desktop, config_sha)
        except Exception as exc:
            common.atomic_json(state / "LAST_FAILURE.json", {"time": common.utc_now(), "config_sha256":config_sha,
                               "error":f"{type(exc).__name__}: {exc}","completed_checkpoints_preserved":True})
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/Volumes/XT_Pro/lichess_kindness"))
    parser.add_argument("--desktop", type=Path, default=Path.home()/"Desktop/Lichess_Desktop")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 10:
        parser.error("workers must be between 1 and 10")
    if not args.project_root.is_dir():
        parser.error("project root is missing; connect XT_Pro")
    execute(args)


if __name__ == "__main__":
    main()
