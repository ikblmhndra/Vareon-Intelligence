"""Schema `GET /api/data-health` (ROADMAP #24 PR-B). Bertipe penuh (tanpa `dict[str, object]`)
supaya `schema.d.ts` di web ikut ketat."""

from __future__ import annotations

from pydantic import BaseModel

from cti_api.schemas.scraper import ScraperHealthSummary


class EnrichmentHealthOut(BaseModel):
    failed_24h: int
    failed_7d: int
    processed_7d: int
    """Diterima + ditolak + gagal dalam 7 hari: penyebut `failed_7d`."""
    pending_replay: int
    """Baris `rejected_articles` yang gagal di-enrich dan belum di-replay (semua umur)."""
    last_failure_at: str | None


class QueueHealthOut(BaseModel):
    enrich_depth: int | None
    """`LLEN enrich` di broker; `None` kalau Redis tidak bisa dibaca."""
    enrich_max_depth: int
    """`scraper.enrich_queue_max_depth`: di titik ini sink artikel menolak item (backpressure)."""


class SourceFreshnessOut(BaseModel):
    articles_newest_at: str | None
    tweets_newest_at: str | None
    iocs_newest_at: str | None


class IocEnrichmentTypeOut(BaseModel):
    type: str
    total: int
    enriched: int
    """Punya minimal satu kartu provider yang benar-benar dicek (bukan `skipped`)."""


class DataHealthOut(BaseModel):
    generated_at: str
    """ISO UTC saat angka dihitung (cache 60 detik per proses)."""
    scrapers: ScraperHealthSummary
    enrichment: EnrichmentHealthOut
    queues: QueueHealthOut
    sources: SourceFreshnessOut
    ioc_enrichment: list[IocEnrichmentTypeOut]
