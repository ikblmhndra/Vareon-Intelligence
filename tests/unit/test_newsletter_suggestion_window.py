"""`newsletter_suggestion._campaigns` memakai jendela start/end (PR 2), bukan `days` dari hari ini
(ROADMAP #22, PR 8): ukuran kampanye di ranking harus menghitung bulan yang diedisikan saja."""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock

import pytest
from cti_api.services import newsletter_suggestion

D = datetime.date


async def test_campaign_clusters_are_built_from_the_window_not_from_days_back_from_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_recent = AsyncMock(return_value=[{"member_article_ids": [1, 2]}])
    monkeypatch.setattr(newsletter_suggestion.campaign_service, "get_recent_campaigns", get_recent)

    result = await newsletter_suggestion._campaigns("SESSION", D(2026, 10, 1), D(2026, 10, 31))  # type: ignore[arg-type]

    assert result == [{"member_article_ids": [1, 2]}]
    get_recent.assert_awaited_once_with(
        "SESSION",
        min_size=newsletter_suggestion.CLUSTER_MIN_SIZE,
        start=D(2026, 10, 1),
        end=D(2026, 10, 31),
    )
