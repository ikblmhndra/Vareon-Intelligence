"""Info "diupdate per kapan" dan tombol cek manual CVE di tab CVEs (`GET /api/cve/freshness`,
`POST /api/cve/check-new`, `cti_api.services.cve_check`).

Sumber CVE tergantung mode: `new_cve` (scraper, default) atau mirror (`cve.mirror_sync`) bila
promosi mirror `live`. Celery dan settings di-mock di titik yang sama dengan test lain
(`test_monitor_trigger.py`): tidak ada task sungguhan yang terkirim."""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable
from itertools import product
from types import SimpleNamespace
from typing import Any

import pytest
from cti_api.services import cve_check
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from cti_core.db.models.report_state import JobState
from cti_core.db.models.scraper import ScraperConfig, ScraperRun
from cti_core.db.models.techstack import TechStackEntry
from cti_core.db.repositories.auth import AsyncAuditLogRepo, AsyncClientRepo
from cti_scraper import supersede
from cti_scraper.queues import queue_for
from cti_scraper.registry import get as get_scraper_cls
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

UTC = datetime.UTC


def ago(**delta: float) -> datetime.datetime:
    return datetime.datetime.now(UTC) - datetime.timedelta(**delta)


def run_row(
    status: str, *, started: datetime.datetime, finished: datetime.datetime | None
) -> ScraperRun:
    return ScraperRun(
        run_id=str(uuid.uuid4()),
        scraper_id="new_cve",
        trigger="beat",
        status=status,
        started_at=started,
        finished_at=finished,
    )


def as_time(value: str | None) -> datetime.datetime | None:
    return datetime.datetime.fromisoformat(value) if value else None


class FakeCelery:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, Any]] = []

    def send_task(
        self,
        name: str,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        **opts: Any,
    ) -> SimpleNamespace:
        if self.fail:
            raise ConnectionError("broker mati")
        self.sent.append({"name": name, "args": tuple(args), "kwargs": kwargs or {}, **opts})
        return SimpleNamespace(id=f"task-{len(self.sent)}")


@pytest.fixture
def celery(monkeypatch: pytest.MonkeyPatch) -> FakeCelery:
    fake = FakeCelery()
    monkeypatch.setattr(cve_check, "get_celery_client", lambda: fake)
    return fake


def set_mirror(
    monkeypatch: pytest.MonkeyPatch, *, enabled: bool, promote: str, keep_legacy: bool = False
) -> None:
    cfg = SimpleNamespace(enabled=enabled, promote=promote, keep_legacy_new_cve=keep_legacy)
    monkeypatch.setattr(cve_check, "get_settings", lambda: SimpleNamespace(cve_mirror=cfg))


async def freshness(client: AsyncClient, headers: dict[str, str], **params: str) -> dict[str, Any]:
    resp = await client.get("/api/cve/freshness", headers=headers, params=params)
    assert resp.status_code == 200
    body: dict[str, Any] = resp.json()
    return body


# ── GET /freshness ───────────────────────────────────────────────────────────


async def test_freshness_without_any_run_is_empty(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await AsyncClientRepo(api_session).ensure_default()

    body = await freshness(api_client, auth_header(role="analyst"))

    assert (body["last_checked_at"], body["running"], body["newest_detected_at"]) == (
        None,
        False,
        None,
    )
    assert [s["id"] for s in body["sources"]] == ["new_cve"]


async def test_freshness_separates_last_successful_check_from_latest_attempt(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    """Info "diupdate per kapan" = run SUKSES terakhir; percobaan terakhir yang gagal dilaporkan
    terpisah supaya tidak tampak seolah data baru saja diperbarui."""
    good_finished = ago(hours=3)
    api_session.add_all(
        [
            run_row("ok", started=ago(hours=3, minutes=5), finished=good_finished),
            run_row("rate_limited", started=ago(hours=1, minutes=1), finished=ago(hours=1)),
        ]
    )
    await api_session.flush()

    body = await freshness(api_client, auth_header())
    source = body["sources"][0]

    assert as_time(body["last_checked_at"]) == good_finished
    assert (source["last_run_status"], source["enabled"]) == ("rate_limited", True)
    assert as_time(source["next_check_at"]) > datetime.datetime.now(UTC)


async def test_freshness_ignores_runs_stuck_in_running(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    """Worker yang mati meninggalkan baris `running` selamanya; hanya yang baru yang dianggap
    sedang berjalan."""
    stuck = run_row("running", started=ago(hours=2), finished=None)
    api_session.add(stuck)
    await api_session.flush()
    assert (await freshness(api_client, auth_header()))["running"] is False

    api_session.add(run_row("running", started=ago(minutes=5), finished=None))
    await api_session.flush()
    assert (await freshness(api_client, auth_header()))["running"] is True


async def test_newest_detected_and_new_since_follow_the_visible_cve_list(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    """Sama dengan tab CVEs: client aktif saja, tanpa FP, hanya tech yang dimonitor."""
    clients = AsyncClientRepo(api_session)
    await clients.ensure_default()
    await clients.create(client_id="acme", name="Acme", countries=[])
    visible = ago(minutes=5)
    api_session.add_all(
        [
            TechStackEntry(name="nginx", client_id="default"),
            CveTracker(
                cve_id="CVE-2026-0001", client_id="default", tech="nginx", detected_on=ago(hours=2)
            ),
            CveTracker(
                cve_id="CVE-2026-0002",
                client_id="default",
                tech="nginx",
                detected_on=ago(minutes=10),
            ),
            CveTracker(
                cve_id="CVE-2026-0003", client_id="default", tech="nginx", detected_on=visible
            ),
            CveTracker(
                cve_id="CVE-2026-0004",
                client_id="default",
                tech="other",
                detected_on=ago(minutes=1),
            ),
            CveTracker(
                cve_id="CVE-2026-0005", client_id="acme", tech="nginx", detected_on=ago(minutes=1)
            ),
        ]
    )
    await api_session.flush()
    api_session.add(CveFalsePositive(cve_id="CVE-2026-0002", client_id="default"))
    await api_session.flush()

    body = await freshness(api_client, auth_header(), new_since=ago(minutes=30).isoformat())

    assert as_time(body["newest_detected_at"]) == visible
    assert body["new_since"] == 1  # 0002 FP, 0004 tech tidak dimonitor, 0005 client lain, 0001 lama
    assert (await freshness(api_client, auth_header()))["new_since"] is None


async def test_freshness_in_mirror_mode_reads_the_sync_state(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polled = ago(minutes=3)
    api_session.add(
        JobState(
            key="cve_mirror.state",
            value={
                "fetch_time": ago(minutes=20).isoformat(),
                "polled_at": polled.isoformat(),
                "pending": [],
            },
        )
    )
    await api_session.flush()
    set_mirror(monkeypatch, enabled=True, promote="live")

    body = await freshness(api_client, auth_header())

    assert [s["id"] for s in body["sources"]] == ["mirror"]  # `new_cve` ditangguhkan
    assert as_time(body["last_checked_at"]) == polled


async def test_freshness_lists_both_sources_while_they_overlap(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_mirror(monkeypatch, enabled=True, promote="live", keep_legacy=True)

    body = await freshness(api_client, auth_header())

    assert [s["id"] for s in body["sources"]] == ["mirror", "new_cve"]


@pytest.mark.parametrize(
    ("enabled", "promote", "keep_legacy"),
    list(product([True, False], ["off", "shadow", "live"], [True, False])),
)
async def test_active_sources_agree_with_the_scraper_supersede_rule(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, promote: str, keep_legacy: bool
) -> None:
    """`new_cve` dianggap aktif di sini persis kalau `Runner` tidak menangguhkannya."""
    cfg = SimpleNamespace(enabled=enabled, promote=promote, keep_legacy_new_cve=keep_legacy)
    monkeypatch.setattr(cve_check, "get_settings", lambda: SimpleNamespace(cve_mirror=cfg))
    monkeypatch.setattr(supersede, "get_settings", lambda: SimpleNamespace(cve_mirror=cfg))

    assert cve_check.active_sources().scraper == (not supersede.superseded_by_mirror("new_cve"))


# ── POST /check-new ──────────────────────────────────────────────────────────


async def test_check_new_is_admin_only(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]], celery: FakeCelery
) -> None:
    resp = await api_client.post("/api/cve/check-new", headers=auth_header(role="analyst"))

    assert resp.status_code == 403
    assert celery.sent == []


async def test_check_new_sends_the_scraper_task_and_is_audited(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    celery: FakeCelery,
) -> None:
    resp = await api_client.post("/api/cve/check-new", headers=auth_header(role="admin"))

    assert resp.status_code == 200
    body = resp.json()
    assert (body["status"], body["sources"]) == ("queued", ["new_cve"])
    assert celery.sent == [
        {
            "name": "scrape.run",
            "args": ("new_cve",),
            "kwargs": {"trigger": "manual"},
            "queue": queue_for(get_scraper_cls("new_cve").meta),
        }
    ]
    entries, total = await AsyncAuditLogRepo(api_session).query(action="check_new_cves")
    assert (total, entries[0].detail["sources"]) == (1, ["new_cve"])


async def test_check_new_has_a_cooldown(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    celery: FakeCelery,
    fake_redis: Any,
) -> None:
    first = await api_client.post("/api/cve/check-new", headers=auth_header())
    fake_redis._ttl["cve:check_new:cooldown"] = 44  # sisa waktu sebenarnya, bukan konstanta
    second = await api_client.post("/api/cve/check-new", headers=auth_header())

    assert (first.status_code, second.status_code) == (200, 429)
    assert second.headers["Retry-After"] == "44"
    assert "in 44 seconds" in second.json()["detail"]
    assert len(celery.sent) == 1


async def test_check_new_is_rejected_while_a_run_is_in_progress(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    celery: FakeCelery,
) -> None:
    """Penolakan karena run berjalan tidak boleh menghabiskan cooldown: begitu run selesai tombol
    langsung bisa dipakai."""
    running = run_row("running", started=ago(minutes=2), finished=None)
    api_session.add(running)
    await api_session.flush()

    blocked = await api_client.post("/api/cve/check-new", headers=auth_header())
    assert (blocked.status_code, celery.sent) == (409, [])

    running.status, running.finished_at = "ok", datetime.datetime.now(UTC)
    await api_session.flush()
    assert (await api_client.post("/api/cve/check-new", headers=auth_header())).status_code == 200


async def test_check_new_is_rejected_when_the_scraper_is_disabled(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    celery: FakeCelery,
) -> None:
    api_session.add(ScraperConfig(scraper_id="new_cve", enabled=False))
    await api_session.flush()

    resp = await api_client.post("/api/cve/check-new", headers=auth_header())

    assert (resp.status_code, celery.sent) == (409, [])
    assert (await freshness(api_client, auth_header()))["sources"][0]["enabled"] is False


async def test_check_new_in_mirror_mode_sends_the_mirror_sync(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    celery: FakeCelery,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_mirror(monkeypatch, enabled=True, promote="live")

    resp = await api_client.post("/api/cve/check-new", headers=auth_header())

    assert (resp.status_code, resp.json()["sources"]) == (200, ["mirror"])
    assert [(t["name"], t["queue"]) for t in celery.sent] == [("cve.mirror_sync", "maintenance")]


async def test_check_new_while_sources_overlap_sends_both(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    celery: FakeCelery,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_mirror(monkeypatch, enabled=True, promote="live", keep_legacy=True)

    resp = await api_client.post("/api/cve/check-new", headers=auth_header())

    assert resp.status_code == 200
    assert sorted(t["name"] for t in celery.sent) == ["cve.mirror_sync", "scrape.run"]


async def test_check_new_with_a_dead_broker_fails_cleanly_and_releases_the_cooldown(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cve_check, "get_celery_client", lambda: FakeCelery(fail=True))
    failed = await api_client.post("/api/cve/check-new", headers=auth_header())
    assert failed.status_code == 503

    monkeypatch.setattr(cve_check, "get_celery_client", lambda: FakeCelery())
    assert (await api_client.post("/api/cve/check-new", headers=auth_header())).status_code == 200
