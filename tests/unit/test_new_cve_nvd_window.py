"""`new_cve` -- jendela waktu query NVD.

Bug: `ctx.now` itu UTC naive, tapi URL NVD menempelkan `+07:00` ke jam UTC itu. Hasilnya
`pubEndDate` jatuh 7 jam di masa lalu: CVE yang terbit dalam 7 jam terakhir belum terjangkau
dan baru tercatat di run berikutnya (`detected_on` telat, MTTD di dashboard ikut membengkak)."""

from __future__ import annotations

import datetime

import httpx
from cti_scrapers.feeds.new_cve import NewCve

from tests.unit.scraper_helpers import NOW, json_response, make_ctx

UTC = datetime.UTC


def test_nvd_window_ends_at_ctx_now_in_utc() -> None:
    requested: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url)
        return json_response({"vulnerabilities": []})

    NewCve()._nvd_candidates(make_ctx(NewCve, handler), ["nginx"], {})

    params = requested[0].params
    end = datetime.datetime.fromisoformat(params["pubEndDate"])
    start = datetime.datetime.fromisoformat(params["pubStartDate"])
    assert end == NOW.replace(tzinfo=UTC)
    assert end - start == datetime.timedelta(days=8)
