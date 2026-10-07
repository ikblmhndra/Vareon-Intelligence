"""`tools/ops/reconcile_cve_tech.py` -- bersihkan baris `cve_tracker` lama yang Tech-nya tidak
cocok dengan produk terdampak (bug 0.2.1, lihat `test_new_cve_tech_relevance.py`).

Yang dikunci: penilai memakai aturan yang sama dengan scraper; tidak pernah bertindak tanpa bukti
(MITRE gagal / tanpa produk dan tanpa ringkasan); baris ber-ticket tidak pernah jadi `delete`."""

from __future__ import annotations

import httpx
import pytest

from tools.ops.reconcile_cve_tech import Row, fetch_products, plan, render


def row(cve_id: str, tech: str, *, client: str = "acme", summary: str = "", ticket: bool = False):
    return Row(
        id=1,
        cve_id=cve_id,
        client_id=client,
        tech=tech,
        summary=summary,
        affected=("Zabbix: < 7.0",),
        has_ticket=ticket,
    )


ZABBIX = ["Zabbix", "Zabbix"]
ATLASSIAN = ["Atlassian", "Jira Core Data Center", "Atlassian", "Confluence Data Center"]


def actions(rows, products, techs=None) -> list[tuple[str, str | None]]:
    return [(f.action, f.new_tech) for f in plan(rows, products, techs or {}).findings]


def test_a_matching_row_is_left_alone() -> None:
    result = plan([row("CVE-1", "zabbix")], {"CVE-1": ZABBIX}, {})

    assert result.findings == [] and result.ok == 1


def test_a_product_name_with_a_glued_major_version_is_not_a_mismatch() -> None:
    """Dari laporan produksi: `graylog2-server` untuk tech `graylog` hampir ikut dihapus."""
    result = plan(
        [row("CVE-1", "graylog")], {"CVE-1": ["Graylog2", "graylog2-server"]}, {"acme": ["graylog"]}
    )

    assert result.findings == [] and result.ok == 1


def test_a_mismatched_row_with_no_better_tech_is_deleted() -> None:
    assert actions([row("CVE-1", "mariadb")], {"CVE-1": ZABBIX}, {"acme": ["mariadb"]}) == [
        ("delete", None)
    ]


def test_a_mismatched_row_is_retagged_to_another_tech_of_the_same_client() -> None:
    """Sisa bug `seen` global: CVE Atlassian menempel ke `jira`, padahal client ini hanya
    menjalankan Confluence."""
    found = actions(
        [row("CVE-1", "jira")],
        {"CVE-1": ["Atlassian", "Confluence Data Center"]},
        {"acme": ["jira", "confluence", "grafana"]},
    )

    assert found == [("retag", "confluence")]


def test_retag_only_considers_techs_of_the_rows_own_client() -> None:
    found = actions(
        [row("CVE-1", "jira", client="acme")],
        {"CVE-1": ["Atlassian", "Confluence Data Center"]},
        {"acme": ["jira"], "globex": ["confluence"]},
    )

    assert found == [("delete", None)]


def test_a_row_with_a_ticket_is_never_deleted_only_flagged_for_review() -> None:
    assert actions([row("CVE-1", "mariadb", ticket=True)], {"CVE-1": ZABBIX}, {}) == [
        ("review", None)
    ]


def test_a_ticketed_row_can_still_be_retagged() -> None:
    found = actions(
        [row("CVE-1", "jira", ticket=True)],
        {"CVE-1": ["Atlassian", "Confluence Data Center"]},
        {"acme": ["confluence"]},
    )

    assert found == [("retag", "confluence")]


def test_nothing_is_decided_when_mitre_could_not_be_reached() -> None:
    result = plan([row("CVE-1", "mariadb")], {"CVE-1": None}, {})

    assert result.findings == [] and result.unverified == 1


def test_nothing_is_decided_without_any_evidence_at_all() -> None:
    """Tanpa produk (atau cuma "n/a") DAN tanpa ringkasan -- scraper pun tak punya pegangan."""
    result = plan(
        [row("CVE-1", "mariadb"), row("CVE-2", "mariadb")],
        {"CVE-1": [], "CVE-2": ["n/a", "N/A"]},
        {},
    )

    assert result.findings == [] and result.unverified == 2


def test_without_product_data_the_stored_summary_decides_like_the_scraper_does() -> None:
    result = plan(
        [
            row("CVE-1", "grafana", summary="Grafana dashboard flaw"),
            row("CVE-2", "nginx", summary="x"),
        ],
        {"CVE-1": [], "CVE-2": []},
        {},
    )

    assert result.ok == 1
    assert [(f.row.cve_id, f.action) for f in result.findings] == [("CVE-2", "delete")]


def test_one_cve_is_judged_per_row_so_two_clients_can_get_different_verdicts() -> None:
    rows = [row("CVE-1", "zabbix", client="acme"), row("CVE-1", "mariadb", client="globex")]

    result = plan(rows, {"CVE-1": ZABBIX}, {})

    assert result.ok == 1
    assert [(f.row.client_id, f.action) for f in result.findings] == [("globex", "delete")]


def test_the_report_line_shows_what_will_happen_and_the_ui_affected_text() -> None:
    f = plan([row("CVE-2026-59783", "mariadb")], {"CVE-2026-59783": ZABBIX}, {}).findings[0]

    line = render(f, ZABBIX)

    assert line.startswith("DELETE")
    assert "CVE-2026-59783" in line and "mariadb" in line and "Zabbix: < 7.0" in line


# ---- fetch_products ---------------------------------------------------------------------------


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


RECORD = {"containers": {"cna": {"affected": [{"vendor": "Zabbix", "product": "Zabbix"}]}}}


def test_fetch_products_reads_vendor_and_product() -> None:
    http = client(lambda r: httpx.Response(200, json=RECORD))

    assert fetch_products(http, "CVE-1", sleep=lambda s: None) == ["Zabbix", "Zabbix"]


def test_fetch_products_gives_up_cleanly_on_404_without_retrying() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404)

    assert fetch_products(client(handler), "CVE-1", sleep=lambda s: None) is None
    assert len(calls) == 1


def test_fetch_products_retries_rate_limits_then_succeeds() -> None:
    statuses = iter([429, 503, 200])
    waited: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        return httpx.Response(status, json=RECORD if status == 200 else {})

    assert fetch_products(client(handler), "CVE-1", sleep=waited.append) == ["Zabbix", "Zabbix"]
    assert waited == [5.0, 10.0]


def test_fetch_products_returns_none_when_the_error_never_clears() -> None:
    http = client(lambda r: httpx.Response(500))

    assert fetch_products(http, "CVE-1", sleep=lambda s: None) is None


def test_fetch_products_returns_none_for_a_network_error_and_for_non_json() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("putus")

    assert fetch_products(client(boom), "CVE-1", sleep=lambda s: None) is None
    http = client(lambda r: httpx.Response(200, content=b"<html>"))
    assert fetch_products(http, "CVE-1", sleep=lambda s: None) is None


@pytest.mark.parametrize("body", [{}, {"containers": {}}, {"containers": {"cna": {}}}])
def test_a_record_without_affected_data_gives_an_empty_list_not_none(body: dict) -> None:
    http = client(lambda r: httpx.Response(200, json=body))

    assert fetch_products(http, "CVE-1", sleep=lambda s: None) == []
