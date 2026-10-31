#!/usr/bin/env python3
"""Create a disclosure-safe Wave-1 result ZIP and checksum sidecar."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from runner import common
from runner.run_controlled_reference import FIGURE_STATUS
from runner.run_core import STATUS as CORE_STATUS
from runner.run_krd import STATUS as KRD_STATUS
from runner.run_nonparametric import STATUS as NONPARAM_STATUS
from runner.run_panel_robustness import STATUS as ROBUSTNESS_STATUS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--transfer-root", type=Path, required=True)
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    public = args.public_base.resolve()
    private = args.private_base.resolve()
    expected = {
        public / "core_stage08/_SUCCESS.json": CORE_STATUS,
        public / "panel_robustness_stage09/_SUCCESS.json": ROBUSTNESS_STATUS,
        private / "rating_gap_krd/settings.json": KRD_STATUS,
        private / "rating_gap_nonparametric/settings.json": NONPARAM_STATUS,
        public / "controlled_reference_figure_v111/receipts/completion_receipt.json": FIGURE_STATUS,
    }
    for path, status in expected.items():
        common.verify_lineaged_json(path, status, auth["fingerprint"])

    transfer = args.transfer_root.expanduser().resolve()
    transfer.mkdir(parents=True, exist_ok=True)
    run_id = common.utc_now().replace("-", "").replace(":", "")
    run_id = run_id.replace("T", "T").removesuffix("Z") + "Z"
    name = f"POOL_MAIN_REANALYSIS_WAVE1_RESULTS_{run_id}"
    archive = transfer / f"{name}.zip"
    sidecar = transfer / f"{name}.zip.sha256"
    if archive.exists() or sidecar.exists():
        raise RuntimeError(f"Transfer destination already exists: {archive}")

    temporary_parent = Path(tempfile.mkdtemp(prefix="pool_main_wave1_transfer_", dir=transfer))
    staging = temporary_parent / name
    try:
        staging.mkdir()
        modules = staging / "modules"
        modules.mkdir()
        common.copytree_filtered(public / "core_stage08", modules / "core_stage08")
        common.copytree_filtered(
            public / "panel_robustness_stage09", modules / "panel_robustness_stage09"
        )
        common.copytree_filtered(private / "rating_gap_krd", modules / "rating_gap_krd")
        common.copytree_filtered(
            private / "rating_gap_nonparametric", modules / "rating_gap_nonparametric"
        )
        common.copytree_filtered(
            public / "controlled_reference_model_v110",
            modules / "controlled_reference_model_v110",
        )
        common.copytree_filtered(
            public / "controlled_reference_figure_v111",
            modules / "controlled_reference_figure_v111",
        )

        for name_to_copy in (
            "WAVE1_RUN_STATUS.json",
            "PREFLIGHT.json",
            "RUN_COMMAND.txt",
            "ANALYSIS_RESET_LEDGER.json",
            "ANALYSIS_RESET_LEDGER.md",
        ):
            source = public / name_to_copy
            if source.is_file():
                shutil.copy2(source, staging / name_to_copy)
        common.copytree_filtered(common.PACKAGE_ROOT / "source", staging / "source")
        common.copytree_filtered(common.PACKAGE_ROOT / "runner", staging / "runner")
        common.copytree_filtered(common.PACKAGE_ROOT / "authority", staging / "authority")
        common.copytree_filtered(common.PACKAGE_ROOT / "evidence", staging / "evidence")
        for package_file in (
            "README_FIRST.md",
            "requirements.lock.txt",
            "PACKAGE_MANIFEST.sha256",
        ):
            source = common.PACKAGE_ROOT / package_file
            if source.is_file():
                shutil.copy2(source, staging / package_file)

        summary = {
            "status": "POOL_MAIN_REANALYSIS_WAVE1_TRANSFER_OK",
            "created_at_utc": common.utc_now(),
            "sample_authority": common.compact_sample_lineage(auth),
            "completed_modules": {
                "core_stage08": CORE_STATUS,
                "panel_robustness_stage09": ROBUSTNESS_STATUS,
                "rating_gap_krd": KRD_STATUS,
                "rating_gap_nonparametric": NONPARAM_STATUS,
                "controlled_reference_figure": FIGURE_STATUS,
            },
            "excluded_private_material": [
                "chooser/game identifiers",
                "K/RD row cache",
                "nonparametric model cache and spill",
                "controlled-reference row caches",
                "DuckDB work databases",
            ],
            "downstream_status": (
                "All pre-existing sample-dependent dynamics, dyad, Patron, and manuscript "
                "estimates remain stale until later reset waves complete."
            ),
        }
        common.atomic_json(staging / "_SUCCESS.json", summary)
        common.atomic_text(
            staging / "UPLOAD_THIS.txt",
            f"Upload {archive.name} and its .sha256 sidecar for result review and Wave 2.\n",
        )
        privacy = common.privacy_scan(staging)
        common.atomic_json(staging / "PRIVACY_AUDIT.json", privacy)
        common.write_manifest_tsv(staging)
        common.zip_tree(staging, archive)
        common.atomic_text(sidecar, f"{common.sha256_file(archive)}  {archive.name}\n")
    finally:
        shutil.rmtree(temporary_parent)

    result = {
        "status": "POOL_MAIN_REANALYSIS_WAVE1_TRANSFER_OK",
        "archive": str(archive),
        "archive_sha256": common.sha256_file(archive),
        "sidecar": str(sidecar),
    }
    print(result["status"], flush=True)
    print(f"UPLOAD: {archive}", flush=True)
    print(f"UPLOAD: {sidecar}", flush=True)
    return result


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
