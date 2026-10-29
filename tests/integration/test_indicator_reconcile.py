"""`IndicatorRepo.reconcile_validity`: isi/sinkron `valid_until` dari TTL settings (P7a 3.3)."""

from __future__ import annotations

import datetime

from cti_core.config import IndicatorSettings
from cti_core.db.models.indicator import Indicator
from cti_core.db.models.report_state import JobState
from cti_core.db.repositories.indicator import IndicatorRepo
from cti_core.indicator.validity import ttl_fingerprint
from sqlalchemy import delete
from sqlalchemy.orm import Session

_SEEN = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
_KEY = "indicator.ttl_fingerprint"


def _seed(session: Session) -> dict[str, Indicator]:
    session.execute(delete(JobState).where(JobState.key == _KEY))
    rows = {
        t: Indicator(type=t, value=f"rec-{t}", last_seen_at=_SEEN, valid_until=None)
        for t in ("ip", "domain", "sha256")
    }
    session.add_all(rows.values())
    session.flush()
    return rows


def _stored(session: Session) -> object:
    row = session.get(JobState, _KEY)
    assert row is not None
    session.refresh(row)
    return row.value


def test_first_run_fills_valid_until(db_session: Session) -> None:
    rows = _seed(db_session)
    cfg = IndicatorSettings()
    out = IndicatorRepo(db_session).reconcile_validity(cfg)
    assert out["skipped"] == 0 and out["updated"] >= 2
    for r in rows.values():
        db_session.refresh(r)
    assert rows["ip"].valid_until == _SEEN + datetime.timedelta(days=30)
    assert rows["domain"].valid_until == _SEEN + datetime.timedelta(days=90)
    assert rows["sha256"].valid_until is None
    assert _stored(db_session) == ttl_fingerprint(cfg)


def test_second_run_noop(db_session: Session) -> None:
    _seed(db_session)
    repo = IndicatorRepo(db_session)
    repo.reconcile_validity(IndicatorSettings())
    assert repo.reconcile_validity(IndicatorSettings()) == {"updated": 0, "skipped": 1}


def test_ttl_change_resyncs(db_session: Session) -> None:
    rows = _seed(db_session)
    repo = IndicatorRepo(db_session)
    repo.reconcile_validity(IndicatorSettings())
    old = _stored(db_session)
    assert repo.reconcile_validity(IndicatorSettings(ttl_ip_days=7))["skipped"] == 0
    db_session.refresh(rows["ip"])
    assert rows["ip"].valid_until == _SEEN + datetime.timedelta(days=7)
    assert _stored(db_session) != old


def test_revoked_rows_untouched(db_session: Session) -> None:
    keep = _SEEN + datetime.timedelta(days=500)
    row = Indicator(
        type="ip", value="rec-revoked", last_seen_at=_SEEN, valid_until=keep, revoked_at=_SEEN
    )
    db_session.add(row)
    _seed(db_session)
    IndicatorRepo(db_session).reconcile_validity(IndicatorSettings())
    db_session.refresh(row)
    assert row.valid_until == keep


def test_matching_fingerprint_fills_null_rows(db_session: Session) -> None:
    rows = _seed(db_session)
    revoked = Indicator(
        type="ip", value="rec-null-revoked", last_seen_at=_SEEN, valid_until=None, revoked_at=_SEEN
    )
    db_session.add(revoked)
    repo = IndicatorRepo(db_session)
    cfg = IndicatorSettings()
    repo.reconcile_validity(cfg)
    # Simulasi kode lama (rollback) yang menyisipkan baris NULL setelah fingerprint tersimpan.
    db_session.refresh(rows["ip"])  # ORM masih menyimpan None lama; tanpa refresh flush tak menulis
    rows["ip"].valid_until = None
    db_session.flush()
    out = repo.reconcile_validity(cfg)
    assert out == {"updated": 1, "skipped": 1}
    for r in (*rows.values(), revoked):
        db_session.refresh(r)
    assert rows["ip"].valid_until == _SEEN + datetime.timedelta(days=30)
    assert revoked.valid_until is None
    assert rows["sha256"].valid_until is None


def test_url_with_path_gets_url_ttl(db_session: Session) -> None:
    _seed(db_session)
    row = Indicator(type="url_with_path", value="rec-uwp", last_seen_at=_SEEN, valid_until=None)
    db_session.add(row)
    db_session.flush()
    cfg = IndicatorSettings()
    IndicatorRepo(db_session).reconcile_validity(cfg)
    db_session.refresh(row)
    assert row.valid_until == _SEEN + datetime.timedelta(days=cfg.ttl_url_days)
