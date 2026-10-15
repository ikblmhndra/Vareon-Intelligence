"""Response `GET /api/cve/dashboard` -- dashboard MTTD/MTTA/MTTR CVE Tracker.

Gantiin sheet "Dashboard" di workbook Excel `CVE_Tracker_Dashboard.xlsx` (logbook
manual lama). Semua angka dihitung server-side (`cti_api.services.cve_dashboard`),
frontend cuma menggambar. Satuan waktu SELALU hari, dibulatkan 1 desimal.

`MetricStat.n` = jumlah CVE yang punya datanya (mis. MTTR cuma ada di CVE yang
sudah punya `actual_remediation_date`), supaya rata-rata dari 2 titik data gak
tampil seolah-olah angka yang kuat."""

from __future__ import annotations

from pydantic import BaseModel


class MetricStat(BaseModel):
    n: int = 0
    mean: float | None = None
    median: float | None = None
    p90: float | None = None
    max: float | None = None


class StatusBreakdown(BaseModel):
    """Partisi lengkap: tiap CVE masuk TEPAT SATU bucket, jumlahnya = `summary.total`."""

    unacknowledged: int = 0
    """Belum ada ticket/status dan belum di-acknowledge."""
    awaiting_status: int = 0
    """Sudah di-acknowledge (atau punya ticket) tapi `remediation_status` masih kosong."""
    open: int = 0
    in_progress: int = 0
    risk_accepted: int = 0
    completed: int = 0
    """`Resolved` + `Closed`."""
    not_affected: int = 0
    """`risk_acceptance == "No Risk (Not Affected)"` -- menang atas status."""


class DashboardSummary(BaseModel):
    total: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    unrated: int = 0
    """CVE tanpa severity tersimpan dan tanpa skor CVSS -- supaya
    `critical + high + medium + low + unrated == total`."""
    acknowledged: int = 0
    ack_rate: float | None = None
    """`acknowledged / total`, 0..1."""
    actionable: int = 0
    """`total - not_affected` -- pembagi resolution rate."""
    resolution_rate: float | None = None
    """`completed / actionable`, 0..1. `None` kalau `actionable == 0`."""
    no_solution_yet: int = 0


class SeverityMetrics(BaseModel):
    severity: str
    """`CRITICAL`/`HIGH`/`MEDIUM`/`LOW`, ditambah `UNRATED` di ujung HANYA kalau tahun itu punya
    CVE tanpa severity tersimpan dan tanpa skor CVSS."""
    count: int
    mttd: MetricStat
    mtta: MetricStat
    mttr: MetricStat


class TeamMetrics(BaseModel):
    team: str
    """`"Unassigned"` untuk CVE tanpa `owner_team`."""
    count: int
    mtta: MetricStat
    mttr: MetricStat


class MonthMetrics(BaseModel):
    """Kohort per bulan `detected_on`: MTTA/MTTR di sini = rata-rata CVE yang
    TERDETEKSI bulan itu (bukan yang di-ack/di-remediasi bulan itu)."""

    month: int
    total: int = 0
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    unrated: int = 0
    """CVE bulan itu tanpa severity dan tanpa skor, supaya
    `critical + high + medium + low + unrated == total` berlaku per bulan."""
    completed: int = 0
    not_affected: int = 0
    in_progress: int = 0
    mttd_mean: float | None = None
    mtta_mean: float | None = None
    mttr_mean: float | None = None


class SlowestCve(BaseModel):
    cve_id: str
    severity: str
    tech: str = ""
    status: str
    """Key bucket `StatusBreakdown` (`completed`, `in_progress`, ...)."""
    owner_team: str = ""
    mttd: int | None = None
    mtta: int | None = None
    mttr: int | None = None
    detected_on: str = ""


class BacklogSeverity(BaseModel):
    severity: str
    """Sama dengan `SeverityMetrics.severity` (`UNRATED` hanya bila ada)."""
    total: int = 0
    bands: list[int]
    """Banyaknya CVE per pita umur, urutan = `Backlog.bands`."""


class Backlog(BaseModel):
    """Beban kerja yang belum selesai (belum di-acknowledge, menunggu status, Open, atau In
    Progress), dikelompokkan menurut umur sejak terdeteksi (hari kalender WIB)."""

    as_of: str
    """`YYYY-MM-DD` (WIB) tempat umur dihitung."""
    threshold_days: int
    """Batas "terlalu lama": `overdue` = CVE yang umurnya LEBIH dari ini."""
    bands: list[str]
    total: int = 0
    overdue: int = 0
    by_severity: list[BacklogSeverity]


class ExploitRiskCve(BaseModel):
    """CVE yang belum selesai tetapi terbukti/berpeluang tinggi dieksploitasi."""

    cve_id: str
    severity: str = ""
    tech: str = ""
    status: str
    """Key bucket `StatusBreakdown`."""
    cisa_kev: bool = False
    epss_score: float | None = None
    age_days: int = 0


class TechCount(BaseModel):
    tech: str
    """`"(none)"` untuk CVE tanpa nama tech."""
    count: int
    critical: int = 0
    high: int = 0
    backlog: int = 0
    """Berapa dari `count` yang belum selesai (definisi sama dengan `Backlog`)."""


class CveDashboard(BaseModel):
    year: int
    years: list[int]
    """Tahun yang punya CVE, terbaru dulu -- isi pilihan tahun di UI."""
    timezone: str
    summary: DashboardSummary
    status: StatusBreakdown
    mttd: MetricStat
    mtta: MetricStat
    mttr: MetricStat
    by_severity: list[SeverityMetrics]
    by_team: list[TeamMetrics]
    monthly: list[MonthMetrics]
    slowest: list[SlowestCve]
    backlog: Backlog
    exploit_risk: list[ExploitRiskCve]
    """Paling berisiko dulu, dipotong 10; jumlah sebenarnya di `exploit_risk_total`."""
    exploit_risk_total: int = 0
    top_tech: list[TechCount]
