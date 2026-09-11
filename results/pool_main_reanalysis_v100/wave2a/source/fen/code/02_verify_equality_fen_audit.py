#!/usr/bin/env python3
"""Independent aggregate verifier and success finalizer."""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import equality_fen_common as common


REQUIRED_FILES = (
    "analysis_complete.json",
    "interpretation.json",
    "receipts/input_authorities.json",
    "receipts/input_no_mutation.json",
    "receipts/position_design_receipt.json",
    "tables/equality_fe_models.csv",
    "tables/equality_raw_contrasts.csv",
    "tables/engine_eval_25cp_bins.csv",
    "tables/engine_eval_curve_by_speed.csv",
    "tables/engine_eval_density_heaping.csv",
    "tables/engine_eval_exact_cp_support.csv",
    "tables/engine_zero_models.csv",
    "tables/five_bin_by_month.csv",
    "tables/five_bin_by_ply_band.csv",
    "tables/five_bin_by_short_status.csv",
    "tables/position_commonness_implied_equality_effects.csv",
    "tables/position_commonness_models.csv",
    "tables/position_commonness_raw_rates.csv",
    "tables/position_commonness_support.csv",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def require_columns(frame: pd.DataFrame, required: set[str], name: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RuntimeError(f"{name} is missing required columns: {missing}")


def verify(args: argparse.Namespace) -> dict[str, Any]:
    package_root = args.package_root.resolve()
    root = args.public_root.resolve()
    contract = common.load_contract(package_root)
    common.verify_package_manifest(package_root)
    for relative in REQUIRED_FILES:
        if not (root / relative).is_file():
            raise RuntimeError(f"Required aggregate result is missing: {relative}")

    analysis = common.load_json(root / "analysis_complete.json")
    interpretation = common.load_json(root / "interpretation.json")
    no_mutation = common.load_json(root / "receipts/input_no_mutation.json")
    design = common.load_json(root / "receipts/position_design_receipt.json")
    if analysis.get("status") != "POOL_MAIN_EQUALITY_FEN_ANALYSIS_STAGE_COMPLETE":
        raise RuntimeError("Analysis-stage status is invalid")
    if bool(analysis.get("synthetic")) != bool(args.synthetic):
        raise RuntimeError("Synthetic/production status changed")
    if no_mutation.get("status") != "AUTHENTICATED_INPUTS_UNCHANGED_AFTER_ANALYSIS":
        raise RuntimeError("Input no-mutation receipt is invalid")
    if design.get("status") != common.DESIGN_STATUS:
        raise RuntimeError("Outcome-blind design status is invalid")
    if design.get("outcome_columns_read") != []:
        raise RuntimeError("Outcome-blind design reports outcome access")
    if design.get("fen_strings_retained_in_cache") is not False:
        raise RuntimeError("Outcome-blind design retained raw FEN strings")

    expected_rows = int(analysis["sample"]["stage07_rows"])
    expected_kinds = int(analysis["sample"]["stage07_kind_draws"])
    expected_short = int(analysis["sample"]["short_rows"])
    if not args.synthetic:
        if expected_rows != int(contract["stage07"]["rows"]):
            raise RuntimeError("Stage 07 row total changed")
        if expected_kinds != int(contract["stage07"]["kind_draws"]):
            raise RuntimeError("Stage 07 outcome total changed")
        if expected_short != int(contract["stage07"]["short_rows_ply_le_10"]):
            raise RuntimeError("Stage 07 short-row total changed")

    five_ply = pd.read_csv(root / "tables/five_bin_by_ply_band.csv")
    require_columns(
        five_ply,
        {"ply_band","fairness_bin","rows","kind_draws","kind_rate_pct"},
        "five_bin_by_ply_band",
    )
    if int(five_ply.rows.sum()) != expected_rows:
        raise RuntimeError("Five-bin-by-ply rows do not conserve")
    if int(five_ply.kind_draws.sum()) != expected_kinds:
        raise RuntimeError("Five-bin-by-ply outcomes do not conserve")
    if set(five_ply.fairness_bin) != {
        "disconnected_clearly_better",
        "disconnected_better",
        "roughly_equal",
        "modestly_worse_excluded",
        "clearly_worse",
    }:
        raise RuntimeError("Five-bin labels changed")

    five_short = pd.read_csv(root / "tables/five_bin_by_short_status.csv")
    if int(five_short.rows.sum()) != expected_rows:
        raise RuntimeError("Five-bin-by-short rows do not conserve")
    observed_short = int(five_short.loc[five_short.short_status == "ply_le_10", "rows"].sum())
    if observed_short != expected_short:
        raise RuntimeError("Short-row authority changed")

    raw = pd.read_csv(root / "tables/equality_raw_contrasts.csv")
    require_columns(
        raw,
        {
            "contrast_family","roughly_equal_rows","disconnected_better_rows",
            "equal_minus_better_pp","independent_binomial_se_pp",
        },
        "equality_raw_contrasts",
    )
    overall = raw.loc[raw.contrast_family == "overall"]
    if len(overall) != 1:
        raise RuntimeError("Canonical raw equality contrast is missing or duplicated")
    if not args.synthetic:
        certified = contract["stage08"]["known_raw_rates"]
        row = overall.iloc[0]
        if int(row.roughly_equal_rows) != int(certified["roughly_equal_rows"]):
            raise RuntimeError("Raw equality rows do not reproduce Stage 08")
        if int(row.disconnected_better_rows) != int(certified["disconnected_better_rows"]):
            raise RuntimeError("Raw better rows do not reproduce Stage 08")

    models = pd.read_csv(root / "tables/equality_fe_models.csv")
    require_columns(
        models,
        {
            "status","model_id","variable","coefficient_pp","se_pp","t",
            "rows_raw","chooser_clusters","matrix_rank","absorption_method",
        },
        "equality_fe_models",
    )
    required_models = {
        "E0_raw","E1_chooser_fe","E2_primary_modern_analogue",
        "E3_price_adjusted","E4_game_stage_adjusted","E5_short_interaction",
        "E6_short_only","E7_long_only",
    }
    estimated_ids = set(models.loc[models.status == "ESTIMATED", "model_id"])
    if not required_models <= estimated_ids:
        raise RuntimeError(
            f"Required equality models are not all estimated: {sorted(required_models - estimated_ids)}"
        )
    raw_model = models.loc[
        (models.model_id == "E0_raw") & (models.variable == "roughly_equal")
    ]
    if len(raw_model) != 1:
        raise RuntimeError("Raw regression equality coefficient is missing")
    if not math.isclose(
        float(raw_model.iloc[0].coefficient_pp),
        float(overall.iloc[0].equal_minus_better_pp),
        rel_tol=0.0,
        abs_tol=1e-10,
    ):
        raise RuntimeError("Raw regression does not reproduce the raw equality contrast")
    tolerance = float(contract["analysis"]["fixed_effect_tolerance"])
    absorbed = models.loc[
        (models.status == "ESTIMATED") & (models.absorption_method != "none")
    ]
    if (
        absorbed["absorption_max_scaled_group_mean"].fillna(np.inf)
        > tolerance * 1.01
    ).any():
        raise RuntimeError("Equality fixed-effect orthogonality exceeds tolerance")

    commonness = pd.read_csv(root / "tables/position_commonness_models.csv")
    required_commonness = {
        "C0_short_baseline","C1_fen4_commonness",
        "C2_board_commonness","C3_fen4_price_adjusted",
    }
    if not required_commonness <= set(
        commonness.loc[commonness.status == "ESTIMATED", "model_id"]
    ):
        raise RuntimeError("Required position-commonness models are incomplete")
    implied = pd.read_csv(
        root / "tables/position_commonness_implied_equality_effects.csv"
    )
    if len(implied) != 9 or set(implied.commonness_quantile) != {0.1, 0.5, 0.9}:
        raise RuntimeError("Position-commonness implied-effect grid changed")
    position_raw = pd.read_csv(root / "tables/position_commonness_raw_rates.csv")
    if int(position_raw.rows.sum()) != 2 * expected_short:
        raise RuntimeError("Stacked FEN4/board commonness rows do not conserve")
    if set(position_raw.signature_type) != {"fen4", "board"}:
        raise RuntimeError("Position signature labels changed")

    engine = pd.read_csv(root / "tables/engine_zero_models.csv")
    require_columns(
        engine,
        {
            "status","model_id","analysis_role","knot_cp","window_cp",
            "statistic","estimate_pp","se_pp","t","p_normal_approx",
        },
        "engine_zero_models",
    )
    primary = engine.loc[
        (engine.analysis_role == "engine_zero_primary")
        & (engine.status == "ESTIMATED")
        & (engine.statistic == "derivative_change_right_plus_left_distance")
    ]
    if set(primary.window_cp.astype(int)) != set(
        int(value) for value in contract["analysis"]["engine_zero_windows_cp"]
    ):
        raise RuntimeError("Primary engine-zero bandwidth grid changed")
    placebos = engine.loc[
        (engine.analysis_role == "engine_placebo_knot")
        & (engine.status == "ESTIMATED")
        & (engine.statistic == "derivative_change_right_plus_left_distance")
    ]
    if set(placebos.knot_cp.astype(int)) != set(
        int(value) for value in contract["analysis"]["engine_placebo_knots_cp"]
    ):
        raise RuntimeError("Engine placebo-knot grid changed")
    estimated_engine = engine.loc[
        (engine.status == "ESTIMATED")
        & engine.absorption_max_scaled_group_mean.notna()
    ]
    if (
        estimated_engine.absorption_max_scaled_group_mean > tolerance * 1.01
    ).any():
        raise RuntimeError("Engine fixed-effect orthogonality exceeds tolerance")

    if interpretation.get("causal_language_authorized") is not False:
        raise RuntimeError("Interpretation improperly authorizes causal language")
    if interpretation["rating_payoff_zero"]["addressed_by_this_package"] is not False:
        raise RuntimeError("Engine-zero package conflates rating-payoff zero")

    privacy = common.privacy_scan_public_output(root)
    verification = {
        "status": common.VERIFY_STATUS,
        "verified_at_utc": common.utc_now(),
        "synthetic": bool(args.synthetic),
        "required_files": len(REQUIRED_FILES),
        "stage07_rows": expected_rows,
        "stage07_kind_draws": expected_kinds,
        "short_rows": expected_short,
        "stage08_raw_reproduction_required": not args.synthetic,
        "stage08_raw_reproduction_ok": bool(
            args.synthetic or analysis["raw"]["stage08_raw_reproduction_ok"]
        ),
        "fixed_effect_tolerance": tolerance,
        "privacy": privacy,
        "input_no_mutation": True,
        "causal_claims_authorized": False,
    }
    common.atomic_write_json(root / "independent_verification.json", verification)
    privacy = common.privacy_scan_public_output(root)
    verification["privacy"] = privacy
    common.atomic_write_json(root / "independent_verification.json", verification)

    manifest = common.make_report_manifest(
        root,
        excluded_names=("report_file_hashes.tsv", "_SUCCESS.json"),
    )
    manifest_path = root / "report_file_hashes.tsv"
    root.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(manifest_path, sep="\t", index=False, lineterminator="\n")
    manifest_check = common.verify_report_manifest(root, manifest_path)
    success = {
        "status": common.PUBLIC_STATUS,
        "created_at_utc": common.utc_now(),
        "synthetic": bool(args.synthetic),
        "verification_status": common.VERIFY_STATUS,
        "stage07_rows": expected_rows,
        "stage07_kind_draws": expected_kinds,
        "short_rows": expected_short,
        "sample_fingerprint": (
            None if args.synthetic else contract["stage07"]["sample_fingerprint"]
        ),
        "main_predicate": (
            None if args.synthetic else contract["stage07"]["main_predicate"]
        ),
        "observed_screen_certified": (
            None if args.synthetic else contract["stage07"]["observed_screen_certified"]
        ),
        "literal_immediate_rematches_certified": (
            None
            if args.synthetic
            else contract["stage07"]["literal_immediate_rematches_certified"]
        ),
        "report_files": manifest_check["files"],
        "report_bytes": manifest_check["bytes"],
        "report_manifest_sha256": manifest_check["manifest_sha256"],
        "raw_bump": interpretation["raw_bump"],
        "adjusted_bump": interpretation["adjusted_bump"],
        "short_game_concentration": interpretation["short_game_concentration"],
        "engine_zero_placebo_uniqueness": interpretation[
            "engine_zero_placebo_uniqueness"
        ],
        "position_commonness_causal_explanation_claim_generated": False,
        "rating_payoff_zero_next": "completed in pool-main Wave 1 controlled-reference module",
    }
    common.atomic_write_json(root / "_SUCCESS.json", success)
    common.verify_report_manifest(root, manifest_path)
    return success


def self_test() -> None:
    adjusted = common.holm_adjust([0.01, 0.04, 0.20, 0.5, 0.8])
    if not np.allclose(adjusted, [0.05, 0.16, 0.6, 1.0, 1.0]):
        raise RuntimeError(f"Verifier Holm self-test failed: {adjusted}")
    if len(REQUIRED_FILES) < 15:
        raise RuntimeError("Verifier required-output inventory unexpectedly small")
    print("KINDNESS_EQUALITY_FEN_VERIFIER_SELFTEST_OK")


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    success = verify(args)
    print(common.VERIFY_STATUS)
    print(common.PUBLIC_STATUS)
    print(f"Report files authenticated: {success['report_files']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
