"""Unit test `cti_api.services.cve_dashboard.build_dashboard` -- murni, tanpa DB.

Angka-angka yang dijaga di sini adalah keputusan yang SENGAJA beda dari rumus
Excel lama (lihat docstring modulnya): nol ikut dihitung di rata-rata, resolution
rate dibagi CVE yang memang butuh tindakan, MTTD dalam hari, MTTR gak dihitung
untuk "Not Affected", dan hari kalender dibaca di WIB."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_api.services.cve_dashboard import (
    SLOWEST_LIMIT,
    UNASSIGNED,
    DashRow,
    build_dashboard,
    classify,
    severity_of,
)

UTC = datetime.UTC


def _row(cve_id: str = "CVE-2026-0001", **kw: Any) -> DashRow:
    base: dict[str, Any] = {
        "cve_id": cve_id,
        "severity_label": "HIGH",
        "score": 7.5,
        "tech": "nginx",
        "published": datetime.date(2026, 3, 1),
        "detected_on": datetime.datetime(2026, 3, 3, 3, 0, tzinfo=UTC),  # 10:00 WIB
        "solutions": "Upgrade to 1.2.3",
        "has_ticket": False,
        "owner_team": "",
        "remediation_status": "",
        "risk_acceptance": "",
        "acknowledge_time": None,
        "actual_remediation_date": None,
    }
    base.update(kw)
    return DashRow(**base)


def _ack(day: int, hour: int = 3, month: int = 3) -> datetime.datetime:
    return datetime.datetime(2026, month, day, hour, 0, tzinfo=UTC)


# ── severity_of / classify ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("label", "score", "expected"),
    [
        ("critical", 1.0, "CRITICAL"),  # label tersimpan menang atas skor
        ("", 9.8, "CRITICAL"),
        ("", 7.0, "HIGH"),
        ("n/a", 4.0, "MEDIUM"),
        ("", 3.9, "LOW"),
        ("", 0.0, None),
        ("", None, None),
    ],
)
def test_severity_of(label: str, score: float | None, expected: str | None) -> None:
    assert severity_of(label, score) == expected


@pytest.mark.parametrize(
    ("kw", "bucket"),
    [
        ({}, "unacknowledged"),
        ({"has_ticket": True}, "awaiting_status"),
        ({"acknowledge_time": _ack(4)}, "awaiting_status"),
        ({"remediation_status": "Open"}, "open"),
        ({"remediation_status": "In Progress"}, "in_progress"),
        ({"remediation_status": "Risk Accepted"}, "risk_accepted"),
        ({"remediation_status": "Resolved"}, "completed"),
        ({"remediation_status": "Closed"}, "completed"),
        # vocab legenda Excel lama gak boleh diam-diam jatuh ke bucket yang salah
        ({"remediation_status": "Completed"}, "completed"),
        ({"remediation_status": "Pending"}, "open"),
        ({"remediation_status": " in progress "}, "in_progress"),
        # "Not Affected" turunan dari risk_acceptance dan menang atas status
        (
            {"risk_acceptance": "No Risk (Not Affected)", "remediation_status": "In Progress"},
            "not_affected",
        ),
        ({"risk_acceptance": "Risk Mitigation"}, "unacknowledged"),
        ({"remediation_status": "something odd", "has_ticket": True}, "awaiting_status"),
    ],
)
def test_classify(kw: dict[str, Any], bucket: str) -> None:
    assert classify(_row(**kw)) == bucket


# ── metrik ────────────────────────────────────────────────────────────────────


def test_mtta_includes_zero_days_unlike_the_old_excel() -> None:
    rows = [
        _row("CVE-2026-0001", acknowledge_time=_ack(3, hour=8)),  # hari yang sama: 0
        _row("CVE-2026-0002", acknowledge_time=_ack(3, hour=9)),  # 0
        _row("CVE-2026-0003", acknowledge_time=_ack(13)),  # 10
        _row("CVE-2026-0004"),  # belum di-ack: bukan data, bukan nol
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    assert d.mtta.n == 3
    assert d.mtta.mean == 3.3  # Excel: (0+0+10)/1 = 10.0 karena nol dibuang
    assert d.mtta.median == 0.0
    assert d.mtta.p90 == 8.0
    assert d.mtta.max == 10.0


def test_mttd_is_days_from_published_to_detected() -> None:
    rows = [
        _row("CVE-2026-0001", published=datetime.date(2026, 3, 3)),  # 0
        _row("CVE-2026-0002", published=datetime.date(2026, 2, 27)),  # 4
        _row("CVE-2026-0003", published=None),  # tanpa data
        _row("CVE-2026-0004", published=datetime.date(2026, 3, 9)),  # published > detected: 0
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    assert (d.mttd.n, d.mttd.mean, d.mttd.max) == (3, 1.3, 4.0)


def test_mttr_skips_not_affected_and_rows_without_remediation_date() -> None:
    rows = [
        _row(
            "CVE-2026-0001",
            remediation_status="Resolved",
            actual_remediation_date=datetime.date(2026, 3, 8),  # 5 hari dari 3 Mar
        ),
        _row(
            "CVE-2026-0002",
            risk_acceptance="No Risk (Not Affected)",
            actual_remediation_date=datetime.date(2026, 3, 30),  # diabaikan
        ),
        _row("CVE-2026-0003", remediation_status="In Progress"),
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    assert (d.mttr.n, d.mttr.mean) == (1, 5.0)


def test_day_boundaries_use_wib_not_utc() -> None:
    # 18:00 UTC = 01:00 WIB hari berikutnya: ack jam 02:00 WIB di hari yang sama = 0 hari
    row = _row(
        detected_on=datetime.datetime(2026, 3, 3, 18, 0, tzinfo=UTC),
        acknowledge_time=datetime.datetime(2026, 3, 3, 19, 0, tzinfo=UTC),
    )
    assert build_dashboard([row], year=2026, years=[2026]).mtta.mean == 0.0


def test_year_and_month_are_read_in_wib() -> None:
    # 17:30 UTC 31 Des 2025 = 00:30 WIB 1 Jan 2026 -> masuk 2026 (Januari), bukan 2025
    row = _row(detected_on=datetime.datetime(2025, 12, 31, 17, 30, tzinfo=UTC))
    d = build_dashboard([row], year=2026, years=[2026, 2025])
    assert d.summary.total == 1
    assert d.monthly[0].total == 1
    assert build_dashboard([row], year=2025, years=[2026, 2025]).summary.total == 0


# ── ringkasan ─────────────────────────────────────────────────────────────────


def test_status_buckets_partition_total_and_resolution_rate_excludes_not_affected() -> None:
    rows = [
        _row("CVE-2026-0001"),  # unacknowledged
        _row("CVE-2026-0002", has_ticket=True),  # awaiting_status
        _row("CVE-2026-0003", remediation_status="Open"),
        _row("CVE-2026-0004", remediation_status="In Progress"),
        _row("CVE-2026-0005", remediation_status="Risk Accepted"),
        _row("CVE-2026-0006", remediation_status="Resolved"),
        _row("CVE-2026-0007", remediation_status="Closed"),
        _row("CVE-2026-0008", risk_acceptance="No Risk (Not Affected)"),
        _row("CVE-2026-0009", risk_acceptance="No Risk (Not Affected)"),
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    s = d.status
    assert (
        s.unacknowledged,
        s.awaiting_status,
        s.open,
        s.in_progress,
        s.risk_accepted,
        s.completed,
        s.not_affected,
    ) == (1, 1, 1, 1, 1, 2, 2)
    assert sum(s.model_dump().values()) == d.summary.total == 9
    assert d.summary.actionable == 7
    assert d.summary.resolution_rate == round(2 / 7, 4)  # Excel: 2/9 dari semua baris


def test_empty_year_gives_none_rates_and_twelve_zero_months() -> None:
    d = build_dashboard([], year=2026, years=[])
    assert d.summary.total == 0
    assert d.summary.ack_rate is None
    assert d.summary.resolution_rate is None
    assert d.mtta == d.mttr == d.mttd
    assert d.mtta.n == 0
    assert [m.month for m in d.monthly] == list(range(1, 13))
    assert all(m.total == 0 and m.mtta_mean is None for m in d.monthly)
    assert [s.severity for s in d.by_severity] == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def test_severity_counts_fall_back_to_score_and_count_unrated() -> None:
    rows = [
        _row("CVE-2026-0001", severity_label="CRITICAL", score=9.9),
        _row("CVE-2026-0002", severity_label="", score=7.2),  # -> HIGH
        _row("CVE-2026-0003", severity_label="", score=None),  # unrated
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    sm = d.summary
    assert (sm.critical, sm.high, sm.medium, sm.low, sm.unrated) == (1, 1, 0, 0, 1)
    assert sm.critical + sm.high + sm.medium + sm.low + sm.unrated == sm.total
    assert [s.count for s in d.by_severity] == [1, 1, 0, 0]


def test_no_solution_yet_counts_blank_and_placeholder() -> None:
    rows = [
        _row("CVE-2026-0001", solutions="No solution yet"),
        _row("CVE-2026-0002", solutions="  "),
        _row("CVE-2026-0003", solutions="Upgrade to 2.0"),
    ]
    assert build_dashboard(rows, year=2026, years=[2026]).summary.no_solution_yet == 2


def test_ack_rate() -> None:
    rows = [_row("CVE-2026-0001", acknowledge_time=_ack(4)), _row("CVE-2026-0002")]
    assert build_dashboard(rows, year=2026, years=[2026]).summary.ack_rate == 0.5


# ── tim, bulan, paling lambat ─────────────────────────────────────────────────


def test_teams_sorted_by_count_with_unassigned_last() -> None:
    rows = [
        _row("CVE-2026-0001"),
        _row("CVE-2026-0002"),
        _row("CVE-2026-0003"),
        _row("CVE-2026-0004", owner_team="SOC"),
        _row("CVE-2026-0005", owner_team="Network Security"),
        _row("CVE-2026-0006", owner_team="Network Security"),
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    assert [(t.team, t.count) for t in d.by_team] == [
        ("Network Security", 2),
        ("SOC", 1),
        (UNASSIGNED, 3),
    ]


def test_monthly_is_a_cohort_by_detected_month() -> None:
    rows = [
        _row(
            "CVE-2026-0001",
            detected_on=datetime.datetime(2026, 1, 10, 3, 0, tzinfo=UTC),
            severity_label="CRITICAL",
            acknowledge_time=datetime.datetime(2026, 2, 9, 3, 0, tzinfo=UTC),  # 30 hari
        ),
        _row("CVE-2026-0002", detected_on=datetime.datetime(2026, 1, 20, 3, 0, tzinfo=UTC)),
        _row("CVE-2026-0003", detected_on=datetime.datetime(2026, 2, 5, 3, 0, tzinfo=UTC)),
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    jan, feb, mar = d.monthly[0], d.monthly[1], d.monthly[2]
    assert (jan.total, jan.critical, jan.high) == (2, 1, 1)
    assert jan.mtta_mean == 30.0  # di-ack Februari, tapi dihitung ke kohort Januari
    assert feb.total == 1 and feb.mtta_mean is None
    assert mar.total == 0


def test_slowest_ranks_by_mttr_then_mtta_and_is_capped() -> None:
    rows = [
        _row(
            "CVE-2026-0001",
            acknowledge_time=_ack(4),  # mtta 1, tanpa mttr
        ),
        _row(
            "CVE-2026-0002",
            acknowledge_time=_ack(4),
            remediation_status="Resolved",
            actual_remediation_date=datetime.date(2026, 3, 10),  # mttr 7
        ),
        _row(
            "CVE-2026-0003",
            acknowledge_time=_ack(30),  # mtta 27, tanpa mttr
        ),
        _row("CVE-2026-0004"),  # gak punya data -> gak masuk daftar
    ]
    d = build_dashboard(rows, year=2026, years=[2026])
    assert [s.cve_id for s in d.slowest] == ["CVE-2026-0002", "CVE-2026-0003", "CVE-2026-0001"]
    assert d.slowest[0].status == "completed"
    assert d.slowest[0].detected_on == "2026-03-03 10:00"  # WIB

    many = [_row(f"CVE-2026-{i:04d}", acknowledge_time=_ack(4 + i % 20)) for i in range(1, 40)]
    assert len(build_dashboard(many, year=2026, years=[2026]).slowest) == SLOWEST_LIMIT
