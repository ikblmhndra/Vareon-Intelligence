"""Embedder judul berbasis fastembed (MiniLM), dipakai model relevansi dan story resolver.

`fastembed` di-import LAZY di dalam fungsi: image `api`/`worker` ringan tidak membawa
extra `nlp`, dan `cti_enrich.pipeline` harus tetap bisa di-import tanpanya
(`test_enrich_pipeline_imports_without_nlp_extra`). Model TIDAK pernah diunduh saat
runtime (`local_files_only=True`); cache-nya disiapkan di image (`FASTEMBED_CACHE_PATH`).
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any, Protocol

import numpy as np

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_REVISION = "d13954661f83248295ba75c1ed411eef3b7b936e"
"""Revisi HF model ONNX yang dipin di image; HARUS sama dengan `MINILM_REVISION` di
`docker/worker.Dockerfile` (dijaga `test_relevance_embedder.py`). Masuk `feature_version`
supaya ganti revisi memaksa latih ulang."""
EMBEDDING_DIM = 384


class EmbedderUnavailable(RuntimeError):
    """fastembed tidak ter-install, atau model tidak ada di disk."""


class Embedder(Protocol):
    name: str

    def embed(self, titles: Sequence[str]) -> np.ndarray:
        """Matriks `(n, 384)` float32 dengan baris ber-norma L2 = 1."""
        ...


class FastEmbedEmbedder:
    name = f"{EMBEDDING_MODEL}@{EMBEDDING_REVISION[:8]}"

    def __init__(self, model: Any) -> None:
        self._model = model

    def embed(self, titles: Sequence[str]) -> np.ndarray:
        if not titles:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        vectors = np.asarray(list(self._model.embed(list(titles))), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        # Norma nol (judul kosong) dibiarkan nol; jangan bagi dengan nol.
        return (vectors / np.where(norms == 0, 1.0, norms)).astype(np.float32)


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Singleton per proses; dibuat saat pertama dipakai (aman untuk prefork Celery)."""
    global _embedder
    if _embedder is None:
        _embedder = _load()
    return _embedder


def set_embedder(e: Embedder | None) -> None:
    """Hook test: pasang embedder palsu, atau `None` untuk reset singleton."""
    global _embedder
    _embedder = e


def _load() -> Embedder:
    try:
        from fastembed import TextEmbedding

        kwargs: dict[str, Any] = {"local_files_only": True}
        cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        model = TextEmbedding(EMBEDDING_MODEL, **kwargs)
    except Exception as exc:  # ImportError, model belum ada di disk, ONNX gagal load
        raise EmbedderUnavailable(f"embedder tidak tersedia: {exc}") from exc
    return FastEmbedEmbedder(model)
