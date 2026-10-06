"""`new_cve` -- techstack bernama multi-kata ("palo alto", "microsoft 365").

Bug yang ketemu di staging: kandidat CVE membawa nama ter-encode URL ("palo%20alto" dari NVD,
"palo+alto" dari Tenable) sementara peta tech -> client berkunci nama asli ("palo alto"), jadi
kandidatnya selalu dibuang ("cve_candidate_no_client_match") dan techstack multi-kata TIDAK PERNAH
dapat CVE -- 4 dari 33 techstack di staging, termasuk Palo Alto dan Microsoft 365. Skrip lama
(`newCveThreat.py`) meng-index kedua bentuk dan menyimpan nama yang sudah di-decode."""

from __future__ import annotations

import re

import httpx
from cti_scrapers.feeds.new_cve import NewCve

from tests.unit.scraper_helpers import json_response, make_ctx

# XPath baris hasil Tenable yang di-hardcode scraper -> HTML sintetis yang cocok dengannya.
_ROW_PATH = (
    "/html/body/div/div/div[2]/div/div/div[2]/div/div/div[3]"
    "/div/section/div/div/table/tbody/tr[{i}]"
)


def _segments(path: str) -> list[tuple[str, int]]:
    out = []
    for seg in path.strip("/").split("/"):
        m = re.fullmatch(r"(\w+)(?:\[(\d+)\])?", seg)
        assert m, seg
        out.append((m.group(1), int(m.group(2) or 1)))
    return out


def tenable_html(rows: list[tuple[str, str]]) -> bytes:
    """Halaman yang memuat `rows` (cve_id, summary) di tr[1..n], persis sesuai XPath scraper."""

    def build(segs: list[tuple[str, int]], leaf: str) -> str:
        (tag, pos), rest = segs[0], segs[1:]
        inner = build(rest, leaf) if rest else leaf
        return f"<{tag}></{tag}>" * (pos - 1) + f"<{tag}>{inner}</{tag}>"

    trs = "".join(f"<tr><td><a>{cid}</a></td><td>{summ}</td></tr>" for cid, summ in rows)
    # segmen sampai <tbody>; baris <tr> diisi sekaligus di dalam tbody
    base = _segments(_ROW_PATH.format(i=1).rsplit("/tr[", 1)[0])
    assert base[0][0] == "html"
    return build(base[1:], trs).encode()


MITRE_RECORD = {
    "cveMetadata": {"datePublished": "2026-09-20T00:00:00Z"},
    "containers": {
        "cna": {"metrics": [{"cvssV3_1": {"baseScore": 9.1, "baseSeverity": "CRITICAL"}}]}
    },
}


def run_fetch(techstack_by_client: dict[str, list[str]], nvd: dict, tenable_rows):
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if request.url.host == "services.nvd.nist.gov":
            return json_response(nvd.get(url.split("keywordSearch=")[1].split("&")[0], {}))
        if request.url.host == "www.tenable.com":
            q = url.split("?q=")[1].split("+AND")[0]
            return httpx.Response(200, content=tenable_html(tenable_rows.get(q, [])))
        assert request.url.host == "cveawg.mitre.org", url
        return json_response(MITRE_RECORD)

    techs = sorted({t for ts in techstack_by_client.values() for t in ts})
    ctx = make_ctx(
        NewCve,
        handler,
        reference={"techstack": techs, "techstack_by_client": techstack_by_client},
    )
    items = list(NewCve().fetch(ctx))
    return [(i.cve_id, i.client_id, i.tech) for i in items], requested


def nvd_hit(cve_id: str, summary: str) -> dict:
    return {
        "vulnerabilities": [
            {"cve": {"id": cve_id, "descriptions": [{"lang": "en", "value": summary}]}}
        ]
    }


def test_a_multi_word_techstack_gets_its_cves_from_nvd_stored_under_the_real_name() -> None:
    items, requested = run_fetch(
        {"acme": ["palo alto"]},
        nvd={"palo%20alto": nvd_hit("CVE-2026-9001", "Palo Alto PAN-OS flaw")},
        tenable_rows={},
    )

    assert items == [("CVE-2026-9001", "acme", "palo alto")]  # bukan "palo%20alto"
    assert any("keywordSearch=palo%20alto&" in u for u in requested)  # URL tetap ter-encode


def test_a_multi_word_techstack_gets_its_cves_from_tenable_stored_under_the_real_name() -> None:
    items, requested = run_fetch(
        {"acme": ["microsoft 365"]},
        nvd={},
        tenable_rows={"microsoft+365": [("CVE-2026-9002", "A flaw in Microsoft 365 apps")]},
    )

    assert items == [("CVE-2026-9002", "acme", "microsoft 365")]  # bukan "microsoft+365"
    assert any("q=microsoft+365+AND" in u for u in requested)


def test_tenable_still_rejects_a_hit_that_does_not_really_mention_the_multi_word_tech() -> None:
    items, _ = run_fetch(
        {"acme": ["palo alto"]},
        nvd={},
        tenable_rows={"palo+alto": [("CVE-2026-9003", "A flaw in something unrelated")]},
    )

    assert items == []


def test_every_client_that_has_the_multi_word_tech_gets_its_own_row() -> None:
    items, _ = run_fetch(
        {"acme": ["palo alto", "nginx"], "globex": ["palo alto"]},
        nvd={"palo%20alto": nvd_hit("CVE-2026-9004", "Palo Alto PAN-OS flaw")},
        tenable_rows={},
    )

    assert sorted(items) == [
        ("CVE-2026-9004", "acme", "palo alto"),
        ("CVE-2026-9004", "globex", "palo alto"),
    ]


def test_single_word_techstack_is_unchanged() -> None:
    items, _ = run_fetch(
        {"acme": ["nginx"]},
        nvd={"nginx": nvd_hit("CVE-2026-9005", "nginx flaw")},
        tenable_rows={},
    )

    assert items == [("CVE-2026-9005", "acme", "nginx")]
