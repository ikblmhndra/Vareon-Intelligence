"""`new_cve` -- kolom Tech di CVE Tracker harus cocok dengan produk yang terdampak (Affected).

Bug yang ketemu di UI (2026-10-05): `keywordSearch` NVD cuma mencocokkan kata di deskripsi mana
pun, jadi CVE Zabbix yang menyebut MariaDB tercatat sebagai tech MARIADB dengan Affected "Zabbix",
CVE Plane yang menyebut GitLab OAuth jadi GITLAB, CVE repo Chainguard Academy jadi NGINX, dan CVE
Pandora FMS jadi GRAFANA. Selain itu `seen` global membuat CVE yang kena beberapa tech menempel ke
tech pertama saja."""

from __future__ import annotations

from typing import Any

import httpx
from cti_scrapers.feeds.new_cve import NewCve

from tests.unit.scraper_helpers import json_response, make_ctx
from tests.unit.test_new_cve_multiword_tech import nvd_hit, tenable_html


def mitre(*affected: dict[str, Any]) -> dict[str, Any]:
    cna: dict[str, Any] = {"affected": list(affected)} if affected else {}
    return {"cveMetadata": {"datePublished": "2026-10-05T00:00:00Z"}, "containers": {"cna": cna}}


def product(vendor: str, name: str, **extra: Any) -> dict[str, Any]:
    return {
        "vendor": vendor,
        "product": name,
        "versions": [{"status": "affected", "version": "0", "lessThan": "9.9"}],
        **extra,
    }


def run(
    techstack_by_client: dict[str, list[str]],
    nvd: dict[str, dict],
    records: dict[str, dict],
    tenable_rows: dict[str, list[tuple[str, str]]] | None = None,
) -> list[tuple[str, str, str]]:
    """`nvd`: {keyword_ter-encode: respons NVD}; `records`: {cve_id: record MITRE}."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "services.nvd.nist.gov":
            return json_response(nvd.get(url.split("keywordSearch=")[1].split("&")[0], {}))
        if request.url.host == "www.tenable.com":
            q = url.split("?q=")[1].split("+AND")[0]
            return httpx.Response(200, content=tenable_html((tenable_rows or {}).get(q, [])))
        assert request.url.host == "cveawg.mitre.org", url
        return json_response(records[url.rsplit("/", 1)[1]])

    techs = sorted({t for ts in techstack_by_client.values() for t in ts})
    ctx = make_ctx(
        NewCve,
        handler,
        reference={"techstack": techs, "techstack_by_client": techstack_by_client},
    )
    return sorted((i.cve_id, i.client_id, i.tech) for i in NewCve().fetch(ctx))


def test_a_cve_that_only_mentions_the_tech_in_passing_is_not_tracked_under_it() -> None:
    items = run(
        {"acme": ["mariadb"]},
        nvd={
            "mariadb": nvd_hit("CVE-2026-59783", "Zabbix binary items crash on NULL byte, MariaDB")
        },
        records={"CVE-2026-59783": mitre(product("Zabbix", "Zabbix"))},
    )

    assert items == []


def test_each_unrelated_cve_from_the_ui_report_is_dropped_and_the_real_ones_are_kept() -> None:
    items = run(
        {"acme": ["gitlab", "nginx", "grafana", "n8n"]},
        nvd={
            "gitlab": {
                "vulnerabilities": [
                    *nvd_hit("CVE-2026-105640", "Plane trusts emails from Gitea, GitLab OAuth")[
                        "vulnerabilities"
                    ],
                    *nvd_hit("CVE-2026-90970", "GitLab has remediated a flaw in AI Gateway")[
                        "vulnerabilities"
                    ],
                ]
            },
            "nginx": nvd_hit(
                "CVE-2026-105766", "Use of $scheme in nginx.conf of Chainguard Academy"
            ),
            "grafana": nvd_hit("CVE-2026-75786", "Pandora FMS Grafana datasource SQL injection"),
            "n8n": nvd_hit("CVE-2026-103260", "n8n versions before 2.39.6 approval bypass"),
        },
        records={
            "CVE-2026-105640": mitre(product("makeplane", "plane")),
            "CVE-2026-90970": mitre(product("GitLab", "GitLab AI Gateway")),
            "CVE-2026-105766": mitre(product("chainguard-dev", "Chainguard Academy (edu)")),
            "CVE-2026-75786": mitre(product("Artica", "Pandora FMS")),
            "CVE-2026-103260": mitre(product("n8n-io", "n8n")),
        },
    )

    assert items == [
        ("CVE-2026-103260", "acme", "n8n"),
        ("CVE-2026-90970", "acme", "gitlab"),
    ]


def test_vendor_alone_is_enough_when_the_product_has_a_different_name() -> None:
    items = run(
        {"acme": ["palo alto"]},
        nvd={"palo%20alto": nvd_hit("CVE-2026-9101", "Palo Alto Networks PAN-OS flaw")},
        records={"CVE-2026-9101": mitre(product("Palo Alto Networks", "PAN-OS"))},
    )

    assert items == [("CVE-2026-9101", "acme", "palo alto")]


def test_cpe_names_match_even_though_they_use_underscores() -> None:
    items = run(
        {"acme": ["palo alto"]},
        nvd={"palo%20alto": nvd_hit("CVE-2026-9102", "Palo Alto firewall flaw")},
        records={
            "CVE-2026-9102": mitre(
                {"product": "GlobalProtect", "cpes": ["cpe:2.3:a:palo_alto_networks:pan-os:*"]}
            )
        },
    )

    assert items == [("CVE-2026-9102", "acme", "palo alto")]


def test_a_tech_name_does_not_match_inside_a_longer_word() -> None:
    items = run(
        {"acme": ["nginx"]},
        nvd={"nginx": nvd_hit("CVE-2026-9103", "nginx-ui panel flaw")},
        records={"CVE-2026-9103": mitre(product("0xJacky", "nginxy-panel"))},
    )

    assert items == []


def test_a_cve_that_hits_several_techs_goes_to_every_client_that_has_one_of_them() -> None:
    """Dulu `seen` global: CVE Atlassian yang muncul lewat "jira" dan "confluence" cuma nempel ke
    tech yang kebetulan ketemu duluan, jadi client yang hanya punya Confluence tak pernah dapat."""
    atlassian = mitre(
        product("Atlassian", "Jira Service Management Data Center"),
        product("Atlassian", "Confluence Data Center"),
        product("Atlassian", "Bamboo Data Center"),
    )
    hit = nvd_hit("CVE-2026-21589", "Atlassian Jira and Confluence Data Center flaw")

    items = run(
        {"acme": ["jira"], "globex": ["confluence"], "initech": ["bamboo", "grafana"]},
        nvd={"jira": hit, "confluence": hit, "bamboo": hit},
        records={"CVE-2026-21589": atlassian},
    )

    assert items == [
        ("CVE-2026-21589", "acme", "jira"),
        ("CVE-2026-21589", "globex", "confluence"),
        ("CVE-2026-21589", "initech", "bamboo"),
    ]


def test_a_client_with_two_affected_techs_gets_one_row_with_the_earlier_tech() -> None:
    hit = nvd_hit("CVE-2026-9104", "Atlassian Jira and Confluence flaw")
    atlassian = mitre(product("Atlassian", "Jira"), product("Atlassian", "Confluence"))

    items = run(
        {"acme": ["jira", "confluence"]},
        nvd={"jira": hit, "confluence": hit},
        records={"CVE-2026-9104": atlassian},
    )

    assert items == [("CVE-2026-9104", "acme", "confluence")]  # urutan techstack: confluence < jira


def test_without_product_data_the_summary_is_the_fallback() -> None:
    items = run(
        {"acme": ["fortinet", "grafana"]},
        nvd={
            "fortinet": nvd_hit("CVE-2026-9105", "Fortinet FortiOS flaw"),
            "grafana": nvd_hit("CVE-2026-9106", "Grafana dashboard flaw"),
        },
        records={
            "CVE-2026-9105": mitre(),  # CNA tak mengisi `affected`
            "CVE-2026-9106": mitre({"vendor": "n/a", "product": "N/A"}),  # placeholder
        },
    )

    assert items == [
        ("CVE-2026-9105", "acme", "fortinet"),
        ("CVE-2026-9106", "acme", "grafana"),
    ]


def test_tenable_hits_are_checked_against_the_affected_product_too() -> None:
    items = run(
        {"acme": ["mariadb"]},
        nvd={},
        records={"CVE-2026-9107": mitre(product("Zabbix", "Zabbix"))},
        tenable_rows={"mariadb": [("CVE-2026-9107", "Zabbix Server crash, tested on MariaDB")]},
    )

    assert items == []
