"""Unit test fungsi murni `cti_api.services.confidence`. Fase 7.4 Grup D
(survei 2026-09-19). Gak butuh DB -- `IOC` dipakai transient (gak
`session.add()`), cuma buat isi atribut yang dibaca fungsi pure."""

from __future__ import annotations

import datetime

from cti_api.services import confidence as svc
from cti_core.db.models.ioc import IOC, IOCSource


def _now() -> datetime.datetime:
    return datetime.datetime(2026, 9, 23, tzinfo=datetime.UTC)


def _ioc(
    *,
    ioc_type: str = "ip",
    last_seen_at: datetime.datetime | None = None,
    seen_count: int = 1,
    tp_count: int = 0,
    fp_count: int = 0,
    sources: list[IOCSource] | None = None,
) -> IOC:
    ioc = IOC(
        type=ioc_type,
        value="1.2.3.4",
        last_seen_at=last_seen_at or _now(),
        seen_count=seen_count,
        tp_count=tp_count,
        fp_count=fp_count,
    )
    ioc.sources = sources or []
    return ioc


# ── compute_score (confidence artikel) ───────────────────────────────────────


def test_compute_score_no_rating_defaults_to_50_50() -> None:
    # (50+50)/2 = 50, gak ada bonus
    assert svc.compute_score(None, None, 0, 0) == 50


def test_compute_score_grade_a_credibility_1_is_100() -> None:
    assert svc.compute_score("A", "1", 0, 0) == 100


def test_compute_score_ttp_bonus_caps_at_20() -> None:
    # 5 TTP * 5 = 25, tapi dibatasin 20
    base = svc.compute_score(None, None, 0, 0)
    capped = svc.compute_score(None, None, 5, 0)
    assert capped - base == 20


def test_compute_score_ta_bonus_caps_at_10() -> None:
    base = svc.compute_score(None, None, 0, 0)
    capped = svc.compute_score(None, None, 0, 5)
    assert capped - base == 10


def test_compute_score_clamped_to_100() -> None:
    assert svc.compute_score("A", "1", 5, 5) == 100


def test_compute_score_unknown_grade_falls_back_to_50() -> None:
    assert svc.compute_score("Z", "9", 0, 0) == 50


# ── compute_ioc_confidence ────────────────────────────────────────────────────


def test_compute_ioc_confidence_fresh_high_tp_high_source_count() -> None:
    now = _now()
    ioc = _ioc(
        last_seen_at=now,
        tp_count=10,
        fp_count=0,
        sources=[IOCSource(url="https://a.com", source_name="a", first_seen_at=now)] * 3,
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


def test_bonus_ttp_count_counts_only_explicit_and_llm() -> None:
    # Spec P4: bonus confidence hanya untuk TTP `explicit` + `llm`; `keyword` belum diukur.
    from cti_core.confidence import bonus_ttp_count

    assert bonus_ttp_count(["llm", "keyword", "explicit", "keyword"]) == 2
    assert bonus_ttp_count([]) == 0
