"""IOCRepo -- satu-satunya jalur tulis `iocs`. Gantiin dua jalur nulis
terpisah di sistem lama (`dbMongo.upsert_ioc_from_feed` sync vs
`ioc_service.upsert_ioc` async, beda kekayaan data) -- lihat plan §6.
"""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any

from sqlalchemy import DateTime, bindparam, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.ioc import IOC, IOCFeedback, IOCSource, IOCTag, IOCThreatActor

_VALID_VERDICTS = frozenset({"tp", "fp"})
_VALID_TYPES = frozenset({"ip", "url", "domain", "email", "sha256", "sha1", "md5", "cve"})


class IOCRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        type: str,
        value: str,
        source_url: str,
        source_name: str,
        context: str | None = None,
        article_id: int | None = None,
    ) -> IOC:
        existing = self.session.execute(
            select(IOC).where(IOC.type == type, IOC.value == value)
        ).scalar_one_or_none()
        now = datetime.datetime.now(datetime.UTC)

        if existing is None:
            ioc = IOC(type=type, value=value, first_seen_at=now, last_seen_at=now, seen_count=1)
            self.session.add(ioc)
        else:
            ioc = existing
            ioc.last_seen_at = now
            ioc.seen_count += 1

        ioc.sources.append(
            IOCSource(
                url=source_url,
                source_name=source_name,
                context=context,
                article_id=article_id,
                first_seen_at=now,
            )
        )
        self.session.flush()
        return ioc

    def add_feedback(
        self, ioc: IOC, *, verdict: str, submitted_by: str, note: str | None = None
    ) -> IOC:
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"verdict '{verdict}' harus salah satu dari {_VALID_VERDICTS}")
        ioc.feedback.append(IOCFeedback(verdict=verdict, submitted_by=submitted_by, note=note))
        if verdict == "tp":
            ioc.tp_count += 1
        else:
            ioc.fp_count += 1
        self.session.flush()
        return ioc

    def get(self, *, type: str, value: str) -> IOC | None:
        return self.session.execute(
            select(IOC).where(IOC.type == type, IOC.value == value)
        ).scalar_one_or_none()


class AsyncIOCRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        type: str,
        value: str,
        source_url: str,
        source_name: str,
        context: str | None = None,
        article_id: int | None = None,
    ) -> IOC:
        result = await self.session.execute(select(IOC).where(IOC.type == type, IOC.value == value))
        existing = result.scalar_one_or_none()
        now = datetime.datetime.now(datetime.UTC)

        if existing is None:
            ioc = IOC(type=type, value=value, first_seen_at=now, last_seen_at=now, seen_count=1)
            self.session.add(ioc)
        else:
            ioc = existing
            ioc.last_seen_at = now
            ioc.seen_count += 1

        ioc.sources.append(
            IOCSource(
                url=source_url,
                source_name=source_name,
                context=context,
                article_id=article_id,
                first_seen_at=now,
            )
        )
        await self.session.flush()
        return ioc

    async def add_feedback(
        self, ioc: IOC, *, verdict: str, submitted_by: str, note: str | None = None
    ) -> IOC:
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"verdict '{verdict}' harus salah satu dari {_VALID_VERDICTS}")
        ioc.feedback.append(IOCFeedback(verdict=verdict, submitted_by=submitted_by, note=note))
        if verdict == "tp":
            ioc.tp_count += 1
        else:
            ioc.fp_count += 1
        await self.session.flush()
        return ioc

    async def apply_confidence_and_actionability(
        self,
        ioc: IOC,
        *,
        confidence_score: int,
        actionability_score: int,
        actionability_label: str,
        recommended_action: str,
        decayed_at: datetime.datetime,
    ) -> IOC:
        """Port bagian akhir `ioc_service.submit_feedback()` (Fase 7.4 Grup
        D) -- recompute confidence+actionability abis feedback baru masuk."""
        ioc.confidence_score = confidence_score
        ioc.confidence_decayed_at = decayed_at
        ioc.actionability_score = actionability_score
        ioc.actionability_label = actionability_label
        ioc.recommended_action = recommended_action
        await self.session.flush()
        return ioc

    async def get(self, *, type: str, value: str) -> IOC | None:
        result = await self.session.execute(select(IOC).where(IOC.type == type, IOC.value == value))
        return result.scalar_one_or_none()

    async def get_by_id(self, ioc_id: int) -> IOC | None:
        result = await self.session.execute(select(IOC).where(IOC.id == ioc_id))
        return result.scalar_one_or_none()

    async def list_by_ids(self, ioc_ids: Sequence[int]) -> list[IOC]:
        """Batch get -- port `_ioc_confidence_factor()`'s `$in` lookup
        (`campaign_scoring_service.py`, Fase 7.4 Grup A)."""
        if not ioc_ids:
            return []
        result = await self.session.execute(select(IOC).where(IOC.id.in_(ioc_ids)))
        return list(result.scalars().all())

    async def list_first_seen_on(self, day: datetime.date, *, limit: int = 200) -> list[IOC]:
        """Port `_collect_iocs()` (`recap_service.py`, Fase 7.3 router
        `recap`, Bagian 5) -- IOC yang PERTAMA ketemu tanggal ini."""
        result = await self.session.execute(
            select(IOC)
            .where(func.date(IOC.first_seen_at) == day)
            .order_by(IOC.first_seen_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_first_seen_by_type_between(
        self, start: datetime.date, end: datetime.date
    ) -> dict[str, int]:
        """IOC yang PERTAMA ketemu di `[start, end]` (inklusif), dihitung per `type` lewat
        GROUP BY: recap mingguan cuma butuh hitungan per tipe, jadi barisnya tidak perlu dimuat
        (seminggu bisa ribuan). Tanggalnya `func.date(timestamptz)`, jadi mengikuti timezone sesi
        DB seperti `list_first_seen_on`."""
        result = await self.session.execute(
            select(IOC.type, func.count())
            .where(func.date(IOC.first_seen_at).between(start, end))
            .group_by(IOC.type)
        )
        return {ioc_type: n for ioc_type, n in result.all()}

    async def list_needing_decay(self, cutoff: datetime.datetime, *, limit: int = 500) -> list[IOC]:
        """Port query `decay_sweep()` (`ioc_service.py` lama) -- IOC yang
        confidence-nya belum PERNAH dihitung ulang (`confidence_decayed_at`
        NULL) ATAU udah lebih lama dari `cutoff` (24 jam lalu, port apa
        adanya). `limit` -- Celery task (`ioc_decay`, Fase 7.8) manggil ini
        berulang tiap sweep sampai kosong, bukan sekali angkut semua (dataset
        bisa gede, satu UPDATE per-IOC lewat ORM -- lihat docstring
        `ioc_decay.decay_sweep`)."""
        result = await self.session.execute(
            select(IOC)
            .where(or_(IOC.confidence_decayed_at.is_(None), IOC.confidence_decayed_at < cutoff))
            .order_by(IOC.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_needing_enrichment(
        self,
        *,
        provider: str,
        types: Sequence[str],
        checked_before: datetime.datetime,
        limit: int,
    ) -> list[IOC]:
        """IOC bertipe `types` (bukan yang `auto_suppressed`) yang BELUM punya kartu `provider` di
        `enrichment.providers`, atau yang kartunya dicek sebelum `checked_before`. Terbaru dilihat
        dulu (`last_seen_at`), supaya jatah provider dipakai untuk IOC yang paling relevan.

        Kartu dicari lewat `jsonb_array_elements`: `enrichment` kosong (`{}`) tidak punya
        `providers`, jadi `COALESCE` ke array kosong dan IOC-nya terhitung belum dicek."""
        fresh_card = text(
            "NOT EXISTS (SELECT 1 FROM jsonb_array_elements("
            "COALESCE(iocs.enrichment -> 'providers', '[]'::jsonb)) AS card "
            "WHERE card ->> 'key' = :provider "
            "AND (card ->> 'checked_at')::timestamptz > :checked_before)"
        ).bindparams(
            bindparam("provider", provider),
            bindparam("checked_before", checked_before, type_=DateTime(timezone=True)),
        )
        stmt = (
            select(IOC)
            .where(IOC.type.in_(types), IOC.auto_suppressed.is_(False), fresh_card)
            .order_by(IOC.last_seen_at.desc(), IOC.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_enrichment_provider(
        self, ioc: IOC, card: dict[str, Any], *, now: datetime.datetime
    ) -> None:
        """Tulis kartu SATU provider ke `enrichment.providers` (mengganti kartu `key` yang sama,
        kartu provider lain tidak disentuh) dan perbarui `updated_at`. Kolom JSONB diganti dengan
        dict BARU, bukan dimutasi di tempat, supaya perubahannya terdeteksi."""
        current = dict(ioc.enrichment or {})
        cards = [c for c in current.get("providers", []) if c.get("key") != card["key"]]
        cards.append(card)
        cards.sort(key=lambda c: str(c.get("key", "")))
        current["providers"] = cards
        current["updated_at"] = now.strftime("%Y-%m-%d %H:%M UTC")
        ioc.enrichment = current
        await self.session.flush()

    async def list_filtered(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        ioc_type: str | None = None,
        search: str | None = None,
        tags: Sequence[str] | None = None,
        sort_by: str | None = None,
        actionability: str | None = None,
    ) -> tuple[list[IOC], int]:
        """Port `ioc_service.get_iocs()`. `actionability` (filter lama)
        gak diport pas Fase 7.3 -- waktu itu kolomnya emang belum ada.
        Fase 7.4 Grup D nambahin `actionability_label` ke skema (lihat
        `IOC.actionability_label`), jadi filter ini SEKARANG bisa
        diwire -- ditambahin di sini pas Grup G4 (`/intelligence/
        ioc-management`) baru butuh beneran dari frontend."""
        stmt = select(IOC)
        if ioc_type and ioc_type in _VALID_TYPES:
            stmt = stmt.where(IOC.type == ioc_type)
        if search:
            stmt = stmt.where(IOC.value.ilike(f"%{search}%"))
        if tags:
            stmt = stmt.join(IOC.tags).where(IOCTag.tag.in_(tags)).distinct()
        if actionability:
            stmt = stmt.where(IOC.actionability_label == actionability)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        order_col = IOC.confidence_score if sort_by == "confidence" else IOC.last_seen_at
        list_stmt = stmt.order_by(order_col.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(list_stmt)
        return list(result.scalars().unique().all()), total

    async def list_with_feedback(self) -> list[IOC]:
        """IOC yang punya minimal satu feedback (tp/fp) -- port filter
        `{"feedback_log": {"$exists": True, "$ne": []}}`
        (`fp_analytics_service.get_fp_analytics()`, Fase 7.4 Grup D)."""
        result = await self.session.execute(select(IOC).where(IOC.feedback.any()))
        return list(result.scalars().all())

    async def list_by_article_ids(self, article_ids: Sequence[int]) -> list[IOC]:
        """IOC (semua tipe, TERMASUK `type="cve"`) yang nyantol ke salah
        satu `article_ids` lewat `IOCSource` -- port `cluster_service.py`'s
        `ioc_map` building (Fase 7.4 Grup A, `get_recent_campaigns()`).
        Gantiin DUA sumber legacy sekaligus: koleksi `iocs` (IOC jaringan/
        hash) DAN `article.cves` (array terpisah, `iocExtractor.py`'s
        regex CVE match yang sama persis) -- di skema baru CVE mention
        cuma IOC biasa dengan `type="cve"`, gak ada array duplikat lagi."""
        if not article_ids:
            return []
        result = await self.session.execute(
            select(IOC).join(IOC.sources).where(IOCSource.article_id.in_(article_ids)).distinct()
        )
        return list(result.scalars().unique().all())

    async def cve_ids_by_article(self, article_ids: Sequence[int]) -> dict[int, set[str]]:
        """Id CVE (IOC `type="cve"`, huruf besar) per artikel lewat `IOCSource` -- satu query
        ramping: tanpa memuat objek IOC beserta sumber, tag, dan feedback-nya seperti
        `list_by_article_ids`. Inilah satu-satunya hubungan artikel -> CVE yang tersimpan (tidak
        ada tabel khusus; `persist` menulis IOC dari isi artikel), jadi mencakup CVE yang hanya
        disebut di body. Artikel tanpa CVE tidak ada di hasil."""
        if not article_ids:
            return {}
        result = await self.session.execute(
            select(IOCSource.article_id, IOC.value)
            .join(IOC, IOC.id == IOCSource.ioc_id)
            .where(IOC.type == "cve", IOCSource.article_id.in_(article_ids))
            .distinct()
        )
        found: dict[int, set[str]] = {}
        for article_id, value in result.all():
            found.setdefault(article_id, set()).add(value.upper())
        return found

    async def get_stats(self) -> dict[str, object]:
        total = (await self.session.execute(select(func.count()).select_from(IOC))).scalar_one()
        by_type_stmt = (
            select(IOC.type, func.count())
            .group_by(IOC.type)
            .order_by(func.count().desc(), IOC.type)  # tie-break: urutan deterministik
        )
        by_type = (await self.session.execute(by_type_stmt)).all()
        return {
            "total": total,
            "by_type": [{"type": t, "count": c} for t, c in by_type],
        }

    async def add_tags(self, ioc: IOC, tags: Sequence[str]) -> IOC:
        existing = {t.tag for t in ioc.tags}
        for tag in tags:
            if tag not in existing:
                ioc.tags.append(IOCTag(tag=tag))
                existing.add(tag)
        await self.session.flush()
        return ioc

    async def add_threat_actors(self, ioc: IOC, threat_actors: Sequence[str]) -> IOC:
        existing = {t.threat_actor for t in ioc.threat_actors}
        for actor in threat_actors:
            if actor not in existing:
                ioc.threat_actors.append(IOCThreatActor(threat_actor=actor))
                existing.add(actor)
        await self.session.flush()
        return ioc

    async def remove_threat_actor(self, ioc: IOC, actor: str) -> bool:
        match = next((t for t in ioc.threat_actors if t.threat_actor == actor), None)
        if match is None:
            return False
        # `.remove()` dari koleksi (bukan `session.delete()` langsung) --
        # `cascade="all, delete-orphan"` (model) yang urus DELETE pas
        # flush, DAN koleksi in-memory `ioc.threat_actors` langsung
        # ke-update tanpa staleness (lihat bug `update_client_ids`,
        # `AsyncUserRepo`, Fase 7.2 -- `session.delete()` langsung pada
        # child gak nyabut dia dari koleksi parent yang udah ke-load).
        ioc.threat_actors.remove(match)
        await self.session.flush()
        return True

    async def delete(self, ioc_id: int) -> bool:
        ioc = await self.get_by_id(ioc_id)
        if ioc is None:
            return False
        await self.session.delete(ioc)
        await self.session.flush()
        return True

    async def bulk_delete(self, ioc_ids: Sequence[int]) -> int:
        count = 0
        for ioc_id in ioc_ids:
            if await self.delete(ioc_id):
                count += 1
        return count
