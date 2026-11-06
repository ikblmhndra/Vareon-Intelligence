"""Pencarian targeted `github_poc_monitor` dibagi per jam (prod 2026-11-06).

Satu run dulu mencari SEMUA CVE di `cve_tracker` (2.469 di prod) dengan budget GitHub Search
30/menit, jadi satu run > 80 menit padahal jadwalnya tiap jam: run menumpuk, memenuhi semua slot
`worker`, dan ingest RSS berhenti ~5 jam. Sekarang tiap run hanya mencari satu irisan (maks
`_TARGETED_SEARCHES_PER_RUN`), irisan dipilih dari jam `ctx.now`, dan semua CVE tetap kebagian dalam
satu siklus."""

from __future__ import annotations

import datetime
from typing import Any

import httpx
from cti_scrapers.feeds import github_poc_monitor as mod
from cti_scrapers.feeds.github_poc_monitor import GithubPocMonitor

from tests.unit.scraper_helpers import make_ctx

NOW = datetime.datetime(2026, 11, 6, 7, 0, 0, tzinfo=datetime.UTC)


class _CountingHttp:
    def __init__(self) -> None:
        self.targeted: list[str] = []

    def get(self, url: str, **_: Any) -> httpx.Response:
        if "+in:name,description" in url:
            self.targeted.append(url.split("q=")[1].split("+")[0])
        return httpx.Response(200, json={"items": []})


def _searched(n_cves: int, now: datetime.datetime) -> list[str]:
    entries = [{"cve_id": f"CVE-2026-{i:05d}", "poc_urls": set()} for i in range(n_cves)]
    ctx = make_ctx(
        GithubPocMonitor,
        lambda r: httpx.Response(200),
        now=now,
        reference={"techstack": [], "true_positive_cves": entries},
    )
    http = _CountingHttp()
    ctx.http = http  # type: ignore[assignment]
    list(GithubPocMonitor().fetch(ctx))
    return http.targeted


def test_daftar_kecil_dicari_semua_tiap_run() -> None:
    assert len(_searched(10, NOW)) == 10


def test_daftar_besar_dibatasi_per_run_dan_semua_kebagian_dalam_satu_siklus() -> None:
    n = 2469
    budget = mod._TARGETED_SEARCHES_PER_RUN
    slices = -(-n // budget)
    seen: list[str] = []
    for hour in range(slices):
        searched = _searched(n, NOW + datetime.timedelta(hours=hour))
        # irisan hash tidak persis rata; batas atas longgar 25 % tetap jauh di bawah satu jam
        assert len(searched) <= budget * 1.25
        seen.extend(searched)
    assert len(seen) == n
    assert len(set(seen)) == n


def test_irisan_stabil_untuk_jam_yang_sama() -> None:
    assert _searched(2469, NOW) == _searched(2469, NOW + datetime.timedelta(minutes=40))
