"""Process-local SHA256 memoization; every file is hashed on its first use.

No digest is trusted across restarts. Reuse requires the same resolved path,
device, inode, size, nanosecond mtime AND nanosecond ctime. Concurrent readers
share one hash; a change during hashing stops verification. Frozen checkpoint
schemas, dependency comparisons and expected SHA256 checks remain unchanged.
"""
from pathlib import Path
import threading


class DigestCache:
    def __init__(self, hash_file):
        self.hash_file = hash_file
        self.guard = threading.Lock()
        self.locks = {}
        self.values = {}
        self.hashes = 0
        self.hits = 0

    @staticmethod
    def fingerprint(path):
        s = path.stat()
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    def __call__(self, path):
        path = Path(path).resolve()
        with self.guard:
            lock = self.locks.setdefault(path, threading.Lock())
        with lock:
            before = self.fingerprint(path)
            entry = self.values.get(path)
            if entry is not None and entry[0] == before:
                with self.guard:
                    self.hits += 1
                return entry[1]
            digest = self.hash_file(path)
            if self.fingerprint(path) != before:
                raise RuntimeError('Input changed while hashing: ' + str(path))
            self.values[path] = (before, digest)
            with self.guard:
                self.hashes += 1
            return digest


def install(io):
    if not isinstance(io.sha, DigestCache):
        io.sha = DigestCache(io.sha)
    return io.sha
