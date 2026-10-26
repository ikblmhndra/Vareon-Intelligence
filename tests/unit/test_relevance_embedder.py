"""Embedder relevance: fake deterministik, kegagalan fastembed, dan import pipeline."""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap

import numpy as np
import pytest
from cti_enrich.relevance import embedder
from cti_enrich.relevance.embedder import (
    EMBEDDING_DIM,
    EMBEDDING_REVISION,
    EmbedderUnavailable,
    FastEmbedEmbedder,
    get_embedder,
)

from tests.unit.relevance_fakes import FakeEmbedder


def test_fake_embedder_is_deterministic_and_normalised() -> None:
    fake = FakeEmbedder()
    titles = ["Ransomware hits hospital", "Patch Tuesday fixes zero-day"]

    first = fake.embed(titles)
    second = fake.embed(titles)

    assert first.shape == (2, EMBEDDING_DIM)
    assert first.dtype == np.float32
    assert np.array_equal(first, second)
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-5)


def test_get_embedder_without_fastembed_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    embedder.set_embedder(None)
    monkeypatch.setitem(sys.modules, "fastembed", None)

    with pytest.raises(EmbedderUnavailable) as excinfo:
        get_embedder()

    assert isinstance(excinfo.value.__cause__, ImportError)


def test_set_embedder_overrides_singleton() -> None:
    fake = FakeEmbedder()
    embedder.set_embedder(fake)
    try:
        assert get_embedder() is fake
    finally:
        embedder.set_embedder(None)


def test_pipeline_still_imports_without_fastembed() -> None:
    code = textwrap.dedent(
        """
        import sys
        sys.modules["fastembed"] = None
        import cti_enrich.pipeline
        import cti_enrich.relevance.embedder
        print("ok")
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180, check=False
    )

    assert proc.returncode == 0, proc.stderr[-3000:]


def test_embedding_revision_matches_dockerfile() -> None:
    from pathlib import Path

    dockerfile = Path(__file__).resolve().parents[2] / "docker" / "worker.Dockerfile"
    match = re.search(r"^ARG MINILM_REVISION=(\S+)$", dockerfile.read_text(), re.MULTILINE)

    assert match is not None
    assert match.group(1) == EMBEDDING_REVISION


def test_embedder_name_includes_revision() -> None:
    assert FastEmbedEmbedder.name.endswith(f"@{EMBEDDING_REVISION[:8]}")
