"""Port `ScraperNewsWeb/app/services/confidence_service.py`. Fase 7.4
Grup D (survei 2026-09-19). Dua skor beda tapi satu file (sama kayak
`cve_lookup.py`, Grup B) -- confidence artikel (grading Admiralty +
bonus TTP/TA) dan confidence+actionability IOC (recency+corroborasi+
peluruhan waktu), dua-duanya dipanggil dari router `articles`/`iocs`.

Confidence artikel ditulis lewat `AsyncArticleRepo.set_overrides()`
(BUKAN kolom `confidence_score` langsung) -- docstring `Article.overrides`
(Fase 2) SENGAJA nyebut `confidence_score` sebagai contoh field yang
dilacak lewat overrides, meskipun tulisan Mongo lama (`compute_and_store`)
langsung `$set` tanpa konsep override. Keputusan desain ini ngikutin
dokumentasi skema yang UDAH ADA, bukan port literal.

`compute_ioc_actionability`'s `campaign_score` SELALU 0 -- butuh
`CLUSTERS_COLLECTION` (mesin cluster, Grup A, BELUM diport, lihat plan
§Fase 7.4). Legacy sendiri fallback ke 0 lewat `try/except` kalau lookup
gagal; di sini permanen 0 sampai Grup A ada, pola fallback yang sama."""

from __future__ import annotations

import datetime
from typing import Any

from cti_core.db.models.article import Article
from cti_core.db.models.ioc import IOC
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sqlalchemy.ext.asyncio import AsyncSession

# ── Confidence artikel ───────────────────────────────────────────────────────

_RELIABILITY_SCORE = {"A": 100, "B": 80, "C": 60, "D": 40, "E": 20, "F": 50}
_CREDIBILITY_SCORE = {"1": 100, "2": 80, "3": 60, "4": 40, "5": 20, "6": 50}


def _reliability_to_score(grade: str) -> int:
    return _RELIABILITY_SCORE.get(grade.upper(), 50)


def _credibility_to_score(code: str) -> int:
    return _CREDIBILITY_SCORE.get(str(code), 50)


def compute_score(
    reliability_grade: str | None,
    credibility_code: str | None,
    ttp_count: int,
    ta_count: int,
) -> int:
    rel = _reliability_to_score(reliability_grade) if reliability_grade else 50
    cred = _credibility_to_score(credibility_code) if credibility_code else 50
    base = (rel + cred) / 2
    ttp_bonus = min(ttp_count * 5, 20)
    ta_bonus = min(ta_count * 10, 10)
    return min(100, max(0, round(base + ttp_bonus + ta_bonus)))


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
    """Port `compute_and_store()`. `None` kalau artikel gak ketemu."""
    repo = AsyncArticleRepo(session)
    article = await repo.get_by_id(article_id)
    if article is None:
        return None
    score = await compute_article_confidence(session, article)
    await repo.set_overrides(article, confidence_score=score)
    return score


async def recompute_all_confidence(
    session: AsyncSession, *, batch_size: int = 500
) -> dict[str, int]:
    """Port `recompute_all_confidence()`. Preload semua rating source dulu
    (hindari N+1 query per artikel, sama optimasi kayak legacy), lalu
    paging lewat `list_filtered()` -- gak ada method "list semua artikel"
    terpisah, `list_filtered()` tanpa filter udah setara."""
    ratings = await AsyncSourceReliabilityRepo(session).get_all_ratings()
    repo = AsyncArticleRepo(session)

    updated = 0
    page = 1
    while True:
        articles, total = await repo.list_filtered(page=page, page_size=batch_size)
        if not articles:
            break
        for article in articles:
            rating = ratings.get((article.source or "").lower())
            score = compute_score(
                reliability_grade=rating.reliability_grade if rating else None,
                credibility_code=rating.credibility_code if rating else None,
                ttp_count=len(article.ttps),
                ta_count=len(article.threat_actors),
            )
            await repo.set_overrides(article, confidence_score=score)
            updated += 1
        if page * batch_size >= total:
            break
        page += 1

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
