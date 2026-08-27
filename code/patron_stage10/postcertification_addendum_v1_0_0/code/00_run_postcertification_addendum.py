#!/usr/bin/env python3
"""Run the separate Patron Stage 10 post-certification addendum.

This program authenticates, but never modifies, the certified v1.0.1 output.
It adds three secondary/sensitivity families identified by the final audit:

1. rich-control models with explicit missing account-date handling;
2. chooser-level kindness indicators across all five fairness bins; and
3. price-side count and rate companions.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from patron_stage10_common import (
    EXPECTED,
    VERSION,
    atomic_write_json,
    coefficient_difference,
    connect_database,
    contrast_from_frame,
    fit_absorbed_ols,
    impute_within_cell,
    read_manifest_tsv,
    runtime_record,
    sha256_file,
    sql_string,
    utc_now,
    verify_manifest,
    verify_software_exact,
    write_csv,
)


BASE_PUBLIC_SUCCESS_SHA256 = "5ee2169e3b87a0e1064e0d2953f6c5288e65287de7bdc4a5a1f26ae6e2ec2b0a"
BASE_REPORT_MANIFEST_SHA256 = "4a3b082e655de50c5bc554d1b684387f4ed9ef7da24745d65b9c9c919b8f3f2d"
BASE_RECEIPT_SHA256 = {
    "00_chooser_design_stage_success.json": "cbc8e0b963adafb57931cc66e4a92581bc3f74cbb81c8d0cf500138931a50a20",
    "01_chooser_models_stage_success.json": "6cf65ef7c11118bc978da4a5c8e97aa50b4dc5d50fcd2173edb05f29edd7d4fe",
    "02_opportunity_models_stage_success.json": "12c80506ec375e43dfdd286f51e5ca80e27a2ade1cd8d03276979de8ba81cf9e",
    "chooser_cache_success.json": "1fd93eb66d210e537a5a9bb414bdc9ed4524961b94fcdde6b99e5829ec687722",
    "opportunity_cache_success.json": "cacba97efa97626bda5d602677544254b0c7375d840340c0d5094f6aceca8f2c",
}
BASE_CHOOSER_CACHE_SHA256 = "a0be630ac68f3624b35b0c3d388bc34ecb35be7575c7b911acbf4322354baeee"
BASE_OPPORTUNITY_CACHE_SHA256 = "f6ee10fc947776601d513f40ede3d1d897db03ffba1121db68450ac204d3ee80"
BASE_PRIMARY_MODEL = "main_fair_kind_1to3_01_match_cell_fe_only_HC1"
BASE_FULL_MODEL = "main_fair_kind_1to3_08_all_controls_HC1"

FAIRNESS_BINS: list[tuple[str, str]] = [
    ("disconnected_clearly_better", "clearly_better"),
    ("disconnected_better", "better"),
    ("roughly_equal", "roughly_equal"),
    ("modestly_worse_excluded", "modestly_worse"),
    ("clearly_worse", "clearly_worse"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--base-output-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--fixture", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def authenticate_base(
    project_root: Path,
    base_root: Path,
    *,
    fixture: bool,
) -> tuple[dict[str, Any], Path, Path, Path]:
    public = base_root / "public_results"
    receipts = base_root / "run_receipts"
    private = base_root / "private_cache"
    snapshot = (
        project_root
        / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED"
        / "profile_snapshot_24m_private_lossless.parquet"
    )
    success_path = public / "_SUCCESS.json"
    report_manifest = public / "report_file_hashes.tsv"
    chooser_cache = private / "chooser_design_features_private.parquet"
    opportunity_cache = private / "opportunity_cells_private.parquet"

    required = [
        snapshot,
        success_path,
        report_manifest,
        chooser_cache,
        opportunity_cache,
        public / "chooser_model_coefficients.csv",
    ] + [receipts / name for name in BASE_RECEIPT_SHA256]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required certified-base files are missing: {missing}")

    success = load_json(success_path)
    if success.get("status") != "PATRON_STAGE10_PRODUCTION_CERTIFIED_OK":
        raise RuntimeError("The base production status is not certified OK")
    verify_manifest(public, report_manifest)

    chooser_receipt = load_json(receipts / "chooser_cache_success.json")
    opportunity_receipt = load_json(receipts / "opportunity_cache_success.json")
    if chooser_receipt.get("cache_sha256") != sha256_file(chooser_cache):
        raise RuntimeError("Certified chooser cache failed its receipt")
    if opportunity_receipt.get("cache_sha256") != sha256_file(opportunity_cache):
        raise RuntimeError("Certified opportunity cache failed its receipt")

    if not fixture:
        exact = {
            "snapshot_sha256": (sha256_file(snapshot), EXPECTED["snapshot_sha256"]),
            "base_success_sha256": (sha256_file(success_path), BASE_PUBLIC_SUCCESS_SHA256),
            "base_manifest_sha256": (sha256_file(report_manifest), BASE_REPORT_MANIFEST_SHA256),
            "success_manifest_reference": (
                success.get("report_file_hashes_sha256"),
                BASE_REPORT_MANIFEST_SHA256,
            ),
            "chooser_cache_sha256": (sha256_file(chooser_cache), BASE_CHOOSER_CACHE_SHA256),
            "opportunity_cache_sha256": (
                sha256_file(opportunity_cache),
                BASE_OPPORTUNITY_CACHE_SHA256,
            ),
        }
        for filename, expected_sha in BASE_RECEIPT_SHA256.items():
            exact[f"receipt:{filename}"] = (sha256_file(receipts / filename), expected_sha)
        failures = {
            name: {"observed": observed, "expected": expected}
            for name, (observed, expected) in exact.items()
            if observed != expected
        }
        if failures:
            raise RuntimeError(f"Certified v1.0.1 base authentication failed: {failures}")

    primary_frame = pd.read_csv(public / "chooser_model_coefficients.csv")
    primary = primary_frame[
        primary_frame["model"].eq(BASE_PRIMARY_MODEL)
        & primary_frame["variable"].eq("is_kind_role")
        & primary_frame["status"].eq("estimated")
    ]
    full = primary_frame[
        primary_frame["model"].eq(BASE_FULL_MODEL)
        & primary_frame["variable"].eq("is_kind_role")
        & primary_frame["status"].eq("estimated")
    ]
    if len(primary) != 1 or len(full) != 1:
        raise RuntimeError("Certified primary or full-control coefficient is not unique")

    authentication = {
        "created_utc": utc_now(),
        "status": "PATRON_STAGE10_V101_BASE_AUTHENTICATED_OK",
        "fixture": fixture,
        "base_status": success["status"],
        "base_success_sha256": sha256_file(success_path),
        "base_report_manifest_sha256": sha256_file(report_manifest),
        "base_report_files_authenticated": len(read_manifest_tsv(report_manifest)),
        "snapshot_sha256": sha256_file(snapshot),
        "chooser_cache_sha256": sha256_file(chooser_cache),
        "opportunity_cache_sha256": sha256_file(opportunity_cache),
        "base_primary_coefficient_pp": float(primary.iloc[0]["coefficient_pp"]),
        "base_full_control_coefficient_pp": float(full.iloc[0]["coefficient_pp"]),
        "base_lineage_modified": False,
    }
    return authentication, snapshot, chooser_cache, opportunity_cache


def prepare_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]], dict[str, Any]]:
    """Recreate the v1.0.1 control set after corrected date construction."""
    out = frame.copy()
    out["patron"] = out["patron"].astype(bool).astype(np.int8)
    out["patron_pp"] = 100.0 * out["patron"].astype(float)
    out["is_kind_role"] = pd.to_numeric(out["is_kind_role"], errors="raise").astype(np.int8)
    for name in [
        "ever_kind_fair_state",
        "ever_kind_clearly_worse_state",
        "ever_kind_fair_costly",
        "ever_kind_fair_nonnegative",
    ]:
        out[name] = pd.to_numeric(out[name], errors="coerce").fillna(0).astype(np.int8)
    out["log_fair_opps"] = np.log1p(pd.to_numeric(out["fair_opps"], errors="coerce"))
    out["log_total_opps"] = np.log1p(pd.to_numeric(out["total_opps"], errors="coerce"))
    out["log_clearly_worse_opps"] = np.log1p(pd.to_numeric(out["clearly_worse_opps"], errors="coerce"))
    out["log_fair_costly_opps"] = np.log1p(pd.to_numeric(out["fair_costly_opps"], errors="coerce"))
    out["log_fair_nonnegative_opps"] = np.log1p(pd.to_numeric(out["fair_nonnegative_opps"], errors="coerce"))

    profile_raw = [
        "account_age_days_at_query",
        "days_since_seen_at_query",
        "play_time_total_seconds",
        "count_all",
        "count_rated",
        "count_win",
        "count_loss",
        "count_draw",
        "current_bullet_rating",
        "current_blitz_rating",
        "current_rapid_rating",
        "current_classical_rating",
        "current_correspondence_rating",
        "current_bullet_games",
        "current_blitz_games",
        "current_rapid_games",
        "current_classical_games",
    ]
    out, missing_indicators, imputation = impute_within_cell(out, profile_raw, "match_cell")
    out["log_playtime_total"] = np.log1p(np.maximum(out["play_time_total_seconds"], 0.0))
    for column in [
        "count_all",
        "count_rated",
        "current_bullet_games",
        "current_blitz_games",
        "current_rapid_games",
        "current_classical_games",
    ]:
        out[f"log1p_{column}"] = np.log1p(np.maximum(out[column], 0.0))

    for level in ["1200_1599", "1600_1999", "2000_2399", "2400_plus"]:
        out[f"rating_tier_{level}"] = (out["rating_tier"].astype(str) == level).astype(np.int8)

    exposure_volume = ["log_fair_opps", "log_total_opps"]
    profile_tenure = [
        "account_age_days_at_query",
        "days_since_seen_at_query",
        "log_playtime_total",
        "account_age_days_at_query__missing",
        "days_since_seen_at_query__missing",
        "play_time_total_seconds__missing",
    ]
    board_state = [
        "share_eval_disconnected_better",
        "share_eval_roughly_equal",
        "share_eval_modestly_worse",
        "share_eval_clearly_worse",
        "mean_eval_capped600",
        "share_fair",
        "share_clearly_worse",
    ]
    price = [
        "share_fair_nonnegative",
        "share_fair_costly",
        "panel_mean_draw_payoff_fair",
        "panel_mean_win_premium_fair",
    ]
    engagement = [
        "active_months",
        "share_speed_bullet",
        "share_speed_blitz",
        "share_speed_rapid",
        "share_speed_classical_long",
        "share_speed_other",
        "share_tournament",
        "log1p_count_all",
        "log1p_count_rated",
        "log1p_current_bullet_games",
        "log1p_current_blitz_games",
        "log1p_current_rapid_games",
        "log1p_current_classical_games",
        "count_all__missing",
        "count_rated__missing",
        "current_bullet_games__missing",
        "current_blitz_games__missing",
        "current_rapid_games__missing",
        "current_classical_games__missing",
    ]
    skill = [
        "mean_chooser_elo",
        "sd_chooser_elo",
        "rating_tier_1200_1599",
        "rating_tier_1600_1999",
        "rating_tier_2000_2399",
        "rating_tier_2400_plus",
        "current_bullet_rating",
        "current_blitz_rating",
        "current_rapid_rating",
        "current_classical_rating",
        "current_correspondence_rating",
        "current_bullet_rating__missing",
        "current_blitz_rating__missing",
        "current_rapid_rating__missing",
        "current_classical_rating__missing",
        "current_correspondence_rating__missing",
    ]
    controls = list(
        dict.fromkeys(exposure_volume + profile_tenure + board_state + price + engagement + skill)
    )
    binary = set(missing_indicators) | {
        name for name in controls if name.startswith("rating_tier_")
    }
    standardize = [name for name in controls if name not in binary]
    return out, {"all": controls, "standardize": standardize}, imputation


class Collector:
    def __init__(self) -> None:
        self.models: list[dict[str, Any]] = []
        self.coefficients: list[pd.DataFrame] = []
        self.contrasts: list[dict[str, Any]] = []

    def run(
        self,
        frame: pd.DataFrame,
        *,
        name: str,
        regressors: Sequence[str],
        standardize: Iterable[str],
        covariance: str = "HC1",
        differences: Sequence[tuple[str, str, str]] = (),
        estimand_class: str = "postcertification_sensitivity",
    ):
        result = fit_absorbed_ols(
            frame,
            model_name=name,
            y_col="patron_pp",
            regressors=list(dict.fromkeys(regressors)),
            fe_col="match_cell",
            covariance=covariance,
            cluster_col="match_cell" if covariance == "CR1" else None,
            standardize=standardize,
            estimand_class=estimand_class,
        )
        self.models.append(result.model)
        self.coefficients.append(result.coefficients)
        for first, second, label in differences:
            record = coefficient_difference(result, first, second, label)
            record["estimand_class"] = estimand_class
            self.contrasts.append(record)
        return result

    def coefficient_frame(self) -> pd.DataFrame:
        return pd.concat(self.coefficients, ignore_index=True) if self.coefficients else pd.DataFrame()


def load_analysis_frame(
    database,
    snapshot: Path,
    chooser_cache: Path,
    opportunity_cache: Path,
) -> pd.DataFrame:
    bin_columns: list[str] = []
    for source, alias in FAIRNESS_BINS:
        bin_columns.extend(
            [
                f"SUM(opportunities) FILTER (WHERE fairness_bin={sql_string(source)})::BIGINT AS eval_{alias}_opps",
                f"SUM(kind_draws) FILTER (WHERE fairness_bin={sql_string(source)})::BIGINT AS eval_{alias}_kind_count",
            ]
        )
    bin_sql = ",\n".join(bin_columns)
    query = f"""
      WITH bins AS (
        SELECT username_norm, {bin_sql}
        FROM read_parquet({sql_string(opportunity_cache)})
        GROUP BY username_norm
      ), s AS (
        SELECT username_norm, returned, patron
        FROM read_parquet({sql_string(snapshot)})
      ), joined AS (
        SELECT
          d.* EXCLUDE(account_age_days_at_query, days_since_seen_at_query),
          s.returned,
          s.patron,
          CASE
            WHEN d.created_at_ms IS NULL
              OR try_cast(d.queried_at_utc AS TIMESTAMPTZ) IS NULL THEN NULL
            ELSE greatest(
              0.0,
              (epoch_ms(try_cast(d.queried_at_utc AS TIMESTAMPTZ))-d.created_at_ms)/86400000.0
            )
          END::DOUBLE AS account_age_days_at_query,
          CASE
            WHEN d.seen_at_ms IS NULL
              OR try_cast(d.queried_at_utc AS TIMESTAMPTZ) IS NULL THEN NULL
            ELSE greatest(
              0.0,
              (epoch_ms(try_cast(d.queried_at_utc AS TIMESTAMPTZ))-d.seen_at_ms)/86400000.0
            )
          END::DOUBLE AS days_since_seen_at_query,
          b.* EXCLUDE(username_norm),
          MAX(CASE WHEN d.is_kind_role=1 THEN s.returned::INTEGER ELSE 0 END)
            OVER (PARTITION BY d.matched_kind_chooser_id)::BOOLEAN AS group_kind_returned
        FROM read_parquet({sql_string(chooser_cache)}) d
        JOIN s USING(username_norm)
        LEFT JOIN bins b USING(username_norm)
      )
      SELECT * FROM joined
    """
    print("Loading authenticated chooser and opportunity caches...", flush=True)
    return database.execute(query).fetchdf()


def corrected_rich_controls(
    data: pd.DataFrame,
    groups: dict[str, list[str]],
    base_public: Path,
) -> tuple[Collector, dict[str, Any]]:
    collector = Collector()
    main = data[
        data["group_ever_kind_fair"].astype(bool)
        & data["group_kind_returned"].astype(bool)
    ].copy()
    all_regressors = ["is_kind_role"] + groups["all"]
    all_standardize = groups["standardize"]
    specs = [
        ("corrected_dates_all_controls_HC1", main, "HC1"),
        ("corrected_dates_all_controls_CR1", main, "CR1"),
        (
            "corrected_dates_all_controls_exclude_disabled_HC1",
            main[~main["disabled"].fillna(False).astype(bool)].copy(),
            "HC1",
        ),
        (
            "corrected_dates_all_controls_exclude_tos_violation_HC1",
            main[~main["tos_violation"].fillna(False).astype(bool)].copy(),
            "HC1",
        ),
        (
            "corrected_dates_all_controls_exclude_disabled_or_tos_HC1",
            main[
                ~(
                    main["disabled"].fillna(False).astype(bool)
                    | main["tos_violation"].fillna(False).astype(bool)
                )
            ].copy(),
            "HC1",
        ),
    ]
    for name, sample, covariance in specs:
        collector.run(
            sample,
            name=name,
            regressors=all_regressors,
            standardize=all_standardize,
            covariance=covariance,
        )

    certified = pd.read_csv(base_public / "chooser_model_coefficients.csv")
    baseline = certified[
        certified["model"].eq(BASE_FULL_MODEL)
        & certified["variable"].eq("is_kind_role")
        & certified["status"].eq("estimated")
    ].iloc[0]
    corrected = collector.coefficient_frame()
    corrected_row = corrected[
        corrected["model"].eq("corrected_dates_all_controls_HC1")
        & corrected["variable"].eq("is_kind_role")
        & corrected["status"].eq("estimated")
    ].iloc[0]
    comparison = {
        "certified_v101_full_control_coefficient_pp": float(baseline["coefficient_pp"]),
        "corrected_date_full_control_coefficient_pp": float(corrected_row["coefficient_pp"]),
        "difference_corrected_minus_certified_pp": float(
            corrected_row["coefficient_pp"] - baseline["coefficient_pp"]
        ),
        "certified_primary_model_unchanged": True,
        "interpretation": (
            "This is a post-certification rich-control sensitivity. It does not replace "
            "the certified match-cell-FE primary estimate."
        ),
    }
    return collector, comparison


def fairness_models(
    data: pd.DataFrame,
    groups: dict[str, list[str]],
) -> tuple[Collector, pd.DataFrame, pd.DataFrame]:
    collector = Collector()
    ever_names: list[str] = []
    log_opp_names: list[str] = []
    for _, alias in FAIRNESS_BINS:
        opp = f"eval_{alias}_opps"
        count = f"eval_{alias}_kind_count"
        ever = f"ever_kind_eval_{alias}"
        log_opp = f"log_eval_{alias}_opps"
        data[opp] = pd.to_numeric(data[opp], errors="coerce").fillna(0.0)
        data[count] = pd.to_numeric(data[count], errors="coerce").fillna(0.0)
        data[ever] = (data[count] > 0).astype(np.int8)
        data[log_opp] = np.log1p(data[opp])
        ever_names.append(ever)
        log_opp_names.append(log_opp)

    differences: list[tuple[str, str, str]] = []
    for index in range(len(ever_names) - 1):
        differences.append(
            (
                ever_names[index],
                ever_names[index + 1],
                f"{ever_names[index]}_minus_{ever_names[index + 1]}",
            )
        )
    differences.append((ever_names[0], ever_names[-1], "clearly_better_minus_clearly_worse"))

    support_rows: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    for threshold in [0, 2, 4]:
        sample = data.copy()
        if threshold > 0:
            support_mask = np.ones(len(sample), dtype=bool)
            for _, alias in FAIRNESS_BINS:
                support_mask &= sample[f"eval_{alias}_opps"].to_numpy(dtype=float) >= threshold
            sample = sample.loc[support_mask].copy()
        support_rows.append(
            {
                "minimum_opportunities_in_each_of_five_bins": threshold,
                "users": len(sample),
                "patrons": int(sample["patron"].sum()),
                "match_cells": int(sample["match_cell"].nunique()),
                **{
                    f"ever_kind_{alias}": int(sample[f"ever_kind_eval_{alias}"].sum())
                    for _, alias in FAIRNESS_BINS
                },
            }
        )
        for _, alias in FAIRNESS_BINS:
            raw = contrast_from_frame(sample, f"ever_kind_eval_{alias}")
            raw_rows.append(
                {
                    "minimum_opportunities_in_each_of_five_bins": threshold,
                    "fairness_bin": alias,
                    **raw,
                }
            )

        base = ever_names + log_opp_names
        collector.run(
            sample,
            name=f"five_bin_chooser_min{threshold}_exposure_HC1",
            regressors=base,
            standardize=log_opp_names,
            covariance="HC1",
            differences=differences,
            estimand_class="postcertification_secondary",
        )
        full = ever_names + list(dict.fromkeys(log_opp_names + groups["all"]))
        full_standardize = list(
            dict.fromkeys(log_opp_names + [name for name in full if name in groups["standardize"]])
        )
        collector.run(
            sample,
            name=f"five_bin_chooser_min{threshold}_full_HC1",
            regressors=full,
            standardize=full_standardize,
            covariance="HC1",
            differences=differences,
            estimand_class="postcertification_secondary",
        )
        if threshold == 4:
            collector.run(
                sample,
                name="five_bin_chooser_min4_full_CR1",
                regressors=full,
                standardize=full_standardize,
                covariance="CR1",
                differences=differences,
                estimand_class="postcertification_sensitivity",
            )
    return collector, pd.DataFrame(support_rows), pd.DataFrame(raw_rows)


def price_count_rate_models(
    data: pd.DataFrame,
    groups: dict[str, list[str]],
) -> tuple[Collector, pd.DataFrame]:
    collector = Collector()
    for side in ["costly", "nonnegative"]:
        data[f"log1p_fair_{side}_kind_count"] = np.log1p(
            pd.to_numeric(data[f"fair_{side}_kind_count"], errors="coerce").fillna(0.0)
        )
        data[f"fair_{side}_kind_rate"] = pd.to_numeric(
            data[f"fair_{side}_kind_rate"], errors="coerce"
        )
    support_rows: list[dict[str, Any]] = []
    exposure = ["log_fair_costly_opps", "log_fair_nonnegative_opps", "log_total_opps"]
    count_terms = ["log1p_fair_costly_kind_count", "log1p_fair_nonnegative_kind_count"]
    rate_terms = ["fair_costly_kind_rate", "fair_nonnegative_kind_rate"]

    for threshold in [2, 4]:
        sample = data[
            (pd.to_numeric(data["fair_costly_opps"], errors="coerce") >= threshold)
            & (pd.to_numeric(data["fair_nonnegative_opps"], errors="coerce") >= threshold)
        ].copy()
        support_rows.append(
            {
                "minimum_opportunities_each_price_side": threshold,
                "users": len(sample),
                "patrons": int(sample["patron"].sum()),
                "match_cells": int(sample["match_cell"].nunique()),
                "positive_costly_count": int((sample["fair_costly_kind_count"] > 0).sum()),
                "positive_nonnegative_count": int((sample["fair_nonnegative_kind_count"] > 0).sum()),
                "positive_both": int(
                    (
                        (sample["fair_costly_kind_count"] > 0)
                        & (sample["fair_nonnegative_kind_count"] > 0)
                    ).sum()
                ),
            }
        )
        for label, terms in [("count", count_terms), ("rate", rate_terms)]:
            difference = [(terms[0], terms[1], f"standardized_costly_minus_nonnegative_{label}")]
            collector.run(
                sample,
                name=f"price_{label}_min{threshold}_exposure_HC1",
                regressors=terms + exposure,
                standardize=terms + exposure,
                covariance="HC1",
                differences=difference,
                estimand_class="postcertification_secondary",
            )
            full = terms + list(dict.fromkeys(exposure + groups["all"]))
            standardize = list(
                dict.fromkeys(terms + exposure + [name for name in full if name in groups["standardize"]])
            )
            collector.run(
                sample,
                name=f"price_{label}_min{threshold}_full_HC1",
                regressors=full,
                standardize=standardize,
                covariance="HC1",
                differences=difference,
                estimand_class="postcertification_secondary",
            )
            if threshold == 4:
                collector.run(
                    sample,
                    name=f"price_{label}_min4_full_CR1",
                    regressors=full,
                    standardize=standardize,
                    covariance="CR1",
                    differences=difference,
                    estimand_class="postcertification_sensitivity",
                )
    return collector, pd.DataFrame(support_rows)


def main() -> None:
    args = parse_args()
    started = time.time()
    project_root = args.project_root.expanduser().resolve()
    base_root = args.base_output_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    public = output_root / "public_results"
    receipts = output_root / "run_receipts"
    private = output_root / "private_cache"
    public.mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True, exist_ok=True)
    private.mkdir(parents=True, exist_ok=True)

    verify_software_exact(args.fixture)
    authentication, snapshot, chooser_cache, opportunity_cache = authenticate_base(
        project_root, base_root, fixture=args.fixture
    )

    stage_path = receipts / "00_postcertification_addendum_stage_success.json"
    if stage_path.is_file():
        stage = load_json(stage_path)
        hashes = stage.get("public_output_hashes") or {}
        if stage.get("status") != "PATRON_STAGE10_POSTCERT_ADDENDUM_STAGE_OK" or not hashes:
            raise RuntimeError("Existing addendum stage receipt is invalid")
        failures = [
            name
            for name, expected in hashes.items()
            if not (public / name).is_file() or sha256_file(public / name) != expected
        ]
        if failures:
            raise RuntimeError(f"Existing addendum stage failed authentication: {failures}")
        print("PATRON_STAGE10_POSTCERT_ADDENDUM_STAGE_AUTHENTICATED_AND_SKIPPED", flush=True)
        return

    atomic_write_json(public / "base_v101_authentication.json", authentication)

    database = connect_database(private / "postcertification_addendum.duckdb", args.threads, args.memory_limit)
    try:
        frame = load_analysis_frame(database, snapshot, chooser_cache, opportunity_cache)
    finally:
        database.close()
    returned = frame[frame["returned"].astype(bool)].copy()
    if not args.fixture:
        if len(returned) != EXPECTED["returned_profiles"]:
            raise RuntimeError("Returned-account count differs from the certified authority")
        if int(returned["patron"].sum()) != EXPECTED["patrons"]:
            raise RuntimeError("Patron count differs from the certified authority")

    returned, groups, imputation = prepare_features(returned)
    atomic_write_json(
        public / "corrected_covariate_missingness.json",
        {
            "created_utc": utc_now(),
            "status": "CORRECTED_ACCOUNT_DATE_MISSINGNESS_RETAINED_OK",
            "construction": (
                "created_at_ms and seen_at_ms remain missing when absent; only observed timestamps "
                "are transformed to nonnegative days; imputation then uses within-cell medians with indicators"
            ),
            "outcome_used_for_imputation": False,
            "diagnostics": imputation,
            "typed_count_field_note": (
                "Snapshot total/rated/win/loss/draw count fields may be entirely unavailable; "
                "unsupported terms are retained in receipts and deterministically dropped by the estimator."
            ),
        },
    )

    rich, comparison = corrected_rich_controls(returned, groups, base_root / "public_results")
    fairness, fairness_support, fairness_raw = fairness_models(returned, groups)
    price, price_support = price_count_rate_models(returned, groups)

    write_csv(public / "corrected_rich_control_coefficients.csv", rich.coefficient_frame())
    atomic_write_json(public / "corrected_rich_control_models.json", rich.models)
    atomic_write_json(public / "corrected_vs_certified_comparison.json", comparison)
    write_csv(public / "five_bin_chooser_support.csv", fairness_support)
    write_csv(public / "five_bin_chooser_raw_rates.csv", fairness_raw)
    write_csv(public / "five_bin_chooser_coefficients.csv", fairness.coefficient_frame())
    write_csv(public / "five_bin_chooser_contrasts.csv", pd.DataFrame(fairness.contrasts))
    atomic_write_json(public / "five_bin_chooser_models.json", fairness.models)
    write_csv(public / "price_count_rate_support.csv", price_support)
    write_csv(public / "price_count_rate_coefficients.csv", price.coefficient_frame())
    write_csv(public / "price_count_rate_contrasts.csv", pd.DataFrame(price.contrasts))
    atomic_write_json(public / "price_count_rate_models.json", price.models)
    atomic_write_json(
        public / "postcertification_interpretation.json",
        {
            "created_utc": utc_now(),
            "status": "PATRON_STAGE10_POSTCERTIFICATION_ANALYSIS_COMPLETE",
            "base_certification_preserved": True,
            "primary_estimand_rerun": False,
            "families": {
                "corrected_rich_controls": (
                    "Sensitivity only: explicit missing-date handling and disabled/TOS exclusions."
                ),
                "five_bin_chooser": (
                    "Secondary prediction of current patron status from where kindness occurred "
                    "across the five certified fairness bins."
                ),
                "price_count_rate": (
                    "Secondary one-standard-deviation count/rate companions at frozen min-2 and min-4 support."
                ),
            },
            "causal_scope": (
                "All estimates remain current cross-sectional stable-type associations. "
                "Patron adoption timing and causality are not identified."
            ),
        },
    )

    output_names = [
        path.name
        for path in public.iterdir()
        if path.is_file() and path.name not in {"_SUCCESS.json", "report_file_hashes.tsv"}
    ]
    stage = {
        "created_utc": utc_now(),
        "version": VERSION,
        "status": "PATRON_STAGE10_POSTCERT_ADDENDUM_STAGE_OK",
        "fixture": args.fixture,
        "runtime_seconds": round(time.time() - started, 3),
        "models": {
            "corrected_rich_control": len(rich.models),
            "five_bin_chooser": len(fairness.models),
            "price_count_rate": len(price.models),
        },
        "public_output_hashes": {
            name: sha256_file(public / name) for name in sorted(output_names)
        },
        "runtime": runtime_record(),
    }
    atomic_write_json(stage_path, stage)
    print("PATRON_STAGE10_POSTCERT_ADDENDUM_STAGE_OK", flush=True)
    print(f"Runtime seconds: {time.time() - started:.3f}", flush=True)


if __name__ == "__main__":
    main()
