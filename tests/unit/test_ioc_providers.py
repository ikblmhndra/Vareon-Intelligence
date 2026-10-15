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


# ── VirusTotal ──────────────────────────────────────────────────────────────────────────────────


def _vt(**stats: int) -> dict[str, Any]:
    base = {"harmless": 0, "malicious": 0, "suspicious": 0, "undetected": 0, "timeout": 0}
    return {"last_analysis_stats": {**base, **stats}}


@pytest.mark.parametrize(
    ("stats", "verdict", "score"),
    [
        ({"malicious": 12, "undetected": 60}, "malicious", 17),
        ({"malicious": 3, "harmless": 70}, "malicious", 4),
        ({"malicious": 1, "harmless": 70}, "suspicious", 1),
        ({"suspicious": 3, "harmless": 70}, "suspicious", 4),
        ({"suspicious": 2, "harmless": 70}, "clean", 3),
        ({"harmless": 60, "undetected": 14}, "clean", 0),
        ({}, "unknown", 0),  # tidak ada mesin yang menilai
    ],
)
def test_virustotal_verdict_and_detection_percentage(
    stats: dict[str, int], verdict: str, score: int
) -> None:
    card = providers.virustotal_card(_vt(**stats))

    assert (card["verdict"], card["score"]) == (verdict, score)


def test_virustotal_card_for_a_file_carries_family_tags_and_the_detection_ratio() -> None:
    attributes = {
        **_vt(malicious=40, harmless=5, undetected=25),
        "reputation": -35,
        "meaningful_name": "invoice.exe",
        "type_description": "Win32 EXE",
        "popular_threat_classification": {"suggested_threat_label": "trojan.agenttesla/msil"},
        "tags": ["peexe", "overlay"],
    }

    card = providers.virustotal_card(attributes)

    assert card["key"] == "virustotal" and card["name"] == "VirusTotal"
    assert card["malware_families"] == ["trojan.agenttesla/msil"]
    assert card["tags"] == ["peexe", "overlay"]
    assert card["raw"] == {
        "detections": "40/70",
        "reputation": -35,
        "file_name": "invoice.exe",
        "file_type": "Win32 EXE",
    }


def test_virustotal_card_for_an_ip_carries_the_network_owner() -> None:
    card = providers.virustotal_card(
        {**_vt(harmless=70), "as_owner": "Example Net", "country": "NL", "reputation": 0}
    )

    assert card["raw"] == {
        "detections": "0/70",
        "reputation": 0,
        "network_owner": "Example Net",
        "country": "NL",
    }


def test_virustotal_url_id_is_unpadded_urlsafe_base64() -> None:
    assert providers.virustotal_url_id("http://example.com/") == "aHR0cDovL2V4YW1wbGUuY29tLw"


@pytest.mark.parametrize(
    ("ioc_type", "value", "path"),
    [
        ("ip", "8.8.8.8", "/api/v3/ip_addresses/8.8.8.8"),
        ("domain", "example.com", "/api/v3/domains/example.com"),
        ("url", "http://example.com/", "/api/v3/urls/aHR0cDovL2V4YW1wbGUuY29tLw"),
        ("sha256", "a" * 64, f"/api/v3/files/{'a' * 64}"),
        ("md5", "b" * 32, f"/api/v3/files/{'b' * 32}"),
    ],
)
@pytest.mark.asyncio
async def test_lookup_virustotal_uses_the_endpoint_for_the_ioc_type(
    ioc_type: str, value: str, path: str
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers["x-apikey"]
        return httpx.Response(200, json={"data": {"attributes": _vt(harmless=10)}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        card = await providers.lookup_virustotal(http, "vt-key", ioc_type, value)

    assert seen == {"path": path, "key": "vt-key"}
    assert card["verdict"] == "clean"


@pytest.mark.asyncio
async def test_lookup_virustotal_treats_404_as_not_seen_before_not_as_an_error() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(404, json={}))

    async with httpx.AsyncClient(transport=transport) as http:
        card = await providers.lookup_virustotal(http, "vt-key", "sha256", "a" * 64)

    assert card["verdict"] == "unknown" and "score" not in card
    assert card["raw"] == {"note": "not seen by VirusTotal"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 503])
async def test_lookup_virustotal_raises_on_other_http_errors(status: int) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json={}))

    async with httpx.AsyncClient(transport=transport) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await providers.lookup_virustotal(http, "vt-key", "ip", "8.8.8.8")


# ── OTX ─────────────────────────────────────────────────────────────────────────────────────────


def _otx(count: int, **extra: Any) -> dict[str, Any]:
    pulses = [
        {
            "name": f"pulse {n}",
            "tags": ["botnet", "c2"] if n % 2 == 0 else ["botnet"],
            "malware_families": [{"display_name": "Emotet"}, "TrickBot"] if n == 0 else [],
        }
        for n in range(count)
    ]
    return {"pulse_info": {"count": count, "pulses": pulses}, **extra}


@pytest.mark.parametrize(
    ("count", "verdict"), [(0, "unknown"), (1, "suspicious"), (2, "suspicious"), (3, "malicious")]
)
def test_otx_verdict_follows_the_pulse_count(count: int, verdict: str) -> None:
    card = providers.otx_card(_otx(count))

    assert card["verdict"] == verdict
    assert "score" not in card  # OTX tidak punya skor 0-100


def test_otx_card_collects_families_tags_and_context() -> None:
    card = providers.otx_card(
        _otx(3, reputation=0, country_name="Netherlands", asn="AS1 Example", validation=[])
    )

    assert card["key"] == "otx" and card["name"] == "AlienVault OTX"
    assert card["malware_families"] == ["Emotet", "TrickBot"]
    assert card["tags"] == ["botnet", "c2"]  # paling sering dulu, tanpa duplikat
    assert card["raw"] == {"pulses": 3, "country": "Netherlands", "asn": "AS1 Example"}


@pytest.mark.parametrize(
    ("ioc_type", "value", "path"),
    [
        ("ip", "8.8.8.8", "/api/v1/indicators/IPv4/8.8.8.8/general"),
        ("ip", "2001:4860:4860::8888", "/api/v1/indicators/IPv6/2001:4860:4860::8888/general"),
        ("domain", "example.com", "/api/v1/indicators/domain/example.com/general"),
        ("sha1", "c" * 40, f"/api/v1/indicators/file/{'c' * 40}/general"),
    ],
)
@pytest.mark.asyncio
async def test_lookup_otx_uses_the_section_for_the_ioc_type(
    ioc_type: str, value: str, path: str
) -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers["X-OTX-API-KEY"]
        return httpx.Response(200, json=_otx(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        card = await providers.lookup_otx(http, "otx-key", ioc_type, value)

    assert seen == {"path": path, "key": "otx-key"}
    assert card["verdict"] == "unknown"


@pytest.mark.asyncio
async def test_lookup_otx_404_is_not_an_error_and_other_statuses_raise() -> None:
    not_found = httpx.MockTransport(lambda request: httpx.Response(404, json={}))
    async with httpx.AsyncClient(transport=not_found) as http:
        card = await providers.lookup_otx(http, "otx-key", "domain", "example.com")
    assert card["raw"] == {"note": "not seen by AlienVault OTX"}

    forbidden = httpx.MockTransport(lambda request: httpx.Response(403, json={}))
    async with httpx.AsyncClient(transport=forbidden) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await providers.lookup_otx(http, "otx-key", "domain", "example.com")
