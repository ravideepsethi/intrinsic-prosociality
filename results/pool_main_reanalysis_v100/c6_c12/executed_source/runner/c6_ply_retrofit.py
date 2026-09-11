#!/usr/bin/env python3
"""Pre-scoped C6 game-stage sensitivity for the pool-main reset.

The frozen C6 primary is left untouched.  This module asks whether its sign and
interpretation survive (a) restricting the received act to ply > 10 and (b)
counting only later timeout events observed after ply 10.  All gates are frozen
on pooled support before the receipt arm is inspected.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Sequence


HORIZON_90D_MS = 90 * 86_400_000
MINIMUM_POOLED_RECIPIENTS_WITH_LATE_TIMEOUT = 4_000
MINIMUM_POOLED_CLEAR_LATE_TIMEOUTS = 4_000


def _checkpoint(
    *,
    cohort_index: Path,
    stage_paths: Sequence[Path],
    state: Path,
    campaign_common: Any,
    config_sha256: str,
    threads: int,
    memory_limit: str,
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = campaign_common.import_dependencies()
    output = state / "c6_later_timeout_events_ply_gt10_90d_private.parquet"
    receipt = state / "c6_later_timeout_events_ply_gt10_90d_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = campaign_common.load_json(receipt)
        expected = {
            "status": "C6_PLY_GT10_EVENT_CACHE_PRIVATE_OK",
            "config_sha256": config_sha256,
            "output_sha256": campaign_common.sha256_file(output),
            "rows": int(pq.ParquetFile(output).metadata.num_rows),
        }
        for key, value in expected.items():
            if saved.get(key) != value:
                raise RuntimeError(f"C6 ply checkpoint mismatch: {key}")
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C6 ply checkpoint exists")

    state.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection = duckdb.connect()
    campaign_common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c6_ply_events",
    )
    try:
        connection.execute(
            f"""
            COPY (
              WITH cohort AS (
                SELECT cohort_row_id, recipient_user_id, exposure_anchor_utc_ms
                FROM read_parquet({campaign_common.sql_literal(cohort_index)})
              ), events AS (
                SELECT
                  CAST(disconnected_user_id AS BIGINT) AS recipient_user_id,
                  CAST(api_last_move_at_ms AS BIGINT) AS event_utc_ms,
                  CAST(clearly_worse AS BOOLEAN) AS clearly_worse,
                  CAST(tournament_like_event AS BOOLEAN) AS tournament_like,
                  CAST(ply_count AS DOUBLE) AS ply_count
                FROM read_parquet(
                  {campaign_common.path_list_literal(stage_paths)}, union_by_name=true
                )
                WHERE disconnected_user_id IS NOT NULL
                  AND api_last_move_at_ms IS NOT NULL
                  AND ply_count IS NOT NULL
                  AND CAST(ply_count AS DOUBLE) > 10
              ), aggregated AS (
                SELECT
                  c.cohort_row_id,
                  COUNT(*)::BIGINT AS all_timeout_count_90d_ply_gt10,
                  COUNT(*) FILTER (WHERE e.clearly_worse)::BIGINT
                    AS clearly_losing_count_90d_ply_gt10,
                  COUNT(*) FILTER (WHERE NOT e.tournament_like)::BIGINT
                    AS all_timeout_count_90d_ply_gt10_no_tournament,
                  COUNT(*) FILTER (
                    WHERE e.clearly_worse AND NOT e.tournament_like
                  )::BIGINT AS clearly_losing_count_90d_ply_gt10_no_tournament
                FROM cohort c INNER JOIN events e
                  ON e.recipient_user_id = c.recipient_user_id
                 AND e.event_utc_ms > c.exposure_anchor_utc_ms
                 AND e.event_utc_ms <= c.exposure_anchor_utc_ms + {HORIZON_90D_MS}
                GROUP BY c.cohort_row_id
              )
              SELECT
                c.cohort_row_id,
                COALESCE(a.all_timeout_count_90d_ply_gt10, 0)::BIGINT
                  AS all_timeout_count_90d_ply_gt10,
                COALESCE(a.clearly_losing_count_90d_ply_gt10, 0)::BIGINT
                  AS clearly_losing_count_90d_ply_gt10,
                COALESCE(a.all_timeout_count_90d_ply_gt10_no_tournament, 0)::BIGINT
                  AS all_timeout_count_90d_ply_gt10_no_tournament,
                COALESCE(
                  a.clearly_losing_count_90d_ply_gt10_no_tournament, 0
                )::BIGINT AS clearly_losing_count_90d_ply_gt10_no_tournament
              FROM cohort c LEFT JOIN aggregated a USING (cohort_row_id)
              ORDER BY c.cohort_row_id
            ) TO {campaign_common.sql_literal(temporary)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        qa = connection.execute(
            f"""
            SELECT COUNT(*),
                   COUNT(*) FILTER (WHERE all_timeout_count_90d_ply_gt10 > 0),
                   SUM(all_timeout_count_90d_ply_gt10),
                   SUM(clearly_losing_count_90d_ply_gt10),
                   SUM(all_timeout_count_90d_ply_gt10_no_tournament),
                   SUM(clearly_losing_count_90d_ply_gt10_no_tournament)
            FROM read_parquet({campaign_common.sql_literal(temporary)})
            """
        ).fetchone()
    finally:
        connection.close()
        shutil.rmtree(state / "duckdb_temp/c6_ply_events", ignore_errors=True)
    cohort_rows = int(pq.ParquetFile(cohort_index).metadata.num_rows)
    if int(qa[0]) != cohort_rows or any(value is None for value in qa[1:]):
        raise RuntimeError(f"C6 ply event-cache conservation failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "C6_PLY_GT10_EVENT_CACHE_PRIVATE_OK",
        "created_utc": campaign_common.utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_sha256": campaign_common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": int(qa[0]),
        "recipients_with_any_later_timeout_ply_gt10": int(qa[1]),
        "pooled_all_timeout_events_ply_gt10": int(qa[2]),
        "pooled_clearly_losing_events_ply_gt10": int(qa[3]),
        "pooled_all_timeout_events_ply_gt10_no_tournament": int(qa[4]),
        "pooled_clearly_losing_events_ply_gt10_no_tournament": int(qa[5]),
        "treatment_field_read": False,
        "event_stage_rule": "ply_count > 10",
        "privacy": "PRIVATE ACCOUNT-LEVEL EVENT COUNTS; DO NOT PUBLISH",
    }
    campaign_common.atomic_json(receipt, saved)
    return output, saved


def _arm_descriptives(
    *, data: dict[str, Any], support: dict[str, Any], sample: Any,
    clear: Any, all_timeout: Any, games: Any, np: Any
) -> dict[str, Any]:
    treatment = data["received_mercy"].astype(bool)
    weights = support["weights"]
    output: dict[str, Any] = {}
    for label, arm in (("mercy", treatment), ("claimed", ~treatment)):
        mask = sample & support["eligible"] & arm
        weighted_games = float(np.sum(weights[mask] * games[mask]))
        weighted_clear = float(np.sum(weights[mask] * clear[mask]))
        weighted_all = float(np.sum(weights[mask] * all_timeout[mask]))
        output[label] = {
            "rows": int(np.count_nonzero(mask)),
            "positive_rated_game_denominator_rows": int(
                np.count_nonzero(mask & (games > 0))
            ),
            "weighted_clear_events_per_1000_rated_games": (
                1000.0 * weighted_clear / weighted_games if weighted_games > 0 else None
            ),
            "weighted_clear_share_of_late_timeouts": (
                weighted_clear / weighted_all if weighted_all > 0 else None
            ),
        }
    return output


def execute(
    *,
    recipient: Path,
    stage_paths: Sequence[Path],
    c6_state: Path,
    state: Path,
    public_stage: Path,
    core: Any,
    c6: Any,
    campaign_common: Any,
    config_sha256: str,
    threads: int,
    memory_limit: str,
) -> dict[str, Any]:
    started = time.time()
    cohort = c6_state / "c6_preoutcome_cohort_private.parquet"
    denominator_path = c6_state / "c6_rated_games_90d_private.parquet"
    original_events_path = c6_state / "c6_later_timeout_events_90d_private.parquet"
    for path in (cohort, denominator_path, original_events_path):
        if not path.is_file():
            raise RuntimeError(f"C6 prerequisite checkpoint is missing: {path}")
    original_gate_path = c6_state / "c6_support_gate_frozen_before_arm_split.json"
    if not original_gate_path.is_file():
        raise RuntimeError(f"Frozen parent C6 gate is missing: {original_gate_path}")
    original_gate = campaign_common.load_json(original_gate_path)
    if original_gate.get("config_sha256") != config_sha256:
        raise RuntimeError("Frozen parent C6 gate belongs to another configuration")
    ply_path, ply_receipt = _checkpoint(
        cohort_index=cohort,
        stage_paths=stage_paths,
        state=state,
        campaign_common=campaign_common,
        config_sha256=config_sha256,
        threads=threads,
        memory_limit=memory_limit,
    )

    np = campaign_common.import_numpy()
    data = c6._load_recipient_minimal(recipient, core)
    support = core.common_support_weights(data)
    total_rows = int(data["cohort_row_id"].size)
    denominator = c6._expand_cache(
        denominator_path, total_rows, ["rated_games_90d"]
    )
    original = c6._expand_cache(
        original_events_path,
        total_rows,
        ["all_timeout_count_90d", "clearly_losing_count_90d"],
    )
    late = c6._expand_cache(
        ply_path,
        total_rows,
        [
            "all_timeout_count_90d_ply_gt10",
            "clearly_losing_count_90d_ply_gt10",
            "all_timeout_count_90d_ply_gt10_no_tournament",
            "clearly_losing_count_90d_ply_gt10_no_tournament",
        ],
    )
    games = denominator["rated_games_90d"].astype(np.float64)
    original_clear = original["clearly_losing_count_90d"].astype(np.float64)
    late_all = late["all_timeout_count_90d_ply_gt10"].astype(np.float64)
    late_clear = late["clearly_losing_count_90d_ply_gt10"].astype(np.float64)
    late_all_nt = late[
        "all_timeout_count_90d_ply_gt10_no_tournament"
    ].astype(np.float64)
    late_clear_nt = late[
        "clearly_losing_count_90d_ply_gt10_no_tournament"
    ].astype(np.float64)
    first_followup = (
        data["first_ever_pair"].astype(bool)
        & data["arm_eligible"].astype(bool)
        & data["a1_90d_followup_eligible"].astype(bool)
    )
    exposure_late = np.asarray(data["exposure_ply_count"], dtype=np.float64) > 10
    pooled_gate = {
        "status": "C6_PLY_RETROFIT_TREATMENT_BLIND_SUPPORT_FROZEN",
        "created_utc": campaign_common.utc_now(),
        "config_sha256": config_sha256,
        "event_stage_rule": "later timeout ply_count > 10",
        "exposure_stage_rule": "received act ply_count > 10",
        "eligible_first_followup_rows": int(np.count_nonzero(first_followup)),
        "eligible_exposure_ply_gt10_rows": int(
            np.count_nonzero(first_followup & exposure_late)
        ),
        "recipients_with_any_later_timeout_ply_gt10": int(
            ply_receipt["recipients_with_any_later_timeout_ply_gt10"]
        ),
        "pooled_clearly_losing_events_ply_gt10": int(
            ply_receipt["pooled_clearly_losing_events_ply_gt10"]
        ),
        "minimum_recipients_with_any_later_timeout": (
            MINIMUM_POOLED_RECIPIENTS_WITH_LATE_TIMEOUT
        ),
        "minimum_pooled_clearly_losing_events": MINIMUM_POOLED_CLEAR_LATE_TIMEOUTS,
        "parent_c6_support_gate_pass": bool(original_gate.get("gate_pass")),
        "gate_pass": (
            bool(original_gate.get("gate_pass"))
            and int(ply_receipt["recipients_with_any_later_timeout_ply_gt10"])
            >= MINIMUM_POOLED_RECIPIENTS_WITH_LATE_TIMEOUT
            and int(ply_receipt["pooled_clearly_losing_events_ply_gt10"])
            >= MINIMUM_POOLED_CLEAR_LATE_TIMEOUTS
        ),
        "arm_specific_outcomes_inspected_before_gate": False,
    }
    gate_path = state / "c6_ply_support_gate_frozen.json"
    if gate_path.is_file():
        saved_gate = campaign_common.load_json(gate_path)
        for key in (
            "config_sha256",
            "eligible_first_followup_rows",
            "eligible_exposure_ply_gt10_rows",
            "recipients_with_any_later_timeout_ply_gt10",
            "pooled_clearly_losing_events_ply_gt10",
            "parent_c6_support_gate_pass",
            "gate_pass",
        ):
            if saved_gate.get(key) != pooled_gate.get(key):
                raise RuntimeError(f"Frozen C6 ply support gate changed: {key}")
        pooled_gate = saved_gate
    else:
        campaign_common.atomic_json(gate_path, pooled_gate)

    data.update(
        {
            "c6_original_clear_rate_per_1000": campaign_common.rate_from_counts(
                original_clear, games, scale=1000
            ),
            "c6_original_clear_count": original_clear,
            "c6_later_ply_gt10_clear_rate_per_1000_all_rated_games": (
                campaign_common.rate_from_counts(late_clear, games, scale=1000)
            ),
            "c6_later_ply_gt10_clear_count": late_clear,
            "c6_later_ply_gt10_clear_share": campaign_common.rate_from_counts(
                late_clear, late_all
            ),
            "c6_later_ply_gt10_clear_rate_no_tournament_per_1000_all_rated_games": (
                campaign_common.rate_from_counts(late_clear_nt, games, scale=1000)
            ),
            "c6_later_ply_gt10_clear_share_no_tournament": (
                campaign_common.rate_from_counts(late_clear_nt, late_all_nt)
            ),
        }
    )
    models: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    if pooled_gate["gate_pass"]:
        specifications = [
            (
                "c6_original_clear_rate_per_1000",
                "S_ply_retrofit_exposure_ply_gt10_original_primary_outcome",
                first_followup & exposure_late,
            ),
            (
                "c6_original_clear_count",
                "S_ply_retrofit_exposure_ply_gt10_unnormalized_count",
                first_followup & exposure_late,
            ),
            (
                "c6_later_ply_gt10_clear_rate_per_1000_all_rated_games",
                "S_ply_retrofit_later_event_ply_gt10_per_all_rated_games",
                first_followup,
            ),
            (
                "c6_later_ply_gt10_clear_count",
                "S_ply_retrofit_both_exposure_and_later_event_ply_gt10_count",
                first_followup & exposure_late,
            ),
            (
                "c6_later_ply_gt10_clear_share",
                "S_ply_retrofit_both_ply_gt10_clear_share_conditional_timeout",
                first_followup & exposure_late & (late_all > 0),
            ),
            (
                "c6_later_ply_gt10_clear_share_no_tournament",
                "S_ply_retrofit_both_ply_gt10_clear_share_no_tournament",
                first_followup & exposure_late & (late_all_nt > 0),
            ),
        ]
        for outcome, estimand, sample in specifications:
            attempt = {
                "analysis": "C6_ply_retrofit",
                "outcome": outcome,
                "estimand": estimand,
                "requested_rows_before_common_support": int(np.count_nonzero(sample)),
                "epistemic_label": "S",
                "holm_family_member": False,
            }
            try:
                fitted = core.fit_recipient_outcome(
                    data=data,
                    support=support,
                    outcome_name=outcome,
                    sample=sample,
                    estimand=estimand,
                    state_conditioned=False,
                    binary_outcome=False,
                )
                fitted.update(
                    {
                        "analysis": "C6_ply_retrofit",
                        "epistemic_label": "S",
                        "holm_family_member": False,
                        "pre_scoped_robustness_only": True,
                    }
                )
                models.append(fitted)
                attempt.update({"status": "ESTIMATED", "error": None})
            except RuntimeError as exc:
                attempt.update({"status": "NOT_ESTIMABLE_RETAINED", "error": str(exc)})
            attempts.append(attempt)

    descriptions = {
        "all_first_followup": _arm_descriptives(
            data=data,
            support=support,
            sample=first_followup,
            clear=late_clear,
            all_timeout=late_all,
            games=games,
            np=np,
        ),
        "exposure_ply_gt10_first_followup": _arm_descriptives(
            data=data,
            support=support,
            sample=first_followup & exposure_late,
            clear=late_clear,
            all_timeout=late_all,
            games=games,
            np=np,
        ),
    }
    result = {
        "status": (
            "C6_PLY_RETROFIT_ESTIMATED"
            if pooled_gate["gate_pass"]
            else "C6_PLY_RETROFIT_NOT_ESTIMABLE_POOLED_SUPPORT_GATE_FAILED"
        ),
        "created_utc": campaign_common.utc_now(),
        "runtime_seconds": time.time() - started,
        "epistemic_label": "S",
        "primary_c6_estimator_changed": False,
        "new_holm_family_member": False,
        "support_gate": pooled_gate,
        "models": models,
        "model_attempts": attempts,
        "arm_descriptives": descriptions,
        "denominator_note": (
            "The later-event-ply>10 rate counts such events per 1,000 all rated games; "
            "the all-game chronology does not contain ply and therefore cannot supply "
            "a denominator restricted to games continuing past ply 10."
        ),
        "claim_boundary": (
            "Pre-scoped robustness check only. Exposure-ply and later-event-ply "
            "restrictions do not create a new confirmatory estimand."
        ),
        "account_level_output": False,
        "api_requests": 0,
    }
    public_stage.mkdir(parents=True, exist_ok=True)
    campaign_common.atomic_json(public_stage / "c6_ply_results.json", result)
    campaign_common.atomic_json(public_stage / "c6_ply_support_gate.json", pooled_gate)
    if models:
        campaign_common.write_csv(public_stage / "c6_ply_models.csv", models)
    if attempts:
        campaign_common.write_csv(public_stage / "c6_ply_model_attempts.csv", attempts)
    return result


def self_test() -> None:
    if HORIZON_90D_MS != 7_776_000_000:
        raise RuntimeError("C6 ply horizon changed")
    if MINIMUM_POOLED_RECIPIENTS_WITH_LATE_TIMEOUT != 4_000:
        raise RuntimeError("C6 ply support gate changed")
    print("POOL_MAIN_C6_PLY_RETROFIT_SELF_TEST_OK")
