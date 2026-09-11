#!/usr/bin/env python3
"""Estimate the prespecified opportunity-level patron-structure appendix."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from patron_stage10_common import (
    VERSION,
    atomic_write_json,
    connect_database,
    normal_two_sided_p,
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
    parser.add_argument("--force-rebuild", action="store_true")
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def speed_sql(column: str) -> str:
    normalized = f"lower(regexp_replace(coalesce({column},''),'[^a-zA-Z0-9]','','g'))"
    return f"""CASE
      WHEN {normalized}='ultrabullet' THEN 'ultrabullet'
      WHEN {normalized}='bullet' THEN 'bullet'
      WHEN {normalized}='blitz' THEN 'blitz'
      WHEN {normalized}='rapid' THEN 'rapid'
      WHEN {normalized} IN ('classical','correspondence') THEN 'classical_long'
      ELSE 'other' END"""


def clock_bin_sql(column: str) -> str:
    return f"""CASE
      WHEN {column} IS NULL THEN 'missing'
      WHEN {column}<5 THEN '00_05'
      WHEN {column}<15 THEN '05_15'
      WHEN {column}<30 THEN '15_30'
      WHEN {column}<60 THEN '30_60'
      WHEN {column}<180 THEN '60_180'
      ELSE '180_plus' END"""


def rating_gap_bin_sql(column: str) -> str:
    return f"""CASE
      WHEN {column} IS NULL THEN 'missing'
      WHEN {column}<-200 THEN 'lt_m200'
      WHEN {column}<-100 THEN 'm200_m100'
      WHEN {column}<-50 THEN 'm100_m50'
      WHEN {column}<0 THEN 'm50_0'
      WHEN {column}<50 THEN '0_50'
      WHEN {column}<100 THEN '50_100'
      WHEN {column}<200 THEN '100_200'
      ELSE '200_plus' END"""


def build_opportunity_cache(database, project_root: Path, cache_path: Path) -> None:
    stage07 = project_root / "derived/replication/analysis_panel_24m_sf100k/month=*/analysis_panel.parquet"
    snapshot = project_root / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet"
    temporary = cache_path.with_name(f".{cache_path.name}.tmp.{os.getpid()}")
    temporary.unlink(missing_ok=True)
    print("Building private chooser-by-opportunity-cell cache from 47,587,020 certified rows...", flush=True)
    database.execute(
        f"""
        COPY (
          WITH returned_users AS (
            SELECT username_norm
            FROM read_parquet({sql_string(snapshot)})
            WHERE returned
          ), base AS (
            SELECT
              p.chooser_username_norm::VARCHAR AS username_norm,
              p.month::VARCHAR AS month,
              {speed_sql('p.api_speed')} AS speed_group,
              p.tournament_like_event::BOOLEAN AS tournament_like,
              p.engine_fairness_bin::VARCHAR AS fairness_bin,
              p.fair_competitive::BOOLEAN AS fair_competitive,
              p.clearly_worse::BOOLEAN AS clearly_worse,
              p.excluded_middle::BOOLEAN AS excluded_middle,
              p.draw_nonnegative::BOOLEAN AS favorable_draw,
              {clock_bin_sql('p.chooser_clock_last_obs_s')} AS chooser_clock_bin,
              {clock_bin_sql('p.disconnected_clock_last_obs_s')} AS disconnected_clock_bin,
              {rating_gap_bin_sql('p.rating_gap')} AS rating_gap_bin,
              p.kind_draw::BOOLEAN AS kind_draw
            FROM read_parquet({sql_string(stage07)}, union_by_name=true, hive_partitioning=false) p
            SEMI JOIN returned_users u ON p.chooser_username_norm=u.username_norm
          )
          SELECT
            username_norm,
            month,
            speed_group,
            tournament_like,
            fairness_bin,
            fair_competitive,
            clearly_worse,
            excluded_middle,
            favorable_draw,
            chooser_clock_bin,
            disconnected_clock_bin,
            rating_gap_bin,
            COUNT(*)::BIGINT AS opportunities,
            SUM(kind_draw::INTEGER)::BIGINT AS kind_draws
          FROM base
          GROUP BY ALL
          ORDER BY username_norm, month, speed_group, fairness_bin, favorable_draw
        ) TO {sql_string(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    temporary.replace(cache_path)


def cache_qa(database, cache_path: Path, project_root: Path) -> dict[str, Any]:
    snapshot = project_root / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet"
    result = database.execute(
        f"""
        WITH c AS (SELECT * FROM read_parquet({sql_string(cache_path)})),
        s AS (
          SELECT username_norm, total_opps, total_kind_count
          FROM read_parquet({sql_string(snapshot)}) WHERE returned
        ), a AS (
          SELECT username_norm, SUM(opportunities)::BIGINT AS opportunities, SUM(kind_draws)::BIGINT AS kind_draws
          FROM c GROUP BY username_norm
        )
        SELECT
          (SELECT COUNT(*) FROM c)::BIGINT AS collapsed_rows,
          (SELECT SUM(opportunities) FROM c)::BIGINT AS opportunities,
          (SELECT SUM(kind_draws) FROM c)::BIGINT AS kind_draws,
          (SELECT COUNT(DISTINCT username_norm) FROM c)::BIGINT AS chooser_accounts,
          SUM((a.opportunities<>s.total_opps)::INTEGER)::BIGINT AS total_opportunity_mismatch,
          SUM((a.kind_draws<>s.total_kind_count)::INTEGER)::BIGINT AS kind_draw_mismatch,
          SUM((a.username_norm IS NULL)::INTEGER)::BIGINT AS returned_without_panel_rows,
          SUM((s.username_norm IS NULL)::INTEGER)::BIGINT AS unplanned_panel_users
        FROM s FULL JOIN a USING(username_norm)
        """
    ).fetchdf().iloc[0].to_dict()
    out = {key: int(value) for key, value in result.items()}
    for key in ["total_opportunity_mismatch", "kind_draw_mismatch", "returned_without_panel_rows", "unplanned_panel_users"]:
        if out[key] != 0:
            raise RuntimeError(f"Opportunity cache QA failed: {out}")
    return out


def safe_alias(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


def dummy_expressions(column: str, levels: Sequence[str], prefix: str) -> list[tuple[str, str]]:
    return [
        (f"({column}={sql_string(level)})::DOUBLE", f"{prefix}_{safe_alias(level)}")
        for level in levels[1:]
    ]


def deterministic_rank(gram: np.ndarray, names: Sequence[str], tolerance: float = 1e-10) -> tuple[list[int], dict[str, str]]:
    keep: list[int] = []
    dropped: dict[str, str] = {}
    scale = max(float(np.max(np.diag(gram))), 1.0)
    for index, name in enumerate(names):
        own = float(gram[index, index])
        if own <= tolerance * scale:
            dropped[name] = "zero_or_unsupported"
            continue
        if keep:
            cross = gram[np.ix_(keep, [index])].reshape(-1)
            base = gram[np.ix_(keep, keep)]
            residual = own - float(cross @ np.linalg.pinv(base, rcond=tolerance) @ cross)
            if residual <= tolerance * max(own, scale):
                dropped[name] = "deterministically_collinear"
                continue
        keep.append(index)
    return keep, dropped


def record_batches(database, query: str, rows_per_batch: int = 200_000):
    reader = database.execute(query).to_arrow_reader(batch_size=rows_per_batch)
    for batch in reader:
        yield batch


def batch_matrix(batch, names: Sequence[str]) -> np.ndarray:
    return np.column_stack(
        [np.asarray(batch.column(batch.schema.get_field_index(name)).to_numpy(zero_copy_only=False), dtype=float) for name in names]
    )


def fit_collapsed_model(
    database,
    *,
    table: str,
    condition: str,
    model_name: str,
    terms: Sequence[tuple[str, str]],
    primary_terms: Sequence[str],
) -> tuple[dict[str, Any], pd.DataFrame]:
    aliases = [alias for _, alias in terms]
    select_terms = ",\n".join(f"({expression})::DOUBLE AS {alias}" for expression, alias in terms)
    query = f"""
      SELECT cluster_code::BIGINT AS cluster_code,
             opportunities::DOUBLE AS opportunities,
             kind_draws::DOUBLE AS kind_draws,
             {select_terms}
      FROM {table}
      WHERE {condition}
    """
    gram = np.zeros((len(aliases), len(aliases)), dtype=float)
    x_y = np.zeros(len(aliases), dtype=float)
    observations = 0
    collapsed_rows = 0
    print(f"Opportunity model first pass: {model_name}", flush=True)
    for batch in record_batches(database, query):
        n = np.asarray(batch.column(batch.schema.get_field_index("opportunities")).to_numpy(zero_copy_only=False), dtype=float)
        successes = np.asarray(batch.column(batch.schema.get_field_index("kind_draws")).to_numpy(zero_copy_only=False), dtype=float)
        x = batch_matrix(batch, aliases)
        gram += x.T @ (x * n[:, None])
        x_y += x.T @ (100.0 * successes)
        observations += int(n.sum())
        collapsed_rows += len(n)

    keep, dropped = deterministic_rank(gram, aliases)
    if not keep:
        raise RuntimeError(f"No supported terms in {model_name}")
    kept = [aliases[index] for index in keep]
    gram_kept = gram[np.ix_(keep, keep)]
    inverse = np.linalg.pinv(gram_kept, rcond=1e-12)
    beta = inverse @ x_y[keep]
    k = len(kept)

    meat_hc = np.zeros((k, k), dtype=float)
    meat_cluster = np.zeros((k, k), dtype=float)
    clusters = 0
    pending_code: int | None = None
    pending_score = np.zeros(k, dtype=float)
    ordered_query = query + " ORDER BY cluster_code"
    print(f"Opportunity model covariance pass: {model_name}", flush=True)
    for batch in record_batches(database, ordered_query):
        codes = np.asarray(batch.column(batch.schema.get_field_index("cluster_code")).to_numpy(zero_copy_only=False), dtype=np.int64)
        n = np.asarray(batch.column(batch.schema.get_field_index("opportunities")).to_numpy(zero_copy_only=False), dtype=float)
        successes = np.asarray(batch.column(batch.schema.get_field_index("kind_draws")).to_numpy(zero_copy_only=False), dtype=float)
        x_all = batch_matrix(batch, aliases)
        x = x_all[:, keep]
        prediction = x @ beta
        cluster_scalar = 100.0 * successes - n * prediction
        row_scores = x * cluster_scalar[:, None]

        hc_residual_ss = successes * (100.0 - prediction) ** 2 + (n - successes) * prediction**2
        meat_hc += x.T @ (x * hc_residual_ss[:, None])

        starts = np.r_[0, np.flatnonzero(codes[1:] != codes[:-1]) + 1]
        segment_codes = codes[starts]
        segment_scores = np.add.reduceat(row_scores, starts, axis=0)
        if pending_code is not None:
            if int(segment_codes[0]) != pending_code:
                meat_cluster += np.outer(pending_score, pending_score)
                clusters += 1
            else:
                segment_scores[0] += pending_score
        if len(segment_scores) > 1:
            complete = segment_scores[:-1]
            meat_cluster += complete.T @ complete
            clusters += len(complete)
        pending_code = int(segment_codes[-1])
        pending_score = segment_scores[-1].copy()
    if pending_code is not None:
        meat_cluster += np.outer(pending_score, pending_score)
        clusters += 1

    hc_scale = observations / max(observations - k, 1)
    hc_cov = hc_scale * inverse @ meat_hc @ inverse
    cr_scale = (clusters / (clusters - 1.0)) * ((observations - 1.0) / max(observations - k, 1)) if clusters > 1 else math.nan
    cr_cov = cr_scale * inverse @ meat_cluster @ inverse

    rows: list[dict[str, Any]] = []
    for covariance, vcov in [("HC1", hc_cov), ("CR1_chooser", cr_cov)]:
        for index, name in enumerate(kept):
            coefficient = float(beta[index])
            se = math.sqrt(max(float(vcov[index, index]), 0.0))
            statistic = coefficient / se if se > 0 else math.nan
            rows.append(
                {
                    "model": model_name,
                    "estimand_class": "appendix_secondary",
                    "variable": name,
                    "primary_term": name in set(primary_terms),
                    "status": "estimated",
                    "coefficient_pp": coefficient,
                    "se_pp": se,
                    "statistic": statistic,
                    "p_two_sided_approx": normal_two_sided_p(statistic),
                    "ci95_low_pp": coefficient - 1.959963984540054 * se,
                    "ci95_high_pp": coefficient + 1.959963984540054 * se,
                    "covariance": covariance,
                    "opportunities": observations,
                    "collapsed_rows": collapsed_rows,
                    "chooser_clusters": clusters,
                    "rank": k,
                }
            )
        for name, reason in dropped.items():
            rows.append(
                {
                    "model": model_name,
                    "estimand_class": "appendix_secondary",
                    "variable": name,
                    "primary_term": name in set(primary_terms),
                    "status": "dropped",
                    "drop_reason": reason,
                    "covariance": covariance,
                    "opportunities": observations,
                    "collapsed_rows": collapsed_rows,
                    "chooser_clusters": clusters,
                    "rank": k,
                }
            )
    model = {
        "model": model_name,
        "status": "estimated",
        "estimand_class": "appendix_secondary",
        "condition": condition,
        "requested_terms": aliases,
        "kept_terms": kept,
        "dropped_terms": dropped,
        "primary_terms": list(primary_terms),
        "opportunities": observations,
        "collapsed_rows": collapsed_rows,
        "chooser_clusters": clusters,
        "rank": k,
        "outcome": "kind draw in percentage points",
        "inference": "HC1 and CR1 clustered by normalized chooser account",
    }
    return model, pd.DataFrame(rows)


def control_terms(database, table: str) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = [("1.0", "intercept"), ("tournament_like::INTEGER", "tournament_like")]
    for column, prefix in [
        ("month", "month"),
        ("speed_group", "speed"),
        ("chooser_clock_bin", "chooser_clock"),
        ("disconnected_clock_bin", "disconnected_clock"),
        ("rating_gap_bin", "rating_gap"),
    ]:
        levels = [str(row[0]) for row in database.execute(f"SELECT DISTINCT {column} FROM {table} ORDER BY {column}").fetchall()]
        terms.extend(dummy_expressions(column, levels, prefix))
    return terms


def main() -> None:
    args = parse_args()
    started = time.time()
    project_root = args.project_root.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    private_cache = output_root / "private_cache"
    public_results = output_root / "public_results"
    receipts = output_root / "run_receipts"
    if not (receipts / "01_chooser_models_stage_success.json").is_file():
        raise RuntimeError("Chooser models must complete before the opportunity appendix")
    verify_software_exact(args.fixture)

    stage_success_path = receipts / "02_opportunity_models_stage_success.json"
    cache_path = private_cache / "opportunity_cells_private.parquet"
    if stage_success_path.exists():
        stage = load_json(stage_success_path)
        if stage.get("status") != "PATRON_STAGE10_OPPORTUNITY_MODELS_OK":
            raise RuntimeError("Completed opportunity-model stage has an invalid status")
        output_hashes = stage.get("public_output_hashes")
        if not isinstance(output_hashes, dict) or not output_hashes:
            raise RuntimeError("Completed opportunity-model stage has no output hashes")
        failed: list[str] = []
        if not cache_path.is_file() or sha256_file(cache_path) != stage.get("opportunity_cache_sha256"):
            failed.append(cache_path.name)
        for name, expected_hash in output_hashes.items():
            path = public_results / name
            if not path.is_file() or sha256_file(path) != expected_hash:
                failed.append(name)
        if failed:
            raise RuntimeError(
                "Completed opportunity-model stage failed authentication: "
                + ", ".join(sorted(failed))
            )
        print(
            "PATRON_STAGE10_OPPORTUNITY_MODELS_STAGE_AUTHENTICATED_AND_SKIPPED",
            flush=True,
        )
        return

    database = connect_database(private_cache / "opportunity_models.duckdb", args.threads, args.memory_limit)
    cache_receipt_path = receipts / "opportunity_cache_success.json"
    try:
        if cache_path.exists() and cache_receipt_path.exists() and not args.force_rebuild:
            receipt = load_json(cache_receipt_path)
            if receipt.get("cache_sha256") != sha256_file(cache_path):
                raise RuntimeError("Opportunity cache authentication failed")
            qa = receipt["qa"]
            print("PATRON_STAGE10_OPPORTUNITY_CACHE_AUTHENTICATED_AND_SKIPPED", flush=True)
        else:
            if cache_path.exists() or cache_receipt_path.exists():
                raise RuntimeError("Partial opportunity cache exists; do not overwrite without --force-rebuild")
            build_opportunity_cache(database, project_root, cache_path)
            qa = cache_qa(database, cache_path, project_root)
            receipt = {
                "created_utc": utc_now(),
                "status": "PATRON_STAGE10_OPPORTUNITY_CACHE_OK",
                "cache_path": str(cache_path),
                "cache_bytes": cache_path.stat().st_size,
                "cache_sha256": sha256_file(cache_path),
                "qa": qa,
                "patron_outcome_in_cache": False,
                "contains_private_identifiers": True,
                "publish": False,
            }
            atomic_write_json(cache_receipt_path, receipt)

        snapshot = project_root / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet"
        database.execute(
            f"""
            CREATE OR REPLACE TABLE opportunity_analysis AS
            WITH users AS (
              SELECT
                username_norm,
                patron::INTEGER AS patron,
                ROW_NUMBER() OVER (ORDER BY username_norm)-1 AS cluster_code
              FROM read_parquet({sql_string(snapshot)})
              WHERE returned
            )
            SELECT c.*, u.patron, u.cluster_code
            FROM read_parquet({sql_string(cache_path)}) c
            JOIN users u USING(username_norm)
            ORDER BY u.cluster_code
            """
        )

        controls = control_terms(database, "opportunity_analysis")
        desert_primary = [
            ("patron", "patron"),
            ("(fairness_bin='disconnected_better')::INTEGER", "eval_disconnected_better"),
            ("(fairness_bin='roughly_equal')::INTEGER", "eval_roughly_equal"),
            ("(fairness_bin='modestly_worse_excluded')::INTEGER", "eval_modestly_worse"),
            ("(fairness_bin='clearly_worse')::INTEGER", "eval_clearly_worse"),
            ("patron*(fairness_bin='disconnected_better')::INTEGER", "patron_x_eval_disconnected_better"),
            ("patron*(fairness_bin='roughly_equal')::INTEGER", "patron_x_eval_roughly_equal"),
            ("patron*(fairness_bin='modestly_worse_excluded')::INTEGER", "patron_x_eval_modestly_worse"),
            ("patron*(fairness_bin='clearly_worse')::INTEGER", "patron_x_eval_clearly_worse"),
        ]
        price_primary = [
            ("patron", "patron"),
            ("favorable_draw::INTEGER", "favorable_draw"),
            ("patron*favorable_draw::INTEGER", "patron_x_favorable_draw"),
        ]
        triple_primary = [
            ("patron", "patron"),
            ("fair_competitive::INTEGER", "fair_state"),
            ("favorable_draw::INTEGER", "favorable_draw"),
            ("patron*fair_competitive::INTEGER", "patron_x_fair"),
            ("patron*favorable_draw::INTEGER", "patron_x_favorable"),
            ("fair_competitive::INTEGER*favorable_draw::INTEGER", "fair_x_favorable"),
            ("patron*fair_competitive::INTEGER*favorable_draw::INTEGER", "patron_x_fair_x_favorable"),
        ]

        models: list[dict[str, Any]] = []
        coefficient_frames: list[pd.DataFrame] = []
        for name, condition, primary in [
            ("patron_by_five_bin_desert_gradient", "TRUE", desert_primary),
            ("patron_by_favorable_price_in_fair_states", "fair_competitive", price_primary),
            ("patron_by_fair_state_by_favorable_price", "fair_competitive OR clearly_worse", triple_primary),
        ]:
            terms = controls + primary
            # Preserve first occurrence of each alias and put primary terms after generic controls only
            # when aliases do not collide (the intercept is always first).
            unique: list[tuple[str, str]] = []
            seen: set[str] = set()
            for expression, alias in terms:
                if alias not in seen:
                    unique.append((expression, alias))
                    seen.add(alias)
            model, coefficients = fit_collapsed_model(
                database,
                table="opportunity_analysis",
                condition=condition,
                model_name=name,
                terms=unique,
                primary_terms=[alias for _, alias in primary],
            )
            models.append(model)
            coefficient_frames.append(coefficients)

        coefficients = pd.concat(coefficient_frames, ignore_index=True)
        write_csv(public_results / "opportunity_model_coefficients.csv", coefficients)
        atomic_write_json(public_results / "opportunity_models.json", models)
        atomic_write_json(
            public_results / "opportunity_support.json",
            {
                "created_utc": utc_now(),
                "cache_qa": qa,
                "models": [
                    {
                        "model": model["model"],
                        "opportunities": model["opportunities"],
                        "collapsed_rows": model["collapsed_rows"],
                        "chooser_clusters": model["chooser_clusters"],
                    }
                    for model in models
                ],
                "interpretation": "These appendix regressions condition on current patron status and describe how patrons behave across desert and price states. They do not estimate patron adoption or a causal patron effect.",
            },
        )
        stage = {
            "created_utc": utc_now(),
            "version": VERSION,
            "status": "PATRON_STAGE10_OPPORTUNITY_MODELS_OK",
            "fixture": args.fixture,
            "runtime_seconds": round(time.time() - started, 3),
            "models": len(models),
            "coefficient_rows": len(coefficients),
            "opportunity_cache_sha256": sha256_file(cache_path),
            "public_output_hashes": {
                name: sha256_file(public_results / name)
                for name in [
                    "opportunity_model_coefficients.csv",
                    "opportunity_models.json",
                    "opportunity_support.json",
                ]
            },
            "runtime": runtime_record(),
        }
        atomic_write_json(stage_success_path, stage)
        print("PATRON_STAGE10_OPPORTUNITY_MODELS_OK", flush=True)
        print(f"Runtime seconds: {time.time() - started:.3f}", flush=True)
    finally:
        database.close()


if __name__ == "__main__":
    main()
