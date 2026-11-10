"""IndicatorRepo -- satu-satunya jalur tulis `indicators`. Gantiin dua jalur nulis
terpisah di sistem lama (`dbMongo.upsert_ioc_from_feed` sync vs
`ioc_service.upsert_ioc` async, beda kekayaan data) -- lihat plan §6.
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator, Sequence
from typing import Any

from sqlalchemy import DateTime, Select, bindparam, delete, func, or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, noload

from cti_core.config import IndicatorSettings, get_settings
from cti_core.db.models.entity import Entity, EntityMention
from cti_core.db.models.indicator import (
    Indicator,
    IndicatorFeedback,
    IndicatorSource,
    IndicatorTag,
)
from cti_core.entity.mentions import (
    MentionInput,
    insert_mentions,
    mention_rows,
    resolve_all_async,
)
from cti_core.indicator.marking import stricter_pap, stricter_tlp
from cti_core.indicator.stix_id import indicator_uuid
from cti_core.indicator.validity import HASH_TYPES, TTL_TYPES, extend, ttl_days, ttl_fingerprint

_VALID_VERDICTS = frozenset({"tp", "fp"})
_VALID_TYPES = frozenset({"ip", "url", "domain", "email", "sha256", "sha1", "md5"})
_TTL_FINGERPRINT_KEY = "indicator.ttl_fingerprint"
_EXPORT_BATCH = 2000
"""Ukuran batch keyset export CSV IOC (dibaca saat dipanggil, jadi test bisa mengecilkannya)."""


def _apply_upsert(
    session: Any,
    existing: Indicator | None,
    *,
    type: str,
    value: str,
    source_url: str,
    source_name: str,
    context: str | None,
    article_id: int | None,
    suppression_reason: str | None,
    tlp: str,
    pap: str,
) -> Indicator:
    """Aturan ingest P7a (spec 3.2) untuk jalur sync dan async: satu implementasi supaya tidak
    melenceng. Terlihat lagi memperpanjang `valid_until` (indikator kedaluwarsa jadi aktif lagi),
    `valid_from` dan `revoked_at` tidak disentuh (FP analis final; sumber barunya tetap dicatat),
    marking hanya naik ke yang lebih ketat."""
    now = datetime.datetime.now(datetime.UTC)
    cfg = get_settings().indicator
    if existing is None:
        indicator = Indicator(
            type=type,
            value=value,
            first_seen_at=now,
            last_seen_at=now,
            seen_count=1,
            stix_id=indicator_uuid(type, value),
            valid_from=now,
            valid_until=extend(None, type, now, cfg),
            tlp=tlp,
            pap=pap,
        )
        session.add(indicator)
    else:
        indicator = existing
        if indicator.stix_id is None:  # baris dari kode lama hasil rollback
            indicator.stix_id = indicator_uuid(type, value)
        indicator.last_seen_at = now
        indicator.seen_count += 1
        indicator.valid_until = extend(indicator.valid_until, type, now, cfg)
        indicator.tlp = stricter_tlp(indicator.tlp, tlp)
        indicator.pap = stricter_pap(indicator.pap, pap)
    # Baris yang SUDAH tersuppress tidak ditimpa alasannya (jejak pertama dipertahankan).
    if suppression_reason is not None and not indicator.auto_suppressed:
        indicator.auto_suppressed = True
        indicator.suppression_reason = suppression_reason

    indicator.sources.append(
        IndicatorSource(
            url=source_url,
            source_name=source_name,
            context=context,
            article_id=article_id,
            first_seen_at=now,
        )
    )
    return indicator


def _apply_verdict(indicator: Indicator, verdict: str, submitted_by: str) -> None:
    """FP mencabut (revoked_at pertama dipertahankan), TP memulihkan: verdict analis final (P7a)."""
    if verdict == "tp":
        indicator.tp_count += 1
        indicator.revoked_at = None
        indicator.revoked_by = None
    else:
        indicator.fp_count += 1
        if indicator.revoked_at is None:
            indicator.revoked_at = datetime.datetime.now(datetime.UTC)
            indicator.revoked_by = submitted_by


class IndicatorRepo:
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
        suppression_reason: str | None = None,
        tlp: str = "clear",
        pap: str = "clear",
    ) -> Indicator:
        existing = self.session.execute(
            select(Indicator).where(Indicator.type == type, Indicator.value == value)
        ).scalar_one_or_none()
        indicator = _apply_upsert(
            self.session,
            existing,
            type=type,
            value=value,
            source_url=source_url,
            source_name=source_name,
            context=context,
            article_id=article_id,
            suppression_reason=suppression_reason,
            tlp=tlp,
            pap=pap,
        )
        self.session.flush()
        return indicator

    def add_feedback(
        self, indicator: Indicator, *, verdict: str, submitted_by: str, note: str | None = None
    ) -> Indicator:
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"verdict '{verdict}' harus salah satu dari {_VALID_VERDICTS}")
        indicator.feedback.append(
            IndicatorFeedback(verdict=verdict, submitted_by=submitted_by, note=note)
        )
        _apply_verdict(indicator, verdict, submitted_by)
        self.session.flush()
        return indicator

    def reconcile_validity(self, cfg: IndicatorSettings) -> dict[str, int]:
        """Isi/sinkronkan `valid_until = last_seen_at + TTL` untuk indikator tak-dicabut
        (spec P7a 3.3). Selalu menjalankan langkah murah "isi yang NULL" (baris yang masuk dari
        kode lama hasil rollback, atau sebelum reconcile pertama, tidak boleh aktif selamanya).
        Re-sync penuh (timpa semua nilai) hanya bila sidik jari TTL berubah/belum tersimpan;
        `skipped` = 1 bila re-sync penuh dilewati. Dicabut tidak disentuh; hash selalu NULL."""
        from cti_core.db.repositories.report_state import JobStateRepo

        states = JobStateRepo(self.session)
        fingerprint = ttl_fingerprint(cfg)
        full = states.get(_TTL_FINGERPRINT_KEY) != fingerprint
        by_days: dict[int, list[str]] = {}
        for t in TTL_TYPES:
            days = ttl_days(t, cfg)
            assert days is not None
            by_days.setdefault(days, []).append(t)
        self._fill_stix_ids()
        guard = (
            " AND valid_until IS DISTINCT FROM last_seen_at + make_interval(days => :d)"
            if full
            else " AND valid_until IS NULL"
        )
        updated = 0
        for days, types in by_days.items():
            res = self.session.execute(
                text(
                    "UPDATE indicators SET valid_until = last_seen_at + make_interval(days => :d)"
                    " WHERE type = ANY(:types) AND revoked_at IS NULL" + guard
                ),
                {"d": days, "types": types},
            )
            updated += res.rowcount  # type: ignore[attr-defined]
        if not full:
            return {"updated": updated, "skipped": 1}
        res = self.session.execute(
            text(
                "UPDATE indicators SET valid_until = NULL WHERE type = ANY(:types)"
                " AND revoked_at IS NULL AND valid_until IS NOT NULL"
            ),
            {"types": sorted(HASH_TYPES)},
        )
        updated += res.rowcount  # type: ignore[attr-defined]
        states.set(_TTL_FINGERPRINT_KEY, fingerprint)
        return {"updated": updated, "skipped": 0}

    def _fill_stix_ids(self) -> None:
        """Baris dari kode lama (rollback) lahir tanpa `stix_id`; diisi di langkah tetap."""
        rows = self.session.execute(
            text("SELECT id, type, value FROM indicators WHERE stix_id IS NULL")
        ).all()
        if rows:
            self.session.execute(
                text("UPDATE indicators SET stix_id = :s WHERE id = :i"),
                [{"s": indicator_uuid(r.type, r.value), "i": r.id} for r in rows],
            )

    def get(self, *, type: str, value: str) -> Indicator | None:
        return self.session.execute(
            select(Indicator).where(Indicator.type == type, Indicator.value == value)
        ).scalar_one_or_none()


class AsyncIndicatorRepo:
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
        suppression_reason: str | None = None,
        tlp: str = "clear",
        pap: str = "clear",
    ) -> Indicator:
        result = await self.session.execute(
            select(Indicator).where(Indicator.type == type, Indicator.value == value)
        )
        existing = result.scalar_one_or_none()
        indicator = _apply_upsert(
            self.session,
            existing,
            type=type,
            value=value,
            source_url=source_url,
            source_name=source_name,
            context=context,
            article_id=article_id,
            suppression_reason=suppression_reason,
            tlp=tlp,
            pap=pap,
        )
        await self.session.flush()
        return indicator

    async def add_feedback(
        self, indicator: Indicator, *, verdict: str, submitted_by: str, note: str | None = None
    ) -> Indicator:
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"verdict '{verdict}' harus salah satu dari {_VALID_VERDICTS}")
        indicator.feedback.append(
            IndicatorFeedback(verdict=verdict, submitted_by=submitted_by, note=note)
        )
        _apply_verdict(indicator, verdict, submitted_by)
        await self.session.flush()
        return indicator

    async def set_marking(
        self, indicator: Indicator, *, tlp: str | None, pap: str | None
    ) -> Indicator:
        """Atur marking manual oleh analis (boleh menurunkan, berbeda dari ingest); None = tetap."""
        if tlp is not None:
            indicator.tlp = tlp
        if pap is not None:
            indicator.pap = pap
        await self.session.flush()
        return indicator

    async def apply_confidence_and_actionability(
        self,
        indicator: Indicator,
        *,
        confidence_score: int,
        actionability_score: int,
        actionability_label: str,
        recommended_action: str,
        decayed_at: datetime.datetime,
    ) -> Indicator:
        """Port bagian akhir `ioc_service.submit_feedback()` (Fase 7.4 Grup
        D) -- recompute confidence+actionability abis feedback baru masuk."""
        indicator.confidence_score = confidence_score
        indicator.confidence_decayed_at = decayed_at
        indicator.actionability_score = actionability_score
        indicator.actionability_label = actionability_label
        indicator.recommended_action = recommended_action
        await self.session.flush()
        return indicator

    async def get(self, *, type: str, value: str) -> Indicator | None:
        result = await self.session.execute(
            select(Indicator).where(Indicator.type == type, Indicator.value == value)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, indicator_id: int) -> Indicator | None:
        result = await self.session.execute(select(Indicator).where(Indicator.id == indicator_id))
        return result.scalar_one_or_none()

    async def list_by_ids(self, indicator_ids: Sequence[int]) -> list[Indicator]:
        """Batch get -- port `_ioc_confidence_factor()`'s `$in` lookup
        (`campaign_scoring_service.py`, Fase 7.4 Grup A)."""
        if not indicator_ids:
            return []
        result = await self.session.execute(
            select(Indicator).where(Indicator.id.in_(indicator_ids))
        )
        return list(result.scalars().all())

    async def list_first_seen_on(self, day: datetime.date, *, limit: int = 200) -> list[Indicator]:
        """Port `_collect_iocs()` (`recap_service.py`, Fase 7.3 router
        `recap`, Bagian 5) -- IOC yang PERTAMA ketemu tanggal ini."""
        result = await self.session.execute(
            select(Indicator)
            .where(func.date(Indicator.first_seen_at) == day, Indicator.usable)
            .order_by(Indicator.first_seen_at)
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
            select(Indicator.type, func.count())
            .where(
                func.date(Indicator.first_seen_at).between(start, end),
                Indicator.usable,
            )
            .group_by(Indicator.type)
        )
        return {ioc_type: n for ioc_type, n in result.all()}

    async def list_needing_decay(
        self, cutoff: datetime.datetime, *, limit: int = 500
    ) -> list[Indicator]:
        """Port query `decay_sweep()` (`ioc_service.py` lama) -- IOC yang
        confidence-nya belum PERNAH dihitung ulang (`confidence_decayed_at`
        NULL) ATAU udah lebih lama dari `cutoff` (24 jam lalu, port apa
        adanya). `limit` -- Celery task (`ioc_decay`, Fase 7.8) manggil ini
        berulang tiap sweep sampai kosong, bukan sekali angkut semua (dataset
        bisa gede, satu UPDATE per-IOC lewat ORM -- lihat docstring
        `ioc_decay.decay_sweep`)."""
        result = await self.session.execute(
            select(Indicator)
            .where(
                or_(
                    Indicator.confidence_decayed_at.is_(None),
                    Indicator.confidence_decayed_at < cutoff,
                )
            )
            .order_by(Indicator.id)
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
    ) -> list[Indicator]:
        """IOC bertipe `types` (bukan yang `auto_suppressed` atau dicabut) yang BELUM punya kartu
        `provider` di `enrichment.providers`, atau yang kartunya dicek sebelum `checked_before`.
        Terbaru dilihat dulu (`last_seen_at`), supaya jatah provider dipakai untuk IOC yang paling
        relevan.

        Kartu dicari lewat `jsonb_array_elements`: `enrichment` kosong (`{}`) tidak punya
        `providers`, jadi `COALESCE` ke array kosong dan IOC-nya terhitung belum dicek."""
        fresh_card = text(
            "NOT EXISTS (SELECT 1 FROM jsonb_array_elements("
            "COALESCE(indicators.enrichment -> 'providers', '[]'::jsonb)) AS card "
            "WHERE card ->> 'key' = :provider "
            "AND (card ->> 'checked_at')::timestamptz > :checked_before)"
        ).bindparams(
            bindparam("provider", provider),
            bindparam("checked_before", checked_before, type_=DateTime(timezone=True)),
        )
        stmt = (
            select(Indicator)
            .where(Indicator.type.in_(types), Indicator.usable, fresh_card)
            .order_by(Indicator.last_seen_at.desc(), Indicator.id)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def set_enrichment_provider(
        self, indicator: Indicator, card: dict[str, Any], *, now: datetime.datetime
    ) -> None:
        """Tulis kartu SATU provider ke `enrichment.providers` (mengganti kartu `key` yang sama,
        kartu provider lain tidak disentuh) dan perbarui `updated_at`. Kolom JSONB diganti dengan
        dict BARU, bukan dimutasi di tempat, supaya perubahannya terdeteksi."""
        current = dict(indicator.enrichment or {})
        cards = [c for c in current.get("providers", []) if c.get("key") != card["key"]]
        cards.append(card)
        cards.sort(key=lambda c: str(c.get("key", "")))
        current["providers"] = cards
        current["updated_at"] = now.strftime("%Y-%m-%d %H:%M UTC")
        indicator.enrichment = current
        await self.session.flush()

    def _filtered_stmt(
        self,
        *,
        ioc_type: str | None,
        search: str | None,
        tags: Sequence[str] | None,
        actionability: str | None,
        include_suppressed: bool,
        state: str | None,
        include_revoked: bool,
    ) -> Select[tuple[Indicator]]:
        """Hanya filter (tanpa order/paging), dipakai bersama oleh `list_filtered` dan
        `iter_export` supaya export IOC selalu memakai aturan filter yang sama dengan daftar."""
        stmt = select(Indicator)
        if state:
            # state menggantikan include_suppressed: allowlisted justru butuh baris tersembunyi
            stmt = stmt.where(Indicator.state == state)
        elif not include_suppressed:
            # IOC `auto_suppressed` (cocok allowlist) disembunyikan kecuali diminta eksplisit.
            stmt = stmt.where(Indicator.auto_suppressed.is_(False))
        if not include_revoked:
            stmt = stmt.where(Indicator.revoked_at.is_(None))
        if ioc_type and ioc_type in _VALID_TYPES:
            stmt = stmt.where(Indicator.type == ioc_type)
        if search:
            stmt = stmt.where(Indicator.value.ilike(f"%{search}%"))
        if tags:
            stmt = stmt.join(Indicator.tags).where(IndicatorTag.tag.in_(tags)).distinct()
        if actionability:
            stmt = stmt.where(Indicator.actionability_label == actionability)
        return stmt

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
        include_suppressed: bool = False,
        state: str | None = None,
        include_revoked: bool = True,
    ) -> tuple[list[Indicator], int]:
        """Port `ioc_service.get_iocs()`. `actionability` (filter lama)
        gak diport pas Fase 7.3 -- waktu itu kolomnya emang belum ada.
        Fase 7.4 Grup D nambahin `actionability_label` ke skema (lihat
        `IOC.actionability_label`), jadi filter ini SEKARANG bisa
        diwire -- ditambahin di sini pas Grup G4 (`/intelligence/
        ioc-management`) baru butuh beneran dari frontend."""
        stmt = self._filtered_stmt(
            ioc_type=ioc_type,
            search=search,
            tags=tags,
            actionability=actionability,
            include_suppressed=include_suppressed,
            state=state,
            include_revoked=include_revoked,
        )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        order_col = (
            Indicator.confidence_score if sort_by == "confidence" else Indicator.last_seen_at
        )
        # `id` sebagai tie-breaker: `last_seen_at`/skor sering kembar, tanpa ini halaman offset
        # bisa menduplikasi atau melewatkan baris.
        list_stmt = (
            stmt.order_by(order_col.desc(), Indicator.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().unique().all()), total

    async def iter_export(
        self,
        *,
        sort_by: str | None,
        batch_size: int | None = None,
        limit: int,
        ioc_type: str | None = None,
        search: str | None = None,
        tags: Sequence[str] | None = None,
        actionability: str | None = None,
        include_suppressed: bool = False,
        state: str | None = None,
        include_revoked: bool = True,
    ) -> AsyncIterator[list[Indicator]]:
        """Batch IOC untuk export CSV, maksimal `limit` baris, urutan sama dengan `list_filtered`.

        Keyset `(kolom sort, id)` menurun, bukan offset: offset pada puluhan ribu baris membaca
        ulang semua baris sebelumnya di tiap batch, dan baris yang masuk/berubah di tengah export
        menggeser halaman (duplikat/terlewat). Kunci gabungan dengan `id` membuat baris yang
        kembar di kolom sort tetap terurut total, jadi tidak ada yang hilang di batas batch."""
        size = batch_size or _EXPORT_BATCH
        order_col = (
            Indicator.confidence_score if sort_by == "confidence" else Indicator.last_seen_at
        )
        base = self._filtered_stmt(
            ioc_type=ioc_type,
            search=search,
            tags=tags,
            actionability=actionability,
            include_suppressed=include_suppressed,
            state=state,
            include_revoked=include_revoked,
        ).options(
            # baris CSV hanya membaca tags + mentions (aktor); riwayat sumber dan feedback
            # (selectin bawaan model) bisa puluhan kali lipat jumlah IOC, jadi jangan dimuat
            noload(Indicator.sources),
            noload(Indicator.feedback),
        )
        remaining = limit
        last: tuple[Any, ...] | None = None
        while remaining > 0:
            want = min(size, remaining)
            stmt = base
            if last is not None:
                stmt = stmt.where(tuple_(order_col, Indicator.id) < tuple_(*last))
            stmt = stmt.order_by(order_col.desc(), Indicator.id.desc()).limit(want)
            batch = list((await self.session.execute(stmt)).scalars().unique().all())
            if not batch:
                return
            yield batch
            remaining -= len(batch)
            if len(batch) < want:  # batch tidak penuh = data habis
                return
            tail = batch[-1]
            last = (getattr(tail, order_col.key), tail.id)

    async def list_with_feedback(self) -> list[Indicator]:
        """IOC yang punya minimal satu feedback (tp/fp) -- port filter
        `{"feedback_log": {"$exists": True, "$ne": []}}`
        (`fp_analytics_service.get_fp_analytics()`, Fase 7.4 Grup D)."""
        result = await self.session.execute(select(Indicator).where(Indicator.feedback.any()))
        return list(result.scalars().all())

    async def list_by_article_ids(self, article_ids: Sequence[int]) -> list[Indicator]:
        """IOC yang nyantol ke salah satu `article_ids` lewat `IOCSource` -- port
        `cluster_service.py`'s `ioc_map` building (Fase 7.4 Grup A,
        `get_recent_campaigns()`). CVE tidak termasuk: relasinya ada di mention CVE artikel
        (`AsyncArticleCveRepo.cve_ids_by_article`)."""
        if not article_ids:
            return []
        result = await self.session.execute(
            select(Indicator)
            .join(Indicator.sources)
            .where(IndicatorSource.article_id.in_(article_ids), Indicator.usable)
            .distinct()
        )
        return list(result.scalars().unique().all())

    async def get_stats(self) -> dict[str, object]:
        total = (
            await self.session.execute(
                select(func.count()).select_from(Indicator).where(Indicator.usable)
            )
        ).scalar_one()
        by_type_stmt = (
            select(Indicator.type, func.count())
            .where(Indicator.usable)
            .group_by(Indicator.type)
            .order_by(func.count().desc(), Indicator.type)  # tie-break: urutan deterministik
        )
        by_type = (await self.session.execute(by_type_stmt)).all()
        return {
            "total": total,
            "by_type": [{"type": t, "count": c} for t, c in by_type],
        }

    async def add_tags(self, indicator: Indicator, tags: Sequence[str]) -> Indicator:
        existing = {t.tag for t in indicator.tags}
        for tag in tags:
            if tag not in existing:
                indicator.tags.append(IndicatorTag(tag=tag))
                existing.add(tag)
        await self.session.flush()
        return indicator

    async def add_threat_actors(
        self, indicator: Indicator, threat_actors: Sequence[str]
    ) -> Indicator:
        """Tag aktor oleh analis = mention `intrusion-set` (method `analyst`) di indikator, lewat
        resolver (P7c Task 8); alias aktor yang sudah ada menempel ke entitas yang sama, nama
        suppressed/kosong dibuang, idempoten."""
        await self.session.flush()
        hits = [
            MentionInput("intrusion-set", a, "analyst", a) for a in dict.fromkeys(threat_actors)
        ]
        rows = mention_rows(
            {"indicator_id": indicator.id},
            await resolve_all_async(self.session, hits),
        )
        if rows:
            await self.session.execute(insert_mentions(rows, update=False))
        await self._reload_actors(indicator)
        return indicator

    async def remove_threat_actor(self, indicator: Indicator, actor: str) -> bool:
        """Hapus mention aktor yang namanya (nama entitas, seperti yang ditampilkan) = `actor`."""
        actor_ids = select(Entity.id).where(Entity.type == "intrusion-set", Entity.name == actor)
        result = await self.session.execute(
            delete(EntityMention)
            .where(
                EntityMention.indicator_id == indicator.id,
                EntityMention.entity_id.in_(actor_ids),
            )
            .returning(EntityMention.id)
            .execution_options(synchronize_session=False)
        )
        removed = bool(result.all())
        await self._reload_actors(indicator)
        return removed

    async def _reload_actors(self, indicator: Indicator) -> None:
        await self.session.flush()
        await self.session.refresh(indicator, attribute_names=["mentions"])

    async def delete(self, indicator_id: int) -> bool:
        indicator = await self.get_by_id(indicator_id)
        if indicator is None:
            return False
        await self.session.delete(indicator)
        await self.session.flush()
        return True

    async def bulk_delete(self, indicator_ids: Sequence[int]) -> int:
        count = 0
        for indicator_id in indicator_ids:
            if await self.delete(indicator_id):
                count += 1
        return count
