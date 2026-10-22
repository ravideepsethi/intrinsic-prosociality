#!/usr/bin/env python3
"""Build audited Stage-05 timeout opportunities for completed 36m API months.

This is a narrow extension adapter around the authenticated 24-month Stage-05
producer bundled in ``vendor/05_build_timeout_opportunity_panel.py``.  It does
not call the network.  It authenticates completed Stage-04 extension outputs,
freezes their timeout IDs, and delegates the scientific transformation and all
row-level gates to the canonical producer.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import math
import os
import shlex
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


SCRIPT_VERSION = "1.0.0"
ALLOWED_MONTHS = ("2026-04",)


def load_canonical() -> Any:
    path = Path(__file__).resolve().parents[1] / "vendor" / "05_build_timeout_opportunity_panel.py"
    spec = importlib.util.spec_from_file_location("canonical_stage05", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load canonical Stage-05 producer: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.SCRIPT_VERSION = f"{module.SCRIPT_VERSION}+36m-extension-{SCRIPT_VERSION}"
    module.LOCKED_MONTHS = ALLOWED_MONTHS
    module.EARLIER_MONTHS = ()
    module.BRIDGE_MONTHS = ALLOWED_MONTHS
    module.LATE_MONTHS = ()
    return module


C = load_canonical()


def parse_months(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() == "all":
        return ALLOWED_MONTHS
    values = tuple(value.strip() for value in raw.split(",") if value.strip())
    C.require(bool(values), "--months resolved to an empty list")
    C.require(len(values) == len(set(values)), "--months contains duplicates")
    bad = [value for value in values if value not in ALLOWED_MONTHS]
    C.require(not bad, f"unsupported months: {bad}; allowed={ALLOWED_MONTHS}")
    wanted = set(values)
    return tuple(month for month in ALLOWED_MONTHS if month in wanted)


def digest_payload(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@contextlib.contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise C.ContractError(f"another Stage-05 extension process holds {path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "started_utc": C.utc_now()}) + "\n")
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def success_status_counts(success: Mapping[str, Any]) -> dict[str, int]:
    raw = success.get("status_counts") or {}
    return {str(key): int(value) for key, value in raw.items()}


def validate_completed_api_month(
    connection: Any,
    month: str,
    stage01_root: Path,
    api_root: Path,
    logger: Any,
) -> dict[str, Any]:
    candidate = stage01_root / f"month={month}" / "api_target_candidates_ge5s_or_missing.parquet"
    stage01_success_path = stage01_root / f"month={month}" / "_SUCCESS.json"
    api_month = api_root / f"month={month}"
    api_success_path = api_month / "_SUCCESS.json"
    api_plan_path = api_month / "_plan.json"

    stage01_success = C.read_json(stage01_success_path)
    api_success = C.read_json(api_success_path)
    api_plan = C.read_json(api_plan_path)

    C.require(stage01_success.get("final_ok") is True, f"{month}: Stage-01 is not final")
    C.require(api_success.get("final_ok") is True, f"{month}: API enrichment is not final")
    C.require(api_success.get("month") == month, f"{month}: API success month mismatch")
    C.require(api_plan.get("month") == month, f"{month}: API plan month mismatch")
    C.require(bool(api_success.get("production")), f"{month}: API output is not production")

    expected_target = int(api_success.get("source_rows", -1))
    C.require(expected_target > 0, f"{month}: API source_rows is not positive")

    for field in ("source_rows", "selected_rows", "requested_ids", "returned_unique_ids"):
        C.require(
            int(api_success.get(field, -1)) == expected_target,
            f"{month}: API {field}={api_success.get(field)!r}, expected {expected_target}",
        )
    C.require(int(api_success.get("missing_ids", -1)) == 0, f"{month}: API has missing IDs")
    C.require(int(api_plan.get("selected_rows", -1)) == expected_target, f"{month}: plan row mismatch")

    unit_count = int(api_success.get("unit_count", -1))
    expected_units = math.ceil(expected_target / int(api_success.get("unit_size", 30_000)))
    C.require(unit_count == expected_units, f"{month}: API unit count mismatch")

    response_paths = sorted((api_month / "responses").glob("unit-*.parquet"))
    checkpoint_paths = sorted((api_month / "_checkpoints").glob("unit-*.success.json"))
    C.require(len(response_paths) == unit_count, f"{month}: expected {unit_count} response files, found {len(response_paths)}")
    C.require(len(checkpoint_paths) == unit_count, f"{month}: expected {unit_count} checkpoints, found {len(checkpoint_paths)}")

    candidate_fp = C.fingerprint(candidate)
    api_fps = tuple(C.fingerprint(path) for path in response_paths)
    checkpoint_fps = tuple(C.fingerprint(path) for path in checkpoint_paths)
    recorded_checkpoints = {
        int(row["unit_index"]): str(row["sha256"])
        for row in api_success.get("unit_checkpoint_sha256", [])
    }
    C.require(
        len(recorded_checkpoints) == unit_count,
        f"{month}: success receipt does not enumerate every unit checkpoint",
    )
    for unit_index, (response_fp, checkpoint_fp) in enumerate(zip(api_fps, checkpoint_fps)):
        C.require(
            checkpoint_fp.sha256 == recorded_checkpoints.get(unit_index),
            f"{month}: checkpoint {unit_index:05d} hash disagrees with month success receipt",
        )
        checkpoint = C.read_json(Path(checkpoint_fp.path))
        compact = (checkpoint.get("artifacts") or {}).get("compact") or {}
        C.require(checkpoint.get("final_ok") is True, f"{month}: checkpoint {unit_index:05d} is not final")
        C.require(int(checkpoint.get("unit_index", -1)) == unit_index, f"{month}: checkpoint index mismatch")
        C.require(int(checkpoint.get("missing_ids", -1)) == 0, f"{month}: checkpoint {unit_index:05d} has missing IDs")
        C.require(compact.get("sha256") == response_fp.sha256, f"{month}: response {unit_index:05d} hash disagrees with checkpoint")
        C.require(int(compact.get("size_bytes", -1)) == response_fp.size_bytes, f"{month}: response {unit_index:05d} size disagrees with checkpoint")
    authority_fps = (
        C.fingerprint(stage01_success_path),
        C.fingerprint(api_success_path),
        C.fingerprint(api_plan_path),
        *checkpoint_fps,
    )

    candidate_relation = C.parquet_scan_sql((candidate,))
    api_relation = C.parquet_scan_sql(response_paths)
    candidate_counts = connection.execute(
        f"SELECT COUNT(*)::BIGINT, COUNT(DISTINCT game_id)::BIGINT FROM {candidate_relation}"
    ).fetchone()
    C.require(tuple(map(int, candidate_counts)) == (expected_target, expected_target), f"{month}: Stage-01 candidate cardinality failed: {candidate_counts}")

    api_counts = connection.execute(
        f"""
        SELECT
            COUNT(*)::BIGINT,
            COUNT(DISTINCT game_id)::BIGINT,
            COUNT(DISTINCT request_ordinal)::BIGINT,
            MIN(request_ordinal)::BIGINT,
            MAX(request_ordinal)::BIGINT,
            SUM((month <> {C.sql_string(month)})::INTEGER)::BIGINT,
            SUM((lower(trim(api_status)) NOT IN ('timeout','outoftime'))::INTEGER)::BIGINT,
            SUM((api_status IS NULL OR game_id IS NULL)::INTEGER)::BIGINT
        FROM {api_relation}
        """
    ).fetchone()
    expected_api = (expected_target, expected_target, expected_target, 0, expected_target - 1, 0, 0, 0)
    observed_api = tuple(int(value or 0) for value in api_counts)
    C.require(observed_api == expected_api, f"{month}: API response cardinality/semantics failed: {observed_api}")

    observed_status = {
        str(status): int(rows)
        for status, rows in connection.execute(
            f"SELECT lower(trim(api_status)), COUNT(*)::BIGINT FROM {api_relation} GROUP BY 1 ORDER BY 1"
        ).fetchall()
    }
    recorded_status = success_status_counts(api_success)
    C.require(observed_status == recorded_status, f"{month}: API status counts disagree with success receipt: observed={observed_status}, recorded={recorded_status}")
    C.require(set(observed_status) <= {"timeout", "outoftime"}, f"{month}: unexpected API statuses: {observed_status}")
    timeout_rows = int(observed_status.get("timeout", 0))
    C.require(timeout_rows > 0, f"{month}: no timeout opportunities found")

    set_diff = connection.execute(
        f"""
        SELECT
          (SELECT COUNT(*) FROM (SELECT game_id FROM {candidate_relation} EXCEPT SELECT game_id FROM {api_relation}))::BIGINT,
          (SELECT COUNT(*) FROM (SELECT game_id FROM {api_relation} EXCEPT SELECT game_id FROM {candidate_relation}))::BIGINT
        """
    ).fetchone()
    C.require(tuple(map(int, set_diff)) == (0, 0), f"{month}: Stage-01/API target ID sets differ: {set_diff}")

    logger.emit(f"{month}: API completion authenticated; targets={expected_target:,}; timeouts={timeout_rows:,}")
    return {
        "month": month,
        "target_rows": expected_target,
        "timeout_rows": timeout_rows,
        "candidate": candidate_fp,
        "api_files": api_fps,
        "authority_files": authority_fps,
        "api_relation": api_relation,
        "recorded_status_counts": recorded_status,
    }


def build_or_reuse_frozen_timeout(
    connection: Any,
    evidence: Mapping[str, Any],
    frozen_root: Path,
    logger: Any,
) -> tuple[Any, Any]:
    month = str(evidence["month"])
    final_dir = frozen_root / f"month={month}"
    output = final_dir / "timeout_ids.parquet"
    success_path = final_dir / "_SUCCESS.json"
    api_files = evidence["api_files"]
    authority_files = evidence["authority_files"]
    source_digest = digest_payload(
        {
            "contract": "stage04_extension_timeout_freeze_v1",
            "script_version": SCRIPT_VERSION,
            "month": month,
            "api_files": [asdict(item) for item in api_files],
            "authority_files": [asdict(item) for item in authority_files],
        }
    )

    if final_dir.exists():
        receipt = C.read_json(success_path)
        C.require(receipt.get("final_ok") is True, f"{month}: existing timeout freeze is not final")
        C.require(receipt.get("source_set_sha256") == source_digest, f"{month}: existing timeout freeze used different sources")
        frozen_fp = C.fingerprint(output, str(receipt.get("output_sha256")))
        counts = connection.execute(
            f"SELECT COUNT(*)::BIGINT, COUNT(DISTINCT game_id)::BIGINT FROM {C.parquet_scan_sql((output,))}"
        ).fetchone()
        expected = int(evidence["timeout_rows"])
        C.require(tuple(map(int, counts)) == (expected, expected), f"{month}: existing timeout freeze cardinality failed")
        logger.emit(f"{month}: authenticated frozen timeout checkpoint reused")
        return frozen_fp, C.fingerprint(success_path)

    partial = frozen_root / f".month={month}.partial.{os.getpid()}"
    C.require(not partial.exists(), f"{month}: unexpected frozen partial exists: {partial}")
    partial.mkdir(parents=True)
    partial_output = partial / "timeout_ids.parquet"
    try:
        connection.execute(
            f"""
            COPY (
              SELECT
                CAST(month AS VARCHAR) AS month,
                CAST(game_id AS VARCHAR) AS game_id,
                'timeout'::VARCHAR AS api_status,
                'extension_native_stage04'::VARCHAR AS source_block,
                'canonical_stage01_plus_native_stage04_extension'::VARCHAR AS provenance_class
              FROM {evidence['api_relation']}
              WHERE lower(trim(api_status)) = 'timeout'
              ORDER BY request_ordinal
            ) TO {C.sql_string(partial_output)}
            (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
            """
        )
        partial_fp = C.fingerprint(partial_output)
        counts = connection.execute(
            f"SELECT COUNT(*)::BIGINT, COUNT(DISTINCT game_id)::BIGINT FROM {C.parquet_scan_sql((partial_output,))}"
        ).fetchone()
        expected = int(evidence["timeout_rows"])
        C.require(tuple(map(int, counts)) == (expected, expected), f"{month}: newly frozen timeout cardinality failed: {counts}")
        receipt = {
            "contract": "stage04_extension_timeout_freeze_v1",
            "script_version": SCRIPT_VERSION,
            "final_ok": True,
            "month": month,
            "target_rows": int(evidence["target_rows"]),
            "timeout_rows": expected,
            "status_counts": evidence["recorded_status_counts"],
            "source_set_sha256": source_digest,
            "output_path": str(output),
            "output_size_bytes": partial_fp.size_bytes,
            "output_sha256": partial_fp.sha256,
            "created_utc": C.utc_now(),
        }
        C.atomic_write_json(partial / "_SUCCESS.json", receipt)
        frozen_root.mkdir(parents=True, exist_ok=True)
        os.replace(partial, final_dir)
        logger.emit(f"{month}: froze {expected:,} exact timeout IDs")
        return C.fingerprint(output, partial_fp.sha256), C.fingerprint(success_path)
    except Exception:
        raise


def make_sources(evidence: Mapping[str, Any], frozen_fp: Any, frozen_success_fp: Any) -> Any:
    month = str(evidence["month"])
    authority = tuple(evidence["authority_files"]) + (frozen_success_fp,)
    ordered = (frozen_fp, evidence["candidate"], *evidence["api_files"], *authority)
    digest = C.source_set_digest(month, "bridge", ordered)
    return C.MonthSources(
        month=month,
        block="bridge",
        source_block="extension_native_stage04",
        provenance_class="canonical_stage01_plus_native_stage04_extension",
        candidate_source_class="canonical_stage01_target_parquet",
        expected_timeout_rows=int(evidence["timeout_rows"]),
        expected_target_rows=int(evidence["target_rows"]),
        frozen_timeout=frozen_fp,
        candidate=evidence["candidate"],
        api_files=tuple(evidence["api_files"]),
        authority_files=authority,
        source_set_sha256=digest,
        candidate_kind="parquet",
    )


def execute(args: argparse.Namespace) -> int:
    started = time.monotonic()
    project_root = args.project_root.expanduser().resolve()
    months = parse_months(args.months)
    stage01_root = (args.stage01_root or project_root / "derived/replication/pgn_timeforfeit_candidates").expanduser().resolve()
    api_root = (args.api_root or project_root / "derived/replication_36m/api_timeout_enrichment_extension").expanduser().resolve()
    output_root = (args.output_root or project_root / "derived/replication_36m/timeout_opportunity_extension").expanduser().resolve()
    frozen_root = (args.frozen_root or project_root / "derived/replication_36m/api_timeout_enrichment_extension_reconciled").expanduser().resolve()

    C.require(project_root.is_dir(), f"project root does not exist: {project_root}")
    C.require(stage01_root.is_dir(), f"Stage-01 root does not exist: {stage01_root}")
    C.require(api_root.is_dir(), f"API extension root does not exist: {api_root}")
    C.require(args.threads >= 1 and args.threads <= 10, "--threads must be between 1 and 10")
    output_root.mkdir(parents=True, exist_ok=True)
    frozen_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / "_manifests" / "runs" / f"{C.run_stamp()}_{os.getpid()}"
    run_root.mkdir(parents=True, exist_ok=False)
    logger = C.EventLog(run_root / "run.log")

    duckdb = C.load_duckdb()
    temp_root = (args.temp_directory or output_root / "_duckdb_tmp").expanduser().resolve()
    temp_root.mkdir(parents=True, exist_ok=True)
    connection = C.configure_connection(
        duckdb,
        database=str(run_root / "stage05_extension.duckdb"),
        memory_limit=args.memory_limit,
        threads=args.threads,
        temp_directory=temp_root,
    )

    C.atomic_write_json(
        run_root / "run_config.json",
        {
            "script_version": SCRIPT_VERSION,
            "canonical_stage05_version": C.SCRIPT_VERSION,
            "started_utc": C.utc_now(),
            "command": shlex.join([sys.executable, *sys.argv]),
            "project_root": str(project_root),
            "stage01_root": str(stage01_root),
            "api_root": str(api_root),
            "frozen_root": str(frozen_root),
            "output_root": str(output_root),
            "months": list(months),
            "threads": args.threads,
            "memory_limit": args.memory_limit,
            "api_requests_performed": False,
        },
    )

    rows: list[dict[str, Any]] = []
    try:
        with exclusive_lock(output_root / ".stage05_extension.lock"):
            logger.emit("36M STAGE-05 EXTENSION STARTED — READ-ONLY ON STAGE-01/API SOURCES")
            for ordinal, month in enumerate(months, start=1):
                logger.emit(f"{month}: month {ordinal}/{len(months)}")
                evidence = validate_completed_api_month(connection, month, stage01_root, api_root, logger)
                frozen_fp, frozen_success_fp = build_or_reuse_frozen_timeout(connection, evidence, frozen_root, logger)
                sources = make_sources(evidence, frozen_fp, frozen_success_fp)
                C.install_source_views(connection, sources)
                result = C.build_month(connection, sources, output_root, logger)
                success = result["success"]
                gates = success["gates"]
                rows.append(
                    {
                        "month": month,
                        "run_status": result["status"],
                        "target_rows": int(evidence["target_rows"]),
                        "opportunity_rows": int(gates["rows"]),
                        "outcome_kind_draws": int(gates["outcome_kind_draws"]),
                        "timeout_draws": int(gates["timeout_draws"]),
                        "timeout_chooser_wins": int(gates["timeout_chooser_wins"]),
                        "timeout_chooser_losses": int(gates["timeout_chooser_losses"]),
                        "source_set_sha256": sources.source_set_sha256,
                        "output_path": str(output_root / f"month={month}" / "timeout_opportunities.parquet"),
                        "output_sha256": success["output"]["sha256"],
                    }
                )

            output_paths = [Path(row["output_path"]) for row in rows]
            union = C.parquet_scan_sql(output_paths)
            total, distinct_ids, months_observed = connection.execute(
                f"SELECT COUNT(*)::BIGINT, COUNT(DISTINCT game_id)::BIGINT, COUNT(DISTINCT month)::BIGINT FROM {union}"
            ).fetchone()
            total = int(total)
            C.require(int(distinct_ids) == total, "cross-month duplicate game IDs detected")
            C.require(int(months_observed) == len(months), "output month count mismatch")

            fields = (
                "month", "run_status", "target_rows", "opportunity_rows",
                "outcome_kind_draws", "timeout_draws", "timeout_chooser_wins",
                "timeout_chooser_losses", "source_set_sha256", "output_path", "output_sha256",
            )
            C.write_csv(run_root / "month_status.csv", rows, fields)
            paths_file = run_root / "timeout_opportunity_paths.txt"
            C.atomic_write_text(paths_file, "".join(f"{row['output_path']}\n" for row in rows))
            summary = {
                "certificate": "LICHESS_36M_STAGE05_APRIL_OK",
                "final_ok": True,
                "scope": "completed API month 2026-04 only",
                "script_version": SCRIPT_VERSION,
                "canonical_stage05_version": C.SCRIPT_VERSION,
                "months": list(months),
                "month_count": len(months),
                "target_rows": sum(row["target_rows"] for row in rows),
                "total_timeout_opportunities": total,
                "outcome_kind_draws": sum(row["outcome_kind_draws"] for row in rows),
                "global_unique_game_ids": int(distinct_ids),
                "api_requests_performed": False,
                "storage": "typed ZSTD Parquet",
                "output_root": str(output_root),
                "paths_file": str(paths_file),
                "monthly_funnel": rows,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "finished_utc": C.utc_now(),
                "next_step": "Prepare extension Stockfish inputs and run Stockfish 18 at 100,000 nodes.",
            }
            C.atomic_write_json(run_root / "_SUCCESS.json", summary)
            C.atomic_write_json(output_root / "_manifests" / "CHECKPOINT_2026-04_SUCCESS.json", summary)
            C.atomic_write_text(output_root / "_manifests" / "latest_april_checkpoint_run_path.txt", str(run_root) + "\n")
            logger.emit(f"LICHESS_36M_STAGE05_APRIL_OK rows={total:,}")
            print(json.dumps(summary, indent=2, sort_keys=True))
        connection.close()
        return 0
    except Exception as exc:
        C.atomic_write_json(
            run_root / "failure.json",
            {
                "final_ok": False,
                "failed_utc": C.utc_now(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "api_requests_performed": False,
            },
        )
        logger.emit(f"FAILED CLOSED: {type(exc).__name__}: {exc}")
        try:
            connection.close()
        except Exception:
            pass
        raise


def plan(args: argparse.Namespace) -> int:
    project_root = args.project_root.expanduser().resolve()
    months = parse_months(args.months)
    api_root = (args.api_root or project_root / "derived/replication_36m/api_timeout_enrichment_extension").expanduser().resolve()
    stage01_root = (args.stage01_root or project_root / "derived/replication/pgn_timeforfeit_candidates").expanduser().resolve()
    print("STAGE-05 EXTENSION PLAN — NO WRITES")
    print(f"Project: {project_root}")
    print(f"Months: {','.join(months)}")
    print(f"API root: {api_root}")
    print(f"Stage-01 root: {stage01_root}")
    print("Inputs are authenticated read-only; no API requests are possible.")
    print("Expected runtime: 10–30 minutes for April.")
    print("Expected temporary storage: 3–8 GiB.")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build audited Stage-05 extension Parquets for completed API months.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--months", default="all")
    parser.add_argument("--stage01-root", type=Path)
    parser.add_argument("--api-root", type=Path)
    parser.add_argument("--frozen-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--temp-directory", type=Path)
    parser.add_argument("--memory-limit", default="8GB")
    parser.add_argument("--threads", type=int, default=10)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    if args.self_test:
        return C.self_test(args)
    if args.execute:
        return execute(args)
    return plan(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except C.ContractError as exc:
        print(f"CONTRACT FAILURE: {exc}", file=sys.stderr)
        raise SystemExit(2)
