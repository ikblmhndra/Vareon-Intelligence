"""`new_cve` -- klasifikasi error MITRE. Dulu `_mitre_detail` membungkus SEMUA exception jadi
`ParseError`, jadi batas laju domain (`RateLimited`) dan 5xx/429 (`TransientFetchError`) tampil
sebagai "struktur situs berubah" (health `degraded`). Ketemu di rehearsal beat staging (10.G)."""

from __future__ import annotations

import httpx
import pytest
from cti_scraper.errors import ParseError, RateLimited, TransientFetchError
from cti_scrapers.feeds import _pacing as pacing
from cti_scrapers.feeds.new_cve import NewCve

from tests.unit.scraper_helpers import json_response, make_ctx

CAND = {"id": "CVE-2026-1111", "tech": "acme", "link": "x", "summary": "s"}


def detail(handler):
    ctx = make_ctx(NewCve, handler)
    return NewCve()._mitre_detail(ctx, CAND)


def test_a_rate_limited_domain_stays_rate_limited_not_a_parse_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `get_waiting` menunggu jendela reset (maks `RATE_RETRIES` kali) sebelum menyerah dan
    # meneruskan `RateLimited` -- jangan tidur beneran di test.
    monkeypatch.setattr(pacing.time, "sleep", lambda _s: None)
    ctx = make_ctx(NewCve, lambda r: json_response({}))

    def throttled(url: str, **kw: object) -> httpx.Response:
        raise RateLimited("rate limit domain 'cveawg.mitre.org' abis (60/minute)")

    ctx.http.get = throttled  # type: ignore[method-assign]

    with pytest.raises(RateLimited, match=r"cveawg\.mitre\.org"):
        NewCve()._mitre_detail(ctx, CAND)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_http_statuses_stay_transient_so_the_run_is_fetch_error_not_degraded(
    status: int,
) -> None:
    with pytest.raises(TransientFetchError, match=f"HTTP {status}"):
        detail(lambda r: httpx.Response(status, json={}))


def test_a_body_that_is_not_json_is_still_a_parse_error_with_the_cve_id() -> None:
    with pytest.raises(ParseError, match="CVE-2026-1111"):
        detail(lambda r: httpx.Response(200, content=b"<html>bukan json</html>"))


def test_a_well_formed_record_is_still_parsed() -> None:
    record = {
        "cveMetadata": {"datePublished": "2026-09-01T00:00:00Z"},
        "containers": {
            "cna": {
                "affected": [
                    {"product": "Widget", "versions": [{"status": "affected", "lessThan": "2.0"}]}
                ],
                "metrics": [{"cvssV3_1": {"baseScore": 9.8, "baseSeverity": "CRITICAL"}}],
            }
        },
    }

    result = detail(lambda r: json_response(record))

    assert result.fields["cve_id"] == "CVE-2026-1111"
    assert result.fields["affected"] == ["Widget: < 2.0"]
    assert result.products == ["Widget"]
