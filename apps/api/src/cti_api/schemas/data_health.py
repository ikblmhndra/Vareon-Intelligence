"""Schema `GET /api/data-health` (ROADMAP #24 PR-B). Bertipe penuh (tanpa `dict[str, object]`)
supaya `schema.d.ts` di web ikut ketat."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from cti_api.schemas.scraper import ScraperHealthSummary


class EnrichmentHealthOut(BaseModel):
    failed_24h: int
    """Job `failed` yang DIBUAT dalam 24 jam (tabel tanpa cap waktu gagal): angka snapshot."""
    failed_7d: int
    """Sama, jendela 7 hari."""
    processed_7d: int
    """Diterima + ditolak + gagal dalam 7 hari: penyebut `failed_7d`."""
    pending_replay: int
    """Job `enrich_jobs` `failed` (menunggu analis), semua umur; nama lama dipertahankan."""
    last_failure_at: str | None


class PipelineWindowOut(BaseModel):
    items_found: int
    """Jumlah `items_found` semua run scraper yang dimulai dalam jendela (semua status)."""
    items_new: int
    articles_published: int
    """Artikel dengan `first_seen_at` dalam jendela."""


class PipelineHealthOut(BaseModel):
    last_24h: PipelineWindowOut
    last_7d: PipelineWindowOut


class QueueHealthOut(BaseModel):
    depths: dict[str, int] | None
    """`LLEN` tiap queue Celery (hanya pesan yang menunggu; task yang sudah di-reserve belum di-ack
    tidak ada di list). `None` kalau Redis tidak bisa dibaca."""
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


class LlmErrorOut(BaseModel):
    at: str
    task: str
    error_type: str | None
    http_status: int | None


class LlmQueueOut(BaseModel):
    """Antrean kerja LLM (`enrich_jobs`) dan circuit breaker-nya (P7g)."""

    breaker: Literal["closed", "open", "half_open"]
    retry_at: str | None
    """Akhir cooldown breaker; `None` saat tertutup."""
    pending_classify: int
    pending_ttp: int
    failed: int
    oldest_pending_at: str | None


class LlmTaskUsageOut(BaseModel):
    task: str
    calls: int
    errors: int
    """Baris berstatus `error` atau `empty`."""
    prompt_tokens: int | None
    completion_tokens: int | None
    """`None` kalau tidak ada baris task ini yang melaporkan token."""
    median_latency_ms: int | None
    prompt_version: str | None


class StoryHealthOut(BaseModel):
    new_stories: int
    """Story yang mulai dalam jendela dan sudah punya artikel."""
    followups: int
    """Artikel yang menempel ke story yang sudah ada (match cve/judul) dalam jendela."""
    inherited: int
    """Dari follow-up itu, yang mewarisi classify story (tanpa panggilan LLM classify)."""
    llm_calls_avoided: int
    """Perkiraan panggilan LLM yang dihemat: inherited x 2 (classify + ekstraksi TTP)."""
    by_embedding: int
    """Artikel yang menempel ke story lewat aturan judul-embedding (`title_embedding`)."""


class LlmHealthOut(BaseModel):
    status: Literal["ok", "failing", "unknown"]
    """Panggilan terbaru task classify/ttp: ok -> ok, error/empty -> failing, kosong -> unknown."""
    last_call_at: str | None
    last_ok_at: str | None
    last_error: LlmErrorOut | None
    queue: LlmQueueOut
    usage_24h: list[LlmTaskUsageOut]
    usage_7d: list[LlmTaskUsageOut]
    stories_24h: StoryHealthOut
    stories_7d: StoryHealthOut


class RelevanceHealthOut(BaseModel):
    """Model relevansi lokal (P5). `None` = belum ada data (tanpa model aktif / penyebut nol)."""

    mode: Literal["off", "shadow", "auto"]
    gate_state: Literal["shadow", "gate"] | None
    """Status gate di baris model aktif; `None` tanpa model aktif."""
    gate_changed_at: str | None
    model_trained_at: str | None
    n_examples: int | None
    holdout_agreement: float | None
    holdout_band_share: float | None
    band_titles_14d: int
    """Judul dalam band dengan vonis LLM (keputusan shadow/audit) dalam jendela gate."""
    band_agreement_14d: float | None
    middle_band_14d: int
    """Baris dengan skor di luar band dalam jendela itu (selalu ke LLM)."""
    audit_samples: int
    audit_agreement: float | None
    """Kesepakatan pada `revert_samples` sampel audit terakhir."""
    classify_avoided_24h: int
    classify_avoided_7d: int


class SigmaHealthOut(BaseModel):
    """Snapshot SigmaHQ (P7e). `red` = 0 aturan; `amber` = snapshot >60 hari atau `last_error`."""

    release: str | None
    rules: int
    fetched_at: str | None
    last_error: str | None
    status: Literal["ok", "amber", "red"]


class CveIngestHealthOut(BaseModel):
    """Ingest CVE dari mirror V5. `off` = mirror mati; `red` = poll terakhir hilang/>15 menit;
    `amber` = rekonsiliasi belum ada, >2 jam, atau terakhir `status == "error"`."""

    enabled: bool
    promote: str
    last_sync_at: str | None
    pending: int
    last_reconcile_at: str | None
    last_reconcile: dict[str, int | str] | None
    status: Literal["ok", "amber", "red", "off"]


class DataHealthOut(BaseModel):
    generated_at: str
    """ISO UTC saat angka dihitung (cache 60 detik per proses)."""
    scrapers: ScraperHealthSummary
    enrichment: EnrichmentHealthOut
    pipeline: PipelineHealthOut
    queues: QueueHealthOut
    sources: SourceFreshnessOut
    ioc_enrichment: list[IocEnrichmentTypeOut]
    llm: LlmHealthOut
    relevance: RelevanceHealthOut
    sigma: SigmaHealthOut
    cve_ingest: CveIngestHealthOut
