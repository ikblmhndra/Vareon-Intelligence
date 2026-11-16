"""Seri harian `/api/spikes` (`daily`) dan model respons bertipe."""

from __future__ import annotations

import datetime

from cti_api.schemas.spike import SpikesResponse
from cti_api.services.spike import _daily_series, _date_axis

_D1 = datetime.date(2026, 11, 1)


def test_daily_zero_fill() -> None:
    d2, d3 = _D1 + datetime.timedelta(days=1), _D1 + datetime.timedelta(days=2)
    raw = [(_D1, "A", 3), (d3, "A", 1), (d2, "B", 5)]
    assert _daily_series(raw, ["A"], _D1, d3) == {"A": [3, 0, 1]}


def test_date_axis_inclusive() -> None:
    assert len(_date_axis(_D1, _D1 + datetime.timedelta(days=29))) == 30


def test_spikes_response_model_accepts_service_shape() -> None:
    d = {
        "threat_actors": [
            {
                "entity": "LockBit",
                "date": "2026-11-07",
                "count": 9,
                "baseline_mean": 1.5,
                "z_score": 3.2,
                "severity": "high",
                "entity_id": None,
            }
        ],
        "countries": [],
        "industries": [],
        "overall": [],
        "generated_at": "2026-11-08T00:00:00Z",
        "parameters": {"lookback_days": 30, "z_threshold": 2.0, "recent_window": "last 7 days"},
        "daily": {
            "dates": ["2026-11-07", "2026-11-08"],
            "threat_actors": {"LockBit": [9, 0]},
            "countries": {},
            "industries": {},
            "overall": [9, 0],
        },
    }
    assert SpikesResponse.model_validate(d).model_dump() == d
