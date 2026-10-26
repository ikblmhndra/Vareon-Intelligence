"""Embedder palsu deterministik untuk test (CI tidak meng-install fastembed)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

DIM = 384


class FakeEmbedder:
    """Tiap token huruf kecil di-hash (blake2b, 8 byte) ke satu indeks dari 384 dimensi,
    dijumlahkan, lalu dinormalisasi L2. Judul dengan kata sama -> vektor mirip."""

    name = "fake"

    def embed(self, titles: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(titles), DIM), dtype=np.float32)
        for row, title in enumerate(titles):
            for token in title.lower().split():
                digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
                out[row, int.from_bytes(digest, "big") % DIM] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return (out / np.where(norms == 0, 1.0, norms)).astype(np.float32)
