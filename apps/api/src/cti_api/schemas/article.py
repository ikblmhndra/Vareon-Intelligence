"""Adaptasi dari `ScraperNewsWeb/app/models/article.py` -- `id` sekarang
`int` (Postgres bigint autoincrement), BUKAN `str` (Mongo ObjectId hex).
`iocs` SENGAJA selalu `{}` buat sekarang -- linkage artikel<->IOC belum
diport (router `iocs.py`, nyusul terpisah), placeholder daripada nebak
bentuknya sekarang."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TTP(BaseModel):
    id: str
    name: str
    source: Literal["explicit", "keyword", "llm"] = "llm"
    """Asal TTP: `explicit` (ID disebut artikel), `keyword` (kamus Tier 1), `llm`."""
    evidence: str | None = None
    """Kalimat bukti (Tier 1); `None` kalau tidak ada."""


class MalwareRef(BaseModel):
    name: str
    kind: Literal["malware", "tool"]


class InferredTechnique(BaseModel):
    id: str
    name: str


class InferredEntity(BaseModel):
    """Aktor/malware artikel yang cocok di ATT&CK beserta teknik yang DIPAKAI-nya menurut
    ATT&CK. Tidak disimpan (tidak ada `source`): ini inferensi, bukan isi artikel."""

    entity: str
    kind: Literal["actor", "malware", "tool"]
    attack_id: str
    techniques: list[InferredTechnique]


class StoryRef(BaseModel):
    """Story (kelompok berita sama) tempat artikel bergabung."""

    id: int
    article_count: int
    source_count: int


class PriorityReason(BaseModel):
    code: str
    points: int


class ScoreReasons(BaseModel):
    """Alasan penilaian artikel (P6 3.1): kode kredibilitas + rincian poin prioritas."""

    credibility: list[str] = []
    priority: list[PriorityReason] = []


class CredibilityOverrideIn(BaseModel):
    """`credibility=None` menghapus override (kembali ke hasil hitung)."""

    credibility: int | None = Field(None, ge=1, le=6)
    note: str = Field("", max_length=500)


class ArticleOut(BaseModel):
    id: int
    year: int = 0
    month: str = ""
    week: str = ""
    title: str = ""
    url: str = ""
    posted_on: str = ""
    source: str = ""
    impacted_industries: list[str] = []
    mentioned_countries: list[str] = []
    victim_countries: list[str] = []
    actor_countries: list[str] = []
    threat_actors: list[str] = []
    ttps: list[TTP] = []
    malware: list[MalwareRef] = []
    industry_source: Literal["llm", "keyword"] | None = None
    """Asal industri (dari baris industri pertama); `None` kalau tidak ada baris."""
    news_type: str = ""
    confidence_score: int | None = None
    # P6: `admiralty_code` = kode ARTIKEL (`reliability_grade` + `credibility`, mis. "B2");
    # `None` = belum dinilai. `grade_origin` tetap asal grade SOURCE (baris rating).
    admiralty_code: str | None = None
    grade_origin: Literal["default", "analyst"] | None = None
    reliability_grade: str | None = None
    credibility: int | None = None
    priority_score: int | None = None
    score_reasons: ScoreReasons = ScoreReasons()
    iocs: dict[str, object] = {}
    confirmed_incident: bool = False
    story: StoryRef | None = None
    classify_inherited_from: int | None = None
    """Id artikel lead kalau klasifikasi artikel ini diwarisi dari story-nya (audit classify)."""


class FilterOptions(BaseModel):
    industries: list[str]
    countries: list[str]
    sources: list[str]
    news_types: list[str]
    threat_actors: list[str]
    date_range: dict[str, str]


class ArticleListResponse(BaseModel):
    articles: list[ArticleOut]
    total: int
    page: int
    page_size: int


class TopItem(BaseModel):
    name: str
    count: int


class TimelinePoint(BaseModel):
    date: str
    count: int
    incidents: int = 0


class DashboardCoverage(BaseModel):
    """Jumlah ARTIKEL yang punya minimal satu negara / threat actor / TTP --
    penyebut buat chart dashboard (bandingkan dengan `total_articles`)."""

    with_country: int
    with_actor: int
    with_ttp: int


class DashboardStats(BaseModel):
    total_articles: int
    total_sources: int
    total_countries: int
    total_threat_actors: int
    confirmed_incidents: int
    # `None` kalau tanpa `days` (all-time): gak ada periode sebelumnya buat dibandingkan.
    prev_total_articles: int | None
    prev_confirmed_incidents: int | None
    # False = periode sebelumnya kosong/jarang (< separuh harinya berartikel) atau all-time:
    # UI menulis "no prior-period data" alih-alih delta (aturan yang sama dengan Exec).
    prev_period_reliable: bool
    # Artikel berlabel industri "General" (gak punya sektor spesifik); sengaja
    # TIDAK ada di `top_industries` supaya bar teratas gak selalu "General".
    industry_unspecified: int
    coverage: DashboardCoverage
    # ISO UTC saat angka ini dihitung (cache 15 menit, jadi bukan "sekarang").
    generated_at: str
    top_countries: list[TopItem]
    # Semua negara (bukan cuma top-10) -- dipakai peta dunia di dashboard.
    country_counts: list[TopItem]
    top_sources: list[TopItem]
    top_threat_actors: list[TopItem]
    top_industries: list[TopItem]
    top_ttps: list[TopItem]
    by_news_type: list[TopItem]
    timeline: list[TimelinePoint]
