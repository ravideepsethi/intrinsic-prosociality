#!/usr/bin/env python3
"""Independent fail-closed verifier for the Patron Stage 10 addendum."""

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
    read_manifest_tsv,
    runtime_record,
    sha256_file,
    verify_software_exact,
    write_manifest_tsv,
)


REQUIRED_PUBLIC = {
    "base_v101_authentication.json",
    "corrected_covariate_missingness.json",
    "corrected_rich_control_coefficients.csv",
    "corrected_rich_control_models.json",
    "corrected_vs_certified_comparison.json",
    "five_bin_chooser_support.csv",
    "five_bin_chooser_raw_rates.csv",
    "five_bin_chooser_coefficients.csv",
    "five_bin_chooser_contrasts.csv",
    "five_bin_chooser_models.json",
    "price_count_rate_support.csv",
    "price_count_rate_coefficients.csv",
    "price_count_rate_contrasts.csv",
    "price_count_rate_models.json",
    "postcertification_interpretation.json",
}

FIVE_TERMS = {
    "ever_kind_eval_clearly_better",
    "ever_kind_eval_better",
    "ever_kind_eval_roughly_equal",
    "ever_kind_eval_modestly_worse",
    "ever_kind_eval_clearly_worse",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--fixture", action="store_true")
    return parser.parse_args()


def strict_load(path: Path) -> Any:
    def reject(value: str) -> None:
        raise ValueError(f"Non-RFC JSON constant {value!r} in {path}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)


def finite(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(f"Required result is nonfinite: {label}")
    return number


def require_term(frame: pd.DataFrame, model: str, variable: str) -> pd.Series:
    rows = frame[
        frame["model"].eq(model)
        & frame["variable"].eq(variable)
        & frame["status"].eq("estimated")
    ]
    if len(rows) != 1:
        raise RuntimeError(f"Required coefficient is not unique: {model} / {variable}")
    row = rows.iloc[0]
    finite(row["coefficient_pp"], f"{model}:{variable}:coefficient")
    finite(row["se_pp"], f"{model}:{variable}:se")
    if int(row["n"]) <= 0:
        raise RuntimeError(f"Required coefficient has no observations: {model} / {variable}")
    return row


def main() -> None:
    args = parse_args()
    started = time.time()
    output_root = args.output_root.expanduser().resolve()
    public = output_root / "public_results"
    receipts = output_root / "run_receipts"
    verify_software_exact(args.fixture)

    missing = sorted(name for name in REQUIRED_PUBLIC if not (public / name).is_file())
    if missing:
        raise RuntimeError(f"Required public addendum outputs are missing: {missing}")
    stage_path = receipts / "00_postcertification_addendum_stage_success.json"
    if not stage_path.is_file():
        raise RuntimeError("Addendum stage receipt is missing")

    stage = strict_load(stage_path)
    if stage.get("status") != "PATRON_STAGE10_POSTCERT_ADDENDUM_STAGE_OK":
        raise RuntimeError("Addendum stage status is invalid")
    stage_hashes = stage.get("public_output_hashes") or {}
    if set(stage_hashes) != REQUIRED_PUBLIC:
        raise RuntimeError("Addendum stage output set differs from the frozen contract")
    for name, expected in stage_hashes.items():
        path = public / name
        if sha256_file(path) != expected:
            raise RuntimeError(f"Addendum stage output failed authentication: {name}")

    for path in sorted(public.glob("*.json")):
        strict_load(path)
    authentication = strict_load(public / "base_v101_authentication.json")
    if authentication.get("status") != "PATRON_STAGE10_V101_BASE_AUTHENTICATED_OK":
        raise RuntimeError("Certified base authentication record is invalid")
    if authentication.get("base_lineage_modified") is not False:
        raise RuntimeError("Certified base lineage was not preserved")

    missingness = strict_load(public / "corrected_covariate_missingness.json")
    diagnostics = missingness.get("diagnostics") or {}
    created_missing = int((diagnostics.get("account_age_days_at_query") or {}).get("missing", -1))
    seen_missing = int((diagnostics.get("days_since_seen_at_query") or {}).get("missing", -1))
    if created_missing <= 0 or seen_missing <= 0:
        raise RuntimeError("Corrected account-date missingness indicators were not retained")
    if not args.fixture and (created_missing != 69_094 or seen_missing != 69_094):
        raise RuntimeError(
            "Corrected account-date missingness differs from the authenticated snapshot audit"
        )

    rich = pd.read_csv(public / "corrected_rich_control_coefficients.csv")
    corrected = require_term(rich, "corrected_dates_all_controls_HC1", "is_kind_role")
    require_term(rich, "corrected_dates_all_controls_CR1", "is_kind_role")
    require_term(
        rich,
        "corrected_dates_all_controls_exclude_disabled_or_tos_HC1",
        "is_kind_role",
    )
    comparison = strict_load(public / "corrected_vs_certified_comparison.json")
    if comparison.get("certified_primary_model_unchanged") is not True:
        raise RuntimeError("Certified primary was not preserved")
    finite(
        comparison.get("certified_v101_full_control_coefficient_pp"),
        "certified full-control comparison",
    )
    if not math.isclose(
        finite(comparison.get("corrected_date_full_control_coefficient_pp"), "corrected comparison"),
        float(corrected["coefficient_pp"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise RuntimeError("Corrected comparison differs from the coefficient table")

    fairness_support = pd.read_csv(public / "five_bin_chooser_support.csv")
    if sorted(fairness_support["minimum_opportunities_in_each_of_five_bins"].astype(int)) != [0, 2, 4]:
        raise RuntimeError("Five-bin support thresholds are incomplete")
    if (fairness_support["users"] <= 0).any():
        raise RuntimeError("Five-bin support contains an empty sample")
    fairness = pd.read_csv(public / "five_bin_chooser_coefficients.csv")
    for term in FIVE_TERMS:
        require_term(fairness, "five_bin_chooser_min4_full_HC1", term)
        require_term(fairness, "five_bin_chooser_min4_full_CR1", term)
    fairness_contrasts = pd.read_csv(public / "five_bin_chooser_contrasts.csv")
    required_contrast = fairness_contrasts[
        fairness_contrasts["model"].eq("five_bin_chooser_min4_full_HC1")
        & fairness_contrasts["contrast"].eq("clearly_better_minus_clearly_worse")
        & fairness_contrasts["status"].eq("estimated")
    ]
    if len(required_contrast) != 1:
        raise RuntimeError("Five-bin endpoint contrast is missing")
    finite(required_contrast.iloc[0]["difference_pp"], "five-bin endpoint contrast")

    price_support = pd.read_csv(public / "price_count_rate_support.csv")
    if sorted(price_support["minimum_opportunities_each_price_side"].astype(int)) != [2, 4]:
        raise RuntimeError("Price count/rate support thresholds are incomplete")
    if (price_support["users"] <= 0).any():
        raise RuntimeError("Price count/rate support contains an empty sample")
    price = pd.read_csv(public / "price_count_rate_coefficients.csv")
    price_terms = {
        "price_count_min4_full_HC1": [
            "log1p_fair_costly_kind_count",
            "log1p_fair_nonnegative_kind_count",
        ],
        "price_rate_min4_full_HC1": [
            "fair_costly_kind_rate",
            "fair_nonnegative_kind_rate",
        ],
        "price_count_min4_full_CR1": [
            "log1p_fair_costly_kind_count",
            "log1p_fair_nonnegative_kind_count",
        ],
        "price_rate_min4_full_CR1": [
            "fair_costly_kind_rate",
            "fair_nonnegative_kind_rate",
        ],
    }
    for model, terms in price_terms.items():
        for term in terms:
            require_term(price, model, term)

    interpretation = strict_load(public / "postcertification_interpretation.json")
    if interpretation.get("base_certification_preserved") is not True:
        raise RuntimeError("Addendum interpretation does not preserve the base certification")
    if interpretation.get("primary_estimand_rerun") is not False:
        raise RuntimeError("Addendum improperly claims to rerun the primary estimand")

    for path in public.iterdir():
        if path.is_dir():
            raise RuntimeError(f"Unexpected public subdirectory: {path}")
        if path.suffix.lower() in {".parquet", ".duckdb", ".db", ".sqlite"}:
            raise RuntimeError(f"Private-format file in public output: {path}")
        if path.suffix.lower() == ".csv":
            columns = pd.read_csv(path, nrows=0).columns
            forbidden = [
                column
                for column in columns
                if any(token in column.lower() for token in PUBLIC_FORBIDDEN_COLUMN_TOKENS)
            ]
            if forbidden:
                raise RuntimeError(f"Potential identifier columns in {path.name}: {forbidden}")

    manifest_path = public / "report_file_hashes.tsv"
    success_path = public / "_SUCCESS.json"
    manifest_path.unlink(missing_ok=True)
    success_path.unlink(missing_ok=True)
    rows = manifest_directory(public, excluded_names={"report_file_hashes.tsv", "_SUCCESS.json"})
    write_manifest_tsv(manifest_path, rows)

    five_endpoint = required_contrast.iloc[0]
    price_contrasts = pd.read_csv(public / "price_count_rate_contrasts.csv")
    selected_price = price_contrasts[
        price_contrasts["model"].isin(
            ["price_count_min4_full_HC1", "price_rate_min4_full_HC1"]
        )
        & price_contrasts["status"].eq("estimated")
    ]
    if len(selected_price) != 2:
        raise RuntimeError("Min-4 full price count/rate contrasts are incomplete")

    success = {
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "version": VERSION,
        "status": "PATRON_STAGE10_POSTCERTIFICATION_ADDENDUM_CERTIFIED_OK",
        "fixture": args.fixture,
        "files_authenticated": len(rows),
        "report_file_hashes_sha256": sha256_file(manifest_path),
        "base_v101_status": authentication.get("base_status"),
        "base_primary_coefficient_pp": authentication.get("base_primary_coefficient_pp"),
        "corrected_rich_control_coefficient_pp": float(corrected["coefficient_pp"]),
        "five_bin_min4_full_endpoint_contrast_pp": float(five_endpoint["difference_pp"]),
        "price_min4_full_standardized_contrasts": selected_price[
            ["model", "contrast", "difference_pp", "se_pp", "p_two_sided_approx"]
        ].to_dict(orient="records"),
        "privacy": {
            "usernames_in_public_results": False,
            "row_level_profile_data_in_public_results": False,
            "private_caches_excluded_from_transfer": True,
        },
        "interpretation": (
            "Separate secondary/sensitivity addendum. The certified v1.0.1 primary remains "
            "unchanged; current patron status is cross-sectional, not patron adoption or causality."
        ),
        "runtime_seconds": round(time.time() - started, 3),
        "runtime": runtime_record(),
    }
    atomic_write_json(success_path, success)
    strict_load(success_path)
    print("PATRON_STAGE10_POSTCERTIFICATION_ADDENDUM_CERTIFIED_OK", flush=True)
    print(f"Files authenticated: {len(rows):,}", flush=True)
    print(f"Runtime seconds: {time.time() - started:.3f}", flush=True)


if __name__ == "__main__":
    main()
