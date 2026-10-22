#!/usr/bin/env python3
"""Compute matched descriptive surfaces on the authenticated current pool sample."""
from __future__ import annotations
import os
for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"
import argparse
import concurrent.futures
import csv
import fcntl
import hashlib
import json
import multiprocessing
import platform
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import matplotlib
from source import pool_wave1_common as common
from surface_model import (VERSION, EXPECTED, READ_COLUMNS, CONTROL_COLUMNS,
    X, D, Y, Settings, Moments, consume, estimate, make_grid, term_names, require)
from render_surfaces import render

ROOT = Path(__file__).resolve().parent
SAMPLE_RELATIVE = "derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE"
STATUS = "POOL_DESERT_PAYOFF_SURFACES_COMPUTED_OK"


def manifest(root, name):
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != name and "__pycache__" not in path.parts:
            entries.append(f"{common.sha256_file(path)}  {path.relative_to(root).as_posix()}\n")
    common.atomic_text(root / name, "".join(entries))


def verify_manifest(root, name):
    path = root / name
    require(path.is_file(), f"Missing manifest: {path}")
    seen = set()
    for line in path.read_text().splitlines():
        digest, relative = line.split("  ", 1)
        target = root / relative
        require(target.resolve().is_relative_to(root.resolve()), "Unsafe manifest path")
        require(relative not in seen, "Duplicate manifest entry")
        seen.add(relative)
        require(target.is_file() and common.sha256_file(target) == digest,
                f"File failed SHA-256 verification: {relative}")
    require(bool(seen), "Empty manifest")
    return common.sha256_file(path)


def stat_signature(path):
    s = Path(path).stat()
    return (s.st_size, s.st_mtime_ns, s.st_ino)


def save_checkpoint(path, stats, metadata):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = dict(metadata, counts=stats.counts)
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as f:
        temp = Path(f.name)
        np.savez_compressed(f, **stats.arrays(), metadata=np.array(json.dumps(metadata, sort_keys=True)))
    os.replace(temp, path)
    common.atomic_text(path.with_suffix(".npz.sha256"), common.sha256_file(path) + "\n")


def load_checkpoint(path, settings, metadata):
    path = Path(path)
    sidecar = path.with_suffix(".npz.sha256")
    require(sidecar.is_file(), f"Incomplete checkpoint: {path}; remove this checkpoint and retry")
    require(sidecar.read_text().strip() == common.sha256_file(path), f"Corrupt checkpoint: {path}")
    with np.load(path, allow_pickle=False) as data:
        observed = json.loads(str(data["metadata"]))
        for key, value in metadata.items():
            require(observed.get(key) == value, f"Checkpoint metadata mismatch: {key}")
        return Moments.restore(settings, data, observed["counts"])


def month_job(job):
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    settings = Settings(**job["settings"])
    path, checkpoint = Path(job["path"]), Path(job["checkpoint"])
    meta = {key: job[key] for key in ("month", "run_fingerprint", "input_sha256")}
    if checkpoint.is_file():
        stats = load_checkpoint(checkpoint, settings, meta)
        require(stats.counts["rows"] == job["rows"], "Checkpoint row count mismatch")
        return {"month": job["month"], "counts": stats.counts, "resumed": True}
    before = stat_signature(path)
    require(before[0] == job["size_bytes"], "Input size changed after authentication")
    parquet = pq.ParquetFile(path)
    require(set(READ_COLUMNS).issubset(parquet.schema_arrow.names), "Required columns missing")
    stats = Moments(settings)
    for batch in parquet.iter_batches(batch_size=settings.batch_rows,
                                      columns=READ_COLUMNS, use_threads=False):
        consume(batch, job["month"], settings, stats)
    require(before == stat_signature(path), "Input changed during scan")
    require(stats.counts["rows"] == job["rows"], f"Wrong scanned rows for {job['month']}")
    save_checkpoint(checkpoint, stats, meta)
    return {"month": job["month"], "counts": stats.counts, "resumed": False}


def write_csv(path, rows):
    require(bool(rows), "Cannot write empty table")
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_report(report, settings, stats, month_counts, monthly_rows, lineage, run_fingerprint,
                 *, expected=EXPECTED, synthetic=False):
    require(stats.counts == expected, f"Sample totals changed: {stats.counts}, expected {expected}")
    require(int(month_counts.sum()) == stats.counts["rows"], "Monthly cells do not conserve rows")
    raw, adjusted, model = estimate(stats)
    grid = make_grid(stats, settings, raw, adjusted, month_counts)
    report.mkdir(parents=True, exist_ok=True)
    common.atomic_json(report / "SETTINGS.json", settings.dictionary())
    common.atomic_json(report / "MODEL.json", model)
    common.atomic_json(report / "SAMPLE_LINEAGE.json", lineage)
    write_csv(report / "surface_grid.csv", grid)
    pq.write_table(pa.Table.from_pylist(grid), report / "surface_grid.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(monthly_rows), report / "monthly_cell_counts.parquet", compression="zstd")
    coefficients = [{"term": name, "coefficient_probability_units": model["coefficients"][name],
                     "reference_basis_mean": model["reference_basis_means"][name]} for name in term_names()]
    write_csv(report / "control_coefficients.csv", coefficients)
    save_checkpoint(report / "pooled_moments.npz", stats, {"run_fingerprint": run_fingerprint})
    plot = render(grid, settings, report / "figures", synthetic=synthetic)
    visible = [r for r in grid if r["display_supported"]]
    inside = [r for r in grid if r["inside_display_window"]]
    summary = {
        "status": "SYNTHETIC_TEST_ONLY" if synthetic else STATUS,
        "created_utc": common.utc_now(), "version": VERSION,
        "run_fingerprint": run_fingerprint, "counts": stats.counts,
        "axes": {"x": X, "y": D, "z": Y}, "controls": list(CONTROL_COLUMNS),
        "same_rows_raw_and_adjusted": True, "complete_case_drops": 0,
        "rows_in_display_window": sum(r["opportunities"] for r in inside),
        "rows_in_supported_display_cells": sum(r["opportunities"] for r in visible),
        "share_of_sample_in_supported_display_cells": sum(r["opportunities"] for r in visible) / stats.counts["rows"],
        "support_criteria": {"min_opportunities": settings.min_cell_n, "min_months_observed": settings.min_cell_months},
        "display_raw_percent_range": [min(r["raw_percent"] for r in visible), max(r["raw_percent"] for r in visible)],
        "display_adjusted_percent_range": [min(r["adjusted_percent"] for r in visible), max(r["adjusted_percent"] for r in visible)],
        "adjusted_display_cells_outside_0_100": sum(r["adjusted_outside_0_100"] for r in visible),
        "plot": plot, "model_rank": model["identified_control_rank"],
        "interpretation": "Descriptive covariate adjustment; no chooser fixed effects or causal identification.",
        "production_microdata_run": not synthetic,
    }
    common.atomic_json(report / "SUMMARY.json", summary)
    notes = f"""# Kindness over desert and signed draw payoff

Sample: {stats.counts['rows']:,} opportunities, {stats.counts['kind_draws']:,} kind draws.
Raw and adjusted panels use the SAME rows, cells, support mask, camera and color/z scale.
X: chooser's signed draw payoff r_G, in rating points; negative means a draw loses points.
Y: disconnected opponent's engine evaluation in centipawns; positive means opponent ahead.
Z: kind draw percent. All finite input rows enter estimation; only the stated display window is shown.

Raw: 100 * kind_draws / opportunities in each joint cell.
Adjusted: OLS with joint-cell intercepts and additive linear splines in log(1+ply),
both players' log pre-game RD and both players' log pre-game volatility. Knots are in MODEL.json.
The joint surface is included WHILE estimating the controls. Each cell is then standardized
to the full sample's empirical distribution of the control basis terms:
adjusted[g] = raw[g] + 100 * (overall_mean_basis - cell_mean_basis[g]) @ beta.
This is a conditional association with common additive control effects. No chooser FE,
causal interpretation, uncertainty intervals, or claim of covariate-overlap certification.
Adjusted LPM levels can lie outside 0–100%; they are reported and plotted WITHOUT clipping.

Display: r_G in [{settings.payoff_min:g}, {settings.payoff_max:g}], step {settings.payoff_step:g};
evaluation in [{settings.desert_min:g}, {settings.desert_max:g}], step {settings.desert_step:g} cp.
Bins are lower-inclusive, upper-exclusive except the final upper edge, which is included.
Exact zero draw payoff belongs to the nonnegative cell. These bins do not estimate a zero discontinuity.
Actual tails occupy separate cells in the regression and CSV; they are not clamped onto display edges.
Cells require {settings.min_cell_n} opportunities and observations in {settings.min_cell_months} months
to be displayed. Support never depends on whether a cell has positive kind draws.
The threshold concerns cell counts, not overlap of all adjusted covariates.
3D facets join adjacent cell centers only when all four corners are supported. No smoothing.
Heatmaps display all supported cells, including isolated cells not joined by 3D facets.
Counts and control means in surface_grid.csv allow review of composition and support.

{'SYNTHETIC TEST DATA. NOT STUDY RESULTS.' if synthetic else 'Current frozen pool sample; observed predecessor nonadjacency screen certified, literal immediate non-rematches not certified.'}
"""
    common.atomic_text(report / "FIGURE_NOTES.md", notes)
    common.atomic_json(report / "_SUCCESS.json", {
        "status": summary["status"], "run_fingerprint": run_fingerprint,
        "counts": stats.counts, "created_utc": summary["created_utc"],
    })
    manifest(report, "OUTPUT_MANIFEST.sha256")
    return summary


def deliver(report, transfer_root, fingerprint):
    verify_manifest(report, "OUTPUT_MANIFEST.sha256")
    receipt = common.load_json(report / "_SUCCESS.json")
    require(receipt["status"] == STATUS and receipt["run_fingerprint"] == fingerprint,
            "Report success receipt does not match production run")
    transfer_root.mkdir(parents=True, exist_ok=True)
    stem = f"POOL_DESERT_PAYOFF_SURFACES_RESULTS_v100_{fingerprint[:16]}"
    target = transfer_root / f"{stem}.zip"
    temp = transfer_root / f".{stem}.{os.getpid()}.tmp.zip"
    with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(report.rglob("*")):
            if p.is_file():
                z.write(p, f"{stem}/{p.relative_to(report).as_posix()}")
    os.replace(temp, target)
    digest = common.sha256_file(target)
    common.atomic_text(target.with_suffix(".zip.sha256"), f"{digest}  {target.name}\n")
    print(f"\n{STATUS}\nRESULTS_ZIP: {target}\nSHA256: {digest}\nFIGURES: {report / 'figures'}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root", type=Path, default=Path("/Volumes/XT_Pro/lichess_kindness"))
    p.add_argument("--sample-root", type=Path)
    p.add_argument("--output-root", type=Path)
    p.add_argument("--transfer-root", type=Path, default=Path.home() / "Desktop/Lichess_Desktop")
    p.add_argument("--workers", type=int, default=10)
    p.add_argument("--hash-workers", type=int, default=2)
    for name, field in Settings.__dataclass_fields__.items():
        p.add_argument("--" + name.replace("_", "-"), type=type(field.default), default=field.default)
    args = p.parse_args()
    require(1 <= args.workers <= 10 and 1 <= args.hash_workers <= 10, "Use 1..10 workers")
    settings = Settings(**{name: getattr(args, name) for name in Settings.__dataclass_fields__})
    settings.validate()
    package_hash = verify_manifest(ROOT, "PACKAGE_MANIFEST.sha256")
    sample_root = args.sample_root or args.project_root / SAMPLE_RELATIVE
    started = time.monotonic()
    auth = common.authenticate_sample(sample_root, verify_hashes=True, hash_workers=args.hash_workers)
    require(set(READ_COLUMNS).issubset(auth["schema"]), "Requested controls absent from current sample")
    lineage = common.compact_sample_lineage(auth)
    for key, value in EXPECTED.items():
        require(lineage[key] == value, f"Authority {key} differs from current sample")
    versions = {"python": platform.python_version(), "numpy": np.__version__,
                "pyarrow": pa.__version__, "matplotlib": matplotlib.__version__}
    identity = {"sample_fingerprint": auth["fingerprint"], "package_manifest_sha256": package_hash,
                "settings": settings.dictionary(), "versions": versions}
    fingerprint = hashlib.sha256(common.canonical_json(identity).encode()).hexdigest()
    output_root = args.output_root or args.project_root / "output/pool_desert_payoff_surfaces_v100"
    work = output_root / f"run_{fingerprint[:16]}"
    work.mkdir(parents=True, exist_ok=True)
    with (work / "RUN.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This exact surface run is already active") from exc
        report = work / "report"
        if (report / "OUTPUT_MANIFEST.sha256").is_file():
            deliver(report, args.transfer_root, fingerprint)
            return
        common.atomic_json(work / "RUN_IDENTITY.json", identity)
        records = sorted(auth["month_records"], key=lambda r: r["month"])
        snapshots = {str(r["path"]): stat_signature(r["path"]) for r in records}
        jobs = []
        for r in records:
            jobs.append({"month": r["month"], "path": str(r["path"]), "rows": r["rows"],
                "size_bytes": r["size_bytes"], "input_sha256": r["actual_sha256"],
                "checkpoint": str(work / "checkpoints" / f"{r['month']}.npz"),
                "settings": settings.dictionary(), "run_fingerprint": fingerprint})
        print(f"Scanning {len(jobs)} months with {args.workers} workers; run {fingerprint[:16]}", flush=True)
        ctx = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers, mp_context=ctx) as executor:
            futures = {executor.submit(month_job, job): job["month"] for job in jobs}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                print(f"MONTH_OK {result['month']} rows={result['counts']['rows']:,} resumed={result['resumed']}", flush=True)
        for path, signature in snapshots.items():
            require(stat_signature(path) == signature, "Authenticated input changed during run")
        pooled = Moments(settings)
        monthly_counts, monthly_rows = [], []
        for job in jobs:
            meta = {k: job[k] for k in ("month", "run_fingerprint", "input_sha256")}
            stats = load_checkpoint(job["checkpoint"], settings, meta)
            pooled.merge(stats)
            monthly_counts.append(stats.n)
            for g in np.flatnonzero(stats.n):
                monthly_rows.append({"month": job["month"], "cell_id": int(g),
                    "opportunities": int(stats.n[g]), "kind_draws": int(stats.events[g])})
        require(pooled.counts == EXPECTED, f"Current sample count reconciliation failed: {pooled.counts}")
        staging = work / "report_building"
        if staging.exists(): shutil.rmtree(staging)
        staging.mkdir()
        common.atomic_json(staging / "RUN_IDENTITY.json", identity)
        input_manifest = [{k: v for k, v in r.items() if k != "path"} for r in records]
        common.atomic_json(staging / "INPUT_MANIFEST.json", input_manifest)
        summary = build_report(staging, settings, pooled, np.stack(monthly_counts), monthly_rows,
                               lineage, fingerprint)
        require(not report.exists(), "Incomplete report directory exists; inspect before rerunning")
        os.replace(staging, report)
        deliver(report, args.transfer_root, fingerprint)
        print(f"Covered by supported display cells: {summary['share_of_sample_in_supported_display_cells']:.1%}")
        print(f"Adjusted display cells outside 0–100%: {summary['adjusted_display_cells_outside_0_100']}")
        print(f"Elapsed: {(time.monotonic()-started)/60:.1f} minutes", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"SURFACE_RUN_FAILED: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
