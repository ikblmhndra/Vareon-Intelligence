"""CVE tracker -- gantiin `news_db.cve_tracker` + `cve_false_positives` +
`cve_tickets`. Ditulis dua sisi di sistem lama (scraper `newCveThreat.py`
dkk, web `cve_service.py`) -- lihat plan §1. Multi-tenant lewat `client_id`
(unique bareng `cve_id`), pola yang sama kayak app lama v3.8.0.

`active_exploitation`/`threat_actors`/`ttps` (Fase 7.3, router `crossref`,
Bagian 3) -- field ini ADA di dokumen Mongo `cve_tracker` lama, tapi
`threat_actors`/`ttps` KHUSUSNYA ditulis loop enrichment CVE
(`app/main.py::_cve_enrichment_loop`, cross-reference CVE vs artikel/TA)
yang BELUM diport -- salah satu dari 5 loop yang dipindah ke Celery beat
(Fase 7.8). Kolomnya ditambah pas porting `crossref`, buat sekarang
selalu kosong, cold-start biasa. `threat_actors`/`ttps` dinormalisasi
jadi tabel anak (`CveThreatActor`/`CveTTP`), sama pola kayak
`ArticleThreatActor`/`ArticleTTP`.

`cisa_kev`/`active_exploitation` (bool) + `epss_score`/`epss_percentile`
dst (Fase 7.3, router `cve`, Grup B survei 7.4 2026-09-19) -- SEKARANG
diisi jalur MANUAL (`POST /cisa-lookup`/`/epss-lookup`/`/exploit-lookup`,
lihat `cti_api.services.cve_lookup`), bukan lagi nunggu `_cve_enrichment_
loop`. Fungsi service yang sama itu jugalah yang bakal dipanggil ulang
dari Celery beat task pas Fase 7.8 beneran ngerjain loop-nya (tinggal
jadwalin, bukan nulis ulang) -- jadi kolom-kolom ini SEKARANG genuinely
keisi kalau analis mijit tombol lookup, bukan nunggu loop yang belum ada.

`cisa_kev_detail`/`exploit_db_hits` JSONB -- snapshot mentah respons API
eksternal (CISA KEV catalog entry / hasil exploit-db), "cair" persis
alasan yang sama kayak `PackageDepGraph.scorecard_checks` (Bagian 4):
field deskriptif yang gak pernah di-query per-sub-field, dibaca+ditulis
utuh. `pocs` hasil exploit-db TETAP masuk tabel anak `CvePoc` yang udah
ada (bukan field baru) -- exploit-db cuma nambahin baris baru ke situ.

`CveNewsletterMention` (Fase 7.3, router `newsletter`, Bagian 4) --
gantiin `cve_tracker.newsletter_mentions` (array Mongo, `$push` dedup by
url). Ini DITULIS sama fitur yang lagi diport sendiri (newsletter), beda
dari `threat_actors` dkk di atas yang nunggu loop terpisah."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin


class CveTracker(TimestampMixin, Base):
    __tablename__ = "cve_tracker"
    __table_args__ = (UniqueConstraint("cve_id", "client_id", name="uq_cve_tracker_cve_client"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    cve_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )
    tech: Mapped[str | None] = mapped_column(String(200))
    link: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    published: Mapped[datetime.date | None] = mapped_column(Date)
    published_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    """Jam publish asli dari MITRE (`cveMetadata.datePublished`, UTC) -- `published` di atas
    cuma tanggalnya (dipakai filter/sort/UI sejak Fase 2). Kolom ini sumber "CVE Reported Date"
    di export Excel; `detected_on` (kapan scraper pertama dapat CVE-nya) jadi "Reported by
    System". `NULL` untuk CVE yang masuk sebelum kolom ini ada, diisi lewat
    `tools/ops/backfill_cve_published_at.py`."""
    solutions: Mapped[str | None] = mapped_column(Text)

    cve_score: Mapped[float | None] = mapped_column(Float)
    cve_severity: Mapped[str | None] = mapped_column(String(20))
    cvss_vector: Mapped[str | None] = mapped_column(String(100))
    cve_modified_date: Mapped[datetime.date | None] = mapped_column(Date)

    poc_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cisa_kev: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_exploitation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    detected_on: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    epss_score: Mapped[float | None] = mapped_column(Float)
    epss_percentile: Mapped[float | None] = mapped_column(Float)
    epss_date: Mapped[str | None] = mapped_column(String(10))
    """`YYYY-MM-DD` -- tanggal "as-of" skor dari FIRST.org, string
    apa adanya kayak sumbernya, bukan `Date` (bukan field yang di-range-
    query)."""
    epss_checked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    cisa_kev_checked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    cisa_kev_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """`{date_added, due_date, vendor, product, name, description,
    action}` -- snapshot satu entry katalog CISA KEV, lihat docstring
    modul."""

    exploit_db_checked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    exploit_db_hits: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    """Snapshot mentah hasil pencarian exploit-db (dipotong ke `pocs`
    juga, lihat docstring modul) -- dipakai UI nampilin detail exploit
    (title/tanggal publish) yang gak ada analognya di `CvePoc` (cuma
    `url`/`source`/`poc_type`)."""
    registered_date: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    references: Mapped[list[CveReference]] = relationship(
        back_populates="cve", cascade="all, delete-orphan", lazy="selectin"
    )
    affected: Mapped[list[CveAffected]] = relationship(
        back_populates="cve", cascade="all, delete-orphan", lazy="selectin"
    )
    pocs: Mapped[list[CvePoc]] = relationship(
        back_populates="cve", cascade="all, delete-orphan", lazy="selectin"
    )
    threat_actors: Mapped[list[CveThreatActor]] = relationship(
        back_populates="cve", cascade="all, delete-orphan", lazy="selectin"
    )
    ttps: Mapped[list[CveTTP]] = relationship(
        back_populates="cve", cascade="all, delete-orphan", lazy="selectin"
    )
    newsletter_mentions: Mapped[list[CveNewsletterMention]] = relationship(
        back_populates="cve", cascade="all, delete-orphan", lazy="selectin"
    )


class CveReference(Base):
    __tablename__ = "cve_references"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_tracker_id: Mapped[int] = mapped_column(
        ForeignKey("cve_tracker.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)

    cve: Mapped[CveTracker] = relationship(back_populates="references")


class CveAffected(Base):
    __tablename__ = "cve_affected"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_tracker_id: Mapped[int] = mapped_column(
        ForeignKey("cve_tracker.id", ondelete="CASCADE"), nullable=False
    )
    affected: Mapped[str] = mapped_column(String(300), nullable=False)

    cve: Mapped[CveTracker] = relationship(back_populates="affected")


class CvePoc(Base):
    __tablename__ = "cve_pocs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_tracker_id: Mapped[int] = mapped_column(
        ForeignKey("cve_tracker.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100))
    poc_type: Mapped[str | None] = mapped_column(String(20))
    """"poc" atau "exploit" -- klasifikasi regex sederhana atas nama/deskripsi
    repo (lihat `githubPOCMonitor.py` lama, `github_poc_monitor.py` baru).
    Kolom ketinggalan pas Fase 2 (model ini ditulis SEBELUM `githubPOCMonitor.py`
    beneran di-port, jadi belum ketauan field ini dipakai) -- ditambah Fase 4
    pas port beneran butuh, bukan dirombak ulang."""

    cve: Mapped[CveTracker] = relationship(back_populates="pocs")


class CveNewsletterMention(Base):
    __tablename__ = "cve_newsletter_mentions"
    __table_args__ = (UniqueConstraint("cve_tracker_id", "url", name="uq_cve_newsletter_mention"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_tracker_id: Mapped[int] = mapped_column(
        ForeignKey("cve_tracker.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    mention_date: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    added_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    cve: Mapped[CveTracker] = relationship(back_populates="newsletter_mentions")


class CveThreatActor(Base):
    __tablename__ = "cve_threat_actors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_tracker_id: Mapped[int] = mapped_column(
        ForeignKey("cve_tracker.id", ondelete="CASCADE"), nullable=False
    )
    threat_actor: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    cve: Mapped[CveTracker] = relationship(back_populates="threat_actors")


class CveTTP(Base):
    __tablename__ = "cve_ttps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_tracker_id: Mapped[int] = mapped_column(
        ForeignKey("cve_tracker.id", ondelete="CASCADE"), nullable=False
    )
    ttp_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    ttp_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    cve: Mapped[CveTracker] = relationship(back_populates="ttps")


class CveFalsePositive(Base):
    __tablename__ = "cve_false_positives"
    __table_args__ = (UniqueConstraint("cve_id", "client_id", name="uq_cve_fp_cve_client"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False
    )
    marked_by: Mapped[str | None] = mapped_column(String(200))
    marked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CveTicket(TimestampMixin, Base):
    """Fase 7.4 Grup C (2026-09-23) -- ROMBAK TOTAL dari placeholder Fase 2
    (`CveTicket` 1:N `CveTicketItem`, "satu ticket bisa nyakup banyak CVE").
    Ketauan pas baca `cve_ticket_service.py` lama: KONSEPNYA BEDA -- SATU
    record per (cve_id, client_id), bukan container. `ticket_id` ("CTI-
    2026-09-001") cuma label tampilan yang di-generate pas record ini
    pertama disentuh (acknowledge atau edit manual), BUKAN entity yang
    menaungi banyak CVE. Gak ada tabel anak sama sekali.

    `remediation_date_plan`/`actual_remediation_date`/`closure_date` --
    `Date` asli (legacy: string bebas dari `<input type="date">` frontend,
    `str=""` di Pydantic lama tanpa validasi) -- upgrade konsisten sama
    pola `Article.posted_on`/`CveTracker.published` di skema ini, bukan
    port literal (frontend selalu kirim `YYYY-MM-DD`, aman diparse).

    `cve_reported_date` (legacy) SENGAJA GAK ADA kolomnya -- field itu
    READONLY di UI lama (auto-fill dari `cve.published`), gak ada bukti
    pernah beneran di-override. Router baca `CveTracker.published`
    langsung pas serialize, bukan simpen field duplikat.

    `active_exploitation`/`remediation_status`/`risk_acceptance` --
    "soft enum" String, TANPA CHECK constraint -- legacy juga gak
    validasi server-side (cuma dropdown `<select>` di frontend, Pydantic-
    nya `str=""` polos). Nilai yang dipakai UI lama (dokumentasi, bukan
    enforced): `active_exploitation` -- "Active Exploitation"|"Limited
    Exploitation"|"No Known Exploitation"|"Unknown/Under Investigation";
    `remediation_status` -- "Open"|"In Progress"|"Resolved"|"Risk
    Accepted"|"Closed"; `risk_acceptance` -- "Risk Acceptance"|"Risk
    Mitigation"|"Risk Transfer"|"No Risk (Not Affected)".

    `ticket_id` di-generate GLOBAL lintas SEMUA client per bulan (legacy
    `get_next_ticket_id()` scan tanpa filter client_id sama sekali) --
    asimetri dipertahankan apa adanya, port literal (lihat
    `AsyncCveTicketRepo.get_next_ticket_id`)."""

    __tablename__ = "cve_tickets"
    __table_args__ = (UniqueConstraint("cve_id", "client_id", name="uq_cve_tickets_cve_client"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cve_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )
    ticket_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)

    affected_asset: Mapped[str | None] = mapped_column(Text)
    affected_version: Mapped[str | None] = mapped_column(Text)
    fixed_version: Mapped[str | None] = mapped_column(Text)
    asset_owner: Mapped[str | None] = mapped_column(String(200))
    owner_email: Mapped[str | None] = mapped_column(String(200))
    owner_team: Mapped[str | None] = mapped_column(String(200))
    active_exploitation: Mapped[str | None] = mapped_column(String(50))
    """Free-text/soft-enum ANALIS, BEDA dari `CveTracker.active_exploitation`
    (bool, dihitung mesin dari CISA KEV/exploit-db, Grup B) -- dua konsep
    beda yang kebetulan nama sama, dipertahankan terpisah kayak legacy."""
    remediation_date_plan: Mapped[datetime.date | None] = mapped_column(Date)
    remediation_status: Mapped[str | None] = mapped_column(String(50))
    actual_remediation_date: Mapped[datetime.date | None] = mapped_column(Date)
    escalation_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    comments: Mapped[str | None] = mapped_column(Text)
    risk_acceptance: Mapped[str | None] = mapped_column(String(50))
    closure_date: Mapped[datetime.date | None] = mapped_column(Date)

    acknowledged_by: Mapped[str | None] = mapped_column(String(200))
    acknowledge_time: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
