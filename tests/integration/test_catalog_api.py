"""API katalog + CVE DB + Monitor berbasis katalog (ROADMAP #19, irisan 5), lewat HTTP beneran.

Yang dikunci: aturan tampilan jelajah (keluarga ber-1 CVE disembunyikan; `q`, `show_all`, dan yang
sudah di-Monitor selalu tampil), pagination, status Monitor per client, CVE DB baca-saja, bentuk
entri Monitor (katalog vs custom) dan kegagalannya, target (tambah/lepas/terakhir tak boleh
dilepas), nonaktif = disembunyikan dari tab CVEs tanpa menghapus, dan pemicu promosi."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

import pytest
from cti_core.catalog_resolve import AffectedEntry, resolve_all
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.catalog import CveMirrorRepo, MirrorRecord
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

UTC = datetime.UTC
D = datetime.date

# (cve_id, terbit, [(vendor, produk)], severity)
SEED: list[tuple[str, datetime.date, list[tuple[str, str]], str | None]] = [
    ("CVE-2026-0001", D(2026, 3, 1), [("Fortinet", "FortiOS")], "CRITICAL"),
    ("CVE-2026-0002", D(2026, 3, 2), [("Fortinet", "FortiOS"), ("Fortinet", "FortiProxy")], "HIGH"),
    ("CVE-2026-0003", D(2026, 3, 3), [("Fortinet", "FortiOS")], "HIGH"),
    ("CVE-2026-0004", D(2026, 4, 1), [("Palo Alto Networks", "PAN-OS")], "MEDIUM"),
    ("CVE-2026-0005", D(2026, 4, 2), [("Palo Alto Networks", "PAN-OS")], None),
    ("CVE-2026-0006", D(2026, 5, 1), [("Acme", "Widget")], "LOW"),
    ("CVE-2026-0007", D(2026, 5, 2), [("", "Orphan Tool")], "LOW"),
]


async def seed_catalog(session: AsyncSession) -> None:
    def _do(sync: Any) -> None:
        repo = CveMirrorRepo(sync)
        for cve_id, published, pairs, severity in SEED:
            repo.upsert(
                MirrorRecord(
                    cve_id=cve_id,
                    published_date=published,
                    published_at=datetime.datetime.combine(published, datetime.time(9), tzinfo=UTC),
                    modified_at=datetime.datetime.combine(published, datetime.time(10), tzinfo=UTC),
                    summary=f"{cve_id} overflow in {pairs[0][1]}",
                    link=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
                    cvss_severity=severity,
                    cvss_score=9.8 if severity == "CRITICAL" else None,
                    reference_urls=["https://example.org/x"],
                    affected_lines=[f"{pairs[0][1]}: < 2.0"],
                ),
                resolve_all(AffectedEntry(vendor=v, product=p) for v, p in pairs),
            )

    await session.run_sync(_do)
    await session.flush()


async def vid(session: AsyncSession, key: str) -> int:
    return (
        await session.execute(select(CatalogVendor.id).where(CatalogVendor.key == key))
    ).scalar_one()


async def fid(session: AsyncSession, key: str) -> int:
    return (
        await session.execute(select(CatalogFamily.id).where(CatalogFamily.key == key))
    ).scalar_one()


@pytest.fixture
def h(auth_header: Callable[..., dict[str, str]]) -> dict[str, str]:
    return auth_header()


# ── katalog: vendor ───────────────────────────────────────────────────────────────────────────


async def test_vendor_browse_hides_vendors_whose_families_all_have_one_cve(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    body = (await api_client.get("/api/catalog/vendors", headers=h)).json()
    names = [v["display_name"] for v in body["items"]]
    assert names == ["Fortinet", "Palo Alto Networks"]  # urut CVE terbanyak
    assert body["total"] == 2 and body["hidden"] == 2  # Acme dan "(tanpa vendor)"
    forti = body["items"][0]
    assert (forti["family_count"], forti["visible_family_count"]) == (2, 1)
    assert forti["cve_seen_total"] == 3 and forti["monitored"] is False and forti["monitorable"]


async def test_vendor_show_all_and_search_never_hide(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    everyone = (await api_client.get("/api/catalog/vendors?show_all=true", headers=h)).json()
    assert everyone["total"] == 4 and everyone["hidden"] == 0
    none_vendor = next(v for v in everyone["items"] if v["key"] == "~none")
    assert none_vendor["monitorable"] is False and none_vendor["display_name"] == "(tanpa vendor)"

    found = (await api_client.get("/api/catalog/vendors?q=acme", headers=h)).json()
    assert [v["display_name"] for v in found["items"]] == ["Acme"]  # ber-1 CVE, tetap ketemu
    compact = (await api_client.get("/api/catalog/vendors?q=palo%20alto", headers=h)).json()
    assert [v["key"] for v in compact["items"]] == ["paloaltonetworks"]
    assert (await api_client.get("/api/catalog/vendors?q=zzz", headers=h)).json()["total"] == 0


async def test_search_input_is_literal_not_a_like_pattern(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    assert (await api_client.get("/api/catalog/vendors?q=%25", headers=h)).json()["total"] == 0
    assert (await api_client.get("/api/catalog/vendors?q=_", headers=h)).json()["total"] == 0


async def test_vendor_pagination_and_limits(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    p1 = (
        await api_client.get("/api/catalog/vendors?show_all=true&page=1&page_size=3", headers=h)
    ).json()
    p2 = (
        await api_client.get("/api/catalog/vendors?show_all=true&page=2&page_size=3", headers=h)
    ).json()
    assert (len(p1["items"]), len(p2["items"]), p1["total"]) == (3, 1, 4)
    assert {v["id"] for v in p1["items"]}.isdisjoint(v["id"] for v in p2["items"])
    assert (
        await api_client.get("/api/catalog/vendors?page_size=101", headers=h)
    ).status_code == 422
    assert (await api_client.get("/api/catalog/vendors")).status_code in (401, 403)


# ── katalog: keluarga ─────────────────────────────────────────────────────────────────────────


async def test_family_browse_hides_single_cve_families_but_not_monitored_ones(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    forti = await vid(api_session, "fortinet")
    url = f"/api/catalog/vendors/{forti}/families"
    body = (await api_client.get(url, headers=h)).json()
    assert [f["key"] for f in body["items"]] == ["fortios"] and body["hidden"] == 1
    assert body["items"][0]["cve_seen_total"] == 3

    everything = (await api_client.get(url + "?show_all=true", headers=h)).json()
    assert [f["key"] for f in everything["items"]] == ["fortios", "fortiproxy"]
    searched = (await api_client.get(url + "?q=proxy", headers=h)).json()
    assert [f["key"] for f in searched["items"]] == ["fortiproxy"]

    # yang sudah di-Monitor selalu tampil, walau hanya 1 CVE
    created = await api_client.post(
        "/api/techstack", headers=h, json={"family_id": await fid(api_session, "fortiproxy")}
    )
    assert created.json()["success"] is True
    again = (await api_client.get(url, headers=h)).json()
    assert [f["key"] for f in again["items"]] == ["fortios", "fortiproxy"] and again["hidden"] == 0
    proxy = again["items"][1]
    assert proxy["monitored"] is True and proxy["monitor_entry_id"] is not None


async def test_unknown_vendor_is_404_and_family_search_needs_two_chars(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    assert (
        await api_client.get("/api/catalog/vendors/999999/families", headers=h)
    ).status_code == 404
    assert (await api_client.get("/api/catalog/families?q=a", headers=h)).status_code == 422
    assert (await api_client.get("/api/catalog/families", headers=h)).status_code == 422


async def test_family_search_spans_vendors_and_shows_single_cve_families(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    body = (await api_client.get("/api/catalog/families?q=wid", headers=h)).json()
    assert [(f["display_name"], f["vendor_name"], f["cve_seen_total"]) for f in body["items"]] == [
        ("Widget", "Acme", 1)
    ]
    both = (await api_client.get("/api/catalog/families?q=forti", headers=h)).json()
    assert [f["key"] for f in both["items"]] == ["fortios", "fortiproxy"]  # urut CVE


async def test_vendor_monitor_covers_its_families(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    forti = await vid(api_session, "fortinet")
    entry = (await api_client.post("/api/techstack", headers=h, json={"vendor_id": forti})).json()
    assert entry["success"] and entry["item"]["name"] == "Fortinet"
    vendors = (await api_client.get("/api/catalog/vendors?q=fortinet", headers=h)).json()["items"]
    assert vendors[0]["monitored"] is True
    fams = (
        await api_client.get(f"/api/catalog/vendors/{forti}/families?show_all=true", headers=h)
    ).json()["items"]
    assert all(f["monitored"] and f["covered_by_vendor"] for f in fams)


async def test_monitor_status_is_per_client(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    from cti_core.db.repositories.auth import AsyncClientRepo

    await AsyncClientRepo(api_session).create(client_id="globex", name="Globex", countries=[])
    await seed_catalog(api_session)
    mine = auth_header(client_ids=["default", "globex"])
    fam = await fid(api_session, "fortios")
    await api_client.post(
        "/api/techstack", headers={**mine, "X-Client-ID": "default"}, json={"family_id": fam}
    )
    url = "/api/catalog/families?q=fortios"
    default = (await api_client.get(url, headers={**mine, "X-Client-ID": "default"})).json()
    globex = (await api_client.get(url, headers={**mine, "X-Client-ID": "globex"})).json()
    assert default["items"][0]["monitored"] is True and globex["items"][0]["monitored"] is False


# ── CVE DB ────────────────────────────────────────────────────────────────────────────────────


async def test_cve_db_list_filters_and_marks_monitored_products(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    allrows = (await api_client.get("/api/cve-db", headers=h)).json()
    assert allrows["total"] == 7
    assert allrows["items"][0]["cve_id"] == "CVE-2026-0007"  # terbaru dulu
    assert allrows["items"][-1]["cve_id"] == "CVE-2026-0001"

    by_family = (
        await api_client.get(
            f"/api/cve-db?family={await fid(api_session, 'fortiproxy')}", headers=h
        )
    ).json()
    assert [c["cve_id"] for c in by_family["items"]] == ["CVE-2026-0002"]
    by_vendor = (
        await api_client.get(f"/api/cve-db?vendor={await vid(api_session, 'fortinet')}", headers=h)
    ).json()
    assert by_vendor["total"] == 3
    assert (await api_client.get("/api/cve-db?q=pan-os", headers=h)).json()["total"] == 2
    assert (await api_client.get("/api/cve-db?q=CVE-2026-000", headers=h)).json()["total"] == 7
    assert (await api_client.get("/api/cve-db?severity=high&severity=low", headers=h)).json()[
        "total"
    ] == 4
    window = (
        await api_client.get("/api/cve-db?date_start=2026-04-01&date_end=2026-04-30", headers=h)
    ).json()
    assert window["total"] == 2

    await api_client.post(
        "/api/techstack", headers=h, json={"family_id": await fid(api_session, "fortios")}
    )
    row = (await api_client.get("/api/cve-db?q=CVE-2026-0002", headers=h)).json()["items"][0]
    flags = {p["family"]: p["monitored"] for p in row["products"]}
    assert flags == {"FortiOS": True, "FortiProxy": False}


async def test_cve_db_without_identity_and_detail(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    detail = (await api_client.get("/api/cve-db/cve-2026-0001", headers=h)).json()  # huruf kecil ok
    assert detail["cve_id"] == "CVE-2026-0001" and detail["cvss_severity"] == "CRITICAL"
    assert detail["reference_urls"] == ["https://example.org/x"]
    assert detail["affected_lines"] == ["FortiOS: < 2.0"]
    assert (
        detail["link"].endswith("CVE-2026-0001") and detail["products"][0]["vendor"] == "Fortinet"
    )
    assert (await api_client.get("/api/cve-db/CVE-1999-0001", headers=h)).status_code == 404
    assert (await api_client.get("/api/cve-db?page_size=500", headers=h)).status_code == 422


async def test_cve_db_truncates_long_summaries_in_the_list_only(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    def _do(sync: Any) -> None:
        CveMirrorRepo(sync).upsert(
            MirrorRecord(cve_id="CVE-2026-0100", published_date=D(2026, 6, 1), summary="x" * 900),
            resolve_all([AffectedEntry(vendor="Acme", product="Widget")]),
        )

    await api_session.run_sync(_do)
    row = (await api_client.get("/api/cve-db?q=CVE-2026-0100", headers=h)).json()["items"][0]
    assert len(row["summary"]) == 403 and row["summary"].endswith("...")
    detail = (await api_client.get("/api/cve-db/CVE-2026-0100", headers=h)).json()
    assert len(detail["summary"]) == 900


# ── Monitor ───────────────────────────────────────────────────────────────────────────────────


async def test_monitor_catalog_entry_shape_and_label_override(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    fam = await fid(api_session, "fortios")
    r = (await api_client.post("/api/techstack", headers=h, json={"family_id": fam})).json()
    item = r["item"]
    assert r["success"] and item["name"] == "FortiOS" and item["kind"] == "catalog"
    assert item["source"] == "catalog" and item["active"] is True
    assert item["targets"] == [
        {
            "id": item["targets"][0]["id"],
            "kind": "family",
            "vendor_id": None,
            "family_id": fam,
            "label": "FortiOS",
            "vendor_label": "Fortinet",
        }
    ]
    dup = (await api_client.post("/api/techstack", headers=h, json={"family_id": fam})).json()
    assert dup == {"success": False, "reason": "duplicate"}
    renamed = (
        await api_client.post(
            "/api/techstack", headers=h, json={"family_id": fam, "name": "fortigate"}
        )
    ).json()
    assert renamed["success"] and renamed["item"]["name"] == "fortigate"


async def test_monitor_rejections(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    none_vendor = await vid(api_session, "~none")
    post = lambda body: api_client.post("/api/techstack", headers=h, json=body)  # noqa: E731
    assert (await post({"vendor_id": none_vendor})).json() == {
        "success": False,
        "reason": "vendor_not_monitorable",
    }
    assert (await post({"family_id": 999999})).json() == {"success": False, "reason": "not_found"}
    assert (await post({"vendor_id": 999999})).json()["reason"] == "not_found"
    assert (await post({})).status_code == 422
    assert (await post({"name": "  "})).status_code == 422
    assert (await post({"vendor_id": 1, "family_id": 1})).status_code == 422


async def test_custom_entry_keeps_the_old_contract(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    r = (await api_client.post("/api/techstack", headers=h, json={"name": "nginx"})).json()
    assert r["success"] and r["item"]["kind"] == "custom" and r["item"]["targets"] == []
    assert r["item"]["source"] == "manual" and r["item"]["active"] is True
    assert (await api_client.post("/api/techstack", headers=h, json={"name": "NGINX"})).json() == {
        "success": False,
        "reason": "duplicate",
    }


async def test_targets_add_remove_and_last_one_is_protected(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    entry = (
        await api_client.post(
            "/api/techstack",
            headers=h,
            json={"family_id": await fid(api_session, "fortios"), "name": "forti"},
        )
    ).json()["item"]
    base = f"/api/techstack/{entry['id']}/targets"
    proxy = await fid(api_session, "fortiproxy")

    added = await api_client.post(base, headers=h, json={"family_id": proxy})
    assert added.status_code == 200 and len(added.json()["item"]["targets"]) == 2
    assert (await api_client.post(base, headers=h, json={"family_id": proxy})).status_code == 409
    assert (await api_client.post(base, headers=h, json={"family_id": 999999})).status_code == 404
    assert (await api_client.post(base, headers=h, json={})).status_code == 422
    assert (
        await api_client.post(base, headers=h, json={"vendor_id": await vid(api_session, "~none")})
    ).status_code == 422
    assert (
        await api_client.post("/api/techstack/999999/targets", headers=h, json={"family_id": proxy})
    ).status_code == 404

    first, second = [t["id"] for t in added.json()["item"]["targets"]]
    removed = await api_client.delete(f"{base}/{first}", headers=h)
    assert removed.status_code == 200 and [t["id"] for t in removed.json()["item"]["targets"]] == [
        second
    ]
    last = await api_client.delete(f"{base}/{second}", headers=h)
    assert last.status_code == 409 and "last target" in last.json()["detail"]
    assert (await api_client.delete(f"{base}/424242", headers=h)).status_code == 404
    listing = (await api_client.get("/api/techstack", headers=h)).json()["items"]
    assert [len(i["targets"]) for i in listing] == [1]


async def test_targets_of_another_clients_entry_are_not_reachable(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    from cti_core.db.repositories.auth import AsyncClientRepo

    await AsyncClientRepo(api_session).create(client_id="globex", name="Globex", countries=[])
    await seed_catalog(api_session)
    fam = await fid(api_session, "fortios")
    other = auth_header(username="g", role="analyst", client_ids=["globex"])
    mine = auth_header()
    entry = (await api_client.post("/api/techstack", headers=mine, json={"family_id": fam})).json()
    entry_id = entry["item"]["id"]
    r = await api_client.post(
        f"/api/techstack/{entry_id}/targets", headers=other, json={"family_id": fam}
    )
    assert r.status_code == 404
    assert (
        await api_client.patch(f"/api/techstack/{entry_id}", headers=other, json={"active": False})
    ).status_code == 404


async def test_toggle_active_and_list_filter(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    a = (await api_client.post("/api/techstack", headers=h, json={"name": "alpha"})).json()["item"]
    await api_client.post("/api/techstack", headers=h, json={"name": "bravo"})
    off = await api_client.patch(f"/api/techstack/{a['id']}", headers=h, json={"active": False})
    assert off.status_code == 200 and off.json()["item"]["active"] is False

    def names(r: Any) -> list[str]:
        return [i["name"] for i in r.json()["items"]]

    assert names(await api_client.get("/api/techstack", headers=h)) == ["alpha", "bravo"]
    assert names(await api_client.get("/api/techstack?active=true", headers=h)) == ["bravo"]
    assert names(await api_client.get("/api/techstack?active=false", headers=h)) == ["alpha"]
    assert (
        await api_client.patch("/api/techstack/999999", headers=h, json={"active": True})
    ).status_code == 404
    assert (
        await api_client.patch(f"/api/techstack/{a['id']}", headers=h, json={})
    ).status_code == 422


async def test_deleting_an_entry_drops_its_targets_but_not_the_catalog(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await seed_catalog(api_session)
    entry = (
        await api_client.post(
            "/api/techstack", headers=h, json={"family_id": await fid(api_session, "fortios")}
        )
    ).json()["item"]
    assert (await api_client.delete(f"/api/techstack/{entry['id']}", headers=h)).json() == {
        "success": True
    }
    fam = (await api_client.get("/api/catalog/families?q=fortios", headers=h)).json()["items"][0]
    assert fam["monitored"] is False and fam["cve_seen_total"] == 3


# ── pemicu promosi ────────────────────────────────────────────────────────────────────────────


async def test_monitor_changes_enqueue_promotion_after_commit(
    api_client: AsyncClient,
    api_session: AsyncSession,
    h: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[int] = []
    monkeypatch.setattr("cti_api.routers.techstack.enqueue_promote_entry", sent.append)
    await seed_catalog(api_session)
    entry = (
        await api_client.post(
            "/api/techstack", headers=h, json={"family_id": await fid(api_session, "fortios")}
        )
    ).json()["item"]
    assert sent == [entry["id"]]
    await api_client.post(
        f"/api/techstack/{entry['id']}/targets",
        headers=h,
        json={"family_id": await fid(api_session, "fortiproxy")},
    )
    await api_client.patch(f"/api/techstack/{entry['id']}", headers=h, json={"active": False})
    assert sent == [entry["id"], entry["id"]]  # nonaktif tidak memicu
    await api_client.patch(f"/api/techstack/{entry['id']}", headers=h, json={"active": True})
    assert sent == [entry["id"]] * 3
    await api_client.post("/api/techstack", headers=h, json={"name": "custom"})
    assert len(sent) == 3  # entri custom tidak memicu promosi
    await api_client.post("/api/techstack", headers=h, json={"family_id": 999999})
    assert len(sent) == 3  # gagal = tidak memicu


# ── scope tab CVEs ────────────────────────────────────────────────────────────────────────────


async def add_tracker(session: AsyncSession, cve_id: str, tech: str) -> None:
    session.add(
        CveTracker(
            cve_id=cve_id,
            client_id="default",
            tech=tech,
            published=D(2026, 3, 1),
            summary="s",
            cve_severity="HIGH",
        )
    )
    await session.flush()


async def cve_ids(client: AsyncClient, h: dict[str, str], path: str = "/api/cve") -> list[str]:
    body = (await client.get(path, headers=h)).json()
    return sorted(c["cve_id"] for c in body["cves"])


async def test_inactive_entry_is_hidden_from_cve_tab_stats_and_tech_list_but_not_deleted(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    a = (await api_client.post("/api/techstack", headers=h, json={"name": "alpha"})).json()["item"]
    await api_client.post("/api/techstack", headers=h, json={"name": "bravo"})
    await add_tracker(api_session, "CVE-2026-0001", "alpha")
    await add_tracker(api_session, "CVE-2026-0002", "bravo")
    assert await cve_ids(api_client, h) == ["CVE-2026-0001", "CVE-2026-0002"]

    await api_client.patch(f"/api/techstack/{a['id']}", headers=h, json={"active": False})
    assert await cve_ids(api_client, h) == ["CVE-2026-0002"]
    stats = (await api_client.get("/api/cve/stats", headers=h)).json()
    assert stats["total"] == 1
    assert (await api_client.get("/api/cve/tech-list", headers=h)).json() == ["bravo"]
    # tidak dihapus: purge-orphaned tidak menganggapnya yatim
    purge = (
        await api_client.post("/api/cve/purge-orphaned", headers=h, json={"dry_run": True})
    ).json()
    assert purge["would_delete"] == 0

    await api_client.patch(f"/api/techstack/{a['id']}", headers=h, json={"active": True})
    assert await cve_ids(api_client, h) == ["CVE-2026-0001", "CVE-2026-0002"]


async def test_all_entries_inactive_shows_nothing_but_no_entries_at_all_stays_unfiltered(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    await add_tracker(api_session, "CVE-2026-0001", "legacy-orphan")
    # belum punya entri sama sekali: perilaku lama (tanpa filter tech)
    assert await cve_ids(api_client, h) == ["CVE-2026-0001"]
    a = (await api_client.post("/api/techstack", headers=h, json={"name": "alpha"})).json()["item"]
    assert await cve_ids(api_client, h) == []  # ada entri aktif, baris yatim tak tampil (lama)
    await add_tracker(api_session, "CVE-2026-0002", "alpha")
    await api_client.patch(f"/api/techstack/{a['id']}", headers=h, json={"active": False})
    # punya entri tapi semuanya nonaktif: kosong, BUKAN tanpa filter
    assert await cve_ids(api_client, h) == []
    assert (await api_client.get("/api/cve/stats", headers=h)).json()["total"] == 0
    assert (await api_client.get("/api/cve/tech-list", headers=h)).json() == []


async def tab_techs(client: AsyncClient, h: dict[str, str]) -> list[str]:
    cves = (await client.get("/api/cve", headers=h)).json()["cves"]
    return sorted({c["tech"] for c in cves})


async def test_tech_list_offers_only_techs_the_tab_can_show(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    """Dropdown filter tech = tech yang bisa muncul di tab CVEs tanpa filter. Menghapus entri
    techstack tidak menghapus baris `cve_tracker`-nya: tab menyembunyikan baris yatim itu, tapi
    dulu dropdown tetap menawarkannya dan memilihnya memunculkan baris yatim tersebut."""
    alpha = (await api_client.post("/api/techstack", headers=h, json={"name": "alpha"})).json()[
        "item"
    ]
    await api_client.post("/api/techstack", headers=h, json={"name": "bravo"})
    await add_tracker(api_session, "CVE-2026-0001", "alpha")
    await add_tracker(api_session, "CVE-2026-0002", "bravo")
    await add_tracker(api_session, "CVE-2026-0003", "never-in-stack")

    tech_list = (await api_client.get("/api/cve/tech-list", headers=h)).json()
    assert tech_list == ["alpha", "bravo"]
    assert tech_list == await tab_techs(api_client, h)

    await api_client.delete(f"/api/techstack/{alpha['id']}", headers=h)
    tech_list = (await api_client.get("/api/cve/tech-list", headers=h)).json()
    assert tech_list == ["bravo"]
    assert tech_list == await tab_techs(api_client, h)


async def test_tech_list_without_any_entry_stays_unfiltered_like_the_tab(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    """Client tanpa entri techstack = tab tanpa filter tech (perilaku lama), jadi dropdown juga
    menawarkan semua tech di tracker, bukan daftar kosong."""
    await add_tracker(api_session, "CVE-2026-0001", "legacy-a")
    await add_tracker(api_session, "CVE-2026-0002", "legacy-b")
    tech_list = (await api_client.get("/api/cve/tech-list", headers=h)).json()
    assert tech_list == ["legacy-a", "legacy-b"]
    assert tech_list == await tab_techs(api_client, h)


async def test_export_follows_the_same_scope_as_the_tab(
    api_client: AsyncClient, api_session: AsyncSession, h: dict[str, str]
) -> None:
    import io

    import openpyxl

    a = (await api_client.post("/api/techstack", headers=h, json={"name": "alpha"})).json()["item"]
    await api_client.post("/api/techstack", headers=h, json={"name": "bravo"})
    await add_tracker(api_session, "CVE-2026-0001", "alpha")
    await add_tracker(api_session, "CVE-2026-0002", "bravo")
    await api_client.patch(f"/api/techstack/{a['id']}", headers=h, json={"active": False})
    resp = await api_client.get("/api/cve/export", headers=h)
    assert resp.status_code == 200
    ws = openpyxl.load_workbook(io.BytesIO(resp.content)).worksheets[0]
    text = " ".join(str(c.value) for row in ws.iter_rows() for c in row if c.value is not None)
    assert "CVE-2026-0002" in text and "CVE-2026-0001" not in text
