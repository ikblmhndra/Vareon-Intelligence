"""Control plane scraper -- lihat plan §8. Gantiin `scraper_health.py`
15-baris read-only yang gak bisa bedain scraper nol-item vs scraper crash.

Empat tabel:
  ScraperRun    -- SATU baris per eksekusi (heartbeat). Ini yang bikin
                   nol-item vs crash bisa dibedain, beda dari desain lama
                   yang nyatet per-artikel lewat worker.
  ScraperItem   -- SATU baris per artikel (accept/reject) dalam satu run.
                   `legacy_script_label` cuma buat kompat mundur ke
                   scraper_health_service lama, dihapus 1 rilis setelah
                   cutover (plan §8.5).
  ScraperConfig -- SATU-SATUNYA permukaan yang operator boleh tulis
                   (enable/disable/reschedule). Beat baca ini tiap refresh.
  ScraperSeen   -- dedup two-phase reserve/commit, gantiin
                   `threatintel.offsets`.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True, index=True)
    """UUID4 (36 char dgn hyphen) -- dikembaliin ke caller waktu trigger
    manual. Ketauan dari testing (bukan ditebak): draft pertama kolom ini
    String(30), padahal `uuid.uuid4()` di runner.py ngasilin 36 karakter --
    StringDataRightTruncation pas run pertama beneran ke Postgres."""
    scraper_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="beat")
    """beat | manual | retry."""
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    """ok | empty | partial | fetch_error | parse_error | rate_limited |
    timeout | backpressure | disabled. Dicek di level aplikasi, bukan
    Postgres CHECK constraint -- lihat catatan `CountryRole` (models/article.py)."""

    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    items_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_new: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_dropped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    celery_task_id: Mapped[str | None] = mapped_column(String(50))
    worker: Mapped[str | None] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ScraperItem(Base):
    __tablename__ = "scraper_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("scraper_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scraper_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """sha256(canonicalize_url(url)) -- SAMA nilainya kayak Article.url_hash,
    dipakai buat nyambungin run ke artikel yang beneran ke-simpan."""
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    legacy_script_label: Mapped[str | None] = mapped_column(String(200))
    """Push_job label lama, mis. "NEW ARTICLE FROM GBHACKER" -- kompat
    mundur ke scraper_health_service selama migrasi. Hapus 1 rilis setelah
    cutover, lihat plan §8.5."""
    run_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    expire_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    """`run_at + Settings.worker.scraper_item_retention_days` (Fase 9),
    dibersihin task Celery periodik `scraper.purge_expired_items` --
    tabel ini nyatet SEMUA item (accept+reject) 84 scraper, gak ada TTL
    index bawaan Postgres (sama keterbatasan kayak `ScraperSeen`)."""


class ScraperConfig(TimestampMixin, Base):
    __tablename__ = "scraper_config"

    scraper_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schedule: Mapped[str | None] = mapped_column(String(100))
    """Override cron ScraperMeta.schedule di kode -- null = pakai default kode."""
    rate_limit: Mapped[str | None] = mapped_column(String(30))
    max_items: Mapped[int | None] = mapped_column(Integer)
    paused_reason: Mapped[str | None] = mapped_column(Text)
    options: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    """Pilihan admin buat `ScraperMeta.options` (`{key: value}`, mis. `{"provider":
    "x_official"}`) -- null/kosong = semua opsi pakai default kode. Divalidasi API
    (`cti_scraper.options.validate_options`); `Runner` menolerir isi usang (lihat
    `resolve_options`)."""
    updated_by: Mapped[str | None] = mapped_column(String(200))


class ScraperSeen(Base):
    """Dedup two-phase reserve/commit -- gantiin `threatintel.offsets`.

    `dedup_key` BUKAN `cti_core.urlkit.url_hash()` -- itu identitas artikel
    LINTAS-scraper (dipakai di Article.url_hash). Di sini identitasnya
    per-scraper (dua scraper yang liput situs sama harus dedup terpisah,
    lihat plan §3.2), jadi hash-nya `sha256(scraper_id + key ternormalisasi)`
    dikomputasi `cti_scraper.dedup` (Fase 3) -- modul ini cuma nyimpen
    hasilnya.

    Postgres gak punya TTL index kayak Mongo `expireAfterSeconds` -- baris
    yang `expire_at`-nya lewat dibersihin task Celery periodik
    (Fase 6: cti.maintenance.purge_expired_seen), bukan otomatis dari DB.
    """

    __tablename__ = "scraper_seen"

    dedup_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scraper_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="in_flight")
    """in_flight | done."""
    lease_until: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    poisoned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Attempts kelewat batas -- item ini konsisten bikin sink gagal, jadi
    di-mark done tanpa diproses lagi supaya gak makan slot tiap run."""
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    committed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    expire_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
