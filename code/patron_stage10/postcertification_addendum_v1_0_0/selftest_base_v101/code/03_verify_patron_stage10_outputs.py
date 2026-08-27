#!/usr/bin/env python3
"""Independent fail-closed verification for Patron Stage 10 production."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import pandas as pd

from patron_stage10_common import (
    EXPECTED,
    PUBLIC_FORBIDDEN_COLUMN_TOKENS,
    VERSION,
    atomic_write_json,
    manifest_directory,
    runtime_record,
    sha256_file,
    verify_software_exact,
    write_manifest_tsv,
)


REQUIRED_PUBLIC = {
    "exact_mapping_resolution.json",
    "input_authorities.json",
    "preoutcome_support_receipt.json",
    "patron_outcome_semantics_qa.json",
    "return_and_patron_coverage_by_match_cell.csv",
    "profile_field_missingness_by_role.csv",
    "covariate_imputation_receipt.json",
    "raw_matched_patron_comparisons.csv",
    "common_support_samples.csv",
    "one_to_one_fixed_slots.csv",
    "repeated_rematch_long.csv",
    "repeated_rematch_summary.csv",
    "dose_response_raw_rates.csv",
    "diagnostic_kindness_raw_groups.csv",
    "diagnostic_kindness_support.csv",
    "price_side_support.csv",
    "chooser_model_coefficients.csv",
    "chooser_model_contrasts.csv",
    "chooser_models.json",
    "chooser_primary_interpretation.json",
    "opportunity_model_coefficients.csv",
    "opportunity_models.json",
    "opportunity_support.json",
}

REQUIRED_RECEIPTS = {
    "00_chooser_design_stage_success.json": "PATRON_STAGE10_CHOOSER_DESIGN_STAGE_OK",
    "chooser_cache_success.json": "PATRON_STAGE10_CHOOSER_CACHE_OK",
    "01_chooser_models_stage_success.json": "PATRON_STAGE10_CHOOSER_MODELS_OK",
    "opportunity_cache_success.json": "PATRON_STAGE10_OPPORTUNITY_CACHE_OK",
    "02_opportunity_models_stage_success.json": "PATRON_STAGE10_OPPORTUNITY_MODELS_OK",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fixture", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"Nonfinite required result: {label}")
    return number


def main() -> None:
    args = parse_args()
    started = time.time()
    output_root = args.output_root.expanduser().resolve()
    public = output_root / "public_results"
    receipts = output_root / "run_receipts"
    private = output_root / "private_cache"
    verify_software_exact(args.fixture)

    missing_public = sorted(name for name in REQUIRED_PUBLIC if not (public / name).is_file())
    if missing_public:
        raise RuntimeError(f"Required public outputs are missing: {missing_public}")
    for filename, status in REQUIRED_RECEIPTS.items():
        path = receipts / filename
        if not path.is_file():
            raise RuntimeError(f"Required stage receipt is missing: {path}")
        record = load_json(path)
        if record.get("status") != status:
            raise RuntimeError(f"Stage receipt status differs: {filename}")

    mapping = load_json(public / "exact_mapping_resolution.json")
    if mapping.get("status") != "PATRON_STAGE10_EXACT_MAPPING_RESOLVED_OK":
        raise RuntimeError("Exact mapping was not resolved")
    if mapping.get("control_order") != "control_slot=1,2,3 copied from certified plan; no reconstruction":
        raise RuntimeError("Control-order mapping changed")

    qa = load_json(public / "patron_outcome_semantics_qa.json")
    for key in [
        "returned_missing_patron",
        "unreturned_nonnull_patron",
        "true_patron_missing_field",
        "color_without_patron",
        "returned_non200",
        "unreturned_named",
    ]:
        if int(qa.get(key, -1)) != 0:
            raise RuntimeError(f"Outcome semantics QA failed: {key}")
    if not args.fixture:
        exact = {
            "rows": EXPECTED["snapshot_rows"],
            "returned_profiles": EXPECTED["returned_profiles"],
            "unreturned_profiles": EXPECTED["unreturned_profiles"],
            "patrons": EXPECTED["patrons"],
            "kind_role_patrons": EXPECTED["kind_role_patrons"],
            "control_role_patrons": EXPECTED["control_role_patrons"],
        }
        for key, expected in exact.items():
            if int(qa.get(key, -1)) != expected:
                raise RuntimeError(f"Certified aggregate was not reproduced: {key}")

    raw = pd.read_csv(public / "raw_matched_patron_comparisons.csv")
    broad = raw[raw["sample"] == "broad_any_state_acquisition_roles"]
    main = raw[raw["sample"] == "main_fair_kind_stored_1to3_available_cases"]
    if len(broad) != 1 or len(main) != 1:
        raise RuntimeError("Raw broad or primary fair-kind contrast is not unique")
    if not args.fixture:
        row = broad.iloc[0]
        if int(row["treated_n"]) != EXPECTED["kind_role_returned"]:
            raise RuntimeError("Broad kind-role denominator differs from audit")
        if int(row["control_n"]) != EXPECTED["control_role_returned"]:
            raise RuntimeError("Broad control denominator differs from audit")
        if int(row["treated_successes"]) != EXPECTED["kind_role_patrons"]:
            raise RuntimeError("Broad kind-role patrons differ from audit")
        if int(row["control_successes"]) != EXPECTED["control_role_patrons"]:
            raise RuntimeError("Broad control patrons differ from audit")
    ensure_finite(main.iloc[0]["gap_pp"], "primary raw gap")

    coefficients = pd.read_csv(public / "chooser_model_coefficients.csv")
    primary = coefficients[
        (coefficients["model"] == "main_fair_kind_1to3_01_match_cell_fe_only_HC1")
        & (coefficients["variable"] == "is_kind_role")
        & (coefficients["status"] == "estimated")
    ]
    if len(primary) != 1:
        raise RuntimeError("Primary model coefficient is missing or duplicated")
    ensure_finite(primary.iloc[0]["coefficient_pp"], "primary model coefficient")
    ensure_finite(primary.iloc[0]["se_pp"], "primary model standard error")
    if int(primary.iloc[0]["n"]) <= 0:
        raise RuntimeError("Primary model has no observations")

    rematch = pd.read_csv(public / "repeated_rematch_long.csv")
    if len(rematch) != 100 or sorted(rematch["replicate"].astype(int).tolist()) != list(range(1, 101)):
        raise RuntimeError("The 100 deterministic rematches are incomplete")
    for column in ["raw_gap_pp", "fe_gap_pp", "full_gap_pp"]:
        if not pd.to_numeric(rematch[column], errors="coerce").notna().all():
            raise RuntimeError(f"Rematch column contains failed estimates: {column}")

    slot = pd.read_csv(public / "one_to_one_fixed_slots.csv")
    if sorted(slot["control_slot"].astype(int).tolist()) != [1, 2, 3]:
        raise RuntimeError("Fixed one-to-one slots are incomplete")

    opportunity = pd.read_csv(public / "opportunity_model_coefficients.csv")
    required_opportunity_models = {
        "patron_by_five_bin_desert_gradient",
        "patron_by_favorable_price_in_fair_states",
        "patron_by_fair_state_by_favorable_price",
    }
    if not required_opportunity_models.issubset(set(opportunity["model"])):
        raise RuntimeError("Opportunity-level model family is incomplete")
    estimated_primary_terms = opportunity[
        (opportunity["primary_term"].astype(str).str.lower().isin(["true", "1"]))
        & (opportunity["status"] == "estimated")
        & (opportunity["covariance"] == "CR1_chooser")
    ]
    if estimated_primary_terms.empty:
        raise RuntimeError("No chooser-clustered opportunity-level primary terms were estimated")

    for path in public.iterdir():
        if path.is_dir():
            raise RuntimeError(f"Unexpected public subdirectory: {path}")
        if path.suffix.lower() in {".parquet", ".duckdb", ".db", ".sqlite"}:
            raise RuntimeError(f"Private-format file in public results: {path}")
        if path.suffix.lower() == ".csv":
            header = pd.read_csv(path, nrows=0).columns
            forbidden = [
                column
                for column in header
                if any(token in column.lower() for token in PUBLIC_FORBIDDEN_COLUMN_TOKENS)
            ]
            if forbidden:
                raise RuntimeError(f"Potential identifier columns in public CSV {path.name}: {forbidden}")

    private_required = {
        "chooser_design_features_private.parquet",
        "opportunity_cells_private.parquet",
    }
    if any(not (private / name).is_file() for name in private_required):
        raise RuntimeError("Required private caches are missing")

    manifest_path = public / "report_file_hashes.tsv"
    success_path = public / "_SUCCESS.json"
    manifest_path.unlink(missing_ok=True)
    success_path.unlink(missing_ok=True)
    manifest_rows = manifest_directory(public, excluded_names={"report_file_hashes.tsv", "_SUCCESS.json"})
    write_manifest_tsv(manifest_path, manifest_rows)
    success = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "version": VERSION,
        "status": "PATRON_STAGE10_PRODUCTION_CERTIFIED_OK",
        "fixture": args.fixture,
        "files_authenticated": len(manifest_rows),
        "report_file_hashes_sha256": sha256_file(manifest_path),
        "primary_model": primary.iloc[0].to_dict(),
        "privacy": {
            "usernames_in_public_results": False,
            "raw_profile_json_in_public_results": False,
            "row_level_profile_data_in_public_results": False,
            "private_caches_excluded_from_transfer": True,
        },
        "interpretation": "Current patron status is a cross-sectional stable-type association; patron timing and causal adoption are not identified.",
        "runtime_seconds": round(time.time() - started, 3),
        "runtime": runtime_record(),
    }
    atomic_write_json(success_path, success)
    print("PATRON_STAGE10_PRODUCTION_CERTIFIED_OK", flush=True)
    print(f"Files authenticated: {len(manifest_rows):,}", flush=True)
    print(f"Runtime seconds: {time.time() - started:.3f}", flush=True)


if __name__ == "__main__":
    main()
