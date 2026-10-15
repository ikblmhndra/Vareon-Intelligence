"""`cti_api.services.ioc_enrichment.enrich_pending` -- Postgres REAL (testcontainers), provider
palsu (tanpa jaringan). Memakai `api_session` (mode savepoint): servisnya meng-commit per IOC, jadi
fixture `async_db_session` biasa akan membocorkan data ke test lain.

Yang dikunci: pemilihan IOC (tipe, FP-suppressed, TTL, terbaru dulu), bentuk yang ditulis ke
`iocs.enrichment` (kontrak yang dibaca UI), dan isolasi kegagalan: satu provider/IOC gagal tidak
menggagalkan yang lain, dan log tak pernah memuat pesan exception (bisa membawa potongan kunci)."""

from __future__ import annotations

import datetime
from collections.abc import Awaitable, Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from cti_api.services.ioc_enrichment import ProviderSpec, build_specs, enrich_pending
from cti_core.db.models.ioc import IOC
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

pytestmark = pytest.mark.asyncio

NOW = datetime.datetime(2026, 10, 15, 12, 0, tzinfo=datetime.UTC)
# IP publik sungguhan (resolver DNS terkenal): rentang dokumentasi (198.51.100.0/24 dan
# 203.0.113.0/24) bukan `is_global`, jadi dilewati sebagai non-publik. Tanpa panggilan jaringan.
PUBLIC = ["8.8.8.8", "1.1.1.1", "9.9.9.9", "4.4.4.4", "8.8.4.4"]


def _card(key: str = "abuseipdb", score: int = 3) -> dict[str, Any]:
    return {
        "key": key,
        "name": key.title(),
        "verdict": "clean",
        "score": score,
        "raw": {},
        "tags": [],
        "malware_families": [],
    }


class FakeLookup:
    """Mencatat nilai yang di-lookup; `errors` = {nilai: exception} untuk simulasi kegagalan."""

    def __init__(self, errors: dict[str, Exception] | None = None) -> None:
        self.values: list[str] = []
        self.errors = errors or {}

    async def __call__(self, ioc_type: str, value: str) -> dict[str, Any]:
        self.values.append(value)
        if value in self.errors:
            raise self.errors[value]
        return _card()


def _spec(lookup: Callable[[str, str], Awaitable[dict[str, Any]]], **kw: Any) -> ProviderSpec:
    base: dict[str, Any] = {
        "key": "abuseipdb",
        "name": "AbuseIPDB",
        "types": frozenset({"ip"}),
        "ttl": datetime.timedelta(days=3),
        "rate": "40/hour",
        "min_interval": 0.0,
        "lookup": lookup,
    }
    base.update(kw)
    return ProviderSpec(**base)


def _settings_with(**providers: SimpleNamespace) -> SimpleNamespace:
    """`Settings` mini untuk `build_specs`: provider yang tidak disebut kuncinya kosong (mati)."""
    off = SimpleNamespace(api_key="", rate="1/hour")
    return SimpleNamespace(**{"abuseipdb": off, "virustotal": off, "otx": off, **providers})


def _allow_all(key: str, rate: str) -> bool:
    return True


async def _ioc(session: AsyncSession, type_: str, value: str, **kw: Any) -> IOC:
    kw.setdefault("last_seen_at", NOW)
    ioc = IOC(type=type_, value=value, **kw)
    session.add(ioc)
    await session.flush()
    return ioc


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.test")
    return httpx.HTTPStatusError("boom", request=request, response=httpx.Response(status))


def _stamp(days_ago: float) -> str:
    return (NOW - datetime.timedelta(days=days_ago)).isoformat()


async def test_enriches_unsuppressed_ips_newest_first_and_writes_the_ui_contract(
    api_session: AsyncSession,
) -> None:
    older = await _ioc(api_session, "ip", PUBLIC[0], last_seen_at=NOW - datetime.timedelta(days=2))
    newer = await _ioc(api_session, "ip", PUBLIC[1])
    domain = await _ioc(api_session, "domain", "example.test")
    suppressed = await _ioc(api_session, "ip", PUBLIC[2], auto_suppressed=True)
    lookup = FakeLookup()

    summary = await enrich_pending(api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW)

    assert lookup.values == [PUBLIC[1], PUBLIC[0]]
    assert summary["abuseipdb"]["checked"] == 2
    for ioc in (newer, older):
        await api_session.refresh(ioc)
        (provider,) = ioc.enrichment["providers"]
        assert provider["key"] == "abuseipdb" and provider["score"] == 3
        assert provider["checked_at"] == NOW.isoformat()
        assert ioc.enrichment["updated_at"] == "2026-10-15 12:00 UTC"
    for untouched in (domain, suppressed):
        await api_session.refresh(untouched)
        assert untouched.enrichment == {}


async def test_fresh_results_are_not_rechecked_but_stale_ones_replace_their_own_card(
    api_session: AsyncSession,
) -> None:
    fresh = await _ioc(
        api_session,
        "ip",
        PUBLIC[0],
        enrichment={"providers": [{**_card(score=9), "checked_at": _stamp(1)}]},
    )
    stale = await _ioc(
        api_session,
        "ip",
        PUBLIC[1],
        enrichment={
            "providers": [
                {**_card("virustotal", score=50), "checked_at": _stamp(1)},
                {**_card(score=9), "checked_at": _stamp(10)},
            ]
        },
    )
    lookup = FakeLookup()

    await enrich_pending(api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW)

    assert lookup.values == [PUBLIC[1]]
    await api_session.refresh(fresh)
    assert fresh.enrichment["providers"][0]["score"] == 9
    await api_session.refresh(stale)
    by_key = {p["key"]: p for p in stale.enrichment["providers"]}
    assert sorted(by_key) == ["abuseipdb", "virustotal"]  # satu kartu per provider, tak ganda
    assert by_key["abuseipdb"]["score"] == 3
    assert by_key["abuseipdb"]["checked_at"] == NOW.isoformat()
    assert by_key["virustotal"]["score"] == 50  # milik provider lain tak tersentuh


async def test_a_defanged_ip_is_refanged_before_the_lookup(
    api_session: AsyncSession,
) -> None:
    await _ioc(api_session, "ip", "208[.]67[.]222[.]222")
    lookup = FakeLookup()

    await enrich_pending(api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW)

    assert lookup.values == ["208.67.222.222"]


async def test_a_non_public_ip_is_marked_skipped_without_a_lookup_or_budget(
    api_session: AsyncSession,
) -> None:
    ioc = await _ioc(api_session, "ip", "10.0.0.5")
    lookup = FakeLookup()
    asked: list[str] = []

    def allow(key: str, rate: str) -> bool:
        asked.append(key)
        return True

    summary = await enrich_pending(api_session, specs=[_spec(lookup)], allow=allow, now=NOW)

    assert lookup.values == [] and asked == []
    assert summary["abuseipdb"]["skipped"] == 1
    await api_session.refresh(ioc)
    (provider,) = ioc.enrichment["providers"]
    assert provider["verdict"] == "unknown" and "score" not in provider
    assert provider["checked_at"] == NOW.isoformat()  # tidak dipilih ulang tiap run


async def test_stops_when_the_provider_budget_runs_out(api_session: AsyncSession) -> None:
    for n in range(1, 4):
        await _ioc(
            api_session,
            "ip",
            PUBLIC[n - 1],
            last_seen_at=NOW - datetime.timedelta(hours=n),
        )
    lookup = FakeLookup()
    grants = iter([True, False])

    summary = await enrich_pending(
        api_session,
        specs=[_spec(lookup)],
        allow=lambda key, rate: next(grants),
        now=NOW,
    )

    assert lookup.values == [PUBLIC[0]]
    assert summary["abuseipdb"]["checked"] == 1
    assert summary["abuseipdb"]["stopped"] == "budget"


async def test_one_failed_lookup_does_not_stop_the_others_and_leaves_no_card(
    api_session: AsyncSession,
) -> None:
    bad = await _ioc(api_session, "ip", PUBLIC[0])
    good = await _ioc(api_session, "ip", PUBLIC[1], last_seen_at=NOW - datetime.timedelta(hours=1))
    lookup = FakeLookup({PUBLIC[0]: httpx.ConnectError("down")})

    summary = await enrich_pending(api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW)

    assert summary["abuseipdb"]["failed"] == 1 and summary["abuseipdb"]["checked"] == 1
    await api_session.refresh(bad)
    await api_session.refresh(good)
    assert bad.enrichment == {}
    assert [p["key"] for p in good.enrichment["providers"]] == ["abuseipdb"]


@pytest.mark.parametrize("status", [401, 403, 429])
async def test_an_auth_or_quota_error_stops_that_provider_for_the_run(
    api_session: AsyncSession, status: int
) -> None:
    await _ioc(api_session, "ip", PUBLIC[0])
    await _ioc(api_session, "ip", PUBLIC[1], last_seen_at=NOW - datetime.timedelta(hours=1))
    lookup = FakeLookup({PUBLIC[0]: _http_error(status)})

    summary = await enrich_pending(api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW)

    assert lookup.values == [PUBLIC[0]]  # tidak lanjut menghantam provider yang menolak
    assert summary["abuseipdb"]["stopped"] == f"HTTP {status}"


async def test_three_failures_in_a_row_stop_the_provider(api_session: AsyncSession) -> None:
    for n in range(1, 6):
        await _ioc(
            api_session,
            "ip",
            PUBLIC[n - 1],
            last_seen_at=NOW - datetime.timedelta(hours=n),
        )
    errors = {PUBLIC[n - 1]: _http_error(503) for n in range(1, 6)}
    lookup = FakeLookup(errors)

    summary = await enrich_pending(api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW)

    assert len(lookup.values) == 3
    assert summary["abuseipdb"]["stopped"] == "consecutive_failures"


async def test_max_per_run_caps_the_batch(api_session: AsyncSession) -> None:
    for n in range(1, 6):
        await _ioc(
            api_session,
            "ip",
            PUBLIC[n - 1],
            last_seen_at=NOW - datetime.timedelta(hours=n),
        )
    lookup = FakeLookup()

    await enrich_pending(
        api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW, max_per_run=2
    )

    assert len(lookup.values) == 2


async def test_failure_logs_carry_the_error_class_and_status_but_never_the_message(
    api_session: AsyncSession,
) -> None:
    await _ioc(api_session, "ip", PUBLIC[0])
    lookup = FakeLookup({PUBLIC[0]: httpx.ConnectError("leaked-key-abc123 in message")})

    with capture_logs() as logs:
        await enrich_pending(api_session, specs=[_spec(lookup)], allow=_allow_all, now=NOW)

    failed = [entry for entry in logs if entry["event"] == "ioc_enrich_failed"]
    assert failed and failed[0]["error"] == "ConnectError"
    assert "leaked-key" not in str(logs)


async def test_the_pacing_delay_runs_between_lookups(api_session: AsyncSession) -> None:
    for n in range(1, 4):
        await _ioc(
            api_session,
            "ip",
            PUBLIC[n - 1],
            last_seen_at=NOW - datetime.timedelta(hours=n),
        )
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    await enrich_pending(
        api_session,
        specs=[_spec(FakeLookup(), min_interval=15.0)],
        allow=_allow_all,
        now=NOW,
        sleep=fake_sleep,
    )

    assert slept == [15.0, 15.0]  # di antara tiga lookup, bukan sebelum yang pertama


async def test_build_specs_wires_the_real_abuseipdb_client_end_to_end(
    api_session: AsyncSession,
) -> None:
    """`build_specs` + `lookup_abuseipdb` + `enrich_pending` + repo, hanya HTTP-nya yang palsu."""
    ioc = await _ioc(api_session, "ip", PUBLIC[0])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        data = {"abuseConfidenceScore": 91, "totalReports": 30, "countryCode": "US"}
        return httpx.Response(200, json={"data": data})

    settings = _settings_with(abuseipdb=SimpleNamespace(api_key="test-key", rate="40/hour"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        specs = build_specs(settings, http)  # type: ignore[arg-type]
        summary = await enrich_pending(api_session, specs=specs, allow=_allow_all, now=NOW)

    assert summary["abuseipdb"]["checked"] == 1
    assert requests[0].headers["Key"] == "test-key"
    assert f"ipAddress={PUBLIC[0]}" in str(requests[0].url)
    await api_session.refresh(ioc)
    (card,) = ioc.enrichment["providers"]
    assert (card["verdict"], card["score"], card["raw"]["country"]) == ("malicious", 91, "US")


async def test_virustotal_and_otx_are_wired_and_a_404_becomes_an_unknown_card(
    api_session: AsyncSession,
) -> None:
    file_ioc = await _ioc(api_session, "sha256", "a" * 64)
    domain_ioc = await _ioc(
        api_session, "domain", "evil.example", last_seen_at=NOW - datetime.timedelta(hours=1)
    )
    paths: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append((request.url.host, request.url.path))
        if request.url.host == "www.virustotal.com":
            return httpx.Response(404, json={})  # belum pernah dilihat VirusTotal
        pulses = [{"name": "p", "tags": ["c2"], "malware_families": []}] * 3
        return httpx.Response(200, json={"pulse_info": {"count": 3, "pulses": pulses}})

    settings = _settings_with(
        virustotal=SimpleNamespace(api_key="vt-key", rate="20/hour"),
        otx=SimpleNamespace(api_key="otx-key", rate="300/hour"),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        specs = build_specs(settings, http)  # type: ignore[arg-type]
        specs = [replace(s, min_interval=0.0) for s in specs]  # tanpa jeda 15 detik di tes
        summary = await enrich_pending(api_session, specs=specs, allow=_allow_all, now=NOW)

    assert [s.key for s in specs] == ["virustotal", "otx"]
    assert summary["virustotal"]["checked"] == 2 and summary["otx"]["checked"] == 2
    assert ("www.virustotal.com", f"/api/v3/files/{'a' * 64}") in paths
    assert ("otx.alienvault.com", "/api/v1/indicators/domain/evil.example/general") in paths

    await api_session.refresh(file_ioc)
    cards = {c["key"]: c for c in file_ioc.enrichment["providers"]}
    assert cards["virustotal"]["verdict"] == "unknown"
    assert cards["virustotal"]["raw"] == {"note": "not seen by VirusTotal"}
    assert cards["otx"]["verdict"] == "malicious" and cards["otx"]["tags"] == ["c2"]
    await api_session.refresh(domain_ioc)
    assert sorted(c["key"] for c in domain_ioc.enrichment["providers"]) == ["otx", "virustotal"]
