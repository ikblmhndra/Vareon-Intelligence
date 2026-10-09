"""`CveTrackerRepo` -- satu-satunya jalur tulis `cve_tracker` (+ tabel anak
`cve_references`/`cve_affected`/`cve_pocs`). Gantiin dua penulis terpisah
di sistem lama (`newCveThreat.py` upsert penuh per-client, `githubPOCMonitor.py`
push POC ke array) -- di sini `upsert()` buat yang pertama, `add_pocs()`
buat yang kedua, dua-duanya lewat repo yang sama biar gak drift lagi.

`AsyncCveTrackerRepo`/`AsyncCveFalsePositiveRepo` (Fase 7.3, router `cve.py`)
BARU -- permukaan BACA + false-positive doang, satu-satunya jalur TULIS CVE
baru tetap `CveTrackerRepo` sync di atas (Celery task, Fase 4).

**`AsyncCveTicketRepo`** (Fase 7.4 Grup C, 2026-09-23) -- jalur baca/tulis
`cve_tickets`, satu record remediation per (cve_id, client_id) -- lihat
docstring `CveTicket` (`db/models/cve.py`) soal kenapa bentuknya flat,
bukan "ticket nyakup banyak CVE" kayak placeholder Fase 2. `ack_filter`
(parameter `list_filtered()`/`get_stats()` di bawah) sekarang jalan lagi,
subquery lawan `cve_tickets.acknowledged_by`."""

from __future__ import annotations

import datetime
import re
import zoneinfo
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from cti_core.db.models.article import Article
from cti_core.db.models.cve import (
    CveAffected,
    CveFalsePositive,
    CveNewsletterMention,
    CvePoc,
    CveReference,
    CveThreatActor,
    CveTicket,
    CveTracker,
    CveTTP,
)

_TICKET_TZ = zoneinfo.ZoneInfo("Asia/Jakarta")
"""Zona nomor ticket -- sama dengan dashboard dan export (hari/bulan yang dilihat analis)."""

_TICKET_ID_LOCK = 7_241_001
"""Kunci `pg_advisory_xact_lock` yang menserialkan pembuatan nomor ticket (lihat
`AsyncCveTicketRepo.get_next_ticket_id`)."""


def _date_column(basis: str) -> Any:
    """Kolom tanggal yang difilter From/To. "published" = tanggal terbit CVE (kolom Published di
    tabel); "detected" = hari kalender WIB saat scraper pertama menemukannya (sama dengan dashboard
    dan export, bukan tanggal UTC)."""
    if basis == "detected":
        return func.date(func.timezone(_TICKET_TZ.key, CveTracker.detected_on))
    return CveTracker.published


_SORT_FIELDS = {
    "tech": CveTracker.tech,
    "severity": CveTracker.cve_score,
    "published": CveTracker.published,
    "epss": CveTracker.epss_score,
}
"""`epss` (sort key lama) sekarang kepetakan -- kolom `epss_score` udah
ada (Grup B survei 7.4, `POST /epss-lookup`). Key gak dikenal tetap
fallback ke `published`, port apa adanya."""


class CveTrackerRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        cve_id: str,
        client_id: str,
        references: Sequence[str] = (),
        affected: Sequence[str] = (),
        **fields: Any,
    ) -> CveTracker:
        """Lihat `upsert_with_status` (sama, tanpa penanda baru/update)."""
        row, _created = self.upsert_with_status(
            cve_id=cve_id, client_id=client_id, references=references, affected=affected, **fields
        )
        return row

    def upsert_with_status(
        self,
        *,
        cve_id: str,
        client_id: str,
        references: Sequence[str] = (),
        affected: Sequence[str] = (),
        **fields: Any,
    ) -> tuple[CveTracker, bool]:
        """`(baris, dibuat)` -- `dibuat` True hanya kalau INSERT (CVE baru buat client ini);
        dipakai sink buat notifikasi CVE baru (`cti_scraper.cve_alert`).

        `references`/`affected` SELALU diganti utuh (bukan di-merge) --
        MITRE ngasih daftar lengkap tiap kali, bukan delta. Relationship-nya
        `cascade="all, delete-orphan"` (lihat model), jadi assign list baru
        otomatis buang baris anak yang lama."""
        existing = self.session.execute(
            select(CveTracker).where(CveTracker.cve_id == cve_id, CveTracker.client_id == client_id)
        ).scalar_one_or_none()

        if existing is None:
            row = CveTracker(cve_id=cve_id, client_id=client_id, **fields)
            row.references = [CveReference(url=u) for u in references]
            row.affected = [CveAffected(affected=a) for a in affected]
            self.session.add(row)
            self.session.flush()
            return row, True

        for k, v in fields.items():
            setattr(existing, k, v)
        existing.references = [CveReference(url=u) for u in references]
        existing.affected = [CveAffected(affected=a) for a in affected]
        self.session.flush()
        return existing, False

    def add_pocs(self, *, cve_id: str, pocs: list[dict[str, str]]) -> int:
        """Nambahin POC baru ke SEMUA baris `cve_tracker` yang `cve_id`-nya
        cocok -- satu CVE bisa dipantau lebih dari satu client, masing-masing
        baris sendiri (lihat unique constraint `(cve_id, client_id)`).
        Skip URL yang udah tercatat (setara `existing_poc_urls` di
        `githubPOCMonitor.py` lama). Balikin jumlah baris yang KE-UPDATE
        (bukan jumlah POC)."""
        rows = (
            self.session.execute(select(CveTracker).where(CveTracker.cve_id == cve_id))
            .scalars()
            .all()
        )

        updated = 0
        for row in rows:
            existing_urls = {p.url for p in row.pocs}
            new_pocs = [p for p in pocs if p["url"] not in existing_urls]
            if not new_pocs:
                continue
            row.pocs.extend(
                CvePoc(url=p["url"], source=p.get("source"), poc_type=p.get("poc_type"))
                for p in new_pocs
            )
            row.poc_available = True
            updated += 1

        self.session.flush()
        return updated


def _apply_filters(
    stmt: Select[tuple[CveTracker]],
    *,
    client_id: str,
    tech: Sequence[str] | None,
    severity: Sequence[str] | None,
    search: str | None,
    date_start: datetime.date | None,
    date_end: datetime.date | None,
    exclude_cve_ids: Sequence[str] | None,
    ack_filter: str | None = None,
    date_basis: str = "published",
) -> Select[tuple[CveTracker]]:
    stmt = stmt.where(CveTracker.client_id == client_id)
    if exclude_cve_ids:
        stmt = stmt.where(CveTracker.cve_id.notin_(exclude_cve_ids))
    if tech is not None:
        stmt = stmt.where(CveTracker.tech.in_(tech))
    if severity:
        stmt = stmt.where(CveTracker.cve_severity.in_([s.upper() for s in severity]))
    if search:
        stmt = stmt.where(
            or_(
                CveTracker.cve_id.ilike(f"%{search}%"),
                CveTracker.summary.ilike(f"%{search}%"),
                CveTracker.tech.ilike(f"%{search}%"),
            )
        )
    date_column = _date_column(date_basis)
    if date_start is not None:
        stmt = stmt.where(date_column >= date_start)
    if date_end is not None:
        stmt = stmt.where(date_column <= date_end)
    if ack_filter in ("acked", "unacked"):
        acked_subq = select(CveTicket.cve_id).where(
            CveTicket.client_id == client_id, CveTicket.acknowledged_by.is_not(None)
        )
        if ack_filter == "acked":
            stmt = stmt.where(CveTracker.cve_id.in_(acked_subq))
        else:
            stmt = stmt.where(CveTracker.cve_id.notin_(acked_subq))
    return stmt


class AsyncCveFalsePositiveRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_cve_ids(self, client_id: str) -> list[str]:
        result = await self.session.execute(
            select(CveFalsePositive.cve_id).where(CveFalsePositive.client_id == client_id)
        )
        return list(result.scalars().all())

    async def list_all_cve_ids(self) -> list[str]:
        """Lintas client, TANPA filter -- port apa adanya dari
        `cross_reference_service.py` (`db[FP_COLLECTION].distinct("cve_id")`,
        gak pernah nge-scope client). Dipakai `crossref` (Bagian 3) doang,
        endpoint FP utama (`cve.py`) tetap per-client via `list_cve_ids`."""
        result = await self.session.execute(select(CveFalsePositive.cve_id).distinct())
        return list(result.scalars().all())

    async def mark(self, cve_id: str, client_id: str, marked_by: str | None = None) -> None:
        existing = await self.session.execute(
            select(CveFalsePositive).where(
                CveFalsePositive.cve_id == cve_id, CveFalsePositive.client_id == client_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            return
        self.session.add(CveFalsePositive(cve_id=cve_id, client_id=client_id, marked_by=marked_by))
        await self.session.flush()

    async def unmark(self, cve_id: str, client_id: str) -> None:
        result = await self.session.execute(
            select(CveFalsePositive).where(
                CveFalsePositive.cve_id == cve_id, CveFalsePositive.client_id == client_id
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()

    async def bulk_mark(
        self, cve_ids: Sequence[str], client_id: str, marked_by: str | None = None
    ) -> int:
        existing = set(await self.list_cve_ids(client_id))
        to_add = [cid for cid in cve_ids if cid not in existing]
        for cid in to_add:
            self.session.add(CveFalsePositive(cve_id=cid, client_id=client_id, marked_by=marked_by))
        await self.session.flush()
        return len(to_add)


class AsyncCveTrackerRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all_distinct_cve_ids(self) -> list[str]:
        """Lintas client, TANPA filter -- semua cve_id yang lagi ditrack, termasuk yang
        ditandai FP. Buat "true positive" pakai `list_true_positive_cve_ids`."""
        result = await self.session.execute(select(CveTracker.cve_id).distinct())
        return list(result.scalars().all())

    async def list_registered_on(
        self, day: datetime.date, *, exclude_cve_ids: Sequence[str], limit: int = 50
    ) -> list[CveTracker]:
        """Port `_collect_cves()` (`recap_service.py`, Fase 7.3 router
        `recap`, Bagian 5) -- CVE yang PERTAMA ke-track/kedetek/dipublish
        tanggal ini (OR tiga kolom tanggal, port apa adanya dari kode
        lama), lintas client (recap emang digest GLOBAL, bukan per-client).
        `exclude_cve_ids` global juga (bukan per-client) -- `recap` gak
        pernah nge-scope client sama sekali."""
        stmt = select(CveTracker).where(
            or_(
                func.date(CveTracker.registered_date) == day,
                func.date(CveTracker.detected_on) == day,
                CveTracker.published == day,
            )
        )
        if exclude_cve_ids:
            stmt = stmt.where(CveTracker.cve_id.not_in(exclude_cve_ids))
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_cve_id_any_client(self, cve_id: str) -> CveTracker | None:
        """Case-insensitive, lintas client, ambil SATU baris pertama yang
        cocok -- port apa adanya dari `cross_reference_service.get_cve_crossrefs()`
        (`find_one` tanpa client filter). Kalau CVE yang sama ke-track di
        lebih dari satu client, baris yang kepilih arbitrer (tergantung
        urutan default DB) -- sama ambiguitas kayak kode lama."""
        result = await self.session.execute(
            select(CveTracker).where(func.lower(CveTracker.cve_id) == cve_id.lower())
        )
        return result.scalars().first()

    async def add_newsletter_mention(
        self, cve_id: str, *, title: str, url: str, source: str, mention_date: str
    ) -> bool:
        """Port `cve_service.upsert_newsletter_mention()` -- `$push` dedup
        by url ke `cve_tracker.newsletter_mentions` (array Mongo) jadi
        insert ke tabel anak `cve_newsletter_mentions`, unique constraint
        (cve_tracker_id, url) yang jaga dedup-nya (bukan cek manual kayak
        `add_pocs`). Sama kayak `get_by_cve_id_any_client`, lintas client,
        ambil baris PERTAMA yang cocok -- kalau gak ketemu, no-op (return
        False), port apa adanya (`update_one` Mongo juga diam-diam no-op
        kalau filter gak match)."""
        cve = await self.get_by_cve_id_any_client(cve_id)
        if cve is None:
            return False
        existing_urls = {m.url for m in cve.newsletter_mentions}
        if url in existing_urls:
            return False
        cve.newsletter_mentions.append(
            CveNewsletterMention(title=title, url=url, source=source, mention_date=mention_date)
        )
        await self.session.flush()
        return True

    async def list_true_positive_cve_ids(self, client_id: str | None = None) -> list[str]:
        """CVE yang masih true positive: dipakai enrichment EPSS/KEV/exploit-db (`cve_lookup`)
        dan korelasi CVE di newsletter.

        `client_id=None` (default): CVE dianggap true positive selama ada SATU baris
        `cve_tracker` (client mana pun) yang tidak ditandai FP oleh clientnya sendiri. FP itu per
        `(cve_id, client_id)`, dan hasil lookup ditulis ke semua baris CVE-nya, jadi yang
        menentukan adalah apakah masih ada client yang membutuhkannya. Dulu: hanya FP client
        "default" yang dihitung (port `lookup_all_true_positives()` Mongo, yang memang tak peduli
        client), sehingga CVE yang FP di "default" tapi valid di client lain tak pernah di-enrich,
        dan sebaliknya.

        `client_id` eksplisit: perilaku lama -- semua CVE minus FP client itu."""
        if client_id is not None:
            all_ids = await self.list_all_distinct_cve_ids()
            fp_ids = set(await AsyncCveFalsePositiveRepo(self.session).list_cve_ids(client_id))
            return [cid for cid in all_ids if cid not in fp_ids]

        is_fp = (
            select(CveFalsePositive.id)
            .where(
                CveFalsePositive.cve_id == CveTracker.cve_id,
                CveFalsePositive.client_id == CveTracker.client_id,
            )
            .exists()
        )
        result = await self.session.execute(
            select(CveTracker.cve_id).where(~is_fp).distinct().order_by(CveTracker.cve_id)
        )
        return list(result.scalars().all())

    async def list_by_cve_ids_any_client(self, cve_ids: Sequence[str]) -> list[CveTracker]:
        """Semua baris (lintas client) buat sekumpulan cve_id, case-
        insensitive -- beda dari `get_by_cve_id_any_client` (satu baris
        pertama doang). Dipakai EPSS/CISA-KEV/exploit-db lookup yang
        niatnya `update_many` lintas SEMUA client sekaligus (properti
        CVE itu sendiri, bukan spesifik client) -- lihat docstring
        `cti_api.services.cve_lookup`."""
        if not cve_ids:
            return []
        upper_ids = {cid.upper() for cid in cve_ids}
        result = await self.session.execute(
            select(CveTracker).where(func.upper(CveTracker.cve_id).in_(upper_ids))
        )
        return list(result.scalars().all())

    async def apply_epss_scores(self, scores: dict[str, dict[str, Any]]) -> None:
        """`scores`: `{cve_id_upper: {epss, percentile, date}}`. Update
        SEMUA baris (lintas client) buat tiap cve_id -- port
        `save_epss_scores()` lama (`update_many` per cve_id)."""
        if not scores:
            return
        rows = await self.list_by_cve_ids_any_client(list(scores.keys()))
        now = datetime.datetime.now(datetime.UTC)
        for cve in rows:
            data = scores.get(cve.cve_id.upper())
            if data is None:
                continue
            cve.epss_score = data["epss"]
            cve.epss_percentile = data["percentile"]
            cve.epss_date = data["date"]
            cve.epss_checked_at = now
        await self.session.flush()

    async def apply_cisa_kev_hits(
        self, catalog: dict[str, dict[str, Any]], tp_cve_ids: Sequence[str]
    ) -> list[str]:
        """Cross-reference `tp_cve_ids` vs katalog KEV penuh, update SEMUA
        baris (lintas client) yang cocok -- port `lookup_all_true_
        positives()` lama. Balikin daftar cve_id yang match (buat summary
        `matched_cves`)."""
        matched = sorted({cid.upper() for cid in tp_cve_ids if cid.upper() in catalog})
        if not matched:
            return []
        rows = await self.list_by_cve_ids_any_client(matched)
        now = datetime.datetime.now(datetime.UTC)
        for cve in rows:
            vuln = catalog.get(cve.cve_id.upper())
            if vuln is None:
                continue
            cve.cisa_kev = True
            cve.active_exploitation = True
            cve.cisa_kev_checked_at = now
            cve.cisa_kev_detail = {
                "date_added": vuln.get("dateAdded", ""),
                "due_date": vuln.get("dueDate", ""),
                "vendor": vuln.get("vendorProject", ""),
                "product": vuln.get("product", ""),
                "name": vuln.get("vulnerabilityName", ""),
                "description": vuln.get("shortDescription", ""),
                "action": vuln.get("requiredAction", ""),
            }
        await self.session.flush()
        return matched

    async def apply_exploit_hits(self, cve_id: str, exploits: list[dict[str, Any]]) -> None:
        """Update SEMUA baris (lintas client) buat SATU cve_id -- port
        `save_exploit_hits()` lama. **Dedup POC per-baris** (cek existing
        URL PER client row) -- kode lama cek dedup dari SATU dokumen
        (`find_one`, ambil sembarang) lalu `$push` hasil yang sama ke
        SEMUA baris lewat `update_many`, jadi kalau ada >1 client nge-
        track CVE yang sama, baris client lain bisa kebagian POC
        duplikat (existing URL beda per baris tapi dedup-nya dihitung
        cuma dari satu baris). Di sini dedup dihitung ULANG per baris --
        koreksi kecil, bukan ubah niat (niatnya emang "jangan taro POC
        dobel", bukan "dedup dari baris tertentu")."""
        rows = await self.list_by_cve_ids_any_client([cve_id])
        now = datetime.datetime.now(datetime.UTC)
        for cve in rows:
            cve.exploit_db_checked_at = now
            cve.exploit_db_hits = exploits
            existing_urls = {p.url for p in cve.pocs}
            new_urls = {e["url"] for e in exploits} - existing_urls
            if new_urls:
                cve.poc_available = True
                for e in exploits:
                    if e["url"] in new_urls:
                        cve.pocs.append(
                            CvePoc(url=e["url"], source="exploit-db", poc_type="exploit")
                        )
                        new_urls.discard(
                            e["url"]
                        )  # port apa adanya: exploit-db bisa balikin URL kembar
        await self.session.flush()

    async def get_by_threat_actor_exact(
        self, actor_name: str, *, exclude_cve_ids: Sequence[str]
    ) -> list[CveTracker]:
        """Exact-match (case-insensitive) `threat_actors`, urut `cve_score`
        desc, limit 30 -- port `cross_reference_service.get_ta_crossrefs()`."""
        stmt = (
            select(CveTracker)
            .join(CveThreatActor)
            .where(func.lower(CveThreatActor.threat_actor) == actor_name.lower())
        )
        if exclude_cve_ids:
            stmt = stmt.where(CveTracker.cve_id.notin_(exclude_cve_ids))
        stmt = stmt.order_by(CveTracker.cve_score.desc().nulls_last()).limit(30)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def search_crossref(
        self,
        *,
        threat_actors: Sequence[str],
        ttp_ids: Sequence[str],
        tech_list: Sequence[str],
        exclude_cve_ids: Sequence[str],
    ) -> list[CveTracker]:
        """CVE yang overlap TA/TTP/industri PIR -- port
        `cross_reference_service.get_pir_crossrefs()`. Kosongin ketiga
        kriteria (`threat_actors`/`ttp_ids`/`tech_list`) -> gak ada OR
        clause -> query balik ke `cve_id NOT IN fp` doang (match-all),
        port perilaku sama persis `cve_conditions = []` -> `$or` gak
        keisi di kode lama."""
        conditions = []
        if threat_actors:
            lowered = [t.lower() for t in threat_actors]
            conditions.append(
                CveTracker.id.in_(
                    select(CveThreatActor.cve_tracker_id).where(
                        func.lower(CveThreatActor.threat_actor).in_(lowered)
                    )
                )
            )
        if ttp_ids:
            conditions.append(
                CveTracker.id.in_(select(CveTTP.cve_tracker_id).where(CveTTP.ttp_id.in_(ttp_ids)))
            )
        if tech_list:
            conditions.append(CveTracker.tech.in_(tech_list))

        stmt = select(CveTracker)
        if exclude_cve_ids:
            stmt = stmt.where(CveTracker.cve_id.notin_(exclude_cve_ids))
        if conditions:
            stmt = stmt.where(or_(*conditions))
        stmt = stmt.order_by(CveTracker.cve_score.desc().nulls_last()).limit(50)
        result = await self.session.execute(stmt)
        return list(result.scalars().unique().all())

    async def get_by_cve_ids(
        self, cve_ids: Sequence[str], *, client_id: str | None = None
    ) -> list[CveTracker]:
        """Lintas client, TANPA filter `client_id` kecuali diisi -- port apa adanya dari
        `cross_reference_service.py`/`ta_profile_service.py` lama
        (`cve_col.find({"cve_id": {"$in": ...}})`, gak pernah nge-scope
        client). Dipakai `crossref`/`ta_groups` (Bagian 3), bukan
        endpoint CVE utama yang emang per-client. Kalau CVE yang sama ada
        di lebih dari satu client, caller yang mutusin gimana nanganin
        duplikat -- sama ambiguitas yang ada di kode lama, bukan
        diselesaikan diam-diam di sini."""
        if not cve_ids:
            return []
        stmt = select(CveTracker).where(CveTracker.cve_id.in_(cve_ids))
        if client_id is not None:
            stmt = stmt.where(CveTracker.client_id == client_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_filtered(
        self,
        *,
        client_id: str,
        page: int = 1,
        page_size: int = 20,
        tech: Sequence[str] | None = None,
        severity: Sequence[str] | None = None,
        search: str | None = None,
        date_start: datetime.date | None = None,
        date_end: datetime.date | None = None,
        exclude_cve_ids: Sequence[str] | None = None,
        sort_by: str = "published",
        sort_dir: str = "desc",
        ack_filter: str | None = None,
        date_basis: str = "published",
    ) -> tuple[list[CveTracker], int]:
        base = _apply_filters(
            select(CveTracker),
            client_id=client_id,
            tech=tech,
            severity=severity,
            search=search,
            date_start=date_start,
            date_end=date_end,
            exclude_cve_ids=exclude_cve_ids,
            ack_filter=ack_filter,
            date_basis=date_basis,
        )
        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()

        order_col = _SORT_FIELDS.get(sort_by, CveTracker.published)
        order = order_col.desc() if sort_dir == "desc" else order_col.asc()
        # `CveTracker.id` = tie-breaker: tanpa ini baris ber-nilai sama (mis. published) bisa
        # muncul di dua halaman dan sebagian lain tidak pernah muncul.
        list_stmt = (
            base.order_by(order.nulls_last(), CveTracker.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def get_stats(
        self,
        *,
        client_id: str,
        tech: Sequence[str] | None = None,
        severity: Sequence[str] | None = None,
        search: str | None = None,
        date_start: datetime.date | None = None,
        date_end: datetime.date | None = None,
        exclude_cve_ids: Sequence[str] | None = None,
        ack_filter: str | None = None,
        date_basis: str = "published",
    ) -> dict[str, int]:
        """`severity` SENGAJA cuma dipakai buat query `total` -- port perilaku
        lama: bucket critical/high/medium/low tetap ngitung SEMUA severity
        biar tetap bermakna dibandingin (filter severity bikin bucket lain
        selalu 0, gak ada gunanya). `unrated` (tanpa skor CVSS) mengikuti bucket,
        bukan `total`."""
        base_no_severity = _apply_filters(
            select(CveTracker),
            client_id=client_id,
            tech=tech,
            severity=None,
            search=search,
            date_start=date_start,
            date_end=date_end,
            exclude_cve_ids=exclude_cve_ids,
            ack_filter=ack_filter,
            date_basis=date_basis,
        )
        base_with_severity = _apply_filters(
            select(CveTracker),
            client_id=client_id,
            tech=tech,
            severity=severity,
            search=search,
            date_start=date_start,
            date_end=date_end,
            exclude_cve_ids=exclude_cve_ids,
            ack_filter=ack_filter,
            date_basis=date_basis,
        )

        async def _count(stmt: Select[tuple[CveTracker]]) -> int:
            result = await self.session.execute(select(func.count()).select_from(stmt.subquery()))
            return result.scalar_one()

        total = await _count(base_with_severity)
        critical = await _count(base_no_severity.where(CveTracker.cve_score >= 9.0))
        high = await _count(
            base_no_severity.where(CveTracker.cve_score >= 7.0, CveTracker.cve_score < 9.0)
        )
        medium = await _count(
            base_no_severity.where(CveTracker.cve_score >= 4.0, CveTracker.cve_score < 7.0)
        )
        low = await _count(
            base_no_severity.where(CveTracker.cve_score > 0, CveTracker.cve_score < 4.0)
        )
        # Skor 0.0 (CNA tidak mengisi CVSS) dan NULL (baris lama) tidak masuk bucket mana pun di
        # atas; tanpa ini kartu critical..low tidak akan pernah menjumlah ke `total`.
        unrated = await _count(
            base_no_severity.where(or_(CveTracker.cve_score.is_(None), CveTracker.cve_score <= 0))
        )
        return {
            "total": total,
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "unrated": unrated,
        }

    async def list_dashboard_rows(
        self,
        *,
        client_id: str,
        detected_from: datetime.datetime,
        detected_to: datetime.datetime,
        tech: Sequence[str] | None = None,
        exclude_cve_ids: Sequence[str] | None = None,
    ) -> list[Row[Any]]:
        """Bahan dashboard CVE Tracker: satu baris per CVE (`detected_on` dalam
        `[detected_from, detected_to)`) + ticket-nya kalau ada (outer join --
        CVE yang belum disentuh analis tetap kehitung, itu angka "untriaged").

        Kolom dipilih eksplisit, BUKAN `select(CveTracker)`: relasi model ini
        `lazy="selectin"` (6 query anak per halaman hasil), padahal dashboard
        cuma butuh beberapa kolom skalar. Scope `client_id`/`tech`/`exclude_cve_ids`
        sama dengan `_apply_filters()` (list + stats), supaya total di dashboard
        = total di tab CVEs."""
        stmt = (
            select(
                CveTracker.cve_id,
                CveTracker.cve_severity,
                CveTracker.cve_score,
                CveTracker.tech,
                CveTracker.published,
                CveTracker.detected_on,
                CveTracker.solutions,
                CveTicket.ticket_id,
                CveTicket.owner_team,
                CveTicket.remediation_status,
                CveTicket.risk_acceptance,
                CveTicket.acknowledge_time,
                CveTicket.actual_remediation_date,
            )
            .outerjoin(
                CveTicket,
                (CveTicket.cve_id == CveTracker.cve_id)
                & (CveTicket.client_id == CveTracker.client_id),
            )
            .where(
                CveTracker.client_id == client_id,
                CveTracker.detected_on >= detected_from,
                CveTracker.detected_on < detected_to,
            )
        )
        if exclude_cve_ids:
            stmt = stmt.where(CveTracker.cve_id.notin_(exclude_cve_ids))
        if tech is not None:
            stmt = stmt.where(CveTracker.tech.in_(tech))
        result = await self.session.execute(stmt.order_by(CveTracker.detected_on.asc()))
        return list(result.all())

    async def list_detected_years(
        self,
        *,
        client_id: str,
        timezone: str,
        tech: Sequence[str] | None = None,
        exclude_cve_ids: Sequence[str] | None = None,
    ) -> list[int]:
        """Tahun-tahun yang punya CVE (`detected_on` dibaca di zona `timezone`,
        supaya CVE jam 01.00 WIB 1 Januari gak lari ke tahun lalu), terbaru dulu.
        Buat pilihan tahun di dashboard."""
        year = func.extract("year", func.timezone(timezone, CveTracker.detected_on))
        stmt = select(year).where(CveTracker.client_id == client_id).distinct()
        if exclude_cve_ids:
            stmt = stmt.where(CveTracker.cve_id.notin_(exclude_cve_ids))
        if tech is not None:
            stmt = stmt.where(CveTracker.tech.in_(tech))
        result = await self.session.execute(stmt)
        return sorted((int(y) for y in result.scalars().all()), reverse=True)

    async def list_for_export(
        self,
        *,
        client_id: str,
        tech: Sequence[str] | None = None,
        severity: Sequence[str] | None = None,
        search: str | None = None,
        date_start: datetime.date | None = None,
        date_end: datetime.date | None = None,
        exclude_cve_ids: Sequence[str] | None = None,
        ack_filter: str | None = None,
        date_basis: str = "detected",
    ) -> list[CveTracker]:
        """Port `cve_export_service.export_cves_to_excel()`'s query --
        filter tanggal default ke `detected_on` (laporan bulanan), BUKAN `published` kayak
        `list_filtered()`/`get_stats()` di atas. Asimetri default ini UDAH ADA di legacy
        (`cve_export_service.py` filter `detected_on`, `cve_service.py` filter `published`);
        `date_basis` membuatnya eksplisit supaya UI bisa memakai dasar yang sama untuk list,
        stats, dan export. "detected" dibaca sebagai hari WIB (`_date_column`).
        Fallback-ke-`published` lama (buat dokumen Mongo tanpa `detected_on`) gak relevan lagi --
        `detected_on` NOT NULL di skema baru (`server_default=now()`),
        kasusnya struktural gak mungkin kejadian."""
        stmt = select(CveTracker).where(CveTracker.client_id == client_id)
        if exclude_cve_ids:
            stmt = stmt.where(CveTracker.cve_id.notin_(exclude_cve_ids))
        if tech is not None:
            stmt = stmt.where(CveTracker.tech.in_(tech))
        if severity:
            stmt = stmt.where(CveTracker.cve_severity.in_([s.upper() for s in severity]))
        if search:
            stmt = stmt.where(
                or_(
                    CveTracker.cve_id.ilike(f"%{search}%"),
                    CveTracker.summary.ilike(f"%{search}%"),
                    CveTracker.tech.ilike(f"%{search}%"),
                )
            )
        date_column = _date_column(date_basis)
        if date_start is not None:
            stmt = stmt.where(date_column >= date_start)
        if date_end is not None:
            stmt = stmt.where(date_column <= date_end)
        if ack_filter in ("acked", "unacked"):
            acked_subq = select(CveTicket.cve_id).where(
                CveTicket.client_id == client_id, CveTicket.acknowledged_by.is_not(None)
            )
            if ack_filter == "acked":
                stmt = stmt.where(CveTracker.cve_id.in_(acked_subq))
            else:
                stmt = stmt.where(CveTracker.cve_id.notin_(acked_subq))
        stmt = stmt.order_by(CveTracker.detected_on.asc(), CveTracker.cve_id.asc()).limit(50000)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_tech_list(self, client_id: str) -> list[str]:
        result = await self.session.execute(
            select(CveTracker.tech)
            .where(CveTracker.client_id == client_id, CveTracker.tech.is_not(None))
            .distinct()
            .order_by(CveTracker.tech)
        )
        return [t for t in result.scalars().all() if t]

    async def get_article_mentions(self, cve_ids: Sequence[str]) -> dict[str, list[dict[str, str]]]:
        """Port `get_article_mentions()` -- CVE ID nyebut di judul artikel
        mana aja. Query SATU kali (OR ilike per cve_id), bukan N query.

        `ilike` cuma penyaring kasar; kecocokan sebenarnya dicek per ID dengan batas angka,
        supaya `CVE-2026-1234` tidak ikut menghitung artikel `CVE-2026-12345`."""
        result: dict[str, list[dict[str, str]]] = {cid: [] for cid in cve_ids}
        if not cve_ids:
            return result
        patterns = {
            cid: re.compile(rf"(?<![0-9a-z]){re.escape(cid)}(?![0-9])", re.IGNORECASE)
            for cid in cve_ids
        }
        stmt = select(Article.title, Article.url).where(
            or_(*[Article.title.ilike(f"%{cid}%") for cid in cve_ids])
        )
        rows = (await self.session.execute(stmt)).all()
        for title, url in rows:
            for cid, pattern in patterns.items():
                if pattern.search(title):
                    result[cid].append({"title": title, "url": url})
        return result

    async def purge_orphaned(
        self, *, client_id: str, active_tech_names: Sequence[str], dry_run: bool = True
    ) -> dict[str, Any]:
        """Port `purge_orphaned_cves()`. `active_tech_names` kosong = SEMUA
        CVE client ini dianggap orphan (port perilaku lama persis --
        client tanpa tech stack sama sekali gak punya CVE yang "sah")."""
        stmt = select(CveTracker).where(CveTracker.client_id == client_id)
        if active_tech_names:
            stmt = stmt.where(CveTracker.tech.notin_(active_tech_names))
        rows = (await self.session.execute(stmt)).scalars().all()

        by_tech: dict[str, int] = {}
        cve_ids: list[str] = []
        for row in rows:
            t = row.tech or "(no tech)"
            by_tech[t] = by_tech.get(t, 0) + 1
            cve_ids.append(row.cve_id)

        if dry_run or not rows:
            return {
                "dry_run": True,
                "would_delete": len(cve_ids),
                "by_tech": by_tech,
                "cve_ids": cve_ids,
            }

        for row in rows:
            await self.session.delete(row)
        fp_stmt = select(CveFalsePositive).where(
            CveFalsePositive.client_id == client_id, CveFalsePositive.cve_id.in_(cve_ids)
        )
        for fp in (await self.session.execute(fp_stmt)).scalars().all():
            await self.session.delete(fp)
        await self.session.flush()
        return {"dry_run": False, "deleted": len(cve_ids), "by_tech": by_tech, "cve_ids": cve_ids}


class AsyncCveTicketRepo:
    """Port `cve_ticket_service.py`. Satu record `CveTicket` per
    (cve_id, client_id) -- lihat docstring model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, cve_id: str, client_id: str) -> CveTicket | None:
        result = await self.session.execute(
            select(CveTicket).where(CveTicket.cve_id == cve_id, CveTicket.client_id == client_id)
        )
        return result.scalar_one_or_none()

    async def get_by_cve_ids(self, cve_ids: Sequence[str], client_id: str) -> dict[str, CveTicket]:
        """`{cve_id: ticket}` -- batch fetch buat export Excel (Grup C),
        satu query bukan N."""
        if not cve_ids:
            return {}
        result = await self.session.execute(
            select(CveTicket).where(CveTicket.client_id == client_id, CveTicket.cve_id.in_(cve_ids))
        )
        return {t.cve_id: t for t in result.scalars().all()}

    async def tracking_id_for(self, cve_ids: Sequence[str], client_id: str) -> str | None:
        """Nomor ticket yang SUDAH ada untuk CVE-CVE ini (urut, dipisah koma), `None` kalau belum
        ada satu pun. Dipakai draft email supaya Tracking ID-nya nomor ticket sungguhan."""
        tickets = await self.get_by_cve_ids(cve_ids, client_id)
        return ", ".join(sorted({t.ticket_id for t in tickets.values()})) or None

    async def list_with_cve(
        self,
        client_id: str,
        *,
        search: str | None = None,
        status: str | None = None,
        exclude_cve_ids: Sequence[str] | None = None,
    ) -> list[tuple[CveTicket, CveTracker | None]]:
        """Semua ticket client ini + CVE-nya (outer join -- ticket bisa
        yatim kalau CVE-nya udah dipurge), terbaru dulu. Buat view
        "Ticketing" di CVE Tracker. `status="__none__"` = ticket tanpa
        `remediation_status`."""
        stmt = (
            select(CveTicket, CveTracker)
            .outerjoin(
                CveTracker,
                (CveTracker.cve_id == CveTicket.cve_id)
                & (CveTracker.client_id == CveTicket.client_id),
            )
            .where(CveTicket.client_id == client_id)
        )
        if exclude_cve_ids:
            stmt = stmt.where(CveTicket.cve_id.notin_(exclude_cve_ids))
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                or_(
                    CveTicket.ticket_id.ilike(like),
                    CveTicket.cve_id.ilike(like),
                    CveTicket.affected_asset.ilike(like),
                    CveTicket.asset_owner.ilike(like),
                    CveTicket.owner_team.ilike(like),
                )
            )
        if status == "__none__":
            stmt = stmt.where(
                or_(CveTicket.remediation_status.is_(None), CveTicket.remediation_status == "")
            )
        elif status:
            stmt = stmt.where(CveTicket.remediation_status == status)
        stmt = stmt.order_by(CveTicket.ticket_id.desc()).limit(5000)
        result = await self.session.execute(stmt)
        return [(t, c) for t, c in result.all()]

    async def _lock_ticket_numbering(self) -> None:
        """Advisory lock sampai transaksi selesai; boleh dipanggil berulang di transaksi yang
        sama."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _TICKET_ID_LOCK}
        )

    async def _get_for_create(self, cve_id: str, client_id: str) -> CveTicket | None:
        """`get()` untuk jalur yang akan membuat ticket kalau belum ada. Kalau belum ada, ambil
        lock penomoran LALU cek lagi: transaksi lain bisa saja membuat ticket yang sama selagi kita
        menunggu lock, dan menyisipkan baris `(cve_id, client_id)` kedua kena `IntegrityError`."""
        existing = await self.get(cve_id, client_id)
        if existing is not None:
            return existing
        await self._lock_ticket_numbering()
        return await self.get(cve_id, client_id)

    async def get_next_ticket_id(
        self, *, now: datetime.datetime | None = None, reserve: bool = False
    ) -> str:
        """`"CTI-{tahun}-{bulan:02d}-{urut:03d}"` -- scan GLOBAL lintas
        SEMUA client (legacy: query tanpa filter client_id sama sekali),
        port apa adanya (lihat docstring `CveTicket`). Urutan dari suffix
        numerik terbesar yang match prefix bulan ini + 1, bukan row
        count (gap dari ticket yang kehapus gak bikin nomor kepake
        ulang). Bulan dibaca di WIB.

        `reserve=True` WAJIB untuk jalur yang langsung menyimpan ticket: ambil advisory lock
        sampai transaksi selesai, supaya transaksi lain menunggu dan membaca max yang sudah
        ter-commit (tanpa ini dua request bersamaan dapat nomor sama dan satu kena
        `IntegrityError`). Jalur 'intip' (`/next-ticket-id`, draft email) tidak mengunci -- lock
        tidak boleh ditahan selama panggilan LLM."""
        if reserve:
            await self._lock_ticket_numbering()
        now = (now or datetime.datetime.now(datetime.UTC)).astimezone(_TICKET_TZ)
        prefix = f"CTI-{now.year}-{now.month:02d}-"
        result = await self.session.execute(
            select(CveTicket.ticket_id).where(CveTicket.ticket_id.like(f"{prefix}%"))
        )
        max_num = 0
        for ticket_id in result.scalars().all():
            try:
                num = int(ticket_id.rsplit("-", 1)[-1])
            except ValueError:
                continue
            max_num = max(max_num, num)
        return f"{prefix}{max_num + 1:03d}"

    async def upsert(
        self,
        *,
        cve_id: str,
        client_id: str,
        ticket_id: str | None = None,
        affected_asset: str | None = None,
        affected_version: str | None = None,
        fixed_version: str | None = None,
        asset_owner: str | None = None,
        owner_email: str | None = None,
        owner_team: str | None = None,
        active_exploitation: str | None = None,
        remediation_date_plan: datetime.date | None = None,
        remediation_status: str | None = None,
        actual_remediation_date: datetime.date | None = None,
        escalation_required: bool = False,
        comments: str | None = None,
        risk_acceptance: str | None = None,
        closure_date: datetime.date | None = None,
    ) -> CveTicket:
        """Port `upsert_ticket()` -- `PUT /{cve_id}/ticket`. `ticket_id`
        kosong/`None` -> pakai yang udah ada (record lama) atau generate
        baru -- BEDA kecil dari legacy (yang `$set` apa adanya termasuk
        string kosong dari form) SENGAJA: `ticket_id` UNIQUE di Postgres
        (gak ada analognya di Mongo schemaless), nyimpen blank buat >1
        ticket bakal nabrak constraint itu. `acknowledged_by`/
        `acknowledge_time` TETAP -- cuma `acknowledge()`/`bulk_acknowledge()`
        yang nyentuh dua field itu."""
        existing = await self._get_for_create(cve_id, client_id)
        existing_ticket_id = existing.ticket_id if existing else None
        resolved_ticket_id = (
            ticket_id or existing_ticket_id or await self.get_next_ticket_id(reserve=True)
        )

        if existing is None:
            ticket = CveTicket(cve_id=cve_id, client_id=client_id, ticket_id=resolved_ticket_id)
            self.session.add(ticket)
        else:
            ticket = existing
            ticket.ticket_id = resolved_ticket_id

        ticket.affected_asset = affected_asset
        ticket.affected_version = affected_version
        ticket.fixed_version = fixed_version
        ticket.asset_owner = asset_owner
        ticket.owner_email = owner_email
        ticket.owner_team = owner_team
        ticket.active_exploitation = active_exploitation
        ticket.remediation_date_plan = remediation_date_plan
        ticket.remediation_status = remediation_status
        ticket.actual_remediation_date = actual_remediation_date
        ticket.escalation_required = escalation_required
        ticket.comments = comments
        ticket.risk_acceptance = risk_acceptance
        ticket.closure_date = closure_date
        await self.session.flush()
        return ticket

    async def get_acked_cve_ids(self, client_id: str) -> list[str]:
        result = await self.session.execute(
            select(CveTicket.cve_id).where(
                CveTicket.client_id == client_id, CveTicket.acknowledged_by.is_not(None)
            )
        )
        return list(result.scalars().all())

    async def get_ack_statuses(self, client_id: str) -> dict[str, str]:
        result = await self.session.execute(
            select(CveTicket.cve_id, CveTicket.acknowledged_by).where(
                CveTicket.client_id == client_id, CveTicket.acknowledged_by.is_not(None)
            )
        )
        return {cve_id: acked_by for cve_id, acked_by in result.all() if acked_by}

    async def acknowledge(self, cve_id: str, client_id: str, analyst_name: str) -> CveTicket:
        """Ack pertama menang: ticket yang UDAH di-ack (`acknowledged_by` keisi) dikembalikan apa
        adanya, jadi nama, waktu ack, dan nomor ticket-nya tidak berubah -- sama dengan
        `bulk_acknowledge`. Dulu ack ulang menimpa ketiganya: user lain bisa mengambil alih ack
        analis lain, dan `acknowledge_time` (dasar MTTA di dashboard) ikut bergeser.

        Lock penomoran diambil SEBELUM ticket dibaca (bukan lewat `_get_for_create`, yang
        melewatinya kalau ticket sudah ada): dua ack bersamaan atas ticket yang sama-sama belum
        di-ack harus berurutan, supaya yang kedua melihat ack yang pertama dan tidak menimpanya."""
        await self._lock_ticket_numbering()
        existing = await self.get(cve_id, client_id)
        if existing is not None and existing.acknowledged_by:
            return existing
        ticket_id = (existing.ticket_id if existing else None) or await self.get_next_ticket_id(
            reserve=True
        )
        now = datetime.datetime.now(datetime.UTC)

        if existing is None:
            ticket = CveTicket(cve_id=cve_id, client_id=client_id, ticket_id=ticket_id)
            self.session.add(ticket)
        else:
            ticket = existing
            ticket.ticket_id = ticket_id
        ticket.acknowledged_by = analyst_name.strip()
        ticket.acknowledge_time = now
        await self.session.flush()
        return ticket

    async def bulk_acknowledge(
        self, cve_ids: Sequence[str], client_id: str, analyst_name: str
    ) -> int:
        """Port `bulk_acknowledge_cves()`. CVE yang UDAH acked (`acknowledged_by`
        keisi) di-skip, gak dobel-timpa waktu ack-nya. Flush TIAP iterasi
        (bukan sekali di akhir) -- `get_next_ticket_id()` scan ulang tiap
        kali, ticket BARU dari iterasi sebelumnya harus udah keliatan di
        query berikutnya biar 2 CVE baru dalam satu batch gak kebagian
        nomor ticket sama (legacy Mongo aman dari ini otomatis karena
        tiap `update_one` langsung commit; SQLAlchemy session butuh
        flush eksplisit). Lock penomoran diambil SEBELUM membaca ticket yang ada, supaya
        pembacaan itu tidak basi terhadap transaksi lain yang sedang membuat ticket."""
        await self._lock_ticket_numbering()
        result = await self.session.execute(
            select(CveTicket).where(CveTicket.client_id == client_id, CveTicket.cve_id.in_(cve_ids))
        )
        existing_by_cve = {t.cve_id: t for t in result.scalars().all()}
        already_acked = {cid for cid, t in existing_by_cve.items() if t.acknowledged_by}
        to_ack = [c for c in cve_ids if c not in already_acked]
        if not to_ack:
            return 0

        analyst_name = analyst_name.strip()
        now = datetime.datetime.now(datetime.UTC)
        for cve_id in to_ack:
            ticket = existing_by_cve.get(cve_id)
            if ticket is None:
                ticket = CveTicket(
                    cve_id=cve_id,
                    client_id=client_id,
                    ticket_id=await self.get_next_ticket_id(reserve=True),
                )
                self.session.add(ticket)
            ticket.acknowledged_by = analyst_name
            ticket.acknowledge_time = now
            await self.session.flush()
        return len(to_ack)
