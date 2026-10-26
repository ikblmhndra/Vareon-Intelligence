"""Model relevansi tiga kelas: fitur (TF-IDF kata + char + embedding) dan LR."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cti_enrich.relevance import model as rm

from tests.unit.relevance_fakes import FakeEmbedder

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _examples() -> list[rm.Example]:
    templates = {
        "reject": "webinar product launch {n}",
        "best_practice": "best practices for zero trust {n}",
        "threat_news": "ransomware attack on hospital {n}",
    }
    return [
        rm.Example(t.format(n=i), label, NOW) for label, t in templates.items() for i in range(20)
    ]


def _fit() -> rm.TrainedModel:
    return rm.fit(_examples(), FakeEmbedder())


def test_fit_predict_separates_synthetic_classes() -> None:
    examples = _examples()
    probs = rm.predict(_fit(), [e.title for e in examples], FakeEmbedder())
    hits = sum(
        max(rm.CLASSES, key=lambda c: getattr(p, c)) == e.label
        for p, e in zip(probs, examples, strict=True)
    )
    assert hits / len(examples) >= 0.95


def test_probs_sum_to_one() -> None:
    for p in rm.predict(_fit(), ["ransomware attack on clinic", "hello"], FakeEmbedder()):
        assert p.reject + p.best_practice + p.threat_news == pytest.approx(1.0)


def test_roundtrip_bytes() -> None:
    m = _fit()
    titles = ["ransomware attack on hospital 99", "best practices for patching"]
    restored = rm.loads(rm.dumps(m))
    assert rm.predict(restored, titles, FakeEmbedder()) == rm.predict(m, titles, FakeEmbedder())
    assert restored.feature_version == m.feature_version


def test_predict_odd_titles() -> None:
    out = rm.predict(_fit(), ["", "x", "Анализ угроз"], FakeEmbedder())
    assert len(out) == 3
    assert all(isinstance(p, rm.Probs) for p in out)


def test_fit_rejects_unknown_label() -> None:
    bad = [*_examples(), rm.Example("t", "other", NOW)]
    with pytest.raises(ValueError):
        rm.fit(bad, FakeEmbedder())


def test_feature_version_format() -> None:
    v = rm.feature_version(FakeEmbedder())
    assert v.startswith("fake|fastembed=") and "|sklearn=" in v
