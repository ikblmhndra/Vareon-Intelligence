"""Artikel -- rekaman utama scraper.

Menggantikan `news_db.articles` (dokumen Mongo). Perbedaan disengaja dari
bentuk lama, sesuai plan §3/§5.6:

  - `confidence_score` SATU kolom, bukan `confidence` (scraper) vs
    `confidence_score` (web) yang dulu dua field beda maksud sama.
  - `url_hash` unique constraint ADALAH kebenaran dedup -- bukan lagi
    `is_new_and_mark(script, title+url)` yang gak dinormalisasi.
  - `overrides` (JSONB): field yang ditulis analis lewat web gak pernah
    ketimpa scraper. Baca lewat repository, bukan langsung ke kolom
    aslinya -- lihat ArticleRepo.
  - Array Mongo (impacted_industries, mentioned_countries+peran,
    threat_actors, ttps) dinormalisasi jadi baris, BUKAN Postgres
    ARRAY -- supaya bisa di-query/index per nilai (mis. "semua artikel
    yang nyebut Indonesia sebagai victim"). Sejak P7c barisnya
    `entity_mentions` -> `entities` (relasi `Article.mentions`); tabel
    link per-tipe lama tinggal view kompatibilitas tanpa model ORM.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin
from cti_core.db.models.entity import EntityMention, live_entity_names, live_mentions


class Article(TimestampMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        CheckConstraint("credibility BETWEEN 1 AND 6", name="credibility_range"),
        Index("ix_articles_priority_score", text("priority_score DESC NULLS LAST")),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    """sha256(canonicalize_url(url)) -- lihat cti_core.urlkit. Ini kebenaran
    dedup, bukan sekadar kolom pendukung."""

    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    posted_on: Mapped[datetime.date | None] = mapped_column(Date)

    scraper_id: Mapped[str | None] = mapped_column(String(100), index=True)
    """Slug ScraperMeta.id (Fase 3). Nullable -- artikel hasil migrasi data
    lama gak semuanya bisa dipetakan balik ke scraper_id baru."""

    news_type: Mapped[str | None] = mapped_column(String(50), index=True)
    """Hasil keputusan routing (cti_enrich.routing.route()), mis.
    "zero_day", "apac", "best_practice". Lihat plan §6.3."""

    confidence_score: Mapped[int | None] = mapped_column(SmallInteger)
    """0-100. SATU kolom -- lihat docstring modul."""
    reliability_grade: Mapped[str | None] = mapped_column(String(1))
    """Snapshot grade sumber (A-F) saat artikel dinilai (P6 spec 3.1)."""
    credibility: Mapped[int | None] = mapped_column(SmallInteger)
    """1-6 hasil tangga aturan `cti_core.confidence.assess`. NULL = belum dinilai (spec 3.1)."""
    priority_score: Mapped[int | None] = mapped_column(SmallInteger)
    """Skor prioritas untuk ranking: `confidence_score` + poin dampak (maks 76), jadi TIDAK
    dibatasi 100 (indeks `priority_score DESC NULLS LAST`)."""
    score_reasons: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    """Alasan penilaian: `{"credibility": [kode...], "priority": [{"code", "points"}...]}`."""
    confirmed_incident: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    incident_confidence: Mapped[int | None] = mapped_column(SmallInteger)
    victim_name: Mapped[str | None] = mapped_column(String(300))
    c2_indicator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Berapa kali URL yang sama ke-scrape ulang (re-crawl feed)."""
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    raw_enrichment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Payload cair: output LLM mentah, hasil ekstraksi TTP/IOC sebelum
    dinormalisasi ke tabel anak. Cadangan/audit trail, BUKAN sumber baca --
    field yang perlu di-query harus dinormalisasi ke kolom/tabel asli."""

    overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Field yang ditimpa analis lewat web (mis. confidence_score, news_type
    hasil koreksi manual). Repository yang gabungin ini ke hasil baca --
    lihat ArticleRepo.to_dict(). Scraper/enrichment CUMA nulis kolom asli,
    gak pernah nyentuh ini."""

    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    story_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("stories.id", ondelete="SET NULL"), index=True
    )
    """Story (kelompok berita sama) tempat artikel ini bergabung; NULL = belum/tanpa story."""
    story_match: Mapped[str | None] = mapped_column(String(20))
    """Aturan yang menautkan: `lead`, `cve`, `title_exact`, `title`, `title_embedding`."""

    mentions: Mapped[list[EntityMention]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="EntityMention.id"
    )
    """Sebutan entitas (P7c): negara, sektor, aktor, malware/tool, teknik, CVE. Ditulis lewat
    `ArticleRepo` (Core INSERT), bukan append ke list ini. Pengganti relasi link lama
    (`countries`/`industries`/`threat_actors`/`ttps`/`malware`, dihapus di Task 12).

    `selectin` (bukan `raise_on_sql`): hampir semua pembaca ORM artikel (list/detail artikel,
    PIR, newsletter, campaign, recap, STIX, dedup) menampilkan mention, dan satu SELECT IN per
    batch artikel (entitas ikut lewat `joined`) menggantikan LIMA selectin relasi lama -- jadi
    tidak ada N+1 dan beban per load turun. Pembaca agregat memakai `mention_rows()` SQL."""

    def mentions_of(self, *types: str) -> list[EntityMention]:
        """Mention ke entitas hidup (tidak suppressed, bukan tombstone) bertipe `types`
        (kosong = semua), urut id mention. `identity` hanya sektor (kelas `class`), sama dengan
        `repositories.entity.mention_rows`."""
        return live_mentions(self.mentions, types)

    def entity_names(self, *types: str) -> list[str]:
        """Nama entitas (kanonik) dari `mentions_of`, tanpa duplikat, urut id mention."""
        return live_entity_names(self.mentions, types)

    def country_codes(self, role: str | None = None) -> list[str]:
        """Kode ISO alpha-2 (`external_id`) negara yang disebut, tanpa duplikat, urut id mention;
        `role` (victim | actor | mentioned) menyaring per peran, None = peran apa pun."""
        return list(
            dict.fromkeys(
                m.entity.external_id
                for m in self.mentions_of("location")
                if m.entity.external_id and (role is None or m.role == role)
            )
        )


class CountryRole(str):
    """Peran negara di mention `location` (`entity_mentions.role`). Bukan Enum Python biasa --
    dicek di aplikasi, bukan Postgres CHECK; didokumentasikan di sini sebagai daftar nilai sah."""

    VICTIM = "victim"
    ACTOR = "actor"
    MENTIONED = "mentioned"


class RejectedArticle(Base):
    """Log artikel yang DITOLAK `cti_enrich.pipeline.run_pipeline()`
    (`classify_result.related_cyber == False`) -- gantiin `filtered_articles_
    service.py` lama yang baca `scraper_runs.accepted == False` (Mongo).

    BARU di Fase 7.3 (router `filtered_articles.py`) -- tabel ini gak ada
    di skema Fase 5 sama sekali (`persist.py` cuma nulis artikel yang
    DITERIMA). Router lama ini ditemuin butuh tabel baru pas porting,
    bukan sekadar nambah kolom -- keputusan eksplisit user (lihat
    docs/PROGRESS.md) buat bikin tabel ini + wire ke pipeline, bukan skip.

    `reason` (alasan LLM classify nolak artikel ini) TERSEDIA sekarang
    (`ClassifyResult.reason`) -- legacy gak punya ini sama sekali (Mongo
    `scraper_runs` cuma nyimpen boolean `accepted`), jadi field ini genuinely
    LEBIH KAYA dari yang lama, bukan port 1:1."""

    __tablename__ = "rejected_articles"
    __table_args__ = (UniqueConstraint("url_hash", name="uq_rejected_articles_url_hash"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """sha256(canonicalize_url(url)) -- sama fungsi `cti_core.urlkit.url_hash`
    yang dipakai `Article.url_hash`, biar dedup konsisten (feed yang sama
    nolak artikel yang sama berkali-kali gak numpuk baris)."""
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scraper_id: Mapped[str | None] = mapped_column(String(100), index=True)
    posted_on: Mapped[datetime.date | None] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text)
    failure_kind: Mapped[str | None] = mapped_column(String(30))
    """NULL = ditolak klasifikasi LLM (`reason` = alasan LLM). Selain itu enrichment GAGAL dan
    artikelnya belum diproses: `transient` (retry habis), `json` (JSON rusak terus), `config`
    (400/401/403/404 dari gateway; ikut replay otomatis), `permanent` (kuota/bug lain, tidak
    diputar ulang otomatis). Validasi di aplikasi, tanpa CHECK (seperti `daily_recaps.kind`). Prefix
    `[enrichment_failed]` di `reason` tetap ditulis satu rilis supaya worker lama tetap terbaca."""
    auto_replay_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    """Berapa kali beat mencoba ulang otomatis artikel yang gagal di-enrich (batas 3). Tidak
    disentuh `RejectedArticleRepo.upsert` supaya hitungan bertahan lintas kegagalan."""
    last_auto_replay_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    """Waktu percobaan otomatis terakhir; dasar backoff `30 menit * 2 ** auto_replay_count`."""
    rejected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    raw_enrichment: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Audit trail respons LLM klasifikasi mentah (`ClassifyResult.audit`); bukan sumber baca."""
