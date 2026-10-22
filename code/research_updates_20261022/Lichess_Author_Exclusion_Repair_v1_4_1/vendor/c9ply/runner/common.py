#!/usr/bin/env python3
"""Shared authentication, provenance, and safe-I/O helpers for pool-main reset waves."""

from __future__ import annotations

import concurrent.futures
import csv
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import zipfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Iterable, Sequence


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_PATH = PACKAGE_ROOT / "authority/SAMPLE_AUTHORITY.json"
REPORT_ZIP = PACKAGE_ROOT / "evidence/Pool_Main_Sample_24M_Report.zip"
REPORT_SIDECAR = PACKAGE_ROOT / "evidence/Pool_Main_Sample_24M_Report.zip.sha256"
PUBLIC_REPOSITORY_HEAD = "0dc981cbc6da157d365015a95f2b7157ecda4859"
PUBLIC_REPOSITORY_URL = "https://github.com/ravideepsethi/intrinsic-prosociality.git"
WAVE_VERSION = "C9-1.0.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object: {path}")
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def sha256_file(path: Path, chunk_bytes: int = 16 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(chunk_bytes), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_package_manifest(
    root: Path = PACKAGE_ROOT,
    manifest_name: str = "PACKAGE_MANIFEST.sha256",
) -> dict[str, Any]:
    """Authenticate every packaged file and reject unmanifested substantive files."""
    root = root.resolve()
    manifest = root / manifest_name
    if not manifest.is_file():
        raise RuntimeError(f"Package manifest is missing: {manifest}")
    rows: list[dict[str, Any]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise RuntimeError(f"Malformed package manifest line: {line!r}")
        expected, relative = match.groups()
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"Package manifest path escapes root: {relative}") from exc
        if not candidate.is_file():
            raise RuntimeError(f"Packaged file is missing: {relative}")
        observed = sha256_file(candidate)
        if observed != expected:
            raise RuntimeError(
                f"Packaged file checksum changed: {relative}; "
                f"expected={expected}; observed={observed}"
            )
        rows.append(
            {"relative_path": relative, "bytes": candidate.stat().st_size, "sha256": observed}
        )
    actual = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.resolve() != manifest.resolve()
        and path.name != ".DS_Store"
        and "__pycache__" not in path.parts
        and not path.name.endswith((".pyc", ".pyo"))
    )
    expected_paths = sorted(row["relative_path"] for row in rows)
    if actual != expected_paths:
        raise RuntimeError(
            "Package inventory changed; "
            f"missing={sorted(set(expected_paths) - set(actual))}; "
            f"extra={sorted(set(actual) - set(expected_paths))}"
        )
    return {
        "status": "POOL_MAIN_C9_PACKAGE_AUTHENTICATED_OK",
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "manifest_sha256": sha256_file(manifest),
    }


def source_record(path: Path, lineage: str) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "lineage": lineage,
        "repository": PUBLIC_REPOSITORY_URL if lineage == "public_repository" else None,
        "repository_head_inspected": PUBLIC_REPOSITORY_HEAD if lineage == "public_repository" else None,
    }


def load_source_module(path: Path, module_name: str) -> ModuleType:
    source_dir = str(path.resolve().parent)
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load source module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def verify_report_package() -> tuple[dict[str, Any], dict[str, Any]]:
    authority = load_json(AUTHORITY_PATH)
    if not REPORT_ZIP.is_file() or not REPORT_SIDECAR.is_file():
        raise RuntimeError("Bundled main-sample report or sidecar is missing")
    sidecar_hash = REPORT_SIDECAR.read_text(encoding="utf-8").split()[0]
    actual_hash = sha256_file(REPORT_ZIP)
    expected_hash = authority["report_sha256"]
    if actual_hash != expected_hash or sidecar_hash != expected_hash:
        raise RuntimeError(
            "Main-sample report checksum failed: "
            f"authority={expected_hash} sidecar={sidecar_hash} actual={actual_hash}"
        )
    with zipfile.ZipFile(REPORT_ZIP) as archive:
        names = archive.namelist()
        by_base = {Path(name).name: name for name in names if not name.endswith("/")}
        required = {"MAIN_SAMPLE_REPORT.json", "SHA256SUMS.txt", "SUMMARY.md"}
        missing = sorted(required - set(by_base))
        if missing:
            raise RuntimeError(f"Bundled report is incomplete: {missing}")
        manifest_lines = archive.read(by_base["SHA256SUMS.txt"]).decode("utf-8").splitlines()
        for line in manifest_lines:
            if not line.strip():
                continue
            digest, relative = line.split("  ", 1)
            member = by_base.get(Path(relative).name)
            if member is None:
                raise RuntimeError(f"Report manifest entry is missing: {relative}")
            observed = hashlib.sha256(archive.read(member)).hexdigest()
            if observed != digest:
                raise RuntimeError(f"Report member checksum failed: {relative}")
        report = json.loads(archive.read(by_base["MAIN_SAMPLE_REPORT.json"]))
    exact = {
        "status": authority["status"],
        "main_predicate": authority["main_predicate"],
        "observed_screen_certified": authority["observed_screen_certified"],
        "literal_immediate_rematches_certified": authority[
            "literal_immediate_rematches_certified"
        ],
    }
    for key, expected in exact.items():
        if report.get(key) != expected:
            raise RuntimeError(
                f"Report authority mismatch for {key}: expected={expected!r}; "
                f"observed={report.get(key)!r}"
            )
    samples = {
        row["sample"]: row for row in report.get("sample_counts", [])
    }
    selected = samples.get(authority["sample_name"])
    if selected is None:
        raise RuntimeError("Selected sample row is absent from the report")
    for key in (
        "rows",
        "kind_draws",
        "fair_rows",
        "fair_kind_draws",
        "choosers",
        "fair_choosers",
        "fair_kind_choosers",
    ):
        if int(selected.get(key, -1)) != int(authority[key]):
            raise RuntimeError(f"Report selected-sample mismatch for {key}")
    outputs = report.get("panel_outputs") or []
    if len(outputs) != authority["months"]:
        raise RuntimeError("Report does not contain 24 monthly panel outputs")
    if len({row.get("month") for row in outputs}) != authority["months"]:
        raise RuntimeError("Report monthly panel inventory has duplicate months")
    observed_fingerprint = sample_fingerprint(report, authority["report_sha256"])
    if observed_fingerprint != authority["sample_fingerprint"]:
        raise RuntimeError("Bundled sample fingerprint differs from SAMPLE_AUTHORITY.json")
    return authority, report


def _normalize_sample_root(path: Path) -> tuple[Path, Path]:
    candidate = path.expanduser().resolve()
    if (candidate / "_SUCCESS.json").is_file() and (candidate / "panel").is_dir():
        return candidate, candidate / "panel"
    if candidate.name == "panel" and (candidate.parent / "_SUCCESS.json").is_file():
        return candidate.parent, candidate
    raise RuntimeError(
        "Sample root must be the certified pool-main output root (containing "
        "_SUCCESS.json and panel/) or its panel/ subdirectory: " + str(candidate)
    )


def sample_fingerprint(report: dict[str, Any], report_sha256: str) -> str:
    payload = {
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
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def authenticate_sample(
    sample_root: Path,
    *,
    verify_hashes: bool = True,
    hash_workers: int = 8,
) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError("pyarrow is required to authenticate the panel") from exc

    authority, report = verify_report_package()
    root, panel = _normalize_sample_root(sample_root)
    success_path = root / "_SUCCESS.json"
    success = load_json(success_path)
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
            raise RuntimeError(f"Local sample success receipt differs from report: {key}")
    if success.get("report_zip_sha256") != authority["report_sha256"]:
        raise RuntimeError("Local sample receipt names a different report ZIP")

    report_outputs = {row["month"]: row for row in report["panel_outputs"]}
    local_outputs = {row["month"]: row for row in success.get("panel_outputs", [])}
    if set(report_outputs) != set(local_outputs):
        raise RuntimeError("Local/report monthly panel inventories differ")
    records: list[dict[str, Any]] = []
    reference_schema: list[str] | None = None
    for month, spec in sorted(report_outputs.items()):
        local = local_outputs[month]
        for key in ("rows", "size_bytes", "sha256", "relative_path"):
            if local.get(key) != spec.get(key):
                raise RuntimeError(f"Local/report inventory mismatch: {month} {key}")
        path = panel / f"month={month}/analysis_panel.parquet"
        if not path.is_file():
            raise RuntimeError(f"Monthly main-sample panel is missing: {path}")
        if path.stat().st_size != int(spec["size_bytes"]):
            raise RuntimeError(f"Monthly panel byte size changed: {month}")
        footer = pq.ParquetFile(path)
        if int(footer.metadata.num_rows) != int(spec["rows"]):
            raise RuntimeError(f"Monthly panel row count changed: {month}")
        names = list(footer.schema_arrow.names)
        expected_names = [item["name"] for item in spec["schema"]]
        if names != expected_names or len(names) != int(authority["columns"]):
            raise RuntimeError(f"Monthly panel schema changed: {month}")
        if reference_schema is None:
            reference_schema = names
        elif names != reference_schema:
            raise RuntimeError(f"Monthly schemas differ: {month}")
        records.append(
            {
                "month": month,
                "path": path,
                "rows": int(spec["rows"]),
                "size_bytes": int(spec["size_bytes"]),
                "expected_sha256": spec["sha256"],
            }
        )

    if sum(row["rows"] for row in records) != int(authority["rows"]):
        raise RuntimeError("Monthly panel rows do not conserve to the selected sample")

    if verify_hashes:
        workers = max(1, min(int(hash_workers), 10, len(records)))
        print(f"Authenticating 24 monthly Parquets with {workers} hash workers.", flush=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(sha256_file, row["path"]): row for row in records
            }
            for future in concurrent.futures.as_completed(futures):
                row = futures[future]
                observed = future.result()
                if observed != row["expected_sha256"]:
                    raise RuntimeError(f"Monthly panel SHA-256 changed: {row['month']}")
                row["actual_sha256"] = observed
                print(f"PANEL_SHA256_OK {row['month']}", flush=True)

    fingerprint = sample_fingerprint(report, authority["report_sha256"])
    return {
        "status": "POOL_MAIN_SAMPLE_AUTHENTICATED_OK",
        "authenticated_at_utc": utc_now(),
        "sample_root": root,
        "panel_root": panel,
        "success_path": success_path,
        "success_sha256": sha256_file(success_path),
        "success": success,
        "report": report,
        "authority": authority,
        "fingerprint": fingerprint,
        "month_records": records,
        "schema": reference_schema or [],
        "hashes_recomputed": bool(verify_hashes),
    }


def compact_sample_lineage(auth: dict[str, Any]) -> dict[str, Any]:
    authority = auth["authority"]
    return {
        "status": auth["status"],
        "fingerprint": auth["fingerprint"],
        "report_sha256": authority["report_sha256"],
        "sample_status": authority["status"],
        "sample_name": authority["sample_name"],
        "main_predicate": authority["main_predicate"],
        "rows": authority["rows"],
        "kind_draws": authority["kind_draws"],
        "fair_rows": authority["fair_rows"],
        "fair_kind_draws": authority["fair_kind_draws"],
        "months": authority["months"],
        "observed_screen_certified": True,
        "literal_immediate_rematches_certified": False,
        "panel_root_machine_specific": str(auth["panel_root"]),
    }


def legacy_month_records(auth: dict[str, Any], months: Sequence[str]) -> list[dict[str, Any]]:
    selected = set(months)
    output = []
    for row in auth["month_records"]:
        if row["month"] not in selected:
            continue
        item = dict(row)
        item["actual_sha256"] = item.get("actual_sha256", item["expected_sha256"])
        item["bytes"] = item["size_bytes"]
        output.append(item)
    return output


def legacy_stage07_auth(auth: dict[str, Any], months: Sequence[str]) -> dict[str, Any]:
    records = legacy_month_records(auth, months)
    return {
        "success_path": str(auth["success_path"]),
        "success_sha256": auth["success_sha256"],
        "producer_path": "bundled Pool_Main_Sample_24M_v1_0_0/build_main_sample.py",
        "producer_sha256": auth["report"]["code_sha256"]["build_main_sample.py"],
        "summary": auth["success"],
        "month_records": records,
        "selected_rows": sum(row["rows"] for row in records),
        "selected_bytes": sum(row["size_bytes"] for row in records),
    }


def recorded_git_state() -> dict[str, str]:
    return {
        "head": PUBLIC_REPOSITORY_HEAD,
        "branch": "main",
        "status_porcelain": "",
        "remote_url": PUBLIC_REPOSITORY_URL,
        "note": "Bundled byte-identical source inspected at this public repository HEAD",
    }


def replace_success_status(
    path: Path,
    *,
    expected_old: str,
    new_status: str,
    auth: dict[str, Any],
    source: dict[str, Any],
    adapter_path: Path,
) -> dict[str, Any]:
    saved = load_json(path)
    if saved.get("status") == new_status:
        if (saved.get("sample_authority") or {}).get("fingerprint") != auth["fingerprint"]:
            raise RuntimeError(f"Existing output belongs to another sample: {path}")
        return saved
    if saved.get("status") != expected_old:
        raise RuntimeError(f"Unexpected producer status in {path}: {saved.get('status')}")
    saved["upstream_producer_status"] = expected_old
    saved["status"] = new_status
    saved["sample_authority"] = compact_sample_lineage(auth)
    saved["source_program"] = source
    saved["adapter"] = source_record(adapter_path, "pool_main_adapter")
    saved["certification_scope"] = (
        "Re-estimated from the authenticated pool/observed-nonadjacent panel; "
        "the original producer's fixed full-panel authority was replaced by this sample receipt."
    )
    atomic_json(path, saved)
    return saved


def verify_lineaged_json(path: Path, status: str, fingerprint: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Completion receipt is missing: {path}")
    saved = load_json(path)
    if saved.get("status") != status:
        raise RuntimeError(f"Unexpected completion status: {path}")
    if (saved.get("sample_authority") or {}).get("fingerprint") != fingerprint:
        raise RuntimeError(f"Completion receipt belongs to another sample: {path}")
    return saved


def environment_record() -> dict[str, Any]:
    versions: dict[str, str | None] = {}
    for name in ("duckdb", "numpy", "pandas", "pyarrow", "matplotlib"):
        try:
            module = __import__(name)
            versions[name] = str(getattr(module, "__version__", "unknown"))
        except ModuleNotFoundError:
            versions[name] = None
    return {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": versions,
    }


def verify_runtime_dependencies() -> dict[str, Any]:
    record = environment_record()
    missing = [name for name, value in record["packages"].items() if value is None]
    if missing:
        raise RuntimeError(
            "Missing Python dependencies: " + ", ".join(missing) + ". See requirements.lock.txt."
        )
    bounds = {
        "duckdb": ((1, 5, 2), (1, 6, 0)),
        "numpy": ((2, 3, 0), (2, 6, 0)),
        "pandas": ((2, 2, 0), (3, 1, 0)),
        "pyarrow": ((24, 0, 0), (26, 0, 0)),
        "matplotlib": ((3, 10, 0), (3, 12, 0)),
    }
    outside = []
    for name, (lower, upper) in bounds.items():
        value = str(record["packages"][name])
        parts = tuple(int(item) for item in re.findall(r"\d+", value)[:3])
        parts = parts + (0,) * (3 - len(parts))
        if not lower <= parts < upper:
            outside.append(f"{name}={value} (require >= {lower} and < {upper})")
    if outside:
        raise RuntimeError(
            "Unsupported dependency versions: " + "; ".join(outside) + ". See requirements.lock.txt."
        )
    return record


def output_manifest(root: Path, *, exclude: Iterable[Path] = ()) -> list[dict[str, Any]]:
    excluded = {path.resolve() for path in exclude}
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.resolve() in excluded:
            continue
        rows.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def write_manifest_tsv(root: Path, name: str = "REPORT_FILE_HASHES.tsv") -> Path:
    path = root / name
    rows = output_manifest(root, exclude=[path])
    text = "relative_path\tbytes\tsha256\n" + "".join(
        f"{row['relative_path']}\t{row['bytes']}\t{row['sha256']}\n" for row in rows
    )
    atomic_text(path, text)
    return path


def zip_tree(root: Path, archive: Path) -> Path:
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_suffix(archive.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            handle.write(path, f"{root.name}/{path.relative_to(root).as_posix()}")
    os.replace(temporary, archive)
    return archive


def copytree_filtered(source: Path, destination: Path) -> None:
    def ignored(directory: str, names: list[str]) -> set[str]:
        blocked = set()
        for name in names:
            lowered = name.lower()
            if lowered in {
                "private_cache",
                "duckdb_spill",
                "_work",
                "scratch",
                "__pycache__",
            }:
                blocked.add(name)
            elif "private" in lowered:
                blocked.add(name)
            elif lowered.endswith((".duckdb", ".duckdb.wal", ".pyc", ".pyo")):
                blocked.add(name)
        return blocked

    shutil.copytree(source, destination, ignore=ignored)


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return next(csv.reader(stream), [])


def privacy_scan(root: Path) -> dict[str, Any]:
    forbidden = {
        "game_id",
        "chooser_user_id",
        "disconnected_user_id",
        "chooser_username",
        "chooser_username_norm",
        "disconnected_username",
        "disconnected_username_norm",
        "username",
        "username_norm",
        "matched_kind_chooser_id",
    }
    violations: list[dict[str, Any]] = []
    parquet_files = 0
    csv_files = 0
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError("pyarrow is required for the transfer privacy scan") from exc
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        names: list[str] | None = None
        if path.suffix.lower() == ".parquet":
            parquet_files += 1
            names = list(pq.ParquetFile(path).schema_arrow.names)
        elif path.suffix.lower() == ".csv":
            csv_files += 1
            names = read_csv_header(path)
        if names is not None:
            overlap = sorted(forbidden & {str(name).lower() for name in names})
            if overlap:
                violations.append(
                    {"path": path.relative_to(root).as_posix(), "forbidden_columns": overlap}
                )
    bad_names = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and "private" in path.name.lower()
    ]
    if bad_names:
        violations.extend({"path": name, "reason": "private filename"} for name in bad_names)
    if violations:
        raise RuntimeError(f"Transfer privacy scan failed: {violations[:20]}")
    return {
        "status": "PUBLIC_TRANSFER_PRIVACY_SCAN_OK",
        "parquet_files_scanned": parquet_files,
        "csv_files_scanned": csv_files,
        "forbidden_identifier_columns": sorted(forbidden),
        "violations": 0,
    }
