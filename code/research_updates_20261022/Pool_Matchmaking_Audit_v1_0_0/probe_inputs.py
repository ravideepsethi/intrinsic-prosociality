#!/usr/bin/env python3
"""Offline Parquet-footer inventory. Does not read game rows or estimate models."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import time
import zipfile
from pathlib import Path

VERSION = "1.0.0"
EXPECTED_MAIN_ROWS = 41_534_331
EXPECTED_MAIN_FINGERPRINT = "a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30"
COMPARISON_REL = (
    "derived/replication/chooser_iv_main_rebuild_v100_PRIVATE/"
    "ccbc43314875/analysis/comparison.parquet"
)
COMPARISON_EXPECTED = {
    "rows": 1_661_563,
    "bytes": 173_517_733,
    "sha256_not_recomputed_by_this_probe":
        "8bc92d15b9a63e4cc1191ab8342aedd918a36bd341d9a8ddc427e93bb9f156ae",
}
FIELD_PATTERNS = {
    "queue_entry_or_wait_candidate": r"queue|enqueue|pool.?join|wait.?time|missed.?wave|^misses$",
    "conduct_score_candidate": r"rage|sitt|conduct|playban",
    "blocking_or_rating_preference_candidate": r"block|rating.?range|seek.?range",
    "internal_pairing_rating_or_trust_candidate": r"pairing.?rating|join.?rating|trust|lame",
    "provisional_or_rating_uncertainty_candidate": r"provisional|established|deviation|(^|_)rd($|_)",
    "game_start_time_candidate_not_queue_time": r"created|archive.?start|start.?ms|start.?time|timestamp|^ts$",
    "rating_candidate": r"rating|elo",
    "pool_clock_source_candidate": r"source|pool|speed|tc.?base|tc.?inc|time.?control|clock.?initial|increment",
    "prior_history_candidate": r"prior|pre_|history|lag|n_7d|n_30d|counterparts|adjusted|expected",
    "selection_or_role_candidate": r"active|passive|timeout|outoftime|eligible|chooser|recipient|disconnect|status|adjacen",
}


def select_spread(paths, cap):
    paths = sorted(paths)
    if len(paths) <= cap:
        return paths
    if cap == 1:
        return [paths[len(paths) // 2]]
    return [paths[i] for i in sorted({round(i * (len(paths) - 1) / (cap - 1)) for i in range(cap)})]


def footer_record(db, path, project):
    before = path.stat()
    meta = db.execute(
        "SELECT num_rows, num_row_groups FROM parquet_file_metadata(?)", [str(path)]
    ).fetchone()
    schema = db.execute(
        "SELECT name, type, repetition_type, num_children, duckdb_type FROM parquet_schema(?)",
        [str(path)],
    ).fetchall()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError("File changed during footer inspection")
    fields = [
        {"name": row[0], "physical_type": row[1], "repetition": row[2],
         "children": row[3], "duckdb_type": row[4]}
        for row in schema[1:]
    ]
    return {
        "relative_path": path.relative_to(project).as_posix(),
        "bytes": before.st_size, "footer_rows": int(meta[0]),
        "row_groups": int(meta[1]), "schema": fields,
        "candidate_fields_only_not_semantic_validation": {
            name: sorted({f["name"] for f in fields if re.search(pattern, f["name"], re.I)})
            for name, pattern in FIELD_PATTERNS.items()
        },
    }


def inventory(project):
    import duckdb
    panel = project / "derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE"
    chron = project / "derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time"
    panel_files = list(panel.glob("panel/month=*/analysis_panel.parquet"))
    chronology_files = [
        p for p in chron.glob("speed=*/month=*/part-00000.parquet")
        if "2023-11" <= p.parent.name.removeprefix("month=") <= "2025-10"
    ]
    comparison = project / COMPARISON_REL
    targets = [
        ("new_main_opportunities", panel_files, 32),
        ("existing_IV_ordinary_game_comparison", [comparison] if comparison.is_file() else [], 1),
        ("all_game_chronology_sample_of_footers", chronology_files, 8),
    ]
    db = duckdb.connect(":memory:")
    db.execute("SET threads=1")
    db.execute("SET memory_limit='256MB'")
    groups = []
    try:
        for name, paths, cap in targets:
            print("Inspecting metadata:", name, flush=True)
            picked = select_spread(paths, cap)
            records, errors = [], []
            for path in picked:
                try:
                    records.append(footer_record(db, path, project))
                except Exception as exc:
                    errors.append({"relative_path": path.relative_to(project).as_posix(),
                                   "error_type": type(exc).__name__,
                                   "message": "Footer read failed; no row data was read."})
            groups.append({
                "group": name, "discovered_files": len(paths), "inspected_files": len(records),
                "status": ("NO_FILES_FOUND" if not paths else "FOOTER_ERRORS" if errors
                           else "FOOTER_SAMPLE" if len(records) < len(paths) else "FOOTERS_INSPECTED"),
                "inspection_cap": cap, "all_discovered_files_inspected": len(records) == len(paths),
                "records": records, "errors": errors,
                "sum_footer_rows_for_inspected_files_only": sum(r["footer_rows"] for r in records),
            })
    finally:
        db.close()
    main, comparison_group, _ = groups
    main_matches = (
        main["discovered_files"] == 24 and main["inspected_files"] == 24
        and main["sum_footer_rows_for_inspected_files_only"] == EXPECTED_MAIN_ROWS
    )
    comparison_matches = bool(
        comparison_group["records"]
        and comparison_group["records"][0]["footer_rows"] == COMPARISON_EXPECTED["rows"]
        and comparison_group["records"][0]["bytes"] == COMPARISON_EXPECTED["bytes"]
    )
    return {
        "version": VERSION, "status": "METADATA_INVENTORY_ONLY",
        "duckdb_version": duckdb.__version__, "groups": groups,
        "expected_main_rows": EXPECTED_MAIN_ROWS,
        "expected_main_fingerprint_not_authenticated_here": EXPECTED_MAIN_FINGERPRINT,
        "main_footer_count_matches_expected": main_matches,
        "comparison_footer_count_and_size_match_expected": comparison_matches,
        "comparison_published_authority": COMPARISON_EXPECTED,
        "parquet_rows_read": 0, "network_requests": 0,
        "stockfish_searches": 0, "private_row_values_in_report": False,
        "input_bytes_fully_rehashed": False, "sample_or_assignment_certified": False,
        "limits": [
            "Only documented paths are inspected. Missing here does not mean absent everywhere.",
            "Field names do not establish meaning, timing, completeness, or valid denominators.",
            "A game-start timestamp is not a queue-entry timestamp.",
            "The ordinary-game comparison is a selected frame, not the entire pool-game universe.",
            "No balance, selection or treatment-effect models were estimated.",
        ],
    }


def package_report(report, desktop):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = desktop / ("POOL_MATCHMAKING_INPUT_PROBE_" + stamp + ".zip")
    payload = {
        "INPUT_AVAILABILITY.json": (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(),
        "README.txt": (
            "This is a metadata-only inventory for a proposed matchmaking audit.\n"
            "It contains schemas, file sizes and footer row counts, without game/account values.\n"
            "It is not a balance result, causal design certificate, or full-byte input verification.\n"
            "Use the accompanying design note to choose the next supported analysis.\n"
        ).encode(),
    }
    hashes = "".join(hashlib.sha256(value).hexdigest() + "  " + name + "\n"
                     for name, value in sorted(payload.items()))
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in payload.items():
            archive.writestr(name, value)
        archive.writestr("REPORT_MANIFEST.sha256", hashes)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    sidecar = Path(str(destination) + ".sha256")
    with sidecar.open("x") as stream:
        stream.write(digest + "  " + destination.name + "\n")
    return destination, sidecar


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=Path("/Volumes/XT_Pro/lichess_kindness"))
    p.add_argument("--desktop", type=Path, default=Path.home() / "Desktop/Lichess_Desktop")
    args = p.parse_args()
    if not args.project_root.is_dir():
        raise SystemExit("Project root is unavailable: " + str(args.project_root))
    if not args.desktop.is_dir():
        raise SystemExit("Output directory is unavailable: " + str(args.desktop))
    begin = time.monotonic()
    report = inventory(args.project_root.resolve())
    report["elapsed_seconds"] = time.monotonic() - begin
    output, sidecar = package_report(report, args.desktop.resolve())
    print("Metadata inventory complete. No empirical tests were run.")
    print("Main footer count agrees:", report["main_footer_count_matches_expected"])
    print("Comparison footer count and size agree:", report["comparison_footer_count_and_size_match_expected"])
    print("UPLOAD", output)
    print("UPLOAD", sidecar)


if __name__ == "__main__":
    main()
