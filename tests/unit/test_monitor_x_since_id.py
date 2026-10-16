"""`since_id` monitor_x: kunci `tweet_last_seen_ids` lowercase, dicari lowercase.

Prod 2026-10-16: `Tweet.author_username` menyimpan `userName` apa adanya (`FalconFeedsio`,
`MonThreat`), sedangkan `monitored_accounts.username` lowercase. `last_seen.get(akun)` meleset untuk
handle bercampur huruf, jadi `since_id` tidak pernah dipakai dan tiap run jatuh ke jendela 3 jam."""

from __future__ import annotations

from typing import Any

import httpx
from cti_enrich.stages.classify import ClassifyResult
from cti_scraper.reference_data import _resolve_tweet_last_seen_ids
from cti_scrapers.feeds import monitor_x
from cti_scrapers.feeds.monitor_x import MonitorX

from tests.unit.scraper_helpers import json_response, make_ctx


class FakeSession:
    """Cukup untuk `session.execute(select(...)).all()` -- resolver tidak memakai yang lain."""

    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self.rows = rows

    def execute(self, _stmt: Any) -> FakeSession:
        return self

    def all(self) -> list[tuple[str, str]]:
        return self.rows


def test_last_seen_ids_are_keyed_by_lowercase_username_and_keep_the_numeric_max() -> None:
    session = FakeSession([("FalconFeedsio", "9"), ("falconfeedsio", "10"), ("rst_cloud", "7")])

    # "10" > "9" secara numerik; MAX string akan memilih "9"
    assert _resolve_tweet_last_seen_ids(session) == {  # type: ignore[arg-type]
        "falconfeedsio": "10",
        "rst_cloud": "7",
    }


def test_since_id_is_used_for_an_account_whose_stored_tweets_have_mixed_case(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(monitor_x, "classify", lambda text: ClassifyResult(related_cyber=True))
    queries: list[str] = []

    def api(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["query"])
        return json_response({"tweets": [], "has_next_page": False})

    reference = {
        "monitored_accounts": ["FalconFeedsio"],
        "tweet_last_seen_ids": {"falconfeedsio": "123"},
        "techstack": [],
        "threat_actor_groups": [],
        "monitored_people": [],
    }

    list(MonitorX().fetch(make_ctx(MonitorX, api, reference=reference)))

    assert queries == ["from:FalconFeedsio -is:retweet -filter:replies since_id:123"]
