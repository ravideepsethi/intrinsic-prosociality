#!/usr/bin/env python3
"""Offline provenance, binding-contract, and bundled-estimator self-tests."""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from runner import common
from runner.bind_source import bind_source


def _module_symbols(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments: set[str] = set()
    functions: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assignments.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.add(node.name)
    return assignments, functions


def _binding_calls(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name not in {"bind", "bind_source"}:
            continue
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        source_node = keywords.get("source_relative") or keywords.get("source")
        if source_node is None and node.args:
            source_node = node.args[0]
        if isinstance(source_node, ast.Constant) and isinstance(source_node.value, str):
            source = source_node.value
        elif source_node is not None:
            # prepare.py constructs its sole source path immediately above. Keep
            # that contract explicit so the AST check remains fail-closed.
            source = "10b_build_a3_chronology_gate.py"
        else:
            continue
        constants_node = keywords.get("constants")
        functions_node = keywords.get("functions")
        constants: set[str] = set()
        functions: set[str] = set()
        if isinstance(constants_node, ast.Dict):
            constants = {
                key.value
                for key in constants_node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
        if isinstance(functions_node, ast.Dict):
            functions = {
                key.value
                for key in functions_node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
        if constants:
            found.append({"source": source, "constants": constants, "functions": functions})
    return found


def verify_source_inventory() -> int:
    frozen = common.load_json(common.PACKAGE_ROOT / "authority/DYNAMICS_REBUILD_PREFLIGHT.json")
    expected = {
        row["relative_path"]: row
        for row in frozen["bundled_source_inventory"]["entries"]
    }
    correction = common.load_json(common.PACKAGE_ROOT / "authority/WAVE2B1_V101_CORRECTION.json")
    if correction.get("status") != "POOL_MAIN_WAVE2B1_V101_CORRECTION_FROZEN_OK":
        raise RuntimeError("Wave 2B1 v1.0.1 correction authority is invalid")
    for row in correction["source_inventory_overrides"]:
        expected[row["relative_path"]] = row
    correction = common.load_json(common.PACKAGE_ROOT / "authority/WAVE2B1_V102_CORRECTION.json")
    if correction.get("status") != "POOL_MAIN_WAVE2B1_V102_CORRECTION_FROZEN_OK":
        raise RuntimeError("Wave 2B1 v1.0.2 correction authority is invalid")
    for row in correction["source_inventory_overrides"]:
        expected[row["relative_path"]] = row
    sources = common.PACKAGE_ROOT / "source/dynamics"
    checked = 0
    for path in sorted(sources.rglob("*.py")):
        relative = path.relative_to(sources).as_posix()
        if relative == "a1_audits/10c_estimate_dynamic_prosociality_core.py":
            # A byte-identical audit-local copy is intentionally retained and checked.
            pass
        row = expected.get(relative)
        if row is None:
            raise RuntimeError(f"Bundled dynamics source lacks frozen Wave-2A provenance: {relative}")
        if path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Bundled source byte count changed: {relative}")
        if common.sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Bundled source SHA-256 changed: {relative}")
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        checked += 1
    if checked != 14:
        raise RuntimeError(f"Expected 14 frozen Python dynamics sources; found {checked}")
    return checked


def verify_binding_contracts() -> int:
    calls = []
    for path in (
        common.PACKAGE_ROOT / "runner/prepare.py",
        common.PACKAGE_ROOT / "runner/orchestrate.py",
    ):
        calls.extend(_binding_calls(path))
    if len(calls) != 13:
        raise RuntimeError(f"Expected 13 source-binding contracts; found {len(calls)}")
    for call in calls:
        source = common.PACKAGE_ROOT / "source/dynamics" / call["source"]
        assignments, functions = _module_symbols(source)
        missing_constants = sorted(call["constants"] - assignments)
        missing_functions = sorted(call["functions"] - functions)
        if missing_constants or missing_functions:
            raise RuntimeError(
                f"Binding contract/source mismatch: {call['source']}; "
                f"constants={missing_constants}; functions={missing_functions}"
            )
    return len(calls)


def _literal_constants(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
                continue
            name = node.targets[0].id
            value = node.value
        else:
            if not isinstance(node.target, ast.Name) or node.value is None:
                continue
            name = node.target.id
            value = node.value
        try:
            values[name] = ast.literal_eval(value)
        except (ValueError, TypeError):
            continue
    return values


def verify_document_authorities() -> int:
    sources = common.PACKAGE_ROOT / "source/dynamics"
    docs = common.PACKAGE_ROOT / "source/docs"
    checks = (
        ("10c_estimate_dynamic_prosociality_core.py", "EXPECTED_PLAN_SHA256", docs / "Dynamic_Prosociality_Analysis_Plan_v1_0_1_2026-08-21.md"),
        ("10c_estimate_dynamic_prosociality_core.py", "EXPECTED_ARM_AMENDMENT_SHA256", docs / "dynamic_prosociality_arm_partition_amendment.md"),
        ("10c_estimate_dynamic_prosociality_core.py", "EXPECTED_EXECUTION_NOTE_SHA256", docs / "dynamic_prosociality_parallel_execution_note.md"),
        ("10d_audit_dynamic_prosociality_core.py", "EXPECTED_POSTAUDIT_PLAN_SHA256", docs / "dynamic_prosociality_postoutcome_audit_plan.md"),
        ("10d_audit_dynamic_prosociality_core.py", "EXPECTED_RECOVERY_NOTE_SHA256", docs / "dynamic_prosociality_postaudit_boolean_recovery.md"),
        ("10g_build_dynamic_second_wave_histories.py", "EXPECTED_PLAN_SHA256", docs / "dynamic_prosociality_second_wave_analysis_plan.md"),
        ("10g_build_dynamic_second_wave_histories.py", "EXPECTED_SOURCE_AMENDMENT_SHA256", docs / "dynamic_prosociality_second_wave_source_contract_amendment.md"),
        ("10g_build_dynamic_second_wave_histories.py", "EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256", docs / "dynamic_prosociality_second_wave_implementation_amendment.md"),
        ("11a_estimate_dynamic_second_wave_postprimary.py", "EXPECTED_POSTPRIMARY_PLAN_SHA", docs / "dynamic_prosociality_second_wave_postprimary_analysis.md"),
        ("10h_estimate_dynamic_second_wave.py", "EXPECTED_STAGE08_SHA256", common.PACKAGE_ROOT / "source/core/08_make_core_paper_results.py"),
    )
    cache: dict[str, dict[str, Any]] = {}
    for source_name, constant, artifact in checks:
        cache.setdefault(source_name, _literal_constants(sources / source_name))
        expected = cache[source_name].get(constant)
        if not isinstance(expected, str) or common.sha256_file(artifact) != expected:
            raise RuntimeError(f"Frozen document/kernel authority mismatch: {artifact}")
    return len(checks)


def test_binder_is_surgical() -> None:
    synthetic = """from pathlib import Path\nVALUE = 1\n\ndef guard(repo: Path):\n    return 'old'\n\ndef estimator(x):\n    return x * x + 7\n"""
    with tempfile.TemporaryDirectory(prefix="wave2b1_binder_test.") as temporary:
        root = Path(temporary)
        source = root / "source.py"
        destination = root / "bound.py"
        source.write_text(synthetic, encoding="utf-8")
        receipt = bind_source(
            source,
            destination,
            constants={"VALUE": 2},
            functions={"guard": "def guard(repo: Path):\n    return 'recorded'\n"},
        )
        original_tree = ast.parse(synthetic)
        bound_tree = ast.parse(destination.read_text(encoding="utf-8"))
        original_estimator = next(
            node for node in original_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "estimator"
        )
        bound_estimator = next(
            node for node in bound_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "estimator"
        )
        if ast.dump(original_estimator) != ast.dump(bound_estimator):
            raise RuntimeError("Source binder changed an estimator function")
        if receipt["estimator_function_bodies_changed"] is not False:
            raise RuntimeError("Source binding receipt did not certify unchanged estimators")


def run_estimator_self_tests() -> int:
    sources = common.PACKAGE_ROOT / "source/dynamics"
    paths = [
        *(sources / name for name in (
            "10b_build_a3_chronology_gate.py",
            "10c_estimate_dynamic_prosociality_core.py",
            "12_complete_remaining_dynamic_analyses.py",
            "10e_audit_dynamic_second_wave_feasibility.py",
            "10f_estimate_b2_first_grant_dynamics.py",
            "10g_build_dynamic_second_wave_histories.py",
            "10h_estimate_dynamic_second_wave.py",
            "11a_estimate_dynamic_second_wave_postprimary.py",
            "11b_audit_dynamic_second_wave_e1.py",
        )),
        sources / "a1_audits/a1_evidence_gap_audit_v100.py",
        sources / "a1_audits/a1_unconditional_first_opportunity_audit_v100.py",
        sources / "c7r_fullpanel_prefocal/run_c7r_fullpanel_prefocal_v100.py",
    ]
    for path in paths:
        print(f"ESTIMATOR_SELF_TEST_BEGIN {path.relative_to(sources)}", flush=True)
        subprocess.run([sys.executable, "-B", "-u", str(path), "--self-test"], check=True)
    print("ESTIMATOR_SELF_TEST_BEGIN 10d_audit_dynamic_prosociality_core.py", flush=True)
    base = common.load_source_module(
        sources / "10c_estimate_dynamic_prosociality_core.py",
        "wave2b1_selftest_core",
    )
    audit = common.load_source_module(
        sources / "10d_audit_dynamic_prosociality_core.py",
        "wave2b1_selftest_postaudit",
    )
    audit.self_test({"base": base})
    return len(paths) + 1


def main() -> int:
    package = common.verify_package_manifest()
    runtime = common.verify_runtime_dependencies()
    sources = verify_source_inventory()
    bindings = verify_binding_contracts()
    documents = verify_document_authorities()
    test_binder_is_surgical()
    estimators = run_estimator_self_tests()
    print(
        "POOL_MAIN_WAVE2B1_OFFLINE_SELF_TEST_OK "
        f"package_files={package['files']} sources={sources} "
        f"bindings={bindings} document_authorities={documents} "
        f"estimator_tests={estimators}",
        flush=True,
    )
    print(f"PYTHON {runtime['executable']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
