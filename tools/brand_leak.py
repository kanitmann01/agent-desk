"""Scan committed presentation packs for denylisted fingerprints.

The hash list is `tools/brand_leak_hashes.txt`: one sha256 per line, of a
lower-cased token or of a media file's raw bytes. Comments start with #.
The list ships empty. To add a token locally:

    python -c "import hashlib; print(hashlib.sha256(b'the-token').hexdigest())"

Paste that line into the hash file, or into the untracked
`tools/brand_leak.local.txt`, which this command also reads. Neither file
should hold the token itself.

    python tools/brand_leak.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentdesk.presentations.leak import load_hashes, pack_roots, scan  # noqa: E402


def main() -> int:
    """Exit 1 when a committed template pack hits the hash list."""
    hashes = load_hashes(
        ROOT / "tools" / "brand_leak_hashes.txt",
        ROOT / "tools" / "brand_leak.local.txt",
    )
    roots = pack_roots(ROOT / "registry")
    hits = scan(roots, hashes)
    if hits:
        print("BRAND-LEAK FAIL")
        for hit in hits:
            print(f"FAIL {hit}")
        return 1
    print(f"BRAND-LEAK PASS ({len(roots)} pack(s), {len(hashes)} hash(es))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
