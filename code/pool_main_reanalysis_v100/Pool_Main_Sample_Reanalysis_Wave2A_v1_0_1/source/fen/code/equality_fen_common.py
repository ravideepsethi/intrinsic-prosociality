#!/usr/bin/env python3
"""Shared authority, numerical, and serialization utilities.

This module has no network client and no package-installation path.  All
physical writes are confined by callers to new public/private run roots.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

try:  # Production requires the frozen versions; lazy fallback enables kernel QA.
    import duckdb  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised only in build environments
    duckdb = None  # type: ignore

try:
    import pyarrow.parquet as pq  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised only in build environments
    pq = None  # type: ignore


PACKAGE_NAME = "Pool_Main_Equality_FEN_Audit_v2_0_0"
CONTRACT_RELATIVE = "frozen_authorities/pool_main_equality_fen_contract_v2_0_0.json"
PUBLIC_STATUS = "POOL_MAIN_EQUALITY_FEN_AUDIT_V200_OK"
DESIGN_STATUS = "POOL_MAIN_EQUALITY_FEN_POSITION_DESIGN_V200_OK"
VERIFY_STATUS = "POOL_MAIN_EQUALITY_FEN_AUDIT_INDEPENDENTLY_VERIFIED_OK"


def utc_now() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_run_id() -> str:
    return pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%SZ")


def progress(message: str) -> None:
    print(f"[{utc_now()}] {message}", flush=True)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.close(descriptor)
        frame.to_csv(temporary, index=False, lineterminator="\n")
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return [json_ready(item) for item in value.tolist()]
    if isinstance(value, np.generic):
        return json_ready(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            block = stream.read(chunk_bytes)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def safe_relative(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"Path escapes required root: {relative}") from exc
    return candidate


def load_contract(package_root: Path) -> dict[str, Any]:
    contract = load_json(package_root / CONTRACT_RELATIVE)
    if contract.get("contract_version") != "2.0.0":
        raise RuntimeError("Frozen authority contract version changed")
    if contract.get("package_name") != PACKAGE_NAME:
        raise RuntimeError("Frozen authority contract package name changed")
    return contract


def _sample_fingerprint(report: Mapping[str, Any], report_sha256: str) -> str:
    material = {
        "report_sha256": report_sha256,
        "status": report["status"],
        "main_predicate": report["main_predicate"],
        "contract_sha256": report["contract_sha256"],
        "code_sha256": report["code_sha256"],
        "panel_outputs": [
            {
                "month": row["month"],
                "rows": int(row["rows"]),
                "size_bytes": int(row["size_bytes"]),
                "sha256": row["sha256"],
            }
            for row in report["panel_outputs"]
        ],
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


def load_pool_report(package_root: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    stage = contract["stage07"]
    path = safe_relative(package_root, stage["report_relative"])
    expected_sha = stage["report_sha256"]
    if sha256_file(path) != expected_sha:
        raise RuntimeError("Bundled pool-main report SHA-256 mismatch")
    sidecar = path.with_name(path.name + ".sha256")
    if not sidecar.is_file() or sidecar.read_text(encoding="utf-8").split()[0] != expected_sha:
        raise RuntimeError("Bundled pool-main report sidecar mismatch")
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Bundled pool-main report ZIP failed CRC validation")
        by_name = {Path(name).name: name for name in archive.namelist() if not name.endswith("/")}
        for required in ("MAIN_SAMPLE_REPORT.json", "SHA256SUMS.txt"):
            if required not in by_name:
                raise RuntimeError(f"Bundled pool-main report is missing {required}")
        for line in archive.read(by_name["SHA256SUMS.txt"]).decode("utf-8").splitlines():
            if not line.strip():
                continue
            digest, relative = line.split("  ", 1)
            member = by_name.get(Path(relative).name)
            if member is None or hashlib.sha256(archive.read(member)).hexdigest() != digest:
                raise RuntimeError(f"Bundled pool-main report member mismatch: {relative}")
        report = json.loads(archive.read(by_name["MAIN_SAMPLE_REPORT.json"]))
    exact = {
        "status": stage["status"],
        "main_predicate": stage["main_predicate"],
        "observed_screen_certified": True,
        "literal_immediate_rematches_certified": False,
    }
    for key, expected in exact.items():
        if report.get(key) != expected:
            raise RuntimeError(f"Pool-main report authority mismatch for {key}")
    fingerprint = _sample_fingerprint(report, expected_sha)
    if fingerprint != stage["sample_fingerprint"]:
        raise RuntimeError("Pool-main sample fingerprint mismatch")
    return report


def verify_package_manifest(package_root: Path) -> dict[str, Any]:
    manifest = package_root / "PACKAGE_MANIFEST.sha256"
    if not manifest.is_file():
        raise RuntimeError("PACKAGE_MANIFEST.sha256 is missing")
    rows: list[dict[str, Any]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise RuntimeError(f"Malformed package manifest line: {line!r}")
        expected, relative = match.groups()
        if relative == "PACKAGE_MANIFEST.sha256":
            raise RuntimeError("Package manifest must not hash itself")
        path = safe_relative(package_root, relative)
        if not path.is_file():
            raise RuntimeError(f"Packaged source missing: {relative}")
        observed = sha256_file(path)
        if observed != expected:
            raise RuntimeError(
                f"Packaged source hash changed: {relative}; expected={expected}; observed={observed}"
            )
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": observed})
    actual = sorted(
        str(path.relative_to(package_root))
        for path in package_root.rglob("*")
        if path.is_file()
        and path.name != "PACKAGE_MANIFEST.sha256"
        and "__pycache__" not in path.parts
        and not path.name.endswith(".pyc")
    )
    expected_paths = sorted(row["path"] for row in rows)
    if actual != expected_paths:
        missing = sorted(set(expected_paths) - set(actual))
        extra = sorted(set(actual) - set(expected_paths))
        raise RuntimeError(f"Package inventory changed; missing={missing}; extra={extra}")
    return {
        "status": "PACKAGE_CONTENTS_AUTHENTICATED_OK",
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "manifest_sha256": sha256_file(manifest),
    }


def environment_versions() -> dict[str, str]:
    if duckdb is None or pq is None:
        raise RuntimeError("duckdb and pyarrow are required for production")
    import pyarrow

    return {
        "duckdb": str(duckdb.__version__),
        "numpy": str(np.__version__),
        "pandas": str(pd.__version__),
        "pyarrow": str(pyarrow.__version__),
    }


def verify_environment(contract: Mapping[str, Any]) -> dict[str, Any]:
    observed = environment_versions()
    expected = dict(contract["expected_environment"])

    def version_tuple(value: str) -> tuple[int, int, int]:
        pieces = [int(item) for item in re.findall(r"\d+", value)[:3]]
        return tuple((pieces + [0, 0, 0])[:3])

    for name, constraint in expected.items():
        match = re.fullmatch(r">=([^,]+),<(.+)", str(constraint))
        if not match:
            raise RuntimeError(f"Malformed environment constraint: {name}={constraint}")
        low, high = map(version_tuple, match.groups())
        current = version_tuple(observed[name])
        if not low <= current < high:
            raise RuntimeError(
                f"Numerical environment is outside the authenticated range: "
                f"{name}={observed[name]} expected={constraint}"
            )
    return {"status": "CANONICAL_ENVIRONMENT_OK", "expected": expected, "observed": observed}


def stage07_paths(
    project: Path,
    contract: Mapping[str, Any],
    months: Sequence[Mapping[str, Any]],
) -> list[Path]:
    root = safe_relative(project, contract["stage07"]["root_relative"])
    return [
        root / f"month={row['month']}" / "analysis_panel.parquet"
        for row in months
    ]


def path_snapshot(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted({item.resolve() for item in paths}, key=str):
        if not path.exists():
            rows.append({"path": str(path), "exists": False})
            continue
        stat = path.stat()
        rows.append(
            {
                "path": str(path),
                "exists": True,
                "bytes": int(stat.st_size),
                "mtime_ns": int(stat.st_mtime_ns),
                "inode": int(stat.st_ino),
                "mode": int(stat.st_mode),
            }
        )
    return rows


def assert_snapshot_unchanged(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]) -> None:
    if canonical_json(list(before)) != canonical_json(list(after)):
        raise RuntimeError("Authenticated input metadata changed during the analysis")


def _run_readonly_git(repo: Path, args: Sequence[str]) -> str:
    environment = dict(os.environ)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=environment,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def authenticate_repository(project: Path, contract: Mapping[str, Any]) -> dict[str, Any]:
    lineage = contract["source_lineage"]
    return {
        "status": "BUNDLED_SOURCE_AUTHORITY_OK",
        "repository": lineage["public_repository"],
        "head": lineage["public_repository_head_inspected"],
        "scientific_design": lineage["scientific_design"],
        "adaptation": lineage["adaptation"],
        "live_repository_not_required": True,
    }


def _receipt(path: Path, expected_sha: str, expected_status: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Authority receipt missing: {path}")
    observed = sha256_file(path)
    if observed != expected_sha:
        raise RuntimeError(
            f"Authority receipt hash changed: {path}; expected={expected_sha}; observed={observed}"
        )
    value = load_json(path)
    if value.get("status") != expected_status:
        raise RuntimeError(
            f"Authority receipt status changed: {path}; observed={value.get('status')}"
        )
    return value


def authenticate_authorities(
    project: Path,
    package_root: Path,
    contract: Mapping[str, Any],
    *,
    full_stage07_hash: bool = True,
    synthetic: bool = False,
) -> dict[str, Any]:
    """Authenticate physical inputs and return paths plus compact evidence."""
    if pq is None:
        raise RuntimeError("pyarrow is required for Parquet authentication")
    if synthetic:
        success = load_json(project / "_SUCCESS.json")
        paths = sorted(project.glob("month=*/analysis_panel.parquet"))
        if success.get("status") != "SYNTHETIC_STAGE07_OK":
            raise RuntimeError("Synthetic fixture receipt is invalid")
        if len(paths) != int(success["months"]):
            raise RuntimeError("Synthetic fixture month count changed")
        rows = 0
        reference_schema: tuple[str, ...] | None = None
        for path in paths:
            footer = pq.ParquetFile(path)
            rows += int(footer.metadata.num_rows)
            schema = tuple(footer.schema_arrow.names)
            if reference_schema is None:
                reference_schema = schema
            elif schema != reference_schema:
                raise RuntimeError("Synthetic fixture schemas differ")
        if rows != int(success["rows"]):
            raise RuntimeError("Synthetic fixture row total changed")
        return {
            "synthetic": True,
            "stage07_paths": paths,
            "stage07_rows": rows,
            "stage07_kind_draws": int(success["kind_draws"]),
            "stage07_short_rows": int(success["short_rows"]),
            "authenticated_files": len(paths),
            "stage07_schema": list(reference_schema or ()),
            "input_authorities": {"synthetic_success": success},
        }

    stage07 = contract["stage07"]
    report = load_pool_report(package_root, contract)
    success_path = safe_relative(project, stage07["success_relative"])
    success = _receipt(success_path, stage07["success_sha256"], stage07["status"])
    for key in (
        "status",
        "main_predicate",
        "contract_sha256",
        "code_sha256",
        "expected_counts",
        "observed_screen_certified",
        "literal_immediate_rematches_certified",
    ):
        if success.get(key) != report.get(key):
            raise RuntimeError(f"Local pool-main receipt differs from report: {key}")
    if success.get("report_zip_sha256") != stage07["report_sha256"]:
        raise RuntimeError("Local pool-main receipt names a different report ZIP")
    if (success.get("code_sha256") or {}).get("build_main_sample.py") != stage07["producer_sha256"]:
        raise RuntimeError("Pool-main producer SHA-256 changed")
    selected = next(
        (row for row in report.get("sample_counts", []) if row.get("sample") == stage07["sample_name"]),
        None,
    )
    if selected is None:
        raise RuntimeError("Selected pool-main sample is absent from the report")
    for key in ("rows", "kind_draws", "fair_rows"):
        if int(selected.get(key, -1)) != int(stage07[key]):
            raise RuntimeError(f"Pool-main report count mismatch: {key}")

    required = set(stage07["required_columns"])
    report_months = sorted(report["panel_outputs"], key=lambda row: row["month"])
    paths = stage07_paths(project, contract, report_months)
    local_months = {row["month"]: row for row in success.get("panel_outputs", [])}
    reference_schema: tuple[str, ...] | None = None
    observed_months: list[dict[str, Any]] = []
    for spec, path in zip(report_months, paths, strict=True):
        if not path.is_file():
            raise RuntimeError(f"Stage 07 month missing: {path}")
        local = local_months.get(spec["month"])
        if local is None:
            raise RuntimeError(f"Local pool-main receipt lacks month {spec['month']}")
        for key in ("rows", "size_bytes", "sha256", "relative_path"):
            if local.get(key) != spec.get(key):
                raise RuntimeError(f"Local/report pool-main inventory mismatch: {spec['month']} {key}")
        stat = path.stat()
        if int(stat.st_size) != int(spec["size_bytes"]):
            raise RuntimeError(f"Stage 07 month byte size changed: {spec['month']}")
        footer = pq.ParquetFile(path)
        rows = int(footer.metadata.num_rows)
        schema = tuple(footer.schema_arrow.names)
        if rows != int(spec["rows"]):
            raise RuntimeError(f"Stage 07 month row count changed: {spec['month']}")
        if reference_schema is None:
            reference_schema = schema
            missing = sorted(required - set(schema))
            if missing:
                raise RuntimeError(f"Stage 07 required columns missing: {missing}")
            if len(schema) != int(stage07["columns"]):
                raise RuntimeError("Stage 07 column count changed")
            expected_schema = tuple(item["name"] for item in spec["schema"])
            if schema != expected_schema:
                raise RuntimeError("Stage 07 schema differs from the pool-main report")
        elif schema != reference_schema:
            raise RuntimeError(f"Stage 07 schema changed in {spec['month']}")
        observed_sha = None
        if full_stage07_hash:
            progress(f"authenticating Stage 07 bytes {spec['month']}")
            observed_sha = sha256_file(path)
            if observed_sha != spec["sha256"]:
                raise RuntimeError(f"Stage 07 monthly SHA-256 changed: {spec['month']}")
        observed_months.append(
            {
                "month": spec["month"],
                "rows": rows,
                "bytes": int(stat.st_size),
                "sha256": observed_sha or spec["sha256"],
                "full_sha256_recomputed": full_stage07_hash,
            }
        )
    if sum(row["rows"] for row in observed_months) != int(stage07["rows"]):
        raise RuntimeError("Stage 07 monthly rows do not conserve")

    compact: dict[str, Any] = {}
    for label in ("stage08", "stage09"):
        spec = contract[label]
        value = _receipt(
            safe_relative(project, spec["success_relative"]),
            spec["success_sha256"],
            spec["status"],
        )
        lineage = value.get("sample_authority") or {}
        if lineage.get("fingerprint") != stage07["sample_fingerprint"]:
            raise RuntimeError(f"{label} was not estimated on the selected pool-main sample")
        if (value.get("source_program") or {}).get("sha256") != spec["source_program_sha256"]:
            raise RuntimeError(f"{label} source-program SHA-256 changed")
        compact[label] = {
            "status": value.get("status"),
            "success_sha256": spec["success_sha256"],
            "sample_fingerprint": lineage.get("fingerprint"),
            "source_program_sha256": spec["source_program_sha256"],
        }

    return {
        "synthetic": False,
        "stage07_paths": paths,
        "stage07_rows": int(stage07["rows"]),
        "stage07_kind_draws": int(stage07["kind_draws"]),
        "stage07_short_rows": int(stage07["short_rows_ply_le_10"]),
        "authenticated_files": len(paths),
        "stage07_schema": list(reference_schema or ()),
        "input_authorities": {
            "stage07_success_sha256": stage07["success_sha256"],
            "stage07_producer_sha256": stage07["producer_sha256"],
            "sample_report_sha256": stage07["report_sha256"],
            "sample_fingerprint": stage07["sample_fingerprint"],
            "main_predicate": stage07["main_predicate"],
            "observed_screen_certified": True,
            "literal_immediate_rematches_certified": False,
            "stage07_months": observed_months,
            **compact,
        },
    }


def open_database(
    database_path: str | Path = ":memory:",
    *,
    threads: int = 8,
    memory_limit: str = "12GB",
) -> duckdb.DuckDBPyConnection:
    if duckdb is None:
        raise RuntimeError("duckdb is required for the equality/FEN audit")
    database = duckdb.connect(str(database_path))
    database.execute(f"PRAGMA threads={int(threads)}")
    database.execute(f"PRAGMA memory_limit='{memory_limit}'")
    database.execute("PRAGMA enable_progress_bar=false")
    database.execute("SET preserve_insertion_order=false")
    return database


def parquet_list_sql(paths: Sequence[Path]) -> str:
    return "[" + ",".join("'" + str(path).replace("'", "''") + "'" for path in paths) + "]"


def register_panel_view(database: duckdb.DuckDBPyConnection, paths: Sequence[Path]) -> None:
    database.execute(
        f"CREATE OR REPLACE VIEW panel AS "
        f"SELECT * FROM read_parquet({parquet_list_sql(paths)}, union_by_name=false)"
    )


def dense_codes(values: np.ndarray) -> tuple[np.ndarray, int]:
    values = np.asarray(values)
    if values.size == 0:
        raise ValueError("Cannot factorize an empty fixed effect")
    if np.issubdtype(values.dtype, np.integer) and int(values.min()) >= 0:
        uniques = np.unique(values)
        if len(uniques) == int(values.max()) + 1:
            return values.astype(np.int64, copy=False), len(uniques)
    codes, uniques = pd.factorize(values, sort=False)
    if np.any(codes < 0):
        raise ValueError("Fixed effect contains missing values")
    return codes.astype(np.int64, copy=False), int(len(uniques))


def _group_demean_inplace(matrix: np.ndarray, codes: np.ndarray, levels: int) -> float:
    counts = np.bincount(codes, minlength=levels).astype(np.float64)
    valid = counts > 0
    maximum = 0.0
    for column in range(matrix.shape[1]):
        sums = np.bincount(codes, weights=matrix[:, column], minlength=levels)
        means = np.zeros(levels, dtype=np.float64)
        means[valid] = sums[valid] / counts[valid]
        if valid.any():
            maximum = max(maximum, float(np.max(np.abs(means[valid]))))
        matrix[:, column] -= means[codes]
    return maximum


def maximum_scaled_group_mean(
    matrix: np.ndarray,
    effects: Sequence[tuple[np.ndarray, int]],
    source_scale: np.ndarray,
) -> float:
    maximum = 0.0
    for codes, levels in effects:
        counts = np.bincount(codes, minlength=levels).astype(np.float64)
        valid = counts > 0
        for column in range(matrix.shape[1]):
            sums = np.bincount(codes, weights=matrix[:, column], minlength=levels)
            means = np.zeros(levels, dtype=np.float64)
            means[valid] = sums[valid] / counts[valid]
            if valid.any():
                maximum = max(
                    maximum,
                    float(np.max(np.abs(means[valid]))) / float(source_scale[column]),
                )
    return maximum


def absorb_fixed_effects(
    matrix: np.ndarray,
    fixed_effect_codes: Sequence[np.ndarray],
    *,
    tolerance: float = 1e-8,
    maximum_iterations: int = 500,
) -> tuple[np.ndarray, int, float, str]:
    source = np.asarray(matrix, dtype=np.float64)
    if not fixed_effect_codes:
        return source.copy(), 0, 0.0, "none"
    effects: list[tuple[np.ndarray, int]] = []
    for values in fixed_effect_codes:
        codes, levels = dense_codes(np.asarray(values))
        effects.append((codes, levels))
    residual = source.copy()
    scales = np.maximum(np.sqrt(np.mean(np.square(source), axis=0)), 1.0)
    if len(effects) == 1:
        _group_demean_inplace(residual, effects[0][0], effects[0][1])
        orthogonality = maximum_scaled_group_mean(residual, effects, scales)
        if orthogonality > tolerance:
            raise RuntimeError(
                f"One-way FE absorption failed: orthogonality={orthogonality:.3e}"
            )
        return residual, 1, orthogonality, "one_way_exact"

    converged = False
    orthogonality = math.inf
    for iteration in range(1, maximum_iterations + 1):
        maximum_update = 0.0
        for codes, levels in effects:
            maximum_update = max(
                maximum_update,
                _group_demean_inplace(residual, codes, levels),
            )
        scaled_update = maximum_update / float(np.max(scales))
        if iteration == 1 or iteration % 5 == 0 or scaled_update <= tolerance:
            orthogonality = maximum_scaled_group_mean(residual, effects, scales)
            if orthogonality <= tolerance:
                converged = True
                break
    if not converged:
        raise RuntimeError(
            "Alternating fixed-effect absorption did not converge: "
            f"iterations={maximum_iterations}; orthogonality={orthogonality:.3e}"
        )
    return residual, iteration, orthogonality, f"{len(effects)}_way_alternating"


def normal_two_sided_p(t_value: float) -> float:
    if not math.isfinite(t_value):
        return math.nan
    return math.erfc(abs(float(t_value)) / math.sqrt(2.0))


def fit_lpm_cluster(
    y: np.ndarray,
    x: np.ndarray,
    x_names: Sequence[str],
    cluster_codes: np.ndarray,
    *,
    fixed_effect_codes: Sequence[np.ndarray] = (),
    add_intercept: bool = False,
    tolerance: float = 1e-8,
    maximum_iterations: int = 500,
) -> dict[str, Any]:
    y = np.asarray(y, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    clusters = np.asarray(cluster_codes, dtype=np.int64)
    if len(y) != len(x) or len(y) != len(clusters):
        raise ValueError("Regression arrays have inconsistent lengths")
    if x.shape[1] != len(x_names):
        raise ValueError("x_names does not match the design matrix")
    finite = np.isfinite(y) & np.all(np.isfinite(x), axis=1) & (clusters >= 0)
    for effect in fixed_effect_codes:
        finite &= np.asarray(effect) >= 0
    y = y[finite]
    x = x[finite]
    clusters = clusters[finite]
    effects = [np.asarray(effect, dtype=np.int64)[finite] for effect in fixed_effect_codes]
    n_raw = int(len(y))
    if n_raw == 0:
        raise ValueError("Regression has no finite rows")
    names = list(x_names)
    if effects:
        transformed, iterations, orthogonality, method = absorb_fixed_effects(
            np.column_stack([y, x]),
            effects,
            tolerance=tolerance,
            maximum_iterations=maximum_iterations,
        )
        y = transformed[:, 0]
        x = transformed[:, 1:]
    else:
        iterations, orthogonality, method = 0, 0.0, "none"
        if add_intercept:
            x = np.column_stack([np.ones(n_raw, dtype=np.float64), x])
            names = ["intercept", *names]
    identifying = np.any(np.abs(x) > 1e-14, axis=1)
    y = y[identifying]
    x = x[identifying]
    clusters = clusters[identifying]
    n = int(len(y))
    k = int(x.shape[1])
    if n <= k or k == 0:
        raise ValueError(f"Regression has inadequate identifying support: n={n}; k={k}")
    xtx = x.T @ x
    rank = int(np.linalg.matrix_rank(xtx))
    inverse = np.linalg.pinv(xtx, rcond=1e-12, hermitian=True)
    beta = inverse @ (x.T @ y)
    residual = y - x @ beta
    cluster_levels = int(clusters.max()) + 1
    cluster_counts = np.bincount(clusters, minlength=cluster_levels)
    populated = np.flatnonzero(cluster_counts)
    g = int(len(populated))
    if g < 2:
        raise ValueError("Clustered covariance requires at least two clusters")
    scores = np.empty((g, k), dtype=np.float64)
    for column in range(k):
        full = np.bincount(
            clusters,
            weights=x[:, column] * residual,
            minlength=cluster_levels,
        )
        scores[:, column] = full[populated]
    covariance = inverse @ (scores.T @ scores) @ inverse
    if n > k:
        covariance *= (g / (g - 1.0)) * ((n - 1.0) / (n - k))
    standard_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    t_statistics = np.divide(
        beta,
        standard_errors,
        out=np.full_like(beta, np.nan),
        where=standard_errors > 0,
    )
    return {
        "n_rows_raw": n_raw,
        "n_rows_identifying": n,
        "n_clusters": g,
        "k": k,
        "rank": rank,
        "x_names": names,
        "beta": beta,
        "covariance": covariance,
        "standard_errors_array": standard_errors,
        "t_statistics_array": t_statistics,
        "coefficients": {name: float(value) for name, value in zip(names, beta)},
        "standard_errors": {
            name: float(value) for name, value in zip(names, standard_errors)
        },
        "t_statistics": {
            name: float(value) for name, value in zip(names, t_statistics)
        },
        "p_normal_approx": {
            name: normal_two_sided_p(float(value))
            for name, value in zip(names, t_statistics)
        },
        "absorption_iterations": iterations,
        "absorption_max_scaled_group_mean": orthogonality,
        "absorption_method": method,
    }


def linear_combination(result: Mapping[str, Any], weights: Mapping[str, float]) -> dict[str, float]:
    names = list(result["x_names"])
    vector = np.array([float(weights.get(name, 0.0)) for name in names], dtype=np.float64)
    beta = np.asarray(result["beta"], dtype=np.float64)
    covariance = np.asarray(result["covariance"], dtype=np.float64)
    estimate = float(vector @ beta)
    variance = float(vector @ covariance @ vector)
    standard_error = math.sqrt(max(variance, 0.0))
    t_value = estimate / standard_error if standard_error > 0 else math.nan
    return {
        "estimate": estimate,
        "se": standard_error,
        "t": t_value,
        "p_normal_approx": normal_two_sided_p(t_value),
    }


def coefficient_row(
    result: Mapping[str, Any],
    *,
    model_id: str,
    sample: str,
    variable: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "status": "ESTIMATED",
        "model_id": model_id,
        "sample": sample,
        "variable": variable,
        "coefficient_pp": result["coefficients"].get(variable),
        "se_pp": result["standard_errors"].get(variable),
        "t": result["t_statistics"].get(variable),
        "p_normal_approx": result["p_normal_approx"].get(variable),
        "rows_raw": result["n_rows_raw"],
        "rows_identifying": result["n_rows_identifying"],
        "chooser_clusters": result["n_clusters"],
        "matrix_columns": result["k"],
        "matrix_rank": result["rank"],
        "absorption_iterations": result["absorption_iterations"],
        "absorption_method": result["absorption_method"],
        "absorption_max_scaled_group_mean": result[
            "absorption_max_scaled_group_mean"
        ],
    }
    if extra:
        row.update(extra)
    return row


def failed_model_row(
    model_id: str,
    sample: str,
    variable: str,
    error: Exception,
    *,
    role: str,
) -> dict[str, Any]:
    return {
        "status": "NOT_ESTIMATED",
        "model_id": model_id,
        "sample": sample,
        "variable": variable,
        "analysis_role": role,
        "error_type": type(error).__name__,
        "error": str(error)[:500],
    }


def holm_adjust(p_values: Sequence[float]) -> list[float]:
    values = np.asarray(p_values, dtype=np.float64)
    result = np.full(len(values), np.nan)
    finite_indices = np.flatnonzero(np.isfinite(values))
    if not len(finite_indices):
        return result.tolist()
    order = finite_indices[np.argsort(values[finite_indices], kind="mergesort")]
    running = 0.0
    total = len(order)
    for rank, index in enumerate(order):
        adjusted = min(1.0, (total - rank) * float(values[index]))
        running = max(running, adjusted)
        result[index] = running
    return result.tolist()


def make_report_manifest(root: Path, *, excluded_names: Sequence[str] = ()) -> pd.DataFrame:
    excluded = set(excluded_names)
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in excluded:
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rows.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": int(path.stat().st_size),
                "sha256": sha256_file(path),
            }
        )
    return pd.DataFrame(rows, columns=["path", "bytes", "sha256"])


def verify_report_manifest(root: Path, manifest_path: Path) -> dict[str, Any]:
    frame = pd.read_csv(manifest_path, sep="\t")
    required = {"path", "bytes", "sha256"}
    if set(frame.columns) != required:
        raise RuntimeError("Report manifest schema changed")
    for row in frame.to_dict("records"):
        path = safe_relative(root, str(row["path"]))
        if not path.is_file():
            raise RuntimeError(f"Report file missing: {row['path']}")
        if path.stat().st_size != int(row["bytes"]):
            raise RuntimeError(f"Report byte size changed: {row['path']}")
        if sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Report SHA-256 changed: {row['path']}")
    return {
        "files": int(len(frame)),
        "bytes": int(frame["bytes"].sum()) if len(frame) else 0,
        "manifest_sha256": sha256_file(manifest_path),
    }


def privacy_scan_public_output(root: Path) -> dict[str, Any]:
    forbidden_csv_columns = {
        "game_id",
        "chooser_username",
        "chooser_username_norm",
        "username",
        "fen",
        "fen_after_last_move",
        "position_fen4",
        "board_fen1",
    }
    forbidden_json_keys = {
        "game_id",
        "chooser_username",
        "chooser_username_norm",
        "fen_after_last_move",
        "position_fen4",
        "board_fen1",
    }
    checked = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "report_file_hashes.tsv":
            continue
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, nrows=5)
            overlap = forbidden_csv_columns & set(frame.columns)
            if overlap:
                raise RuntimeError(f"Public CSV contains forbidden columns: {path}: {sorted(overlap)}")
            checked += 1
        elif path.suffix.lower() == ".json":
            value = load_json(path)
            stack = [value]
            while stack:
                item = stack.pop()
                if isinstance(item, dict):
                    overlap = forbidden_json_keys & set(item)
                    if overlap:
                        raise RuntimeError(
                            f"Public JSON contains forbidden keys: {path}: {sorted(overlap)}"
                        )
                    stack.extend(item.values())
                elif isinstance(item, list):
                    stack.extend(item)
            checked += 1
    return {
        "status": "AGGREGATE_ONLY_PRIVACY_SCAN_OK",
        "structured_files_checked": checked,
    }


def numerical_self_test() -> None:
    rng = np.random.default_rng(20260827)
    n = 2400
    chooser = np.repeat(np.arange(120, dtype=np.int64), 20)
    month = np.tile(np.repeat(np.arange(4, dtype=np.int64), 5), 120)
    speed = np.tile(np.arange(5, dtype=np.int64), 480)
    x = rng.normal(size=(n, 3))
    matrix = np.column_stack([rng.normal(size=n), x])
    residual, iterations, orthogonality, method = absorb_fixed_effects(
        matrix,
        (chooser, month, speed),
        tolerance=1e-10,
        maximum_iterations=500,
    )
    dummy = np.zeros((n, 120 + 4 + 5), dtype=np.float64)
    dummy[np.arange(n), chooser] = 1.0
    dummy[np.arange(n), 120 + month] = 1.0
    dummy[np.arange(n), 124 + speed] = 1.0
    explicit = matrix - dummy @ np.linalg.lstsq(dummy, matrix, rcond=None)[0]
    difference = float(np.max(np.abs(residual - explicit)))
    if difference > 1e-9:
        raise RuntimeError(
            f"Three-way absorber dummy-regression cross-check failed: {difference:.3e}"
        )
    if orthogonality > 1e-10:
        raise RuntimeError("Three-way absorber orthogonality self-test failed")
    equality = (rng.random(n) < 0.55).astype(np.float64)
    short = (rng.random(n) < 0.3).astype(np.float64)
    y = (
        1.0
        + 0.2 * equality
        + 0.3 * equality * short
        + rng.normal(scale=0.5, size=n)
        + rng.normal(scale=0.2, size=120)[chooser]
    )
    result = fit_lpm_cluster(
        y,
        np.column_stack([equality, short, equality * short]),
        ["roughly_equal", "short", "roughly_equal_x_short"],
        chooser,
        fixed_effect_codes=(chooser, month, speed),
        tolerance=1e-10,
    )
    if abs(result["coefficients"]["roughly_equal"] - 0.2) > 0.12:
        raise RuntimeError("Synthetic equality coefficient recovery failed")
    if abs(result["coefficients"]["roughly_equal_x_short"] - 0.3) > 0.15:
        raise RuntimeError("Synthetic short interaction recovery failed")
    adjusted = holm_adjust([0.01, 0.04, 0.20])
    if not np.allclose(adjusted, [0.03, 0.08, 0.20]):
        raise RuntimeError(f"Holm self-test failed: {adjusted}")
    print("KINDNESS_EQUALITY_FEN_NUMERICAL_SELFTEST_OK")
    print(f"absorber_method: {method}")
    print(f"absorber_iterations: {iterations}")
    print(f"maximum_dummy_regression_difference: {difference:.3e}")
    print(f"maximum_scaled_group_mean: {orthogonality:.3e}")
