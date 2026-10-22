#!/usr/bin/env python3
"""Offline structural and numerical tests for the Wave 2B2A launcher."""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

from runner import common
from runner.orchestrate import (
    C7X_LOW_SUPPORT_STATUS,
    _c7x_primary_authority,
    _c7x_replacements,
    _prepare_c7r,
)
from runner.retarget import retarget_source, write_package_manifest


EXPECTED_SOURCE_HASHES = {
    "source/c7x/run_campaign1_c7x_fullpanel_v101.py": "04fb1366706ed1f934f53b5f946d0dcab7480d233fa894ac7569325d9a125a98",
    "source/c7x/c7x_duplicate_order_diagnostic_v101.py": "b48f10e5aa34b5d6b6596a3e21a7ced8e9a1572928fc0cfc8d496e4dbb33767e",
    "source/c7x/campaign1_nonprofile_common_v102.py": "f629876216c797180265d1b848a4424f211fe9a43cffa4dabdb3de67acbc5f1c",
    "source/c7r/run_campaign1_c7r_closure_v102.py": "87caf0cb2c008635f9a8d0db0bd8e67f758fa10d35ae9a8b00058fe84dda1003",
    "source/c7r/c7r_modeling_v102.py": "8fe65619941f5d2712827d47ea8a56053a9d865857959243f8908c8cadcaa817",
    "source/c7r/campaign1_nonprofile_common_v102.py": "f629876216c797180265d1b848a4424f211fe9a43cffa4dabdb3de67acbc5f1c",
}


def _run_source_self_test(path: Path) -> None:
    process = subprocess.run(
        [sys.executable, "-B", str(path), "--self-test"],
        cwd=path.parent,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(f"Frozen producer self-test failed: {path}\n{process.stdout}")
    print(process.stdout.strip(), flush=True)


def main() -> int:
    package = common.verify_package_manifest()
    common.verify_runtime_dependencies()
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        path = common.PACKAGE_ROOT / relative
        observed = common.sha256_file(path)
        if observed != expected:
            raise RuntimeError(f"Recovered source hash changed: {relative}: {observed}")
    _run_source_self_test(
        common.PACKAGE_ROOT / "source/c7x/run_campaign1_c7x_fullpanel_v101.py"
    )
    _run_source_self_test(
        common.PACKAGE_ROOT / "source/c7r/run_campaign1_c7r_closure_v102.py"
    )

    with tempfile.TemporaryDirectory(prefix="wave2b2a_retarget_test_") as raw:
        root = Path(raw)
        c7x = root / "c7x/payload/code/run_campaign1_c7x_fullpanel_v101.py"
        c7x.parent.mkdir(parents=True)
        c7x_receipt = root / "c7x_binding.json"
        retarget_source(
            common.PACKAGE_ROOT / "source/c7x/run_campaign1_c7x_fullpanel_v101.py",
            c7x,
            constants={
                "PROJECT_AUTHORITY": root / "view",
                "EXPECTED_STAGE07_SUCCESS_SHA256": "a" * 64,
                "EXPECTED_STAGE07_ROWS": 41_534_331,
                "EXPECTED_FAIR_ROWS": 15_207_423,
            },
            exact_replacements=_c7x_replacements(),
            receipt=c7x_receipt,
        )
        rendered = c7x.read_text(encoding="utf-8")
        if "C7X_OLD_SAMPLE_SUPPORT_REPRODUCTION_OK" in rendered:
            raise RuntimeError("Historical C7X gate survived retargeting")
        ast.parse(rendered)

        c7r = root / "c7r/payload/code/run_campaign1_c7r_closure_v102.py"
        c7r.parent.mkdir(parents=True)
        old_gate = (
            '    if payload["rows"] != EXPECTED_C7X_CLASSIFICATION_ROWS or '
            'payload["chooser_arm_switchers"] != 370 or '
            'payload["unordered_pair_arm_switchers"] != 320:\n'
        )
        new_gate = (
            '    if payload["rows"] != EXPECTED_C7X_CLASSIFICATION_ROWS or '
            'payload["chooser_arm_switchers"] != 123 or '
            'payload["unordered_pair_arm_switchers"] != 99:\n'
        )
        retarget_source(
            common.PACKAGE_ROOT / "source/c7r/run_campaign1_c7r_closure_v102.py",
            c7r,
            constants={
                "PROJECT_AUTHORITY": root / "view",
                "HISTORY_STATE_RELATIVE": root / "history",
                "C7X_STATE_RELATIVE": root / "c7x_state",
                "EXPECTED_STAGE07_SUCCESS_SHA256": "a" * 64,
                "EXPECTED_HISTORY_SUCCESS_SHA256": "b" * 64,
                "EXPECTED_C7X_CLASSIFICATION_SHA256": "c" * 64,
                "EXPECTED_C7X_CLASSIFICATION_ROWS": 1000,
                "EXPECTED_C7X_PRIMARY_COEFFICIENT": 0.12,
                "EXPECTED_C7X_PRIMARY_STANDARD_ERROR": 0.03,
                "EXPECTED_C7X_CONFIG_SHA256": "d" * 64,
                "EXPECTED_STAGE07_ROWS": 41_534_331,
                "EXPECTED_FAIR_ROWS": 15_207_423,
                "EXPECTED_PAIR_EVENT_ROWS": 154_693_194,
            },
            exact_replacements=[
                (
                    "current-wave2b1-history-public-run",
                    "20260822T150914Z",
                    "POOL_MAIN_WAVE2B1_SECOND",
                ),
                ("current-c7x-switcher-support", old_gate, new_gate),
            ],
            receipt=root / "c7r_binding.json",
        )
        ast.parse(c7r.read_text(encoding="utf-8"))
        write_package_manifest(root / "c7x")

        low_support_private = root / "low_support_private"
        low_support_state = root / "low_support_c7x_state"
        low_support_result = root / "low_support_c7x_result"
        low_support_state.mkdir(parents=True)
        low_support_result.mkdir(parents=True)
        (low_support_private / "source_bindings").mkdir(parents=True)
        classification = low_support_state / "c7x_classification_private.parquet"
        classification.write_bytes(b"synthetic-outcome-free-classification")
        classification_sha256 = common.sha256_file(classification)
        common.atomic_json(
            low_support_state / "c7x_classification_receipt.json",
            {
                "output_sha256": classification_sha256,
                "output_rows": 10_481,
                "config_sha256": "e" * 64,
                "qa": {
                    "within_chooser_both_latest_arms": 7,
                    "within_pair_both_latest_arms": 3,
                },
            },
        )
        common.atomic_json(
            low_support_result / "c7x_results.json",
            {
                "primary": {
                    "status": C7X_LOW_SUPPORT_STATUS,
                    "results": [],
                },
                "support": {"primary_support_pass": False},
            },
        )
        primary_authority = _c7x_primary_authority(low_support_result)
        if primary_authority["selected_panel_reference_available"] is not False:
            raise RuntimeError("C7X low-support primary was treated as a reference")
        amended_package, amended_binding = _prepare_c7r(
            private=low_support_private,
            view=root / "view",
            adapter={
                "success_sha256": "a" * 64,
                "rows": 41_534_331,
                "fair_rows": 15_207_423,
            },
            history_state=root / "history",
            c7x_state=low_support_state,
            c7x_root=low_support_result,
        )
        amended_source = (
            amended_package / "payload/code/run_campaign1_c7r_closure_v102.py"
        ).read_text(encoding="utf-8")
        if "enforce_certified_reproduction=False" not in amended_source:
            raise RuntimeError("C7R low-support amendment was not generated")
        if "NOT_APPLICABLE_PARENT_C7X_PRIMARY_LOW_SUPPORT" not in amended_source:
            raise RuntimeError("C7R low-support disposition is missing")
        if amended_binding["c7x_primary_authority"]["support_gate_pass"] is not False:
            raise RuntimeError("C7R binding lost the parent C7X failed support gate")
        ast.parse(amended_source)
        _run_source_self_test(
            amended_package / "payload/code/run_campaign1_c7r_closure_v102.py"
        )
    print(package["status"], flush=True)
    print("POOL_MAIN_WAVE2B2A_SELF_TEST_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
