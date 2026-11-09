"""`GET /api/cve/lookup/{cve_id}`: lookup langsung satu CVE (mirror, NVD, CIRCL, Exploit-DB, EPSS
paralel). Semua HTTP keluar di-stub (tidak ada akses internet); `fake_redis` untuk limit + cache."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from cti_api.services import cve_live_lookup, cve_lookup
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

CVE = "CVE-2024-3400"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cve_live_lookup"


class Calls:
    def __init__(self) -> None:
        self.nvd = 0
        self.circl = 0
        self.exploitdb = 0
        self.epss = 0


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    c = Calls()

    async def nvd(cve_id: str) -> dict[str, Any] | None:
        c.nvd += 1
        return json.loads((FIXTURES / "nvd_cve_2024_3400.json").read_text())  # type: ignore[no-any-return]

    async def circl(cve_id: str) -> dict[str, Any] | None:
        c.circl += 1
        return json.loads((FIXTURES / "circl_cve_2024_3400.json").read_text())  # type: ignore[no-any-return]

    async def exploitdb(cve_id: str) -> list[dict[str, Any]]:
        c.exploitdb += 1
        return [
            {"title": "PAN-OS RCE", "url": "https://www.exploit-db.com/exploits/1", "posted_on": ""}
        ]

    async def epss(cve_ids: list[str]) -> dict[str, dict[str, Any]]:
        c.epss += 1
        return {cve_ids[0]: {"epss": 0.95, "percentile": 0.99, "date": "2024-04-20"}}

    monkeypatch.setattr(cve_live_lookup, "_fetch_nvd", nvd)
    monkeypatch.setattr(cve_live_lookup, "_fetch_circl", circl)
    monkeypatch.setattr(cve_lookup, "_lookup_exploitdb", exploitdb)
    monkeypatch.setattr(cve_lookup, "_fetch_epss_scores", epss)
    return c


@pytest.fixture
def analyst(auth_header: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth_header(username="alice", role="analyst", client_ids=["default", "acme"])


def statuses(body: dict[str, Any]) -> dict[str, str]:
    return {s["id"]: s["status"] for s in body["sources"]}


async def test_happy_path_merges_sources(
    api_client: AsyncClient, analyst: dict[str, str], calls: Calls
) -> None:
    resp = await api_client.get(f"/api/cve/lookup/{CVE.lower()}", headers=analyst)
    assert resp.status_code == 200
    body = resp.json()
    assert body["cve_id"] == CVE
    assert body["cvss_score"] == 9.8
    assert body["epss_score"] == 0.95
    assert body["exploits"][0]["title"] == "PAN-OS RCE"
    assert body["kev"]["added"] == "2024-04-12"
    assert statuses(body) == {
        "mirror": "not_found",
        "nvd": "ok",
        "circl": "ok",
        "exploitdb": "ok",
        "epss": "ok",
    }


async def test_one_source_timeout_still_200(
    api_client: AsyncClient,
    analyst: dict[str, str],
    calls: Calls,
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: Any,
) -> None:
    async def slow(cve_id: str) -> dict[str, Any] | None:
        await asyncio.sleep(1)
        return None

    monkeypatch.setattr(cve_live_lookup, "_fetch_circl", slow)
    monkeypatch.setattr(cve_live_lookup, "SOURCE_TIMEOUT_S", 0.05)
    resp = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert resp.status_code == 200
    s = statuses(resp.json())
    assert s["circl"] == "timeout"
    assert s["nvd"] == "ok"
    # hasil sebagian tidak di-cache 6 jam: lookup berikutnya mencoba sumber itu lagi
    assert f"cve:lookup:{CVE}" not in fake_redis.values


async def test_source_error_does_not_fail_lookup(
    api_client: AsyncClient, analyst: dict[str, str], calls: Calls, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(cve_id: str) -> list[dict[str, Any]]:
        raise RuntimeError("exploit-db down")

    monkeypatch.setattr(cve_lookup, "_lookup_exploitdb", boom)
    resp = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert resp.status_code == 200
    assert statuses(resp.json())["exploitdb"] == "error"


async def test_user_limit_429(
    api_client: AsyncClient, analyst: dict[str, str], calls: Calls
) -> None:
    for _ in range(cve_live_lookup.USER_LIMIT_PER_MIN):
        assert (await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)).status_code == 200
    resp = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) >= 1


async def test_cache_hit_makes_no_http_call(
    api_client: AsyncClient, analyst: dict[str, str], calls: Calls
) -> None:
    first = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert first.status_code == 200
    before = (calls.nvd, calls.circl, calls.exploitdb, calls.epss)
    second = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert (calls.nvd, calls.circl, calls.exploitdb, calls.epss) == before
    body = second.json()
    assert set(statuses(body).values()) == {"cached"}
    assert body["cvss_score"] == 9.8


async def test_tracked_follows_client_header(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str], calls: Calls
) -> None:
    await AsyncClientRepo(api_session).create(client_id="acme", name="Acme", countries=[])
    api_session.add(CveTracker(cve_id=CVE, client_id="default", tech="PAN-OS"))
    await api_session.flush()

    mine = (await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)).json()
    assert mine["tracked"] is True
    assert mine["tracker_tech"] == "PAN-OS"

    # cache publik sudah terisi dari panggilan pertama; client lain tetap tidak melihat tracker A
    other = (
        await api_client.get(f"/api/cve/lookup/{CVE}", headers={**analyst, "X-Client-ID": "acme"})
    ).json()
    assert other["tracked"] is False
    assert other["tracker_tech"] is None


async def test_nvd_bucket_exhausted_marks_rate_limited(
    api_client: AsyncClient, analyst: dict[str, str], calls: Calls, fake_redis: Any
) -> None:
    fake_redis._counts["cve:lookup:nvd"] = cve_live_lookup.NVD_BUCKET_MAX
    resp = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert resp.status_code == 200
    s = statuses(resp.json())
    assert s["nvd"] == "rate_limited"
    assert s["circl"] == "ok"
    assert calls.nvd == 0


async def test_junk_id_is_422(api_client: AsyncClient, analyst: dict[str, str]) -> None:
    resp = await api_client.get("/api/cve/lookup/not-a-cve", headers=analyst)
    assert resp.status_code == 422


async def test_lookup_writes_no_tracker_row(
    api_client: AsyncClient, api_session: AsyncSession, analyst: dict[str, str], calls: Calls
) -> None:
    resp = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert resp.status_code == 200
    assert (await api_session.scalar(select(func.count()).select_from(CveTracker))) == 0
    audit = (
        await api_session.scalars(
            select(AuditLogEntry).where(AuditLogEntry.action == "cve_live_lookup")
        )
    ).all()
    assert len(audit) == 1


async def test_mirror_failure_keeps_transaction_usable(
    api_client: AsyncClient,
    api_session: AsyncSession,
    analyst: dict[str, str],
    calls: Calls,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Query mirror yang gagal membatalkan transaksi Postgres; savepoint menjaga pembacaan
    tracker sesudahnya tetap jalan (bukan 500)."""
    api_session.add(CveTracker(cve_id=CVE, client_id="default", tech="PAN-OS"))
    await api_session.flush()

    async def broken(self: Any, cve_id: str, client_id: str) -> None:
        await self.session.execute(text("select * from tabel_tidak_ada"))

    monkeypatch.setattr(cve_live_lookup.AsyncCatalogRepo, "get_cve", broken)
    resp = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert resp.status_code == 200
    body = resp.json()
    assert statuses(body)["mirror"] == "error"
    assert body["tracked"] is True


async def test_counter_without_ttl_is_healed(
    api_client: AsyncClient,
    analyst: dict[str, str],
    calls: Calls,
    fake_redis: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kunci limit tanpa TTL (crash antara INCR dan EXPIRE) mendapat TTL lagi di panggilan
    berikutnya, bukan terkunci selamanya."""
    expired: list[str] = []
    original = fake_redis.expire

    async def spy(key: str, seconds: int) -> bool:
        expired.append(key)
        return await original(key, seconds)

    monkeypatch.setattr(fake_redis, "expire", spy)
    fake_redis._counts["cve:lookup:user:alice"] = 3
    resp = await api_client.get(f"/api/cve/lookup/{CVE}", headers=analyst)
    assert resp.status_code == 200
    assert "cve:lookup:user:alice" in expired
