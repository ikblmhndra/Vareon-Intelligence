"""Dashboard MTTD/MTTA/MTTR CVE Tracker -- gantiin sheet "Dashboard" di workbook
Excel `CVE_Tracker_Dashboard.xlsx` (logbook manual lama), dihitung dari
`cve_tracker` + `cve_tickets` per client.

Bukan port literal rumus Excel. Hasil audit workbook-nya (811 baris, 2026) nemu
beberapa kelemahan yang SENGAJA gak ikut dibawa:

- Excel membuang nilai 0 dari rata-rata (`AVERAGEIF(...,">0")`), jadi KPI atas
  (MTTA 8,8 hari) beda dari baris total bulanan (8,4 hari) di halaman yang sama.
  Di sini nol IKUT dihitung, dan tiap metrik menampilkan mean + median + p90 + n.
- "Resolution rate" Excel = Completed / SEMUA CVE (3%), padahal 81% CVE belum
  di-triage. Di sini pembaginya cuma CVE yang memang butuh tindakan
  (`total - not_affected`), dan CVE yang belum di-triage punya bucket sendiri.
- MTTD Excel cuma bernilai 1 atau 6 jam (offset tetap, bukan pengukuran). Di sini
  MTTD = `detected_on` (tanggal WIB) - `published`, dalam HARI -- `published`
  kolom `Date`, tanpa jam, jadi satuan jam memang gak mungkin dari data ini.
- Range formula Excel campur `$500`/`$5000` sehingga panel tertentu memotong
  data; di sini gak ada batas baris.

Definisi (semua hari kalender WIB, `max(0, ...)`):

- MTTD  = tanggal `detected_on` - `published`
- MTTA  = tanggal `acknowledge_time` - tanggal `detected_on`
- MTTR  = `actual_remediation_date` - tanggal `detected_on`, TIDAK dihitung untuk
          CVE "Not Affected" (gak ada remediasi yang perlu diukur)

Status memakai vocab platform (`remediation_status` Open/In Progress/Resolved/
Risk Accepted/Closed). "Not Affected" diturunkan dari `risk_acceptance ==
"No Risk (Not Affected)"` dan menang atas status. `remediation_status` itu
"soft enum" tanpa CHECK (lihat docstring `CveTicket`), jadi nilai legacy dari
legenda Excel (Pending/Completed/Not Affected/Not Applicable) dipetakan lewat
`_STATUS_ALIASES` alih-alih diam-diam jatuh ke bucket yang salah.

`build_dashboard()` murni (tanpa I/O) supaya bisa dites tanpa DB; `get_dashboard()`
yang menyentuh repo."""

from __future__ import annotations

import datetime
import math
import statistics
import zoneinfo
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.cve_dashboard import (
    CveDashboard,
    DashboardSummary,
    MetricStat,
    MonthMetrics,
    SeverityMetrics,
    SlowestCve,
    StatusBreakdown,
    TeamMetrics,
)

TIMEZONE = "Asia/Jakarta"
"""Sama dengan `cve_export` (export Excel) -- hari kalender di dashboard = hari yang
dilihat analis."""
_TZ = zoneinfo.ZoneInfo(TIMEZONE)

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
UNRATED = "UNRATED"
"""Baris `by_severity` untuk CVE tanpa severity tersimpan dan tanpa skor CVSS (`severity_of`
-> `None`). Hanya dikirim kalau ada, supaya tabel menjumlah ke `summary.total`."""
UNASSIGNED = "Unassigned"
SLOWEST_LIMIT = 10
NOT_AFFECTED_RISK = "No Risk (Not Affected)"

_BUCKETS = (
    "unacknowledged",
    "awaiting_status",
    "open",
    "in_progress",
    "risk_accepted",
    "completed",
    "not_affected",
)

_STATUS_ALIASES = {
    "open": "open",
    "pending": "open",
    "in progress": "in_progress",
    "risk accepted": "risk_accepted",
    "resolved": "completed",
    "closed": "completed",
    "completed": "completed",
    "not affected": "not_affected",
    "not applicable": "not_affected",
}


@dataclass(frozen=True)
class DashRow:
    """Satu CVE + ticket-nya (kalau ada). String kosong = tidak diisi."""

    cve_id: str
    severity_label: str
    score: float | None
    tech: str
    published: datetime.date | None
    detected_on: datetime.datetime
    solutions: str
    has_ticket: bool
    owner_team: str
    remediation_status: str
    risk_acceptance: str
    acknowledge_time: datetime.datetime | None
    actual_remediation_date: datetime.date | None


@dataclass(frozen=True)
class _Computed:
    row: DashRow
    severity: str | None
    bucket: str
    detected_local: datetime.datetime
    mttd: int | None
    mtta: int | None
    mttr: int | None


def severity_of(label: str, score: float | None) -> str | None:
    """Label tersimpan kalau valid, kalau tidak turunan dari skor CVSS (band yang
    sama dengan `get_stats()`). `None` = tidak bisa dinilai."""
    sev = (label or "").strip().upper()
    if sev in SEVERITIES:
        return sev
    if score is None or score <= 0:
        return None
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    return "LOW"


def classify(row: DashRow) -> str:
    """Tepat satu bucket per CVE (lihat `StatusBreakdown`)."""
    if row.risk_acceptance.strip() == NOT_AFFECTED_RISK:
        return "not_affected"
    bucket = _STATUS_ALIASES.get(row.remediation_status.strip().lower())
    if bucket is not None:
        return bucket
    if row.has_ticket or row.acknowledge_time is not None:
        return "awaiting_status"
    return "unacknowledged"


def _days(later: datetime.date, earlier: datetime.date) -> int:
    return max(0, (later - earlier).days)


def _compute(row: DashRow) -> _Computed:
    detected_local = row.detected_on.astimezone(_TZ)
    detected_date = detected_local.date()
    bucket = classify(row)
    mttd = _days(detected_date, row.published) if row.published else None
    mtta = (
        _days(row.acknowledge_time.astimezone(_TZ).date(), detected_date)
        if row.acknowledge_time
        else None
    )
    mttr = (
        _days(row.actual_remediation_date, detected_date)
        if row.actual_remediation_date and bucket != "not_affected"
        else None
    )
    return _Computed(
        row=row,
        severity=severity_of(row.severity_label, row.score),
        bucket=bucket,
        detected_local=detected_local,
        mttd=mttd,
        mtta=mtta,
        mttr=mttr,
    )


def _percentile(sorted_values: Sequence[int], q: float) -> float:
    """Interpolasi linear (sama dengan `percentile_cont` Postgres / numpy default)."""
    k = (len(sorted_values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(sorted_values[lo])
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def _stat(values: Iterable[int | None]) -> MetricStat:
    data = sorted(v for v in values if v is not None)
    if not data:
        return MetricStat()
    return MetricStat(
        n=len(data),
        mean=round(sum(data) / len(data), 1),
        median=round(float(statistics.median(data)), 1),
        p90=round(_percentile(data, 0.9), 1),
        max=float(data[-1]),
    )


def _mean(values: Iterable[int | None]) -> float | None:
    data = [v for v in values if v is not None]
    return round(sum(data) / len(data), 1) if data else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _no_solution(solutions: str) -> bool:
    text = solutions.strip().lower()
    return not text or text == "no solution yet"


def build_dashboard(rows: Iterable[DashRow], *, year: int, years: list[int]) -> CveDashboard:
    items = [c for c in map(_compute, rows) if c.detected_local.year == year]

    status = StatusBreakdown(**{b: sum(1 for c in items if c.bucket == b) for b in _BUCKETS})
    total = len(items)
    acknowledged = sum(1 for c in items if c.row.acknowledge_time is not None)
    actionable = total - status.not_affected
    sev_counts = {s: sum(1 for c in items if c.severity == s) for s in SEVERITIES}
    summary = DashboardSummary(
        total=total,
        critical=sev_counts["CRITICAL"],
        high=sev_counts["HIGH"],
        medium=sev_counts["MEDIUM"],
        low=sev_counts["LOW"],
        unrated=sum(1 for c in items if c.severity is None),
        acknowledged=acknowledged,
        ack_rate=_rate(acknowledged, total),
        actionable=actionable,
        resolution_rate=_rate(status.completed, actionable),
        no_solution_yet=sum(1 for c in items if _no_solution(c.row.solutions)),
    )

    def severity_metrics(label: str, group: list[_Computed]) -> SeverityMetrics:
        return SeverityMetrics(
            severity=label,
            count=len(group),
            mttd=_stat(c.mttd for c in group),
            mtta=_stat(c.mtta for c in group),
            mttr=_stat(c.mttr for c in group),
        )

    by_severity = [severity_metrics(s, [c for c in items if c.severity == s]) for s in SEVERITIES]
    unrated_items = [c for c in items if c.severity is None]
    if unrated_items:
        by_severity.append(severity_metrics(UNRATED, unrated_items))

    teams: dict[str, list[_Computed]] = defaultdict(list)
    for c in items:
        teams[c.row.owner_team.strip() or UNASSIGNED].append(c)
    team_order = sorted(teams, key=lambda t: (t == UNASSIGNED, -len(teams[t]), t.lower()))
    by_team = [
        TeamMetrics(
            team=t,
            count=len(teams[t]),
            mtta=_stat(c.mtta for c in teams[t]),
            mttr=_stat(c.mttr for c in teams[t]),
        )
        for t in team_order
    ]

    monthly: list[MonthMetrics] = []
    for month in range(1, 13):
        m = [c for c in items if c.detected_local.month == month]
        monthly.append(
            MonthMetrics(
                month=month,
                total=len(m),
                critical=sum(1 for c in m if c.severity == "CRITICAL"),
                high=sum(1 for c in m if c.severity == "HIGH"),
                medium=sum(1 for c in m if c.severity == "MEDIUM"),
                low=sum(1 for c in m if c.severity == "LOW"),
                unrated=sum(1 for c in m if c.severity is None),
                completed=sum(1 for c in m if c.bucket == "completed"),
                not_affected=sum(1 for c in m if c.bucket == "not_affected"),
                in_progress=sum(1 for c in m if c.bucket == "in_progress"),
                mttd_mean=_mean(c.mttd for c in m),
                mtta_mean=_mean(c.mtta for c in m),
                mttr_mean=_mean(c.mttr for c in m),
            )
        )

    ranked = sorted(
        (c for c in items if c.mtta is not None or c.mttr is not None),
        key=lambda c: (
            -(c.mttr if c.mttr is not None else -1),
            -(c.mtta if c.mtta is not None else -1),
            c.detected_local,
            c.row.cve_id,
        ),
    )
    slowest = [
        SlowestCve(
            cve_id=c.row.cve_id,
            severity=c.severity or "",
            tech=c.row.tech,
            status=c.bucket,
            owner_team=c.row.owner_team,
            mttd=c.mttd,
            mtta=c.mtta,
            mttr=c.mttr,
            detected_on=c.detected_local.strftime("%Y-%m-%d %H:%M"),
        )
        for c in ranked[:SLOWEST_LIMIT]
    ]

    return CveDashboard(
        year=year,
        years=years,
        timezone=TIMEZONE,
        summary=summary,
        status=status,
        mttd=_stat(c.mttd for c in items),
        mtta=_stat(c.mtta for c in items),
        mttr=_stat(c.mttr for c in items),
        by_severity=by_severity,
        by_team=by_team,
        monthly=monthly,
        slowest=slowest,
    )


def _to_row(r: Any) -> DashRow:
    return DashRow(
        cve_id=r.cve_id,
        severity_label=r.cve_severity or "",
        score=r.cve_score,
        tech=r.tech or "",
        published=r.published,
        detected_on=r.detected_on,
        solutions=r.solutions or "",
        has_ticket=r.ticket_id is not None,
        owner_team=r.owner_team or "",
        remediation_status=r.remediation_status or "",
        risk_acceptance=r.risk_acceptance or "",
        acknowledge_time=r.acknowledge_time,
        actual_remediation_date=r.actual_remediation_date,
    )


async def get_dashboard(
    session: AsyncSession,
    *,
    client_id: str,
    year: int | None,
    tech: Sequence[str] | None,
    exclude_cve_ids: Sequence[str] | None,
) -> CveDashboard:
    """`year=None` = tahun berjalan (WIB) kalau punya data, kalau tidak tahun
    terbaru yang ada datanya."""
    repo = AsyncCveTrackerRepo(session)
    years = await repo.list_detected_years(
        client_id=client_id, timezone=TIMEZONE, tech=tech, exclude_cve_ids=exclude_cve_ids
    )
    if year is None:
        current = datetime.datetime.now(_TZ).year
        year = current if not years or current in years else years[0]
    raw = await repo.list_dashboard_rows(
        client_id=client_id,
        detected_from=datetime.datetime(year, 1, 1, tzinfo=_TZ),
        detected_to=datetime.datetime(year + 1, 1, 1, tzinfo=_TZ),
        tech=tech,
        exclude_cve_ids=exclude_cve_ids,
    )
    return build_dashboard([_to_row(r) for r in raw], year=year, years=years)
