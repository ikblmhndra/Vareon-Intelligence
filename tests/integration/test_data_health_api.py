"""`GET /api/data-health` (ROADMAP #24 PR-B): angka halaman Data health sama dengan query
reproduksi audit -- kegagalan enrichment yang menunggu replay, antrian `enrich`, kesegaran sumber,
dan cakupan enrichment IOC (kartu `skipped` tidak dihitung)."""

from __future__ import annotations

import datetime

from cti_core.db.models.article import RejectedArticle
from cti_core.db.models.ioc import IOC
from cti_core.db.repositories.article import AsyncArticleRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


def _rejected(n: int, kind: str | None, age: datetime.timedelta) -> RejectedArticle:
    return RejectedArticle(
        url=f"https://example.com/r{n}",
        url_hash=f"{n:064d}",
        title=f"Rejected {n}",
        source="S",
        reason="x",
        failure_kind=kind,
        rejected_at=datetime.datetime.now(datetime.UTC) - age,
    )


def _ioc(value: str, type_: str, providers: list[dict[str, object]]) -> IOC:
    return IOC(type=type_, value=value, enrichment={"providers": providers} if providers else {})


async def test_data_health_reports_failures_queue_freshness_and_ioc_coverage(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    h = datetime.timedelta(hours=1)
    api_session.add_all(
        [
            _rejected(1, "transient", 2 * h),
            _rejected(2, "permanent", 72 * h),
            _rejected(3, "permanent", 24 * 10 * h),  # di luar 7 hari, tetap menunggu replay
            _rejected(4, None, 3 * h),  # ditolak klasifikasi: bukan kegagalan
        ]
    )
    await AsyncArticleRepo(api_session).upsert(
        url="https://example.com/a1", title="A1", source="S", posted_on=datetime.date.today()
    )
    real = {"key": "abuseipdb", "name": "AbuseIPDB", "verdict": "malicious", "raw": {"score": 90}}
    skipped = {
        "key": "abuseipdb",
        "name": "AbuseIPDB",
        "verdict": "unknown",
        "raw": {"skipped": "private"},
    }
    api_session.add_all(
        [
            _ioc("1.2.3.4", "ip", [real]),
            _ioc("10.0.0.1", "ip", [skipped]),
            _ioc("evil.example", "domain", []),
        ]
    )
    await api_session.flush()
    fake_redis.lists["enrich"] = 7

    resp = await api_client.get("/api/data-health", headers=auth_header(role="viewer"))
    assert resp.status_code == 200
    body = resp.json()

    enrichment = body["enrichment"]
    assert enrichment["failed_24h"] == 1
    assert enrichment["failed_7d"] == 2
    assert enrichment["pending_replay"] == 3
    assert enrichment["processed_7d"] == 4  # 1 artikel + 3 baris rejected dalam 7 hari
    assert enrichment["last_failure_at"] is not None

    assert body["queues"]["enrich_depth"] == 7
    assert body["queues"]["enrich_max_depth"] > 0

    assert body["sources"]["articles_newest_at"] is not None
    assert body["sources"]["iocs_newest_at"] is not None
    assert body["sources"]["tweets_newest_at"] is None

    coverage = {c["type"]: (c["total"], c["enriched"]) for c in body["ioc_enrichment"]}
    assert coverage["ip"] == (2, 1)
    assert coverage["domain"] == (1, 0)

    assert body["scrapers"]["scheduler"]["state"] == "unknown"
    assert isinstance(body["scrapers"]["counts"], dict)


async def test_data_health_requires_login(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/data-health")).status_code == 401


async def test_data_health_survives_a_redis_outage(
    api_client: AsyncClient, auth_header, fake_redis, monkeypatch
) -> None:
    async def boom(key: str) -> int:
        raise ConnectionError("redis down")

    monkeypatch.setattr(fake_redis, "llen", boom)
    body = (await api_client.get("/api/data-health", headers=auth_header())).json()
    assert body["queues"]["enrich_depth"] is None
