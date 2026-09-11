#!/usr/bin/env python3
"""Complete the remaining A1/A2 dynamic analyses from authenticated private inputs.

The producer is intentionally narrow. It reads the certified Stage-07 opportunity
panel and the certified private recipient panel, creates one compressed account-window
cache, and emits disclosure-safe aggregates. It never reads Patron/profile data and it
never changes an existing primary or multiple-testing family.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Iterable, Sequence
import uuid


SCRIPT_VERSION = "1.0.0"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
CORE_RUN_ID = "20260822T022146Z"
EXPECTED_BASE_CODE_SHA256 = (
    "2dcf0dd19f7cfe8f694d348e6590df88083a37882404112229d6ef05ebc42713"
)
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_CORE_SUCCESS_SHA256 = (
    "bd64005162bf8f37f9488d47e95c2ea4dd946d1227e909930a42dd8e4904f009"
)
EXPECTED_PRIVATE_RECIPIENT_SHA256 = (
    "41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d"
)
EXPECTED_RECIPIENT_ROWS = 2_556_782
EXPECTED_STAGE07_ROWS = 47_587_020
DAY_MS = 86_400_000
WINDOW_HORIZONS_DAYS = (30, 60, 90)
MINIMUM_CHOICES = (1, 4)

# The symmetric A2 window is restricted to dates fully observed in Stage 07.
PANEL_START_MS = 1_698_796_800_000  # 2023-11-01T00:00:00Z
PANEL_END_EXCLUSIVE_MS = 1_761_955_200_000  # 2025-11-01T00:00:00Z


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--base-code", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--verify-stage07-hashes", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def utc_run_id() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def utc_now() -> str:
    import datetime as dt

    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: Sequence[dict[str, Any]], delimiter: str = ",") -> None:
    if not rows:
        raise RuntimeError(f"Refusing to write an empty aggregate table: {path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for field in row:
            if field not in seen:
                fields.append(field)
                seen.add(field)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter=delimiter)
        writer.writeheader()
        for row in rows:
            encoded = {
                key: canonical_json(value) if isinstance(value, (dict, list, tuple)) else value
                for key, value in row.items()
            }
            writer.writerow(encoded)
    os.replace(temporary, path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path) -> Any:
    specification = importlib.util.spec_from_file_location("dynamic_core_authority", path)
    if specification is None or specification.loader is None:
        raise RuntimeError(f"Cannot import authenticated core code: {path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def sql_literal(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def path_list_literal(paths: Iterable[Path]) -> str:
    return "[" + ",".join(sql_literal(path) for path in paths) + "]"


def directory_manifest(root: Path, excluded: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = excluded or set()
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in excluded:
            continue
        rows.append(
            {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "path": str(path.relative_to(root)),
            }
        )
    return rows


def import_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import duckdb  # type: ignore
        import numpy as np  # type: ignore
        import pyarrow as pa  # type: ignore
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("duckdb, numpy, and pyarrow are required") from exc
    return duckdb, np, pa, pq


def configure_duckdb(connection: Any, *, threads: int, memory: str, temp: Path) -> None:
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute(f"PRAGMA threads={int(threads)}")
    connection.execute(f"PRAGMA memory_limit={sql_literal(memory)}")
    connection.execute(f"PRAGMA temp_directory={sql_literal(temp)}")
    connection.execute("PRAGMA preserve_insertion_order=false")


def make_payload(args: argparse.Namespace, script_path: Path) -> dict[str, Any]:
    if not 1 <= args.threads <= 16:
        raise RuntimeError("--threads must be between 1 and 16")
    project = args.project_root.expanduser().resolve()
    if project != PROJECT_AUTHORITY or not project.is_dir():
        raise RuntimeError(f"XT_Pro project authority is unavailable: {project}")
    repo = project / "replication_package"
    base_code = (
        args.base_code.expanduser().resolve()
        if args.base_code
        else repo / "code/10c_estimate_dynamic_prosociality_core.py"
    )
    stage07 = project / "derived/replication/analysis_panel_24m_sf100k"
    core_root = project / "output/dynamic_prosociality_core_v102" / CORE_RUN_ID
    core_state = project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
    recipient = core_state / "recipient_with_chronology_private.parquet"
    state = project / "derived/replication/remaining_dynamic_completion_v100_PRIVATE"
    output_base = project / "output/remaining_dynamic_completion_v100"
    run_id = args.run_id or utc_run_id()
    authorities = {
        "script_sha256": sha256_file(script_path),
        "base_code_sha256": sha256_file(base_code),
        "stage07_success_sha256": sha256_file(stage07 / "_SUCCESS.json"),
        "core_success_sha256": sha256_file(core_root / "_SUCCESS.json"),
        "private_recipient_sha256": sha256_file(recipient),
    }
    expected = {
        "base_code_sha256": EXPECTED_BASE_CODE_SHA256,
        "stage07_success_sha256": EXPECTED_STAGE07_SUCCESS_SHA256,
        "core_success_sha256": EXPECTED_CORE_SUCCESS_SHA256,
        "private_recipient_sha256": EXPECTED_PRIVATE_RECIPIENT_SHA256,
    }
    for key, wanted in expected.items():
        if authorities[key] != wanted:
            raise RuntimeError(f"Input authority mismatch: {key}")
    core_success = load_json(core_root / "_SUCCESS.json")
    if core_success.get("status") != "DYNAMIC_PROSOCIALITY_CORE_V102_OK":
        raise RuntimeError("Certified dynamic-core status changed")
    if core_success.get("recipient_private_input_sha256") != EXPECTED_PRIVATE_RECIPIENT_SHA256:
        raise RuntimeError("Dynamic-core receipt no longer names the private recipient authority")
    config = {
        "script_version": SCRIPT_VERSION,
        **authorities,
        "panel_start_ms": PANEL_START_MS,
        "panel_end_exclusive_ms": PANEL_END_EXCLUSIVE_MS,
        "horizons_days": list(WINDOW_HORIZONS_DAYS),
        "minimum_choices": list(MINIMUM_CHOICES),
        "a2_scope": "symmetric fair-chooser windows around first qualifying disconnection",
        "a1_scope": "censor first subsequent choice at next qualifying disconnection",
    }
    return {
        "project": project,
        "repo": repo,
        "base_code": base_code,
        "stage07": stage07,
        "core_root": core_root,
        "core_state": core_state,
        "recipient": recipient,
        "state": state,
        "output_base": output_base,
        "output": output_base / run_id,
        "run_id": run_id,
        "threads": args.threads,
        "memory": args.memory_limit,
        "verify_stage07_hashes": bool(args.verify_stage07_hashes),
        "authorities": authorities,
        "config": config,
        "config_sha256": sha256_json(config),
    }


def initialize_state(payload: dict[str, Any]) -> None:
    state = payload["state"]
    config_path = state / "resume_config.json"
    if state.exists():
        if not config_path.is_file():
            raise RuntimeError("Private state exists without its resume configuration")
        saved = load_json(config_path)
        if saved.get("config_sha256") != payload["config_sha256"]:
            raise RuntimeError("Existing private state belongs to a different configuration")
        print("REMAINING_DYNAMIC_PRIVATE_STATE_AUTHENTICATED_OK", flush=True)
        return
    state.mkdir(parents=True, exist_ok=False)
    (state / "duckdb_temp").mkdir()
    atomic_json(
        config_path,
        {
            "status": "REMAINING_DYNAMIC_RESUME_CONFIG_OK",
            "created_utc": utc_now(),
            "config": payload["config"],
            "config_sha256": payload["config_sha256"],
            "privacy": "PRIVATE ACCOUNT-LEVEL STATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print("REMAINING_DYNAMIC_PRIVATE_STATE_CREATED", flush=True)


def build_a2_account_windows(
    *,
    recipient: Path,
    stage07_paths: Sequence[Path],
    output: Path,
    threads: int,
    memory: str,
    temp: Path,
    start_ms: int = PANEL_START_MS,
    end_exclusive_ms: int = PANEL_END_EXCLUSIVE_MS,
) -> None:
    """Create one row per first disconnection with symmetric choice-window counts."""
    duckdb, _, _, _ = import_dependencies()
    connection = duckdb.connect()
    configure_duckdb(connection, threads=threads, memory=memory, temp=temp)
    stage_paths = path_list_literal(stage07_paths)
    recipient_sql = sql_literal(recipient)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}.parquet")
    max_window = 90 * DAY_MS
    query = f"""
      COPY (
        WITH exposure AS (
          SELECT
            CAST(cohort_row_id AS BIGINT) AS cohort_row_id,
            CAST(recipient_user_id AS BIGINT) AS recipient_user_id,
            CAST(exposure_anchor_utc_ms AS BIGINT) AS exposure_anchor_utc_ms
          FROM read_parquet({recipient_sql})
          WHERE CAST(exposure_anchor_utc_ms AS BIGINT) >= {int(start_ms + max_window)}
            AND CAST(exposure_anchor_utc_ms AS BIGINT) < {int(end_exclusive_ms - max_window)}
        ), choices AS (
          SELECT
            CAST(chooser_user_id AS BIGINT) AS recipient_user_id,
            CAST(api_last_move_at_ms AS BIGINT) AS choice_utc_ms,
            CAST(kind_draw AS BIGINT) AS kind_draw
          FROM read_parquet({stage_paths}, union_by_name=true)
          WHERE CAST(fair_competitive AS BOOLEAN)
            AND chooser_user_id IS NOT NULL
            AND api_last_move_at_ms IS NOT NULL
        ), joined AS (
          SELECT
            e.cohort_row_id,
            c.choice_utc_ms - e.exposure_anchor_utc_ms AS delta_ms,
            c.kind_draw
          FROM exposure e
          INNER JOIN choices c
            ON c.recipient_user_id = e.recipient_user_id
           AND c.choice_utc_ms >= e.exposure_anchor_utc_ms - {max_window}
           AND c.choice_utc_ms <= e.exposure_anchor_utc_ms + {max_window}
           AND c.choice_utc_ms <> e.exposure_anchor_utc_ms
        ), aggregated AS (
          SELECT
            cohort_row_id,
            COUNT(*) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{90 * DAY_MS})::BIGINT AS pre_90_n,
            SUM(kind_draw) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{90 * DAY_MS})::BIGINT AS pre_90_k,
            COUNT(*) FILTER (WHERE delta_ms > 0 AND delta_ms <= {90 * DAY_MS})::BIGINT AS post_90_n,
            SUM(kind_draw) FILTER (WHERE delta_ms > 0 AND delta_ms <= {90 * DAY_MS})::BIGINT AS post_90_k,
            COUNT(*) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{60 * DAY_MS})::BIGINT AS pre_60_n,
            SUM(kind_draw) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{60 * DAY_MS})::BIGINT AS pre_60_k,
            COUNT(*) FILTER (WHERE delta_ms > 0 AND delta_ms <= {60 * DAY_MS})::BIGINT AS post_60_n,
            SUM(kind_draw) FILTER (WHERE delta_ms > 0 AND delta_ms <= {60 * DAY_MS})::BIGINT AS post_60_k,
            COUNT(*) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{30 * DAY_MS})::BIGINT AS pre_30_n,
            SUM(kind_draw) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{30 * DAY_MS})::BIGINT AS pre_30_k,
            COUNT(*) FILTER (WHERE delta_ms > 0 AND delta_ms <= {30 * DAY_MS})::BIGINT AS post_30_n,
            SUM(kind_draw) FILTER (WHERE delta_ms > 0 AND delta_ms <= {30 * DAY_MS})::BIGINT AS post_30_k
          FROM joined
          GROUP BY cohort_row_id
        )
        SELECT
          e.cohort_row_id,
          COALESCE(a.pre_30_n, 0)::BIGINT AS pre_30_n,
          COALESCE(a.pre_30_k, 0)::BIGINT AS pre_30_k,
          COALESCE(a.post_30_n, 0)::BIGINT AS post_30_n,
          COALESCE(a.post_30_k, 0)::BIGINT AS post_30_k,
          COALESCE(a.pre_60_n, 0)::BIGINT AS pre_60_n,
          COALESCE(a.pre_60_k, 0)::BIGINT AS pre_60_k,
          COALESCE(a.post_60_n, 0)::BIGINT AS post_60_n,
          COALESCE(a.post_60_k, 0)::BIGINT AS post_60_k,
          COALESCE(a.pre_90_n, 0)::BIGINT AS pre_90_n,
          COALESCE(a.pre_90_k, 0)::BIGINT AS pre_90_k,
          COALESCE(a.post_90_n, 0)::BIGINT AS post_90_n,
          COALESCE(a.post_90_k, 0)::BIGINT AS post_90_k
        FROM exposure e
        LEFT JOIN aggregated a USING (cohort_row_id)
        ORDER BY e.cohort_row_id
      ) TO {sql_literal(temporary)}
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
    """
    try:
        connection.execute(query)
    finally:
        connection.close()
    os.replace(temporary, output)


def authenticate_or_build_a2_cache(
    payload: dict[str, Any], stage07_paths: Sequence[Path]
) -> tuple[Path, dict[str, Any]]:
    _, _, _, pq = import_dependencies()
    output = payload["state"] / "a2_account_windows_private.parquet"
    receipt = payload["state"] / "a2_account_windows_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = load_json(receipt)
        expected = {
            "status": "A2_ACCOUNT_WINDOWS_PRIVATE_OK",
            "config_sha256": payload["config_sha256"],
            "output_sha256": sha256_file(output),
            "output_bytes": output.stat().st_size,
            "rows": int(pq.ParquetFile(output).metadata.num_rows),
        }
        for key, value in expected.items():
            if saved.get(key) != value:
                raise RuntimeError(f"A2 private-cache mismatch: {key}")
        print(f"A2_ACCOUNT_WINDOWS_CHECKPOINT_OK rows={saved['rows']:,}", flush=True)
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial A2 account-window checkpoint exists")
    print("A2_ACCOUNT_WINDOWS_BUILD_BEGIN", flush=True)
    started = time.time()
    build_a2_account_windows(
        recipient=payload["recipient"],
        stage07_paths=stage07_paths,
        output=output,
        threads=payload["threads"],
        memory=payload["memory"],
        temp=payload["state"] / "duckdb_temp/a2",
    )
    rows = int(pq.ParquetFile(output).metadata.num_rows)
    if not 500_000 <= rows <= EXPECTED_RECIPIENT_ROWS:
        raise RuntimeError(f"Implausible A2 symmetric-window row count: {rows}")
    saved = {
        "status": "A2_ACCOUNT_WINDOWS_PRIVATE_OK",
        "created_utc": utc_now(),
        "config_sha256": payload["config_sha256"],
        "output_path": str(output),
        "output_sha256": sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": rows,
        "runtime_seconds": time.time() - started,
        "compression": "Zstandard",
        "row_group_size": 250_000,
        "source_stage07_rows": EXPECTED_STAGE07_ROWS,
        "privacy": "PRIVATE ACCOUNT-LEVEL STATE; DO NOT COMMIT OR PUBLISH",
    }
    atomic_json(receipt, saved)
    shutil.rmtree(payload["state"] / "duckdb_temp/a2", ignore_errors=True)
    print(f"A2_ACCOUNT_WINDOWS_BUILD_OK rows={rows:,}", flush=True)
    return output, saved


def arrow_numpy(table: Any, name: str, np: Any, pa: Any) -> Any:
    import pyarrow.compute as pc  # type: ignore

    column = table[name].combine_chunks()
    # A missing subsequent choice is substantively missing, not a false or -1 choice.
    # Preserve that distinction so the model's finite-outcome filter works correctly.
    if pa.types.is_boolean(column.type) and name == "first_subsequent_kind_draw":
        column = pc.cast(column, pa.float64(), safe=True)
        column = pc.fill_null(column, pa.scalar(float("nan"), type=pa.float64()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)
    if pa.types.is_boolean(column.type):
        column = pc.cast(column, pa.int8(), safe=True)
        column = pc.fill_null(column, pa.scalar(-1, type=pa.int8()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.int64)
    if pa.types.is_integer(column.type):
        column = pc.cast(column, pa.int64(), safe=True)
        column = pc.fill_null(column, pa.scalar(-1, type=pa.int64()))
        return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.int64)
    column = pc.cast(column, pa.float64(), safe=True)
    column = pc.fill_null(column, pa.scalar(float("nan"), type=pa.float64()))
    return np.asarray(column.to_numpy(zero_copy_only=False), dtype=np.float64)


def load_recipient_data(base: Any, path: Path) -> dict[str, Any]:
    _, np, pa, pq = import_dependencies()
    columns = {
        "cohort_row_id",
        "exposure_chooser_user_id",
        "received_mercy",
        "exposure_claimed_win",
        "arm_eligible",
        "exposure_no_mating_draw",
        "exposure_chooser_loss",
        "first_ever_pair",
        "a1_90d_followup_eligible",
        "exposure_cell_code",
        "exposure_month_code",
        "reached_fair_chooser_within_90d",
        "first_subsequent_kind_draw",
        "first_subsequent_speed_code",
        "first_subsequent_tournament_like",
        "first_subsequent_month_code",
        "recipient_future_disconnections_90d",
        "recipient_future_mercy_receipts_90d",
        "recipient_next_disconnection_utc_ms",
        "exposure_anchor_utc_ms",
        *base.EXPOSURE_CONTROLS,
        *base.SUBSEQUENT_CONTROLS,
    }
    ordered = sorted(columns)
    table = pq.read_table(path, columns=ordered)
    data = {name: arrow_numpy(table, name, np, pa) for name in ordered}
    row_id = data["cohort_row_id"]
    if row_id.size != EXPECTED_RECIPIENT_ROWS or not np.array_equal(
        row_id, np.arange(EXPECTED_RECIPIENT_ROWS, dtype=np.int64)
    ):
        raise RuntimeError("Private recipient row order changed")
    return data


def load_a2_arrays(cache: Path, total_rows: int) -> dict[str, Any]:
    _, np, pa, pq = import_dependencies()
    table = pq.read_table(cache)
    row_id = arrow_numpy(table, "cohort_row_id", np, pa)
    if row_id.size == 0 or np.any(np.diff(row_id) <= 0):
        raise RuntimeError("A2 cache row IDs are not strictly increasing")
    output: dict[str, Any] = {
        "full_symmetric_window": np.zeros(total_rows, dtype=bool)
    }
    output["full_symmetric_window"][row_id] = True
    for horizon in WINDOW_HORIZONS_DAYS:
        for side in ("pre", "post"):
            for suffix in ("n", "k"):
                name = f"{side}_{horizon}_{suffix}"
                values = arrow_numpy(table, name, np, pa)
                expanded = np.zeros(total_rows, dtype=np.int64)
                expanded[row_id] = values
                output[name] = expanded
    return output


def rates_from_counts(numerator: Any, denominator: Any) -> Any:
    import numpy as np
    numerator = np.asarray(numerator, dtype=np.float64)
    denominator = np.asarray(denominator, dtype=np.float64)
    result = np.full(denominator.size, np.nan, dtype=np.float64)
    valid = denominator > 0
    result[valid] = numerator[valid] / denominator[valid]
    return result


def normal_two_sided_p(t_value: float) -> float:
    return math.erfc(abs(t_value) / math.sqrt(2.0))


def clustered_weighted_mean(
    values: Any, weights: Any, clusters: Any, sample: Any
) -> dict[str, Any]:
    """Weighted mean with a one-way cluster-robust influence-function SE."""
    import numpy as np
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    clusters = np.asarray(clusters, dtype=np.int64)
    sample = np.asarray(sample, dtype=bool)
    valid = sample & np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if np.count_nonzero(valid) < 2:
        raise RuntimeError("Insufficient rows for clustered weighted mean")
    y = values[valid]
    w = weights[valid]
    g = clusters[valid]
    mean = float(np.sum(w * y) / np.sum(w))
    unique, inverse = np.unique(g, return_inverse=True)
    if unique.size < 2:
        raise RuntimeError("Insufficient clusters for clustered weighted mean")
    scores = np.bincount(inverse, weights=w * (y - mean), minlength=unique.size)
    correction = unique.size / (unique.size - 1)
    variance = correction * float(np.sum(scores * scores)) / float(np.sum(w) ** 2)
    standard_error = math.sqrt(max(variance, 0.0))
    t_value = mean / standard_error if standard_error > 0 else math.inf
    return {
        "mean": mean,
        "standard_error": standard_error,
        "t_value": t_value,
        "p_value_two_sided": normal_two_sided_p(t_value),
        "rows": int(y.size),
        "clusters": int(unique.size),
        "weight_sum": float(np.sum(w)),
    }


def add_percentage_point_fields(result: dict[str, Any]) -> dict[str, Any]:
    result = dict(result)
    result["coefficient_percentage_points"] = 100.0 * float(result["coefficient"])
    result["standard_error_percentage_points"] = 100.0 * float(result["standard_error"])
    result["confidence_interval_95_low_pp"] = 100.0 * (
        float(result["coefficient"]) - 1.959963984540054 * float(result["standard_error"])
    )
    result["confidence_interval_95_high_pp"] = 100.0 * (
        float(result["coefficient"]) + 1.959963984540054 * float(result["standard_error"])
    )
    return result


def estimate_a2(
    base: Any,
    data: dict[str, Any],
    support: dict[str, Any],
    windows: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, np, _, _ = import_dependencies()
    did_rows: list[dict[str, Any]] = []
    arm_rows: list[dict[str, Any]] = []
    treatment = data["received_mercy"].astype(bool)
    first_pair = data["first_ever_pair"].astype(bool)
    full = windows["full_symmetric_window"]
    clusters = data["exposure_chooser_user_id"]

    for horizon in WINDOW_HORIZONS_DAYS:
        pre_n = windows[f"pre_{horizon}_n"]
        pre_k = windows[f"pre_{horizon}_k"]
        post_n = windows[f"post_{horizon}_n"]
        post_k = windows[f"post_{horizon}_k"]
        pre_rate = rates_from_counts(pre_k, pre_n)
        post_rate = rates_from_counts(post_k, post_n)
        change = post_rate - pre_rate
        for minimum in MINIMUM_CHOICES:
            sample = full & (pre_n >= minimum) & (post_n >= minimum)
            outcome_name = f"a2_change_{horizon}d_min{minimum}"
            data[outcome_name] = change
            model_sample = sample & support["eligible"] & np.isfinite(change)
            indices = np.flatnonzero(model_sample)
            controls, control_names = base.model_controls(
                data, indices, state_conditioned=False
            )
            estimand = (
                f"A2_mercy_minus_claim_change_{horizon}d_"
                f"minimum_{minimum}_choices_each_side"
            )
            specification = {
                "analysis": "A2_secondary_mechanism_decomposition",
                "outcome": "within_account_post_minus_pre_kind_rate",
                "estimand": estimand,
                "state_conditioned": False,
                "symmetric_window_days": horizon,
                "minimum_opportunities_each_side": minimum,
                "exposure_common_support": "n_mercy>=5 and n_claimed>=20",
                "standardization": "ATT-style exposure-cell weights",
                "fixed_effects": "exposure cell and exposure month",
                "cluster": "exposure chooser",
                "postoutcome_secondary": True,
            }
            fitted = base.fit_weighted_cluster_model(
                outcome=change[indices],
                treatment=data["received_mercy"][indices],
                controls=controls,
                control_names=control_names,
                weights=support["weights"][indices],
                cell_fe=data["exposure_cell_code"][indices],
                month_fe=data["exposure_month_code"][indices],
                clusters=data["exposure_chooser_user_id"][indices],
                row_ids=data["cohort_row_id"][indices],
                specification=specification,
                binary_outcome=False,
            )
            fitted = add_percentage_point_fields(fitted)
            fitted.update(
                {
                    "analysis": "A2_secondary_mechanism_decomposition",
                    "horizon_days_each_side": horizon,
                    "minimum_opportunities_each_side": minimum,
                    "outcome": "within_account_post_minus_pre_kind_rate",
                    "interpretation": (
                        "mercy-minus-claim difference in within-account change; "
                        "inherits nonrandom-treatment caveats"
                    ),
                    "primary_family_reopened": False,
                }
            )
            did_rows.append(fitted)

            # The arm-path table makes the sign-pattern decomposition transparent.
            arm_definitions = (
                (
                    "any_first_qualifying_disconnection",
                    sample & first_pair,
                    np.ones(change.size, dtype=np.float64),
                ),
                (
                    "arm_eligible_common_support_pooled",
                    sample & support["eligible"],
                    support["weights"],
                ),
                (
                    "mercy_received",
                    sample & support["eligible"] & treatment,
                    support["weights"],
                ),
                (
                    "claimed_against",
                    sample & support["eligible"] & ~treatment,
                    support["weights"],
                ),
            )
            for label, mask, weights in arm_definitions:
                moments = clustered_weighted_mean(change, weights, clusters, mask)
                valid = mask & np.isfinite(change) & (weights > 0)
                pre_total_n = int(np.sum(pre_n[valid]))
                post_total_n = int(np.sum(post_n[valid]))
                row = {
                    "analysis": "A2_secondary_arm_path",
                    "path": label,
                    "horizon_days_each_side": horizon,
                    "minimum_opportunities_each_side": minimum,
                    **moments,
                    "mean_change_percentage_points": 100.0 * moments["mean"],
                    "standard_error_percentage_points": 100.0 * moments["standard_error"],
                    "weighted_pre_kind_rate": float(np.average(pre_rate[valid], weights=weights[valid])),
                    "weighted_post_kind_rate": float(np.average(post_rate[valid], weights=weights[valid])),
                    "pre_opportunities": pre_total_n,
                    "post_opportunities": post_total_n,
                    "pre_kind_draws": int(np.sum(pre_k[valid])),
                    "post_kind_draws": int(np.sum(post_k[valid])),
                    "causal_claim": False,
                    "primary_family_reopened": False,
                }
                arm_rows.append(row)
    return did_rows, arm_rows


def next_exposure_censor_mask(
    exposure_anchor_ms: Any, first_delta_ms: Any, next_exposure_ms: Any
) -> Any:
    import numpy as np
    anchor = np.asarray(exposure_anchor_ms, dtype=np.int64)
    delta = np.asarray(first_delta_ms, dtype=np.int64)
    next_time = np.asarray(next_exposure_ms, dtype=np.int64)
    first_time = anchor + delta
    return (next_time < 0) | (first_time <= next_time)


def estimate_a1_completion(
    base: Any, data: dict[str, Any], support: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    _, np, _, _ = import_dependencies()
    first = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(bool)
    followup = data["a1_90d_followup_eligible"].astype(bool)
    reached = data["reached_fair_chooser_within_90d"].astype(bool)
    conditional = first & followup & reached
    uncrossed = next_exposure_censor_mask(
        data["exposure_anchor_utc_ms"],
        data["first_subsequent_delta_ms"],
        data["recipient_next_disconnection_utc_ms"],
    )
    censored_sample = conditional & uncrossed
    censor_rows: list[dict[str, Any]] = []
    for state_conditioned, label in (
        (False, "A1_total_path_censored_at_next_qualifying_exposure"),
        (True, "A1_state_conditioned_censored_at_next_qualifying_exposure"),
    ):
        fitted = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name="first_subsequent_kind_draw",
            sample=censored_sample,
            estimand=label,
            state_conditioned=state_conditioned,
            binary_outcome=True,
        )
        fitted.update(
            {
                "analysis": "A1_postoutcome_next_exposure_censoring_sensitivity",
                "postoutcome_secondary": True,
                "censoring_rule": (
                    "exclude first subsequent fair choice if it follows the next "
                    "qualifying disconnection"
                ),
                "primary_family_reopened": False,
            }
        )
        censor_rows.append(fitted)

    future_disconnections = data["recipient_future_disconnections_90d"].astype(np.int64)
    future_mercy = data["recipient_future_mercy_receipts_90d"].astype(np.int64)
    data["any_future_disconnection_90d"] = future_disconnections > 0
    data["any_future_mercy_receipt_90d"] = future_mercy > 0
    path_rows: list[dict[str, Any]] = []
    for outcome, label, binary in (
        (
            "any_future_disconnection_90d",
            "any_later_qualifying_disconnection_within_90d",
            True,
        ),
        (
            "recipient_future_disconnections_90d",
            "number_later_qualifying_disconnections_within_90d",
            False,
        ),
        ("any_future_mercy_receipt_90d", "any_later_mercy_receipt_within_90d", True),
        (
            "recipient_future_mercy_receipts_90d",
            "number_later_mercy_receipts_within_90d",
            False,
        ),
    ):
        fitted = base.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name=outcome,
            sample=first & followup,
            estimand=label,
            state_conditioned=False,
            binary_outcome=binary,
        )
        fitted.update(
            {
                "analysis": "A1_postoutcome_natural_later_exposure_path",
                "postoutcome_secondary": True,
                "primary_family_reopened": False,
            }
        )
        path_rows.append(fitted)

    diagnostic = {
        "conditional_choice_rows_before_censoring": int(np.count_nonzero(conditional & support["eligible"])),
        "conditional_choice_rows_after_censoring": int(np.count_nonzero(censored_sample & support["eligible"])),
        "rows_removed_by_next_exposure_censoring": int(np.count_nonzero(conditional & support["eligible"] & ~uncrossed)),
        "retained_share": float(
            np.count_nonzero(censored_sample & support["eligible"])
            / np.count_nonzero(conditional & support["eligible"])
        ),
    }
    return censor_rows, path_rows, diagnostic


def authenticate_completed_output(root: Path, config_sha: str) -> dict[str, Any] | None:
    if not root.exists():
        return None
    success_path = root / "_SUCCESS.json"
    if not success_path.is_file():
        raise RuntimeError(f"Partial aggregate output exists: {root}")
    saved = load_json(success_path)
    if (
        saved.get("status") != "REMAINING_DYNAMIC_COMPLETION_V100_OK"
        or saved.get("config_sha256") != config_sha
    ):
        raise RuntimeError("Existing aggregate output belongs to another configuration")
    manifest = root / "report_file_hashes.tsv"
    if sha256_file(manifest) != saved.get("report_manifest_sha256"):
        raise RuntimeError("Existing aggregate manifest SHA mismatch")
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    for row in rows:
        path = root / row["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(row["bytes"])
            or sha256_file(path) != row["sha256"]
        ):
            raise RuntimeError(f"Existing aggregate file mismatch: {path}")
    return saved


def write_public_output(
    payload: dict[str, Any],
    a2_did: list[dict[str, Any]],
    a2_arms: list[dict[str, Any]],
    a1_censor: list[dict[str, Any]],
    a1_paths: list[dict[str, Any]],
    censor_diagnostic: dict[str, Any],
    cache_receipt: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    final = payload["output"]
    completed = authenticate_completed_output(final, payload["config_sha256"])
    if completed is not None:
        print("REMAINING_DYNAMIC_COMPLETED_OUTPUT_AUTHENTICATED_OK", flush=True)
        return final, completed
    staging = final.with_name("." + final.name + f".tmp.{uuid.uuid4().hex}")
    (staging / "results").mkdir(parents=True, exist_ok=False)
    (staging / "receipts").mkdir()
    write_csv(staging / "results/a2_mercy_vs_claim_differences.csv", a2_did)
    write_csv(staging / "results/a2_prepost_arm_paths.csv", a2_arms)
    write_csv(staging / "results/a1_next_exposure_censoring.csv", a1_censor)
    write_csv(staging / "results/a1_later_exposure_paths.csv", a1_paths)
    atomic_json(staging / "results/a1_censoring_diagnostic.json", censor_diagnostic)
    atomic_json(
        staging / "receipts/input_authorities.json",
        {
            **payload["authorities"],
            "config_sha256": payload["config_sha256"],
            "stage07_rows": EXPECTED_STAGE07_ROWS,
            "private_a2_cache_sha256": cache_receipt["output_sha256"],
            "private_a2_cache_rows": cache_receipt["rows"],
        },
    )
    summary = {
        "status": "REMAINING_DYNAMIC_COMPLETION_V100_OK",
        "created_utc": utc_now(),
        "run_id": payload["run_id"],
        "script_version": SCRIPT_VERSION,
        "script_sha256": payload["authorities"]["script_sha256"],
        "config_sha256": payload["config_sha256"],
        "scope": [
            "A2 secondary three-state pre/post mechanism decomposition",
            "A1 next-exposure censoring and later-exposure paths",
        ],
        "a2_mercy_vs_claim_differences": a2_did,
        "a2_prepost_arm_paths": a2_arms,
        "a1_next_exposure_censoring": a1_censor,
        "a1_later_exposure_paths": a1_paths,
        "a1_censoring_diagnostic": censor_diagnostic,
        "private_cache": {
            key: cache_receipt[key]
            for key in (
                "status",
                "output_sha256",
                "output_bytes",
                "rows",
                "runtime_seconds",
                "compression",
                "row_group_size",
            )
            if key in cache_receipt
        },
        "execution": {
            "duckdb_threads": payload["threads"],
            "memory_limit": payload["memory"],
            "stage07_hashes_reverified": payload["verify_stage07_hashes"],
            "chronology_rebuilt": False,
            "patron_profile_input_read": False,
            "api_requests": 0,
            "git_mutation": False,
        },
        "claim_boundary": {
            "postoutcome_secondary": True,
            "primary_family_reopened": False,
            "a2_pooled_prepost_is_causal": False,
            "a2_mercy_vs_claim_is_randomized": False,
            "b2_first_lifetime_claim_supported": False,
        },
        "privacy": "Aggregate results only; account-level cache remains on XT_Pro.",
    }
    atomic_json(staging / "summary.json", summary)
    manifest_rows = directory_manifest(
        staging, excluded={"_SUCCESS.json", "report_file_hashes.tsv"}
    )
    write_csv(staging / "report_file_hashes.tsv", manifest_rows, delimiter="\t")
    success = {
        **summary,
        "summary_sha256": sha256_file(staging / "summary.json"),
        "report_manifest_sha256": sha256_file(staging / "report_file_hashes.tsv"),
        "report_files_hashed": len(manifest_rows),
    }
    atomic_json(staging / "_SUCCESS.json", success)
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    return final, success


def privacy_audit(root: Path) -> None:
    allowed = {".json", ".csv", ".tsv"}
    forbidden = (
        "recipient_user_id",
        "exposure_chooser_user_id",
        "disconnected_username",
        "chooser_username",
        '"username"',
    )
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in allowed:
            raise RuntimeError(f"Non-aggregate file type in public output: {path}")
        lowered = path.read_text(encoding="utf-8").lower()
        for token in forbidden:
            if token in lowered:
                raise RuntimeError(f"Private identifier field leaked into {path}: {token}")


def execute(payload: dict[str, Any], base: Any) -> tuple[Path, dict[str, Any]]:
    started = time.time()
    completed = authenticate_completed_output(payload["output"], payload["config_sha256"])
    if completed is not None:
        return payload["output"], completed
    initialize_state(payload)
    stage07 = base.authenticate_stage07(
        payload["stage07"], verify_hashes=payload["verify_stage07_hashes"]
    )
    stage07_paths = stage07["paths"]
    cache, cache_receipt = authenticate_or_build_a2_cache(payload, stage07_paths)
    print("RECIPIENT_MODEL_INPUT_LOAD_BEGIN", flush=True)
    data = load_recipient_data(base, payload["recipient"])
    support = base.common_support_weights(data)
    windows = load_a2_arrays(cache, EXPECTED_RECIPIENT_ROWS)
    print("RECIPIENT_MODEL_INPUT_LOAD_OK", flush=True)
    print("A2_ESTIMATION_BEGIN", flush=True)
    a2_did, a2_arms = estimate_a2(base, data, support, windows)
    print("A2_ESTIMATION_OK", flush=True)
    print("A1_COMPLETION_ESTIMATION_BEGIN", flush=True)
    a1_censor, a1_paths, censor_diagnostic = estimate_a1_completion(base, data, support)
    print("A1_COMPLETION_ESTIMATION_OK", flush=True)
    final, success = write_public_output(
        payload,
        a2_did,
        a2_arms,
        a1_censor,
        a1_paths,
        censor_diagnostic,
        cache_receipt,
    )
    privacy_audit(final)
    success["runtime_seconds_current_invocation"] = time.time() - started
    print(f"REMAINING_DYNAMIC_COMPLETION_V100_OK: {final}", flush=True)
    print(f"runtime_seconds: {time.time() - started:.1f}", flush=True)
    return final, success


def self_test() -> None:
    import numpy as np
    rate = rates_from_counts(np.array([0, 1, 2]), np.array([0, 2, 4]))
    assert np.isnan(rate[0]) and np.allclose(rate[1:], [0.5, 0.5])
    mask = next_exposure_censor_mask(
        np.array([100, 100, 100]),
        np.array([10, 20, 30]),
        np.array([-1, 125, 120]),
    )
    assert mask.tolist() == [True, True, False]
    means = clustered_weighted_mean(
        np.array([0.0, 1.0, 0.5, 0.5]),
        np.ones(4),
        np.array([1, 1, 2, 2]),
        np.ones(4, dtype=bool),
    )
    assert abs(means["mean"] - 0.5) < 1e-12
    assert means["clusters"] == 2
    assert PANEL_START_MS + 180 * DAY_MS < PANEL_END_EXCLUSIVE_MS
    print("REMAINING_DYNAMIC_COMPLETION_V100_SELF_TEST_OK")


def print_plan(payload: dict[str, Any]) -> None:
    print("REMAINING_DYNAMIC_COMPLETION_V100_PLAN_OK")
    print("script_version:", SCRIPT_VERSION)
    print("script_sha256:", payload["authorities"]["script_sha256"])
    print("run_id:", payload["run_id"])
    print("threads:", payload["threads"])
    print("memory_limit:", payload["memory"])
    print("stage07_rows:", f"{EXPECTED_STAGE07_ROWS:,}")
    print("private_state:", payload["state"])
    print("aggregate_output:", payload["output"])
    print("expected_runtime: 15-60 minutes; most likely 20-35 minutes")
    print("storage: one projected Zstandard-compressed account-window Parquet")
    print("chronology_rebuilt: false")
    print("patron_profile_input_read: false")
    print("primary_family_reopened: false")


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return
    script_path = Path(__file__).resolve()
    payload = make_payload(args, script_path)
    base = load_module(payload["base_code"])
    print_plan(payload)
    if not args.execute:
        print("No analysis row was read. Re-run with --execute.")
        return
    execute(payload, base)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"REMAINING_DYNAMIC_COMPLETION_FAIL_CLOSED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise
