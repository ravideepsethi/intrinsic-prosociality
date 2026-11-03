#!/usr/bin/env python3
"""Estimate the complete chooser-level Patron Stage 10 analysis."""

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
    deterministic_control_slot,
    fit_absorbed_ols,
    impute_within_cell,
    runtime_record,
    sha256_file,
    sql_string,
    utc_now,
    verify_software_exact,
    write_csv,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument("--fixture", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def outcome_qa(database, snapshot: Path, fixture: bool) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    qa = database.execute(
        f"""
        SELECT
          COUNT(*)::BIGINT AS rows,
          COUNT(DISTINCT username_norm)::BIGINT AS unique_users,
          SUM(returned::INTEGER)::BIGINT AS returned_profiles,
          SUM((NOT returned)::INTEGER)::BIGINT AS unreturned_profiles,
          SUM((returned AND patron)::INTEGER)::BIGINT AS patrons,
          SUM((acquisition_role='kind')::INTEGER)::BIGINT AS kind_role_users,
          SUM((acquisition_role='control')::INTEGER)::BIGINT AS control_role_users,
          SUM((acquisition_role='kind' AND returned)::INTEGER)::BIGINT AS kind_role_returned,
          SUM((acquisition_role='control' AND returned)::INTEGER)::BIGINT AS control_role_returned,
          SUM((acquisition_role='kind' AND returned AND patron)::INTEGER)::BIGINT AS kind_role_patrons,
          SUM((acquisition_role='control' AND returned AND patron)::INTEGER)::BIGINT AS control_role_patrons,
          SUM((returned AND patron IS NULL)::INTEGER)::BIGINT AS returned_missing_patron,
          SUM(((NOT returned) AND patron IS NOT NULL)::INTEGER)::BIGINT AS unreturned_nonnull_patron,
          SUM((returned AND patron AND patron_field_present IS DISTINCT FROM TRUE)::INTEGER)::BIGINT AS true_patron_missing_field,
          SUM((returned AND NOT patron AND patron_color IS NOT NULL)::INTEGER)::BIGINT AS color_without_patron,
          SUM((returned AND http_status<>200)::INTEGER)::BIGINT AS returned_non200,
          SUM(((NOT returned) AND username_returned IS NOT NULL)::INTEGER)::BIGINT AS unreturned_named,
          SUM((upper(coalesce(title,''))='BOT')::INTEGER)::BIGINT AS bot_title_accounts,
          SUM((returned AND upper(coalesce(title,''))='BOT' AND patron)::INTEGER)::BIGINT AS bot_title_patrons,
          SUM((returned AND disabled IS TRUE)::INTEGER)::BIGINT AS disabled_returned,
          SUM((returned AND tos_violation IS TRUE)::INTEGER)::BIGINT AS tos_violation_returned
        FROM read_parquet({sql_string(snapshot)})
        """
    ).fetchdf().iloc[0].to_dict()
    qa_int = {key: int(value) for key, value in qa.items()}
    fatal = [
        "returned_missing_patron",
        "unreturned_nonnull_patron",
        "true_patron_missing_field",
        "color_without_patron",
        "returned_non200",
        "unreturned_named",
    ]
    if qa_int["rows"] != qa_int["unique_users"] or any(qa_int[key] != 0 for key in fatal):
        raise RuntimeError(f"Patron-outcome semantics or join authority failed: {qa_int}")
    if not fixture:
        expected = {
            "rows": EXPECTED["snapshot_rows"],
            "returned_profiles": EXPECTED["returned_profiles"],
            "unreturned_profiles": EXPECTED["unreturned_profiles"],
            "patrons": EXPECTED["patrons"],
            "kind_role_users": EXPECTED["kind_role_users"],
            "control_role_users": EXPECTED["control_role_users"],
            "kind_role_returned": EXPECTED["kind_role_returned"],
            "control_role_returned": EXPECTED["control_role_returned"],
            "kind_role_patrons": EXPECTED["kind_role_patrons"],
            "control_role_patrons": EXPECTED["control_role_patrons"],
        }
        failures = {key: {"observed": qa_int[key], "expected": value} for key, value in expected.items() if qa_int[key] != value}
        if failures:
            raise RuntimeError(f"Certified patron audit totals were not reproduced: {failures}")

    coverage = database.execute(
        f"""
        SELECT
          match_cell,
          acquisition_role,
          COUNT(*)::BIGINT AS requested_users,
          SUM(returned::INTEGER)::BIGINT AS returned_profiles,
          SUM((NOT returned)::INTEGER)::BIGINT AS unreturned_profiles,
          SUM((returned AND patron)::INTEGER)::BIGINT AS patrons,
          100.0*AVG(returned::INTEGER)::DOUBLE AS return_rate_pct,
          100.0*SUM((returned AND patron)::INTEGER)::DOUBLE/nullif(SUM(returned::INTEGER),0) AS patron_rate_returned_pct,
          SUM(CASE WHEN NOT returned THEN total_opps ELSE 0 END)::BIGINT AS nonreturn_total_opportunities,
          SUM(CASE WHEN NOT returned THEN total_kind_count ELSE 0 END)::BIGINT AS nonreturn_kind_draws
        FROM read_parquet({sql_string(snapshot)})
        GROUP BY match_cell, acquisition_role
        ORDER BY match_cell, acquisition_role
        """
    ).fetchdf()
    profile_fields = database.execute(
        f"""
        SELECT
          acquisition_role,
          COUNT(*) FILTER (WHERE returned)::BIGINT AS returned_profiles,
          SUM((upper(coalesce(title,''))='BOT')::INTEGER) FILTER (WHERE returned)::BIGINT AS bot_titles,
          SUM((created_at_ms IS NULL)::INTEGER) FILTER (WHERE returned)::BIGINT AS missing_created_at,
          SUM((seen_at_ms IS NULL)::INTEGER) FILTER (WHERE returned)::BIGINT AS missing_seen_at,
          SUM((play_time_total_seconds IS NULL)::INTEGER) FILTER (WHERE returned)::BIGINT AS missing_playtime,
          SUM((count_all IS NULL)::INTEGER) FILTER (WHERE returned)::BIGINT AS missing_count_all,
          SUM((disabled IS TRUE)::INTEGER) FILTER (WHERE returned)::BIGINT AS disabled,
          SUM((tos_violation IS TRUE)::INTEGER) FILTER (WHERE returned)::BIGINT AS tos_violation
        FROM read_parquet({sql_string(snapshot)})
        GROUP BY acquisition_role ORDER BY acquisition_role
        """
    ).fetchdf()
    return qa_int, coverage, profile_fields


def prepare_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, list[str]], dict[str, Any]]:
    out = frame.copy()
    out["patron"] = out["patron"].astype(bool).astype(np.int8)
    out["patron_pp"] = 100.0 * out["patron"].astype(float)
    out["is_kind_role"] = out["is_kind_role"].astype(np.int8)
    out["ever_kind_fair_state"] = out["ever_kind_fair_state"].astype(np.int8)
    out["ever_kind_clearly_worse_state"] = out["ever_kind_clearly_worse_state"].astype(np.int8)
    out["ever_kind_fair_costly"] = out["ever_kind_fair_costly"].astype(np.int8)
    out["ever_kind_fair_nonnegative"] = out["ever_kind_fair_nonnegative"].astype(np.int8)
    out["log_fair_opps"] = np.log1p(pd.to_numeric(out["fair_opps"], errors="coerce"))
    out["log_total_opps"] = np.log1p(pd.to_numeric(out["total_opps"], errors="coerce"))
    out["log_clearly_worse_opps"] = np.log1p(pd.to_numeric(out["clearly_worse_opps"], errors="coerce"))
    out["log_fair_costly_opps"] = np.log1p(pd.to_numeric(out["fair_costly_opps"], errors="coerce"))
    out["log_fair_nonnegative_opps"] = np.log1p(pd.to_numeric(out["fair_nonnegative_opps"], errors="coerce"))
    out["log1p_fair_kind_count"] = np.log1p(pd.to_numeric(out["fair_kind_count"], errors="coerce"))
    out["fair_kind_rate"] = pd.to_numeric(out["fair_kind_count"], errors="coerce") / pd.to_numeric(out["fair_opps"], errors="coerce").replace(0, np.nan)

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
    all_controls = list(dict.fromkeys(exposure_volume + profile_tenure + board_state + price + engagement + skill))
    binary = set(missing_indicators) | {name for name in all_controls if name.startswith("rating_tier_")}
    standardize = [name for name in all_controls if name not in binary]
    groups = {
        "exposure_volume": exposure_volume,
        "profile_tenure": profile_tenure,
        "board_state": board_state,
        "price": price,
        "engagement": engagement,
        "skill": skill,
        "all": all_controls,
        "standardize": standardize,
    }
    return out, groups, imputation


class ModelCollector:
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
        estimand_class: str = "secondary",
        differences: Sequence[tuple[str, str, str]] = (),
    ):
        result = fit_absorbed_ols(
            frame,
            model_name=name,
            y_col="patron_pp",
            regressors=regressors,
            fe_col="match_cell",
            covariance=covariance,
            cluster_col="match_cell" if covariance.upper() == "CR1" else None,
            standardize=standardize,
            estimand_class=estimand_class,
        )
        self.models.append(result.model)
        self.coefficients.append(result.coefficients)
        for first, second, label in differences:
            contrast = coefficient_difference(result, first, second, label)
            contrast["estimand_class"] = estimand_class
            self.contrasts.append(contrast)
        return result


def raw_row(frame: pd.DataFrame, sample: str, treatment: str, estimand_class: str) -> dict[str, Any]:
    result = contrast_from_frame(frame, treatment)
    return {
        "sample": sample,
        "estimand_class": estimand_class,
        "treatment": treatment,
        "bot_policy": "include",
        **result,
    }


def matched_one_to_one(frame: pd.DataFrame, slot: int) -> pd.DataFrame:
    selected = frame[(frame["is_kind_role"] == 1) | (frame["control_slot"] == slot)].copy()
    counts = selected.groupby("matched_kind_chooser_id", observed=True).agg(
        rows=("username_norm", "size"),
        kinds=("is_kind_role", "sum"),
    )
    valid_groups = counts.index[(counts["rows"] == 2) & (counts["kinds"] == 1)]
    return selected[selected["matched_kind_chooser_id"].isin(valid_groups)].copy()


def deterministic_rematch(frame: pd.DataFrame, replicate: int) -> pd.DataFrame:
    kinds = frame[frame["is_kind_role"] == 1][["matched_kind_chooser_id"]].drop_duplicates().copy()
    kinds["chosen_slot"] = [deterministic_control_slot(str(value), replicate) for value in kinds["matched_kind_chooser_id"]]
    controls = frame[frame["is_kind_role"] == 0].merge(kinds, on="matched_kind_chooser_id", how="inner")
    controls = controls[controls["control_slot"] == controls["chosen_slot"]].drop(columns="chosen_slot")
    available = set(controls["matched_kind_chooser_id"].astype(str))
    kind_rows = frame[(frame["is_kind_role"] == 1) & frame["matched_kind_chooser_id"].astype(str).isin(available)]
    return pd.concat([kind_rows, controls], ignore_index=True)


def dose_tables(data: pd.DataFrame, collector: ModelCollector, groups: dict[str, list[str]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    out = data.copy()
    counts = pd.to_numeric(out["fair_kind_count"], errors="coerce").fillna(0)
    out["dose_bin"] = pd.cut(
        counts,
        bins=[-0.1, 0, 1, 4, 9, np.inf],
        labels=["0", "1", "2_4", "5_9", "10_plus"],
        right=True,
    )
    for level in ["1", "2_4", "5_9", "10_plus"]:
        out[f"dose_{level}"] = (out["dose_bin"].astype(str) == level).astype(np.int8)
    raw = (
        out.groupby("dose_bin", observed=True)
        .agg(users=("patron", "size"), patrons=("patron", "sum"), mean_fair_opps=("fair_opps", "mean"))
        .reset_index()
    )
    raw["patron_rate_pct"] = 100.0 * raw["patrons"] / raw["users"]
    dose_regressors = ["dose_1", "dose_2_4", "dose_5_9", "dose_10_plus"] + groups["exposure_volume"]
    collector.run(
        out,
        name="dose_response_bins_match_cell_fe_HC1",
        regressors=dose_regressors,
        standardize=groups["exposure_volume"],
        covariance="HC1",
        estimand_class="secondary",
    )
    collector.run(
        out[out["fair_opps"] > 0],
        name="dose_continuous_log_count_match_cell_fe_HC1",
        regressors=["log1p_fair_kind_count"] + groups["exposure_volume"],
        standardize=["log1p_fair_kind_count"] + groups["exposure_volume"],
        covariance="HC1",
        estimand_class="secondary",
    )
    collector.run(
        out[out["fair_opps"] > 0],
        name="dose_continuous_fair_kind_rate_match_cell_fe_HC1",
        regressors=["fair_kind_rate"] + groups["exposure_volume"],
        standardize=["fair_kind_rate"] + groups["exposure_volume"],
        covariance="HC1",
        estimand_class="secondary",
    )
    return raw, []


def diagnostic_models(data: pd.DataFrame, collector: ModelCollector, groups: dict[str, list[str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    for threshold in [2, 4, 5, 10]:
        sample = data[(data["fair_opps"] >= threshold) & (data["clearly_worse_opps"] >= threshold)].copy()
        sample["diagnostic_group"] = np.select(
            [
                (sample["ever_kind_fair_state"] == 1) & (sample["ever_kind_clearly_worse_state"] == 0),
                (sample["ever_kind_fair_state"] == 0) & (sample["ever_kind_clearly_worse_state"] == 1),
                (sample["ever_kind_fair_state"] == 1) & (sample["ever_kind_clearly_worse_state"] == 1),
            ],
            ["fair_only", "losing_only", "both"],
            default="neither",
        )
        grouped = sample.groupby("diagnostic_group", observed=True).agg(users=("patron", "size"), patrons=("patron", "sum")).reset_index()
        grouped["patron_rate_pct"] = 100.0 * grouped["patrons"] / grouped["users"]
        grouped["minimum_opportunities_each_state"] = threshold
        raw_rows.extend(grouped.to_dict(orient="records"))
        support_rows.append(
            {
                "minimum_opportunities_each_state": threshold,
                "users": len(sample),
                "patrons": int(sample["patron"].sum()),
                "match_cells": int(sample["match_cell"].nunique()),
            }
        )
        base = ["ever_kind_fair_state", "ever_kind_clearly_worse_state", "log_fair_opps", "log_clearly_worse_opps"]
        standardize_base = ["log_fair_opps", "log_clearly_worse_opps"]
        classification = "confirmatory" if threshold == 4 else "secondary"
        collector.run(
            sample,
            name=f"diagnostic_horse_race_min{threshold}_exposure_match_cell_fe_HC1",
            regressors=base,
            standardize=standardize_base,
            covariance="HC1",
            estimand_class=classification,
            differences=[("ever_kind_fair_state", "ever_kind_clearly_worse_state", "fair_minus_clearly_worse")],
        )
        full = ["ever_kind_fair_state", "ever_kind_clearly_worse_state"] + list(
            dict.fromkeys(["log_fair_opps", "log_clearly_worse_opps"] + groups["all"])
        )
        collector.run(
            sample,
            name=f"diagnostic_horse_race_min{threshold}_full_match_cell_fe_HC1",
            regressors=full,
            standardize=[name for name in full if name in set(groups["standardize"] + ["log_clearly_worse_opps"])],
            covariance="HC1",
            estimand_class=classification,
            differences=[("ever_kind_fair_state", "ever_kind_clearly_worse_state", "fair_minus_clearly_worse")],
        )
        if threshold == 4:
            collector.run(
                sample,
                name="diagnostic_horse_race_min4_full_match_cell_fe_CR1",
                regressors=full,
                standardize=[name for name in full if name in set(groups["standardize"] + ["log_clearly_worse_opps"])],
                covariance="CR1",
                estimand_class="sensitivity",
                differences=[("ever_kind_fair_state", "ever_kind_clearly_worse_state", "fair_minus_clearly_worse")],
            )
    return pd.DataFrame(raw_rows), pd.DataFrame(support_rows)


def price_side_models(data: pd.DataFrame, collector: ModelCollector, groups: dict[str, list[str]]) -> pd.DataFrame:
    support: list[dict[str, Any]] = []
    for threshold in [2, 4]:
        sample = data[(data["fair_costly_opps"] >= threshold) & (data["fair_nonnegative_opps"] >= threshold)].copy()
        support.append(
            {
                "minimum_opportunities_each_price_side": threshold,
                "users": len(sample),
                "patrons": int(sample["patron"].sum()),
                "ever_kind_costly": int(sample["ever_kind_fair_costly"].sum()),
                "ever_kind_nonnegative": int(sample["ever_kind_fair_nonnegative"].sum()),
                "both": int(((sample["ever_kind_fair_costly"] == 1) & (sample["ever_kind_fair_nonnegative"] == 1)).sum()),
                "match_cells": int(sample["match_cell"].nunique()),
            }
        )
        base = [
            "ever_kind_fair_costly",
            "ever_kind_fair_nonnegative",
            "log_fair_costly_opps",
            "log_fair_nonnegative_opps",
            "log_total_opps",
        ]
        collector.run(
            sample,
            name=f"price_side_horse_race_min{threshold}_match_cell_fe_HC1",
            regressors=base,
            standardize=["log_fair_costly_opps", "log_fair_nonnegative_opps", "log_total_opps"],
            covariance="HC1",
            estimand_class="secondary",
            differences=[("ever_kind_fair_costly", "ever_kind_fair_nonnegative", "costly_minus_nonnegative")],
        )
        full = ["ever_kind_fair_costly", "ever_kind_fair_nonnegative"] + list(
            dict.fromkeys(["log_fair_costly_opps", "log_fair_nonnegative_opps"] + groups["all"])
        )
        collector.run(
            sample,
            name=f"price_side_horse_race_min{threshold}_full_match_cell_fe_HC1",
            regressors=full,
            standardize=[name for name in full if name in set(groups["standardize"] + ["log_fair_costly_opps", "log_fair_nonnegative_opps"])],
            covariance="HC1",
            estimand_class="secondary",
            differences=[("ever_kind_fair_costly", "ever_kind_fair_nonnegative", "costly_minus_nonnegative")],
        )
    return pd.DataFrame(support)


def main() -> None:
    args = parse_args()
    started = time.time()
    project_root = args.project_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    private_cache = output_root / "private_cache"
    public_results = output_root / "public_results"
    receipts = output_root / "run_receipts"
    stage00 = receipts / "00_chooser_design_stage_success.json"
    cache_receipt_path = receipts / "chooser_cache_success.json"
    if not stage00.is_file() or not cache_receipt_path.is_file():
        raise RuntimeError("Chooser design stage is incomplete")
    verify_software_exact(args.fixture)
    cache_receipt = load_json(cache_receipt_path)
    cache_path = private_cache / "chooser_design_features_private.parquet"
    if cache_receipt.get("cache_sha256") != sha256_file(cache_path):
        raise RuntimeError("Chooser design cache authentication failed")

    stage_success_path = receipts / "01_chooser_models_stage_success.json"
    if stage_success_path.exists():
        stage = load_json(stage_success_path)
        if stage.get("status") != "PATRON_STAGE10_CHOOSER_MODELS_OK":
            raise RuntimeError("Completed chooser-model stage has an invalid status")
        output_hashes = stage.get("public_output_hashes")
        if not isinstance(output_hashes, dict) or not output_hashes:
            raise RuntimeError("Completed chooser-model stage has no output hashes")
        failed: list[str] = []
        for name, expected_hash in output_hashes.items():
            path = public_results / name
            if not path.is_file() or sha256_file(path) != expected_hash:
                failed.append(name)
        if failed:
            raise RuntimeError(
                "Completed chooser-model stage failed authentication: "
                + ", ".join(sorted(failed))
            )
        print(
            "PATRON_STAGE10_CHOOSER_MODELS_STAGE_AUTHENTICATED_AND_SKIPPED",
            flush=True,
        )
        return

    snapshot = project_root / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet"
    database = connect_database(private_cache / "chooser_models.duckdb", args.threads, args.memory_limit)
    try:
        qa, coverage, profile_fields = outcome_qa(database, snapshot, args.fixture)
        write_csv(public_results / "return_and_patron_coverage_by_match_cell.csv", coverage)
        write_csv(public_results / "profile_field_missingness_by_role.csv", profile_fields)
        atomic_write_json(public_results / "patron_outcome_semantics_qa.json", qa)

        print("Loading private design cache and only the typed patron outcome fields...", flush=True)
        frame = database.execute(
            f"""
            WITH d AS (SELECT * FROM read_parquet({sql_string(cache_path)})),
            s AS (
              SELECT username_norm, returned, patron, patron_field_present, patron_color, http_status, username_returned
              FROM read_parquet({sql_string(snapshot)})
            ), joined AS (
              SELECT d.*, s.* EXCLUDE(username_norm)
              FROM d JOIN s USING (username_norm)
            )
            SELECT
              *,
              MAX(CASE WHEN is_kind_role=1 THEN returned::INTEGER ELSE 0 END)
                OVER (PARTITION BY matched_kind_chooser_id)::BOOLEAN AS group_kind_returned,
              SUM(returned::INTEGER) OVER (PARTITION BY matched_kind_chooser_id)::SMALLINT AS group_returned_count,
              MAX(CASE WHEN is_kind_role=1 THEN fair_opps ELSE NULL END)
                OVER (PARTITION BY matched_kind_chooser_id)::BIGINT AS group_kind_fair_opps
            FROM joined
            """
        ).fetchdf()
    finally:
        database.close()

    returned = frame[frame["returned"].astype(bool)].copy()
    returned, control_groups, imputation = prepare_features(returned)
    atomic_write_json(
        public_results / "covariate_imputation_receipt.json",
        {
            "created_utc": utc_now(),
            "rule": "within-match-cell median, global median only for all-missing cells; indicators retained",
            "outcome_used_for_imputation": False,
            "diagnostics": imputation,
        },
    )

    collector = ModelCollector()
    raw_rows: list[dict[str, Any]] = []
    broad = returned.copy()
    raw_rows.append(raw_row(broad, "broad_any_state_acquisition_roles", "is_kind_role", "qa_secondary"))

    main = returned[
        returned["group_ever_kind_fair"].astype(bool)
        & returned["group_kind_returned"].astype(bool)
    ].copy()
    raw_rows.append(raw_row(main, "main_fair_kind_stored_1to3_available_cases", "is_kind_role", "confirmatory"))
    complete = main[main["group_returned_count"] == 4].copy()
    raw_rows.append(raw_row(complete, "main_fair_kind_complete_four_account_groups", "is_kind_role", "sensitivity"))
    main_no_bot = main[main["bot_title"] == 0].copy()
    raw_rows.append(raw_row(main_no_bot, "main_fair_kind_stored_1to3_exclude_bot", "is_kind_role", "sensitivity"))

    ladder_specs = [
        ("01_match_cell_fe_only", []),
        ("02_plus_exposure_volume", control_groups["exposure_volume"]),
        ("03_plus_profile_tenure", control_groups["exposure_volume"] + control_groups["profile_tenure"]),
        ("04_plus_board_state", control_groups["exposure_volume"] + control_groups["profile_tenure"] + control_groups["board_state"]),
        ("05_plus_price", control_groups["exposure_volume"] + control_groups["profile_tenure"] + control_groups["board_state"] + control_groups["price"]),
        ("06_plus_engagement", control_groups["exposure_volume"] + control_groups["profile_tenure"] + control_groups["board_state"] + control_groups["price"] + control_groups["engagement"]),
        ("07_plus_skill_stability", control_groups["all"]),
        ("08_all_controls", control_groups["all"]),
    ]
    seen_ladder: set[tuple[str, ...]] = set()
    for label, controls in ladder_specs:
        controls = list(dict.fromkeys(controls))
        signature = tuple(controls)
        if signature in seen_ladder and label != "08_all_controls":
            continue
        seen_ladder.add(signature)
        regressors = ["is_kind_role"] + controls
        collector.run(
            main,
            name=f"main_fair_kind_1to3_{label}_HC1",
            regressors=regressors,
            standardize=[name for name in controls if name in control_groups["standardize"]],
            covariance="HC1",
            estimand_class="confirmatory" if label in {"01_match_cell_fe_only", "08_all_controls"} else "secondary",
        )

    collector.run(
        main,
        name="main_fair_kind_1to3_match_cell_fe_only_CR1",
        regressors=["is_kind_role"],
        standardize=[],
        covariance="CR1",
        estimand_class="sensitivity",
    )
    collector.run(
        main,
        name="main_fair_kind_1to3_all_controls_CR1",
        regressors=["is_kind_role"] + control_groups["all"],
        standardize=control_groups["standardize"],
        covariance="CR1",
        estimand_class="sensitivity",
    )
    collector.run(
        main_no_bot,
        name="main_fair_kind_1to3_all_controls_exclude_bot_HC1",
        regressors=["is_kind_role"] + control_groups["all"],
        standardize=control_groups["standardize"],
        covariance="HC1",
        estimand_class="sensitivity",
    )
    collector.run(
        complete,
        name="main_fair_kind_complete_groups_all_controls_HC1",
        regressors=["is_kind_role"] + control_groups["all"],
        standardize=control_groups["standardize"],
        covariance="HC1",
        estimand_class="sensitivity",
    )

    support_specs = {
        "legacy_2_20": main[main["group_kind_fair_opps"].between(2, 20)],
        "duration_2_40": main[main["group_kind_fair_opps"].between(2, 40)],
    }
    support_receipt = load_json(public_results / "preoutcome_support_receipt.json")
    overlap_cells = {
        row["match_cell"] for row in support_receipt["cell_support"] if row["overlap_cell_min20"]
    }
    support_specs["overlap_cells_min20"] = main[main["match_cell"].isin(overlap_cells)]
    support_rows: list[dict[str, Any]] = []
    for label, sample in support_specs.items():
        raw_rows.append(raw_row(sample, f"main_fair_kind_{label}", "is_kind_role", "sensitivity"))
        support_rows.append(
            {
                "sample": label,
                "users": len(sample),
                "kind_users": int(sample["is_kind_role"].sum()),
                "controls": int((sample["is_kind_role"] == 0).sum()),
                "patrons": int(sample["patron"].sum()),
                "match_cells": int(sample["match_cell"].nunique()),
            }
        )
        collector.run(
            sample,
            name=f"main_fair_kind_{label}_all_controls_HC1",
            regressors=["is_kind_role"] + control_groups["all"],
            standardize=control_groups["standardize"],
            covariance="HC1",
            estimand_class="sensitivity",
        )

    one_to_one_rows: list[dict[str, Any]] = []
    for slot in [1, 2, 3]:
        sample = matched_one_to_one(main, slot)
        raw = raw_row(sample, f"main_fair_kind_control_slot_{slot}_1to1", "is_kind_role", "sensitivity")
        raw_rows.append(raw)
        fe = collector.run(
            sample,
            name=f"main_fair_kind_control_slot_{slot}_1to1_match_cell_fe_HC1",
            regressors=["is_kind_role"],
            standardize=[],
            covariance="HC1",
            estimand_class="sensitivity",
        )
        full = collector.run(
            sample,
            name=f"main_fair_kind_control_slot_{slot}_1to1_all_controls_HC1",
            regressors=["is_kind_role"] + control_groups["all"],
            standardize=control_groups["standardize"],
            covariance="HC1",
            estimand_class="sensitivity",
        )
        one_to_one_rows.append(
            {
                "control_slot": slot,
                **raw,
                "fe_coefficient_pp": float(fe.coefficients.set_index("variable").loc["is_kind_role", "coefficient_pp"]),
                "full_coefficient_pp": float(full.coefficients.set_index("variable").loc["is_kind_role", "coefficient_pp"]),
            }
        )

    rematch_rows: list[dict[str, Any]] = []
    print("Running 100 deterministic valid 1:1 rematches within immutable three-control sets...", flush=True)
    for replicate in range(1, 101):
        sample = deterministic_rematch(main, replicate)
        raw = contrast_from_frame(sample, "is_kind_role")
        fe = collector.run(
            sample,
            name=f"rematch_{replicate:03d}_match_cell_fe_HC1",
            regressors=["is_kind_role"],
            standardize=[],
            covariance="HC1",
            estimand_class="rematch_sensitivity",
        )
        full = collector.run(
            sample,
            name=f"rematch_{replicate:03d}_all_controls_HC1",
            regressors=["is_kind_role"] + control_groups["all"],
            standardize=control_groups["standardize"],
            covariance="HC1",
            estimand_class="rematch_sensitivity",
        )
        fe_row = fe.coefficients.set_index("variable").loc["is_kind_role"]
        full_row = full.coefficients.set_index("variable").loc["is_kind_role"]
        rematch_rows.append(
            {
                "replicate": replicate,
                "root_seed": "20260826",
                "users": len(sample),
                "kind_users": int(sample["is_kind_role"].sum()),
                "controls": int((sample["is_kind_role"] == 0).sum()),
                "raw_gap_pp": raw.get("gap_pp"),
                "raw_p_two_sided": raw.get("pooled_p_two_sided"),
                "fe_gap_pp": float(fe_row["coefficient_pp"]),
                "fe_p_two_sided": float(fe_row["p_two_sided_approx"]),
                "full_gap_pp": float(full_row["coefficient_pp"]),
                "full_p_two_sided": float(full_row["p_two_sided_approx"]),
            }
        )
        if replicate == 1 or replicate % 10 == 0:
            print(f"REMATCH_PROGRESS completed={replicate}/100", flush=True)

    rematch = pd.DataFrame(rematch_rows)
    rematch_summary_rows: list[dict[str, Any]] = []
    for label, column, p_column in [
        ("raw", "raw_gap_pp", "raw_p_two_sided"),
        ("match_cell_fe", "fe_gap_pp", "fe_p_two_sided"),
        ("full_controls", "full_gap_pp", "full_p_two_sided"),
    ]:
        values = pd.to_numeric(rematch[column], errors="coerce")
        pvalues = pd.to_numeric(rematch[p_column], errors="coerce")
        rematch_summary_rows.append(
            {
                "estimand": label,
                "replicates": int(values.notna().sum()),
                "mean_pp": values.mean(),
                "sd_pp": values.std(ddof=1),
                "minimum_pp": values.min(),
                "p10_pp": values.quantile(0.10),
                "median_pp": values.median(),
                "p90_pp": values.quantile(0.90),
                "maximum_pp": values.max(),
                "share_positive": float((values > 0).mean()),
                "share_positive_p_below_0_05": float(((values > 0) & (pvalues < 0.05)).mean()),
            }
        )

    dose_raw, _ = dose_tables(broad, collector, control_groups)
    diagnostic_raw, diagnostic_support = diagnostic_models(broad, collector, control_groups)
    price_support = price_side_models(broad, collector, control_groups)

    raw_frame = pd.DataFrame(raw_rows)
    write_csv(public_results / "raw_matched_patron_comparisons.csv", raw_frame)
    write_csv(public_results / "common_support_samples.csv", pd.DataFrame(support_rows))
    write_csv(public_results / "one_to_one_fixed_slots.csv", pd.DataFrame(one_to_one_rows))
    write_csv(public_results / "repeated_rematch_long.csv", rematch)
    write_csv(public_results / "repeated_rematch_summary.csv", pd.DataFrame(rematch_summary_rows))
    write_csv(public_results / "dose_response_raw_rates.csv", dose_raw)
    write_csv(public_results / "diagnostic_kindness_raw_groups.csv", diagnostic_raw)
    write_csv(public_results / "diagnostic_kindness_support.csv", diagnostic_support)
    write_csv(public_results / "price_side_support.csv", price_support)

    coefficients = pd.concat(collector.coefficients, ignore_index=True)
    write_csv(public_results / "chooser_model_coefficients.csv", coefficients)
    write_csv(public_results / "chooser_model_contrasts.csv", pd.DataFrame(collector.contrasts))
    atomic_write_json(public_results / "chooser_models.json", collector.models)

    primary_model = coefficients[
        (coefficients["model"] == "main_fair_kind_1to3_01_match_cell_fe_only_HC1")
        & (coefficients["variable"] == "is_kind_role")
        & (coefficients["status"] == "estimated")
    ]
    if len(primary_model) != 1:
        raise RuntimeError("Primary chooser model was not estimated exactly once")
    primary = primary_model.iloc[0].to_dict()
    interpretation = {
        "created_utc": utc_now(),
        "status": "PATRON_STAGE10_CHOOSER_ANALYSIS_COMPLETE",
        "primary_estimand": "current patron-status percentage-point difference for fair-state kind choosers versus their three immutable never-kind controls, with certified match-cell fixed effects",
        "primary_result": primary,
        "broad_role_audit": raw_frame[raw_frame["sample"] == "broad_any_state_acquisition_roles"].iloc[0].to_dict(),
        "interpretation": "A current cross-sectional association between private kind-draw behavior and a second costly platform decision. Patron adoption timing and a causal effect of kindness on patronage are not identified.",
        "missingness": "Explicit nonreturns are excluded as missing outcomes and are never coded as non-patrons.",
        "multiplicity": "The stored 1:3 fair-kind contrast and min-4 diagnostic horse race are confirmatory; other ladders, support restrictions, dose, price-side, BOT, and rematch analyses are labeled secondary or sensitivity and all results are retained.",
    }
    atomic_write_json(public_results / "chooser_primary_interpretation.json", interpretation)

    stage = {
        "created_utc": utc_now(),
        "version": VERSION,
        "status": "PATRON_STAGE10_CHOOSER_MODELS_OK",
        "fixture": args.fixture,
        "runtime_seconds": round(time.time() - started, 3),
        "models": len(collector.models),
        "coefficient_rows": len(coefficients),
        "rematches": len(rematch),
        "primary_model": primary["model"],
        "primary_coefficient_pp": primary["coefficient_pp"],
        "public_output_hashes": {
            path.name: sha256_file(path)
            for path in sorted(public_results.iterdir())
            if path.is_file()
        },
        "runtime": runtime_record(),
    }
    atomic_write_json(stage_success_path, stage)
    print("PATRON_STAGE10_CHOOSER_MODELS_OK", flush=True)
    print(f"Models: {len(collector.models):,}", flush=True)
    print(f"Runtime seconds: {time.time() - started:.3f}", flush=True)


if __name__ == "__main__":
    main()
