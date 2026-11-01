"""Port `ScraperNewsWeb/app/services/dedup_service.py`. Fase 7.4 Grup D.
TF-IDF (ngram 1-2) + cosine similarity + union-find buat kelompokkan
artikel near-duplicate berdasarkan judul. Dependency baru `scikit-learn`
(`apps/api/pyproject.toml`) -- stack yang sama juga dipakai Grup A
("mesin cluster", belum diport) buat clustering artikel, tapi dua-duanya
independen (satu judul-similarity buat dedup, satu full-text buat
campaign clustering).

`find_dedup_groups` SENGAJA sync (bukan `async def` kayak legacy) --
gak ada `await` di dalamnya sama sekali (murni CPU-bound sklearn),
`async` di kode lama gak ngapa-ngapain selain nambah boilerplate."""

from __future__ import annotations

import datetime
from typing import Any

from cti_core.db.repositories.article import AsyncArticleRepo
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.ext.asyncio import AsyncSession


def _make_uf(n: int) -> tuple[Any, Any]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    return find, union


def find_dedup_groups(
    articles: list[dict[str, Any]], threshold: float = 0.75
) -> list[dict[str, Any]]:
    """Kelompokkan artikel yang cosine similarity judulnya (TF-IDF) di
    atas `threshold`. Balikin satu artikel kanonik per grup (yang
    pertama -- caller wajib udah sort desc posted_on duluan), dianotasi
    `_dup_count`/`_dup_sources`/`_dup_urls`. Artikel tanpa near-duplicate
    balik apa adanya dengan `_dup_count=1`."""
    if len(articles) < 2:
        for a in articles:
            a.setdefault("_dup_count", 1)
            a.setdefault("_dup_sources", [])
            a.setdefault("_dup_urls", [])
        return articles

    valid_indices = [i for i, a in enumerate(articles) if (a.get("title") or "").strip()]
    invalid_indices = [i for i, a in enumerate(articles) if not (a.get("title") or "").strip()]

    if len(valid_indices) < 2:
        for a in articles:
            a.setdefault("_dup_count", 1)
            a.setdefault("_dup_sources", [])
            a.setdefault("_dup_urls", [])
        return articles

    titles = [articles[i]["title"].strip() for i in valid_indices]

    try:
        vectorizer = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1)
        tfidf_matrix = vectorizer.fit_transform(titles)
    except ValueError:
        for a in articles:
            a.setdefault("_dup_count", 1)
            a.setdefault("_dup_sources", [])
            a.setdefault("_dup_urls", [])
        return articles

    sim_matrix = cosine_similarity(tfidf_matrix)
    n = len(valid_indices)
    find, union = _make_uf(n)

    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i, j] > threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for pos in range(n):
        root = find(pos)
        groups.setdefault(root, []).append(pos)

    result: list[dict[str, Any]] = []
    for positions in groups.values():
        orig_indices = [valid_indices[p] for p in positions]
        canonical_orig_idx = orig_indices[0]
        canonical = articles[canonical_orig_idx]
        dup_orig_indices = orig_indices[1:]

        canonical["_dup_count"] = len(orig_indices)
        canonical["_dup_sources"] = [
            articles[i].get("source", "") for i in dup_orig_indices if articles[i].get("source")
        ]
        canonical["_dup_urls"] = [
            articles[i].get("url", "") for i in dup_orig_indices if articles[i].get("url")
        ]
        result.append(canonical)

    for i in invalid_indices:
        a = articles[i]
        a.setdefault("_dup_count", 1)
        a.setdefault("_dup_sources", [])
        a.setdefault("_dup_urls", [])
        result.append(a)

    return result


async def get_dedup_groups(
    session: AsyncSession, *, days: int = 7, threshold: float = 0.75, limit: int = 500
) -> dict[str, Any]:
    """Port `get_dedup_groups()` -- ambil artikel N hari terakhir, jalanin
    dedup, balikin cuma grup yang beneran duplikat (`_dup_count > 1`)."""
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    articles, _total = await AsyncArticleRepo(session).list_filtered(
        posted_on_start=cutoff, page=1, page_size=limit
    )

    total_articles = len(articles)
    if total_articles == 0:
        return {"groups": [], "total_articles": 0, "total_groups": 0, "duplicates_suppressed": 0}

    dicts = [
        {
            "id": a.id,
            "title": a.title,
            "url": a.url,
            "source": a.source,
            "posted_on": a.posted_on.isoformat() if a.posted_on else "",
            "impacted_industries": a.entity_names("identity"),
            "threat_actors": a.entity_names("intrusion-set"),
            "news_type": a.news_type or "",
        }
        for a in articles
    ]

    deduped = find_dedup_groups(dicts, threshold)
    dup_groups = [a for a in deduped if a.get("_dup_count", 1) > 1]
    duplicates_suppressed = sum(
        a.get("_dup_count", 1) - 1 for a in deduped if a.get("_dup_count", 1) > 1
    )

    return {
        "groups": dup_groups,
        "total_articles": total_articles,
        "total_groups": len(dup_groups),
        "duplicates_suppressed": duplicates_suppressed,
    }
