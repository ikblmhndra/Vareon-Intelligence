"""Control plane: status scheduler (heartbeat beat) + `next_run_at` per scraper di
`GET /api/scraper` dan `GET /api/scraper/health` (QA BUG-D2/D8)."""

from __future__ import annotations

import datetime

from cti_core import beat_heartbeat
from cti_core.db.models.scraper import ScraperConfig
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


async def test_list_reports_unknown_scheduler_without_heartbeat(
    api_client: AsyncClient, auth_header
) -> None:
    resp = await api_client.get("/api/scraper", headers=auth_header(role="analyst"))
    assert resp.status_code == 200
    body = resp.json()

    assert body["scheduler"]["state"] == "unknown"
    assert body["scheduler"]["last_tick_at"] is None
    enabled = [s for s in body["scrapers"] if s["enabled"]]
    assert enabled and all(s["next_run_at"] for s in enabled)
    now = datetime.datetime.now(datetime.UTC)
    for s in enabled[:5]:
        assert datetime.datetime.fromisoformat(s["next_run_at"]) > now


async def test_list_reports_fresh_and_stale_heartbeat(
    api_client: AsyncClient, auth_header, fake_redis
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    fake_redis.values[beat_heartbeat.HEARTBEAT_KEY] = beat_heartbeat.encode(
        now - datetime.timedelta(seconds=20), now - datetime.timedelta(hours=1)
    )
    body = (await api_client.get("/api/scraper", headers=auth_header())).json()
    assert body["scheduler"]["state"] == "ok"
    assert body["scheduler"]["started_at"] is not None

    fake_redis.values[beat_heartbeat.HEARTBEAT_KEY] = beat_heartbeat.encode(
        now - datetime.timedelta(hours=97), None
    )
    health = (await api_client.get("/api/scraper/health", headers=auth_header())).json()
    assert health["scheduler"]["state"] == "stale"
    assert health["scheduler"]["age_s"] > 96 * 3600


async def test_health_reports_failed_items_with_a_reason_and_the_last_clean_run(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    from cti_core.db.models.scraper import ScraperRun

    body = (await api_client.get("/api/scraper", headers=auth_header())).json()
    target = next(s for s in body["scrapers"] if s["enabled"])["id"]
    now = datetime.datetime.now(datetime.UTC)
    api_session.add_all(
        [
            ScraperRun(
                run_id="run-clean",
                scraper_id=target,
                status="ok",
                started_at=now - datetime.timedelta(hours=2),
            ),
            ScraperRun(
                run_id="run-failing",
                scraper_id=target,
                status="partial",
                started_at=now - datetime.timedelta(minutes=1),
                items_failed=4,
                errors=[{"stage": "sink", "type": "UnknownAlertTopic", "message": "topic x"}],
            ),
        ]
    )
    await api_session.flush()

    health = (await api_client.get("/api/scraper/health", headers=auth_header())).json()

    problem = next(p for p in health["problems"] if p["id"] == target)
    assert problem["status"] == "degraded" and problem["items_failed_last"] == 4
    assert "4 item(s) failed in the last run" in problem["reason"]
    assert problem["consecutive_failing"] == 1
    assert problem["last_success_at"] is not None  # run bersih 2 jam lalu, bukan yang gagal


async def test_disabled_scraper_has_no_next_run(
    api_client: AsyncClient, api_session: AsyncSession, auth_header
) -> None:
    body = (await api_client.get("/api/scraper", headers=auth_header())).json()
    target = next(s for s in body["scrapers"] if s["enabled"])["id"]
    assert next(s for s in body["scrapers"] if s["id"] == target)["disabled_by"] is None
    api_session.add(ScraperConfig(scraper_id=target, enabled=False, paused_reason="site down"))
    await api_session.flush()

    body = (await api_client.get("/api/scraper", headers=auth_header())).json()
    row = next(s for s in body["scrapers"] if s["id"] == target)
    assert row["enabled"] is False
    assert row["next_run_at"] is None
    assert row["disabled_by"] == "admin"
    assert row["paused_reason"] == "site down"
