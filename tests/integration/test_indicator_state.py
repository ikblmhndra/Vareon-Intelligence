"""`Indicator.state` / `usable`: sisi Python dan sisi SQL harus sepakat -- Postgres REAL."""

from __future__ import annotations

import datetime

from cti_core.db.models.indicator import Indicator
from sqlalchemy import select
from sqlalchemy.orm import Session

_NOW = datetime.datetime.now(datetime.UTC)
_DAY = datetime.timedelta(days=1)

_CASES: dict[str, dict[str, object]] = {
    "revoked": {"revoked_at": _NOW, "auto_suppressed": True},
    "allowlisted": {"auto_suppressed": True},
    "expired": {"valid_until": _NOW - _DAY},
    "active-null": {"valid_until": None},
    "active-future": {"valid_until": _NOW + _DAY},
}
_STATE = {
    "revoked": "revoked",
    "allowlisted": "allowlisted",
    "expired": "expired",
    "active-null": "active",
    "active-future": "active",
}


def test_state_python_and_sql_agree(db_session: Session) -> None:
    rows = {
        name: Indicator(type="domain", value=f"{name}.example", **kw) for name, kw in _CASES.items()
    }
    db_session.add_all(rows.values())
    db_session.flush()

    for name, row in rows.items():
        assert row.state == _STATE[name], name
        assert (
            db_session.execute(select(Indicator.state).where(Indicator.id == row.id)).scalar_one()
            == _STATE[name]
        )

    usable = set(db_session.execute(select(Indicator.value).where(Indicator.usable)).scalars())
    assert "revoked.example" not in usable
    assert "allowlisted.example" not in usable
    assert {"expired.example", "active-null.example", "active-future.example"} <= usable
    assert rows["expired"].usable and not rows["revoked"].usable
