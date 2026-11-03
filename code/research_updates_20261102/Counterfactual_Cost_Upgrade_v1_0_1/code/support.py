from __future__ import annotations

import concurrent.futures as cf
import contextlib
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from engine import AUTHORS, MONTHS, require

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0.1"
EXPECTED_ORIGINAL_ROWS = 41534331
EXPECTED_EXCLUDED_ROWS = 41534289


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(s):
    print(f"[{now()}] {s}", flush=True)


def read_json(p):
    with Path(p).open(encoding="utf-8") as f:
        return json.load(f)


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()


def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def atomic_text(p, s):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + p.name, dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(s)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_json(p, x):
    atomic_text(p, json.dumps(x, sort_keys=True, indent=2, allow_nan=False) + "\n")


def stamp(p):
    s = Path(p).stat()
    return [s.st_size, s.st_mtime_ns, s.st_ino]


def record(p, **kw):
    p = Path(p)
    return {"path": str(p.resolve()), "sha256": sha(p), "bytes": p.stat().st_size, **kw}


def verify_package(root=ROOT):
    lines = (root / "SHA256SUMS.txt").read_text().splitlines()
    require(lines, "Package checksum manifest is empty")
    for line in lines:
        want, relative = line.split("  ", 1)
        p = (root / relative).resolve()
        require(p.is_relative_to(root.resolve()), "Unsafe package manifest path")
        require(p.is_file() and sha(p) == want, f"Package checksum failed: {relative}")
    return sha(root / "SHA256SUMS.txt")


@contextlib.contextmanager
def heartbeat(label, seconds=20):
    stop = threading.Event()
    start = time.monotonic()
    def tick():
        while not stop.wait(seconds):
            log(f"{label}; elapsed {(time.monotonic()-start)/60:.1f} min")
    t = threading.Thread(target=tick, daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        t.join()


@contextlib.contextmanager
def lock(p):
    """OS lock is released after crashes; no stale lock deletion is needed."""
    import fcntl
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    f = p.open("a+")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another process is already running this cost job") from None
        f.seek(0)
        f.truncate()
        f.write(canonical({"pid": os.getpid(), "host": socket.gethostname(), "started": now()}))
        f.flush()
        yield
    finally:
        f.close()


def authenticate(project, manifest_path=None, sample_root=None, hash_workers=2, authority_path=None):
    """Use the existing author-exclusion manifest; otherwise the pinned original.

    The original fallback is permitted only by the bundled 24 file hashes and
    applies the two-name exclusion itself. It never changes the historical replay.
    authority_path exists for synthetic tests; the CLI never exposes it.
    """
    report = read_json(authority_path or ROOT / "authority/MAIN_SAMPLE_REPORT.json")
    require(report["observed_screen_certified"] is True, "Uncertified parent selection")
    pins = {x["month"]: x for x in report["panel_outputs"]}
    require(sorted(pins) == MONTHS, "Pinned parent does not cover the 24 main months")
    expected_original = sum(x["rows"] for x in pins.values())
    if authority_path is None:
        require(expected_original == EXPECTED_ORIGINAL_ROWS, "Wrong parent sample size")
    project = Path(project).expanduser().resolve()
    auto = project / "derived/replication/author_exclusion_v100_PRIVATE/AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json"
    manifest = Path(manifest_path).expanduser().resolve() if manifest_path else auto
    if sample_root is not None:
        require(manifest_path is None, "Choose a manifest or an original sample root, not both")
    use_excluded = sample_root is None and manifest.is_file()
    require(not manifest_path or manifest.is_file(), "Explicit author-exclusion manifest is missing")
    if use_excluded:
        m = read_json(manifest)
        require(m.get("contract") == "AUTHOR_EXCLUDED_MAIN_24M_V1", "Wrong author-exclusion contract")
        require(tuple(sorted(x.strip().lower() for x in m["policy"]["excluded_usernames"])) == AUTHORS,
                "Author-exclusion policy names differ")
        originals = {x["month"]: x for x in m["audited_inputs"] if x["family"] == "main_24m"}
        require(sorted(originals) == MONTHS, "Author manifest lacks original main-panel lineage")
        for month in MONTHS:
            require(originals[month]["sha256"] == pins[month]["sha256"],
                    f"Author-excluded source has different parent bytes: {month}")
        records = [dict(x) for x in m["datasets"]["main_24m"]]
        require(sorted(x["month"] for x in records) == MONTHS, "Wrong author-excluded month inventory")
        provenance = {"mode": "authenticated_author_excluded", "manifest_sha256": sha(manifest),
                      "policy_sha256": m["policy_sha256"], "manifest_path": str(manifest)}
    else:
        base = Path(sample_root).expanduser().resolve() if sample_root else project / (
            "derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE")
        if base.name == "panel":
            base = base.parent
        require((base / "_SUCCESS.json").is_file(), "Original main-panel completion receipt is missing")
        records = [{"month": mo, "path": str(base / pins[mo]["relative_path"]),
                    "rows": pins[mo]["rows"], "sha256": pins[mo]["sha256"]} for mo in MONTHS]
        provenance = {"mode": "pinned_original_with_direct_author_filter",
                      "completion_sha256": sha(base / "_SUCCESS.json"), "sample_root": str(base)}
    records.sort(key=lambda x: x["month"])
    def check(r):
        p = Path(r["path"]).expanduser().resolve()
        require(p.is_file(), f"Missing input Parquet: {p}")
        before = stamp(p)
        require(sha(p) == r["sha256"], f"Input checksum mismatch: {r['month']}")
        pf = pq.ParquetFile(p)
        require(pf.metadata.num_rows == r["rows"], f"Input row-count mismatch: {r['month']}")
        require(stamp(p) == before, "Input changed during authentication")
        return {"month": r["month"], "path": str(p), "rows": r["rows"], "sha256": r["sha256"],
                "stamp": before, "columns": pf.schema_arrow.names}
    with heartbeat("Authenticating the 24 input Parquets"), cf.ThreadPoolExecutor(max_workers=hash_workers) as pool:
        checked = list(pool.map(check, records))
    provenance.update({"files": checked, "parent_report_sha256": sha(authority_path or ROOT / "authority/MAIN_SAMPLE_REPORT.json"),
                       "expected_original_rows": expected_original,
                       "excluded_accounts": list(AUTHORS), "runtime": now()})
    if use_excluded and authority_path is None:
        require(sum(r["rows"] for r in checked) == EXPECTED_EXCLUDED_ROWS,
                "Author-excluded main size differs from 41,534,289; do not silently change sample")
    return checked, provenance


def write_table(path, rows):
    """Write both readable CSV and typed Parquet for aggregate results."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        rows = [{"status": "no_rows"}]
    table = pa.Table.from_pylist(rows)
    tmp = path.with_suffix(".parquet.partial")
    pq.write_table(table, tmp, compression="zstd")
    os.replace(tmp, path.with_suffix(".parquet"))
    with path.with_suffix(".csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=table.column_names)
        writer.writeheader()
        writer.writerows(table.to_pylist())


def bundle_report(report_dir, desktop, fingerprint, percent):
    """Only aggregate tables, methods and redacted receipts leave the private tree."""
    report_dir, desktop = Path(report_dir), Path(desktop)
    desktop.mkdir(parents=True, exist_ok=True)
    dest = desktop / f"COST_UPGRADE_{fingerprint[:12]}_{percent:03d}.zip"
    temp = dest.with_suffix(".zip.partial")
    files = sorted(p for p in report_dir.rglob("*") if p.is_file())
    require(all("PRIVATE" not in p.name for p in files), "Private file entered report folder")
    sums = "".join(f"{sha(p)}  {p.relative_to(report_dir).as_posix()}\n" for p in files if p.name != "SHA256SUMS.txt")
    atomic_text(report_dir / "SHA256SUMS.txt", sums)
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(report_dir.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(report_dir))
    os.replace(temp, dest)
    atomic_text(dest.with_suffix(".zip.sha256"), f"{sha(dest)}  {dest.name}\n")
    return dest
