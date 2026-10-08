"""`new_cve` -- nama tech di query NVD/Tenable harus di-encode penuh.

Dulu hanya spasi yang diganti (`%20` / `+`): tech seperti `c++` (di NVD `+` dibaca spasi) atau
`a&b` (memotong parameter) merusak query, dan CVE-nya tidak pernah ditemukan."""

from __future__ import annotations

import httpx
import pytest
from cti_scrapers.feeds.new_cve import NewCve

from tests.unit.scraper_helpers import json_response, make_ctx

TECHS = ["c++", "a&b", "palo alto", "node.js"]


def _requested(method_name: str) -> list[httpx.URL]:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return json_response({"vulnerabilities": []})

    ctx = make_ctx(NewCve, handler)
    getattr(NewCve(), method_name)(ctx, TECHS, {})
    return seen


def test_nvd_keyword_is_encoded_per_tech() -> None:
    urls = _requested("_nvd_candidates")
    assert [u.params["keywordSearch"] for u in urls] == TECHS
    assert all("pubStartDate" in u.params and "pubEndDate" in u.params for u in urls)


@pytest.mark.parametrize("tech", TECHS)
def test_tenable_query_starts_with_the_exact_tech(tech: str) -> None:
    index = TECHS.index(tech)
    url = _requested("_tenable_candidates")[index]
    assert url.params["q"].startswith(f"{tech} AND publication_date:")
