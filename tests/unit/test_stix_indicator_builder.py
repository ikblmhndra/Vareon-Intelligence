"""Builder indikator STIX yang stabil (P7b): pola, escape, waktu dari baris, flag revoked."""

from __future__ import annotations

import datetime
from typing import Any

from cti_api.services.stix import (
    _build_indicator,
    _ioc_pattern,
    indicator_to_stix,
    stix_ts,
)
from cti_core.db.models.indicator import Indicator
from cti_core.indicator.stix_id import indicator_uuid

_CREATED = datetime.datetime(2026, 10, 1, 1, 2, 3, 456789, tzinfo=datetime.UTC)
_CHANGED = datetime.datetime(2026, 10, 29, 4, 0, 25, 542000, tzinfo=datetime.UTC)


def _ind(**kw: Any) -> Indicator:
    base: dict[str, Any] = {
        "type": "domain",
        "value": "evil.example.com",
        "created_at": _CREATED,
        "feed_changed_at": _CHANGED,
        "valid_from": _CREATED,
        "valid_until": _CHANGED,
        "first_seen_at": _CREATED,
        "last_seen_at": _CHANGED,
        "seen_count": 3,
        "tlp": "amber",
        "auto_suppressed": False,
        "revoked_at": None,
    }
    base.update(kw)
    return Indicator(**base)


def test_stix_ts_millis_utc() -> None:
    assert stix_ts(_CHANGED) == "2026-10-29T04:00:25.542Z"


def test_url_with_path_pattern() -> None:
    assert _ioc_pattern("url_with_path", "http://a/b") == "[url:value = 'http://a/b']"


def test_pattern_escapes_backslash_then_quote() -> None:
    assert _ioc_pattern("url", "a\\'b") == "[url:value = 'a\\\\\\'b']"


def test_indicator_to_stix_stable_times() -> None:
    ind = _ind()
    first, second = indicator_to_stix(ind), indicator_to_stix(ind)
    assert first == second
    assert first is not None
    assert first["created"] == "2026-10-01T01:02:03.456Z"
    assert first["modified"] == "2026-10-29T04:00:25.542Z"
    assert first["valid_until"] == "2026-10-29T04:00:25.542Z"
    assert "revoked" not in first


def test_revoked_and_allowlisted_flagged() -> None:
    revoked = indicator_to_stix(_ind(revoked_at=_CHANGED))
    allow = indicator_to_stix(_ind(auto_suppressed=True))
    assert revoked is not None and revoked["revoked"] is True
    assert allow is not None and allow["revoked"] is True


def test_no_confidence_key() -> None:
    obj = indicator_to_stix(_ind())
    assert obj is not None and "confidence" not in obj


def test_hash_has_no_valid_until() -> None:
    obj = indicator_to_stix(_ind(type="sha256", value="a" * 64, valid_until=None))
    assert obj is not None and "valid_until" not in obj


def test_stix_id_fallback_matches_column() -> None:
    expected = f"indicator--{indicator_uuid('domain', 'evil.example.com')}"
    assert indicator_to_stix(_ind(stix_id=None))["id"] == expected  # type: ignore[index]
    explicit = indicator_uuid("domain", "evil.example.com")
    assert indicator_to_stix(_ind(stix_id=explicit))["id"] == expected  # type: ignore[index]


def test_build_indicator_id_uses_indicator_uuid() -> None:
    obj = _build_indicator("url", "http://a/B", "2026-10-29T00:00:00+00:00")
    assert obj is not None
    assert obj["id"] == f"indicator--{indicator_uuid('url', 'http://a/B')}"
