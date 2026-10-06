"""`cve_tracker.published_at` -- jalur DB-nya di Postgres beneran:

  1. Sink `CveItem` menulis jam publish MITRE, dan item TANPA jam tidak menimpa nilai yang sudah ada
     dengan NULL (mis. hasil backfill).
  2. `tools/ops/backfill_cve_published_at.py`: `load_rows` hanya baris yang NULL (dan menghormati
     `--client`); `apply_findings` hanya mengisi `fill`, tidak pernah `mismatch`, tidak menimpa.

Parser jam dan penilai backfill dites murni di `tests/unit/test_new_cve_published_at.py` dan
`tests/unit/test_backfill_cve_published_at.py`."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveTracker
from cti_scraper.base import ScraperMeta
from cti_scraper.items import CveItem
from cti_scraper.sinks import dispatch
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.ops.backfill_cve_published_at import Finding, Row, apply_findings, load_rows

UTC = datetime.UTC
META = ScraperMeta(id="new_cve", source="New CVE", schedule="0 * * * *")
AT = datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)


@pytest.fixture
def session(db_session: Session) -> Iterator[Session]:
    for cid in ("acme", "globex"):
        db_session.add(Client(client_id=cid, name=cid.title()))
    db_session.flush()
    yield db_session


def tracker(session: Session, cve_id: str, client: str = "acme", **kw: object) -> CveTracker:
    row = CveTracker(cve_id=cve_id, client_id=client, tech="nginx", **kw)
    session.add(row)
    session.flush()
    return row


def stored(session: Session, cve_id: str, client: str = "acme") -> datetime.datetime | None:
    return session.execute(
        select(CveTracker.published_at).where(
            CveTracker.cve_id == cve_id, CveTracker.client_id == client
        )
    ).scalar_one()


# ── sink ──────────────────────────────────────────────────────────────────────


def item(**kw: object) -> CveItem:
    return CveItem(cve_id="CVE-2026-5001", client_id="acme", tech="nginx", **kw)  # type: ignore[arg-type]


def test_sink_writes_the_mitre_publish_time(session: Session) -> None:
    dispatch(item(published=AT.date(), published_at=AT), META, session)

    assert stored(session, "CVE-2026-5001") == AT


def test_sink_without_a_publish_time_keeps_the_value_already_stored(session: Session) -> None:
    tracker(session, "CVE-2026-5001", published_at=AT)

    dispatch(item(summary="ditulis ulang scraper", published_at=None), META, session)

    assert stored(session, "CVE-2026-5001") == AT
    # field lain tetap ikut di-upsert seperti biasa
    row = session.execute(
        select(CveTracker).where(CveTracker.cve_id == "CVE-2026-5001")
    ).scalar_one()
    assert row.summary == "ditulis ulang scraper"


def test_sink_replaces_a_stored_time_when_mitre_gives_a_new_one(session: Session) -> None:
    tracker(session, "CVE-2026-5001", published_at=AT)
    later = AT + datetime.timedelta(hours=2)

    dispatch(item(published_at=later), META, session)

    assert stored(session, "CVE-2026-5001") == later


# ── backfill ──────────────────────────────────────────────────────────────────


def test_load_rows_returns_only_rows_without_published_at(session: Session) -> None:
    tracker(session, "CVE-2026-6001", published=datetime.date(2026, 8, 31))
    tracker(session, "CVE-2026-6002", published_at=AT)

    rows = load_rows(session, None)

    assert [(r.cve_id, r.published) for r in rows] == [
        ("CVE-2026-6001", datetime.date(2026, 8, 31))
    ]


def test_load_rows_can_be_limited_to_one_client(session: Session) -> None:
    tracker(session, "CVE-2026-6003", client="acme")
    tracker(session, "CVE-2026-6003", client="globex")

    assert [r.client_id for r in load_rows(session, "globex")] == ["globex"]
    assert sorted(r.client_id for r in load_rows(session, None)) == ["acme", "globex"]


def test_apply_fills_only_fill_findings_and_never_overwrites(session: Session) -> None:
    a = tracker(session, "CVE-2026-6004")
    b = tracker(session, "CVE-2026-6005")
    c = tracker(session, "CVE-2026-6006", published_at=AT)  # sudah terisi (mis. oleh scraper)
    other = AT + datetime.timedelta(days=1)

    def row(t: CveTracker) -> Row:
        return Row(id=t.id, cve_id=t.cve_id, client_id=t.client_id, published=None)

    done = apply_findings(
        session,
        [
            Finding(row(a), "fill", AT),
            Finding(row(b), "mismatch", AT),
            Finding(row(c), "fill", other),
        ],
    )

    assert done == 1  # c sudah terisi -> `WHERE published_at IS NULL` mencegah penimpaan
    assert stored(session, "CVE-2026-6004") == AT
    assert stored(session, "CVE-2026-6005") is None  # mismatch tidak pernah ditulis
    assert stored(session, "CVE-2026-6006") == AT
