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
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from sqlalchemy import Select, func, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased, object_session

from cti_core.attack_ttp import NormalizedTTP
from cti_core.db.models.article import (
    Article,
    ArticleCountry,
    ArticleIndustry,
    ArticleThreatActor,
    ArticleTTP,
    RejectedArticle,
)
from cti_core.enrich_replay import BACKOFF_BASE, MAX_ATTEMPTS, ReplayCandidate
from cti_core.entity.mentions import (
    ARTICLE_MENTION_ATTRS,
    MentionInput,
    country_mention,
    delete_other_mentions,
    insert_mentions,
    mention_rows,
    resolve_mention,
    resolve_mention_async,
    sector_mention,
    touch_seen_stmt,
)
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
    ttp_sources: Sequence[str] | None = None,
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
    if ttps or ttp_sources:
        # Satu join: ID dan sumber harus cocok pada BARIS TTP yang sama.
        stmt = stmt.join(Article.ttps)
        if ttps:
            stmt = stmt.where(ArticleTTP.ttp_id.in_(ttps))
        if ttp_sources:
            stmt = stmt.where(ArticleTTP.source.in_(ttp_sources))
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

EntityAliases = Mapping[str, str]
"""Nama huruf kecil -> teks yang cocok (hit Tier 1), supaya mention menyimpan alias yang
benar-benar muncul di teks (`matched_alias`, split eksak). Entitas tetap di-resolve lewat nama
yang dikirim (bentuk simpan `capitalize()` untuk nama baru, sama seperti v1)."""

ENRICHMENT_TYPES = ("location", "identity", "intrusion-set", "malware", "tool", "attack-pattern")
"""Tipe entitas yang diganti utuh oleh `set_enrichment`; CVE ditulis `ArticleCveRepo`."""


def _first_ttps(ttps: Sequence[TTPInput]) -> dict[str, NormalizedTTP]:
    """DEDUP PER `ttp_id`, nama pertama menang: LLM kadang mengembalikan ID yang SAMA dua kali
    dengan nama beda ("T1176" -> "Browser Extensions" & "Software Extensions"); tanpa ini
    artikel bisa gagal tersimpan (e2e staging Fase 10)."""
    first_per_id: dict[str, NormalizedTTP] = {}
    for t in ttps:
        n = t if isinstance(t, NormalizedTTP) else NormalizedTTP(t[0], t[1])
        first_per_id.setdefault(n.ttp_id, n)
    return first_per_id


def _ttp_hits(ttps: Sequence[TTPInput]) -> list[MentionInput]:
    """Teknik -> mention `attack-pattern` lewat id teknik (Ruling 7); teks asli LLM ke
    `extracted`, kalimat bukti ke `evidence`."""
    hits: list[MentionInput] = []
    for tid, n in _first_ttps(ttps).items():
        _check(n.source, _TTP_SOURCES, "ttp source")
        raw = {"extracted_id": n.extracted_id, "extracted_name": n.extracted_name}
        extracted = {k: v for k, v in raw.items() if v is not None} or None
        hits.append(
            MentionInput(
                "attack-pattern",
                n.ttp_name,
                n.source,
                tid,
                evidence=n.evidence,
                extracted=extracted,
                external_id=tid,
            )
        )
    return hits


def _matched(name: str, aliases: EntityAliases) -> str:
    return aliases.get(name.lower(), name)


def _actor_hits(names: Iterable[str], aliases: EntityAliases) -> list[MentionInput]:
    hits = []
    for name in dict.fromkeys(names):
        hits.append(MentionInput("intrusion-set", name, "dictionary", _matched(name, aliases)))
    return hits


def _malware_hits(malware: Sequence[tuple[str, str]], aliases: EntityAliases) -> list[MentionInput]:
    # nama sama beda kind: yang pertama menang (sama seperti kunci unik lama per nama)
    kinds: dict[str, str] = {}
    for name, kind in malware:
        _check(kind, _MALWARE_KINDS, "malware kind")
        kinds.setdefault(name, kind)
    hits = []
    for name, kind in kinds.items():
        hits.append(MentionInput(kind, name, "dictionary", _matched(name, aliases)))
    return hits


def _sector_hits(industries: Iterable[str], method: str) -> list[MentionInput]:
    return [h for label in dict.fromkeys(industries) if (h := sector_mention(label, method))]


def _enrichment_hits(
    *,
    countries: Sequence[tuple[str, str]],
    industries: Sequence[str],
    threat_actors: Sequence[str],
    ttps: Sequence[TTPInput],
    malware: Sequence[tuple[str, str]],
    industry_source: str,
    aliases: EntityAliases,
) -> list[MentionInput]:
    """Hasil satu enrichment -> mention. Negara datang dari classify LLM (+ NER regex untuk role
    `mentioned`); semua dicatat method `llm` karena role-nya ditentukan dari jawaban LLM."""
    _check(industry_source, _INDUSTRY_SOURCES, "industry_source")
    countries_hits = [
        h for code, role in dict.fromkeys(countries) if (h := country_mention(code, role, "llm"))
    ]
    return [
        *countries_hits,
        *_sector_hits(industries, industry_source),
        *_actor_hits(threat_actors, aliases),
        *_malware_hits(malware, aliases),
        *_ttp_hits(ttps),
    ]


def apply_ttps(article: Article, ttps: Sequence[TTPInput]) -> None:
    """Ganti mention teknik artikel dengan `ttps` (yang tidak ada lagi dihapus, yang ada
    diperbarui method/bukti). Dipakai remap TTP (`ttp_catalog.remap_article_ttps`)."""
    session = object_session(article)
    if not isinstance(session, Session):
        raise ValueError("apply_ttps butuh artikel yang terikat ke Session sync")
    ArticleRepo(session).replace_mentions(article, _ttp_hits(ttps), ("attack-pattern",))


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
        aliases: EntityAliases | None = None,
    ) -> Article:
        """Ganti SEMUA mention negara/sektor/aktor/malware/teknik artikel dari SATU hasil
        enrichment (pipeline, `cti_enrich.stages.persist`). `countries`: `(kode ISO alpha-2,
        role)`, role `victim|actor|mentioned`. `ttps`: `(ttp_id, ttp_name)` atau `NormalizedTTP`
        (normalisasi ke katalog ATT&CK tugas CALLER). `aliases`: lihat `EntityAliases`.

        Nama di-resolve ke entitas (P7c, spec 4.3); hasil terbaru = kebenaran: mention bertipe
        `ENRICHMENT_TYPES` yang tidak ada lagi dihapus, yang tetap diperbarui (method, alias,
        bukti), idempoten saat replay. Dua ejaan satu entitas = satu mention (ejaan pertama)."""
        hits = _enrichment_hits(
            countries=countries,
            industries=industries,
            threat_actors=threat_actors,
            ttps=ttps,
            malware=malware,
            industry_source=industry_source,
            aliases=aliases or {},
        )
        self.replace_mentions(article, hits, ENRICHMENT_TYPES)
        return article

    def replace_mentions(
        self, article: Article, hits: Sequence[MentionInput], types: Sequence[str]
    ) -> None:
        """Mention artikel bertipe `types` dibuat persis `hits` (lihat `set_enrichment`)."""
        self.session.flush()
        rows = mention_rows(
            {"article_id": article.id}, [(h, resolve_mention(self.session, h)) for h in hits]
        )
        keep = [(r["entity_id"], r["role"]) for r in rows]
        self.session.execute(delete_other_mentions(article.id, types, keep))
        if rows:
            self.session.execute(insert_mentions(rows, update=True))
        self.session.flush()
        self.session.expire(article, ARTICLE_MENTION_ATTRS)

    def add_mentions(self, article: Article, hits: Iterable[MentionInput]) -> int:
        """ADD-ONLY dan idempoten (`ON CONFLICT DO NOTHING` di kunci unik mention): mention yang
        sudah ada tidak diubah. Return jumlah mention baru."""
        self.session.flush()
        rows = mention_rows(
            {"article_id": article.id}, [(h, resolve_mention(self.session, h)) for h in hits]
        )
        added = len(self.session.execute(insert_mentions(rows, update=False)).all()) if rows else 0
        self.session.flush()
        self.session.expire(article, ARTICLE_MENTION_ATTRS)
        return added

    def touch_entity_seen(self, article: Article) -> None:
        """`first_seen`/`last_seen` entitas yang disebut artikel, satu statement (spec 4.3)."""
        stmt, params = touch_seen_stmt(article.id)
        self.session.execute(stmt, params)

    def add_tier1(
        self,
        article: Article,
        *,
        ttps: Sequence[NormalizedTTP],
        threat_actors: Sequence[str],
        malware: Sequence[tuple[str, str]],
        industries: Sequence[str],
    ) -> dict[str, int]:
        """ADD-ONLY untuk backfill Tier 1: mention yang ada tidak pernah diubah/dihapus (teknik
        LLM tetap; teknik keyword dengan ID sama, atau aktor yang alias-nya sudah tersebut, tidak
        ditambah karena resolve ke entitas yang sama). Sektor `keyword` hanya ditambah kalau
        artikel belum punya sektor sama sekali (dulu: industri persis `["General"]`; "General"
        kini tidak menghasilkan mention) -- sektor dari LLM tidak boleh ditimpa tebakan keyword.
        Return jumlah mention baru per jenis."""
        no_sector = not article.mentions_of("identity")
        return {
            "ttps": self.add_mentions(article, _ttp_hits(ttps)),
            "threat_actors": self.add_mentions(article, _actor_hits(threat_actors, {})),
            "malware": self.add_mentions(article, _malware_hits(malware, {})),
            "industries": (
                self.add_mentions(article, _sector_hits(industries, "keyword")) if no_sector else 0
            ),
        }

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
        aliases: EntityAliases | None = None,
    ) -> Article:
        """Logic sama persis `ArticleRepo.set_enrichment` -- dipakai test integrasi (setup
        fixture artikel lewat jalur async). Relasi baca di-`refresh()` sesudah tulis: lazy-load
        implisit tidak bisa jalan di sesi async (`MissingGreenlet`)."""
        hits = _enrichment_hits(
            countries=countries,
            industries=industries,
            threat_actors=threat_actors,
            ttps=ttps,
            malware=malware,
            industry_source=industry_source,
            aliases=aliases or {},
        )
        await self.session.flush()
        rows = mention_rows(
            {"article_id": article.id},
            [(h, await resolve_mention_async(self.session, h)) for h in hits],
        )
        keep = [(r["entity_id"], r["role"]) for r in rows]
        await self.session.execute(delete_other_mentions(article.id, ENRICHMENT_TYPES, keep))
        if rows:
            await self.session.execute(insert_mentions(rows, update=True))
        await self._reload(article)
        return article

    async def add_mentions(self, article: Article, hits: Iterable[MentionInput]) -> int:
        """Kembaran async `ArticleRepo.add_mentions`."""
        await self.session.flush()
        rows = mention_rows(
            {"article_id": article.id},
            [(h, await resolve_mention_async(self.session, h)) for h in hits],
        )
        added = 0
        if rows:
            added = len((await self.session.execute(insert_mentions(rows, update=False))).all())
        await self._reload(article)
        return added

    async def _reload(self, article: Article) -> None:
        await self.session.flush()
        await self.session.refresh(article, attribute_names=list(ARTICLE_MENTION_ATTRS))

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
        ttp_sources: Sequence[str] | None = None,
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

        `sort="priority"` (newsroom/dashboard "Perlu dibaca", P6 spec 5.2): urut
        `priority_score` (NULL terakhir), lalu terbaru, lalu id; `confirmed_incident` bukan kunci
        pertama lagi karena sudah +25 di dalam priority. SATU artikel per story (kunci
        `coalesce(story_id, -id)`, artikel tanpa story jadi grupnya sendiri): anggota dengan
        priority tertinggi yang tampil, sisanya diwakili badge "+N sources" (P3). Tanpa ini
        top 10 minggu 19-26 Okt di dev isinya PHP2Shell semua. `total` menghitung baris yang
        sudah diciutkan, biar paginasi cocok. Diciutkan lewat `row_number()` atas himpunan id
        yang sudah difilter (`IN (subquery)`), bukan `DISTINCT ON`: `DISTINCT ON` bentrok
        dengan `.distinct()` jalur join dan memaksa ORDER BY diawali kunci grup.
        Default "recent" = urutan lama, tanpa penciutan. `confirmed_only` membatasi ke
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
            ttp_sources=ttp_sources,
        )
        has_join = bool(
            industries
            or countries
            or victim_countries
            or actor_countries
            or threat_actors
            or ttps
            or ttp_sources
        )

        if sort == "priority":
            order = (
                Article.priority_score.desc().nulls_last(),
                Article.posted_on.desc().nulls_last(),
                Article.id.desc(),
            )
            # Filter (termasuk join) cukup lewat `IN`: duplikat dari join one-to-many hilang
            # sendiri, jadi tidak perlu `.distinct()` di sini.
            rank = (
                select(
                    Article.id,
                    func.row_number()
                    .over(
                        partition_by=func.coalesce(Article.story_id, -Article.id),
                        order_by=order,
                    )
                    .label("rn"),
                )
                .where(Article.id.in_(base.with_only_columns(Article.id)))
                .subquery()
            )
            kept_ids = select(rank.c.id).where(rank.c.rn == 1)
            count_stmt = select(func.count()).select_from(kept_ids.subquery())
            total = (await self.session.execute(count_stmt)).scalar_one()
            list_stmt = select(Article).where(Article.id.in_(kept_ids)).order_by(*order)
        else:
            count_stmt = select(func.count()).select_from(base.distinct().subquery())
            total = (await self.session.execute(count_stmt)).scalar_one()
            list_stmt = base.order_by(Article.posted_on.desc().nulls_last(), Article.id.desc())
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
        (seminggu bisa ribuan artikel, tiap baris menarik empat tabel anak lewat selectin).
        Urutan: `priority_score` (NULL terakhir; P6 spec 5.2, insiden terkonfirmasi sudah +25 di
        dalamnya), lalu terbaru. Tanpa penciutan per story: recap sudah mengelompokkan sendiri.
        Sinyal yang tidak ada di kolom (keandalan sumber, ukuran klaster) dipakai
        pemanggil untuk menyusun ulang kumpulan kandidat ini."""
        window = select(Article).where(Article.posted_on >= start, Article.posted_on <= end)
        total = (
            await self.session.execute(select(func.count()).select_from(window.subquery()))
        ).scalar_one()
        result = await self.session.execute(
            window.order_by(
                Article.priority_score.desc().nulls_last(),
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
