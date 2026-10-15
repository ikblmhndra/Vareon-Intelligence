"""`new_cve` -- batas `max_items` tidak boleh membuang CVE diam-diam.

Bug prod (2026-10-15): override `max_items=100` di `scraper_configs`. `fetch()` menyusun kandidat
menurut urutan `techstack` (abjad) lalu `return` begitu cap tercapai, jadi tech di belakang abjad
(palo alto, proofpoint, ...) kelaparan setiap kali tech awal (fortinet, gitlab, ...) ramai. Tiap run
FOUND=100 persis, status `ok`, tanpa log -- 12 CVE Palo Alto (CVE-2026-0311..0322) tak pernah
tercatat. Dikunci di sini: (a) cap memicu warning + `partial`, (b) tech di belakang abjad tetap
diproses (antrean round-robin antar tech)."""

from __future__ import annotations

import dataclasses
from typing import Any

import httpx
import structlog
from cti_scraper.base import ScrapeContext
from cti_scrapers.feeds.new_cve import NewCve

from tests.unit.scraper_helpers import json_response, make_ctx
from tests.unit.test_new_cve_multiword_tech import MITRE_RECORD, tenable_html

TECHS = ["fortinet", "gitlab", "proofpoint"]  # abjad, seperti `_resolve_techstack`


def nvd_for(tech: str, count: int, base: int) -> dict[str, Any]:
    """`count` CVE NVD untuk satu tech; ringkasannya menyebut tech supaya lolos gate relevansi."""
    return {
        "vulnerabilities": [
            {
                "cve": {
                    "id": f"CVE-2026-{base + i}",
                    "descriptions": [{"lang": "en", "value": f"{tech} flaw {i}"}],
                }
            }
            for i in range(count)
        ]
    }


def run(
    max_items: int,
    nvd: dict[str, dict[str, Any]],
    techstack_by_client: dict[str, list[str]] | None = None,
) -> tuple[list[tuple[str, str, str]], ScrapeContext, list[dict[str, Any]]]:
    """Jalankan `fetch()` dengan `max_items` tertentu; kembalikan (cve, client, tech), ctx, log."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "services.nvd.nist.gov":
            return json_response(nvd.get(url.split("keywordSearch=")[1].split("&")[0], {}))
        if request.url.host == "www.tenable.com":
            return httpx.Response(200, content=tenable_html([]))
        assert request.url.host == "cveawg.mitre.org", url
        return json_response(MITRE_RECORD)

    by_client = techstack_by_client or {"acme": TECHS}
    techs = sorted({t for ts in by_client.values() for t in ts})
    ctx = make_ctx(
        NewCve,
        handler,
        reference={"techstack": techs, "techstack_by_client": by_client},
    )
    # `Runner` memasang `meta` hasil override `ScraperConfig` ke scraper dan ctx; tiru itu.
    meta = dataclasses.replace(NewCve.meta, max_items=max_items)
    ctx.meta = meta
    scraper = NewCve()
    scraper.meta = meta  # type: ignore[misc]

    with structlog.testing.capture_logs() as logs:
        items = list(scraper.fetch(ctx))
    return [(i.cve_id, i.client_id, i.tech) for i in items], ctx, logs


# Fortinet & GitLab ramai (6 CVE), Proofpoint sedikit (3); semuanya lolos gate relevansi.
BUSY = {
    "fortinet": nvd_for("fortinet", 6, 1000),
    "gitlab": nvd_for("gitlab", 6, 2000),
    "proofpoint": nvd_for("proofpoint", 3, 3000),
}


def test_a_cap_that_cuts_the_run_logs_a_warning_with_what_was_left_behind() -> None:
    items, _ctx, logs = run(4, BUSY)

    assert len(items) == 4
    [entry] = [e for e in logs if e["event"] == "cve_max_items_reached"]
    assert entry["log_level"] == "warning"
    assert entry["max_items"] == 4
    assert entry["remaining_candidates"] == 11  # 15 kandidat - 4 yang sudah tercatat
    assert entry["first_tech"] == "fortinet"
    assert entry["pending_techs"] == TECHS


def test_a_cap_that_cuts_the_run_marks_it_partial_not_ok() -> None:
    _items, ctx, _logs = run(4, BUSY)

    assert ctx.partial_reason is not None
    assert "max_items=4" in ctx.partial_reason
    assert "11 kandidat" in ctx.partial_reason
    assert "fortinet" in ctx.partial_reason


def test_a_tech_late_in_the_alphabet_is_still_processed_when_the_cap_hits() -> None:
    """Dulu: fortinet menghabiskan cap 4 dan proofpoint tak pernah tersentuh."""
    items, _ctx, _logs = run(4, BUSY)

    assert {tech for _cve, _client, tech in items} == set(TECHS)
    # round-robin: satu per tech dulu, baru putaran kedua
    assert [tech for _cve, _client, tech in items] == [
        "fortinet",
        "gitlab",
        "proofpoint",
        "fortinet",
    ]


def test_without_a_cap_every_tech_gets_all_of_its_cves_and_the_run_is_complete() -> None:
    items, ctx, logs = run(300, BUSY)

    assert len(items) == 15
    assert ctx.partial_reason is None
    assert not [e for e in logs if e["event"] == "cve_max_items_reached"]


def test_a_cap_equal_to_the_number_of_cves_loses_nothing_so_it_is_not_partial() -> None:
    items, ctx, logs = run(15, BUSY)

    assert len(items) == 15
    assert ctx.partial_reason is None
    assert not [e for e in logs if e["event"] == "cve_max_items_reached"]


def test_a_cap_that_lands_between_the_clients_of_one_cve_is_partial_too() -> None:
    """Satu CVE = satu baris per client: cap=1 mencatat acme saja, globex ikut terbuang."""
    items, ctx, logs = run(
        1,
        {"fortinet": nvd_for("fortinet", 1, 1000)},
        {"acme": ["fortinet"], "globex": ["fortinet"]},
    )

    assert items == [("CVE-2026-1000", "acme", "fortinet")]
    [entry] = [e for e in logs if e["event"] == "cve_max_items_reached"]
    assert entry["remaining_candidates"] == 1  # kandidat yang baru sebagian tercatat
    assert ctx.partial_reason is not None


def test_a_cve_that_several_techs_report_is_processed_once() -> None:
    candidates: dict[str, dict[str, Any]] = {}
    for tech, cve_id in [
        ("fortinet", "CVE-1"),
        ("gitlab", "CVE-1"),  # CVE yang sama dilaporkan dua tech
        ("gitlab", "CVE-2"),
        ("proofpoint", "CVE-3"),
    ]:
        NewCve._add_candidate(candidates, cve_id, tech, "link", "summary")

    ordered = NewCve._fair_order(candidates, {t: i for i, t in enumerate(TECHS)})

    assert [c["id"] for c in ordered] == ["CVE-1", "CVE-3", "CVE-2"]


def test_techs_are_ordered_by_the_techstack_not_by_arrival() -> None:
    candidates: dict[str, dict[str, Any]] = {}
    for tech, cve_id in [("proofpoint", "CVE-3"), ("gitlab", "CVE-2"), ("fortinet", "CVE-1")]:
        NewCve._add_candidate(candidates, cve_id, tech, "link", "summary")

    ordered = NewCve._fair_order(candidates, {t: i for i, t in enumerate(TECHS)})

    assert [c["id"] for c in ordered] == ["CVE-1", "CVE-2", "CVE-3"]
