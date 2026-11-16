"""Persist enrich: IOC yang cocok allowlist TETAP disimpan, ditandai `auto_suppressed` + alasan --
Postgres REAL (testcontainers)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from cti_core.db.repositories.indicator import IndicatorRepo
from cti_enrich.routing import RoutingResult
from cti_enrich.stages import extract_iocs as extract_iocs_stage
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.persist import persist
from httpx import AsyncClient
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


@pytest.mark.asyncio
async def test_allowlist_add_with_note(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    """Catatan entri allowlist: di-strip, tampil di daftar, maksimal 300 karakter, kosong jadi
    null, dan menambah ulang entri yang sama tidak menimpa catatan pertama."""
    headers = auth_header(role="admin")
    url = "/api/iocs/allowlist"
    add = await api_client.post(
        url,
        headers=headers,
        json={"type": "url_domain", "value": "note-test.example", "note": "  from IOC 1.2.3.4 "},
    )
    assert add.status_code == 200
    assert add.json()["note"] == "from IOC 1.2.3.4"

    listed = await api_client.get(url, headers=headers)
    entry = next(e for e in listed.json()["entries"] if e["value"] == "note-test.example")
    assert entry["note"] == "from IOC 1.2.3.4"

    too_long = await api_client.post(
        url,
        headers=headers,
        json={"type": "url_domain", "value": "long-note.example", "note": "x" * 301},
    )
    assert too_long.status_code == 422

    blank = await api_client.post(
        url,
        headers=headers,
        json={"type": "url_domain", "value": "blank-note.example", "note": "   "},
    )
    assert blank.json()["note"] is None

    again = await api_client.post(
        url,
        headers=headers,
        json={"type": "url_domain", "value": "note-test.example", "note": "other"},
    )
    assert again.json()["note"] == "from IOC 1.2.3.4"
