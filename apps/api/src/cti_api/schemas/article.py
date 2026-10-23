"""Adaptasi dari `ScraperNewsWeb/app/models/article.py` -- `id` sekarang
`int` (Postgres bigint autoincrement), BUKAN `str` (Mongo ObjectId hex).
`iocs` SENGAJA selalu `{}` buat sekarang -- linkage artikel<->IOC belum
diport (router `iocs.py`, nyusul terpisah), placeholder daripada nebak
bentuknya sekarang."""

from __future__ import annotations

from pydantic import BaseModel


class TTP(BaseModel):
    id: str
    name: str


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
    news_type: str = ""
    confidence_score: int | None = None
    iocs: dict[str, object] = {}


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
