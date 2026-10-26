"""Model relevansi judul tiga kelas: reject / best_practice / threat_news.

Fitur: TF-IDF kata (1,2) + TF-IDF karakter (char_wb 3-5) + embedding judul (384 dim),
digabung `hstack`, lalu regresi logistik. Embedding TIDAK ikut di-pickle: ia dihitung ulang
dari embedder yang dipasang saat `fit`/`predict`, jadi `feature_version` mencatat nama
embedder + versi pustaka agar model lama yang tidak cocok bisa dikenali dan dilewati.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import metadata
from typing import Any

import joblib
import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from cti_enrich.relevance.embedder import Embedder

CLASSES: tuple[str, str, str] = ("reject", "best_practice", "threat_news")


@dataclass(frozen=True)
class Example:
    title: str
    label: str
    at: datetime


@dataclass(frozen=True)
class Probs:
    reject: float
    best_practice: float
    threat_news: float


@dataclass
class TrainedModel:
    pipeline: Any
    feature_version: str


class _Pipeline:
    """Dua vectorizer + classifier dalam satu objek yang bisa di-pickle."""

    def __init__(self, word: TfidfVectorizer, char: TfidfVectorizer, clf: LogisticRegression):
        self.word = word
        self.char = char
        self.clf = clf

    def features(self, titles: Sequence[str], embeddings: np.ndarray) -> csr_matrix:
        return hstack(
            [self.word.transform(titles), self.char.transform(titles), csr_matrix(embeddings)],
            format="csr",
        )


def _pkg_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "none"


def feature_version(embedder: Embedder) -> str:
    fastembed = _pkg_version("fastembed")
    return f"{embedder.name}|fastembed={fastembed}|sklearn={_pkg_version('scikit-learn')}"


def fit(examples: Sequence[Example], embedder: Embedder) -> TrainedModel:
    unknown = {e.label for e in examples} - set(CLASSES)
    if unknown:
        raise ValueError(f"label di luar CLASSES: {sorted(unknown)}")
    titles = [e.title for e in examples]
    word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True, min_df=2)
    word.fit(titles)
    char.fit(titles)
    pipe = _Pipeline(word, char, LogisticRegression(C=4, class_weight="balanced", max_iter=3000))
    pipe.clf.fit(pipe.features(titles, embedder.embed(titles)), [e.label for e in examples])
    return TrainedModel(pipeline=pipe, feature_version=feature_version(embedder))


def predict(model: TrainedModel, titles: Sequence[str], embedder: Embedder) -> list[Probs]:
    if not titles:
        return []
    pipe: _Pipeline = model.pipeline
    proba = pipe.clf.predict_proba(pipe.features(titles, embedder.embed(titles)))
    # Petakan per NAMA kelas (classes_ terurut abjad, bukan urutan CLASSES).
    col = {name: i for i, name in enumerate(pipe.clf.classes_)}
    return [Probs(*(float(row[col[c]]) if c in col else 0.0 for c in CLASSES)) for row in proba]


def dumps(model: TrainedModel) -> bytes:
    buf = io.BytesIO()
    joblib.dump(model, buf)
    return buf.getvalue()


def loads(data: bytes) -> TrainedModel:
    loaded = joblib.load(io.BytesIO(data))
    if not isinstance(loaded, TrainedModel):
        raise ValueError("bukan TrainedModel")
    return loaded
