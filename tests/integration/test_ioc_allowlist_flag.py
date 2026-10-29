"""Persist enrich: IOC yang cocok allowlist TETAP disimpan, ditandai `auto_suppressed` + alasan --
Postgres REAL (testcontainers)."""

from __future__ import annotations

import pytest
from cti_core.db.repositories.indicator import IndicatorRepo
from cti_enrich.routing import RoutingResult
from cti_enrich.stages import extract_iocs as extract_iocs_stage
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.persist import persist
from sqlalchemy.orm import Session


def test_allowlisted_ioc_is_stored_flagged(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(extract_iocs_stage, "_allowlist_cache", None)
    # `gofile.io` sudah ada di `ioc_allowlist_entries`: seed migrasi 0.8.6 (e7b2d4a9c6f1).

    persist(
        session=db_session,
        url="https://news.example/allowlist-flag",
        title="t",
        source="s",
        scraper_id=None,
        posted_on=None,
        classify_result=ClassifyResult(related_cyber=True, confidence=0.9),
        score_result=None,
        routing_result=RoutingResult(news_type="General", alert_topics=[], msg_data=""),
        ttp_result=None,
        ioc_data={"domains": ["Store1[.]gofile.io", "evil-c2.net"]},
        c2_indicator=False,
    )
    monkeypatch.setattr(extract_iocs_stage, "_allowlist_cache", None)

    repo = IndicatorRepo(db_session)
    flagged = repo.get(type="domain", value="store1.gofile.io")
    clean = repo.get(type="domain", value="evil-c2.net")
    assert flagged is not None and clean is not None
    assert flagged.auto_suppressed is True
    assert flagged.suppression_reason == "allowlist:url_domain:gofile.io (infrastructure-abuse)"
    assert clean.auto_suppressed is False
    assert clean.suppression_reason is None
