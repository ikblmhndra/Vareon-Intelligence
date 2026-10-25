"""Kemiripan judul TF-IDF (titik tukar ke model embedding nanti, spec bagian 8)."""

from __future__ import annotations

import re

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_PERIOD_WORDS = frozenset(
    [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
        "report",
        "reports",
        "week",
        "weekly",
        "monthly",
        "quarter",
        "quarterly",
        "q1",
        "q2",
        "q3",
        "q4",
        "trend",
        "trends",
    ]
)
"""Kata periode/laporan generik: dua judul "laporan September 2026" tidak berarti berita
yang sama (Ruling 9)."""
_STOP_WORDS = sorted(ENGLISH_STOP_WORDS | _PERIOD_WORDS)
_YEAR = re.compile(r"\b(19|20)\d\d\b")


def _blank_years(text: str) -> str:
    return _YEAR.sub(" ", text.lower())


def title_similarity(query: str, titles: list[str]) -> list[float]:
    """Cosine TF-IDF `query` terhadap tiap judul di `titles`.

    TF-IDF di-fit sekali pada `titles + [query]` (kosakata dan IDF dihitung dari kandidat
    yang ada). Kosakata kosong (semua token stop word) memberi `0.0` untuk semua.
    """
    if not titles:
        return []
    vectorizer = TfidfVectorizer(
        stop_words=_STOP_WORDS,
        preprocessor=_blank_years,
        token_pattern=r"(?u)\b[\w-]{2,}\b",
        sublinear_tf=True,
    )
    try:
        matrix = vectorizer.fit_transform([*titles, query])
    except ValueError:
        return [0.0] * len(titles)
    scores = cosine_similarity(matrix[-1], matrix[:-1])[0]
    return [float(s) for s in scores]
