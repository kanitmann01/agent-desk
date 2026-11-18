"""Clustering for the repetition detector: small, pure, deterministic.

Normalized token-set Jaccard with a greedy pass in insertion order: good
enough to see "the same shape of request" without a model in the loop,
and stable across runs so tests can pin it.
"""

import hashlib
import re

_SIMILARITY_THRESHOLD = 0.6
_WORD = re.compile(r"[a-z0-9]+")


def normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return " ".join(_WORD.findall(text.lower()))


def tokens(text: str) -> frozenset[str]:
    """Token set of the normalized text; empty when nothing comparable is left."""
    return frozenset(normalize(text).split())


def similarity(a: str, b: str) -> float:
    """Jaccard overlap in [0.0, 1.0]; 0.0 when either side has no tokens."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def cluster_requests(texts: list[str]) -> list[list[int]]:
    """Greedy clusters as index lists, first-seen order preserved.

    A text joins the first cluster whose seed it resembles; otherwise it
    seeds a new one.
    """
    clusters: list[list[int]] = []
    seeds: list[frozenset[str]] = []
    for i, text in enumerate(texts):
        t = tokens(text)
        placed = False
        for ci, seed in enumerate(seeds):
            if t and seed and len(t & seed) / len(t | seed) >= _SIMILARITY_THRESHOLD:
                clusters[ci].append(i)
                placed = True
                break
        if not placed:
            seeds.append(t)
            clusters.append([i])
    return clusters


def pattern_hash(text: str) -> str:
    """A stable pattern identity for cooldowns, from the normalized shape."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()[:16]
