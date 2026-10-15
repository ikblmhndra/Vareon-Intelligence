"""`cti_api.services.ioc_providers` -- pemetaan respons provider ke kartu `IocEnrichmentProvider`
(yang sudah dirender `ioc-detail-dialog.tsx`) dan klien AbuseIPDB lewat `httpx.MockTransport`
(tanpa jaringan, tanpa kunci asli)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from cti_api.services import ioc_providers as providers

_DATA: dict[str, Any] = {
    "ipAddress": "203.0.113.9",
    "isPublic": True,
    "abuseConfidenceScore": 87,
    "countryCode": "NL",
    "usageType": "Data Center/Web Hosting/Transit",
    "isp": "Example ISP",
    "domain": "example.net",
    "isTor": False,
    "totalReports": 41,
    "numDistinctUsers": 12,
    "lastReportedAt": "2026-10-14T09:30:00+00:00",
}


@pytest.mark.parametrize(
    ("score", "reports", "verdict"),
    [
        (100, 5, "malicious"),
        (75, 1, "malicious"),
        (74, 1, "suspicious"),
        (25, 1, "suspicious"),
        (24, 1, "clean"),
        (0, 3, "clean"),
        (0, 0, "unknown"),  # tak pernah dilaporkan: AbuseIPDB tidak menyatakan "bersih"
    ],
)
def test_abuseipdb_verdict_thresholds(score: int, reports: int, verdict: str) -> None:
    card = providers.abuseipdb_card({"abuseConfidenceScore": score, "totalReports": reports})

    assert card["verdict"] == verdict
    assert card["score"] == score


def test_abuseipdb_card_carries_the_fields_the_detail_dialog_reads() -> None:
    card = providers.abuseipdb_card(_DATA)

    assert (card["key"], card["name"]) == ("abuseipdb", "AbuseIPDB")
    assert card["raw"] == {
        "abuse_confidence": 87,
        "total_reports": 41,
        "distinct_reporters": 12,
        "last_reported": "2026-10-14T09:30:00+00:00",
        "country": "NL",
        "isp": "Example ISP",
        "usage_type": "Data Center/Web Hosting/Transit",
        "domain": "example.net",
    }
    assert card["tags"] == []
    assert card["malware_families"] == []


def test_abuseipdb_card_drops_empty_fields_and_tags_tor_exits() -> None:
    card = providers.abuseipdb_card(
        {"abuseConfidenceScore": 10, "totalReports": 2, "isTor": True, "isp": None, "domain": ""}
    )

    assert card["raw"] == {"abuse_confidence": 10, "total_reports": 2}
    assert card["tags"] == ["tor"]


def test_skipped_card_explains_itself_without_a_score() -> None:
    card = providers.skipped_card("abuseipdb", "AbuseIPDB", "not a public IP address")

    assert card["verdict"] == "unknown"
    assert "score" not in card
    assert card["raw"] == {"skipped": "not a public IP address"}


@pytest.mark.asyncio
async def test_lookup_abuseipdb_sends_the_key_and_the_ip_and_maps_the_payload() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["Key"]
        seen["accept"] = request.headers["Accept"]
        return httpx.Response(200, json={"data": _DATA})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        card = await providers.lookup_abuseipdb(http, "test-key", "203.0.113.9")

    assert seen["key"] == "test-key"
    assert seen["accept"] == "application/json"
    assert "ipAddress=203.0.113.9" in seen["url"] and "maxAgeInDays=90" in seen["url"]
    assert (card["score"], card["verdict"]) == (87, "malicious")


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 503])
async def test_lookup_abuseipdb_raises_on_http_errors(status: int) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={}))

    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(httpx.HTTPStatusError) as err:
            await providers.lookup_abuseipdb(http, "test-key", "203.0.113.9")

    assert err.value.response.status_code == status


@pytest.mark.asyncio
async def test_lookup_abuseipdb_rejects_a_payload_without_data() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"errors": []}))

    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(ValueError, match="data"):
            await providers.lookup_abuseipdb(http, "test-key", "203.0.113.9")
