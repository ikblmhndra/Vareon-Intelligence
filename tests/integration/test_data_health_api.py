"""`GET /api/data-health` (ROADMAP #24 PR-B): angka halaman Data health sama dengan query
reproduksi audit -- kegagalan enrichment yang menunggu replay, antrian `enrich`, kesegaran sumber,
dan cakupan enrichment IOC (kartu `skipped` tidak dihitung)."""

from __future__ import annotations

import datetime

from cti_core.db.models.article import RejectedArticle
from cti_core.db.models.ioc import IOC
from cti_core.db.models.llm_call import LlmCall
from cti_core.db.repositories.article import AsyncArticleRepo
from httpx import AsyncClient
from sqlalchemy import delete
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

    resp = await api_client.get("/api/data-health", headers=auth_header(role="analyst"))
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


def _call(
    task: str,
    status: str,
    age: datetime.timedelta,
    *,
    http_status: int | None = None,
    error_type: str | None = None,
    tokens: tuple[int, int] | None = (100, 20),
) -> LlmCall:
    return LlmCall(
        at=datetime.datetime.now(datetime.UTC) - age,
        task=task,
        model="m",
        prompt_version="abcd1234",
        status=status,
        error_type=error_type,
        http_status=http_status,
        prompt_tokens=tokens[0] if tokens else None,
        completion_tokens=tokens[1] if tokens else None,
        latency_ms=500,
    )


async def test_data_health_llm_block_failing_with_parked_and_usage(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    # Isolasi: baris llm_calls / rejected_articles milik test lain di DB bersama dibuang di
    # transaksi test ini (di-rollback saat teardown).
    await api_session.execute(delete(LlmCall))
    await api_session.execute(delete(RejectedArticle))
    h = datetime.timedelta(hours=1)
    now = datetime.datetime.now(datetime.UTC)
    api_session.add_all(
        [
            _call("classify", "ok", 2 * h),
            _call(
                "ttp",
                "error",
                h,
                http_status=400,
                error_type="BadRequestError",
                tokens=None,
            ),
            _call("classify", "ok", 3 * 24 * h),
        ]
    )
    r_ok = _rejected(1, "transient", h)
    r_cap = _rejected(2, "config", h)
    r_cap.auto_replay_count = 3
    r_perm = _rejected(3, "permanent", h)
    r_replayed = _rejected(4, "json", h)
    r_replayed.auto_replay_count = 1
    r_replayed.last_auto_replay_at = now - 2 * h
    r_old_replay = _rejected(5, "transient", h)
    r_old_replay.auto_replay_count = 2
    r_old_replay.last_auto_replay_at = now - 30 * h
    api_session.add_all([r_ok, r_cap, r_perm, r_replayed, r_old_replay, _rejected(6, None, h)])
    await api_session.flush()

    resp = await api_client.get("/api/data-health", headers=auth_header(role="analyst"))
    assert resp.status_code == 200
    llm = resp.json()["llm"]

    assert llm["status"] == "failing"
    assert llm["last_call_at"] is not None
    assert llm["last_ok_at"] is not None
    err = llm["last_error"]
    assert err["task"] == "ttp"
    assert err["error_type"] == "BadRequestError"
    assert err["http_status"] == 400
    assert err["at"] is not None

    assert llm["parked"] == {"total": 5, "auto_eligible": 3, "auto_replays_24h": 1}

    u24 = {u["task"]: u for u in llm["usage_24h"]}
    assert set(u24) == {"classify", "ttp"}
    assert u24["classify"]["calls"] == 1
    assert u24["classify"]["prompt_tokens"] == 100
    assert u24["ttp"]["errors"] == 1
    assert u24["ttp"]["prompt_tokens"] is None
    assert u24["ttp"]["completion_tokens"] is None
    assert u24["ttp"]["prompt_version"] == "abcd1234"
    u7 = {u["task"]: u for u in llm["usage_7d"]}
    assert u7["classify"]["calls"] == 2


async def test_data_health_llm_block_ok_when_latest_call_succeeded(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    await api_session.execute(delete(LlmCall))
    h = datetime.timedelta(hours=1)
    api_session.add_all([_call("ttp", "error", 3 * h, http_status=500), _call("classify", "ok", h)])
    await api_session.flush()
    llm = (await api_client.get("/api/data-health", headers=auth_header())).json()["llm"]
    assert llm["status"] == "ok"
    assert llm["last_error"]["http_status"] == 500


async def test_data_health_llm_status_unknown_without_calls(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    await api_session.execute(delete(LlmCall))
    await api_session.flush()
    llm = (await api_client.get("/api/data-health", headers=auth_header())).json()["llm"]
    assert llm["status"] == "unknown"
    assert llm["last_call_at"] is None
    assert llm["last_ok_at"] is None
    assert llm["last_error"] is None
    assert llm["usage_24h"] == []


async def test_data_health_last_error_describes_latest_empty_status_row(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    await api_session.execute(delete(LlmCall))
    h = datetime.timedelta(hours=1)
    api_session.add_all(
        [
            _call("exec_brief", "error", 5 * h, http_status=500, error_type="InternalServerError"),
            _call("classify", "empty", h, tokens=None),
        ]
    )
    await api_session.flush()
    llm = (await api_client.get("/api/data-health", headers=auth_header())).json()["llm"]
    assert llm["status"] == "failing"
    err = llm["last_error"]
    assert err["task"] == "classify"
    assert err["error_type"] == "empty response"
    assert err["http_status"] is None
