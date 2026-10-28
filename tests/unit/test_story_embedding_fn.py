"""`_embedding_fn` (P5): cache vektor, kegagalan embed, dan embedder tak tersedia."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
import structlog
from cti_core.config import StorySettings
from cti_core.db.repositories.story import StoryCandidate, StoryMember
from cti_enrich.relevance import embedder as emb_mod
from cti_enrich.story import attach
from cti_enrich.story.resolver import ArticleKeys, Match, resolve

AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
ON = StorySettings(embedding_similarity=0.8)


class FakeEmbedder:
    name = "fake"

    def __init__(self) -> None:
        self.embedded: list[str] = []

    def embed(self, titles):
        self.embedded.extend(titles)
        return np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(titles), 1))


class Boom:
    name = "boom"

    def embed(self, titles):
        raise RuntimeError("onnx")


@pytest.fixture(autouse=True)
def _reset():
    attach._VEC_CACHE.clear()
    attach._embedding_unavailable_logged = False
    attach._embedding_failed_logged = False
    yield
    emb_mod.set_embedder(None)
    attach._VEC_CACHE.clear()


def test_disabled_returns_none():
    assert attach._embedding_fn(StorySettings()) is None


def test_unavailable_logged_once(monkeypatch):
    def fail():
        raise emb_mod.EmbedderUnavailable("x")

    monkeypatch.setattr(emb_mod, "get_embedder", fail)
    with structlog.testing.capture_logs() as logs:
        assert attach._embedding_fn(ON) is None
        assert attach._embedding_fn(ON) is None
    assert [e["event"] for e in logs].count("story_embedding_unavailable") == 1


def test_titles_embedded_once():
    fake = FakeEmbedder()
    emb_mod.set_embedder(fake)
    fn = attach._embedding_fn(ON)
    assert fn is not None
    assert fn("q1", ["a", "b"]) == [1.0, 1.0]
    fn("q2", ["a", "b"])
    assert fake.embedded.count("a") == 1
    assert fake.embedded.count("b") == 1


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(attach, "_VEC_CACHE_MAX", 3)
    emb_mod.set_embedder(FakeEmbedder())
    fn = attach._embedding_fn(ON)
    assert fn is not None
    fn("q", ["a", "b", "c", "d"])
    assert len(attach._VEC_CACHE) == 3


def test_embed_failure_falls_back_to_tfidf():
    emb_mod.set_embedder(Boom())
    fn = attach._embedding_fn(ON)
    assert fn is not None
    title = "Citrix confirms NetScaler zero-days exploited in attacks"
    c = StoryCandidate(1, frozenset(), AT, AT, [StoryMember(title, "Other")], False)
    with structlog.testing.capture_logs() as logs:
        got = resolve(
            ArticleKeys(title + " now", "A", frozenset(), AT), [c], ON, embedding_similarity=fn
        )
    assert got == Match(1, "title")
    assert "story_embedding_failed" in [e["event"] for e in logs]
