#!/usr/bin/env python3
"""Authenticate the package, selected panel, Wave-2A gate, and chronology."""

from __future__ import annotations

import argparse
import csv
import shutil
from pathlib import Path

from runner import common


EXPECTED_PREFLIGHT_STATUS = "POOL_MAIN_WAVE2B_PREFLIGHT_READY"
EXPECTED_PREFLIGHT_SHA256 = "4301a2a69fd2c7d8862d0858cad0e01ab161a048243c2dada17d14860c560ece"
EXPECTED_CHRONOLOGY_MANIFEST_SHA256 = (
    "1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd"
)


def parse_args() -> argparse.Namespace:
    authority = common.load_json(common.AUTHORITY_PATH)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--hash-workers", type=int, default=8)
    parser.add_argument("--min-free-gb", type=float, default=100.0)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    package = common.verify_package_manifest()
    dependencies = common.verify_runtime_dependencies()
    auth = common.authenticate_sample(
        args.sample_root, verify_hashes=True, hash_workers=args.hash_workers
    )
    frozen_path = common.PACKAGE_ROOT / "authority/DYNAMICS_REBUILD_PREFLIGHT.json"
    observed_frozen_sha = common.sha256_file(frozen_path)
    if observed_frozen_sha != EXPECTED_PREFLIGHT_SHA256:
        raise RuntimeError(
            f"Bundled Wave-2A preflight SHA changed: {observed_frozen_sha}"
        )
    frozen = common.load_json(frozen_path)
    if frozen.get("status") != EXPECTED_PREFLIGHT_STATUS:
        raise RuntimeError("Wave-2A did not clear the Wave-2B preflight gate")
    frozen_sample = frozen.get("sample_authority") or {}
    if frozen_sample.get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Wave-2A gate belongs to another main sample")
    chronology = frozen.get("canonical_chronology") or {}
    manifest = Path(str(chronology.get("manifest", "")))
    if not manifest.is_file():
        raise RuntimeError(f"Canonical chronology manifest is missing: {manifest}")
    if common.sha256_file(manifest) != EXPECTED_CHRONOLOGY_MANIFEST_SHA256:
        raise RuntimeError("Canonical chronology manifest changed after Wave 2A")
    with manifest.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if len(rows) != int(chronology["files"]):
        raise RuntimeError("Chronology manifest file count changed")
    missing = []
    size_mismatch = []
    total_rows = 0
    for row in rows:
        path = Path(row["path"])
        if not path.is_file():
            missing.append(str(path))
            continue
        if path.stat().st_size != int(row["bytes"]):
            size_mismatch.append(str(path))
        total_rows += int(row["rows"])
    if missing or size_mismatch or total_rows != int(chronology["rows"]):
        raise RuntimeError(
            "Chronology physical inventory changed: "
            f"missing={missing[:3]} size_mismatch={size_mismatch[:3]} rows={total_rows}"
        )
    project = args.project_root.expanduser().resolve()
    if not project.is_dir():
        raise RuntimeError(f"Project root is unavailable: {project}")
    free_gb = shutil.disk_usage(project).free / 1024**3
    if free_gb < args.min_free_gb:
        raise RuntimeError(
            f"Wave 2B1 requires {args.min_free_gb:.0f} GiB free; found {free_gb:.1f} GiB"
        )
    receipt = {
        "status": "POOL_MAIN_WAVE2B1_PREFLIGHT_OK",
        "created_at_utc": common.utc_now(),
        "package": package,
        "runtime": dependencies,
        "sample_authority": common.compact_sample_lineage(auth),
        "wave2a_gate": {
            "status": frozen["status"],
            "sha256": observed_frozen_sha,
        },
        "chronology": {
            "manifest": str(manifest),
            "manifest_sha256": EXPECTED_CHRONOLOGY_MANIFEST_SHA256,
            "files": len(rows),
            "rows": total_rows,
            "physical_inventory_verified": True,
        },
        "free_gb": free_gb,
        "network_requests": 0,
    }
    common.atomic_json(args.receipt.resolve(), receipt)
    print(receipt["status"], flush=True)
    return receipt


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
