#!/usr/bin/env python3
"""Collect aggregate-only Wave 2B2A outputs into a return archive."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runner import common
from runner.orchestrate import C7R_STATUS, C7X_STATUS, _completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-root", type=Path, required=True)
    parser.add_argument("--private-base", type=Path, required=True)
    parser.add_argument("--public-base", type=Path, required=True)
    parser.add_argument("--transfer-root", type=Path, required=True)
    return parser.parse_args()


def _privacy_scan(root: Path) -> dict[str, Any]:
    forbidden = {
        "game_id",
        "chooser_id",
        "opponent_id",
        "chooser_user_id",
        "disconnected_user_id",
        "username",
        "username_norm",
    }
    violations: list[dict[str, Any]] = []
    csv_files = 0
    parquet_files = 0
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError("pyarrow is required for the transfer privacy scan") from exc
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        names: list[str] = []
        if path.suffix.lower() == ".csv":
            csv_files += 1
            with path.open(encoding="utf-8", newline="") as stream:
                names = next(csv.reader(stream), [])
        elif path.suffix.lower() == ".parquet":
            parquet_files += 1
            names = list(pq.ParquetFile(path).schema_arrow.names)
        overlap = sorted(forbidden & {str(name).lower() for name in names})
        if overlap:
            violations.append(
                {"path": path.relative_to(root).as_posix(), "forbidden_columns": overlap}
            )
    if violations:
        raise RuntimeError(f"Wave 2B2A transfer privacy scan failed: {violations[:10]}")
    return {
        "status": "POOL_MAIN_WAVE2B2A_PUBLIC_TRANSFER_PRIVACY_OK",
        "csv_files_scanned": csv_files,
        "parquet_files_scanned": parquet_files,
        "forbidden_identifier_columns": sorted(forbidden),
        "violations": 0,
    }


def _scope(auth: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "POOL_MAIN_WAVE2B2A_SCOPE_DECLARED_OK",
        "sample_authority": common.compact_sample_lineage(auth),
        "included": [
            "C7X full selected-panel latest reversed-arm analysis, with its primary retained as not estimable under the frozen 1,000-rows-per-arm gate",
            "C7X duplicate-order, same-speed, exclusive-history, recency, tie-independent, nontournament, and ply>10 diagnostics",
            "C7R exact first-versus-repeat meeting closure",
            "C7R chooser/opponent and directed-pair relationship attempts, including ply>10 and <=7-day models, explicitly labeled with the failed parent-C7X support gate",
        ],
        "historical_reference_policy": (
            "The former 2% sample support and outcome cells are retained as diagnostics, "
            "not equality gates, because the main sample authority changed."
        ),
        "c7x_c7r_gate_policy": (
            "C7X produced no selected-panel primary estimate because its frozen support "
            "gate failed. The same-run C7R reproduction gate is therefore not applicable; "
            "C7R first/repeat estimates remain independent, and C7R relationship attempts "
            "are retained only as explicitly low-support exploratory diagnostics."
        ),
        "still_blocked": [
            "Frequent-dyad census sensitivity on the new C7X classification",
            "Campaign-1 C1/C6/C9/C12/C13 recovery, remaining ply retrofits, and manuscript-wide Holm reconciliation (Wave 2B2B)",
            "Patron matching and Patron heterogeneity (Wave 3)",
            "unified manuscript tables, figures, abstract count, and final section 5-6 numerical revision",
        ],
        "manuscript_policy": (
            "These results may be drafted into a tracked provisional manuscript, but final "
            "section 5-6 numbers and paper-wide claims remain gated on Waves 2B2B and 3."
        ),
    }


def run(args: argparse.Namespace) -> tuple[Path, Path]:
    public = args.public_base.expanduser().resolve()
    private = args.private_base.expanduser().resolve()
    transfer = args.transfer_root.expanduser().resolve()
    status_path = public / "WAVE2B2A_RUN_STATUS.json"
    status = common.load_json(status_path)
    if status.get("status") != "POOL_MAIN_WAVE2B2A_ALL_STAGES_OK":
        raise RuntimeError("Wave 2B2A stage chain is not certified complete")
    auth = common.authenticate_sample(args.sample_root, verify_hashes=False)
    if (status.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
        raise RuntimeError("Wave 2B2A status belongs to another sample")
    c7x = _completed(Path(status["results"]["c7x"]["root"]), C7X_STATUS)
    c7r = _completed(Path(status["results"]["c7r"]["root"]), C7R_STATUS)
    if c7x is None or c7r is None:
        raise RuntimeError("A Wave 2B2A result disappeared before collection")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"POOL_MAIN_REANALYSIS_WAVE2B2A_RESULTS_{stamp}"
    staging = public / f".{name}.staging"
    final = public / name
    if staging.exists() or final.exists():
        raise RuntimeError(f"Wave 2B2A collection target already exists: {name}")
    staging.mkdir(parents=True)
    try:
        results = staging / "results"
        results.mkdir()
        shutil.copytree(Path(c7x["root"]), results / "c7x")
        shutil.copytree(Path(c7r["root"]), results / "c7r")
        receipts = staging / "receipts"
        receipts.mkdir()
        for path in (public / "PREFLIGHT.json", status_path):
            if not path.is_file():
                raise RuntimeError(f"Wave 2B2A receipt is missing: {path}")
            shutil.copy2(path, receipts / path.name)
        binding_root = private / "source_bindings"
        if not binding_root.is_dir():
            raise RuntimeError("Wave 2B2A source-binding receipts are missing")
        shutil.copytree(binding_root, receipts / "source_bindings")
        authority = staging / "authority"
        authority.mkdir()
        for filename in (
            "SAMPLE_AUTHORITY.json",
            "WAVE2B1_RUN_STATUS.json",
            "WAVE2B1_HISTORY_SUCCESS.json",
            "WAVE2B1_HISTORY_SUMMARY.json",
        ):
            shutil.copy2(common.PACKAGE_ROOT / "authority" / filename, authority / filename)
        common.atomic_json(staging / "PUBLICATION_SCOPE.json", _scope(auth))
        common.atomic_text(
            staging / "README.md",
            "# Pool-main reanalysis — Wave 2B2A\n\n"
            "Aggregate-only targeted-memory support results and exact first/repeat "
            "closure results, rebuilt on the certified pool/non-adjacent 24-month panel.\n\n"
            "The C7X primary is retained as not estimable under its frozen support gate. "
            "C7R first/repeat estimates are unaffected by that disposition.\n\n"
            "The former 2% sample cells are diagnostic only. See `PUBLICATION_SCOPE.json` "
            "for the remaining manuscript gates.\n",
        )
        success = {
            "status": "POOL_MAIN_REANALYSIS_WAVE2B2A_RESULTS_OK",
            "created_at_utc": common.utc_now(),
            "sample_authority": common.compact_sample_lineage(auth),
            "modules": {"c7x": C7X_STATUS, "c7r": C7R_STATUS},
            "account_level_files_transferred": False,
            "private_row_level_files_transferred": False,
            "network_requests": 0,
        }
        common.atomic_json(staging / "_SUCCESS.json", success)
        common.atomic_json(staging / "PRIVACY_SCAN.json", _privacy_scan(staging))
        common.write_manifest_tsv(staging)
        os.replace(staging, final)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    transfer.mkdir(parents=True, exist_ok=True)
    archive = transfer / f"{name}.zip"
    sidecar = archive.with_suffix(archive.suffix + ".sha256")
    if archive.exists() or sidecar.exists():
        raise RuntimeError(f"Transfer artifact already exists: {archive}")
    common.zip_tree(final, archive)
    with zipfile.ZipFile(archive) as handle:
        bad = handle.testzip()
    if bad is not None:
        raise RuntimeError(f"Wave 2B2A ZIP CRC failure: {bad}")
    digest = common.sha256_file(archive)
    common.atomic_text(sidecar, f"{digest}  {archive.name}\n")
    common.atomic_json(
        public / "WAVE2B2A_TRANSFER.json",
        {
            "status": "POOL_MAIN_REANALYSIS_WAVE2B2A_TRANSFER_OK",
            "created_at_utc": common.utc_now(),
            "archive": str(archive),
            "archive_bytes": archive.stat().st_size,
            "archive_sha256": digest,
            "sidecar": str(sidecar),
            "zip_crc_clean": True,
            "sample_fingerprint": auth["fingerprint"],
        },
    )
    print("POOL_MAIN_REANALYSIS_WAVE2B2A_TRANSFER_OK", flush=True)
    print(f"RESULT_ZIP: {archive}", flush=True)
    print(f"RESULT_SIDECAR: {sidecar}", flush=True)
    print(f"RESULT_SHA256: {digest}", flush=True)
    return archive, sidecar


def main() -> int:
    run(parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
