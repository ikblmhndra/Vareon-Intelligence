"""`GET /api/data-health` (ROADMAP #24 PR-B): angka halaman Data health sama dengan query
reproduksi audit -- antrian job enrichment (`enrich_jobs`) dan breaker LLM, kedalaman antrian
`enrich`, kesegaran sumber, dan cakupan enrichment IOC (kartu `skipped` tidak dihitung)."""

from __future__ import annotations

import datetime
import uuid

from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.indicator import Indicator
from cti_core.db.models.llm_call import LlmCall
from cti_core.db.models.scraper import ScraperRun
from cti_core.db.models.story import Story
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.story import AsyncStoryRepo
from cti_core.urlkit import url_hash
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


def _job(n: int, kind: str, state: str, age: datetime.timedelta) -> EnrichJob:
    url = f"https://example.com/j{n}"
    return EnrichJob(
        kind=kind,
        url=url,
        url_hash=url_hash(url),
        title=f"Job {n}",
        source="S",
        state=state,
        created_at=datetime.datetime.now(datetime.UTC) - age,
    )


def _ioc(value: str, type_: str, providers: list[dict[str, object]]) -> Indicator:
    return Indicator(
        type=type_, value=value, enrichment={"providers": providers} if providers else {}
    )


async def test_data_health_reports_failures_queue_freshness_and_ioc_coverage(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    h = datetime.timedelta(hours=1)
    await api_session.execute(delete(EnrichJob))
    await api_session.execute(delete(RejectedArticle))
    api_session.add_all(
        [
            _job(1, "classify", "failed", 2 * h),
            _job(2, "ttp", "failed", 72 * h),
            _job(3, "classify", "failed", 24 * 10 * h),  # di luar 7 hari, tetap menunggu analis
            _job(4, "classify", "pending", 3 * h),  # belum gagal: tidak dihitung
            _rejected(1, None, 2 * h),
            _rejected(2, None, 3 * h),  # ditolak klasifikasi: ikut penyebut, bukan kegagalan
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
    assert enrichment["processed_7d"] == 3  # 1 artikel + 2 baris rejected dalam 7 hari
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
    assert body["queues"]["depths"] is None


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


async def test_data_health_llm_block_failing_with_queue_and_usage(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    # Isolasi: baris llm_calls / enrich_jobs milik test lain di DB bersama dibuang di
    # transaksi test ini (di-rollback saat teardown).
    await api_session.execute(delete(LlmCall))
    await api_session.execute(delete(EnrichJob))
    h = datetime.timedelta(hours=1)
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
    api_session.add_all(
        [
            _job(1, "classify", "pending", 5 * h),
            _job(2, "classify", "pending", 2 * h),
            _job(3, "ttp", "pending", 3 * h),
            _job(4, "ttp", "failed", 9 * h),  # failed tidak ikut `oldest_pending_at`
        ]
    )
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

    # 1 error terbaru saja: breaker tertutup (butuh 3 beruntun)
    queue = llm["queue"]
    assert (queue["breaker"], queue["retry_at"]) == ("closed", None)
    assert (queue["pending_classify"], queue["pending_ttp"], queue["failed"]) == (2, 1, 1)
    assert queue["oldest_pending_at"] is not None
    assert "parked" not in llm

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


async def test_data_health_story_stats(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    """Selisih terhadap data bersama: story berartikel dalam jendela dihitung; story kosong dan
    story lama (`first_seen_at` > 7 hari, walau `created_at` baru, spt hasil backfill) tidak."""
    now = datetime.datetime.now(datetime.UTC)
    before = {
        h: await AsyncStoryRepo(api_session).stats_since(now - datetime.timedelta(hours=h))
        for h in (24, 168)
    }
    story = Story(title="S", lead_source="A", first_seen_at=now, last_seen_at=now, article_count=1)
    empty = Story(title="E", lead_source="A", first_seen_at=now, last_seen_at=now)
    old = Story(
        title="O",
        lead_source="A",
        first_seen_at=now - datetime.timedelta(days=10),
        last_seen_at=now,
        article_count=1,
    )
    api_session.add_all([story, empty, old])
    await api_session.flush()
    follow = await AsyncArticleRepo(api_session).upsert(
        url="https://h.example/follow", title="F", source="B"
    )
    follow.story_id = story.id
    follow.story_match = "cve"
    follow.raw_enrichment = {
        "classify": {"inherited_from_story": story.id, "lead_article_id": None}
    }
    await api_session.flush()

    llm = (await api_client.get("/api/data-health", headers=auth_header(role="analyst"))).json()[
        "llm"
    ]
    for key, h in (("stories_24h", 24), ("stories_7d", 168)):
        got = llm[key]
        assert got["new_stories"] == before[h].new_stories + 1
        assert got["followups"] == before[h].followups + 1
        assert got["inherited"] == before[h].inherited + 1
        assert got["llm_calls_avoided"] == got["inherited"] * 2


async def test_data_health_queue_reports_open_and_half_open_breaker(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    from cti_api.services import data_health as service

    m = datetime.timedelta(minutes=1)
    await api_session.execute(delete(LlmCall))
    await api_session.execute(delete(EnrichJob))
    # 3 kegagalan beruntun, terbaru 1 menit lalu: cooldown 2 menit belum lewat -> terbuka
    api_session.add_all([_call("classify", "error", n * m) for n in (1, 2, 3)])
    await api_session.flush()
    queue = (await api_client.get("/api/data-health", headers=auth_header())).json()["llm"]["queue"]
    assert queue["breaker"] == "open" and queue["retry_at"] is not None
    assert (queue["pending_classify"], queue["pending_ttp"], queue["failed"]) == (0, 0, 0)
    assert queue["oldest_pending_at"] is None

    service._cache = None
    await api_session.execute(delete(LlmCall))
    api_session.add_all([_call("ttp", "empty", n * m) for n in (10, 11, 12)])
    await api_session.flush()
    queue = (await api_client.get("/api/data-health", headers=auth_header())).json()["llm"]["queue"]
    assert queue["breaker"] == "half_open"


def _run(status: str, age: datetime.timedelta, found: int, new: int) -> ScraperRun:
    return ScraperRun(
        run_id=str(uuid.uuid4()),
        scraper_id="pipe-test",
        status=status,
        started_at=datetime.datetime.now(datetime.UTC) - age,
        items_found=found,
        items_new=new,
    )


async def test_data_health_pipeline_windows(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    await api_session.execute(delete(ScraperRun))
    await api_session.execute(delete(Article))
    await api_session.execute(delete(RejectedArticle))
    h = datetime.timedelta(hours=1)
    d = 24 * h
    api_session.add_all(
        [
            _run("ok", h, 10, 4),
            _run("running", 2 * h, 3, 1),  # semua status ikut dihitung
            _run("ok", 30 * h, 20, 5),
            _run("ok", 8 * d, 100, 50),  # di luar 7 hari
            _rejected(1, None, h),  # RejectedArticle tidak dibaca
        ]
    )
    repo = AsyncArticleRepo(api_session)
    now = datetime.datetime.now(datetime.UTC)
    for n, age in enumerate((h, 3 * d, 8 * d)):
        art = await repo.upsert(
            url=f"https://example.com/p{n}", title=f"P{n}", source="S", posted_on=now.date()
        )
        art.first_seen_at = now - age
    await api_session.flush()

    body = (await api_client.get("/api/data-health", headers=auth_header())).json()
    assert body["pipeline"] == {
        "last_24h": {"items_found": 13, "items_new": 5, "articles_published": 1},
        "last_7d": {"items_found": 33, "items_new": 10, "articles_published": 2},
    }


async def test_data_health_pipeline_empty(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    await api_session.execute(delete(ScraperRun))
    await api_session.execute(delete(Article))
    await api_session.flush()
    body = (await api_client.get("/api/data-health", headers=auth_header())).json()
    zero = {"items_found": 0, "items_new": 0, "articles_published": 0}
    assert body["pipeline"] == {"last_24h": zero, "last_7d": zero}


async def test_data_health_queue_depths(api_client: AsyncClient, auth_header, fake_redis) -> None:
    fake_redis.lists["enrich"] = 7
    fake_redis.lists["cve"] = 2
    queues = (await api_client.get("/api/data-health", headers=auth_header())).json()["queues"]
    assert queues["depths"] == {
        "scrape.rss": 0,
        "scrape.api": 0,
        "scrape.browser": 0,
        "enrich": 7,
        "notify": 0,
        "maintenance": 0,
        "cve": 2,
    }
    assert list(queues["depths"]) == [
        "scrape.rss",
        "scrape.api",
        "scrape.browser",
        "enrich",
        "notify",
        "maintenance",
        "cve",
    ]
    assert queues["enrich_depth"] == 7


async def test_data_health_queue_depths_all_or_nothing(
    api_client: AsyncClient, auth_header, fake_redis, monkeypatch
) -> None:
    fake_redis.lists["enrich"] = 7
    real = fake_redis.llen

    async def flaky(key: str) -> int:
        if key == "notify":
            raise ConnectionError("redis down")
        return await real(key)

    monkeypatch.setattr(fake_redis, "llen", flaky)
    queues = (await api_client.get("/api/data-health", headers=auth_header())).json()["queues"]
    assert queues["depths"] is None
    assert queues["enrich_depth"] is None
