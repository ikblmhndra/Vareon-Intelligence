"""Port `ScraperNewsWeb/app/services/confidence_service.py`. Fase 7.4
Grup D (survei 2026-09-19). Dua skor beda tapi satu file (sama kayak
`cve_lookup.py`, Grup B) -- confidence artikel (grading Admiralty +
bonus TTP/TA) dan confidence+actionability IOC (recency+corroborasi+
peluruhan waktu), dua-duanya dipanggil dari router `articles`/`iocs`.

Sejak 0.8.6 confidence artikel ditulis LANGSUNG ke kolom `confidence_score` (sebelumnya lewat
`overrides`), karena persist enrichment juga menulis kolom itu dengan rumus yang sama. Artikel
yang `overrides`-nya sudah membawa `confidence_score` (koreksi analis) dilewati: analis menang.

`compute_ioc_actionability`'s `campaign_score` SELALU 0 -- butuh
`CLUSTERS_COLLECTION` (mesin cluster, Grup A, BELUM diport, lihat plan
§Fase 7.4). Legacy sendiri fallback ke 0 lewat `try/except` kalau lookup
gagal; di sini permanen 0 sampai Grup A ada, pola fallback yang sama."""

from __future__ import annotations

import datetime
from typing import Any

from cti_core.confidence import compute_score
from cti_core.db.models.article import Article
from cti_core.db.models.ioc import IOC
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ── Confidence artikel ───────────────────────────────────────────────────────

__all__ = ["compute_score"]  # re-export: rumusnya pindah ke `cti_core.confidence` (0.8.6)


async def compute_article_confidence(session: AsyncSession, article: Article) -> int:
    rating = (
        await AsyncSourceReliabilityRepo(session).get_by_name_ci(article.source)
        if article.source
        else None
    )
    reliability_grade = rating.reliability_grade if rating else None
    credibility_code = rating.credibility_code if rating else None
    return compute_score(
        reliability_grade, credibility_code, len(article.ttps), len(article.threat_actors)
    )


async def compute_and_store_article_confidence(
    session: AsyncSession, article_id: int
) -> int | None:
    """Port `compute_and_store()`. `None` kalau artikel gak ketemu. Ditulis ke kolom
    `confidence_score`; kalau analis sudah menimpa lewat `overrides`, nilai itu yang dikembalikan
    dan kolom tidak disentuh."""
    article = await AsyncArticleRepo(session).get_by_id(article_id)
    if article is None:
        return None
    if "confidence_score" in article.overrides:
        return int(article.overrides["confidence_score"])
    score = await compute_article_confidence(session, article)
    article.confidence_score = score
    await session.flush()
    return score


async def recompute_all_confidence(
    session: AsyncSession, *, batch_size: int = 500, source_name: str | None = None
) -> dict[str, int]:
    """Port `recompute_all_confidence()`. Preload semua rating source dulu (hindari N+1 query per
    artikel), lalu paging per `id`. `source_name` (case-insensitive) membatasi ke satu sumber
    (task `confidence.recompute_source`). Menulis kolom `confidence_score`, melewati artikel yang
    `overrides`-nya membawa `confidence_score`."""
    ratings = {
        name: (e.reliability_grade, e.credibility_code)
        for name, e in (await AsyncSourceReliabilityRepo(session).get_all_ratings()).items()
    }

    updated = 0
    last_id = 0
    while True:
        stmt = select(Article).where(Article.id > last_id).order_by(Article.id).limit(batch_size)
        if source_name is not None:
            stmt = stmt.where(func.lower(Article.source) == source_name.lower())
        articles = list((await session.execute(stmt)).scalars().all())
        if not articles:
            break
        for article in articles:
            last_id = article.id
            if "confidence_score" in article.overrides:
                continue
            grade, code = ratings.get((article.source or "").lower(), (None, None))
            article.confidence_score = compute_score(
                reliability_grade=grade,
                credibility_code=code,
                ttp_count=len(article.ttps),
                ta_count=len(article.threat_actors),
            )
            updated += 1
        await session.flush()
        for article in articles:  # jaga identity map tetap kecil di recompute besar
            session.expunge(article)

    return {"updated": updated}


# ── Confidence + actionability IOC ───────────────────────────────────────────

_IOC_HALF_LIFE: dict[str, float] = {
    "ip": 30.0,
    "domain": 60.0,
    "url": 30.0,
    "email": 30.0,
    "sha256": 90.0,
    "sha1": 90.0,
    "md5": 90.0,
}
"""Legacy juga punya entry `url_with_path` -- tipe itu gak ada di
`IOC._VALID_TYPES` skema baru (cuma `url`), jadi entry dead-nya di-drop,
bukan diikutin (bukan bug, cuma noise dari enum IOC type yang beda)."""


def compute_ioc_confidence(ioc: IOC, now: datetime.datetime) -> int:
    age_days = max((now - ioc.last_seen_at).total_seconds() / 86400, 0)

    base = 50
    recency_bonus = 30 if age_days <= 7 else 0
    source_bonus = min(len(ioc.sources) * 10, 30)
    tp, fp = ioc.tp_count, ioc.fp_count
    verdict_bonus = 20 * tp / (tp + fp + 1)

    raw = base + recency_bonus + source_bonus + verdict_bonus
    half_life = _IOC_HALF_LIFE.get(ioc.type, 30.0)
    decayed = raw * (0.5 ** (age_days / half_life))

    # `int()` di sini BUKAN redundant (walau ruff RUF046 ngira gitu) --
    # `float ** float` di typeshed balik `Any` (nampung kasus basis
    # negatif -> complex), jadi `round(decayed)` juga `Any` buat mypy;
    # `int()` eksplisit yang bikin return type ke-infer bener.
    return max(0, min(100, int(round(decayed))))  # noqa: RUF046


_ACTIONABILITY_LABELS = [
    (75, "block_now"),
    (50, "investigate"),
    (25, "monitor"),
    (0, "archive"),
]

_BLOCK_HASH_TYPES = {"sha256", "sha1", "md5"}
_BLOCK_NET_TYPES = {"ip", "domain"}


def _recommended_action(label: str, ioc_type: str) -> str:
    if label == "block_now":
        if ioc_type in _BLOCK_HASH_TYPES:
            return "Add to EDR blocklist"
        return "Add to firewall blocklist immediately"
    if label == "investigate":
        return "Verify in environment, check for matches in last 30 days"
    if label == "monitor":
        return "Add to watchlist, no immediate action"
    return "Low priority, aging indicator"


def compute_ioc_actionability(
    ioc: IOC, now: datetime.datetime, *, confidence_score: int
) -> dict[str, Any]:
    """`confidence_score` diterima sebagai parameter (bukan baca
    `ioc.confidence_score`) -- port urutan `submit_feedback()` lama: skor
    confidence BARU (hasil `compute_ioc_confidence` di panggilan yang
    sama) dipakai buat hitung actionability, bukan skor lama yang belum
    ke-update."""
    age_days = max((now - ioc.last_seen_at).total_seconds() / 86400, 0)
    if age_days <= 1:
        recency = 100
    elif age_days <= 3:
        recency = 80
    elif age_days <= 7:
        recency = 60
    elif age_days <= 30:
        recency = 30
    else:
        recency = 0

    campaign_score = 0  # lihat docstring modul -- nunggu Grup A

    seen_count = ioc.seen_count
    if seen_count >= 5:
        corroboration = 100
    elif seen_count >= 3:
        corroboration = 70
    elif seen_count >= 2:
        corroboration = 40
    else:
        corroboration = 10

    score = round(
        recency * 0.40 + campaign_score * 0.25 + confidence_score * 0.20 + corroboration * 0.15
    )
    score = max(0, min(100, score))

    label = "archive"
    for threshold, lbl in _ACTIONABILITY_LABELS:
        if score >= threshold:
            label = lbl
            break

    return {
        "actionability_score": score,
        "actionability_label": label,
        "recommended_action": _recommended_action(label, ioc.type),
    }


async def recompute_ioc_confidence_and_actionability(
    session: AsyncSession, ioc: IOC, *, now: datetime.datetime | None = None
) -> IOC:
    """Port bagian akhir `submit_feedback()` -- dipanggil router `iocs`
    SETELAH `AsyncIOCRepo.add_feedback()` (tp/fp_count udah ke-increment
    di objek `ioc` yang sama, jadi `compute_ioc_confidence` otomatis
    baca angka terbaru)."""
    now = now or datetime.datetime.now(datetime.UTC)
    confidence_score = compute_ioc_confidence(ioc, now)
    actionability = compute_ioc_actionability(ioc, now, confidence_score=confidence_score)
    return await AsyncIOCRepo(session).apply_confidence_and_actionability(
        ioc,
        confidence_score=confidence_score,
        actionability_score=actionability["actionability_score"],
        actionability_label=actionability["actionability_label"],
        recommended_action=actionability["recommended_action"],
        decayed_at=now,
    )
