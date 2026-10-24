"""Replay artikel yang gagal di-enrich (ROADMAP #24): `tools/ops/replay_failed_enrichment.py` dan
`cti_core.celery_client.send_enrich_task`. Murni, tanpa DB, Redis, maupun Celery."""

from __future__ import annotations

import datetime
from typing import Any

import pytest

from tools.ops.replay_failed_enrichment import STUB_NEWS_TYPE, Row, enqueue_all, plan


def row(n: int, news_type: str | None = None, kind: str = "permanent") -> Row:
    return Row(
        id=n,
        url=f"https://example.com/{n}",
        title=f"Judul {n}",
        source="Src",
        scraper_id="sc",
        posted_on=datetime.date(2026, 10, 16),
        failure_kind=kind,
        article_news_type=news_type,
    )


def test_plan_separates_new_stub_and_already_published_articles() -> None:
    rows = [row(1), row(2, STUB_NEWS_TYPE), row(3, "Global")]

    grouped = plan(rows)

    assert [r.id for r in grouped["enqueue"]] == [1]
    assert [r.id for r in grouped["stub_restored"]] == [2]  # replay diam-diam tak berguna
    assert [r.id for r in grouped["skip_article_exists"]] == [3]
    assert grouped["replace_stub"] == []


def test_replacing_stubs_is_explicit() -> None:
    grouped = plan([row(2, STUB_NEWS_TYPE)], replace_stubs=True)

    assert [r.id for r in grouped["replace_stub"]] == [2]
    assert grouped["stub_restored"] == []


def test_enqueue_all_paces_by_rate_and_forwards_the_replay_flag() -> None:
    sent: list[tuple[int, bool]] = []
    slept: list[float] = []

    count = enqueue_all(
        [row(1), row(2)],
        rate_per_min=20,
        replay=True,
        send=lambda r, replay: sent.append((r.id, replay)),
        check_capacity=lambda: None,
        sleep=slept.append,
    )

    assert count == 2 and sent == [(1, True), (2, True)]
    assert slept == [3.0, 3.0]  # 60 / 20 per menit


def test_enqueue_all_stops_when_the_queue_is_full() -> None:
    sent: list[int] = []
    calls = iter([None, None, RuntimeError("antrian penuh")])

    def capacity() -> None:
        item = next(calls)
        if item is not None:
            raise item

    with pytest.raises(RuntimeError):
        enqueue_all(
            [row(1), row(2), row(3)],
            rate_per_min=60,
            replay=True,
            send=lambda r, _replay: sent.append(r.id),
            check_capacity=capacity,
            sleep=lambda _s: None,
        )

    assert sent == [1, 2]  # yang ketiga tidak dikirim


class FakeCelery:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def send_task(self, name: str, kwargs: dict[str, Any], queue: str) -> None:
        self.calls.append({"name": name, "kwargs": kwargs, "queue": queue})


def test_send_enrich_task_sends_the_sink_payload_and_adds_replay_only_when_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cti_core import celery_client

    fake = FakeCelery()
    monkeypatch.setattr(celery_client, "get_celery_client", lambda: fake)
    base = {"title": "T", "url": "https://x/1", "source": "S", "scraper_id": "sc"}

    celery_client.send_enrich_task(**base, posted_on=datetime.date(2026, 10, 16))
    celery_client.send_enrich_task(**base, posted_on=None, replay=True)

    plain, replay = fake.calls
    assert plain["name"] == replay["name"] == "enrich.article" and plain["queue"] == "enrich"
    assert plain["kwargs"] == {**base, "posted_on": "2026-10-16"}  # sama dengan payload sink
    assert replay["kwargs"] == {**base, "posted_on": None, "replay": True}


def test_send_enrich_task_adds_alert_only_when_not_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_core import celery_client

    fake = FakeCelery()
    monkeypatch.setattr(celery_client, "get_celery_client", lambda: fake)
    base = {
        "title": "T",
        "url": "https://x/1",
        "source": "S",
        "scraper_id": "sc",
        "posted_on": None,
    }

    celery_client.send_enrich_task(**base, replay=True, alert=None)
    celery_client.send_enrich_task(**base, replay=True, alert=True)
    celery_client.send_enrich_task(**base, replay=True, alert=False)

    none, yes, no = fake.calls
    assert "alert" not in none["kwargs"]
    assert yes["kwargs"]["alert"] is True and no["kwargs"]["alert"] is False
