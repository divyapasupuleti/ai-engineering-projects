"""Deterministic hashed embeddings (word + char-trigram features).

Stands in for text-embedding-3-small / bge-small so every project runs offline.
Swap `embed` for a real provider call; the rest of each pipeline is unchanged.
"""

from __future__ import annotations

import hashlib
import math

from common.text import content_tokens

DIM = 512


def _bucket(feature: str) -> tuple[int, float]:
    h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "little") % DIM
    sign = 1.0 if h[4] % 2 == 0 else -1.0
    return idx, sign


def embed(text: str) -> list[float]:
    vec = [0.0] * DIM
    for tok in content_tokens(text):
        idx, sign = _bucket("w:" + tok)
        vec[idx] += sign * 1.0
        padded = f"#{tok}#"
        for i in range(len(padded) - 2):
            idx, sign = _bucket("c:" + padded[i : i + 3])
            vec[idx] += sign * 0.35
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
