#!/usr/bin/env python3
"""Offline unit and source-binding tests for Wave 2B2B1."""

from __future__ import annotations

import ast
import shutil
import tempfile
from pathlib import Path

from runner import c6_ply_retrofit, c7x_dyad_diagnostic, common
from runner import orchestrate


EXPECTED_SOURCE_HASHES = {
    "source/campaign/campaign1_nonprofile_common_v102.py": "f629876216c797180265d1b848a4424f211fe9a43cffa4dabdb3de67acbc5f1c",
    "source/campaign/campaign1_c6_c10_v100.py": "f0071a82d6824260f77db26f79fc02ab5f18a241c9dc26ee990f8921771965a5",
    "source/campaign/campaign1_c12_v102.py": "7f009eca37770e730759e4448147b0a416aac870414e0cc01df356b11202b277",
    "source/campaign/campaign1_c12_supplement_v103.py": "7cc5c57434cc71455c89113ad738c93d432ad971ff8a16ce12e528b9a5713087",
    "source/engines/10c_estimate_dynamic_prosociality_core.py": "8d2c218ef17342528326fead84ed883e1b9ec0344e21104003553052589b03da",
    "source/frequent_dyad/frequent_dyad_census_v101.py": "de468744408ebb29107d09c00e11d407dfc6ded036caf78f4b3e86077a2309aa",
}


def run() -> None:
    package = common.verify_package_manifest()
    if package["status"] != "POOL_MAIN_WAVE2B2B1_PACKAGE_AUTHENTICATED_OK":
        raise RuntimeError("Package authentication self-test failed")
    for relative, expected in EXPECTED_SOURCE_HASHES.items():
        path = common.PACKAGE_ROOT / relative
        observed = common.sha256_file(path)
        if observed != expected:
            raise RuntimeError(
                f"Recovered source changed: {relative}; expected={expected}; observed={observed}"
            )
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    temporary = Path(tempfile.mkdtemp(prefix="pool_main_wave2b2b1_test_"))
    try:
        execution, bindings = orchestrate._prepare_sources(
            private=temporary,
            view=temporary / "synthetic_project_view",
            adapter={
                "rows": 41_534_331,
                "fair_rows": 15_207_423,
                "success_sha256": "0" * 64,
            },
        )
        for key in ("common", "c6_c10", "c12"):
            if not bindings[key].get("generated_sha256"):
                raise RuntimeError(f"Source-binding receipt is incomplete: {key}")
        modules = orchestrate._load_modules(execution / "payload/code")
        modules["campaign_common"].self_test()
        modules["c6"].self_test()
        modules["c12"].self_test()
        modules["c12_supplement"].self_test()
        c6_ply_retrofit.self_test()
        c7x_dyad_diagnostic.self_test()
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    print("POOL_MAIN_WAVE2B2B1_SELF_TEST_OK")


def main() -> int:
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

