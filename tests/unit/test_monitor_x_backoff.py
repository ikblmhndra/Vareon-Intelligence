"""`monitor_x` di free tier twitterapi.io (~1 request/5-6 dtk, dibagi 4 scraper yang mukul domain
yang sama): satu query PER AKUN berturut-turut kena HTTP 429 ATAU menghabiskan budget LOKAL kita
sendiri sebelum server sempat balas apa pun. Ketemu di rehearsal beat staging (Fase 10.G/10.G2):
tiap run `fetch_error` (429) atau `rate_limited` (budget lokal). Sekarang: (1) 429 ditunggu lalu
diulang (helper yang sama dengan `tweet_alerts`), (2) budget lokal habis ditunggu sampai jendela
reset lalu diulang, (3) jeda PROAKTIF di antara akun (sebelum limitnya abis, bukan cuma
sesudahnya)."""

from __future__ import annotations

import httpx
import pytest
from cti_enrich.stages.classify import ClassifyResult
from cti_scraper.errors import RateLimited, TransientFetchError
from cti_scrapers.collectors import _twitterapi
from cti_scrapers.feeds import monitor_x
from cti_scrapers.feeds.monitor_x import MonitorX

from tests.unit.scraper_helpers import json_response, make_ctx

REFERENCE = {
    "monitored_accounts": ["akun_a", "akun_b"],
    "tweet_last_seen_ids": {},
    "techstack": [],
    "threat_actor_groups": [],
    "monitored_people": [],
}


def tweet(tid: int, user: str) -> dict:
    return {
        "id": str(tid), "text": f"tweet {tid}", "url": f"https://x.com/{user}/status/{tid}",
        "createdAt": "Sat Sep 26 10:00:00 +0000 2026", "author": {"userName": user},
    }  # fmt: skip


class Api:
    """Membalas 429 untuk `throttle` panggilan pertama per akun, lalu satu tweet per akun."""

    def __init__(self, throttle: int) -> None:
        self.throttle, self.seen, self.calls = throttle, {}, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        account = request.url.params["query"].split()[0].removeprefix("from:")
        self.calls.append(account)
        self.seen[account] = self.seen.get(account, 0) + 1
        if self.seen[account] <= self.throttle:
            return httpx.Response(429, json={"error": "rate limited"})
        return json_response(
            {"tweets": [tweet(len(self.seen) * 100, account)], "has_next_page": False}
        )


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    monkeypatch.setattr(monitor_x, "classify", lambda text, **_: ClassifyResult(related_cyber=True))
    slept: list[float] = []
    # `monitor_x.py` dan `_twitterapi.py` sama-sama `import time` -- keduanya menunjuk modul
    # `time` yang SAMA di `sys.modules`, jadi satu monkeypatch ini menangkap sleep dari dua-duanya
    # (jeda proaktif antar-akun di monitor_x.py, dan backoff 429/RateLimited di _twitterapi.py).
    monkeypatch.setattr(_twitterapi.time, "sleep", slept.append)
    return slept


def run(api: Api):
    return list(MonitorX().fetch(make_ctx(MonitorX, api, reference=REFERENCE)))


def test_a_429_on_an_account_is_waited_out_and_retried_instead_of_failing_the_run(_no_llm) -> None:
    api = Api(throttle=1)

    items = run(api)

    assert sorted(i.author_username for i in items) == ["akun_a", "akun_b"]  # kedua akun terbaca
    assert api.calls == ["akun_a", "akun_a", "akun_b", "akun_b"]  # tiap akun: 429 lalu 200
    # 6.0 (429 akun_a) lalu 6.0 (jeda PROAKTIF sebelum pindah ke akun_b) lalu 6.0 (429 akun_b) --
    # rate_limit MonitorX "10/minute" -> window_s/capacity = 60/10 = 6.0, SAMA dengan
    # RATE_LIMIT_BACKOFF_S
    # (kebetulan, bukan yang satu diturunkan dari yang lain).
    assert _no_llm == [6.0, 6.0, 6.0]


def test_a_persistently_throttled_account_still_fails_visibly(_no_llm) -> None:
    with pytest.raises(TransientFetchError, match="HTTP 429"):
        run(Api(throttle=99))

    assert len(_no_llm) == 3  # 1 + 3 ulangan, lalu menyerah (Runner/Celery yang mengulang run) --
    # gagal di akun PERTAMA, jeda proaktif antar-akun gak pernah ke-trigger.


def test_healthy_accounts_are_still_paced_between_each_other(_no_llm) -> None:
    """Bukan lagi "gak pernah tidur" -- sekarang tetap dijeda PROAKTIF di antara akun (N-1
    jeda buat N akun) walau semuanya sehat, supaya budget gak habis sebelum server menolak."""
    run(Api(throttle=0))

    assert _no_llm == [6.0]  # 2 akun -> 1 jeda di antaranya, TANPA backoff apa pun


def test_local_rate_limit_exhaustion_is_waited_out_using_the_window_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Budget LOKAL kita sendiri (`RateLimited`, dari `cti_scraper.ratelimit.TokenBucket`) habis
    SEBELUM server sempat menolak apa pun -- ketemu di rehearsal staging: 18 akun berturut-turut
    langsung `rate_limited` di akun pertama. Ditunggu sampai jendela FIXED-WINDOW reset (`window_s`
    dari `ctx.meta.rate_limit`, "10/minute" -> 60s) -- BUKAN `RATE_LIMIT_BACKOFF_S` (6.0, itu buat
    429 dari server)."""
    ctx = make_ctx(MonitorX, lambda r: json_response({"tweets": [], "has_next_page": False}))
    calls = {"n": 0}
    real_get = ctx.http.get

    def flaky(url: str, **kw: object):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RateLimited("rate limit domain 'api.twitterapi.io' abis (10/minute)")
        return real_get(url, **kw)

    ctx.http.get = flaky  # type: ignore[method-assign]
    slept: list[float] = []
    monkeypatch.setattr(_twitterapi.time, "sleep", slept.append)

    resp = _twitterapi._get_with_backoff(ctx, {"query": "x"})

    assert resp.status_code == 200
    assert calls["n"] == 3
    assert slept == [60.0, 60.0]  # window_s, dua kali -- BUKAN 6.0


def test_persistent_local_rate_limit_exhaustion_still_fails_visibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_ctx(MonitorX, lambda r: json_response({"tweets": [], "has_next_page": False}))

    def always_limited(url: str, **kw: object):
        raise RateLimited("rate limit domain 'api.twitterapi.io' abis (10/minute)")

    ctx.http.get = always_limited  # type: ignore[method-assign]
    slept: list[float] = []
    monkeypatch.setattr(_twitterapi.time, "sleep", slept.append)

    with pytest.raises(RateLimited):
        _twitterapi._get_with_backoff(ctx, {"query": "x"})

    assert slept == [60.0, 60.0, 60.0]  # 1 + 3 ulangan, lalu menyerah


def test_a_429_and_a_local_rate_limit_do_not_share_a_backoff_duration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regresi kalau kedua `except` diam-diam digabung jadi satu cabang -- jendela lokal (60s)
    tidak boleh terpakai buat 429 remote (6s), dan sebaliknya."""
    ctx = make_ctx(MonitorX, lambda r: json_response({"tweets": [], "has_next_page": False}))
    real_get = ctx.http.get
    sequence = iter(["local", "remote"])

    def flaky(url: str, **kw: object):
        kind = next(sequence, None)
        if kind == "local":
            raise RateLimited("rate limit domain 'api.twitterapi.io' abis (10/minute)")
        if kind == "remote":
            raise TransientFetchError("HTTP 429: ...")
        return real_get(url, **kw)

    ctx.http.get = flaky  # type: ignore[method-assign]
    slept: list[float] = []
    monkeypatch.setattr(_twitterapi.time, "sleep", slept.append)

    resp = _twitterapi._get_with_backoff(ctx, {"query": "x"})

    assert resp.status_code == 200
    assert slept == [60.0, 6.0]
