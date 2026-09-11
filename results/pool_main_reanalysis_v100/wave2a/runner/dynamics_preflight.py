#!/usr/bin/env python3
"""Inventory chronology-dependent authorities and freeze new-sample support counts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from runner import common


EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = (
    "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
)
EXPECTED_CHRONOLOGY_FILES = 852
EXPECTED_CHRONOLOGY_ROWS = 7_763_847_245
USER_SEED = 2026082202
PAIR_SEED = 2026082203
SAMPLE_DENOMINATOR = 50
DAY_MS = 86_400_000
HORIZON_90D_MS = 90 * DAY_MS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--wave1-public", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--private-temp", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="12GB")
    return parser.parse_args()


def quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def path_list(paths: list[Path]) -> str:
    return "[" + ",".join(quote(path) for path in paths) + "]"


def receipt_probe(path: Path, *, status: str | None = None, sha256: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.is_file()}
    if not path.is_file():
        result["status"] = "MISSING"
        return result
    result.update({"bytes": path.stat().st_size, "sha256": common.sha256_file(path)})
    try:
        value = common.load_json(path)
        result["observed_status"] = value.get("status")
    except Exception as exc:
        result.update({"status": "INVALID_JSON", "error": str(exc)})
        return result
    failures = []
    if status is not None and result["observed_status"] != status:
        failures.append("status")
    if sha256 is not None and result["sha256"] != sha256:
        failures.append("sha256")
    result["status"] = "AUTHENTICATED_OK" if not failures else "AUTHORITY_MISMATCH"
    result["failures"] = failures
    return result


def authenticate_wave1(project: Path, wave1: Path, fingerprint: str) -> dict[str, Any]:
    authority = common.load_json(common.PACKAGE_ROOT / "authority/WAVE1_AUTHORITY.json")
    modules: dict[str, Any] = {}
    for name, spec in authority["modules"].items():
        path = wave1 / spec["relative_path"]
        probe = receipt_probe(path, status=spec["status"], sha256=spec["sha256"])
        if probe["status"] == "AUTHENTICATED_OK":
            value = common.load_json(path)
            if (value.get("sample_authority") or {}).get("fingerprint") != fingerprint:
                probe["status"] = "SAMPLE_FINGERPRINT_MISMATCH"
        modules[name] = probe
    return {
        "status": (
            "POOL_MAIN_WAVE1_INPUTS_AUTHENTICATED_OK"
            if all(row["status"] == "AUTHENTICATED_OK" for row in modules.values())
            else "POOL_MAIN_WAVE1_INPUTS_BLOCKED"
        ),
        "root": str(wave1),
        "modules": modules,
    }


def chronology_probe(project: Path) -> dict[str, Any]:
    manifest = (
        project
        / "output/dynamic_prosociality_a3_chronology_gate_v100"
        / "20260821T234626Z/chronology_input_manifest.tsv"
    )
    result: dict[str, Any] = {"manifest": str(manifest), "exists": manifest.is_file()}
    if not manifest.is_file():
        return {**result, "status": "CHRONOLOGY_MANIFEST_MISSING"}
    digest = common.sha256_file(manifest)
    result["manifest_sha256"] = digest
    if digest != EXPECTED_CHRONOLOGY_MANIFEST_SHA256:
        return {**result, "status": "CHRONOLOGY_MANIFEST_SHA256_MISMATCH"}
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    total_rows = sum(int(row["rows"]) for row in rows)
    missing = []
    size_mismatch = []
    ordering_failures = []
    for index, row in enumerate(rows):
        if int(row["file_index"]) != index:
            ordering_failures.append(index)
        candidate = Path(row["path"])
        if not candidate.is_file():
            missing.append(str(candidate))
        elif candidate.stat().st_size != int(row["bytes"]):
            size_mismatch.append(str(candidate))
    result.update(
        {
            "files": len(rows),
            "rows": total_rows,
            "missing_files": len(missing),
            "size_mismatches": len(size_mismatch),
            "ordering_failures": len(ordering_failures),
            "utc_ms_min": min(int(row["utc_ms_min"]) for row in rows if row["utc_ms_min"]),
            "utc_ms_max": max(int(row["utc_ms_max"]) for row in rows if row["utc_ms_max"]),
        }
    )
    valid = (
        len(rows) == EXPECTED_CHRONOLOGY_FILES
        and total_rows == EXPECTED_CHRONOLOGY_ROWS
        and not missing
        and not size_mismatch
        and not ordering_failures
    )
    result["status"] = "CANONICAL_CHRONOLOGY_MANIFEST_AUTHENTICATED_OK" if valid else "CANONICAL_CHRONOLOGY_BLOCKED"
    if missing:
        result["first_missing_files"] = missing[:10]
    if size_mismatch:
        result["first_size_mismatches"] = size_mismatch[:10]
    return result


def directory_probe(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if not path.exists():
        result["status"] = "MISSING"
        return result
    if path.is_file():
        return {
            **result,
            "status": "PRESENT_NOT_CURRENT",
            "type": "file",
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        }
    parquets = list(path.rglob("*.parquet"))
    receipts = list(path.rglob("*.json"))
    result.update(
        {
            "status": "PRESENT_NOT_CURRENT",
            "type": "directory",
            "parquet_files": len(parquets),
            "json_receipts": len(receipts),
            "bytes_shallow": sum(item.stat().st_size for item in path.iterdir() if item.is_file()),
        }
    )
    return result


def support_counts(auth: dict[str, Any], temp: Path, threads: int, memory_limit: str) -> dict[str, Any]:
    import duckdb

    paths = [Path(row["path"]) for row in auth["month_records"]]
    temp.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute(f"SET threads={int(threads)}")
    connection.execute(f"SET memory_limit={quote(memory_limit)}")
    connection.execute(f"SET temp_directory={quote(temp)}")
    connection.execute("SET preserve_insertion_order=false")
    source = path_list(paths)
    panel_end = int(
        connection.execute(
            f"SELECT MAX(CAST(api_last_move_at_ms AS BIGINT)) FROM read_parquet({source}, union_by_name=true)"
        ).fetchone()[0]
    )
    first = connection.execute(
        f"""
        WITH ranked AS (
          SELECT
            disconnected_username_norm,
            CAST(disconnected_user_id AS BIGINT) AS recipient_user_id,
            CAST(api_last_move_at_ms AS BIGINT) AS anchor_ms,
            CAST(kind_draw AS BOOLEAN) AS received_mercy,
            CAST(timeout_chooser_win AS BOOLEAN) AS claimed_win,
            CAST(timeout_draw_no_mating_material AS BOOLEAN) AS no_mating_draw,
            CAST(timeout_chooser_loss AS BOOLEAN) AS chooser_loss,
            ROW_NUMBER() OVER (
              PARTITION BY disconnected_username_norm
              ORDER BY utc_ms, archive_ordinal, game_id
            ) AS exposure_rank
          FROM read_parquet({source}, union_by_name=true)
          WHERE CAST(fair_competitive AS BOOLEAN)
            AND NOT CAST(tournament_like_event AS BOOLEAN)
            AND disconnected_username_norm IS NOT NULL
            AND trim(disconnected_username_norm) <> ''
        ), firsts AS (
          SELECT * FROM ranked WHERE exposure_rank=1
        )
        SELECT
          COUNT(*)::BIGINT,
          COUNT(DISTINCT disconnected_username_norm)::BIGINT,
          COUNT(DISTINCT recipient_user_id)::BIGINT,
          SUM(CAST(received_mercy AS BIGINT))::BIGINT,
          SUM(CAST(claimed_win AS BIGINT))::BIGINT,
          SUM(CAST(no_mating_draw AS BIGINT))::BIGINT,
          SUM(CAST(chooser_loss AS BIGINT))::BIGINT,
          COUNT(*) FILTER (
            WHERE received_mercy IS NULL OR claimed_win IS NULL
               OR no_mating_draw IS NULL OR chooser_loss IS NULL
               OR CAST(received_mercy AS INTEGER)+CAST(claimed_win AS INTEGER)
                  +CAST(no_mating_draw AS INTEGER)+CAST(chooser_loss AS INTEGER) <> 1
          )::BIGINT,
          COUNT(*) FILTER (WHERE anchor_ms IS NULL OR anchor_ms <= 0)::BIGINT,
          COUNT(*) FILTER (WHERE anchor_ms + {HORIZON_90D_MS} <= {panel_end})::BIGINT,
          MIN(anchor_ms)::BIGINT,
          MAX(anchor_ms)::BIGINT
        FROM firsts
        """
    ).fetchone()
    b1 = connection.execute(
        f"""
        WITH chooser AS (
          SELECT chooser_username_norm,
                 COUNT(*)::BIGINT AS n,
                 SUM(CAST(kind_draw AS BIGINT))::BIGINT AS k
          FROM read_parquet({source}, union_by_name=true)
          WHERE CAST(fair_competitive AS BOOLEAN)
            AND chooser_username_norm IS NOT NULL
            AND trim(chooser_username_norm) <> ''
            AND kind_draw IS NOT NULL
          GROUP BY chooser_username_norm
          HAVING COUNT(*) >= 4
             AND SUM(CAST(kind_draw AS BIGINT)) >= 2
             AND SUM(CAST(kind_draw AS BIGINT)) < COUNT(*)
        )
        SELECT COUNT(*)::BIGINT, SUM(n)::BIGINT, SUM(k)::BIGINT,
               MIN(n)::BIGINT, MAX(n)::BIGINT, MIN(k)::BIGINT, MAX(k)::BIGINT
        FROM chooser
        """
    ).fetchone()
    target = connection.execute(
        f"""
        WITH fair AS (
          SELECT CAST(game_id AS VARCHAR) AS game_id,
                 CAST(chooser_user_id AS BIGINT) AS chooser_id,
                 CAST(disconnected_user_id AS BIGINT) AS opponent_id,
                 hash(CAST(chooser_user_id AS BIGINT), {USER_SEED}) % {SAMPLE_DENOMINATOR}=0 AS user_sample,
                 hash(
                   LEAST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
                   GREATEST(CAST(chooser_user_id AS BIGINT), CAST(disconnected_user_id AS BIGINT)),
                   {PAIR_SEED}
                 ) % {SAMPLE_DENOMINATOR}=0 AS pair_sample
          FROM read_parquet({source}, union_by_name=true)
          WHERE CAST(fair_competitive AS BOOLEAN)
            AND chooser_user_id IS NOT NULL AND disconnected_user_id IS NOT NULL
            AND CAST(chooser_user_id AS BIGINT) <> CAST(disconnected_user_id AS BIGINT)
        )
        SELECT
          COUNT(*) FILTER (WHERE user_sample OR pair_sample)::BIGINT,
          COUNT(*) FILTER (WHERE user_sample)::BIGINT,
          COUNT(*) FILTER (WHERE pair_sample)::BIGINT,
          COUNT(DISTINCT game_id) FILTER (WHERE user_sample OR pair_sample)::BIGINT,
          COUNT(DISTINCT chooser_id) FILTER (WHERE user_sample)::BIGINT
        FROM fair
        """
    ).fetchone()
    short_rows = int(
        connection.execute(
            f"SELECT COUNT(*) FROM read_parquet({source}, union_by_name=true) WHERE CAST(ply_count AS INTEGER)<=10"
        ).fetchone()[0]
    )
    connection.close()
    shutil.rmtree(temp, ignore_errors=True)
    return {
        "status": "POOL_MAIN_DYNAMIC_SUPPORT_COUNTS_OK",
        "panel_end_api_last_move_at_ms": panel_end,
        "a3_first_fair_recipient": {
            "rows": int(first[0]),
            "unique_normalized_recipients": int(first[1]),
            "unique_numeric_recipients": int(first[2]),
            "received_mercy": int(first[3]),
            "claimed_win": int(first[4]),
            "no_mating_draw": int(first[5]),
            "chooser_loss": int(first[6]),
            "invalid_arm_partition": int(first[7]),
            "invalid_anchor": int(first[8]),
            "a1_90d_followup_eligible_within_sample_panel": int(first[9]),
            "minimum_anchor_ms": int(first[10]),
            "maximum_anchor_ms": int(first[11]),
        },
        "b1_repeat_granter": {
            "choosers": int(b1[0]),
            "opportunities": int(b1[1]),
            "kind_draws": int(b1[2]),
            "minimum_opportunities": int(b1[3]),
            "maximum_opportunities": int(b1[4]),
            "minimum_kind_draws": int(b1[5]),
            "maximum_kind_draws": int(b1[6]),
        },
        "second_wave_hash_targets": {
            "union_rows": int(target[0]),
            "user_sample_rows": int(target[1]),
            "pair_sample_rows": int(target[2]),
            "distinct_union_games": int(target[3]),
            "sampled_chooser_ids": int(target[4]),
            "user_seed": USER_SEED,
            "pair_seed": PAIR_SEED,
            "denominator": SAMPLE_DENOMINATOR,
        },
        "ply_le_10_rows": short_rows,
    }


def source_inventory() -> dict[str, Any]:
    root = common.PACKAGE_ROOT / "source/dynamics"
    files = common.output_manifest(root)
    material = "".join(
        f"{row['relative_path']}\t{row['bytes']}\t{row['sha256']}\n" for row in files
    )
    return {
        "status": "BUNDLED_DYNAMIC_SOURCE_INVENTORY_OK",
        "root": str(root),
        "files": len(files),
        "bytes": sum(int(row["bytes"]) for row in files),
        "inventory_sha256": hashlib.sha256(material.encode("utf-8")).hexdigest(),
        "entries": files,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.threads <= 10:
        raise SystemExit("--threads must be between 1 and 10")
    project = args.project_root.expanduser().resolve()
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    wave1 = authenticate_wave1(project, args.wave1_public.resolve(), auth["fingerprint"])
    counts = support_counts(
        auth,
        args.private_temp.resolve(),
        args.threads,
        args.memory_limit,
    )
    if counts["ply_le_10_rows"] != 4_137_265:
        raise RuntimeError("Pool-main ply<=10 authority mismatch")
    chronology = chronology_probe(project)
    old_inputs = {
        "original_stage07": directory_probe(project / "derived/replication/analysis_panel_24m_sf100k"),
        "frequent_dyad_flags": directory_probe(
            project
            / "derived/replication/frequent_dyad_census_24m_v101_PRIVATE"
            / "stage07_frequency_flags_private"
        ),
        "a3_old_private": directory_probe(
            project / "derived/replication/dynamic_prosociality_a3_chronology_gate_v100_PRIVATE"
        ),
        "core_old_private": directory_probe(
            project / "derived/replication/dynamic_prosociality_core_v102_PRIVATE"
        ),
        "second_wave_old_private": directory_probe(
            project / "derived/replication/dynamic_second_wave_history_v100_PRIVATE"
        ),
        "campaign_old_private": directory_probe(
            project / "derived/replication/dynamics_campaign1_nonprofile_recovery_v104_PRIVATE"
        ),
        "patron_snapshot": directory_probe(
            project
            / "derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED"
            / "profile_snapshot_24m_private_lossless.parquet"
        ),
    }
    for value in old_inputs.values():
        value["reuse_policy"] = "upstream history/lookup only if semantically invariant; never treat old sample-dependent estimates or caches as current"
    free_gb = shutil.disk_usage(project).free / 1024**3
    cohort = counts["a3_first_fair_recipient"]
    support_integrity_ok = (
        cohort["rows"] == cohort["unique_normalized_recipients"]
        and cohort["rows"] == cohort["unique_numeric_recipients"]
        and cohort["invalid_arm_partition"] == 0
        and cohort["invalid_anchor"] == 0
    )
    ready = (
        wave1["status"] == "POOL_MAIN_WAVE1_INPUTS_AUTHENTICATED_OK"
        and counts["status"] == "POOL_MAIN_DYNAMIC_SUPPORT_COUNTS_OK"
        and support_integrity_ok
        and chronology["status"] == "CANONICAL_CHRONOLOGY_MANIFEST_AUTHENTICATED_OK"
        and free_gb >= 80.0
    )
    result = {
        "status": "POOL_MAIN_WAVE2B_PREFLIGHT_READY" if ready else "POOL_MAIN_WAVE2B_PREFLIGHT_BLOCKED",
        "created_at_utc": common.utc_now(),
        "sample_authority": common.compact_sample_lineage(auth),
        "wave1": wave1,
        "new_sample_support_counts": counts,
        "new_sample_support_integrity": {
            "status": (
                "POOL_MAIN_DYNAMIC_SUPPORT_INTEGRITY_OK"
                if support_integrity_ok
                else "POOL_MAIN_DYNAMIC_SUPPORT_INTEGRITY_BLOCKED"
            ),
            "first_fair_recipient_rows_equal_normalized_and_numeric_users": (
                cohort["rows"]
                == cohort["unique_normalized_recipients"]
                == cohort["unique_numeric_recipients"]
            ),
            "arm_partition_failures": cohort["invalid_arm_partition"],
            "invalid_anchors": cohort["invalid_anchor"],
        },
        "canonical_chronology": chronology,
        "existing_old_lineage_inputs": old_inputs,
        "bundled_source_inventory": source_inventory(),
        "resources": {
            "threads": args.threads,
            "memory_limit": args.memory_limit,
            "free_gb": free_gb,
            "minimum_free_gb_for_next_wave": 80.0,
        },
        "rewrite_contract": {
            "old_sample_dependent_dynamic_caches_current": False,
            "canonical_all_game_chronology_reusable": chronology["status"]
            == "CANONICAL_CHRONOLOGY_MANIFEST_AUTHENTICATED_OK",
            "first_eligible_exposures_must_be_rebuilt": True,
            "b1_support_and_propensities_must_be_rebuilt": True,
            "second_wave_target_and_pair_joins_must_be_rebuilt": True,
            "campaign_and_targeted_memory_outputs_must_be_reestimated": True,
            "chooser_leniency_iv_and_comparison_frame_must_be_rebuilt": True,
            "chooser_leniency_rejoin_predicate": (
                "source = 'pool' AND previous_classification_status = "
                "'not_mutually_adjacent_observed'"
            ),
            "chooser_leniency_selection_decomposition_required": {
                "chooser_role_timeout": True,
                "disconnector_role_timeout": True,
                "active_resolution_given_candidate": True,
                "retain_outoftime_for_selection_denominators": True,
                "note": (
                    "Report role-specific timeout incidence and the active-resolution "
                    "conditional probability on the rebuilt independent comparison frame; "
                    "do not estimate selection from the enriched convenience fragment."
                ),
            },
            "literal_end_to_start_immediate_rematches_certified": False,
        },
    }
    common.atomic_json(args.receipt.resolve(), result)
    print(result["status"], flush=True)
    print(
        "A3_NEW_SAMPLE_ROWS="
        + f"{counts['a3_first_fair_recipient']['rows']:,}",
        flush=True,
    )
    print(
        "B1_NEW_SAMPLE="
        + f"{counts['b1_repeat_granter']['choosers']:,} choosers / "
        + f"{counts['b1_repeat_granter']['opportunities']:,} opportunities / "
        + f"{counts['b1_repeat_granter']['kind_draws']:,} kind draws",
        flush=True,
    )
    print(f"CHRONOLOGY_STATUS={chronology['status']}", flush=True)
    return result


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
