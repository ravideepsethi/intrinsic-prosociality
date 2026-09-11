#!/usr/bin/env python3
"""C6 confirmatory exploitation outcome and C10 denial-mechanism extensions."""

from __future__ import annotations

import concurrent.futures
import csv
import math
import os
from pathlib import Path
import shutil
import time
from typing import Any, Sequence
import uuid

import campaign1_nonprofile_common_v102 as common


SCRIPT_VERSION = "1.0.0"
HORIZON_90D_MS = 90 * common.DAY_MS
EXPECTED_RECIPIENT_SHA256 = (
    "41ef57b3118ea7d3b0bfb7a5e19040bd82e7794aa54fb6b06625d7793921816d"
)
EXPECTED_A2_CACHE_SHA256 = (
    "5222f8702f8dc5fbe651cabf043951d96937e95440a5d233be4e50d1bfa0edac"
)
EXPECTED_A2_CACHE_ROWS = 1_642_449
EXPECTED_REMAINING_SUCCESS_SHA256 = (
    "65555d86abbcfb9eb7918bbddb8460bad1d78198c7767eebe80fb3d3dac373e5"
)
EXPECTED_STAGE07_SUCCESS_SHA256 = (
    "8b7010b528ae5c6f1e1a9b517258648204c14c17ca41a2a6796f8ee5a1ed6db7"
)
EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = (
    "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
)
CHRONOLOGY_COLUMNS = ("utc_ms", "white_id", "black_id")
C6_GATE_RECIPIENTS = 4_000
C6_GATE_CLEAR_EVENTS = 4_000


def read_chronology_manifest(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if len(rows) != common.EXPECTED_CHRONOLOGY_FILES:
        raise RuntimeError(f"Chronology manifest count changed: {len(rows)}")
    parsed: list[dict[str, Any]] = []
    total = 0
    for expected, row in enumerate(rows):
        if int(row["file_index"]) != expected:
            raise RuntimeError("Chronology manifest ordering changed")
        candidate = Path(row["path"])
        if not candidate.is_file() or candidate.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Chronology authority changed: {candidate}")
        total += int(row["rows"])
        parsed.append(
            {
                "file_index": expected,
                "path": str(candidate),
                "bytes": int(row["bytes"]),
                "rows": int(row["rows"]),
                "utc_ms_min": int(row["utc_ms_min"]) if row.get("utc_ms_min") else None,
                "utc_ms_max": int(row["utc_ms_max"]) if row.get("utc_ms_max") else None,
                "footer_signature_sha256": row["footer_signature_sha256"],
            }
        )
    if total != common.EXPECTED_CHRONOLOGY_ROWS:
        raise RuntimeError(f"Chronology row total changed: {total}")
    return parsed


def _load_recipient_minimal(recipient: Path, core: Any) -> dict[str, Any]:
    _, np, _, pq = common.import_dependencies()
    columns = {
        "cohort_row_id",
        "recipient_user_id",
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
        "exposure_anchor_utc_ms",
        "encouragement_prior_pair_excluded_n",
        "encouragement_pair_excluded_propensity",
        *core.EXPOSURE_CONTROLS,
    }
    table = pq.read_table(recipient, columns=sorted(columns))
    data = {
        name: common.arrow_numpy(
            table,
            name,
            nullable_float=name
            in {
                "encouragement_pair_excluded_propensity",
                *core.EXPOSURE_CONTROLS,
            },
        )
        for name in sorted(columns)
    }
    row_id = data["cohort_row_id"]
    if row_id.size != common.EXPECTED_RECIPIENT_ROWS or not np.array_equal(
        row_id, np.arange(row_id.size, dtype=np.int64)
    ):
        raise RuntimeError("A1 recipient dense row order changed")
    return data


def build_c6_preoutcome_index(
    *, recipient: Path, core: Any, state: Path, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    _, np, pa, pq = common.import_dependencies()
    output = state / "c6_preoutcome_cohort_private.parquet"
    receipt = state / "c6_preoutcome_cohort_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = common.load_json(receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
        ):
            raise RuntimeError("C6 pre-outcome cohort checkpoint mismatch")
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C6 pre-outcome cohort checkpoint exists")
    data = _load_recipient_minimal(recipient, core)
    support = core.common_support_weights(data)
    selected = support["eligible"] & data["a1_90d_followup_eligible"].astype(bool)
    indices = np.flatnonzero(selected)
    recipients = data["recipient_user_id"][indices].astype(np.int64)
    if np.unique(recipients).size != recipients.size:
        raise RuntimeError("C6 expects one first-exposure row per recipient ID")
    table = pa.table(
        {
            "cohort_row_id": pa.array(data["cohort_row_id"][indices], type=pa.int64()),
            "recipient_user_id": pa.array(recipients, type=pa.int64()),
            "exposure_anchor_utc_ms": pa.array(
                data["exposure_anchor_utc_ms"][indices], type=pa.int64()
            ),
        }
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    pq.write_table(table, temporary, compression="zstd", row_group_size=250_000)
    os.replace(temporary, output)
    saved = {
        "status": "C6_PREOUTCOME_A1_COHORT_FROZEN",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_sha256": common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": int(indices.size),
        "common_support_rows_before_followup": int(np.count_nonzero(support["eligible"])),
        "followup_eligible_rows": int(indices.size),
        "c6_outcome_fields_read": [],
        "exposure_treatment_read_only_for_frozen_a1_common_support": True,
        "treatment_specific_c6_outcomes_tabulated": False,
        "privacy": "PRIVATE ACCOUNT-LEVEL INDEX; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    del data
    return output, saved


def _arrow_int64(array: Any, np: Any, pa: Any) -> Any:
    import pyarrow.compute as pc  # type: ignore

    converted = pc.cast(array, pa.int64(), safe=True)
    if converted.null_count:
        converted = pc.fill_null(converted, pa.scalar(-1, type=pa.int64()))
    return np.asarray(converted.to_numpy(zero_copy_only=False), dtype=np.int64)


def _update_future_counts(
    *, event_ids: Any, event_times: Any, lookup: Any, anchors: Any, counts: Any, np: Any
) -> int:
    valid = (event_ids >= 0) & (event_ids < lookup.size)
    if not np.any(valid):
        return 0
    ids = event_ids[valid]
    times = event_times[valid]
    rows = lookup[ids]
    matched = rows >= 0
    if not np.any(matched):
        return 0
    rows = rows[matched]
    times = times[matched]
    delta = times - anchors[rows]
    in_window = (delta > 0) & (delta <= HORIZON_90D_MS)
    if not np.any(in_window):
        return 0
    selected = rows[in_window]
    unique, frequency = np.unique(selected, return_counts=True)
    counts[unique] += frequency.astype(np.int32, copy=False)
    return int(selected.size)


def _scan_chronology_file(
    *, file_row: dict[str, Any], lookup: Any, anchors: Any, output: Path, receipt: Path,
    batch_rows: int, config_sha256: str
) -> dict[str, Any]:
    _, np, pa, pq = common.import_dependencies()
    started = time.time()
    path = Path(file_row["path"])
    parquet = pq.ParquetFile(path)
    if set(CHRONOLOGY_COLUMNS) - set(parquet.schema_arrow.names):
        raise RuntimeError(f"Chronology schema changed: {path}")
    counts = np.zeros(anchors.size, dtype=np.int32)
    scanned = 0
    hits = 0
    invalid_time = 0
    for batch in parquet.iter_batches(
        batch_size=batch_rows, columns=list(CHRONOLOGY_COLUMNS), use_threads=False
    ):
        scanned += batch.num_rows
        times = _arrow_int64(batch.column(0), np, pa)
        white = _arrow_int64(batch.column(1), np, pa)
        black = _arrow_int64(batch.column(2), np, pa)
        valid_time = times > 0
        invalid_time += int(np.count_nonzero(~valid_time))
        if not np.all(valid_time):
            times, white, black = times[valid_time], white[valid_time], black[valid_time]
        hits += _update_future_counts(
            event_ids=white, event_times=times, lookup=lookup,
            anchors=anchors, counts=counts, np=np
        )
        hits += _update_future_counts(
            event_ids=black, event_times=times, lookup=lookup,
            anchors=anchors, counts=counts, np=np
        )
    active = np.flatnonzero(counts > 0)
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    pq.write_table(
        pa.table(
            {
                "index_row": pa.array(active, type=pa.int64()),
                "rated_games_90d": pa.array(counts[active], type=pa.int32()),
            }
        ),
        temporary,
        compression="zstd",
        row_group_size=250_000,
    )
    os.replace(temporary, output)
    saved = {
        "status": "C6_CHRONOLOGY_DENOMINATOR_FILE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "chronology_file_index": file_row["file_index"],
        "input_path": file_row["path"],
        "input_bytes": file_row["bytes"],
        "input_rows": file_row["rows"],
        "input_footer_signature_sha256": file_row["footer_signature_sha256"],
        "scanned_rows": scanned,
        "invalid_event_time_rows": invalid_time,
        "recipient_game_hits": hits,
        "output_path": str(output),
        "output_rows": int(active.size),
        "output_bytes": output.stat().st_size,
        "output_sha256": common.sha256_file(output),
        "runtime_seconds": time.time() - started,
    }
    common.atomic_json(receipt, saved)
    return saved


def _authenticate_scan_checkpoint(
    file_row: dict[str, Any], output: Path, receipt: Path, config_sha256: str
) -> dict[str, Any] | None:
    _, _, _, pq = common.import_dependencies()
    if not output.exists() and not receipt.exists():
        return None
    if not output.is_file() or not receipt.is_file():
        raise RuntimeError(f"Partial C6 denominator checkpoint: {file_row['file_index']}")
    saved = common.load_json(receipt)
    expected = {
        "status": "C6_CHRONOLOGY_DENOMINATOR_FILE_OK",
        "config_sha256": config_sha256,
        "chronology_file_index": file_row["file_index"],
        "input_path": file_row["path"],
        "input_footer_signature_sha256": file_row["footer_signature_sha256"],
        "output_path": str(output),
        "output_bytes": output.stat().st_size,
        "output_sha256": common.sha256_file(output),
        "output_rows": int(pq.ParquetFile(output).metadata.num_rows),
    }
    for key, value in expected.items():
        if saved.get(key) != value:
            raise RuntimeError(f"C6 denominator checkpoint mismatch: {key}")
    return saved


def build_c6_denominator_cache(
    *, cohort_index: Path, chronology_manifest: Path, state: Path,
    workers: int, batch_rows: int, threads: int, memory_limit: str,
    config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, np, _, pq = common.import_dependencies()
    output = state / "c6_rated_games_90d_private.parquet"
    final_receipt = state / "c6_rated_games_90d_receipt.json"
    if output.is_file() and final_receipt.is_file():
        saved = common.load_json(final_receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
        ):
            raise RuntimeError("C6 final denominator checkpoint mismatch")
        print("C6_RATED_GAME_DENOMINATOR_CHECKPOINT_OK", flush=True)
        return output, saved
    if output.exists() or final_receipt.exists():
        raise RuntimeError("Partial C6 final denominator checkpoint exists")
    table = pq.read_table(
        cohort_index,
        columns=["cohort_row_id", "recipient_user_id", "exposure_anchor_utc_ms"],
    )
    cohort_ids = common.arrow_numpy(table, "cohort_row_id")
    recipients = common.arrow_numpy(table, "recipient_user_id")
    anchors = common.arrow_numpy(table, "exposure_anchor_utc_ms")
    maximum = int(recipients.max())
    if maximum > 100_000_000:
        raise RuntimeError(f"Implausible maximum recipient ID: {maximum}")
    lookup = np.full(maximum + 1, -1, dtype=np.int32)
    lookup[recipients] = np.arange(recipients.size, dtype=np.int32)
    manifest = read_chronology_manifest(chronology_manifest)
    minimum_anchor = int(anchors.min())
    maximum_end = int(anchors.max()) + HORIZON_90D_MS
    selected = [
        row
        for row in manifest
        if not (
            row["utc_ms_max"] is not None and row["utc_ms_max"] <= minimum_anchor
        )
        and not (
            row["utc_ms_min"] is not None and row["utc_ms_min"] > maximum_end
        )
    ]
    checkpoint_root = state / "c6_chronology_denominator"
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    receipts: dict[int, dict[str, Any]] = {}
    pending: list[dict[str, Any]] = []
    for row in selected:
        target = checkpoint_root / f"file_{row['file_index']:04d}.parquet"
        receipt = checkpoint_root / f"file_{row['file_index']:04d}.json"
        saved = _authenticate_scan_checkpoint(row, target, receipt, config_sha256)
        if saved is None:
            pending.append(row)
        else:
            receipts[row["file_index"]] = saved
    print(
        "C6_CHRONOLOGY_DENOMINATOR_SCAN "
        f"selected={len(selected)} existing={len(receipts)} pending={len(pending)} "
        f"workers={min(workers, max(1, len(pending)))}",
        flush=True,
    )
    if pending:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(workers, len(pending)), thread_name_prefix="c6-chronology"
        ) as executor:
            futures = {}
            for row in pending:
                target = checkpoint_root / f"file_{row['file_index']:04d}.parquet"
                receipt = checkpoint_root / f"file_{row['file_index']:04d}.json"
                future = executor.submit(
                    _scan_chronology_file,
                    file_row=row,
                    lookup=lookup,
                    anchors=anchors,
                    output=target,
                    receipt=receipt,
                    batch_rows=batch_rows,
                    config_sha256=config_sha256,
                )
                futures[future] = row["file_index"]
            completed = len(receipts)
            for future in concurrent.futures.as_completed(futures):
                saved = future.result()
                receipts[saved["chronology_file_index"]] = saved
                completed += 1
                if completed % 10 == 0 or completed == len(selected):
                    print(
                        f"C6_CHRONOLOGY_PROGRESS {completed}/{len(selected)} "
                        f"last_file={saved['chronology_file_index']:04d}",
                        flush=True,
                    )
    if len(receipts) != len(selected):
        raise RuntimeError("C6 chronology scheduler left missing checkpoints")
    paths = [
        checkpoint_root / f"file_{row['file_index']:04d}.parquet" for row in selected
    ]
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c6_denominator_finalize",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH cohort AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY cohort_row_id)::BIGINT - 1 AS index_row
            FROM read_parquet({common.sql_literal(cohort_index)})
          ), summed AS (
            SELECT index_row, SUM(rated_games_90d)::BIGINT AS rated_games_90d
            FROM read_parquet({common.path_list_literal(paths)}, union_by_name=true)
            GROUP BY index_row
          )
          SELECT
            c.cohort_row_id,
            COALESCE(s.rated_games_90d, 0)::BIGINT AS rated_games_90d
          FROM cohort c LEFT JOIN summed s USING (index_row)
          ORDER BY c.cohort_row_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"SELECT COUNT(*), SUM(rated_games_90d), COUNT(*) FILTER (WHERE rated_games_90d>0), MAX(rated_games_90d) FROM read_parquet({common.sql_literal(temporary)})"
    ).fetchone()
    connection.close()
    if qa[0] != cohort_ids.size or qa[1] is None or qa[3] is None:
        raise RuntimeError(f"C6 denominator final row conservation failed: {qa}")
    os.replace(temporary, output)
    ordered = [receipts[row["file_index"]] for row in selected]
    saved = {
        "status": "C6_RATED_GAME_DENOMINATOR_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_sha256": common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": int(qa[0]),
        "rated_games_total": int(qa[1]),
        "recipients_with_positive_denominator": int(qa[2]),
        "maximum_recipient_games_90d": int(qa[3]),
        "chronology_files_selected": len(selected),
        "chronology_rows_scanned": sum(int(row["scanned_rows"]) for row in ordered),
        "chronology_rows_authority": common.EXPECTED_CHRONOLOGY_ROWS,
        "outcome_fields_read": [],
        "privacy": "PRIVATE ACCOUNT-LEVEL DENOMINATOR; DO NOT PUBLISH",
    }
    common.atomic_json(final_receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c6_denominator_finalize", ignore_errors=True)
    return output, saved


def build_c6_event_cache(
    *, cohort_index: Path, stage07_paths: Sequence[Path], state: Path,
    threads: int, memory_limit: str, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c6_later_timeout_events_90d_private.parquet"
    receipt = state / "c6_later_timeout_events_90d_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = common.load_json(receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
        ):
            raise RuntimeError("C6 event checkpoint mismatch")
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C6 event checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c6_events",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH cohort AS (
            SELECT cohort_row_id, recipient_user_id, exposure_anchor_utc_ms
            FROM read_parquet({common.sql_literal(cohort_index)})
          ), events AS (
            SELECT
              CAST(disconnected_user_id AS BIGINT) AS recipient_user_id,
              CAST(api_last_move_at_ms AS BIGINT) AS event_utc_ms,
              CAST(clearly_worse AS BOOLEAN) AS clearly_worse,
              CAST(tournament_like_event AS BOOLEAN) AS tournament_like
            FROM read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true)
            WHERE disconnected_user_id IS NOT NULL AND api_last_move_at_ms IS NOT NULL
          ), aggregated AS (
            SELECT
              c.cohort_row_id,
              COUNT(*)::BIGINT AS all_timeout_count_90d,
              COUNT(*) FILTER (WHERE e.clearly_worse)::BIGINT AS clearly_losing_count_90d,
              COUNT(*) FILTER (WHERE NOT e.tournament_like)::BIGINT AS all_timeout_count_90d_no_tournament,
              COUNT(*) FILTER (WHERE e.clearly_worse AND NOT e.tournament_like)::BIGINT AS clearly_losing_count_90d_no_tournament
            FROM cohort c INNER JOIN events e
              ON e.recipient_user_id = c.recipient_user_id
             AND e.event_utc_ms > c.exposure_anchor_utc_ms
             AND e.event_utc_ms <= c.exposure_anchor_utc_ms + {HORIZON_90D_MS}
            GROUP BY c.cohort_row_id
          )
          SELECT
            c.cohort_row_id,
            COALESCE(a.all_timeout_count_90d, 0)::BIGINT AS all_timeout_count_90d,
            COALESCE(a.clearly_losing_count_90d, 0)::BIGINT AS clearly_losing_count_90d,
            COALESCE(a.all_timeout_count_90d_no_tournament, 0)::BIGINT AS all_timeout_count_90d_no_tournament,
            COALESCE(a.clearly_losing_count_90d_no_tournament, 0)::BIGINT AS clearly_losing_count_90d_no_tournament
          FROM cohort c LEFT JOIN aggregated a USING (cohort_row_id)
          ORDER BY c.cohort_row_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"""
        SELECT COUNT(*), COUNT(*) FILTER (WHERE all_timeout_count_90d>0),
               SUM(all_timeout_count_90d), SUM(clearly_losing_count_90d),
               SUM(clearly_losing_count_90d_no_tournament)
        FROM read_parquet({common.sql_literal(temporary)})
        """
    ).fetchone()
    connection.close()
    cohort_rows = int(pq.ParquetFile(cohort_index).metadata.num_rows)
    if qa[0] != cohort_rows or any(value is None for value in qa[1:]):
        raise RuntimeError(f"C6 event-cache row conservation failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "C6_LATER_TIMEOUT_EVENTS_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_sha256": common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": int(qa[0]),
        "recipients_with_any_later_timeout": int(qa[1]),
        "pooled_all_timeout_events": int(qa[2]),
        "pooled_clearly_losing_events": int(qa[3]),
        "pooled_clearly_losing_events_no_tournament": int(qa[4]),
        "treatment_field_read": False,
        "current_or_later_event_fields_read": [
            "disconnected_user_id", "api_last_move_at_ms", "clearly_worse",
            "tournament_like_event"
        ],
        "privacy": "PRIVATE ACCOUNT-LEVEL EVENT COUNTS; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c6_events", ignore_errors=True)
    return output, saved


def freeze_c6_gate(
    *, cohort_receipt: dict[str, Any], event_receipt: dict[str, Any],
    state: Path, config_sha256: str
) -> dict[str, Any]:
    path = state / "c6_support_gate_frozen_before_arm_split.json"
    decision = (
        int(event_receipt["recipients_with_any_later_timeout"]) >= C6_GATE_RECIPIENTS
        and int(event_receipt["pooled_clearly_losing_events"]) >= C6_GATE_CLEAR_EVENTS
    )
    payload = {
        "status": "C6_TREATMENT_BLIND_POOLED_SUPPORT_GATE_FROZEN",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "eligible_pooled_recipients": int(cohort_receipt["rows"]),
        "recipients_with_any_later_timeout": int(
            event_receipt["recipients_with_any_later_timeout"]
        ),
        "pooled_clearly_losing_timeout_events": int(
            event_receipt["pooled_clearly_losing_events"]
        ),
        "minimum_recipients_with_any_later_timeout": C6_GATE_RECIPIENTS,
        "minimum_pooled_clearly_losing_events": C6_GATE_CLEAR_EVENTS,
        "gate_pass": decision,
        "family_disposition": "RETAIN_C6_IN_HOLM_FAMILY_D" if decision else "DEMOTE_C6_TO_SECONDARY_AND_REMOVE_BEFORE_ARM_SPLIT",
        "treatment_specific_c6_outcomes_tabulated": False,
    }
    if path.is_file():
        saved = common.load_json(path)
        for key in (
            "config_sha256", "eligible_pooled_recipients",
            "recipients_with_any_later_timeout", "pooled_clearly_losing_timeout_events",
            "gate_pass", "family_disposition"
        ):
            if saved.get(key) != payload.get(key):
                raise RuntimeError(f"Frozen C6 support gate changed: {key}")
        return saved
    common.atomic_json(path, payload)
    return payload


def _expand_cache(path: Path, total_rows: int, fields: Sequence[str]) -> dict[str, Any]:
    _, np, _, pq = common.import_dependencies()
    table = pq.read_table(path, columns=["cohort_row_id", *fields])
    row_ids = common.arrow_numpy(table, "cohort_row_id")
    if np.any(row_ids < 0) or np.any(row_ids >= total_rows) or np.unique(row_ids).size != row_ids.size:
        raise RuntimeError(f"Invalid cohort row IDs in cache: {path}")
    output: dict[str, Any] = {"present": np.zeros(total_rows, dtype=bool)}
    output["present"][row_ids] = True
    for field in fields:
        values = common.arrow_numpy(table, field)
        expanded = np.zeros(total_rows, dtype=np.int64)
        expanded[row_ids] = values
        output[field] = expanded
    return output


def _arm_ratio(events: Any, games: Any, weights: Any, sample: Any) -> float | None:
    np = common.import_numpy()
    valid = np.asarray(sample, dtype=bool) & np.isfinite(weights) & (weights > 0)
    denominator = float(np.sum(weights[valid] * games[valid]))
    if denominator <= 0:
        return None
    return 1000.0 * float(np.sum(weights[valid] * events[valid])) / denominator


def estimate_c6(
    *, recipient: Path, core: Any, denominator_cache: Path, event_cache: Path,
    gate: dict[str, Any]
) -> dict[str, Any]:
    np = common.import_numpy()
    if not gate["gate_pass"]:
        return {
            "status": "C6_DEMOTED_SUPPORT_GATE_FAILED_NO_ARM_EFFECT_INSPECTED",
            "epistemic_label": "S",
            "holm_family_member": False,
            "support_gate": gate,
            "arm_specific_effect_estimated": False,
        }
    data = _load_recipient_minimal(recipient, core)
    support = core.common_support_weights(data)
    total_rows = data["cohort_row_id"].size
    denominator = _expand_cache(denominator_cache, total_rows, ["rated_games_90d"])
    events = _expand_cache(
        event_cache,
        total_rows,
        [
            "all_timeout_count_90d", "clearly_losing_count_90d",
            "all_timeout_count_90d_no_tournament",
            "clearly_losing_count_90d_no_tournament",
        ],
    )
    followup = data["a1_90d_followup_eligible"].astype(bool)
    first = data["first_ever_pair"].astype(bool) & data["arm_eligible"].astype(bool)
    full_sample = first & followup
    games = denominator["rated_games_90d"].astype(np.float64)
    clear = events["clearly_losing_count_90d"].astype(np.float64)
    all_timeout = events["all_timeout_count_90d"].astype(np.float64)
    clear_no_tournament = events["clearly_losing_count_90d_no_tournament"].astype(np.float64)
    all_no_tournament = events["all_timeout_count_90d_no_tournament"].astype(np.float64)
    data.update(
        {
            "c6_clear_rate_per_1000": common.rate_from_counts(clear, games, scale=1000),
            "c6_clear_rate_zero_coded_per_1000": np.where(
                games > 0, 1000.0 * clear / np.maximum(games, 1), 0.0
            ),
            "c6_clear_count": clear,
            "c6_all_timeout_rate_per_1000": common.rate_from_counts(
                all_timeout, games, scale=1000
            ),
            "c6_all_timeout_count": all_timeout,
            "c6_clear_share_of_timeouts": common.rate_from_counts(clear, all_timeout),
            "c6_rated_games_90d": games,
            "c6_any_timeout": (all_timeout > 0).astype(np.float64),
            "c6_any_clear_timeout": (clear > 0).astype(np.float64),
            "c6_clear_rate_no_tournament_per_1000": common.rate_from_counts(
                clear_no_tournament, games, scale=1000
            ),
            "c6_clear_count_no_tournament": clear_no_tournament,
            "c6_all_timeout_count_no_tournament": all_no_tournament,
            "c6_all_timeout_rate_no_tournament_per_1000": common.rate_from_counts(
                all_no_tournament, games, scale=1000
            ),
            "c6_clear_share_no_tournament": common.rate_from_counts(
                clear_no_tournament, all_no_tournament
            ),
        }
    )
    model_specs = [
        ("c6_clear_rate_per_1000", "C_primary_positive_rated_game_denominator", full_sample, False),
        ("c6_clear_count", "C_mandatory_unnormalized_count", full_sample, False),
        ("c6_rated_games_90d", "denominator_diagnostic", full_sample, False),
        ("c6_clear_rate_zero_coded_per_1000", "S_zero_coded_nonreturner_rate_contribution", full_sample, False),
        ("c6_all_timeout_rate_per_1000", "S_all_timeout_rate", full_sample, False),
        ("c6_all_timeout_count", "S_all_timeout_count", full_sample, False),
        ("c6_any_timeout", "S_any_timeout", full_sample, True),
        ("c6_any_clear_timeout", "S_any_clearly_losing_timeout", full_sample, True),
        ("c6_clear_share_of_timeouts", "S_clear_share_conditional_any_timeout", full_sample & (all_timeout > 0), False),
        ("c6_clear_rate_no_tournament_per_1000", "S_no_tournament_clear_rate", full_sample, False),
        ("c6_clear_count_no_tournament", "S_no_tournament_clear_count", full_sample, False),
        ("c6_all_timeout_rate_no_tournament_per_1000", "S_no_tournament_all_timeout_rate", full_sample, False),
        ("c6_clear_share_no_tournament", "S_no_tournament_clear_share", full_sample & (all_no_tournament > 0), False),
    ]
    models: list[dict[str, Any]] = []
    for outcome, estimand, sample, binary in model_specs:
        fitted = core.fit_recipient_outcome(
            data=data,
            support=support,
            outcome_name=outcome,
            sample=sample,
            estimand=estimand,
            state_conditioned=False,
            binary_outcome=binary,
        )
        fitted.update(
            {
                "analysis": "C6",
                "epistemic_label": "C" if estimand.startswith("C_primary") else "S",
                "holm_family_member": estimand.startswith("C_primary"),
                "effect_units": (
                    "events_per_1000_rated_games"
                    if "rate" in outcome and "share" not in outcome
                    else "outcome_units_per_recipient"
                ),
            }
        )
        models.append(fitted)
    treatment = data["received_mercy"].astype(bool)
    eligible = support["eligible"] & full_sample
    weights = support["weights"]
    ratio = {
        "mercy_clear_events_per_1000_weighted_rated_games": _arm_ratio(
            clear, games, weights, eligible & treatment
        ),
        "claimed_clear_events_per_1000_weighted_rated_games": _arm_ratio(
            clear, games, weights, eligible & ~treatment
        ),
        "mercy_all_timeouts_per_1000_weighted_rated_games": _arm_ratio(
            all_timeout, games, weights, eligible & treatment
        ),
        "claimed_all_timeouts_per_1000_weighted_rated_games": _arm_ratio(
            all_timeout, games, weights, eligible & ~treatment
        ),
    }
    if ratio["mercy_clear_events_per_1000_weighted_rated_games"] is not None and ratio["claimed_clear_events_per_1000_weighted_rated_games"] is not None:
        ratio["mercy_minus_claimed_clear_ratio_difference_per_1000"] = (
            ratio["mercy_clear_events_per_1000_weighted_rated_games"]
            - ratio["claimed_clear_events_per_1000_weighted_rated_games"]
        )
    denominator_arms = {}
    for label, mask in (("mercy", eligible & treatment), ("claimed", eligible & ~treatment)):
        denominator_arms[label] = common.clustered_weighted_mean(
            games, weights, data["exposure_chooser_user_id"], mask
        )
    primary = next(row for row in models if row["estimand"] == "C_primary_positive_rated_game_denominator")
    return {
        "status": "C6_ESTIMATED_SUPPORT_GATE_PASSED",
        "epistemic_label": "C",
        "holm_family_member": True,
        "support_gate": gate,
        "primary": primary,
        "models": models,
        "ratio_of_sums_diagnostic": ratio,
        "denominator_arm_means": denominator_arms,
        "sample": {
            "first_pair_followup_rows_before_common_support": int(np.count_nonzero(full_sample)),
            "common_support_followup_rows": int(np.count_nonzero(eligible)),
            "positive_rated_game_denominator_rows": int(np.count_nonzero(eligible & (games > 0))),
            "zero_rated_game_denominator_rows": int(np.count_nonzero(eligible & (games == 0))),
        },
    }


def build_c10_window_cache(
    *, recipient: Path, existing_a2_cache: Path, stage07_paths: Sequence[Path],
    state: Path, threads: int, memory_limit: str, config_sha256: str
) -> tuple[Path, dict[str, Any]]:
    duckdb, _, _, pq = common.import_dependencies()
    output = state / "c10_windows_7_14_private.parquet"
    receipt = state / "c10_windows_7_14_receipt.json"
    if output.is_file() and receipt.is_file():
        saved = common.load_json(receipt)
        if (
            saved.get("config_sha256") != config_sha256
            or saved.get("output_sha256") != common.sha256_file(output)
            or saved.get("rows") != int(pq.ParquetFile(output).metadata.num_rows)
        ):
            raise RuntimeError("C10 window checkpoint mismatch")
        return output, saved
    if output.exists() or receipt.exists():
        raise RuntimeError("Partial C10 window checkpoint exists")
    connection = duckdb.connect()
    common.configure_duckdb(
        connection,
        threads=threads,
        memory_limit=memory_limit,
        temp_directory=state / "duckdb_temp/c10_windows",
    )
    temporary = output.with_name(output.name + f".tmp.{uuid.uuid4().hex}")
    connection.execute(
        f"""
        COPY (
          WITH exposure AS (
            SELECT
              CAST(r.cohort_row_id AS BIGINT) AS cohort_row_id,
              CAST(r.recipient_user_id AS BIGINT) AS recipient_user_id,
              CAST(r.exposure_anchor_utc_ms AS BIGINT) AS exposure_anchor_utc_ms,
              (a.cohort_row_id IS NOT NULL) AS common_90d_window,
              CAST(r.exposure_anchor_utc_ms AS BIGINT) >= {common.PANEL_START_MS + 7 * common.DAY_MS}
                AND CAST(r.exposure_anchor_utc_ms AS BIGINT) < {common.PANEL_END_EXCLUSIVE_MS - 7 * common.DAY_MS}
                AS horizon_specific_7d,
              CAST(r.exposure_anchor_utc_ms AS BIGINT) >= {common.PANEL_START_MS + 14 * common.DAY_MS}
                AND CAST(r.exposure_anchor_utc_ms AS BIGINT) < {common.PANEL_END_EXCLUSIVE_MS - 14 * common.DAY_MS}
                AS horizon_specific_14d
            FROM read_parquet({common.sql_literal(recipient)}) r
            LEFT JOIN read_parquet({common.sql_literal(existing_a2_cache)}) a USING (cohort_row_id)
          ), choices AS (
            SELECT
              CAST(chooser_user_id AS BIGINT) AS recipient_user_id,
              CAST(api_last_move_at_ms AS BIGINT) AS choice_utc_ms,
              CAST(kind_draw AS BIGINT) AS kind_draw
            FROM read_parquet({common.path_list_literal(stage07_paths)}, union_by_name=true)
            WHERE CAST(fair_competitive AS BOOLEAN)
              AND chooser_user_id IS NOT NULL AND api_last_move_at_ms IS NOT NULL
          ), joined AS (
            SELECT e.cohort_row_id, c.choice_utc_ms - e.exposure_anchor_utc_ms AS delta_ms,
                   c.kind_draw
            FROM exposure e INNER JOIN choices c
              ON c.recipient_user_id = e.recipient_user_id
             AND c.choice_utc_ms >= e.exposure_anchor_utc_ms - {14 * common.DAY_MS}
             AND c.choice_utc_ms <= e.exposure_anchor_utc_ms + {14 * common.DAY_MS}
             AND c.choice_utc_ms <> e.exposure_anchor_utc_ms
          ), aggregated AS (
            SELECT cohort_row_id,
              COUNT(*) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{7 * common.DAY_MS})::BIGINT AS pre_7_n,
              SUM(kind_draw) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{7 * common.DAY_MS})::BIGINT AS pre_7_k,
              COUNT(*) FILTER (WHERE delta_ms > 0 AND delta_ms <= {7 * common.DAY_MS})::BIGINT AS post_7_n,
              SUM(kind_draw) FILTER (WHERE delta_ms > 0 AND delta_ms <= {7 * common.DAY_MS})::BIGINT AS post_7_k,
              COUNT(*) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{14 * common.DAY_MS})::BIGINT AS pre_14_n,
              SUM(kind_draw) FILTER (WHERE delta_ms < 0 AND delta_ms >= -{14 * common.DAY_MS})::BIGINT AS pre_14_k,
              COUNT(*) FILTER (WHERE delta_ms > 0 AND delta_ms <= {14 * common.DAY_MS})::BIGINT AS post_14_n,
              SUM(kind_draw) FILTER (WHERE delta_ms > 0 AND delta_ms <= {14 * common.DAY_MS})::BIGINT AS post_14_k
            FROM joined GROUP BY cohort_row_id
          )
          SELECT e.cohort_row_id, e.common_90d_window, e.horizon_specific_7d,
                 e.horizon_specific_14d,
                 COALESCE(a.pre_7_n,0)::BIGINT AS pre_7_n,
                 COALESCE(a.pre_7_k,0)::BIGINT AS pre_7_k,
                 COALESCE(a.post_7_n,0)::BIGINT AS post_7_n,
                 COALESCE(a.post_7_k,0)::BIGINT AS post_7_k,
                 COALESCE(a.pre_14_n,0)::BIGINT AS pre_14_n,
                 COALESCE(a.pre_14_k,0)::BIGINT AS pre_14_k,
                 COALESCE(a.post_14_n,0)::BIGINT AS post_14_n,
                 COALESCE(a.post_14_k,0)::BIGINT AS post_14_k
          FROM exposure e LEFT JOIN aggregated a USING (cohort_row_id)
          ORDER BY e.cohort_row_id
        ) TO {common.sql_literal(temporary)}
          (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)
        """
    )
    qa = connection.execute(
        f"SELECT COUNT(*), SUM(CAST(common_90d_window AS BIGINT)), SUM(CAST(horizon_specific_7d AS BIGINT)), SUM(CAST(horizon_specific_14d AS BIGINT)) FROM read_parquet({common.sql_literal(temporary)})"
    ).fetchone()
    connection.close()
    if int(qa[0]) != common.EXPECTED_RECIPIENT_ROWS or int(qa[1]) != EXPECTED_A2_CACHE_ROWS:
        raise RuntimeError(f"C10 window row QA failed: {qa}")
    os.replace(temporary, output)
    saved = {
        "status": "C10_WINDOWS_7_14_PRIVATE_OK",
        "created_utc": common.utc_now(),
        "config_sha256": config_sha256,
        "output_path": str(output),
        "output_sha256": common.sha256_file(output),
        "output_bytes": output.stat().st_size,
        "rows": int(qa[0]),
        "common_90d_window_rows": int(qa[1]),
        "horizon_specific_7d_rows": int(qa[2]),
        "horizon_specific_14d_rows": int(qa[3]),
        "privacy": "PRIVATE ACCOUNT-LEVEL COUNTS; DO NOT PUBLISH",
    }
    common.atomic_json(receipt, saved)
    shutil.rmtree(state / "duckdb_temp/c10_windows", ignore_errors=True)
    return output, saved


def _load_c10_windows(
    *, extension: Path, existing: Path, total_rows: int
) -> dict[str, Any]:
    np = common.import_numpy()
    _, _, _, pq = common.import_dependencies()
    ext = pq.read_table(extension)
    row_id = common.arrow_numpy(ext, "cohort_row_id")
    if not np.array_equal(row_id, np.arange(total_rows, dtype=np.int64)):
        raise RuntimeError("C10 extension row order changed")
    output: dict[str, Any] = {}
    for field in ext.column_names:
        if field == "cohort_row_id":
            continue
        output[field] = common.arrow_numpy(ext, field)
    old = pq.read_table(existing)
    old_rows = common.arrow_numpy(old, "cohort_row_id")
    for field in old.column_names:
        if field == "cohort_row_id":
            continue
        expanded = np.zeros(total_rows, dtype=np.int64)
        expanded[old_rows] = common.arrow_numpy(old, field)
        output[field] = expanded
    return output


def _current_state_controls(data: dict[str, Any], core: Any) -> dict[str, Any]:
    np = common.import_numpy()
    controls: dict[str, Any] = {}
    for field in core.EXPOSURE_CONTROLS:
        raw = np.asarray(data[field], dtype=np.float64)
        controls[field] = raw
        controls[field + "_squared"] = raw * raw
    return controls


def estimate_c10(
    *, recipient: Path, core: Any, support_gate: dict[str, Any], c6: dict[str, Any],
    extension_cache: Path, existing_a2_cache: Path, prior_results_root: Path
) -> dict[str, Any]:
    np = common.import_numpy()
    data = _load_recipient_minimal(recipient, core)
    support = core.common_support_weights(data)
    windows = _load_c10_windows(
        extension=extension_cache,
        existing=existing_a2_cache,
        total_rows=data["cohort_row_id"].size,
    )
    treatment = data["received_mercy"].astype(bool)
    claimed = ~treatment
    weights = support["weights"]
    clusters = data["exposure_chooser_user_id"]
    decay_rows: list[dict[str, Any]] = []
    personal_rows: list[dict[str, Any]] = []
    controls_all = _current_state_controls(data, core)
    for horizon in (7, 14, 30, 60, 90):
        pre_n = windows[f"pre_{horizon}_n"]
        pre_k = windows[f"pre_{horizon}_k"]
        post_n = windows[f"post_{horizon}_n"]
        post_k = windows[f"post_{horizon}_k"]
        pre_rate = common.rate_from_counts(pre_k, pre_n)
        post_rate = common.rate_from_counts(post_k, post_n)
        change = post_rate - pre_rate
        definitions = [("common_90d_endpoint_cohort", windows["common_90d_window"].astype(bool))]
        if horizon in (7, 14):
            definitions.append(
                (f"horizon_specific_{horizon}d_endpoint_cohort", windows[f"horizon_specific_{horizon}d"].astype(bool))
            )
        for sample_label, endpoint in definitions:
            for minimum in (1, 4):
                sample = (
                    endpoint & support["eligible"] & (pre_n >= minimum)
                    & (post_n >= minimum) & np.isfinite(change)
                )
                for arm_label, mask in (
                    ("claimed_against", sample & claimed),
                    ("mercy_received", sample & treatment),
                    ("pooled", sample),
                ):
                    moments = common.clustered_weighted_mean(
                        change, weights, clusters, mask
                    )
                    decay_rows.append(
                        {
                            "analysis": "C10_decay_clock",
                            "epistemic_label": "X",
                            "sample_definition": sample_label,
                            "arm": arm_label,
                            "horizon_days_each_side": horizon,
                            "minimum_fair_opportunities_each_side": minimum,
                            **moments,
                            "mean_change_percentage_points": 100.0 * moments["mean"],
                            "standard_error_percentage_points": 100.0 * moments["standard_error"],
                            "weighted_pre_kind_rate": float(np.average(pre_rate[mask], weights=weights[mask])),
                            "weighted_post_kind_rate": float(np.average(post_rate[mask], weights=weights[mask])),
                            "causal_claim": False,
                        }
                    )
                model_sample = sample
                indices = np.flatnonzero(model_sample)
                if indices.size >= 1_000:
                    fitted = common.fit_hdfe_cluster(
                        outcome=change[indices],
                        exposures={"mercy_minus_claim": treatment[indices].astype(float)},
                        numeric_controls={name: values[indices] for name, values in controls_all.items()},
                        fixed_effects={
                            "exposure_cell": data["exposure_cell_code"][indices],
                            "exposure_month": data["exposure_month_code"][indices],
                        },
                        clusters=clusters[indices],
                        row_ids=data["cohort_row_id"][indices],
                        weights=weights[indices],
                        specification={
                            "model": "C10_decay_mercy_minus_claim",
                            "epistemic_label": "X",
                            "sample_definition": sample_label,
                            "horizon_days_each_side": horizon,
                            "minimum_fair_opportunities_each_side": minimum,
                        },
                    )
                    result = fitted["results"][0]
                    decay_rows.append(
                        {
                            **{key: value for key, value in fitted.items() if key != "results"},
                            "arm": "mercy_minus_claim_adjusted",
                            **result,
                            "effect_percentage_points": 100.0 * result["coefficient"],
                            "standard_error_percentage_points": 100.0 * result["standard_error"],
                            "causal_claim": False,
                        }
                    )
                propensity = data["encouragement_pair_excluded_propensity"].astype(float)
                prop_support = data["encouragement_prior_pair_excluded_n"] >= 10
                personal_sample = sample & prop_support & np.isfinite(propensity)
                if np.count_nonzero(personal_sample & claimed) >= 1_000:
                    claim_idx = np.flatnonzero(personal_sample & claimed)
                    slope = common.fit_hdfe_cluster(
                        outcome=change[claim_idx],
                        exposures={"denier_pair_excluded_propensity": propensity[claim_idx]},
                        numeric_controls={name: values[claim_idx] for name, values in controls_all.items()},
                        fixed_effects={
                            "exposure_cell": data["exposure_cell_code"][claim_idx],
                            "exposure_month": data["exposure_month_code"][claim_idx],
                        },
                        clusters=clusters[claim_idx],
                        row_ids=data["cohort_row_id"][claim_idx],
                        weights=weights[claim_idx],
                        specification={
                            "model": "C10_personal_slight_claimed_arm_slope",
                            "epistemic_label": "X",
                            "sample_definition": sample_label,
                            "horizon_days_each_side": horizon,
                            "minimum_fair_opportunities_each_side": minimum,
                        },
                    )
                    result = slope["results"][0]
                    personal_rows.append(
                        {
                            **{key: value for key, value in slope.items() if key != "results"},
                            **result,
                            "effect_pp_change_per_1pp_denier_propensity": result["coefficient"],
                            "se_pp_change_per_1pp_denier_propensity": result["standard_error"],
                            "causal_claim": False,
                        }
                    )
                if np.count_nonzero(personal_sample) >= 1_000:
                    idx = np.flatnonzero(personal_sample)
                    centered = propensity[idx] - float(np.average(propensity[idx], weights=weights[idx]))
                    claim_float = claimed[idx].astype(float)
                    interaction = claim_float * centered
                    interaction_fit = common.fit_hdfe_cluster(
                        outcome=change[idx],
                        exposures={"claim_by_centered_denier_propensity": interaction},
                        numeric_controls={
                            "claimed_main": claim_float,
                            "denier_propensity_main": centered,
                            **{name: values[idx] for name, values in controls_all.items()},
                        },
                        fixed_effects={
                            "exposure_cell": data["exposure_cell_code"][idx],
                            "exposure_month": data["exposure_month_code"][idx],
                        },
                        clusters=clusters[idx],
                        row_ids=data["cohort_row_id"][idx],
                        weights=weights[idx],
                        specification={
                            "model": "C10_personal_slight_pooled_interaction",
                            "epistemic_label": "X",
                            "sample_definition": sample_label,
                            "horizon_days_each_side": horizon,
                            "minimum_fair_opportunities_each_side": minimum,
                        },
                    )
                    result = interaction_fit["results"][0]
                    personal_rows.append(
                        {
                            **{key: value for key, value in interaction_fit.items() if key != "results"},
                            **result,
                            "interaction_pp_change_per_1pp_denier_propensity": result["coefficient"],
                            "se_pp_change_per_1pp_denier_propensity": result["standard_error"],
                            "causal_claim": False,
                        }
                    )
    # Retain the authenticated pre-existing 30/60/90 output as an explicit cross-check.
    prior_csv = prior_results_root / "results/a2_prepost_arm_paths.csv"
    prior_rows: list[dict[str, Any]] = []
    with prior_csv.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row.get("path") == "claimed_against" and int(row["horizon_days_each_side"]) in (30, 60, 90):
                prior_rows.append(row)
    crosscheck: list[dict[str, Any]] = []
    for prior in prior_rows:
        horizon = int(prior["horizon_days_each_side"])
        minimum = int(prior["minimum_opportunities_each_side"])
        reproduced = next(
            row for row in decay_rows
            if row.get("arm") == "claimed_against"
            and row.get("sample_definition") == "common_90d_endpoint_cohort"
            and row.get("horizon_days_each_side") == horizon
            and row.get("minimum_fair_opportunities_each_side") == minimum
        )
        exact_integer_fields = ("rows", "clusters")
        numeric_fields = (
            "mean", "standard_error", "weight_sum",
            "weighted_pre_kind_rate", "weighted_post_kind_rate",
        )
        integer_match = all(
            int(prior[field]) == int(reproduced[field])
            for field in exact_integer_fields
        )
        numeric_match = all(
            math.isclose(
                float(prior[field]), float(reproduced[field]),
                rel_tol=1e-12, abs_tol=1e-15,
            )
            for field in numeric_fields
        )
        crosscheck.append(
            {
                "horizon_days_each_side": horizon,
                "minimum_opportunities_each_side": minimum,
                "integer_fields_match": integer_match,
                "numeric_fields_match": numeric_match,
                "pass": integer_match and numeric_match,
            }
        )
    if len(crosscheck) != 6 or not all(row["pass"] for row in crosscheck):
        raise RuntimeError(f"C10 failed exact certified 30/60/90 reproduction: {crosscheck}")
    behavioral = {
        "support_gate": support_gate,
        "c6_status": c6["status"],
        "claimed_arm_is_c6_control_arm": True,
        "c6_models": [
            row for row in c6.get("models", [])
            if row.get("outcome") in {
                "c6_clear_rate_per_1000", "c6_clear_count",
                "c6_all_timeout_rate_per_1000", "c6_all_timeout_count",
                "c6_clear_share_of_timeouts", "c6_rated_games_90d",
                "c6_any_timeout",
                "c6_any_clear_timeout", "c6_clear_rate_no_tournament_per_1000",
                "c6_clear_count_no_tournament",
                "c6_all_timeout_rate_no_tournament_per_1000",
                "c6_clear_share_no_tournament",
            }
        ],
        "causal_claim": False,
    }
    return {
        "status": "C10_ESTIMATED",
        "epistemic_label": "X",
        "decay_clock": decay_rows,
        "personal_slight": personal_rows,
        "behavioral_channel": behavioral,
        "certified_prior_30_60_90_claimed_rows": prior_rows,
        "certified_prior_30_60_90_reproduction": crosscheck,
    }


def execute(
    *, project: Path, package_root: Path, state: Path, public_stage: Path,
    core: Any, threads: int, memory_limit: str, workers: int, batch_rows: int,
    config_sha256: str
) -> dict[str, Any]:
    started = time.time()
    recipient = project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE/recipient_with_chronology_private.parquet"
    stage07 = project / "derived/replication/analysis_panel_24m_sf100k"
    stage_paths = common.stage07_paths(stage07)
    chronology_manifest = project / "output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z/chronology_input_manifest.tsv"
    remaining_state = project / "derived/replication/remaining_dynamic_completion_v100_PRIVATE"
    existing_a2 = remaining_state / "a2_account_windows_private.parquet"
    prior_results = project / "output/remaining_dynamic_completion_v100/20260823T141145Z"
    if common.sha256_file(recipient) != EXPECTED_RECIPIENT_SHA256:
        raise RuntimeError("C6/C10 recipient authority hash mismatch")
    if common.sha256_file(existing_a2) != EXPECTED_A2_CACHE_SHA256:
        raise RuntimeError("C10 A2 cache authority hash mismatch")
    if common.sha256_file(prior_results / "_SUCCESS.json") != EXPECTED_REMAINING_SUCCESS_SHA256:
        raise RuntimeError("C10 prior aggregate authority hash mismatch")
    if common.sha256_file(stage07 / "_SUCCESS.json") != EXPECTED_STAGE07_SUCCESS_SHA256:
        raise RuntimeError("C6/C10 Stage 07 authority hash mismatch")
    if common.sha256_file(chronology_manifest) != EXPECTED_CHRONOLOGY_MANIFEST_SHA256:
        raise RuntimeError("C6 chronology manifest authority hash mismatch")
    cohort_index, cohort_receipt = build_c6_preoutcome_index(
        recipient=recipient, core=core, state=state, config_sha256=config_sha256
    )
    denominator, denominator_receipt = build_c6_denominator_cache(
        cohort_index=cohort_index,
        chronology_manifest=chronology_manifest,
        state=state,
        workers=workers,
        batch_rows=batch_rows,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    event_cache, event_receipt = build_c6_event_cache(
        cohort_index=cohort_index,
        stage07_paths=stage_paths,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    gate = freeze_c6_gate(
        cohort_receipt=cohort_receipt,
        event_receipt=event_receipt,
        state=state,
        config_sha256=config_sha256,
    )
    print(
        "C6_TREATMENT_BLIND_GATE "
        f"recipients_any_timeout={gate['recipients_with_any_later_timeout']:,} "
        f"clear_events={gate['pooled_clearly_losing_timeout_events']:,} "
        f"pass={gate['gate_pass']}",
        flush=True,
    )
    c6 = estimate_c6(
        recipient=recipient,
        core=core,
        denominator_cache=denominator,
        event_cache=event_cache,
        gate=gate,
    )
    public_stage.mkdir(parents=True, exist_ok=True)
    common.atomic_json(public_stage / "c6_support_gate.json", gate)
    common.atomic_json(public_stage / "c6_results.json", c6)
    if c6.get("models"):
        common.write_csv(public_stage / "c6_models.csv", c6["models"])
    print(f"C6_PUBLIC_AGGREGATES_CHECKPOINTED status={c6['status']}", flush=True)
    extension, extension_receipt = build_c10_window_cache(
        recipient=recipient,
        existing_a2_cache=existing_a2,
        stage07_paths=stage_paths,
        state=state,
        threads=threads,
        memory_limit=memory_limit,
        config_sha256=config_sha256,
    )
    c10 = estimate_c10(
        recipient=recipient,
        core=core,
        support_gate=gate,
        c6=c6,
        extension_cache=extension,
        existing_a2_cache=existing_a2,
        prior_results_root=prior_results,
    )
    common.atomic_json(public_stage / "c10_results.json", c10)
    common.write_csv(public_stage / "c10_decay_clock.csv", c10["decay_clock"])
    if c10["personal_slight"]:
        common.write_csv(public_stage / "c10_personal_slight.csv", c10["personal_slight"])
    summary = {
        "status": "CAMPAIGN1_C6_C10_V100_OK",
        "created_utc": common.utc_now(),
        "runtime_seconds": time.time() - started,
        "C6": {
            "status": c6["status"],
            "gate_pass": gate["gate_pass"],
            "holm_family_member": c6.get("holm_family_member"),
            "primary": c6.get("primary"),
        },
        "C10": {
            "status": c10["status"],
            "decay_rows": len(c10["decay_clock"]),
            "personal_slight_rows": len(c10["personal_slight"]),
        },
        "private_checkpoints": {
            "cohort": {k: v for k, v in cohort_receipt.items() if "path" not in k},
            "denominator": {k: v for k, v in denominator_receipt.items() if "path" not in k},
            "events": {k: v for k, v in event_receipt.items() if "path" not in k},
            "c10_windows": {k: v for k, v in extension_receipt.items() if "path" not in k},
        },
        "account_level_output": False,
        "api_requests": 0,
        "profile_or_patron_reads": 0,
    }
    common.atomic_json(public_stage / "summary.json", summary)
    return summary


def self_test() -> None:
    np = common.import_numpy()
    lookup = np.full(20, -1, dtype=np.int32)
    lookup[[3, 7]] = [0, 1]
    anchors = np.array([1_000, 2_000], dtype=np.int64)
    counts = np.zeros(2, dtype=np.int32)
    hits = _update_future_counts(
        event_ids=np.array([3, 3, 7, 7, 8]),
        event_times=np.array([999, 1001, 2001, 2000 + HORIZON_90D_MS + 1, 5_000]),
        lookup=lookup,
        anchors=anchors,
        counts=counts,
        np=np,
    )
    if hits != 2 or not np.array_equal(counts, [1, 1]):
        raise RuntimeError("C6 future-game counter self-test failed")
    test_root = Path(os.environ.get("TMPDIR", "/tmp")) / f"c6_gate_test_{uuid.uuid4().hex}"
    gate = freeze_c6_gate(
        cohort_receipt={"rows": 10_000},
        event_receipt={
            "recipients_with_any_later_timeout": 4_000,
            "pooled_clearly_losing_events": 4_000,
        },
        state=test_root,
        config_sha256="synthetic",
    )
    if not gate["gate_pass"]:
        raise RuntimeError("C6 gate boundary self-test failed")
    shutil.rmtree(test_root, ignore_errors=True)
    print("CAMPAIGN1_C6_C10_SELF_TEST_OK")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
