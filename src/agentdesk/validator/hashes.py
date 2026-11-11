"""Release hash pinning: verify files against the pinned release.lock.

release.lock lines look like "sha256 <hex hash> <filename>"; each listed
file's actual sha256 must match. A missing release.lock skips the check.
"""

import hashlib

from .model import Failure

LOCK_NAME = "release.lock"


def check_release_hashes(reader) -> list[Failure]:
    """Check every release.lock entry against actual file bytes."""
    lock_bytes = reader.read_bytes(LOCK_NAME)
    if lock_bytes is None:
        return []

    failures: list[Failure] = []
    for line in lock_bytes.decode("utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[0] != "sha256":
            continue
        expected_hash, filename = parts[1], parts[2]
        content = reader.read_bytes(filename)
        if content is None:
            failures.append(
                Failure("missing-file", f"release.lock lists missing file: {filename}")
            )
            continue
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != expected_hash:
            failures.append(Failure("hash-mismatch", f"sha256 mismatch for {filename}"))
    return failures
