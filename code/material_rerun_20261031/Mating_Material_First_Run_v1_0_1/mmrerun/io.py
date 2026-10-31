from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def signature(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path, value):
    atomic_text(path, json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def record(path, **extra):
    path = Path(path).resolve()
    before = signature(path)
    result = dict(path=str(path), bytes=before[2], sha256=sha(path), **extra)
    require(signature(path) == before, "File changed while hashing: " + str(path))
    return result


def verify(rec):
    path = Path(rec["path"])
    require(path.is_file(), "Missing checkpoint file: " + str(path))
    require(path.stat().st_size == rec["bytes"] and sha(path) == rec["sha256"],
            "Checkpoint checksum mismatch: " + str(path))


def csv_file(path, rows, fields=None):
    import io
    rows = list(rows)
    if fields is None:
        fields = list(dict.fromkeys(k for r in rows for k in r))
    f = io.StringIO(newline="")
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(rows)
    atomic_text(path, f.getvalue())


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def scan(paths):
    return "read_parquet([" + ",".join(quote(p) for p in paths) + "], hive_partitioning=false)"


def database(folder, memory_gb, threads):
    import duckdb
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    c = duckdb.connect()
    c.execute("SET memory_limit=" + quote(f"{memory_gb:.2f}GB"))
    c.execute("SET threads=" + str(int(threads)))
    c.execute("SET temp_directory=" + quote(folder.resolve()))
    c.execute("SET preserve_insertion_order=false")
    return c


def copy_query(c, query, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".partial.parquet")
    if tmp.exists():
        tmp.unlink()
    c.execute("COPY (" + query + ") TO " + quote(tmp) +
              " (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 131072)")
    os.replace(tmp, path)


def log(message):
    print(time.strftime("[%Y-%m-%d %H:%M:%S UTC] ", time.gmtime()) + message, flush=True)


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
def lock(path):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("This rerun is already running in another terminal") from None
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()) + "\n")
        f.flush()
        yield


def package_sha(root):
    root = Path(root).resolve()
    manifest = root / "SHA256SUMS.txt"
    require(manifest.is_file(), "Package manifest is missing")
    for line in manifest.read_text().splitlines():
        expected, relative = line.split("  ", 1)
        p = (root / relative).resolve()
        require(p.is_relative_to(root), "Unsafe package manifest path")
        require(p.is_file() and sha(p) == expected, "Package checksum failed: " + relative)
    return sha(manifest)
