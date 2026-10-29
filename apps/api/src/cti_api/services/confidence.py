"""Port `ScraperNewsWeb/app/services/confidence_service.py`. Fase 7.4
Grup D (survei 2026-09-19). Dua skor beda tapi satu file (sama kayak
`cve_lookup.py`, Grup B) -- confidence artikel (grading Admiralty per
artikel + prioritas, P6) dan confidence+actionability IOC (recency+corroborasi+
peluruhan waktu), dua-duanya dipanggil dari router `articles`/`iocs`.

Sejak 0.8.6 confidence artikel ditulis LANGSUNG ke kolom `confidence_score` (sebelumnya lewat
`overrides`). Sejak P6 semua jalur (persist enrichment, endpoint, recompute) memakai
`cti_core.confidence.assess` lewat `repositories.assessment`: kredibilitas dihitung per artikel
dan override analis dihormati di `assess`, bukan dengan melewati artikelnya.

`compute_ioc_actionability`'s `campaign_score` SELALU 0 -- butuh
`CLUSTERS_COLLECTION` (mesin cluster, Grup A, BELUM diport, lihat plan
§Fase 7.4). Legacy sendiri fallback ke 0 lewat `try/except` kalau lookup
gagal; di sini permanen 0 sampai Grup A ada, pola fallback yang sama."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any

from cti_core.confidence import Assessment, assess
from cti_core.db.models.article import Article
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.assessment import (
    apply_assessments_async,
    facts_from_row,
    facts_stmt,
)
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ── Confidence artikel ───────────────────────────────────────────────────────

_MAX_BATCH = 500
"""Batas id per panggilan loader fakta (`facts_stmt` satu statement untuk semua id)."""


async def compute_article_confidence(session: AsyncSession, article: Article) -> Assessment:
    """Nilai satu artikel TANPA menulis apa pun (pratinjau). Fakta dibaca dari DB lewat loader
    yang sama dengan persist/recompute, jadi child row yang belum di-flush tidak terhitung."""
    row = (await session.execute(facts_stmt([article.id]))).mappings().one()
    return assess(facts_from_row(row))


async def compute_and_store_article_confidence(
    session: AsyncSession, article_id: int
) -> Assessment | None:
    """Port `compute_and_store()`. `None` kalau artikel gak ketemu. Menulis kolom penilaian P6
    (`reliability_grade`, `credibility`, `confidence_score`, `priority_score`, `score_reasons`);
    override analis (`overrides["credibility"]`/`["confidence_score"]`) dipakai `assess`, tidak
    lagi membuat artikel dilewati. Objek `Article` yang sudah dimuat sesi tidak ikut segar
    (bulk UPDATE): pemanggil yang membacanya harus refresh."""
    return (await apply_assessments_async(session, [article_id])).get(article_id)


async def recompute_all_confidence(
    session: AsyncSession,
    *,
    batch_size: int = _MAX_BATCH,
    source_name: str | None = None,
    commit_each_batch: bool = False,
    story_ids: Sequence[int] | None = None,
) -> dict[str, int]:
    """Port `recompute_all_confidence()`. Paging per `id` (yang dimuat cuma id, bukan objek
    `Article`), tiap halaman dinilai ulang dalam satu query fakta lewat `apply_assessments_async`;
    `batch_size` dipotong ke 500 karena itu batas loader fakta. `source_name`
    (case-insensitive) membatasi ke satu sumber (task `confidence.recompute_source`);
    `story_ids` membatasi ke anggota story tersebut (task `confidence.refresh_stories`, P6 4.2).
    Artikel ber-override ikut dinilai: `assess` yang memakai override-nya (P6 4.5).
    `commit_each_batch=True` (task worker) commit tiap batch, supaya recompute penuh di tabel
    besar tidak memegang lock baris sepanjang run; default-nya hanya flush (pemanggil yang
    commit)."""
    limit = max(1, min(batch_size, _MAX_BATCH))
    updated = 0
    last_id = 0
    while True:
        stmt = select(Article.id).where(Article.id > last_id).order_by(Article.id).limit(limit)
        if source_name is not None:
            stmt = stmt.where(func.lower(Article.source) == source_name.lower())
        if story_ids is not None:
            stmt = stmt.where(Article.story_id.in_(story_ids))
        ids = list((await session.execute(stmt)).scalars().all())
        if not ids:
            break
        last_id = ids[-1]
        updated += len(await apply_assessments_async(session, ids))
        if commit_each_batch:
            await session.commit()

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


def compute_ioc_confidence(ioc: Indicator, now: datetime.datetime) -> int:
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
    ioc: Indicator, now: datetime.datetime, *, confidence_score: int
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
    session: AsyncSession, ioc: Indicator, *, now: datetime.datetime | None = None
) -> Indicator:
    """Port bagian akhir `submit_feedback()` -- dipanggil router `iocs`
    SETELAH `AsyncIOCRepo.add_feedback()` (tp/fp_count udah ke-increment
    di objek `ioc` yang sama, jadi `compute_ioc_confidence` otomatis
    baca angka terbaru)."""
    now = now or datetime.datetime.now(datetime.UTC)
    confidence_score = compute_ioc_confidence(ioc, now)
    actionability = compute_ioc_actionability(ioc, now, confidence_score=confidence_score)
    return await AsyncIndicatorRepo(session).apply_confidence_and_actionability(
        ioc,
        confidence_score=confidence_score,
        actionability_score=actionability["actionability_score"],
        actionability_label=actionability["actionability_label"],
        recommended_action=actionability["recommended_action"],
        decayed_at=now,
    )
