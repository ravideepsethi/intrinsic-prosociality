#!/usr/bin/env python3
"""C12 recipient pre-opportunity experience in the certified 2% user sample.

v1.0.2 reuses the fully authenticated v1.0.1 Parquet checkpoints.  It preserves
the v1.0.1 sample correction and adds a transparent numerical-recovery policy:
each HDFE fit is attempted under the original strict tolerance; absorption-only
nonconvergence receives one extended retry; any still-unestimable model is
retained as a model-attempt record while the remaining analyses continue.
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


SCRIPT_VERSION = "1.0.2"
EXPECTED_HISTORY_SUCCESS_SHA256 = (
    "62e4b8335b188f374f83bf1debedc19c62a91769f89a7c12368a628cb26d6de5"
)
USER_SEED = 2026082202
SAMPLE_DENOMINATOR = 50
IDENTIFIER_BUCKETS = 16
EXPECTED_V100_FOCAL_ROWS = 345_138
SAMPLED_BUCKET_STEP = math.gcd(SAMPLE_DENOMINATOR, IDENTIFIER_BUCKETS)
EXPECTED_SAMPLED_BUCKETS = tuple(
    range(0, IDENTIFIER_BUCKETS, SAMPLED_BUCKET_STEP)
)
STRICT_ABSORPTION_TOLERANCE = 1e-9
STRICT_ABSORPTION_ITERATIONS = 2_000
EXTENDED_ABSORPTION_TOLERANCE = 1e-7
EXTENDED_ABSORPTION_ITERATIONS = 25_000


def _user_paths(root: Path, bucket: int) -> list[Path]:
    paths = sorted((root / f"user_bucket={bucket}").glob("*.parquet"))
    if not paths:
        raise RuntimeError(f"C12 user-event bucket is missing: {bucket}")
    return paths


def _authenticate_directory(root: Path, receipt: Path, config_sha256: str) -> dict[str, Any] | None:
    if not root.exists() and not receipt.exists():
        return None
    if not root.is_dir() or not receipt.is_file():
        raise RuntimeError(f"Partial C12 directory checkpoint: {root}")
    saved = common.load_json(receipt)
    manifest = common.directory_manifest(root)
    expected = {
        "config_sha256": config_sha256,
        "file_manifest_sha256": common.sha256_json(manifest),
        "rows": sum(row["rows"] for row in manifest),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"C12 directory checkpoint mismatch: {root} {key}")
    return saved


def build_focal_base(
    *, stage07_paths: Sequence[Path], state: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, _ = common.import_dependencies()
    output = state / "c12_focal_base_private"
    receipt = state / "c12_focal_base_receipt.json"
    saved = _authenticate_directory(output, receipt, config_sha256)
    if saved:
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C12 focal-base checkpoint exists")
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c12_focal",
    )
    speed = common.speed_code_sql("s.api_speed")
    recipient_band = common.rating_band_sql("s.disconnected_elo")
    chooser_band = common.rating_band_sql("s.chooser_elo")
    eval_bin = common.eval_bin_sql("s.engine_eval_cp_disconnected")
    hour_week = common.hour_of_week_sql("s.api_last_move_at_ms")
    connection.execute(
        f"""
        COPY (
          SELECT
            CAST(hash(CAST(s.disconnected_user_id AS BIGINT), {USER_SEED})
              % {IDENTIFIER_BUCKETS} AS INTEGER) AS recipient_bucket,
            CAST(s.game_id AS VARCHAR) AS game_id,
            CAST(s.archive_ordinal AS BIGINT) AS archive_ordinal,
            CAST(s.utc_ms AS BIGINT) AS game_utc_ms,
            CAST(s.api_last_move_at_ms AS BIGINT) AS decision_utc_ms,
            CAST(s.chooser_user_id AS BIGINT) AS chooser_id,
            CAST(s.disconnected_user_id AS BIGINT) AS recipient_id,
            CAST({speed} AS INTEGER) AS speed_code,
            CAST({recipient_band} AS INTEGER) AS recipient_rating_band,
            CAST({chooser_band} AS INTEGER) AS chooser_rating_band,
            CAST({eval_bin} AS INTEGER) AS eval_bin,
            CAST(date_diff('month', DATE '2023-11-01',
              strptime(s.month || '-01', '%Y-%m-%d')) AS INTEGER) AS month_code,
            CAST({hour_week} AS INTEGER) AS hour_of_week,
            CAST(s.chooser_draw_payoff_v2 AS DOUBLE) AS draw_payoff,
            CAST(s.chooser_win_premium_v2 AS DOUBLE) AS win_premium,
            CAST(s.chooser_clock_last_obs_s AS DOUBLE) AS chooser_clock,
            CAST(s.disconnected_clock_last_obs_s AS DOUBLE) AS opponent_clock,
            CAST(s.chooser_elo AS DOUBLE) AS chooser_elo,
            CAST(s.disconnected_elo AS DOUBLE) AS opponent_elo,
            CAST(s.chooser_pre_rd_v2 AS DOUBLE) AS chooser_rd,
            CAST(s.disconnected_pre_rd_v2 AS DOUBLE) AS opponent_rd,
            CAST(s.tournament_like_event AS BOOLEAN) AS tournament,
            CAST(hash(CAST(s.game_id AS VARCHAR)) % 9223372036854775807 AS BIGINT)
              AS row_hash
          FROM read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true) s
          WHERE CAST(s.fair_competitive AS BOOLEAN)
            AND s.chooser_user_id IS NOT NULL
            AND s.disconnected_user_id IS NOT NULL
            AND hash(CAST(s.disconnected_user_id AS BIGINT), {USER_SEED})
                  % {SAMPLE_DENOMINATOR} = 0
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000,
           PARTITION_BY (recipient_bucket), OVERWRITE_OR_IGNORE)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
               COUNT(*) FILTER (WHERE speed_code NOT BETWEEN 0 AND 5),
               COUNT(*) FILTER (WHERE recipient_rating_band NOT BETWEEN 0 AND 3),
               COUNT(DISTINCT recipient_bucket),
               COUNT(*) FILTER (WHERE recipient_bucket % 2 <> 0),
               MIN(recipient_bucket), MAX(recipient_bucket)
        FROM read_parquet({common.sql_literal(str(temporary / '**/*.parquet'))},
                          hive_partitioning=true)
        """
    ).fetchone()
    connection.close()
    if (
        qa[0] != EXPECTED_V100_FOCAL_ROWS
        or qa[0] != qa[1]
        or qa[2]
        or qa[3]
        or qa[4] != len(EXPECTED_SAMPLED_BUCKETS)
        or qa[5]
        or qa[6] != EXPECTED_SAMPLED_BUCKETS[0]
        or qa[7] != EXPECTED_SAMPLED_BUCKETS[-1]
    ):
        raise RuntimeError(f"C12 focal-base row conservation failed: {qa}")
    os.replace(temporary, output)
    manifest = common.directory_manifest(output)
    saved = {
        "status": "C12_RECIPIENT_SAMPLE_FOCAL_BASE_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "sample_rule": f"hash(disconnected_user_id,{USER_SEED}) % {SAMPLE_DENOMINATOR} = 0",
        "partition_rule": (
            f"hash(disconnected_user_id,{USER_SEED}) % {IDENTIFIER_BUCKETS}"
        ),
        "expected_sampled_partition_buckets": list(EXPECTED_SAMPLED_BUCKETS),
        "technical_correction": (
            "v1.0.1 recognizes the deterministic modulo alias between the "
            "1-in-50 sample and 16 storage buckets; sample membership is unchanged"
        ),
        "rows": sum(row["rows"] for row in manifest),
        "v100_focal_rows_exactly_reproduced": True,
        "files": len(manifest),
        "file_manifest_sha256": common.sha256_json(manifest),
        "focal_kind_outcome_read": False,
        "privacy": "PRIVATE ROW-LEVEL FOCAL BASE; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c12_focal", ignore_errors=True)
    return output, saved


def build_experience_parts(
    *, focal_root: Path, user_root: Path, state: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> list[Path]:
    duckdb, _, _, pq = common.import_dependencies()
    part_root = state / "c12_experience_parts"
    receipt_root = state / "c12_experience_part_receipts"
    part_root.mkdir(parents=True, exist_ok=True)
    receipt_root.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for bucket in EXPECTED_SAMPLED_BUCKETS:
        output = part_root / f"bucket_{bucket:02d}.parquet"
        receipt = receipt_root / f"bucket_{bucket:02d}.json"
        focal_paths = sorted((focal_root / f"recipient_bucket={bucket}").glob("*.parquet"))
        if not focal_paths:
            raise RuntimeError(f"C12 focal partition is missing: {bucket}")
        if output.is_file() and receipt.is_file():
            saved = common.load_json(receipt)
            if (
                saved.get("config_sha256") != config_sha256
                or saved.get("output_sha256") != common.sha256_file(output)
                or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
            ):
                raise RuntimeError(f"C12 experience checkpoint mismatch: {bucket}")
            outputs.append(output)
            continue
        if output.exists() or receipt.exists():
            raise RuntimeError(f"Partial C12 experience checkpoint: {bucket}")
        temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
        connection = duckdb.connect()
        common.configure_duckdb(
            connection,
            threads=max(1, min(threads, 4)),
            memory_limit=memory_limit,
            temp_directory=state / f"duckdb_temp/c12_history_{bucket:02d}",
        )
        connection.execute(
            f"""
            COPY (
              WITH history AS (
                SELECT
                  CAST(user_id AS BIGINT) AS user_id,
                  CAST(game_id AS VARCHAR) AS game_id,
                  ROW_NUMBER() OVER (
                    PARTITION BY user_id
                    ORDER BY utc_ms, archive_ordinal, game_id, color_order
                  )::BIGINT - 1 AS prior_all_games,
                  ROW_NUMBER() OVER (
                    PARTITION BY user_id, speed
                    ORDER BY utc_ms, archive_ordinal, game_id, color_order
                  )::BIGINT - 1 AS prior_same_speed_games
                FROM read_parquet(
                  {common.path_list_literal(_user_paths(user_root, bucket))},
                  union_by_name=true
                )
              )
              SELECT f.*, h.prior_all_games, h.prior_same_speed_games
              FROM read_parquet({common.path_list_literal(focal_paths)},
                                union_by_name=true) f
              INNER JOIN history h
                ON h.user_id = CAST(f.recipient_id AS BIGINT)
               AND h.game_id = CAST(f.game_id AS VARCHAR)
              ORDER BY f.game_id
            ) TO {common.sql_literal(temporary)}
              (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
            """
        )
        qa = connection.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT game_id),
                   MIN(prior_all_games), MIN(prior_same_speed_games)
            FROM read_parquet({common.sql_literal(temporary)})
            """
        ).fetchone()
        focal_rows = connection.execute(
            f"SELECT COUNT(*) FROM read_parquet({common.path_list_literal(focal_paths)}, union_by_name=true)"
        ).fetchone()[0]
        connection.close()
        if qa[0] != focal_rows or qa[0] != qa[1] or qa[2] < 0 or qa[3] < 0:
            raise RuntimeError(
                f"C12 history join failed for bucket {bucket}: joined={qa} focal={focal_rows}"
            )
        os.replace(temporary, output)
        common.atomic_json(
            receipt,
            {
                "status": "C12_RECIPIENT_EXPERIENCE_BUCKET_PRIVATE_OK",
                "created_utc": common.utc_now(),
                "config_sha256": config_sha256,
                "bucket": bucket,
                "rows": int(qa[0]),
                "output_sha256": common.sha256_file(output),
                "focal_kind_outcome_read": False,
            },
        )
        shutil.rmtree(state / f"duckdb_temp/c12_history_{bucket:02d}", ignore_errors=True)
        outputs.append(output)
        print(f"C12_EXPERIENCE_BUCKET_OK bucket={bucket:02d} rows={qa[0]:,}", flush=True)
    return outputs


def build_decile_cache(
    *, parts: Sequence[Path], expected_rows: int, state: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c12_experience_deciles_private.parquet"
    receipt = state / "c12_experience_deciles_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = common.load_json(receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
            or saved.get("rows") != expected_rows
        ):
            raise RuntimeError("C12 decile checkpoint mismatch")
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C12 decile checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c12_deciles",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT *,
            NTILE(10) OVER (
              PARTITION BY recipient_rating_band, speed_code
              ORDER BY prior_all_games, row_hash, game_id
            )::TINYINT AS experience_decile,
            NTILE(10) OVER (
              PARTITION BY recipient_rating_band, speed_code
              ORDER BY prior_same_speed_games, row_hash, game_id
            )::TINYINT AS same_speed_experience_decile
          FROM read_parquet({common.path_list_literal(parts)}, union_by_name=true)
          ORDER BY game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(DISTINCT game_id),
               MIN(experience_decile), MAX(experience_decile),
               MIN(same_speed_experience_decile), MAX(same_speed_experience_decile)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    support_rows = connection.execute(
        f"""
        SELECT recipient_rating_band, speed_code, experience_decile,
               COUNT(*) AS opportunities,
               COUNT(DISTINCT recipient_id) AS recipients
        FROM read_parquet({common.sql_literal(temporary)})
        GROUP BY ALL ORDER BY 1,2,3
        """
    ).fetchall()
    connection.close()
    if qa[0] != expected_rows or qa[0] != qa[1] or tuple(qa[2:]) != (1, 10, 1, 10):
        raise RuntimeError(f"C12 decile row conservation failed: {qa}")
    os.replace(temporary, output)
    support = [
        {
            "recipient_rating_band": int(row[0]),
            "speed_code": int(row[1]),
            "experience_decile": int(row[2]),
            "opportunities": int(row[3]),
            "recipients": int(row[4]),
        }
        for row in support_rows
    ]
    saved = {
        "status": "C12_EXPERIENCE_DECILES_FROZEN_BEFORE_FOCAL_OUTCOME",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "rows": int(qa[0]),
        "output_sha256": common.sha256_file(output),
        "support": support,
        "focal_kind_outcome_read": False,
        "tie_break": "prior count, then focal game hash and game ID",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c12_deciles", ignore_errors=True)
    return output, saved


def build_model_cache(
    *, deciles: Path, stage07_paths: Sequence[Path], expected_rows: int,
    state: Path, threads: int, memory_limit: str, config_sha256: str
) -> Path:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c12_model_private.parquet"
    receipt = state / "c12_model_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = common.load_json(receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
            or saved.get("rows") != expected_rows
        ):
            raise RuntimeError("C12 model checkpoint mismatch")
        return output
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C12 model checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c12_model",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          SELECT d.*, CAST(s.outcome_kind_draw AS DOUBLE) AS kind
          FROM read_parquet({common.sql_literal(deciles)}) d
          INNER JOIN read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true) s
            ON CAST(s.game_id AS VARCHAR) = d.game_id
          ORDER BY d.game_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"SELECT COUNT(*), COUNT(DISTINCT game_id), COUNT(*) FILTER (WHERE kind IS NULL) FROM read_parquet({common.sql_literal(temporary)})"
    ).fetchone()
    connection.close()
    if qa[0] != expected_rows or qa[0] != qa[1] or qa[2]:
        raise RuntimeError(f"C12 focal outcome join failed: {qa}")
    os.replace(temporary, output)
    common.atomic_json(
        receipt,
        {
            "status": "C12_MODEL_PRIVATE_OK",
            "created_utc": common.utc_now(),
            "config_sha256": config_sha256,
            "rows": int(qa[0]),
            "output_sha256": common.sha256_file(output),
            "privacy": "PRIVATE ROW-LEVEL MODEL CACHE; DO NOT PUBLISH",
        },
    )
    shutil.rmtree(state / "duckdb_temp/c12_model", ignore_errors=True)
    return output


def _load_model(path: Path) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    table = pq.read_table(path)
    nullable = {
        "draw_payoff", "win_premium", "chooser_clock", "opponent_clock",
        "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
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
            "chooser_elo", "opponent_elo", "chooser_rd", "opponent_rd",
        )
    }


def _fixed_effects(data: dict[str, Any], indices: Any) -> dict[str, Any]:
    return {
        "chooser": data["chooser_id"][indices],
        "recipient_band_x_speed": (
            data["recipient_rating_band"][indices] * 10 + data["speed_code"][indices]
        ),
        "eval_bin": data["eval_bin"][indices],
        "month": data["month_code"][indices],
        "hour_of_week": data["hour_of_week"][indices],
        "tournament": data["tournament"][indices],
    }


def _fit(
    *, data: dict[str, Any], sample: Any, exposures: dict[str, Any], label: str,
    epistemic_label: str, analysis_role: str, absorption_tolerance: float,
    absorption_maximum_iterations: int,
) -> dict[str, Any]:
    np = common.import_numpy()
    indices = np.flatnonzero(sample)
    fitted = common.fit_hdfe_cluster(
        outcome=data["kind"][indices],
        exposures={name: values[indices] for name, values in exposures.items()},
        numeric_controls=_controls(data, indices),
        fixed_effects=_fixed_effects(data, indices),
        clusters=data["chooser_id"][indices],
        row_ids=data["row_hash"][indices],
        specification={
            "model": label,
            "epistemic_label": epistemic_label,
            "analysis_role": analysis_role,
            "fixed_effects": "chooser + recipient-rating-band-by-speed + current-state/calendar",
            "cluster": "chooser",
            "causal_claim": False,
        },
        absorption_tolerance=absorption_tolerance,
        absorption_maximum_iterations=absorption_maximum_iterations,
    )
    return fitted


def _retainable_model_failure(error: BaseException) -> bool:
    if common.is_hdfe_absorption_nonconvergence(error):
        return True
    if isinstance(error, RuntimeError):
        return str(error).startswith(
            (
                "Exposure has no residual variation:",
                "Rank-deficient HDFE model:",
                "Too few clusters for inference:",
                "Model contains no regressors",
            )
        ) or "fewer than 1,000 rows" in str(error)
    return type(error).__name__ == "LinAlgError"


def _attempt_model(
    *, data: dict[str, Any], sample: Any, exposures: dict[str, Any], label: str,
    epistemic_label: str, analysis_role: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the frozen fit, retry absorption once, and retain numerical failures."""
    np = common.import_numpy()
    requested_rows = int(np.count_nonzero(sample))
    requested_clusters = int(np.unique(data["chooser_id"][sample]).size)
    attempt: dict[str, Any] = {
        "model": label,
        "epistemic_label": epistemic_label,
        "analysis_role": analysis_role,
        "requested_rows": requested_rows,
        "requested_chooser_clusters": requested_clusters,
        "strict_absorption_tolerance": STRICT_ABSORPTION_TOLERANCE,
        "strict_absorption_maximum_iterations": STRICT_ABSORPTION_ITERATIONS,
        "extended_absorption_tolerance": EXTENDED_ABSORPTION_TOLERANCE,
        "extended_absorption_maximum_iterations": EXTENDED_ABSORPTION_ITERATIONS,
        "strict_error": None,
        "extended_error": None,
    }
    print(
        f"C12_MODEL_STRICT_BEGIN model={label} rows={requested_rows:,} "
        f"clusters={requested_clusters:,}",
        flush=True,
    )
    try:
        fitted = _fit(
            data=data,
            sample=sample,
            exposures=exposures,
            label=label,
            epistemic_label=epistemic_label,
            analysis_role=analysis_role,
            absorption_tolerance=STRICT_ABSORPTION_TOLERANCE,
            absorption_maximum_iterations=STRICT_ABSORPTION_ITERATIONS,
        )
        attempt.update(
            {
                "strict_status": "ESTIMATED",
                "extended_status": "NOT_NEEDED",
                "final_status": "ESTIMATED_STRICT",
                "numerical_estimate_emitted": True,
            }
        )
        print(f"C12_MODEL_STRICT_OK model={label}", flush=True)
        return _flatten(fitted), attempt
    except BaseException as strict_error:
        if not _retainable_model_failure(strict_error):
            raise
        attempt["strict_status"] = "FAILED_RETAINED"
        attempt["strict_error"] = f"{type(strict_error).__name__}: {strict_error}"
        if not common.is_hdfe_absorption_nonconvergence(strict_error):
            attempt.update(
                {
                    "extended_status": "NOT_APPLICABLE",
                    "final_status": "UNESTIMABLE_RETAINED",
                    "numerical_estimate_emitted": False,
                }
            )
            print(
                f"C12_MODEL_UNESTIMABLE_RETAINED model={label} "
                f"error={type(strict_error).__name__}: {strict_error}",
                flush=True,
            )
            return [], attempt
    print(f"C12_MODEL_EXTENDED_RETRY_BEGIN model={label}", flush=True)
    try:
        fitted = _fit(
            data=data,
            sample=sample,
            exposures=exposures,
            label=label,
            epistemic_label=epistemic_label,
            analysis_role=analysis_role,
            absorption_tolerance=EXTENDED_ABSORPTION_TOLERANCE,
            absorption_maximum_iterations=EXTENDED_ABSORPTION_ITERATIONS,
        )
        attempt.update(
            {
                "extended_status": "ESTIMATED",
                "final_status": "ESTIMATED_EXTENDED_ABSORPTION",
                "numerical_estimate_emitted": True,
            }
        )
        print(f"C12_MODEL_EXTENDED_RETRY_OK model={label}", flush=True)
        return _flatten(fitted), attempt
    except BaseException as extended_error:
        if not _retainable_model_failure(extended_error):
            raise
        attempt.update(
            {
                "extended_status": "FAILED_RETAINED",
                "extended_error": f"{type(extended_error).__name__}: {extended_error}",
                "final_status": "UNESTIMABLE_AFTER_EXTENDED_RETRY_RETAINED",
                "numerical_estimate_emitted": False,
            }
        )
        print(
            f"C12_MODEL_EXTENDED_FAILURE_RETAINED model={label} "
            f"error={type(extended_error).__name__}: {extended_error}",
            flush=True,
        )
        return [], attempt


def _flatten(fitted: dict[str, Any]) -> list[dict[str, Any]]:
    shared = {key: value for key, value in fitted.items() if key != "results"}
    return [
        {
            **shared,
            **result,
            "effect_percentage_points": 100.0 * result["coefficient"],
            "standard_error_percentage_points": 100.0 * result["standard_error"],
        }
        for result in fitted["results"]
    ]


def estimate(model_cache: Path) -> dict[str, Any]:
    np = common.import_numpy()
    data = _load_model(model_cache)
    all_rows = np.ones(data["kind"].size, dtype=bool)
    decile = data["experience_decile"]
    extremes = (decile <= 2) | (decile >= 9)
    low = (decile <= 2).astype(float)
    models: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []

    def add_model(
        *, sample: Any, exposures: dict[str, Any], label: str,
        epistemic_label: str, analysis_role: str,
    ) -> None:
        rows, attempt = _attempt_model(
            data=data,
            sample=sample,
            exposures=exposures,
            label=label,
            epistemic_label=epistemic_label,
            analysis_role=analysis_role,
        )
        models.extend(rows)
        attempts.append(attempt)

    add_model(
        sample=extremes,
        exposures={"low_deciles_1_2_minus_high_deciles_9_10": low},
        label="C12_primary_recipient_experience_extremes",
        epistemic_label="S",
        analysis_role="primary",
    )
    full_exposures = {
        f"experience_decile_{value}_vs_1": (decile == value).astype(float)
        for value in range(2, 11)
    }
    add_model(
        sample=all_rows,
        exposures=full_exposures,
        label="C12_full_recipient_experience_decile_profile",
        epistemic_label="S",
        analysis_role="planned_sensitivity",
    )
    add_model(
        sample=all_rows,
        exposures={"log1p_prior_all_rated_games": np.log1p(data["prior_all_games"])},
        label="C12_continuous_prior_all_rated_games",
        epistemic_label="S",
        analysis_role="planned_sensitivity",
    )
    same_decile = data["same_speed_experience_decile"]
    same_extremes = (same_decile <= 2) | (same_decile >= 9)
    add_model(
        sample=same_extremes,
        exposures={
            "low_same_speed_deciles_1_2_minus_high_9_10":
                (same_decile <= 2).astype(float)
        },
        label="C12_same_speed_recipient_experience_extremes",
        epistemic_label="S",
        analysis_role="planned_sensitivity",
    )
    add_model(
        sample=all_rows,
        exposures={
            "log1p_prior_same_speed_games": np.log1p(data["prior_same_speed_games"])
        },
        label="C12_continuous_prior_same_speed_games",
        epistemic_label="S",
        analysis_role="planned_sensitivity",
    )
    for band in range(4):
        sample = extremes & (data["chooser_rating_band"] == band)
        if np.count_nonzero(sample) >= 1_000 and np.unique(data["chooser_id"][sample]).size >= 100:
            add_model(
                sample=sample,
                exposures={"low_deciles_1_2_minus_high_deciles_9_10": low},
                label=f"C12_primary_by_chooser_rating_band_{band}",
                epistemic_label="X",
                analysis_role="exploratory_heterogeneity",
            )
    descriptive: list[dict[str, Any]] = []
    for value in range(1, 11):
        mask = decile == value
        descriptive.append(
            {
                "experience_decile": value,
                "opportunities": int(np.count_nonzero(mask)),
                "recipients": int(np.unique(data["recipient_id"][mask]).size),
                "kind_draws": int(np.sum(data["kind"][mask])),
                "kind_rate_pct": 100.0 * float(np.mean(data["kind"][mask])),
                "prior_games_mean": float(np.mean(data["prior_all_games"][mask])),
                "prior_games_median": float(np.median(data["prior_all_games"][mask])),
            }
        )
    primary = next(
        (
            row for row in models
            if row.get("model") == "C12_primary_recipient_experience_extremes"
            and row.get("term") == "low_deciles_1_2_minus_high_deciles_9_10"
        ),
        None,
    )
    failed_attempts = [
        row for row in attempts if row["numerical_estimate_emitted"] is not True
    ]
    extended_successes = [
        row for row in attempts
        if row["final_status"] == "ESTIMATED_EXTENDED_ABSORPTION"
    ]
    status = (
        "C12_RECIPIENT_EXPERIENCE_ESTIMATION_COMPLETE"
        if not failed_attempts
        else "C12_RECIPIENT_EXPERIENCE_COMPLETED_WITH_RETAINED_MODEL_FAILURES"
    )
    return {
        "status": status,
        "epistemic_label": "S",
        "sample_fraction": 1.0 / SAMPLE_DENOMINATOR,
        "sample_seed": USER_SEED,
        "models": models,
        "model_attempts": attempts,
        "model_attempts_total": len(attempts),
        "models_estimated": sum(bool(row["numerical_estimate_emitted"]) for row in attempts),
        "extended_absorption_successes": len(extended_successes),
        "retained_model_failures": len(failed_attempts),
        "primary": primary,
        "primary_estimable": primary is not None,
        "descriptive_deciles": descriptive,
        "causal_claim": False,
        "interpretive_limit": "recipient-selection/targeting association; not a causal experience effect",
    }


def execute(
    *, project: Path, state: Path, public_stage: Path, threads: int,
    memory_limit: str, config_sha256: str
) -> dict[str, Any]:
    started = time.time()
    history_public = project / "output/dynamic_second_wave_history_v100/20260822T150914Z"
    if common.sha256_file(history_public / "_SUCCESS.json") != EXPECTED_HISTORY_SUCCESS_SHA256:
        raise RuntimeError("C12 history public authority mismatch")
    history_state = project / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
    user_receipt = common.load_json(history_state / "user_events_receipt.json")
    if int(user_receipt.get("rows", -1)) != common.EXPECTED_USER_EVENT_ROWS:
        raise RuntimeError("C12 user-event row authority changed")
    user_root = history_state / "user_events"
    user_manifest = common.directory_manifest(user_root)
    actual_user_rows = sum(int(row["rows"]) for row in user_manifest)
    if actual_user_rows != common.EXPECTED_USER_EVENT_ROWS:
        raise RuntimeError(f"C12 physical user-event rows changed: {actual_user_rows}")
    if user_receipt.get("file_manifest_sha256") != common.sha256_json(user_manifest):
        raise RuntimeError("C12 physical user-event manifest changed")
    stage_paths = common.stage07_paths(
        project / "derived/replication/analysis_panel_24m_sf100k"
    )
    focal_root, focal_receipt = build_focal_base(
        stage07_paths=stage_paths,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    print(
        f"C12_V100_FOCAL_ROWS_EXACT_REPRODUCTION_OK "
        f"rows={int(focal_receipt['rows']):,} "
        f"buckets={list(EXPECTED_SAMPLED_BUCKETS)}",
        flush=True,
    )
    parts = build_experience_parts(
        focal_root=focal_root,
        user_root=user_root,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    deciles, support = build_decile_cache(
        parts=parts,
        expected_rows=int(focal_receipt["rows"]),
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    print(f"C12_OUTCOME_BLIND_SUPPORT_FROZEN rows={support['rows']:,}", flush=True)
    model = build_model_cache(
        deciles=deciles,
        stage07_paths=stage_paths,
        expected_rows=int(focal_receipt["rows"]),
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    result = estimate(model)
    public_stage.mkdir(parents=True, exist_ok=True)
    public_support = {key: value for key, value in support.items() if key != "output_sha256"}
    common.atomic_json(public_stage / "c12_support_frozen.json", public_support)
    common.atomic_json(public_stage / "c12_results.json", result)
    common.write_csv(public_stage / "c12_support_by_cell_decile.csv", support["support"])
    common.write_csv(public_stage / "c12_models.csv", result["models"])
    common.write_csv(public_stage / "c12_model_attempts.csv", result["model_attempts"])
    common.write_csv(public_stage / "c12_descriptive_deciles.csv", result["descriptive_deciles"])
    summary = {
        "status": "CAMPAIGN1_C12_V102_COMPLETE",
        "result_status": result["status"],
        "created_utc": common.utc_now(),
        "runtime_seconds": time.time() - started,
        "rows": int(focal_receipt["rows"]),
        "sample_membership_changed_by_v101": False,
        "v101_private_parquet_checkpoints_reused": True,
        "sampled_partition_buckets": list(EXPECTED_SAMPLED_BUCKETS),
        "primary": result["primary"],
        "primary_estimable": result["primary_estimable"],
        "model_attempts_total": result["model_attempts_total"],
        "models_estimated": result["models_estimated"],
        "extended_absorption_successes": result["extended_absorption_successes"],
        "retained_model_failures": result["retained_model_failures"],
        "account_level_output": False,
        "api_requests": 0,
        "profile_or_patron_reads": 0,
    }
    common.atomic_json(public_stage / "summary.json", summary)
    return summary


def self_test() -> None:
    np = common.import_numpy()
    deciles = np.arange(1, 11)
    extremes = (deciles <= 2) | (deciles >= 9)
    low = deciles <= 2
    if np.flatnonzero(extremes).tolist() != [0, 1, 8, 9] or int(np.sum(low)) != 2:
        raise RuntimeError("C12 decile contrast self-test failed")
    if not math.isclose(1.0 / SAMPLE_DENOMINATOR, 0.02):
        raise RuntimeError("C12 sample fraction self-test failed")
    if EXPECTED_V100_FOCAL_ROWS != 345_138:
        raise RuntimeError("C12 v1.0.0 focal-row authority self-test failed")
    reachable = tuple(
        sorted(
            {
                (SAMPLE_DENOMINATOR * multiplier) % IDENTIFIER_BUCKETS
                for multiplier in range(IDENTIFIER_BUCKETS)
            }
        )
    )
    if reachable != EXPECTED_SAMPLED_BUCKETS or reachable != tuple(range(0, 16, 2)):
        raise RuntimeError("C12 modulo-alias partition regression test failed")
    original_fit = globals()["_fit"]
    calls: list[dict[str, Any]] = []

    def retry_stub(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError(
                "HDFE absorption did not converge: iterations=2000 "
                "tolerance=1.000e-09 last_adjustment=6.411e-06"
            )
        return {
            "model": kwargs["label"],
            "epistemic_label": kwargs["epistemic_label"],
            "results": [
                {
                    "term": "x",
                    "coefficient": 0.01,
                    "standard_error": 0.005,
                }
            ],
        }

    globals()["_fit"] = retry_stub
    try:
        recovered, attempt = _attempt_model(
            data={"chooser_id": np.arange(8)},
            sample=np.ones(8, dtype=bool),
            exposures={"x": np.arange(8, dtype=float)},
            label="C12_retry_policy_self_test",
            epistemic_label="X",
            analysis_role="self_test",
        )
    finally:
        globals()["_fit"] = original_fit
    if (
        len(calls) != 2
        or len(recovered) != 1
        or attempt["final_status"] != "ESTIMATED_EXTENDED_ABSORPTION"
        or calls[1]["absorption_tolerance"] != EXTENDED_ABSORPTION_TOLERANCE
    ):
        raise RuntimeError("C12 extended-absorption retry self-test failed")
    print("CAMPAIGN1_C12_SELF_TEST_OK")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
