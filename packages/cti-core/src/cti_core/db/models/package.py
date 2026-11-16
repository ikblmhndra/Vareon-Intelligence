"""Package vulnerability monitoring -- gantiin `monitored_packages` +
`package_vulns` + `package_dep_graph` (Mongo). Fase 7.3 (router `pkg_vuln`,
Bagian 4, terbesar dari 4 router di bagian ini).

Fitur ini dibangun DUA kali di sistem lama (`app/services/pkg_vuln_service.py`
1109 baris osv.dev/deps.dev vs `ScraperNews/pkgVulnScanner.py` 419 baris +
`techstackNPM.py`) -- 1528 baris buat satu fitur. Skema ini SATU-SATUNYA
representasi; layer service yang lebih lengkap (`pkg_vuln_service.py`)
yang diporting (plan §6, Fase 7), implementasi scraper dibuang.

**Revisi dari sketsa Fase 2:** skema awal modul ini (`MonitoredPackage`/
`PackageVuln`/`PackageVulnAlias`/`PackageDepEdge`, lihat migrasi
`cb4d50d510ea_skema_awal_fase_2`) ditulis SEBELUM `pkg_vuln_service.py`
lama dibaca detail -- belum ke-wire ke router/service/test manapun
(tabel kosong, aman diganti total, bukan alter bertahap). Dua cacat yang
diperbaiki di sini:

1. `PackageVuln.monitored_package_id` FK STRICT ke `MonitoredPackage` gak
   bisa nampung kasus nyata: `resolve_package_deps(scan_transitive=True)`
   manggil `scan_package()` buat dependensi TRANSITIF yang BUKAN package
   yang lagi dimonitor (gak ada baris `MonitoredPackage` buat mereka sama
   sekali) -- `pkg_col.update_one(...)` di baris terakhir `scan_package()`
   lama TANPA `upsert=True`, jadi diem-diem no-op kalau gak ketemu. Vuln
   tetap kesimpen. Makanya di sini `PackageVuln` pakai `package_name`/
   `ecosystem`/`client_id` LANGSUNG (denormalized, port apa adanya dari
   bentuk Mongo lama), BUKAN FK -- konsisten sama gimana kode lama betulan
   jalan, bukan MEMBUAT constraint yang gak pernah ada.
2. Field yang ilang total di sketsa (`advisory_id` asli/`pinned_version`/
   `summary`/`details`/`cvss_score`/`adjusted_score`/`published`/
   `modified`/`fixed_version`/dst di `PackageVuln`; rollup `vuln_count`/
   `*_count`/`highest_severity`/`dep_*`/`scorecard_*` di `MonitoredPackage`;
   seluruh `resolved_at`/`direct_count`/`scorecard_*` di dep graph) --
   ditambahin lengkap di sini, hasil baca detail `pkg_vuln_service.py`.

`aliases`/`affected_version_ranges`/`references` (`PackageVuln`) dan
`direct_deps`/`indirect_deps`/`scorecard_checks` (`PackageDepGraph`) --
JSONB, bukan tabel anak ternormalisasi kayak `CveReference` dkk. Beda
dari list artikel (`entity_mentions`, di-query/index per nilai), list-list
ini gak pernah di-filter/join per elemen di kode lama -- dibaca+ditulis
SELALU utuh bareng parent-nya, tampilan doang. Sama alasan kayak
`PIRRequirement.criteria` (lihat docstring model itu): bag-of-strings ad
hoc, "cair" sesuai plan §3.

`PackageDepGraph.pkg_id` FK bigint ke `monitored_packages.id` (BUKAN
denormalized kayak `PackageVuln`) -- ini AMAN karena `resolve_package_deps`
lama SELALU mensyaratkan `get_package_by_id()` ketemu duluan (404 kalau
nggak), beda dari `scan_package` yang bisa dipanggil buat package
non-monitored (lihat poin 1 di atas). UNIQUE constraint cukup `pkg_id`
doang (bukan `pkg_id`+`client_id` kayak Mongo lama) -- satu
`MonitoredPackage` udah pasti kepunyaan satu client."""

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
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class MonitoredPackage(TimestampMixin, Base):
    __tablename__ = "monitored_packages"
    __table_args__ = (
        UniqueConstraint("name", "ecosystem", "client_id", name="uq_monitored_package"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    ecosystem: Mapped[str] = mapped_column(String(30), nullable=False)
    """npm | PyPI | Go | Maven | crates.io | NuGet | RubyGems | Packagist |
    Hex -- lihat `_VALID_ECOSYSTEMS` di `cti_api.services.pkg_vuln`."""
    version: Mapped[str | None] = mapped_column(String(200))
    """Versi yang di-pin analis (kalau ada) -- dipakai buat query osv.dev
    version-scoped. `None` berarti scan cross-version (semua advisory buat
    package ini, tanpa filter versi)."""
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )

    added_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    """manual | lockfile."""

    last_scan: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    vuln_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medium_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    low_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    highest_severity: Mapped[str] = mapped_column(String(10), nullable=False, default="NONE")
    latest_version: Mapped[str | None] = mapped_column(String(200))
    """Versi terbaru di registry (deps.dev), bukan versi yang di-pin --
    dipakai UI buat nunjukin "ada update" doang."""

    dep_direct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dep_indirect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dep_total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dep_resolved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    scorecard_score: Mapped[float | None] = mapped_column(Float)
    scorecard_date: Mapped[str | None] = mapped_column(String(10))
    """`YYYY-MM-DD` string dari API OSSF Scorecard (deps.dev), bukan `Date`
    asli -- port apa adanya, sumbernya udah string date-only."""
    source_path: Mapped[str | None] = mapped_column(String(500))
    """Path manifest asal paket (mis. `services/api/requirements.txt`); NULL = ditambah manual."""


class PackageVuln(TimestampMixin, Base):
    __tablename__ = "package_vulns"
    __table_args__ = (
        UniqueConstraint(
            "package_name", "ecosystem", "advisory_id", "client_id", name="uq_package_vuln"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    package_name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    ecosystem: Mapped[str] = mapped_column(String(30), nullable=False)
    """Denormalized (bukan FK) -- lihat docstring modul poin 1: vuln buat
    dependensi transitif yang gak dimonitor tetap harus bisa kesimpen."""
    pinned_version: Mapped[str | None] = mapped_column(String(200))
    """Versi yang lagi di-query pas advisory ini ketemu -- snapshot,
    BUKAN FK ke `MonitoredPackage.version` (bisa berubah abis scan ini)."""
    advisory_id: Mapped[str] = mapped_column(String(100), nullable=False)
    """Mis. `GHSA-xxxx` atau `OSV-2024-xxxx` -- ID advisory osv.dev, bukan
    selalu CVE (lihat `aliases` buat mapping ke CVE kalau ada)."""
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """Dipotong 2000 karakter pas ditulis (`scan_package`), port apa
    adanya dari kode lama."""

    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="UNKNOWN")
    cvss_score: Mapped[float | None] = mapped_column(Float)

    # ── Composite enrichment (EPSS + KEV) -- SENGAJA belum diisi ──────────
    epss_score: Mapped[float | None] = mapped_column(Float)
    epss_percentile: Mapped[float | None] = mapped_column(Float)
    kev: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kev_date_added: Mapped[str | None] = mapped_column(String(10))
    """`_enrich_vulns_composite()` lama (fetch EPSS dari FIRST.org + KEV
    dari CISA, lewat `epss_service.py`/`cisa_kev_service.py`) SENGAJA
    belum diport -- dua modul itu SAMA yang udah didokumentasikan belum
    ke-port di `routers/cve.py` (`POST /cisa-lookup`/`/epss-lookup`,
    lihat docstring modul itu), bukan concern router `pkg_vuln` doang.
    Kolom-kolom ini tetap ada (skema faithful), cuma selalu kosong/False
    sampai dua service lookup eksternal itu diport terpisah -- nyusul
    bareng `cve.py`, bukan scope di sini."""

    adjusted_score: Mapped[float | None] = mapped_column(Float)
    adjusted_severity: Mapped[str | None] = mapped_column(String(10))
    """Dihitung SAAT SCAN dari `cvss_score` doang (`epss=None, kev=False`)
    -- formula `_compute_adjusted_score()` port byte-identik, cuma gak
    ada pass KEDUA yang nge-boost pakai EPSS/KEV asli (lihat catatan di
    atas). Bukan placeholder kosong, nilainya valid, cuma belum "boosted"."""

    published: Mapped[datetime.date | None] = mapped_column(Date)
    modified: Mapped[datetime.date | None] = mapped_column(Date)
    fixed_version: Mapped[str | None] = mapped_column(String(200))
    affected_version_ranges: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    references: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ack_by: Mapped[str | None] = mapped_column(String(200))
    ack_date: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="osv.dev")

    last_updated: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PackageDepGraph(TimestampMixin, Base):
    __tablename__ = "package_dep_graphs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    pkg_id: Mapped[int] = mapped_column(
        ForeignKey("monitored_packages.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    package_name: Mapped[str] = mapped_column(String(300), nullable=False)
    ecosystem: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[str | None] = mapped_column(String(200))
    """Snapshot nama/ekosistem/versi PAS resolve ini jalan -- disimpen
    ulang di sini (bukan cuma di `MonitoredPackage`) buat riwayat, port
    apa adanya dari kode lama."""

    resolved_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indirect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    direct_deps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    indirect_deps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    """Dipotong 200 item pas ditulis (`resolve_package_deps`), port apa
    adanya dari kode lama."""

    scorecard_score: Mapped[float | None] = mapped_column(Float)
    scorecard_date: Mapped[str | None] = mapped_column(String(10))
    scorecard_project: Mapped[str | None] = mapped_column(String(300))
    scorecard_checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    error: Mapped[str | None] = mapped_column(Text)
