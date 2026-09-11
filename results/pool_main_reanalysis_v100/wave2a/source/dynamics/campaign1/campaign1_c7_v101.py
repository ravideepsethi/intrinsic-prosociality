#!/usr/bin/env python3
"""C7 direct reciprocity in the deterministic pair sample.

The treatment-outcome-blind support gate remains frozen and reported.  Under
the user's exhaustive-analysis instruction, v1.0.1 also estimates and exports
the low-support contrasts when that gate fails, labeling them exploratory and
retaining explicit support diagnostics.  They do not enter Holm family D.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import time
from typing import Any, Sequence
import uuid

import campaign1_nonprofile_common_v102 as common


SCRIPT_VERSION = "1.0.1"
EXPECTED_HISTORY_SUCCESS_SHA256 = (
    "62e4b8335b188f374f83bf1debedc19c62a91769f89a7c12368a628cb26d6de5"
)
PAIR_SAMPLE_DENOMINATOR = 50
C7_BENEFACTOR_GATE = 1_000


def _pair_paths(root: Path) -> list[Path]:
    paths = [root / f"bucket_{index:02d}.parquet" for index in range(16)]
    if not all(path.is_file() for path in paths):
        raise RuntimeError("C7 pair-history bucket authority is incomplete")
    return paths


def _authenticate_pair_history(state: Path, paths: Sequence[Path]) -> None:
    _, _, _, pq = common.import_dependencies()
    for bucket, path in enumerate(paths):
        receipt_path = state / "pair_bucket_receipts" / f"bucket_{bucket:02d}.json"
        if not receipt_path.is_file():
            raise RuntimeError(f"C7 pair-history receipt is missing: {bucket}")
        receipt = common.load_json(receipt_path)
        expected = {
            "status": "DYNAMIC_SECOND_WAVE_PAIR_BUCKET_OK",
            "bucket": bucket,
            "output_path": str(path),
            "output_rows": int(pq.ParquetFile(path).metadata.num_rows),
            "output_bytes": path.stat().st_size,
            "output_sha256": common.sha256_file(path),
        }
        for key, value in expected.items():
            if receipt.get(key) != value:
                raise RuntimeError(f"C7 pair-history checkpoint mismatch: bucket={bucket} key={key}")


def build_c7_classification_cache(
    *, pair_paths: Sequence[Path], stage07_paths: Sequence[Path], state: Path,
    threads: int, memory_limit: str, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c7_prior_pair_classification_private.parquet"
    receipt = state / "c7_prior_pair_classification_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = common.load_json(receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
        ):
            raise RuntimeError("C7 classification checkpoint mismatch")
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C7 classification checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c7_classification",
    )
    speed_focal = common.speed_code_sql("s.api_speed")
    speed_prior = common.speed_code_sql("p.api_speed")
    eval_bin = common.eval_bin_sql("s.engine_eval_cp_disconnected")
    hour_week = common.hour_of_week_sql("s.api_last_move_at_ms")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH pair_targets AS (
            SELECT low_id, high_id, game_id, utc_ms, archive_ordinal,
                   pair_sequence, speed
            FROM read_parquet({common.path_list_literal(pair_paths)}, union_by_name=true)
            WHERE CAST(is_stage07_target AS BOOLEAN) AND pair_sequence > 1
          ), focal AS (
            SELECT
              h.low_id, h.high_id, h.pair_sequence,
              CAST(h.utc_ms AS BIGINT) AS focal_game_utc_ms,
              CAST(h.archive_ordinal AS BIGINT) AS focal_archive_ordinal,
              CAST(s.game_id AS VARCHAR) AS game_id,
              CAST(s.chooser_user_id AS BIGINT) AS chooser_id,
              CAST(s.disconnected_user_id AS BIGINT) AS opponent_id,
              CAST(s.api_last_move_at_ms AS BIGINT) AS decision_utc_ms,
              CAST({speed_focal} AS INTEGER) AS speed_code,
              CAST({eval_bin} AS INTEGER) AS eval_bin,
              CAST(date_diff('month', DATE '2023-11-01', strptime(s.month || '-01', '%Y-%m-%d')) AS INTEGER) AS month_code,
              CAST({hour_week} AS INTEGER) AS hour_of_week,
              CAST(s.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
              CAST(s.chooser_win_premium_v2 AS DOUBLE) AS win_premium,
              CAST(s.chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock,
              CAST(s.disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock,
              CAST(s.chooser_elo AS DOUBLE) AS chooser_elo,
              CAST(s.disconnected_elo AS DOUBLE) AS opponent_elo,
              CAST(s.chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
              CAST(s.disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
              CAST(s.tournament_like_event AS DOUBLE) AS tournament,
              CAST(hash(CAST(s.game_id AS VARCHAR)) % 9223372036854775807 AS BIGINT) AS row_hash
            FROM pair_targets h
            INNER JOIN read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true) s
              ON CAST(s.game_id AS VARCHAR) = CAST(h.game_id AS VARCHAR)
            WHERE CAST(s.fair_competitive AS BOOLEAN)
          ), prior AS (
            SELECT
              CAST(p.game_id AS VARCHAR) AS prior_game_id,
              LEAST(CAST(p.chooser_user_id AS BIGINT), CAST(p.disconnected_user_id AS BIGINT)) AS low_id,
              GREATEST(CAST(p.chooser_user_id AS BIGINT), CAST(p.disconnected_user_id AS BIGINT)) AS high_id,
              CAST(p.chooser_user_id AS BIGINT) AS prior_chooser_id,
              CAST(p.disconnected_user_id AS BIGINT) AS prior_disconnected_id,
              CAST(p.utc_ms AS BIGINT) AS prior_game_utc_ms,
              CAST(p.archive_ordinal AS BIGINT) AS prior_archive_ordinal,
              CAST(p.kind_draw AS BOOLEAN) AS prior_mercy,
              CAST(p.timeout_chooser_win AS BOOLEAN) AS prior_claim,
              CAST(CAST(p.kind_draw AS BOOLEAN) OR CAST(p.timeout_chooser_win AS BOOLEAN) AS BOOLEAN) AS prior_arm_eligible,
              CAST({speed_prior} AS INTEGER) AS prior_speed_code
            FROM read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true) p
            WHERE p.chooser_user_id IS NOT NULL AND p.disconnected_user_id IS NOT NULL
          ), candidates AS (
            SELECT
              f.game_id, f.speed_code,
              p.prior_game_id, p.prior_game_utc_ms, p.prior_archive_ordinal,
              p.prior_mercy, p.prior_claim, p.prior_arm_eligible,
              p.prior_speed_code
            FROM focal f INNER JOIN prior p
              ON p.low_id = f.low_id AND p.high_id = f.high_id
             AND p.prior_chooser_id = f.opponent_id
             AND p.prior_disconnected_id = f.chooser_id
             AND (
                  p.prior_game_utc_ms < f.focal_game_utc_ms
                  OR (p.prior_game_utc_ms = f.focal_game_utc_ms
                      AND p.prior_archive_ordinal < f.focal_archive_ordinal)
             )
          ), arm_ranked AS (
            SELECT game_id, prior_mercy, prior_claim,
              ROW_NUMBER() OVER (
                PARTITION BY game_id
                ORDER BY prior_game_utc_ms DESC, prior_archive_ordinal DESC,
                         prior_game_id DESC
              ) AS arm_rank
            FROM candidates
            WHERE prior_arm_eligible
          ), same_speed_arm_ranked AS (
            SELECT game_id, prior_mercy, prior_claim,
              ROW_NUMBER() OVER (
                PARTITION BY game_id
                ORDER BY prior_game_utc_ms DESC, prior_archive_ordinal DESC,
                         prior_game_id DESC
              ) AS arm_rank
            FROM candidates
            WHERE prior_arm_eligible AND prior_speed_code = speed_code
          ), summarized AS (
            SELECT
              game_id,
              COUNT(prior_game_id) AS reversed_timeout_events,
              COUNT(prior_game_id) FILTER (WHERE prior_arm_eligible) AS reversed_arm_events,
              BOOL_OR(COALESCE(prior_mercy, FALSE)) AS any_prior_mercy,
              BOOL_OR(COALESCE(prior_claim, FALSE)) AS any_prior_claim
            FROM candidates GROUP BY game_id
          )
          SELECT
            f.*,
            CASE
              WHEN a.prior_mercy THEN 1
              WHEN a.prior_claim THEN 0
              WHEN COALESCE(s.reversed_timeout_events, 0) > 0 THEN 2
              ELSE 3
            END::TINYINT AS primary_prior_category,
            CASE
              WHEN ss.prior_mercy THEN 1
              WHEN ss.prior_claim THEN 0
              ELSE -1
            END::TINYINT AS same_speed_prior_category,
            COALESCE(s.reversed_timeout_events, 0)::BIGINT AS reversed_timeout_events,
            COALESCE(s.reversed_arm_events, 0)::BIGINT AS reversed_arm_events,
            COALESCE(s.any_prior_mercy, FALSE) AS any_prior_mercy,
            COALESCE(s.any_prior_claim, FALSE) AS any_prior_claim,
            (COALESCE(s.any_prior_mercy, FALSE) AND COALESCE(s.any_prior_claim, FALSE)) AS conflicting_prior_arm_history
          FROM focal f
          LEFT JOIN summarized s USING (game_id)
          LEFT JOIN arm_ranked a ON a.game_id = f.game_id AND a.arm_rank = 1
          LEFT JOIN same_speed_arm_ranked ss
            ON ss.game_id = f.game_id AND ss.arm_rank = 1
          ORDER BY f.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
               COUNT(*) FILTER (WHERE primary_prior_category=1),
               COUNT(*) FILTER (WHERE primary_prior_category=0),
               COUNT(*) FILTER (WHERE primary_prior_category=2),
               COUNT(*) FILTER (WHERE primary_prior_category=3),
               COUNT(*) FILTER (WHERE conflicting_prior_arm_history),
               COUNT(*) FILTER (WHERE same_speed_prior_category=1),
               COUNT(*) FILTER (WHERE same_speed_prior_category=0)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    if qa[0] != qa[1] or qa[0] <= 0 or sum(int(value) for value in qa[2:6]) != qa[0]:
        raise RuntimeError(f"C7 classification row conservation failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "C7_PRIOR_PAIR_CLASSIFICATION_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_sha256": common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": int(qa[0]),
        "benefactor_facing_fair_opportunities": int(qa[2]),
        "claimer_facing_fair_opportunities": int(qa[3]),
        "other_reversed_timeout_fair_opportunities": int(qa[4]),
        "prior_meeting_no_reversed_decision_fair_opportunities": int(qa[5]),
        "conflicting_prior_arm_history_opportunities": int(qa[6]),
        "same_speed_benefactor_opportunities": int(qa[7]),
        "same_speed_claimer_opportunities": int(qa[8]),
        "focal_kind_outcome_read": False,
        "privacy": "PRIVATE ROW-LEVEL CLASSIFICATION; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c7_classification", ignore_errors=True)
    return output, saved


def freeze_c7_gate(
    *, classification_receipt: dict[str, Any], state: Path, config_sha256: str
) -> dict[str, Any]:
    path = state / "c7_support_gate_frozen_before_focal_outcome.json"
    benefactor = int(classification_receipt["benefactor_facing_fair_opportunities"])
    payload = {
        "status": "C7_TREATMENT_OUTCOME_BLIND_SUPPORT_GATE_FROZEN",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "benefactor_facing_fair_opportunities": benefactor,
        "minimum_benefactor_facing_fair_opportunities": C7_BENEFACTOR_GATE,
        "gate_pass": benefactor >= C7_BENEFACTOR_GATE,
        "disposition": (
            "ESTIMATE_SECONDARY_C7"
            if benefactor >= C7_BENEFACTOR_GATE
            else "ESTIMATE_EXPLORATORY_WITH_LOW_SUPPORT_WARNING"
        ),
        "focal_kind_outcome_read": False,
    }
    if path.is_file():
        saved = common.load_json(path)
        for key in (
            "config_sha256", "benefactor_facing_fair_opportunities", "gate_pass", "disposition"
        ):
            if saved.get(key) != payload.get(key):
                raise RuntimeError(f"Frozen C7 support gate changed: {key}")
        return saved
    common.atomic_json(path, payload)
    return payload


def build_c7_model_cache(
    *, classification: Path, stage07_paths: Sequence[Path], state: Path,
    threads: int, memory_limit: str, config_sha256: str
) -> Path:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c7_model_private.parquet"
    receipt = state / "c7_model_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = common.load_json(receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
        ):
            raise RuntimeError("C7 model checkpoint mismatch")
        return output
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C7 model checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c7_model",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT c.*, CAST(s.outcome_kind_draw AS DOUBLE) AS kind
          FROM read_parquet({common.sql_literal(classification)}) c
          INNER JOIN read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true) s
            ON CAST(s.game_id AS VARCHAR) = c.game_id
          ORDER BY c.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT game_id), COUNT(*) FILTER (WHERE kind IS NULL) FROM read_parquet({common.sql_literal(temporary)})"
    ).fetchone()
    connection.close()
    if qa[0] != qa[1] or qa[2] or qa[0] <= 0:
        raise RuntimeError(f"C7 focal outcome join failed: {qa}")
    os.replace(temporary, output)
    common.atomic_json(
        receipt,
        {
            "status": "C7_MODEL_PRIVATE_OK",
            "created_utc": common.utc_now(),
            "config_sha256": config_sha256,
            "output_path": str(output),
            "output_sha256": common.sha256_file(output),
            "output_bytes": output.stat().st_size,
            "rows": int(qa[0]),
            "privacy": "PRIVATE ROW-LEVEL MODEL CACHE; DO NOT PUBLISH",
        },
    )
    shutil.rmtree(state / "duckdb_temp/c7_model", ignore_errors=True)
    return output


def _load_model(path: Path) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    table = pq.read_table(path)
    nullable = {
        "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
        "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd"
    }
    return {
        name: common.arrow_numpy(table, name, nullable_float=name in nullable)
        for name in table.column_names
        if name != "game_id"
    }


def _controls(data: dict[str, Any], indices: Any) -> dict[str, Any]:
    return {
        name: data[name][indices]
        for name in (
            "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
            "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd", "tournament"
        )
    }


def _fit_contrast(
    *, data: dict[str, Any], sample: Any, exposure: Any, label: str,
    epistemic_label: str
) -> dict[str, Any]:
    np = common.import_numpy()
    indices = np.flatnonzero(sample)
    fitted = common.fit_hdfe_cluster(
        outcome=data["kind"][indices],
        exposures={"benefactor_minus_claimer": exposure[indices]},
        numeric_controls=_controls(data, indices),
        fixed_effects={
            "chooser": data["chooser_id"][indices],
            "eval_bin": data["eval_bin"][indices],
            "speed": data["speed_code"][indices],
            "month": data["month_code"][indices],
            "hour_of_week": data["hour_of_week"][indices],
        },
        clusters=data["chooser_id"][indices],
        row_ids=data["row_hash"][indices],
        specification={
            "model": label,
            "epistemic_label": epistemic_label,
            "fixed_effects": "chooser + current-state categorical/calendar",
            "cluster": "chooser",
        },
    )
    result = fitted["results"][0]
    return {
        **{key: value for key, value in fitted.items() if key != "results"},
        **result,
        "effect_percentage_points": 100.0 * result["coefficient"],
        "standard_error_percentage_points": 100.0 * result["standard_error"],
        "causal_claim": False,
    }


def _attempt_fit_contrast(
    *, data: dict[str, Any], sample: Any, exposure: Any, label: str,
    epistemic_label: str
) -> dict[str, Any]:
    np = common.import_numpy()
    sample = np.asarray(sample, dtype=bool)
    exposure = np.asarray(exposure, dtype=float)
    indices = np.flatnonzero(sample)
    treated = int(np.count_nonzero(exposure[indices] == 1.0))
    control = int(np.count_nonzero(exposure[indices] == 0.0))
    clusters = int(np.unique(data["chooser_id"][indices]).size) if indices.size else 0
    support = {
        "rows": int(indices.size),
        "treated_rows": treated,
        "control_rows": control,
        "chooser_clusters": clusters,
    }
    if indices.size < 1_000 or treated == 0 or control == 0 or clusters < 100:
        return {
            "model": label,
            "status": "NOT_HDFE_ESTIMABLE_LOW_SUPPORT",
            "epistemic_label": epistemic_label,
            **support,
            "causal_claim": False,
        }
    try:
        return {
            "status": "HDFE_ESTIMATED",
            **_fit_contrast(
                data=data,
                sample=sample,
                exposure=exposure,
                label=label,
                epistemic_label=epistemic_label,
            ),
            "treated_rows": treated,
            "control_rows": control,
        }
    except (RuntimeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
        return {
            "model": label,
            "status": "HDFE_ATTEMPT_FAILED_RETAINED",
            "epistemic_label": epistemic_label,
            **support,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "causal_claim": False,
        }


def _fisher_exact_two_sided(
    *, treated_successes: int, treated_rows: int,
    control_successes: int, control_rows: int
) -> float | None:
    """Two-sided conditional Fisher p-value without a SciPy dependency."""
    total_rows = treated_rows + control_rows
    total_successes = treated_successes + control_successes
    if treated_rows <= 0 or control_rows <= 0 or total_rows <= 0:
        return None

    def log_choose(n: int, k: int) -> float:
        if k < 0 or k > n:
            return -math.inf
        return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)

    denominator = log_choose(total_rows, treated_rows)

    def log_probability(successes: int) -> float:
        return (
            log_choose(total_successes, successes)
            + log_choose(total_rows - total_successes, treated_rows - successes)
            - denominator
        )

    minimum = max(0, treated_rows - (total_rows - total_successes))
    maximum = min(treated_rows, total_successes)
    observed_log_probability = log_probability(treated_successes)
    probabilities = [
        math.exp(log_probability(successes))
        for successes in range(minimum, maximum + 1)
        if log_probability(successes) <= observed_log_probability + 1e-12
    ]
    return min(1.0, math.fsum(probabilities))


def _descriptive_two_arm(
    *, data: dict[str, Any], sample: Any, treated: Any, label: str
) -> dict[str, Any]:
    np = common.import_numpy()
    sample = np.asarray(sample, dtype=bool)
    treated = np.asarray(treated, dtype=bool)
    treated_mask = sample & treated
    control_mask = sample & ~treated
    n_treated = int(np.count_nonzero(treated_mask))
    n_control = int(np.count_nonzero(control_mask))
    y_treated = int(np.sum(data["kind"][treated_mask]))
    y_control = int(np.sum(data["kind"][control_mask]))
    rate_treated = y_treated / n_treated if n_treated else math.nan
    rate_control = y_control / n_control if n_control else math.nan
    difference = rate_treated - rate_control
    variance = (
        rate_treated * (1.0 - rate_treated) / n_treated
        + rate_control * (1.0 - rate_control) / n_control
    ) if n_treated and n_control else math.nan
    standard_error = math.sqrt(max(variance, 0.0)) if math.isfinite(variance) else math.nan
    z_value = difference / standard_error if standard_error > 0 else math.nan
    return {
        "model": label,
        "status": "DESCRIPTIVE_TWO_ARM_ESTIMATED",
        "epistemic_label": "X",
        "treated_rows": n_treated,
        "treated_kind_draws": y_treated,
        "treated_kind_rate_pct": 100.0 * rate_treated if math.isfinite(rate_treated) else None,
        "control_rows": n_control,
        "control_kind_draws": y_control,
        "control_kind_rate_pct": 100.0 * rate_control if math.isfinite(rate_control) else None,
        "difference_percentage_points": 100.0 * difference if math.isfinite(difference) else None,
        "naive_unclustered_standard_error_percentage_points": (
            100.0 * standard_error if math.isfinite(standard_error) else None
        ),
        "naive_unclustered_normal_p_value": common.normal_two_sided_p(z_value),
        "fisher_exact_two_sided_p_value": _fisher_exact_two_sided(
            treated_successes=y_treated,
            treated_rows=n_treated,
            control_successes=y_control,
            control_rows=n_control,
        ),
        "inference_warning": (
            "descriptive opportunity-level inference ignores repeated-chooser dependence; "
            "use the clustered HDFE attempt when estimable"
        ),
        "causal_claim": False,
    }


def estimate_c7(model_cache: Path, gate: dict[str, Any]) -> dict[str, Any]:
    np = common.import_numpy()
    data = _load_model(model_cache)
    epistemic_label = "S" if gate["gate_pass"] else "X"
    primary_category = data["primary_prior_category"]
    primary_sample = (primary_category == 1) | (primary_category == 0)
    primary = _attempt_fit_contrast(
        data=data,
        sample=primary_sample,
        exposure=(primary_category == 1).astype(float),
        label="C7_latest_reversed_arm_decision_primary",
        epistemic_label=epistemic_label,
    )
    unadjusted_primary = _descriptive_two_arm(
        data=data,
        sample=primary_sample,
        treated=primary_category == 1,
        label="C7_latest_reversed_arm_decision_unadjusted",
    )
    same = data["same_speed_prior_category"]
    same_sample = (same == 1) | (same == 0)
    sensitivities: list[dict[str, Any]] = [
        _attempt_fit_contrast(
            data=data,
            sample=same_sample,
            exposure=(same == 1).astype(float),
            label="C7_latest_reversed_arm_decision_same_speed",
            epistemic_label="X" if not gate["gate_pass"] else "S",
        )
    ]
    exclusive = data["any_prior_mercy"].astype(bool) ^ data["any_prior_claim"].astype(bool)
    sensitivities.append(
        _attempt_fit_contrast(
            data=data,
            sample=exclusive,
            exposure=data["any_prior_mercy"].astype(float),
            label="C7_any_prior_arm_decision_exclusive_histories",
            epistemic_label="X" if not gate["gate_pass"] else "S",
        )
    )
    descriptive: list[dict[str, Any]] = []
    labels = {
        0: "prior_claimer",
        1: "prior_benefactor",
        2: "prior_other_timeout",
        3: "prior_meeting_no_reversed_decision",
    }
    for code, label in labels.items():
        mask = primary_category == code
        descriptive.append(
            {
                "category": label,
                "opportunities": int(np.count_nonzero(mask)),
                "kind_draws": int(np.sum(data["kind"][mask])),
                "kind_rate_pct": 100.0 * float(np.mean(data["kind"][mask])) if np.any(mask) else None,
            }
        )
    return {
        "status": (
            "C7_ESTIMATED_SUPPORT_GATE_PASSED"
            if gate["gate_pass"]
            else "C7_ESTIMATED_EXPLORATORY_LOW_SUPPORT_GATE_FAILED"
        ),
        "epistemic_label": epistemic_label,
        "support_gate": gate,
        "primary": primary,
        "unadjusted_primary": unadjusted_primary,
        "sensitivities": sensitivities,
        "descriptive_categories": descriptive,
        "conflicting_history_opportunities": int(
            np.count_nonzero(data["conflicting_prior_arm_history"])
        ),
        "causal_claim": False,
        "scope_note": "bounds anonymity; does not reopen E1",
        "focal_kind_outcome_estimated": True,
        "low_support_warning": None if gate["gate_pass"] else (
            "Only 33 benefactor-facing opportunities were available; all C7 "
            "estimates are exploratory, fragile, and excluded from Holm family D"
        ),
    }


def execute(
    *, project: Path, state: Path, public_stage: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> dict[str, Any]:
    started = time.time()
    history_public = project / "output/dynamic_second_wave_history_v100/20260822T150914Z"
    if common.sha256_file(history_public / "_SUCCESS.json") != EXPECTED_HISTORY_SUCCESS_SHA256:
        raise RuntimeError("C7 history public authority mismatch")
    history_state = project / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    pair_event_receipt = common.load_json(history_state / "pair_events_receipt.json")
    if int(pair_event_receipt.get("rows", -1)) != common.EXPECTED_PAIR_EVENT_ROWS:
        raise RuntimeError("C7 pair-event row authority changed")
    pair_paths = _pair_paths(history_state / "pair_history_processed")
    _authenticate_pair_history(history_state, pair_paths)
    stage_paths = common.stage07_paths(
        project / "derived/replication/analysis_panel_24m_sf100k"
    )
    classification, classification_receipt = build_c7_classification_cache(
        pair_paths=pair_paths,
        stage07_paths=stage_paths,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    gate = freeze_c7_gate(
        classification_receipt=classification_receipt,
        state=state,
        config_sha256=config_sha256,
    )
    print(
        f"C7_TREATMENT_BLIND_GATE benefactor_opportunities={gate['benefactor_facing_fair_opportunities']:,} pass={gate['gate_pass']}",
        flush=True,
    )
    model_cache = build_c7_model_cache(
        classification=classification,
        stage07_paths=stage_paths,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    result = estimate_c7(model_cache, gate)
    public_stage.mkdir(parents=True, exist_ok=True)
    common.atomic_json(public_stage / "c7_support_gate.json", gate)
    common.atomic_json(public_stage / "c7_results.json", result)
    if result.get("descriptive_categories"):
        common.write_csv(
            public_stage / "c7_descriptive_categories.csv",
            result["descriptive_categories"],
        )
    model_rows = [result["primary"], *result.get("sensitivities", [])] if result.get("primary") else []
    if model_rows:
        common.write_csv(public_stage / "c7_models.csv", model_rows)
    summary = {
        "status": "CAMPAIGN1_C7_V101_OK",
        "created_utc": common.utc_now(),
        "runtime_seconds": time.time() - started,
        "gate_pass": gate["gate_pass"],
        "benefactor_facing_fair_opportunities": gate[
            "benefactor_facing_fair_opportunities"
        ],
        "result_status": result["status"],
        "primary": result.get("primary"),
        "unadjusted_primary": result.get("unadjusted_primary"),
        "focal_kind_outcome_estimated": result.get(
            "focal_kind_outcome_estimated", False
        ),
        "account_level_output": False,
        "api_requests": 0,
        "profile_or_patron_reads": 0,
    }
    common.atomic_json(public_stage / "summary.json", summary)
    return summary


def self_test() -> None:
    np = common.import_numpy()
    test_root = Path(os.environ.get("TMPDIR", "/tmp")) / f"c7_gate_test_{uuid.uuid4().hex}"
    gate = freeze_c7_gate(
        classification_receipt={"benefactor_facing_fair_opportunities": 1_000},
        state=test_root,
        config_sha256="synthetic",
    )
    if not gate["gate_pass"]:
        raise RuntimeError("C7 support boundary self-test failed")
    low_root = Path(os.environ.get("TMPDIR", "/tmp")) / f"c7_low_gate_test_{uuid.uuid4().hex}"
    low_gate = freeze_c7_gate(
        classification_receipt={"benefactor_facing_fair_opportunities": 33},
        state=low_root,
        config_sha256="synthetic-low",
    )
    if low_gate["gate_pass"] or low_gate["disposition"] != "ESTIMATE_EXPLORATORY_WITH_LOW_SUPPORT_WARNING":
        raise RuntimeError("C7 exhaustive low-support policy self-test failed")
    fisher = _fisher_exact_two_sided(
        treated_successes=1,
        treated_rows=10,
        control_successes=11,
        control_rows=14,
    )
    if fisher is None or not math.isclose(
        fisher, 0.0027594561852200836, rel_tol=0.0, abs_tol=1e-14
    ):
        raise RuntimeError(f"C7 Fisher exact self-test failed: {fisher}")
    synthetic = {
        "kind": np.array([1.0, 0.0, 1.0, 0.0]),
        "chooser_id": np.array([1, 2, 3, 4]),
    }
    descriptive = _descriptive_two_arm(
        data=synthetic,
        sample=np.ones(4, dtype=bool),
        treated=np.array([True, True, False, False]),
        label="synthetic",
    )
    if descriptive["treated_rows"] != 2 or descriptive["control_rows"] != 2:
        raise RuntimeError("C7 descriptive low-support self-test failed")
    attempt = _attempt_fit_contrast(
        data=synthetic,
        sample=np.ones(4, dtype=bool),
        exposure=np.array([1.0, 1.0, 0.0, 0.0]),
        label="synthetic",
        epistemic_label="X",
    )
    if attempt["status"] != "NOT_HDFE_ESTIMABLE_LOW_SUPPORT":
        raise RuntimeError("C7 retained failed-attempt self-test failed")
    shutil.rmtree(test_root, ignore_errors=True)
    shutil.rmtree(low_root, ignore_errors=True)
    print("CAMPAIGN1_C7_SELF_TEST_OK")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
