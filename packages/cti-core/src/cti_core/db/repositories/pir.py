"""AsyncPIRRepo -- CRUD `pir_requirements`/`pir_notes` + matching artikel
(Fase 7.3, Bagian 2). Port dari `ScraperNewsWeb/app/services/pir_service.py`.

Matching kriteria PIR -> artikel dilempar ke `AsyncArticleRepo.list_filtered`
yang UDAH ADA (router `articles`, Fase 7.3 awal) lewat `_criteria_filters()`
di bawah -- BUKAN query builder terpisah. Kode lama justru py dua salinan
identik dari builder ini (`pir_service._build_query` DAN
`scripts/export_pir_docx.py::_build_article_query`), sengaja gak diikutin
di sini.

`criteria.keywords` di-map ke `title_keywords` (`AsyncArticleRepo`, OR-match
`Article.title`) -- kode lama nyari lintas title/description/body/content,
tapi skema baru cuma nyimpen `title` per artikel (`body`/`content`
ephemeral, gak dipersist -- lihat `cti_enrich.stages.persist`), jadi
title-only adalah subset yang faithful terhadap apa yang BENERAN ada buat
dicari, bukan pengurangan scope yang disengaja nyembunyiin sesuatu.

**Asimetri client-scoping port apa adanya:** `list_pirs`/`create` di-filter
client_id, tapi `get_by_id`/`update`/`delete`/notes/export-artikel SAMA
SEKALI gak nerima/nge-filter client_id di kode lama (`pir_service.py` asli
-- router-nya juga gak manggil `effective_client_id` buat endpoint-endpoint
itu). Dipertahankan, sama pola kayak `rfi.py` (lihat docstring modul itu).

**Kuirk `recent_coverage` port apa adanya dari `_compute_coverage()` lama:**
kalau kriteria PIR KOSONG semua (query match-all), `recent` di-hardcode 0
(`col.count_documents(q_recent) if q else asyncio.coroutine(lambda: 0)()`)
-- BUKAN dihitung beneran, walau `total`/`last_match` tetap jalan normal
buat match-all. Efeknya PIR tanpa kriteria SELALU keliatan `is_gap=True`
apa pun isi datanya -- kemungkinan sengaja (dorong analis buat selalu
ngisi kriteria), bukan lupa nulis kode, jadi diikutin apa adanya.

Alert otomatis ("artikel baru cocok PIR aktif") BELUM diport di sini --
itu masuk Fase 7.8 (Celery beat "PIR alert"), lihat docstring
`models/pir.py`."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.db.models.article import ArticleTTP
from cti_core.db.models.pir import PIRNote, PIRRequirement
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.ttp_catalog import canonical_ttp_name

_CRITERIA_KEYS = ("threat_actors", "industries", "countries", "news_types", "keywords", "ttps")


def _has_criteria(criteria: dict[str, Any]) -> bool:
    return any(criteria.get(k) for k in _CRITERIA_KEYS)


def _criteria_filters(criteria: dict[str, Any]) -> dict[str, Any]:
    return {
        "threat_actors": criteria.get("threat_actors") or None,
        "industries": criteria.get("industries") or None,
        "countries": criteria.get("countries") or None,
        "news_types": criteria.get("news_types") or None,
        "title_keywords": criteria.get("keywords") or None,
        "ttps": criteria.get("ttps") or None,
    }


class AsyncPIRRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def compute_coverage(
        self,
        article_repo: AsyncArticleRepo,
        criteria: dict[str, Any],
        start_date: datetime.date | None,
        end_date: datetime.date | None,
    ) -> tuple[int, str | None, int]:
        """`(total, last_match_iso, recent_14d_count)` -- lihat catatan
        kuirk `recent` di docstring modul."""
        filters = _criteria_filters(criteria)
        articles, total = await article_repo.list_filtered(
            page=1,
            page_size=1,
            posted_on_start=start_date,
            posted_on_end=end_date,
            **filters,
        )
        last_match = (
            articles[0].posted_on.isoformat() if articles and articles[0].posted_on else None
        )

        recent = 0
        if _has_criteria(criteria):
            cutoff = datetime.date.today() - datetime.timedelta(days=14)
            recent_start = max(cutoff, start_date) if start_date else cutoff
            _, recent = await article_repo.list_filtered(
                page=1,
                page_size=1,
                posted_on_start=recent_start,
                posted_on_end=end_date,
                **filters,
            )
        return total, last_match, recent

    async def list_pirs(
        self, article_repo: AsyncArticleRepo, client_id: str
    ) -> list[tuple[PIRRequirement, int, str | None, int]]:
        result = await self.session.execute(
            select(PIRRequirement)
            .where(PIRRequirement.client_id == client_id)
            .order_by(PIRRequirement.priority.asc())
        )
        pirs = list(result.scalars().all())
        out: list[tuple[PIRRequirement, int, str | None, int]] = []
        for p in pirs:
            # Query berurutan, BUKAN asyncio.gather -- satu AsyncSession
            # gak aman dipakai concurrent (beda dari motor/Mongo async lama
            # yang emang didesain buat itu).
            coverage = await self.compute_coverage(
                article_repo, p.criteria, p.start_date, p.end_date
            )
            out.append((p, *coverage))
        return out

    async def get_by_id(self, pir_id: int) -> PIRRequirement | None:
        result = await self.session.execute(
            select(PIRRequirement).where(PIRRequirement.id == pir_id)
        )
        return result.scalar_one_or_none()

    async def list_active_unscoped(self) -> list[PIRRequirement]:
        """Lintas client, TANPA filter -- port apa adanya dari
        `cross_reference_service.get_cve_crossrefs()`
        (`db[PIR_COLLECTION].find({"status": "active"})`, gak nge-scope
        client). Dulu dipakai `crossref` dan `stix.build_pir_stix_bundle`; sejak 2026-10-24
        keduanya memakai `list_active_by_client` (endpoint user tidak boleh lintas client), jadi
        sisa pemakainya job internal (`pir_alert`)."""
        result = await self.session.execute(
            select(PIRRequirement)
            .where(PIRRequirement.status == "active")
            .order_by(PIRRequirement.priority.asc())
            .limit(500)
        )
        return list(result.scalars().all())

    async def list_active_by_client(self, client_id: str) -> list[PIRRequirement]:
        """PIR aktif, DI-SCOPE client -- port `cluster_service._match_pirs()`
        (Fase 7.4 Grup A). Legacy: `$or [{client_id: "default"}, {client_id
        gak ada}]` khusus client "default" -- asimetri "default ATAU
        field gak ada" itu artefak migrasi era Mongo (PIR lama sebelum
        `client_id` ditambahin), gak relevan lagi di skema baru
        (`PIRRequirement.client_id` NOT NULL, gak ada row "tanpa
        client_id"). Beda dari `list_active_unscoped()` di atas (lintas
        SEMUA client, sekarang hanya untuk job internal seperti `pir_alert`; `crossref`/`stix`
        yang dipanggil user memakai fungsi ini sejak 2026-10-24) -- `_match_pirs` legacy
        MEMANG scope per-client, bukan lintas client."""
        result = await self.session.execute(
            select(PIRRequirement)
            .where(PIRRequirement.client_id == client_id, PIRRequirement.status == "active")
            .order_by(PIRRequirement.priority.asc())
            .limit(500)
        )
        return list(result.scalars().all())

    async def create(self, data: dict[str, Any], *, client_id: str) -> PIRRequirement:
        pir = PIRRequirement(
            title=data["title"],
            description=data.get("description") or "",
            priority=data.get("priority") or "P2",
            owner=data.get("owner") or "",
            status="active",
            criteria=data.get("criteria") or {},
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            client_id=client_id,
        )
        self.session.add(pir)
        await self.session.flush()
        return pir

    async def update(self, pir_id: int, data: dict[str, Any]) -> PIRRequirement | None:
        pir = await self.get_by_id(pir_id)
        if pir is None:
            return None
        for key in (
            "title",
            "description",
            "priority",
            "owner",
            "status",
            "criteria",
            "start_date",
            "end_date",
        ):
            if key in data:
                setattr(pir, key, data[key])
        await self.session.flush()
        return pir

    async def delete(self, pir_id: int) -> bool:
        pir = await self.get_by_id(pir_id)
        if pir is None:
            return False
        await self.session.delete(pir)
        await self.session.flush()
        return True

    async def list_articles_for_pir(
        self,
        pir: PIRRequirement,
        article_repo: AsyncArticleRepo,
        *,
        page: int = 1,
        page_size: int = 15,
        created_at_start: datetime.datetime | None = None,
    ) -> tuple[list[Any], int]:
        """`created_at_start` (Fase 7.8, `pir_alert`) -- "artikel yang
        BARU masuk sejak tick terakhir", dipasang BARENG `pir.start_date`/
        `end_date` (bukan gantiin) -- PIR yang jendela aktifnya udah
        lewat tetep gak nyangkut walau artikelnya baru."""
        filters = _criteria_filters(pir.criteria)
        return await article_repo.list_filtered(
            page=page,
            page_size=page_size,
            posted_on_start=pir.start_date,
            posted_on_end=pir.end_date,
            created_at_start=created_at_start,
            **filters,
        )

    async def list_all_articles_for_pir(
        self, pir: PIRRequirement, article_repo: AsyncArticleRepo
    ) -> list[Any]:
        """Dipakai `/export` + `/export/docx` -- "semua" artikel cocok,
        bukan sepotong halaman. `page_size=10000` port dari `to_list(10000)`
        lama (angka cap yang sama, bukan literally unbounded)."""
        articles, _ = await self.list_articles_for_pir(pir, article_repo, page=1, page_size=10000)
        return articles

    async def urls_with_notes(self, pir_id: int, urls: list[str]) -> set[str]:
        if not urls:
            return set()
        result = await self.session.execute(
            select(PIRNote.url).where(PIRNote.pir_id == pir_id, PIRNote.url.in_(urls))
        )
        return set(result.scalars().all())

    async def get_note(self, pir_id: int, url: str) -> PIRNote | None:
        result = await self.session.execute(
            select(PIRNote).where(PIRNote.pir_id == pir_id, PIRNote.url == url)
        )
        return result.scalar_one_or_none()

    async def notes_by_url(self, pir_id: int) -> dict[str, PIRNote]:
        result = await self.session.execute(select(PIRNote).where(PIRNote.pir_id == pir_id))
        return {n.url: n for n in result.scalars().all()}

    async def save_note(self, pir_id: int, url: str, note: str, analyst: str) -> PIRNote:
        existing = await self.get_note(pir_id, url)
        if existing is not None:
            existing.note = note
            existing.analyst = analyst
            await self.session.flush()
            return existing
        row = PIRNote(pir_id=pir_id, url=url, note=note, analyst=analyst)
        self.session.add(row)
        await self.session.flush()
        return row

    async def get_options(self, article_repo: AsyncArticleRepo) -> dict[str, Any]:
        base = await article_repo.get_filter_options()
        ttp_result = await self.session.execute(
            select(ArticleTTP.ttp_id, canonical_ttp_name())
            .group_by(ArticleTTP.ttp_id)
            .order_by(ArticleTTP.ttp_id)
            .limit(500)
        )
        ttps = [{"id": tid, "name": tname} for tid, tname in ttp_result.all()]
        return {
            "threat_actors": base["threat_actors"],
            "industries": base["industries"],
            "countries": base["countries"],
            "news_types": base["news_types"],
            "ttps": ttps,
        }
