"""Unit test fungsi murni `cti_api.services.confidence`. Fase 7.4 Grup D
(survei 2026-09-19). Gak butuh DB -- `IOC` dipakai transient (gak
`session.add()`), cuma buat isi atribut yang dibaca fungsi pure."""

from __future__ import annotations

import datetime

from cti_api.services import confidence as svc
from cti_core.db.models.indicator import Indicator, IndicatorSource


def _now() -> datetime.datetime:
    return datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)


def _ioc(
    *,
    ioc_type: str = "ip",
    last_seen_at: datetime.datetime | None = None,
    seen_count: int = 1,
    tp_count: int = 0,
    fp_count: int = 0,
    sources: list[IndicatorSource] | None = None,
) -> Indicator:
    ioc = Indicator(
        type=ioc_type,
        value="1.2.3.4",
        last_seen_at=last_seen_at or _now(),
        seen_count=seen_count,
        tp_count=tp_count,
        fp_count=fp_count,
    )
    ioc.sources = sources or []
    return ioc


# ── compute_ioc_confidence ────────────────────────────────────────────────────


def test_compute_ioc_confidence_fresh_high_tp_high_source_count() -> None:
    now = _now()
    ioc = _ioc(
        last_seen_at=now,
        tp_count=10,
        fp_count=0,
        sources=[IndicatorSource(url="https://a.com", source_name="a", first_seen_at=now)] * 3,
    )
    score = svc.compute_ioc_confidence(ioc, now)
    # base 50 + recency 30 + source_bonus min(3*10,30)=30 + verdict_bonus
    # 20*10/11 ~= 18.18, age_days=0 -> gak ada decay
    assert score == 100  # diclamp ke 100


def test_compute_ioc_confidence_decays_with_age() -> None:
    now = _now()
    old = now - datetime.timedelta(days=90)  # half-life ip=30 -> 3 half-life
    ioc = _ioc(ioc_type="ip", last_seen_at=old, tp_count=0, fp_count=0, sources=[])
    score = svc.compute_ioc_confidence(ioc, now)
    # raw = 50 (gak ada recency krn age>7), decay 0.5^(90/30)=0.125 -> 6.25 -> round 6
    assert score == 6


def test_compute_ioc_confidence_half_life_varies_by_type() -> None:
    now = _now()
    old = now - datetime.timedelta(days=90)
    ip_score = svc.compute_ioc_confidence(_ioc(ioc_type="ip", last_seen_at=old), now)
    hash_score = svc.compute_ioc_confidence(_ioc(ioc_type="sha256", last_seen_at=old), now)
    # half-life sha256 (90) jauh lebih lambat meluruh dari ip (30)
    assert hash_score > ip_score


def test_compute_ioc_confidence_clamped_between_0_and_100() -> None:
    now = _now()
    very_old = now - datetime.timedelta(days=3650)
    ioc = _ioc(last_seen_at=very_old)
    assert svc.compute_ioc_confidence(ioc, now) >= 0


# ── compute_ioc_actionability ────────────────────────────────────────────────


def test_compute_ioc_actionability_fresh_high_confidence_is_block_now() -> None:
    now = _now()
    ioc = _ioc(ioc_type="sha256", last_seen_at=now, seen_count=10)
    result = svc.compute_ioc_actionability(ioc, now, confidence_score=100)
    assert result["actionability_label"] == "block_now"
    assert result["recommended_action"] == "Add to EDR blocklist"


def test_compute_ioc_actionability_net_type_block_now_message() -> None:
    now = _now()
    ioc = _ioc(ioc_type="domain", last_seen_at=now, seen_count=10)
    result = svc.compute_ioc_actionability(ioc, now, confidence_score=100)
    assert result["actionability_label"] == "block_now"
    assert result["recommended_action"] == "Add to firewall blocklist immediately"


def test_compute_ioc_actionability_old_low_confidence_is_archive() -> None:
    now = _now()
    old = now - datetime.timedelta(days=90)
    ioc = _ioc(ioc_type="ip", last_seen_at=old, seen_count=1)
    result = svc.compute_ioc_actionability(ioc, now, confidence_score=10)
    assert result["actionability_label"] == "archive"
    assert result["recommended_action"] == "Low priority, aging indicator"


def test_compute_ioc_actionability_campaign_score_always_zero() -> None:
    """`campaign_score` nunggu Grup A (mesin cluster) -- selalu 0 sampai
    itu ada, lihat docstring modul."""
    now = _now()
    ioc = _ioc(last_seen_at=now, seen_count=5)
    result = svc.compute_ioc_actionability(ioc, now, confidence_score=0)
    # recency(100)*0.4 + campaign(0)*0.25 + confidence(0)*0.2 + corrob(100)*0.15 = 55
    assert result["actionability_score"] == 55


def test_compute_ioc_actionability_score_between_0_and_100() -> None:
    now = _now()
    ioc = _ioc(last_seen_at=now, seen_count=1)
    result = svc.compute_ioc_actionability(ioc, now, confidence_score=100)
    assert 0 <= result["actionability_score"] <= 100


def test_bonus_ttp_sources_are_explicit_and_llm() -> None:
    # Spec P4: poin TTP hanya untuk `explicit` + `llm`; `keyword` belum diukur presisinya.
    from cti_core.confidence import BONUS_TTP_SOURCES

    assert frozenset({"explicit", "llm"}) == BONUS_TTP_SOURCES
