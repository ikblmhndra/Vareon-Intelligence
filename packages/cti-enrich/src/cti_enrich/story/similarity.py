"""Kemiripan judul TF-IDF (titik tukar ke model embedding nanti, spec bagian 8)."""

from __future__ import annotations

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def title_similarity(query: str, titles: list[str]) -> list[float]:
    """Cosine TF-IDF `query` terhadap tiap judul di `titles`.

    TF-IDF di-fit sekali pada `titles + [query]` (kosakata dan IDF dihitung dari kandidat
    yang ada). Kosakata kosong (semua token stop word) memberi `0.0` untuk semua.
    """
    if not titles:
        return []
    vectorizer = TfidfVectorizer(
        stop_words="english",
        token_pattern=r"(?u)\b[\w-]{2,}\b",
        sublinear_tf=True,
    )
    try:
        matrix = vectorizer.fit_transform([*titles, query])
    except ValueError:
        return [0.0] * len(titles)
    scores = cosine_similarity(matrix[-1], matrix[:-1])[0]
    return [float(s) for s in scores]
