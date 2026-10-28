"""cti_core.indicator.validity -- TTL per tipe indikator."""

import datetime

import pytest
from cti_core.config import IndicatorSettings
from cti_core.indicator.validity import extend, ttl_days, ttl_fingerprint

CFG = IndicatorSettings()
NOW = datetime.datetime(2026, 10, 29, tzinfo=datetime.UTC)


def _d(n: int) -> datetime.timedelta:
    return datetime.timedelta(days=n)


def test_ttl_days() -> None:
    assert ttl_days("ip", CFG) == 30
    assert ttl_days("url_with_path", CFG) == 90
    assert ttl_days("sha256", CFG) is None
    with pytest.raises(ValueError):
        ttl_days("cve", CFG)


def test_extend_hash_stays_null() -> None:
    assert extend(None, "sha1", NOW, CFG) is None


def test_extend_from_null_non_hash() -> None:
    assert extend(None, "ip", NOW, CFG) == NOW + _d(30)


def test_extend_never_shortens() -> None:
    assert extend(NOW + _d(80), "domain", NOW, CFG) == NOW + _d(90)
    assert extend(NOW + _d(200), "domain", NOW, CFG) == NOW + _d(200)


def test_ttl_fingerprint() -> None:
    assert ttl_fingerprint(CFG) == ttl_fingerprint(IndicatorSettings())
    assert ttl_fingerprint(CFG) != ttl_fingerprint(IndicatorSettings(ttl_ip_days=31))
