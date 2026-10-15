"""`cti_api.services.ioc_enrichment.build_specs` dan `_skip_reason` -- murni, tanpa DB/jaringan."""

from __future__ import annotations

import datetime

import httpx
import pytest
from cti_api.services import ioc_enrichment
from cti_core.config import Settings

from tests.unit.test_config import _settings


def _build(monkeypatch: pytest.MonkeyPatch, **env: str) -> list[ioc_enrichment.ProviderSpec]:
    settings: Settings = _settings(monkeypatch, **env)
    return ioc_enrichment.build_specs(settings, httpx.AsyncClient())


def test_no_key_means_no_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _build(monkeypatch) == []


def test_abuseipdb_spec_is_ip_only_with_a_three_day_ttl_and_the_configured_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (spec,) = _build(monkeypatch, ABUSEIPDB__API_KEY="abuse-key", ABUSEIPDB__RATE="7/hour")

    assert spec.key == "abuseipdb"
    assert spec.types == frozenset({"ip"})
    assert spec.ttl == datetime.timedelta(days=3)
    assert spec.rate == "7/hour"


@pytest.mark.parametrize(
    ("ioc_type", "value", "reason"),
    [
        ("ip", "8.8.8.8", None),
        ("ip", "10.0.0.5", "not a public IP address"),
        ("ip", "198.51.100.7", "not a public IP address"),  # rentang dokumentasi
        ("ip", "not-an-ip", "not a valid IP address"),
        ("domain", "example.test", None),
    ],
)
def test_skip_reason(ioc_type: str, value: str, reason: str | None) -> None:
    assert ioc_enrichment._skip_reason(ioc_type, value) == reason
