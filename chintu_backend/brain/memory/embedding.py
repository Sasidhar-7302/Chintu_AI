"""Lightweight embeddings for local memory without extra dependencies."""

from __future__ import annotations

import math
import re
import zlib
from typing import List


class BaseEmbedder:
    """Abstract embedder interface."""

    def embed(self, text: str) -> List[float]:
        raise NotImplementedError


class HashingEmbedder(BaseEmbedder):
    """Simple hashing embedder (bag-of-words) for CPU-only usage."""

    def __init__(self, dim: int = 256, seed: int = 13):
        self.dim = max(32, int(dim))
        self.seed = int(seed)

    def embed(self, text: str) -> List[float]:
        tokens = re.findall(r"[a-z0-9']+", text.lower())
        vec = [0.0] * self.dim
        if not tokens:
            return vec
        for token in tokens:
            idx = zlib.crc32((token + str(self.seed)).encode("utf-8")) % self.dim
            vec[idx] += 1.0
        return _normalize(vec)


def _normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]
