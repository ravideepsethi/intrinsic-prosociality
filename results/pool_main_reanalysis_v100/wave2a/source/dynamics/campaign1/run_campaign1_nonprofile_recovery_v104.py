#!/usr/bin/env python3
"""Authenticated Campaign 1 non-profile recovery v1.0.4.

Imports the authenticated prior aggregates, preserves the frozen v1.0.3 C13
denominator correction, corrects the all-panel-versus-fair-sample numerator
assertion using a pre-existing certified Stage-09 authority, and completes every
C13 model with retained model-level failures.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
from pathlib import Path
import shutil
import time
import traceback
from typing import Any, Mapping, Sequence
import uuid

import campaign1_c12_supplement_v103 as c12_supplement
import campaign1_c12_v102 as c12
import campaign1_c13_v104 as c13
import campaign1_nonprofile_common_v102 as common


SCRIPT_VERSION = "1.0.4"
PROJECT_AUTHORITY = Path("/Volumes/XT_Pro/lichess_kindness")
C12_SOURCE_STATE_NAME = "dynamics_campaign1_nonprofile_recovery_v101_PRIVATE"
C13_SOURCE_STATE_NAME = "dynamics_campaign1_nonprofile_recovery_v102_PRIVATE"
STATE_NAME = "dynamics_campaign1_nonprofile_recovery_v104_PRIVATE"
OUTPUT_NAME = "dynamics_campaign1_nonprofile_recovery_v104"

PRIOR_V102_RESULT_BUNDLE_SHA256 = (
    "e7df2a259ce3ea2a6392a8f0528e11fc4430ddea98bfb75cc7adb29d56327e76"
)
PRIOR_V103_RESULT_BUNDLE_SHA256 = (
    "e5a3d3ec3adaf337311ccb3ebe5005312bb90a5a53bbaccf2dfa77c990f1bb48"
)
PRIOR_V103_CONFIG_SHA256 = (
    "96ed6324042c95a5e8d465412e5dbb79950a0261df47136bae231efa706e2492"
)
PRIOR_V103_REPORT_MANIFEST_SHA256 = (
    "90e7f29a1c8eecf7ee342720e71ad25fbfe53c118b59c90993e4bcc1ff430425"
)
PRIOR_V103_FAILURE_SHA256 = (
    "e590d9116fe5c6970333b4550ab7f8e769d75a68841e3e80b9a3cad8b9750a32"
)
PRIOR_V103_MODULE_STATUS_SHA256 = (
    "6bd3fb140d054e15d0658deafbf9fce1aeb9385a9df86ac57d5ee21778e07d28"
)
PRIOR_V103_INSPECTION_SHA256 = (
    "d338200e7ffc1764b0c76dfc153245c9685d71bc8871080ae9f4ecef61d449f3"
)
PRIOR_V103_C12_RESULTS_SHA256 = (
    "ee730fd9edae749248c04ce6923a4f308a45fa9e20c913b432e4d319fb4b447f"
)
PRIOR_V103_C12_SUMMARY_SHA256 = (
    "383d7382171d5fb79205abba53e3ee90402040dd6ccc7f74abd904ec34dcc3e5"
)
PRIOR_V103_C13_SUPPORT_SHA256 = (
    "370d787885fc16a936fbaf3b4e1111bec9b6b34e5f552d374f6c76f058776b1f"
)
PRIOR_V103_C13_RECONCILIATION_SHA256 = (
    "009b20d0aeb21505eeb33c36cce4b8d2ef68e849d2668bc487821ae15bf2f24b"
)
PRIOR_V102_CONFIG_SHA256 = (
    "562389a1fd24ba3edfb49cbc4e79d4c34847bca725a1da003dc154c936730555"
)
C12_SOURCE_CONFIG_SHA256 = (
    "f44a90e424dc8400891277caa85104a1b4d97fd29ca984a5e07f1d4794c379dc"
)
C12_SOURCE_MANIFEST_SHA256 = (
    "a19d1be385b8207ac6cab6f49c179ea906e59dd71a7c08f17737eeb364d98681"
)
PRIOR_V102_REPORT_MANIFEST_SHA256 = (
    "014f00fd15fc6738509c5c07e0814fb7ae1205375438a520213ae8f961f2c3eb"
)
PRIOR_V102_FAILURE_SHA256 = (
    "b0ab8596334232306c369402efe26bb0119e3363de17ac388f4d1e493201cb26"
)
PRIOR_V102_MODULE_STATUS_SHA256 = (
    "aa8027e84d83638f8e2d3f411eb243629065969e49173c91311f04c8dabef87b"
)
PRIOR_V102_INSPECTION_SHA256 = (
    "78222cb3139a7ec419bff5f60001c0cfb2d0a2bf90e5c01080b7fa1176287f4a"
)
PRIOR_V102_C12_RESULTS_SHA256 = (
    "7c1ebc5a22c8d7fba1ab83ce57db9c9a9b7fa8fda6ba36893bda322fda55be66"
)
PRIOR_V102_C12_SUMMARY_SHA256 = (
    "eb17480e70c5c4a772aa47ae57e5080e2580f3ef6b09d44678d86ca4a2877770"
)
WAVE0_HASHES = {
    "c13_support_only.json": "1f69ab4663c92a8246f0617acf824c03c598a7849e1c74b1ce324644cca763fe",
    "summary.json": "46e274ef86812faf33178ceecf88ca686bcd4a2be35267fb63fba345e0548f05",
    "stage07_field_mapping.json": "4cfce6356a6aa99994a94fb9361802efe392b05b45776dfbeaf09cbc5924550b",
    "report_file_hashes.tsv": "08aaadd8cde1c70c717c41fd38a35f16c1428d9b30281c4e2d610164e32703cf",
}
EXPECTED_PLAN_HASHES = {
    "dynamics_paper2_campaign1_analysis_plan_v1_0_0.md":
        "ded9965994b6c00ed613adc90eaff3f976b257e9eb6dafdda61819916dde49fe",
    "dynamics_paper2_campaign1_analysis_plan_v1_0_1_amendment.md":
        "01c0ed96bfca62b1659a98d978bedaaf9a4540fcdc5a30a075e2f032e35e05ee",
    "dynamics_paper2_campaign1_analysis_plan_v1_0_2_amendment.md":
        "7eeca3ab8591620a196badbd1b9d3184236d67a031cf9eff06b76584995c0049",
    "dynamics_paper2_campaign1_analysis_plan_v1_0_3_amendment.md":
        "96530f7ffd43b7d68ff84c794200f7db98b2b455ea2994efb5b73ce5cb370a07",
    "dynamics_paper2_campaign1_v1_0_5_postoutcome_correction.md":
        "14cb718408788ea15f94d555eaabc84c27f2dc42b1ca85c03b46daf43e366787",
}
EXPECTED_FAILED_C13_SOURCE_SHA256 = (
    "7d920ed8ff8f18c81d722851c004a2986d96c8d9409e3ce3f6652c871257c9ef"
)
EXPECTED_FAILED_C13_V103_SOURCE_SHA256 = (
    "b0dd2592a2947450000cc89169c53fe5396ecc3934863a24d5f87821d5cb402c"
)
STAGE09_NUMERATOR_SUMMARY_SHA256 = (
    "5107e4dabd11054724691f6c3c6937e495b8b15648302ecd578217e81d55b6e7"
)
STAGE09_NUMERATOR_SCRIPT_SHA256 = (
    "f0b3d8d638523e22e4bc3b665d3067a261bcfb1c3d2831d9bf8fb81e6c521431"
)
MINIMUM_FREE_BYTES = 25 * 1024**3


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_AUTHORITY)
    parser.add_argument("--run-id")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--execution-pointer", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def packaged_files(root: Path) -> list[dict[str, Any]]:
    manifest_path = root / "PACKAGE_CONTENTS.sha256"
    if not manifest_path.is_file():
        raise RuntimeError("Package content manifest is missing")
    rows: list[dict[str, Any]] = []
    for raw in manifest_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        digest, relative = raw.split(None, 1)
        relative = relative.lstrip("* ")
        path = root / relative
        if not path.is_file() or common.sha256_file(path) != digest:
            raise RuntimeError(f"Packaged-file authentication failed: {relative}")
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": digest})
    return sorted(rows, key=lambda row: row["path"])


def authenticate_prior_v102_evidence(root: Path) -> dict[str, Any]:
    prior = root / "payload/prior_evidence/nonprofile_recovery_v102_failed"
    manifest_path = prior / "report_file_hashes.tsv"
    if common.sha256_file(manifest_path) != PRIOR_V102_REPORT_MANIFEST_SHA256:
        raise RuntimeError("Packaged v1.0.2 public-result manifest changed")
    with manifest_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    expected = {row["file"] for row in rows}
    actual = {
        path.relative_to(prior).as_posix()
        for path in prior.rglob("*")
        if path.is_file()
        and path.name not in {"report_file_hashes.tsv", "COLLECTION_INSPECTION.json"}
    }
    if expected != actual:
        raise RuntimeError(
            "Packaged v1.0.2 evidence inventory changed: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    for row in rows:
        path = prior / row["file"]
        if path.stat().st_size != int(row["bytes"]) or common.sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Packaged v1.0.2 evidence changed: {row['file']}")
    checks = {
        prior / "FAILURE_DIAGNOSTIC.json": PRIOR_V102_FAILURE_SHA256,
        prior / "module_status_checkpoint.json": PRIOR_V102_MODULE_STATUS_SHA256,
        prior / "COLLECTION_INSPECTION.json": PRIOR_V102_INSPECTION_SHA256,
        prior / "C12/c12_results.json": PRIOR_V102_C12_RESULTS_SHA256,
        prior / "C12/summary.json": PRIOR_V102_C12_SUMMARY_SHA256,
    }
    for path, digest in checks.items():
        if common.sha256_file(path) != digest:
            raise RuntimeError(f"Packaged v1.0.2 evidence fingerprint changed: {path.name}")
    failure = common.load_json(prior / "FAILURE_DIAGNOSTIC.json")
    expected_error = (
        "C13 frozen support failed to reproduce Wave 0: rows=17328130 "
        "unique=17328130 primary=17101141 expected=17104149 negative=0 "
        "min/p10/median=(0, 28081.0, 136490.0)"
    )
    if (
        failure.get("status") != "DYNAMICS_CAMPAIGN1_NONPROFILE_RECOVERY_V102_FAILED_CLOSED"
        or failure.get("config_sha256") != PRIOR_V102_CONFIG_SHA256
        or failure.get("error") != expected_error
    ):
        raise RuntimeError("Packaged v1.0.2 failure fingerprint changed")
    return {
        "source_bundle_sha256": PRIOR_V102_RESULT_BUNDLE_SHA256,
        "report_manifest_sha256": PRIOR_V102_REPORT_MANIFEST_SHA256,
        "failure_diagnostic_sha256": PRIOR_V102_FAILURE_SHA256,
        "module_status_sha256": PRIOR_V102_MODULE_STATUS_SHA256,
        "collection_inspection_sha256": PRIOR_V102_INSPECTION_SHA256,
        "files_authenticated": len(rows),
        "private_row_level_files_embedded": False,
    }


def authenticate_prior_v103_evidence(root: Path) -> dict[str, Any]:
    prior = root / "payload/prior_evidence/nonprofile_recovery_v103_failed"
    manifest_path = prior / "report_file_hashes.tsv"
    if common.sha256_file(manifest_path) != PRIOR_V103_REPORT_MANIFEST_SHA256:
        raise RuntimeError("Packaged v1.0.3 public-result manifest changed")
    with manifest_path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    expected = {row["file"] for row in rows}
    actual = {
        path.relative_to(prior).as_posix()
        for path in prior.rglob("*")
        if path.is_file()
        and path.name not in {"report_file_hashes.tsv", "COLLECTION_INSPECTION.json"}
    }
    if expected != actual:
        raise RuntimeError(
            "Packaged v1.0.3 evidence inventory changed: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )
    for row in rows:
        path = prior / row["file"]
        if path.stat().st_size != int(row["bytes"]) or common.sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Packaged v1.0.3 evidence changed: {row['file']}")
    checks = {
        prior / "FAILURE_DIAGNOSTIC.json": PRIOR_V103_FAILURE_SHA256,
        prior / "module_status_checkpoint.json": PRIOR_V103_MODULE_STATUS_SHA256,
        prior / "COLLECTION_INSPECTION.json": PRIOR_V103_INSPECTION_SHA256,
        prior / "C12/c12_results.json": PRIOR_V103_C12_RESULTS_SHA256,
        prior / "C12/summary.json": PRIOR_V103_C12_SUMMARY_SHA256,
        prior / "C13/c13_support_frozen.json": PRIOR_V103_C13_SUPPORT_SHA256,
        prior / "C13/c13_denominator_reconciliation_v103.json": (
            PRIOR_V103_C13_RECONCILIATION_SHA256
        ),
    }
    for path, digest in checks.items():
        if common.sha256_file(path) != digest:
            raise RuntimeError(f"Packaged v1.0.3 evidence fingerprint changed: {path.name}")
    failure = common.load_json(prior / "FAILURE_DIAGNOSTIC.json")
    support = common.load_json(prior / "C13/c13_support_frozen.json")
    reconciliation = common.load_json(
        prior / "C13/c13_denominator_reconciliation_v103.json"
    )
    if (
        failure.get("status")
        != "DYNAMICS_CAMPAIGN1_NONPROFILE_RECOVERY_V103_FAILED_CLOSED"
        or failure.get("config_sha256") != PRIOR_V103_CONFIG_SHA256
        or failure.get("error")
        != "C13 kindness numerator authority failed: (17328130, 17328130, 487170, 0)"
        or support.get("primary_supported_rows") != c13.EXPECTED_PRIMARY_SUPPORTED_ROWS
        or support.get("ambient_kindness_numerator_read") is not False
        or reconciliation.get("selection_on_c13_outcome") is not False
    ):
        raise RuntimeError("Packaged v1.0.3 failure fingerprint changed")
    return {
        "source_bundle_sha256": PRIOR_V103_RESULT_BUNDLE_SHA256,
        "report_manifest_sha256": PRIOR_V103_REPORT_MANIFEST_SHA256,
        "failure_diagnostic_sha256": PRIOR_V103_FAILURE_SHA256,
        "module_status_sha256": PRIOR_V103_MODULE_STATUS_SHA256,
        "collection_inspection_sha256": PRIOR_V103_INSPECTION_SHA256,
        "c13_support_sha256": PRIOR_V103_C13_SUPPORT_SHA256,
        "c13_reconciliation_sha256": PRIOR_V103_C13_RECONCILIATION_SHA256,
        "files_authenticated": len(rows),
        "private_row_level_files_embedded": False,
    }


def authenticate_numerator_authority(root: Path) -> dict[str, Any]:
    summary_path = (
        root / "payload/authorities/summary_stage09_panel_robustness_24m_CERTIFIED.json"
    )
    script_path = root / "payload/authorities/09_build_panel_robustness.py"
    if common.sha256_file(summary_path) != STAGE09_NUMERATOR_SUMMARY_SHA256:
        raise RuntimeError("Packaged certified Stage-09 numerator summary changed")
    if common.sha256_file(script_path) != STAGE09_NUMERATOR_SCRIPT_SHA256:
        raise RuntimeError("Packaged certified Stage-09 producer changed")
    summary = common.load_json(summary_path)
    if (
        summary.get("status") != "STAGE09_PANEL_ROBUSTNESS_24M_CERTIFIED_OK"
        or summary.get("created_at_utc") != "2026-08-21T13:49:49Z"
        or summary.get("stage07_summary_sha256") != c13.EXPECTED_STAGE07_SUCCESS_SHA256
        or summary.get("script_sha256") != STAGE09_NUMERATOR_SCRIPT_SHA256
        or summary.get("source_qa", {}).get("rows") != common.EXPECTED_STAGE07_ROWS
        or summary.get("source_qa", {}).get("fair_rows") != c13.EXPECTED_FAIR_ROWS
        or summary.get("source_qa", {}).get("kind_draws")
        != c13.EXPECTED_ALL_STAGE07_KIND_DRAWS
        or summary.get("economic_magnitude", {}).get("fair_kind_draws")
        != c13.EXPECTED_FAIR_KIND_DRAWS
    ):
        raise RuntimeError("Certified Stage-09 numerator values changed")
    return {
        "status": summary["status"],
        "created_at_utc": summary["created_at_utc"],
        "git": summary.get("git"),
        "summary_sha256": STAGE09_NUMERATOR_SUMMARY_SHA256,
        "producer_sha256": STAGE09_NUMERATOR_SCRIPT_SHA256,
        "stage07_summary_sha256": summary["stage07_summary_sha256"],
        "all_stage07_rows": summary["source_qa"]["rows"],
        "all_stage07_kind_draws": summary["source_qa"]["kind_draws"],
        "fair_rows": summary["source_qa"]["fair_rows"],
        "fair_kind_draws": summary["economic_magnitude"]["fair_kind_draws"],
        "predates_campaign1_c13_recovery": True,
    }


def authenticate_wave0_authority(root: Path) -> dict[str, Any]:
    wave0 = root / "payload/prior_evidence/wave0_c13_support"
    for name, digest in WAVE0_HASHES.items():
        if common.sha256_file(wave0 / name) != digest:
            raise RuntimeError(f"Packaged Wave-0 C13 authority changed: {name}")
    support = common.load_json(wave0 / "c13_support_only.json")
    summary = common.load_json(wave0 / "summary.json")
    mapping = common.load_json(wave0 / "stage07_field_mapping.json")
    if (
        support.get("focal_fair_rows") != c13.EXPECTED_FAIR_ROWS
        or support.get("supported_rows") != c13.WAVE0_PRIMARY_SUPPORTED_ROWS
        or support.get("median_other_prior28") != c13.WAVE0_PRIMARY_OTHER_N28_MEDIAN
        or support.get("p10_other_prior28") != c13.WAVE0_PRIMARY_OTHER_N28_P10
        or support.get("ambient_kindness_numerator_computed") is not False
        or summary.get("git_head") != "c0d7cb3da145b7702a6020c09f8eaf19db6fe8c1"
        or mapping.get("time_ms") != "api_last_move_at_ms"
        or mapping.get("chooser") != "chooser_username_norm"
    ):
        raise RuntimeError("Packaged Wave-0 C13 values changed")
    return {
        "result_root": (
            "/Volumes/XT_Pro/lichess_kindness/output/"
            "dynamics_campaign1_wave0_stage07_actual_v100/20260825T005552Z"
        ),
        "hashes": dict(WAVE0_HASHES),
        "git_head": summary["git_head"],
        "field_mapping": mapping,
        "ambient_kindness_numerator_computed": False,
        "executable_producer_preserved_in_git_or_result_tree": False,
    }


def authenticate_package(root: Path) -> dict[str, Any]:
    for name, digest in EXPECTED_PLAN_HASHES.items():
        if common.sha256_file(root / "payload/authorities" / name) != digest:
            raise RuntimeError(f"Packaged governing-plan authority changed: {name}")
    failed_source = root / "payload/authorities/campaign1_c13_v102_failed_source.py"
    if common.sha256_file(failed_source) != EXPECTED_FAILED_C13_SOURCE_SHA256:
        raise RuntimeError("Packaged v1.0.2 C13 source authority changed")
    failed_v103_source = root / "payload/authorities/campaign1_c13_v103_failed_source.py"
    if common.sha256_file(failed_v103_source) != EXPECTED_FAILED_C13_V103_SOURCE_SHA256:
        raise RuntimeError("Packaged v1.0.3 C13 source authority changed")
    ledger = root / "payload/authorities/CAMPAIGN1_RESULTS_LEDGER_v1_0_0_2026-08-25.json"
    if common.load_json(ledger).get("artifact") != "CAMPAIGN1_RESULTS_LEDGER":
        raise RuntimeError("Packaged Campaign 1 ledger is invalid")
    prior = authenticate_prior_v102_evidence(root)
    prior_v103 = authenticate_prior_v103_evidence(root)
    numerator = authenticate_numerator_authority(root)
    wave0 = authenticate_wave0_authority(root)
    return {
        "package_manifest_sha256": common.sha256_file(root / "PACKAGE_CONTENTS.sha256"),
        "packaged_files_sha256": common.sha256_json(packaged_files(root)),
        "plan_hashes": dict(EXPECTED_PLAN_HASHES),
        "ledger_sha256": common.sha256_file(ledger),
        "failed_c13_source_sha256": common.sha256_file(failed_source),
        "failed_c13_v103_source_sha256": common.sha256_file(failed_v103_source),
        "prior_v102": prior,
        "prior_v103": prior_v103,
        "c13_fair_numerator_authority": numerator,
        "wave0_c13": wave0,
    }


def private_checkpoint_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if "duckdb_temp" in path.parts or ".tmp." in path.name:
            continue
        rows.append(
            {
                "file": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": common.sha256_file(path),
            }
        )
    return rows


def authenticate_c12_source_state(project: Path) -> tuple[Path, list[dict[str, Any]]]:
    state = project / "derived/replication" / C12_SOURCE_STATE_NAME
    config_path = state / "CONFIG.json"
    c12_state = state / "C12"
    if not config_path.is_file() or not c12_state.is_dir():
        raise RuntimeError("Required v1.0.1 C12 private state is missing")
    saved = common.load_json(config_path)
    if (
        saved.get("status") != "CAMPAIGN1_NONPROFILE_PRIVATE_STATE_OK"
        or saved.get("config_sha256") != C12_SOURCE_CONFIG_SHA256
        or common.sha256_json(saved.get("config")) != C12_SOURCE_CONFIG_SHA256
    ):
        raise RuntimeError("v1.0.1 C12 private-state configuration changed")
    manifest = private_checkpoint_manifest(c12_state)
    if common.sha256_json(manifest) != C12_SOURCE_MANIFEST_SHA256:
        raise RuntimeError("v1.0.1 C12 private checkpoint manifest changed")
    model = c12_state / "c12_model_private.parquet"
    if not model.is_file():
        raise RuntimeError("v1.0.1 C12 model Parquet is missing")
    print(
        "C12_V101_PRIVATE_CHECKPOINTS_AUTHENTICATED "
        f"files={len(manifest)} manifest_sha256={C12_SOURCE_MANIFEST_SHA256}",
        flush=True,
    )
    return model, manifest


def _authenticate_parquet_receipt(
    *, path: Path, receipt_path: Path, expected_config_sha256: str,
    expected_rows: int | None = None, expected_opportunities: int | None = None
) -> dict[str, Any]:
    _, _, _, pq = common.import_dependencies()
    if not path.is_file() or not receipt_path.is_file():
        raise RuntimeError(f"Required C13 source checkpoint is incomplete: {path}")
    receipt = common.load_json(receipt_path)
    physical_rows = int(pq.ParquetFile(path).metadata.num_rows)
    if (
        receipt.get("config_sha256") != expected_config_sha256
        or receipt.get("output_sha256") != common.sha256_file(path)
        or int(receipt.get("rows", -1)) != physical_rows
        or (expected_rows is not None and physical_rows != expected_rows)
        or (
            expected_opportunities is not None
            and int(receipt.get("opportunities", -1)) != expected_opportunities
        )
    ):
        raise RuntimeError(f"C13 source checkpoint authentication failed: {path.name}")
    return receipt


def authenticate_c13_source_state(
    project: Path,
) -> tuple[Path, dict[str, Path], list[dict[str, Any]]]:
    state = project / "derived/replication" / C13_SOURCE_STATE_NAME
    config_path = state / "CONFIG.json"
    c13_state = state / "C13"
    if not config_path.is_file() or not c13_state.is_dir():
        raise RuntimeError("Required v1.0.2 C13 denominator state is missing")
    saved = common.load_json(config_path)
    if (
        saved.get("status") != "CAMPAIGN1_NONPROFILE_PRIVATE_STATE_OK"
        or saved.get("config_sha256") != PRIOR_V102_CONFIG_SHA256
        or common.sha256_json(saved.get("config")) != PRIOR_V102_CONFIG_SHA256
    ):
        raise RuntimeError("v1.0.2 C13 private-state configuration changed")
    base = c13_state / "c13_fair_base_private.parquet"
    _authenticate_parquet_receipt(
        path=base,
        receipt_path=c13_state / "c13_fair_base_receipt.json",
        expected_config_sha256=PRIOR_V102_CONFIG_SHA256,
        expected_rows=c13.EXPECTED_FAIR_ROWS,
    )
    daily: dict[str, Path] = {}
    for label in c13.DAILY_GROUPS:
        path = c13_state / f"c13_daily_denominator_{label}_private.parquet"
        _authenticate_parquet_receipt(
            path=path,
            receipt_path=c13_state / f"c13_daily_denominator_{label}_receipt.json",
            expected_config_sha256=PRIOR_V102_CONFIG_SHA256,
            expected_opportunities=c13.EXPECTED_FAIR_ROWS,
        )
        daily[label] = path
    official_support = c13_state / "c13_denominator_support_private.parquet"
    official_receipt = c13_state / "c13_denominator_support_frozen.json"
    if official_support.exists() or official_receipt.exists():
        raise RuntimeError("v1.0.2 unexpectedly published an official C13 support checkpoint")
    required = [config_path, base, c13_state / "c13_fair_base_receipt.json"]
    for label, path in daily.items():
        required.extend(
            [path, c13_state / f"c13_daily_denominator_{label}_receipt.json"]
        )
    manifest = [
        {
            "file": path.relative_to(state).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        }
        for path in sorted(required)
    ]
    print(
        "C13_V102_OUTCOME_BLIND_DENOMINATOR_PARQUETS_AUTHENTICATED "
        f"files={len(manifest)} manifest_sha256={common.sha256_json(manifest)}",
        flush=True,
    )
    return base, daily, manifest


def authenticate_machine(project: Path) -> dict[str, Any]:
    if project.resolve() != PROJECT_AUTHORITY or not project.is_dir():
        raise RuntimeError(f"Project authority is unavailable: {project}")
    stage07 = project / "derived/replication/analysis_panel_24m_sf100k"
    stage_auth = common.authenticate_stage07(stage07, c13.EXPECTED_STAGE07_SUCCESS_SHA256)
    if common.parquet_rows(common.stage07_paths(stage07)) != common.EXPECTED_STAGE07_ROWS:
        raise RuntimeError("Physical Stage-07 row authority changed")
    return {
        "stage07_success_sha256": common.sha256_file(stage07 / "_SUCCESS.json"),
        "stage07_rows": common.EXPECTED_STAGE07_ROWS,
        "stage07_fair_rows": common.EXPECTED_STAGE07_FAIR_ROWS,
        "stage07_physical_month_manifest_sha256": stage_auth[
            "physical_month_manifest_sha256"
        ],
    }


def import_prior_modules(*, root: Path, staging: Path) -> dict[str, Any]:
    prior = root / "payload/prior_evidence/nonprofile_recovery_v102_failed"
    summaries = common.load_json(prior / "module_status_checkpoint.json")
    for module in ("C6_C10", "C7", "C12"):
        shutil.copytree(prior / module, staging / module)
    summaries["C6_C10"]["v103_disposition"] = (
        "IMPORTED_FROM_AUTHENTICATED_V102_FAILED_RESULT"
    )
    summaries["C7"]["v103_disposition"] = (
        "IMPORTED_FROM_AUTHENTICATED_V102_FAILED_RESULT"
    )
    summaries["C12"]["v103_disposition"] = (
        "AUTHENTICATED_V102_RESULTS_PLUS_EXPLICIT_2400PLUS_ATTEMPT"
    )
    return summaries


def initialize_state(state: Path, config: dict[str, Any], config_sha256: str) -> None:
    config_path = state / "CONFIG.json"
    if state.exists():
        if not config_path.is_file():
            raise RuntimeError(f"Nonempty private state lacks CONFIG.json: {state}")
        saved = common.load_json(config_path)
        if (
            saved.get("status") != "CAMPAIGN1_NONPROFILE_PRIVATE_STATE_OK"
            or saved.get("config_sha256") != config_sha256
            or saved.get("config") != config
        ):
            raise RuntimeError("Private v1.0.4 state belongs to another configuration")
        print("CAMPAIGN1_NONPROFILE_V104_PRIVATE_STATE_AUTHENTICATED_OK", flush=True)
        return
    state.mkdir(parents=True)
    common.atomic_json(
        config_path,
        {
            "status": "CAMPAIGN1_NONPROFILE_PRIVATE_STATE_OK",
            "created_utc": common.utc_now(),
            "config": config,
            "config_sha256": config_sha256,
            "privacy": "PRIVATE; DO NOT COMMIT OR PUBLISH",
        },
    )
    print("CAMPAIGN1_NONPROFILE_V104_PRIVATE_STATE_CREATED", flush=True)


def write_pointer(path: Path | None, payload: dict[str, Any]) -> None:
    if path is not None:
        common.atomic_json(path.expanduser().resolve(), payload)


def report_manifest(root: Path) -> list[dict[str, Any]]:
    excluded = {"report_file_hashes.tsv", "_SUCCESS.json"}
    return [
        {
            "file": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
        if path.name not in excluded
    ]


def write_report_manifest(root: Path) -> str:
    rows = report_manifest(root)
    path = root / "report_file_hashes.tsv"
    temporary = path.with_name(path.name + f".tmp.{uuid.uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("file", "bytes", "sha256"), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)
    return common.sha256_file(path)


def family_d_status(ledger: dict[str, Any], c6_summary: dict[str, Any]) -> dict[str, Any]:
    members = dict(ledger["family_D"])
    c6_result = c6_summary.get("C6", {})
    if bool(c6_result.get("gate_pass")):
        primary = c6_result.get("primary") or {}
        members["C6"] = {
            "status": "VALID_GATE_PASSED_HOLM_PENDING",
            "raw_p": primary.get("p_value_raw"),
            "effect": primary.get("coefficient"),
            "effect_units": primary.get("effect_units"),
        }
        effective = ["C1", "C2", "C5", "C6", "C9"]
    else:
        members["C6"] = {
            "status": "DEMOTED_BY_FROZEN_TREATMENT_BLIND_SUPPORT_GATE",
            "raw_p": None,
        }
        effective = ["C1", "C2", "C5", "C9"]
    observed = {
        name: float(members[name]["raw_p"])
        for name in effective
        if members[name].get("raw_p") is not None
    }
    missing = [name for name in effective if members[name].get("raw_p") is None]
    family_size = len(effective)
    return {
        "status": (
            "FINAL_HOLM_PENDING_MISSING_EFFECTIVE_FAMILY_MEMBER"
            if missing else "READY_FOR_FINAL_HOLM"
        ),
        "effective_members": effective,
        "family_size": family_size,
        "members": members,
        "observed_raw_p_values": observed,
        "missing_raw_p_values": missing,
        "bonferroni_guaranteed_rejections_at_0_05": [
            name for name, value in observed.items() if family_size * value <= 0.05
        ],
        "guarantee_rule": "family_size * raw_p <= 0.05; sufficient under any ordering of missing p-values",
        "invalid_C1_lineages_included": False,
        "final_holm_computed": not missing,
    }


def _required_c13_manifest(
    *, project: Path, base: Path, daily: Mapping[str, Path]
) -> list[dict[str, Any]]:
    state = project / "derived/replication" / C13_SOURCE_STATE_NAME
    c13_state = state / "C13"
    required = [state / "CONFIG.json", base, c13_state / "c13_fair_base_receipt.json"]
    for label, path in daily.items():
        required.extend([path, c13_state / f"c13_daily_denominator_{label}_receipt.json"])
    return [
        {
            "file": path.relative_to(state).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": common.sha256_file(path),
        }
        for path in sorted(required)
    ]


def execute(args: argparse.Namespace) -> Path:
    if not 1 <= args.threads <= 16:
        raise RuntimeError("threads must be 1..16")
    root = package_root()
    project = args.project_root.expanduser().resolve()
    package_authorities = authenticate_package(root)
    machine_authorities = authenticate_machine(project)
    c12_model, c12_manifest = authenticate_c12_source_state(project)
    c13_base, c13_daily, c13_source_manifest = authenticate_c13_source_state(project)
    free_bytes = shutil.disk_usage(project).free
    if free_bytes < MINIMUM_FREE_BYTES:
        raise RuntimeError(
            f"At least {MINIMUM_FREE_BYTES / 1024**3:.0f} GiB free is required; "
            f"found {free_bytes / 1024**3:.1f} GiB"
        )
    config = {
        "script_version": SCRIPT_VERSION,
        "package_authorities": package_authorities,
        "machine_authorities": machine_authorities,
        "modules": [
            "C6_C10_AUTHENTICATED_IMPORT",
            "C7_AUTHENTICATED_IMPORT",
            "C12_AUTHENTICATED_V102_PLUS_2400PLUS_ATTEMPT",
            "C13_V104_NUMERATOR_AUTHORITY_CORRECTION_AND_COMPLETION",
        ],
        "analysis_policy": (
            "attempt every scientifically useful model; retain favorable, null, adverse, "
            "low-support, and unestimable records with frozen epistemic labels"
        ),
        "prior_v102_result_bundle_sha256": PRIOR_V102_RESULT_BUNDLE_SHA256,
        "prior_v103_result_bundle_sha256": PRIOR_V103_RESULT_BUNDLE_SHA256,
        "c12_source_manifest_sha256": common.sha256_json(c12_manifest),
        "c13_source_manifest_sha256": common.sha256_json(c13_source_manifest),
        "c13_denominator_policy": {
            "wave0_supported_rows_superseded": c13.WAVE0_PRIMARY_SUPPORTED_ROWS,
            "corrected_supported_rows": c13.EXPECTED_PRIMARY_SUPPORTED_ROWS,
            "correction_frozen_before_c13_numerator": True,
            "wave0_executable_producer_preserved": False,
        },
        "c13_numerator_policy": {
            "all_stage07_kind_draws": c13.EXPECTED_ALL_STAGE07_KIND_DRAWS,
            "fair_sample_kind_draws": c13.EXPECTED_FAIR_KIND_DRAWS,
            "preexisting_stage09_authority_sha256": STAGE09_NUMERATOR_SUMMARY_SHA256,
            "correction_after_aggregate_count_before_c13_models": True,
            "selection_on_c13_model_result": False,
            "scientific_sample_or_model_changed": False,
        },
        "hdfe_numerical_policy": {
            "strict_tolerance": 1e-9,
            "strict_maximum_iterations": 2000,
            "extended_tolerance": 1e-7,
            "extended_maximum_iterations": 25000,
            "extended_retry_scope": "absorption-only nonconvergence",
            "still_unestimable_policy": "retain model-attempt failure and continue",
        },
        "c13_other_opportunity_threshold": c13.SUPPORT_THRESHOLD,
        "profile_reads": 0,
        "api_requests": 0,
    }
    config_sha256 = common.sha256_json(config)
    state = project / "derived/replication" / STATE_NAME
    initialize_state(state, config, config_sha256)
    (state / "C13").mkdir(exist_ok=True)
    output_base = project / "output" / OUTPUT_NAME
    output_base.mkdir(parents=True, exist_ok=True)
    run_id = args.run_id or common.utc_run_id()
    final = output_base / run_id
    failed = output_base / f"{run_id}_FAILED"
    if final.exists() or failed.exists():
        raise RuntimeError(f"Run output already exists: {run_id}")
    staging = output_base / f".{run_id}.tmp.{uuid.uuid4().hex}"
    staging.mkdir()
    common.atomic_json(
        staging / "input_authorities.json",
        {
            "created_utc": common.utc_now(),
            "config_sha256": config_sha256,
            "package": package_authorities,
            "machine": machine_authorities,
            "c12_source_manifest_sha256": common.sha256_json(c12_manifest),
            "c13_source_manifest_sha256": common.sha256_json(c13_source_manifest),
            "free_bytes_at_launch": free_bytes,
        },
    )
    started = time.time()
    summaries: dict[str, Any] = {}
    try:
        print("CAMPAIGN1_NONPROFILE_V104_PRIOR_AGGREGATE_IMPORT_BEGIN", flush=True)
        summaries = import_prior_modules(root=root, staging=staging)
        print("CAMPAIGN1_NONPROFILE_V104_PRIOR_AGGREGATE_IMPORT_OK", flush=True)
        common.atomic_json(staging / "module_status_checkpoint.json", summaries)

        print("CAMPAIGN1_NONPROFILE_C12_2400PLUS_SUPPLEMENT_BEGIN", flush=True)
        summaries["C12"] = c12_supplement.supplement(
            model_cache=c12_model, public_stage=staging / "C12"
        )
        after_c12 = private_checkpoint_manifest(c12_model.parent)
        if after_c12 != c12_manifest:
            raise RuntimeError("v1.0.1 C12 private checkpoints changed during supplement")
        summaries["C12"]["v101_private_checkpoint_manifest_unchanged"] = True
        summaries["C12"]["v104_disposition"] = (
            "V103_2400PLUS_RETAINED_FAILURE_EXACTLY_REPRODUCED"
        )
        summaries["C6_C10"]["v104_disposition"] = (
            "IMPORTED_AGGREGATES_AUTHENTICATED_AGAINST_V102_AND_V103"
        )
        summaries["C7"]["v104_disposition"] = (
            "IMPORTED_AGGREGATES_AUTHENTICATED_AGAINST_V102_AND_V103"
        )
        print("C12_V101_PRIVATE_CHECKPOINTS_REMAIN_IMMUTABLE_OK", flush=True)
        common.atomic_json(staging / "module_status_checkpoint.json", summaries)

        print("CAMPAIGN1_NONPROFILE_C13_V104_BEGIN", flush=True)
        summaries["C13"] = c13.execute(
            project=project,
            state=state / "C13",
            public_stage=staging / "C13",
            threads=args.threads,
            memory_limit=args.memory_limit,
            config_sha256=config_sha256,
            source_base=c13_base,
            source_daily=c13_daily,
            wave0_authority=package_authorities["wave0_c13"],
            numerator_authority=package_authorities["c13_fair_numerator_authority"],
        )
        after_c13_source = _required_c13_manifest(
            project=project, base=c13_base, daily=c13_daily
        )
        if after_c13_source != c13_source_manifest:
            raise RuntimeError("v1.0.2 C13 denominator checkpoints changed during recovery")
        summaries["C13"]["v102_denominator_checkpoint_manifest_unchanged"] = True
        common.atomic_json(staging / "module_status_checkpoint.json", summaries)

        ledger_path = root / "payload/authorities/CAMPAIGN1_RESULTS_LEDGER_v1_0_0_2026-08-25.json"
        family = family_d_status(common.load_json(ledger_path), summaries["C6_C10"])
        common.atomic_json(staging / "family_D_holm_status.json", family)
        retained = int(summaries["C12"]["retained_model_failures"]) + int(
            summaries["C13"]["retained_model_failures"]
        )
        summary = {
            "status": "DYNAMICS_CAMPAIGN1_NONPROFILE_RECOVERY_V104_OK",
            "created_utc": common.utc_now(),
            "run_id": run_id,
            "runtime_seconds": time.time() - started,
            "config_sha256": config_sha256,
            "modules": summaries,
            "family_D": family,
            "blocked_missing_profile_authority_modules": ["C4", "C5", "C11", "C14B"],
            "all_currently_available_nonprofile_analyses_attempted": True,
            "c12_all_rating_bands_attempted": True,
            "c13_all_rating_band_and_speed_subgroups_attempted": True,
            "c13_denominator_correction_frozen_before_numerator": True,
            "c13_wave0_supported_rows_superseded": c13.WAVE0_PRIMARY_SUPPORTED_ROWS,
            "c13_corrected_supported_rows": c13.EXPECTED_PRIMARY_SUPPORTED_ROWS,
            "c13_fair_sample_kind_draws": c13.EXPECTED_FAIR_KIND_DRAWS,
            "c13_all_stage07_kind_draws": c13.EXPECTED_ALL_STAGE07_KIND_DRAWS,
            "c13_numerator_authority_corrected_before_model_estimation": True,
            "c13_numerator_correction_selected_on_model_result": False,
            "model_attempt_failures_retained": retained,
            "all_model_attempts_reported": True,
            "account_level_output": False,
            "api_requests": 0,
            "profile_or_patron_reads": 0,
        }
        common.atomic_json(staging / "summary.json", summary)
        manifest_sha = write_report_manifest(staging)
        success = {
            **summary,
            "report_file_hashes_sha256": manifest_sha,
            "v104_private_state_root": str(state),
            "reused_v101_c12_private_state_root": str(c12_model.parent),
            "reused_v102_c13_denominator_state_root": str(c13_base.parent),
        }
        common.atomic_json(staging / "_SUCCESS.json", success)
        os.replace(staging, final)
        write_pointer(
            args.execution_pointer,
            {
                "status": success["status"],
                "run_id": run_id,
                "result_root": str(final),
                "success_sha256": common.sha256_file(final / "_SUCCESS.json"),
                "report_manifest_sha256": common.sha256_file(final / "report_file_hashes.tsv"),
            },
        )
        print(f"DYNAMICS_CAMPAIGN1_NONPROFILE_RECOVERY_V104_OK: {final}", flush=True)
        print(f"runtime_seconds: {time.time() - started:.1f}", flush=True)
        return final
    except BaseException as exc:
        diagnostic = {
            "status": "DYNAMICS_CAMPAIGN1_NONPROFILE_RECOVERY_V104_FAILED_CLOSED",
            "created_utc": common.utc_now(),
            "run_id": run_id,
            "runtime_seconds": time.time() - started,
            "config_sha256": config_sha256,
            "completed_modules": summaries,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        common.atomic_json(staging / "FAILURE_DIAGNOSTIC.json", diagnostic)
        write_report_manifest(staging)
        os.replace(staging, failed)
        write_pointer(
            args.execution_pointer,
            {
                "status": diagnostic["status"],
                "run_id": run_id,
                "result_root": str(failed),
                "failure_sha256": common.sha256_file(failed / "FAILURE_DIAGNOSTIC.json"),
            },
        )
        raise


def self_test() -> None:
    ledger = {
        "family_D": {
            "C1": {"raw_p": 0.006},
            "C2": {"raw_p": 0.036},
            "C5": {"raw_p": None},
            "C6": {"raw_p": None},
            "C9": {"raw_p": 0.0004},
        }
    }
    family = family_d_status(
        ledger,
        {"C6": {"gate_pass": True, "primary": {"p_value_raw": 5.3e-7, "coefficient": -1.79}}},
    )
    if family["missing_raw_p_values"] != ["C5"]:
        raise RuntimeError("Family-D status self-test failed")
    if family["bonferroni_guaranteed_rejections_at_0_05"] != ["C1", "C6", "C9"]:
        raise RuntimeError("Family-D guarantee self-test failed")
    if c13.WAVE0_PRIMARY_SUPPORTED_ROWS - c13.EXPECTED_PRIMARY_SUPPORTED_ROWS != 3_008:
        raise RuntimeError("C13 support-correction self-test failed")
    if not math.isclose(c13.EXPECTED_PRIMARY_SUPPORTED_ROWS / c13.EXPECTED_FAIR_ROWS, 0.9869009, abs_tol=1e-6):
        raise RuntimeError("C13 corrected support-share self-test failed")
    if (
        c13.EXPECTED_FAIR_KIND_DRAWS != 487_170
        or c13.EXPECTED_ALL_STAGE07_KIND_DRAWS != 669_503
    ):
        raise RuntimeError("C13 numerator-authority main self-test failed")
    print("CAMPAIGN1_NONPROFILE_RECOVERY_V104_MAIN_SELF_TEST_OK")


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
        return
    if not args.execute:
        raise SystemExit("Refusing production work without --execute")
    execute(args)


if __name__ == "__main__":
    main()
