"""ArticleRepo -- satu-satunya jalur tulis/baca tabel `articles`.

Aturan inti (plan §5.6, gantiin `$setOnInsert`-only upsert lama yang bikin
re-scrape gak pernah update artikel yang udah ada):
  - Field IDENTITAS (url, url_hash) cuma diisi sekali, waktu insert.
  - Field MESIN (title, source, confidence_score, dst) di-`$set` bebas tiap
    upsert -- scraper/enrichment boleh nimpa terus.
  - Field `overrides` (hasil edit analis lewat web) TIDAK PERNAH disentuh
    upsert ini. `to_dict()` yang gabungin overrides ke atas field mesin,
    overrides menang.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Literal

from sqlalchemy import Select, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from cti_core.attack_ttp import NormalizedTTP
from cti_core.db.models.article import (
    Article,
    ArticleCountry,
    ArticleIndustry,
    ArticleMalware,
    ArticleThreatActor,
    ArticleTTP,
    RejectedArticle,
)
from cti_core.enrich_replay import BACKOFF_BASE, MAX_ATTEMPTS, ReplayCandidate
from cti_core.urlkit import url_hash as compute_url_hash

_RESERVED_OVERRIDE_KEYS = frozenset({"_meta"})

_TTP_SOURCES = frozenset({"llm", "explicit", "keyword"})
_ACTOR_SOURCES = frozenset({"dictionary", "llm", "analyst"})
_INDUSTRY_SOURCES = frozenset({"llm", "keyword"})
_MALWARE_KINDS = frozenset({"malware", "tool"})
"""Nilai sah kolom `source`/`kind` Tier 1. Dicek di sini, bukan Postgres CHECK (konvensi
`ArticleCountry.role`), biar nilai baru tidak butuh migrasi."""


def _check(value: str, allowed: frozenset[str], what: str) -> None:
    if value not in allowed:
        raise ValueError(f"{what} tidak valid: {value!r} (sah: {sorted(allowed)})")


def _apply_list_filters(
    stmt: Select[tuple[Article]],
    *,
    posted_on_start: datetime.date | None,
    posted_on_end: datetime.date | None,
    industries: Sequence[str] | None,
    countries: Sequence[str] | None,
    victim_countries: Sequence[str] | None,
    actor_countries: Sequence[str] | None,
    sources: Sequence[str] | None,
    news_types: Sequence[str] | None,
    threat_actors: Sequence[str] | None,
    search: str | None,
    title_keywords: Sequence[str] | None,
    ttps: Sequence[str] | None = None,
    created_at_start: datetime.datetime | None = None,
    confirmed_only: bool = False,
    story_id: int | None = None,
) -> Select[tuple[Article]]:
    """Filter bersama buat query list DAN count -- port dari `article_service.
    get_articles()` (Mongo query dict) ke SQL. Tiga field negara Mongo lama
    (`mentioned_countries`/`victim_countries`/`actor_countries`, tiga ARRAY
    terpisah) sekarang SATU tabel `article_countries` + kolom `role` (Fase 2)
    -- `countries` (param umum) = role APA PUN. Di Mongo lama
    `mentioned_countries` itu GABUNGAN regex/NER + victim GPT + actor GPT
    (`nlp.py`: `regex_countries + gpt_victim_countries + gpt_actor_countries`),
    sedangkan role "mentioned" di skema baru cuma SISA yang gak kepakai
    victim/actor (`cti_enrich.stages.persist._country_roles`). Filter
    `role == "mentioned"` (bug lama, QA BUG-B1) bikin artikel yang negaranya
    victim -- mayoritas data -- gak pernah ketemu."""
    if posted_on_start is not None:
        stmt = stmt.where(Article.posted_on >= posted_on_start)
    if posted_on_end is not None:
        stmt = stmt.where(Article.posted_on <= posted_on_end)
    if created_at_start is not None:
        # Beda dari `posted_on` (tanggal publish, presisi HARI) -- ini
        # `created_at` (timestamp masuk ke sistem KITA, presisi DETIK).
        # Dipakai `pir_alert` (Fase 7.8, Celery beat) buat "artikel yang
        # BENERAN baru sejak tick terakhir", bukan "artikel yang tayang
        # hari ini" -- dua hal beda yang `posted_on` gak bisa jawab.
        stmt = stmt.where(Article.created_at >= created_at_start)
    if confirmed_only:
        stmt = stmt.where(Article.confirmed_incident.is_(True))
    if story_id is not None:
        stmt = stmt.where(Article.story_id == story_id)
    if industries:
        stmt = stmt.join(Article.industries).where(ArticleIndustry.industry.in_(industries))
    if countries:
        any_role = _country_alias()
        stmt = stmt.join(any_role, Article.id == any_role.article_id).where(
            any_role.country_code.in_(countries)
        )
    if victim_countries:
        victim = _country_alias()
        stmt = stmt.join(victim, Article.id == victim.article_id).where(
            victim.role == "victim", victim.country_code.in_(victim_countries)
        )
    if actor_countries:
        actor = _country_alias()
        stmt = stmt.join(actor, Article.id == actor.article_id).where(
            actor.role == "actor", actor.country_code.in_(actor_countries)
        )
    if sources:
        stmt = stmt.where(Article.source.in_(sources))
    if news_types:
        stmt = stmt.where(Article.news_type.in_(news_types))
    if threat_actors:
        # Mongo lama: regex `^...$` case-insensitive -- exact match, BUKAN
        # substring. `func.lower(...).in_(...)` ekuivalen persis.
        lowered = [t.lower() for t in threat_actors]
        stmt = stmt.join(Article.threat_actors).where(
            func.lower(ArticleThreatActor.threat_actor).in_(lowered)
        )
    if ttps:
        stmt = stmt.join(Article.ttps).where(ArticleTTP.ttp_id.in_(ttps))
    keyword_or = (
        [Article.title.ilike(f"%{kw}%") for kw in title_keywords] if title_keywords else None
    )
    search_or = (
        [Article.title.ilike(f"%{search}%"), Article.source.ilike(f"%{search}%")]
        if search
        else None
    )
    if keyword_or and search_or:
        stmt = stmt.where(or_(*keyword_or), or_(*search_or))
    elif keyword_or:
        stmt = stmt.where(or_(*keyword_or))
    elif search_or:
        stmt = stmt.where(or_(*search_or))
    return stmt


def _country_alias() -> Any:
    """Alias baru tiap dipanggil -- filter negara bisa dipakai 3x sekaligus
    (mentioned + victim + actor) dalam SATU query; tanpa alias, tiga JOIN
    ke tabel yang sama bakal nabrak nama."""
    return aliased(ArticleCountry)


def all_country_codes(article: Article) -> list[str]:
    """Kode negara artikel di role APA PUN, dedup, urutan dipertahankan --
    padanan field `mentioned_countries` Mongo lama (gabungan regex + victim +
    actor, lihat `_apply_list_filters`). Dipakai output yang dulu baca
    `mentioned_countries` mentah (PIR, STIX, clustering campaign); output yang
    memang mecah per role (`ArticleOut`, newsletter) tetap baca per role."""
    return list(dict.fromkeys(c.country_code for c in article.countries if c.country_code))


def _merge_overrides(article: Article) -> dict[str, Any]:
    base = {c.name: getattr(article, c.name) for c in Article.__table__.columns}
    overrides = {k: v for k, v in article.overrides.items() if k not in _RESERVED_OVERRIDE_KEYS}
    return {**base, **overrides}


def _apply_machine_fields(article: Article, machine_fields: dict[str, Any]) -> None:
    valid_columns = Article.__table__.columns.keys()
    for k, v in machine_fields.items():
        if k not in valid_columns:
            raise ValueError(f"'{k}' bukan kolom Article -- typo, atau harusnya masuk overrides?")
        if k in ("id", "url", "url_hash", "overrides", "created_at"):
            raise ValueError(f"'{k}' itu field identitas/override, upsert() gak boleh nimpa ini")
        setattr(article, k, v)


TTPInput = tuple[str, str] | NormalizedTTP
"""`(ttp_id, ttp_name)` polos (test/fixture, tanpa teks asli LLM) atau
`NormalizedTTP` (enrichment/remap -- bawa `extracted_id`/`extracted_name`)."""


def _first_ttps(ttps: Sequence[TTPInput]) -> dict[str, NormalizedTTP]:
    first_per_id: dict[str, NormalizedTTP] = {}
    for t in ttps:
        n = t if isinstance(t, NormalizedTTP) else NormalizedTTP(t[0], t[1])
        first_per_id.setdefault(n.ttp_id, n)
    return first_per_id


def _first_ttp_names(ttps: Sequence[TTPInput]) -> dict[str, str]:
    return {tid: n.ttp_name for tid, n in _first_ttps(ttps).items()}


def _dedup_ttps(ttps: Sequence[TTPInput]) -> list[ArticleTTP]:
    """DEDUP PER `ttp_id` (kunci `uq_article_ttp` = (article_id, ttp_id)),
    BUKAN per tuple `(id, nama)`. LLM kadang ngembaliin ID yang SAMA dua kali
    dgn nama beda ("T1176" -> "Browser Extensions" & "Software Extensions");
    dedup per tuple meloloskan keduanya -> UniqueViolation -> SELURUH
    transaksi (artikelnya) ke-rollback dan artikel HILANG. Ketemu di e2e
    staging Fase 10 (1 dari 10 artikel). Nama pertama yang menang."""
    return [ArticleTTP(ttp_id=tid, ttp_name=name) for tid, name in _first_ttp_names(ttps).items()]


def _reconcile[T, K](
    current: Iterable[T], wanted: Iterable[K], key_of: Callable[[T], K], make: Callable[[K], T]
) -> list[T]:
    """Daftar child baru: baris yang KUNCI-nya masih diinginkan dipakai ULANG
    (instance yang sama), sisanya dibuat baru; yang tidak lagi diinginkan hilang
    (delete-orphan).

    Kenapa bukan "buang semua, bikin ulang" (yang dulu dipakai): unit-of-work
    SQLAlchemy menjalankan INSERT sebelum DELETE di flush yang sama, jadi baris
    baru berkunci SAMA dengan baris lama yang mau dihapus menabrak
    `uq_article_*` (`UniqueViolation`). Persist ulang artikel yang sama -- dua
    scraper meliput URL yang sama (dedup itu per-scraper), atau retry sesudah
    persist -- gagal, dan artikel yang sehat dicatat `[enrichment_failed]`."""
    by_key = {key_of(c): c for c in current}
    return [by_key[k] if k in by_key else make(k) for k in wanted]


def _apply_enrichment(
    article: Article,
    *,
    countries: Sequence[tuple[str, str]],
    industries: Sequence[str],
    threat_actors: Sequence[str],
    ttps: Sequence[TTPInput],
    malware: Sequence[tuple[str, str]] = (),
    industry_source: str = "llm",
) -> None:
    """Pasang hasil enrichment ke child rows -- idempoten (lihat `_reconcile`).
    Dipakai versi sync DAN async, biar logikanya gak bisa drift."""
    _check(industry_source, _INDUSTRY_SOURCES, "industry_source")
    for _, kind in malware:
        _check(kind, _MALWARE_KINDS, "malware kind")
    article.countries = _reconcile(
        article.countries,
        dict.fromkeys(countries),
        lambda c: (c.country_code, c.role),
        lambda k: ArticleCountry(country_code=k[0], role=k[1]),
    )
    article.industries = _reconcile(
        article.industries,
        dict.fromkeys(industries),
        lambda c: c.industry,
        lambda k: ArticleIndustry(industry=k, source=industry_source),
    )
    for ind in article.industries:
        ind.source = industry_source
    article.threat_actors = _reconcile(
        article.threat_actors,
        dict.fromkeys(threat_actors),
        lambda c: c.threat_actor,
        lambda k: ArticleThreatActor(threat_actor=k, source="dictionary"),
    )
    # kunci unik = (article_id, name): dedup per nama (pertama menang), kind baris pakai-ulang
    # ikut diperbarui -- kalau tidak, nama sama beda kind -> UniqueViolation dan artikel hilang.
    kinds: dict[str, str] = {}
    for name, kind in malware:
        kinds.setdefault(name, kind)
    article.malware = _reconcile(
        article.malware,
        kinds,
        lambda c: c.name,
        lambda k: ArticleMalware(name=k, kind=kinds[k], source="dictionary"),
    )
    for m in article.malware:
        m.kind = kinds[m.name]
    apply_ttps(article, ttps)


def apply_ttps(article: Article, ttps: Sequence[TTPInput]) -> None:
    """Pasang child `article_ttps` -- reuse baris ber-`ttp_id` sama (lihat
    `_reconcile`). Dipakai `_apply_enrichment` dan remap TTP
    (`cti_core.db.repositories.ttp_catalog.remap_article_ttps`)."""
    kept = {t.ttp_id: t for t in article.ttps}
    rows: list[ArticleTTP] = []
    for tid, n in _first_ttps(ttps).items():
        _check(n.source, _TTP_SOURCES, "ttp source")
        row = kept.get(tid)
        if row is None:
            row = ArticleTTP(ttp_id=tid, ttp_name=n.ttp_name)
        else:
            row.ttp_name = n.ttp_name
        row.extracted_id = n.extracted_id
        row.extracted_name = n.extracted_name
        row.source = n.source
        row.evidence = n.evidence
        rows.append(row)
    article.ttps = rows


class ArticleRepo:
    """Sync -- dipakai scraper/enrichment (Celery task), CLI."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, *, url: str, title: str, source: str, **machine_fields: Any) -> Article:
        h = compute_url_hash(url)
        existing = self.session.execute(
            select(Article).where(Article.url_hash == h)
        ).scalar_one_or_none()
        now = datetime.datetime.now(datetime.UTC)

        if existing is None:
            article = Article(
                url=url,  # URL ASLI disimpan, bukan hasil canonicalize_url() -- url_hash yang
                # jadi kunci dedup; url tetap perlu bentuk aslinya buat ditampilkan/dibuka user
                url_hash=h,
                title=title,
                source=source,
                first_seen_at=now,
                last_seen_at=now,
                seen_count=1,
            )
            _apply_machine_fields(article, machine_fields)
            self.session.add(article)
            self.session.flush()
            return article

        existing.title = title
        existing.source = source
        existing.last_seen_at = now
        existing.seen_count += 1
        _apply_machine_fields(existing, machine_fields)
        self.session.flush()
        return existing

    def get_by_url_hash(self, url_hash_value: str) -> Article | None:
        return self.session.execute(
            select(Article).where(Article.url_hash == url_hash_value)
        ).scalar_one_or_none()

    def get_by_url(self, url: str) -> Article | None:
        return self.get_by_url_hash(compute_url_hash(url))

    def mark_seen(self, article: Article) -> Article:
        """Kedatangan ulang URL yang SUDAH jadi artikel (feed lain, atau feed yang sama
        sesudah TTL dedup habis): cuma `seen_count`/`last_seen_at` yang naik. Judul,
        sumber, dan enrichment kedatangan pertama dipertahankan -- beda dari `upsert`,
        yang menimpa semuanya. Lihat `cti_enrich.pipeline.run_pipeline`."""
        article.seen_count += 1
        article.last_seen_at = datetime.datetime.now(datetime.UTC)
        self.session.flush()
        return article

    def set_overrides(self, article: Article, **overrides: Any) -> Article:
        """Satu-satunya jalur analis nulis koreksi manual -- lihat plan §5.6.
        Dipanggil dari layer web (Fase 7), bukan dari scraper/enrichment."""
        article.overrides = {**article.overrides, **overrides}
        self.session.flush()
        return article

    def set_enrichment(
        self,
        article: Article,
        *,
        countries: Sequence[tuple[str, str]] = (),
        industries: Sequence[str] = (),
        threat_actors: Sequence[str] = (),
        ttps: Sequence[TTPInput] = (),
        malware: Sequence[tuple[str, str]] = (),
        industry_source: str = "llm",
    ) -> Article:
        """Ganti SEMUA child row (countries/industries/threat_actors/ttps)
        dari SATU hasil enrichment -- Fase 5 (`cti_enrich.pipeline`), satu-
        satunya caller. `countries`: `(country_code ISO alpha-2, role)`,
        `role` salah satu `victim|actor|mentioned` (lihat `ArticleCountry`).
        `ttps`: `(ttp_id, ttp_name)` atau `NormalizedTTP` (normalisasi ke
        katalog ATT&CK itu tugas CALLER -- `cti_enrich.pipeline`, lihat
        `cti_core.attack_ttp`; repo nyimpen apa adanya).

        Assign ulang list relationship (bukan merge/diff) -- `cascade="all,
        delete-orphan"` (Fase 2) yang hapus baris lama, sama filosofi
        `CveTrackerRepo.upsert`: hasil enrichment TERBARU kebenaran, bukan
        delta yang ditumpuk. Dedup di sini (bukan percaya caller) karena
        `UniqueConstraint` per (article, kolom[, role]) bakal nolak baris
        kembar kalau caller kirim duplikat."""
        _apply_enrichment(
            article,
            countries=countries,
            industries=industries,
            threat_actors=threat_actors,
            ttps=ttps,
            malware=malware,
            industry_source=industry_source,
        )
        self.session.flush()
        return article

    def add_tier1(
        self,
        article: Article,
        *,
        ttps: Sequence[NormalizedTTP],
        threat_actors: Sequence[str],
        malware: Sequence[tuple[str, str]],
        industries: Sequence[str],
    ) -> dict[str, int]:
        """ADD-ONLY untuk backfill Tier 1: tidak pernah mengubah/menghapus baris yang ada
        (TTP LLM tetap, TTP keyword dengan ID sama tidak ditambah). Industri `keyword` hanya
        ditambah kalau industri sekarang persis `["General"]` (baris General lalu dibuang) --
        industri spesifik dari LLM tidak boleh ditimpa tebakan keyword. Return jumlah baris
        baru per jenis."""
        counts = {"ttps": 0, "threat_actors": 0, "malware": 0, "industries": 0}
        have_ttp = {t.ttp_id for t in article.ttps}
        for n in ttps:
            _check(n.source, _TTP_SOURCES, "ttp source")
            if n.ttp_id in have_ttp:
                continue
            have_ttp.add(n.ttp_id)
            article.ttps.append(
                ArticleTTP(
                    ttp_id=n.ttp_id,
                    ttp_name=n.ttp_name,
                    extracted_id=n.extracted_id,
                    extracted_name=n.extracted_name,
                    source=n.source,
                    evidence=n.evidence,
                )
            )
            counts["ttps"] += 1
        have_actor = {a.threat_actor for a in article.threat_actors}
        for name in dict.fromkeys(threat_actors):
            if name not in have_actor:
                article.threat_actors.append(
                    ArticleThreatActor(threat_actor=name, source="dictionary")
                )
                counts["threat_actors"] += 1
        have_mal = {m.name for m in article.malware}
        for name, kind in malware:
            _check(kind, _MALWARE_KINDS, "malware kind")
            if name not in have_mal:
                have_mal.add(name)
                article.malware.append(ArticleMalware(name=name, kind=kind, source="dictionary"))
                counts["malware"] += 1
        if industries and [i.industry for i in article.industries] == ["General"]:
            article.industries = [
                ArticleIndustry(industry=name, source="keyword")
                for name in dict.fromkeys(industries)
            ]
            counts["industries"] = len(article.industries)
        self.session.flush()
        return counts

    def to_dict(self, article: Article) -> dict[str, Any]:
        """Field mesin + overrides tergabung, overrides menang. Ini yang
        dibaca API/dashboard -- JANGAN baca kolom Article langsung kalau
        butuh nilai yang analis udah koreksi."""
        return _merge_overrides(article)


class AsyncArticleRepo:
    """Async -- dipakai FastAPI (Fase 7). Logic sama persis ArticleRepo,
    beda cuma `await` -- lihat plan §5.2 soal rasio duplikasi ini."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(self, *, url: str, title: str, source: str, **machine_fields: Any) -> Article:
        h = compute_url_hash(url)
        result = await self.session.execute(select(Article).where(Article.url_hash == h))
        existing = result.scalar_one_or_none()
        now = datetime.datetime.now(datetime.UTC)

        if existing is None:
            article = Article(
                url=url,
                url_hash=h,
                title=title,
                source=source,
                first_seen_at=now,
                last_seen_at=now,
                seen_count=1,
            )
            _apply_machine_fields(article, machine_fields)
            self.session.add(article)
            await self.session.flush()
            return article

        existing.title = title
        existing.source = source
        existing.last_seen_at = now
        existing.seen_count += 1
        _apply_machine_fields(existing, machine_fields)
        await self.session.flush()
        return existing

    async def set_enrichment(
        self,
        article: Article,
        *,
        countries: Sequence[tuple[str, str]] = (),
        industries: Sequence[str] = (),
        threat_actors: Sequence[str] = (),
        ttps: Sequence[TTPInput] = (),
        malware: Sequence[tuple[str, str]] = (),
        industry_source: str = "llm",
    ) -> Article:
        """Logic sama persis `ArticleRepo.set_enrichment` -- dipakai test
        integrasi Fase 7 (setup fixture artikel via jalur async), bukan
        Fase 5 (itu tetap lewat `ArticleRepo` sync, Celery task).

        `refresh()` 5 relationship dulu SEBELUM di-assign ulang -- ganti
        koleksi (`article.countries = [...]`) di sesi ASYNC butuh state
        koleksi LAMA buat ngitung diff (cascade delete-orphan), dan itu
        lazy-load implisit yang gak bisa jalan sinkron di luar `await`
        (`MissingGreenlet`). Versi sync (`ArticleRepo`) gak kena ini --
        lazy-load implisit sinkron biasa jalan di sana."""
        await self.session.refresh(
            article,
            attribute_names=["countries", "industries", "threat_actors", "ttps", "malware"],
        )
        _apply_enrichment(
            article,
            countries=countries,
            industries=industries,
            threat_actors=threat_actors,
            ttps=ttps,
            malware=malware,
            industry_source=industry_source,
        )
        await self.session.flush()
        return article

    async def get_by_url_hash(self, url_hash_value: str) -> Article | None:
        result = await self.session.execute(
            select(Article).where(Article.url_hash == url_hash_value)
        )
        return result.scalar_one_or_none()

    async def get_by_url(self, url: str) -> Article | None:
        return await self.get_by_url_hash(compute_url_hash(url))

    async def set_overrides(self, article: Article, **overrides: Any) -> Article:
        article.overrides = {**article.overrides, **overrides}
        await self.session.flush()
        return article

    def to_dict(self, article: Article) -> dict[str, Any]:
        return _merge_overrides(article)

    async def get_by_id(self, article_id: int) -> Article | None:
        result = await self.session.execute(select(Article).where(Article.id == article_id))
        return result.scalar_one_or_none()

    async def get_by_ids(self, article_ids: Sequence[int]) -> dict[int, Article]:
        """Fase 7.3 (router `newsletter`, Bagian 4) -- port
        `fetch_articles_by_ids()`, dulu ObjectId string, sekarang `int`
        (Article.id) langsung, gak butuh validasi format kayak
        `ObjectId.is_valid()` lama."""
        if not article_ids:
            return {}
        result = await self.session.execute(select(Article).where(Article.id.in_(article_ids)))
        return {a.id: a for a in result.scalars().all()}

    async def list_filtered(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        posted_on_start: datetime.date | None = None,
        posted_on_end: datetime.date | None = None,
        industries: Sequence[str] | None = None,
        countries: Sequence[str] | None = None,
        victim_countries: Sequence[str] | None = None,
        actor_countries: Sequence[str] | None = None,
        sources: Sequence[str] | None = None,
        news_types: Sequence[str] | None = None,
        threat_actors: Sequence[str] | None = None,
        search: str | None = None,
        title_keywords: Sequence[str] | None = None,
        ttps: Sequence[str] | None = None,
        created_at_start: datetime.datetime | None = None,
        sort: Literal["recent", "priority"] = "recent",
        confirmed_only: bool = False,
        story_id: int | None = None,
    ) -> tuple[list[Article], int]:
        """Port `article_service.get_articles()`. Filter di-`join()` ke
        tabel anak -- `.distinct()` WAJIB begitu ada join one-to-many
        (satu artikel bisa punya banyak baris industry/country/TA yang
        cocok, tanpa distinct dia muncul dobel di halaman).

        `ttps` (Fase 7.3, router `pir`) filter `ArticleTTP.ttp_id` --
        ditambah di sini alih-alih duplikat query builder terpisah di
        `pir`, biar SATU sumber logic filter artikel (beda dari kode
        lama: `pir_service._build_query` DAN `export_pir_docx.py
        _build_article_query` adalah dua salinan yang sama persis).

        `created_at_start` (Fase 7.8, `pir_alert`) -- lihat docstring
        `_apply_list_filters`.

        `sort="priority"` (newsroom/dashboard "Perlu dibaca"): insiden terkonfirmasi dulu,
        lalu `confidence_score` (NULL terakhir), `seen_count` (makin sering terlihat makin
        penting), baru terbaru. Default "recent" = urutan lama. `confirmed_only` membatasi ke
        insiden terkonfirmasi."""
        base = _apply_list_filters(
            select(Article),
            posted_on_start=posted_on_start,
            posted_on_end=posted_on_end,
            industries=industries,
            countries=countries,
            victim_countries=victim_countries,
            actor_countries=actor_countries,
            sources=sources,
            news_types=news_types,
            threat_actors=threat_actors,
            search=search,
            title_keywords=title_keywords,
            ttps=ttps,
            created_at_start=created_at_start,
            confirmed_only=confirmed_only,
            story_id=story_id,
        )
        has_join = bool(
            industries or countries or victim_countries or actor_countries or threat_actors or ttps
        )

        count_stmt = select(func.count()).select_from(base.distinct().subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        order: tuple[Any, ...]
        if sort == "priority":
            order = (
                Article.confirmed_incident.desc(),
                Article.confidence_score.desc().nulls_last(),
                Article.seen_count.desc(),
                Article.posted_on.desc().nulls_last(),
                Article.id.desc(),
            )
        else:
            order = (Article.posted_on.desc().nulls_last(), Article.id.desc())
        list_stmt = base.order_by(*order)
        if has_join:
            list_stmt = list_stmt.distinct()
        list_stmt = list_stmt.offset((page - 1) * page_size).limit(page_size)
        result = await self.session.execute(list_stmt)
        articles = list(result.scalars().unique().all())
        return articles, total

    async def list_top_between(
        self, start: datetime.date, end: datetime.date, *, limit: int
    ) -> tuple[list[Article], int]:
        """`(artikel terkuat dengan posted_on di [start, end], maksimal `limit`, total sebenarnya)`.

        Dipakai recap mingguan: yang masuk prompt dipilih DI SQL (`LIMIT`), bukan dimuat semua
        (seminggu bisa ribuan artikel, tiap baris menarik empat tabel anak lewat selectin). Urutan
        sinyal yang ada di kolom: insiden terkonfirmasi, lalu `confidence_score` (NULL terakhir),
        lalu terbaru. Sinyal yang tidak ada di kolom (keandalan sumber, ukuran klaster) dipakai
        pemanggil untuk menyusun ulang kumpulan kandidat ini."""
        window = select(Article).where(Article.posted_on >= start, Article.posted_on <= end)
        total = (
            await self.session.execute(select(func.count()).select_from(window.subquery()))
        ).scalar_one()
        result = await self.session.execute(
            window.order_by(
                Article.confirmed_incident.desc(),
                Article.confidence_score.desc().nulls_last(),
                Article.posted_on.desc(),
                Article.id.desc(),
            ).limit(limit)
        )
        return list(result.scalars().all()), total

    async def get_filter_options(self) -> dict[str, Any]:
        """Port `article_service.get_filter_options()`. Distinct langsung
        dari kolom/tabel anak yang udah ternormalisasi -- gak butuh
        `col.distinct()` Mongo-style, ini query SQL biasa per tabel."""
        industries_q = (
            select(ArticleIndustry.industry).distinct().order_by(ArticleIndustry.industry)
        )
        # Role apa pun -- sama semantik sama filter `countries` (lihat
        # `_apply_list_filters`), biar opsi dropdown = negara yang bisa ketemu.
        countries_q = (
            select(ArticleCountry.country_code).distinct().order_by(ArticleCountry.country_code)
        )
        sources_q = (
            select(Article.source).where(Article.source != "").distinct().order_by(Article.source)
        )
        news_types_q = (
            select(Article.news_type)
            .where(Article.news_type.is_not(None))
            .distinct()
            .order_by(Article.news_type)
        )
        threat_actors_q = (
            select(ArticleThreatActor.threat_actor)
            .distinct()
            .order_by(ArticleThreatActor.threat_actor)
        )
        date_range_q = select(func.min(Article.posted_on), func.max(Article.posted_on))

        industries = (await self.session.execute(industries_q)).scalars().all()
        countries = (await self.session.execute(countries_q)).scalars().all()
        sources = (await self.session.execute(sources_q)).scalars().all()
        news_types = (await self.session.execute(news_types_q)).scalars().all()
        threat_actors = (await self.session.execute(threat_actors_q)).scalars().all()
        min_date, max_date = (await self.session.execute(date_range_q)).one()

        return {
            "industries": list(industries),
            "countries": list(countries),
            "sources": list(sources),
            "news_types": list(news_types),
            "threat_actors": list(threat_actors),
            "date_range": {
                "min": min_date.isoformat() if min_date else "",
                "max": max_date.isoformat() if max_date else "",
            },
        }


AUTO_REPLAY_KINDS = ("transient", "config", "json")


class RejectedArticleRepo:
    """Sync -- dipakai `cti_enrich.stages.persist.persist_rejected()`
    (Celery task `enrich.article`, sama proses tulis kayak `ArticleRepo`)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(
        self,
        *,
        url: str,
        title: str,
        source: str,
        scraper_id: str | None = None,
        posted_on: datetime.date | None = None,
        reason: str | None = None,
        failure_kind: str | None = None,
        raw_enrichment: dict[str, Any] | None = None,
    ) -> RejectedArticle:
        """`raw_enrichment` (audit trail respons LLM mentah) None = jangan
        sentuh yang sudah tersimpan. `failure_kind` SELALU menimpa (None juga): artikel yang
        dulu gagal lalu ditolak klasifikasi pada replay tidak boleh tetap bertanda gagal."""
        h = compute_url_hash(url)
        existing = self.session.execute(
            select(RejectedArticle).where(RejectedArticle.url_hash == h)
        ).scalar_one_or_none()

        if existing is None:
            row = RejectedArticle(
                url=url,
                url_hash=h,
                title=title,
                source=source,
                scraper_id=scraper_id,
                posted_on=posted_on,
                reason=reason,
                failure_kind=failure_kind,
                raw_enrichment=raw_enrichment or {},
            )
            self.session.add(row)
            self.session.flush()
            return row

        existing.title = title
        existing.source = source
        existing.scraper_id = scraper_id
        existing.posted_on = posted_on
        existing.reason = reason
        existing.failure_kind = failure_kind
        # `auto_replay_count` / `last_auto_replay_at` sengaja tidak disentuh (milik task replay).
        if raw_enrichment is not None:
            existing.raw_enrichment = raw_enrichment
        self.session.flush()
        return existing

    def auto_replay_candidates(self, now: datetime.datetime, limit: int) -> list[ReplayCandidate]:
        """Artikel `[enrichment_failed]` yang boleh dicoba otomatis (spec 4.2): jenis `transient`,
        `config`, `json`; percobaan < `MAX_ATTEMPTS`; jeda `BACKOFF_BASE * 2 ** count` sejak
        percobaan terakhir sudah lewat; yang paling lama ditolak lebih dulu."""
        backoff: Any = literal_column("interval '1 minute'") * (
            func.power(2, RejectedArticle.auto_replay_count) * (BACKOFF_BASE.total_seconds() // 60)
        )
        rows = (
            self.session.execute(
                select(RejectedArticle)
                .where(
                    RejectedArticle.failure_kind.in_(AUTO_REPLAY_KINDS),
                    RejectedArticle.auto_replay_count < MAX_ATTEMPTS,
                    or_(
                        RejectedArticle.last_auto_replay_at.is_(None),
                        RejectedArticle.last_auto_replay_at + backoff <= now,
                    ),
                )
                .order_by(RejectedArticle.rejected_at, RejectedArticle.id)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            ReplayCandidate(
                id=r.id,
                url=r.url,
                title=r.title,
                source=r.source,
                scraper_id=r.scraper_id,
                posted_on=r.posted_on,
                auto_replay_count=r.auto_replay_count,
                last_auto_replay_at=r.last_auto_replay_at,
            )
            for r in rows
        ]

    def mark_auto_replayed(self, ids: Sequence[int], now: datetime.datetime) -> None:
        """Catat satu percobaan otomatis untuk `ids` (caller yang commit)."""
        if not ids:
            return
        self.session.execute(
            update(RejectedArticle)
            .where(RejectedArticle.id.in_(ids))
            .values(
                auto_replay_count=RejectedArticle.auto_replay_count + 1,
                last_auto_replay_at=now,
            )
        )


class AsyncRejectedArticleRepo:
    """Async -- dipakai `apps/api` (Fase 7.3, router `filtered_articles.py`).
    Permukaan BACA + `restore()` doang -- jalur TULIS baru tetap
    `RejectedArticleRepo` sync di atas (Celery task)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_filtered(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        kind: str = "all",
    ) -> tuple[list[RejectedArticle], int]:
        """`kind`: `unrelated` (ditolak klasifikasi), `failed` (enrichment gagal) atau `all`."""
        stmt = select(RejectedArticle)
        if kind == "failed":
            stmt = stmt.where(RejectedArticle.failure_kind.is_not(None))
        elif kind == "unrelated":
            stmt = stmt.where(RejectedArticle.failure_kind.is_(None))
        if search:
            stmt = stmt.where(
                or_(
                    RejectedArticle.title.ilike(f"%{search}%"),
                    RejectedArticle.source.ilike(f"%{search}%"),
                )
            )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        list_stmt = (
            stmt.order_by(RejectedArticle.rejected_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().all()), total

    async def get_by_id(self, rejected_id: int) -> RejectedArticle | None:
        result = await self.session.execute(
            select(RejectedArticle).where(RejectedArticle.id == rejected_id)
        )
        return result.scalar_one_or_none()

    async def restore(self, rejected: RejectedArticle, article_repo: AsyncArticleRepo) -> Article:
        """Port `restore_filtered_article()` -- kalau artikel udah ADA
        (by URL), gak disentuh, apa adanya (legacy juga gak nimpa yang
        udah ada, `find_one` check terus `return True` doang). BUKAN
        `upsert()` biasa -- `upsert()` bakal NIMPA artikel asli yang udah
        diterima normal kalau kebetulan url_hash sama, itu salah."""
        existing = await article_repo.get_by_url(rejected.url)
        if existing is not None:
            return existing
        return await article_repo.upsert(
            url=rejected.url,
            title=rejected.title,
            source=rejected.source,
            posted_on=rejected.posted_on,
            news_type="Manually Restored",
        )
