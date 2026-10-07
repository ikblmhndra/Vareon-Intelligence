"""Dua tool ops irisan 4 di Postgres beneran: `promote_cve_mirror` (laporan = rollback, apply =
commit, filter entri/client, kunci advisory) dan `compare_promotion_shadow` (kategori, sebab
"hanya tracker", FP disembunyikan, CSV, keluaran kosong)."""

from __future__ import annotations

import csv
import datetime
from collections.abc import Iterator
from pathlib import Path

import pytest
from cti_core.catalog_resolve import AffectedEntry, resolve_all
from cti_core.cve_mirror_sync import LOCK_KEY
from cti_core.cve_promotion import load_entries, promote_record
from cti_core.db.models.auth import Client
from cti_core.db.models.catalog import CatalogFamily
from cti_core.db.models.cve import CveFalsePositive, CveTracker
from cti_core.db.models.cve_mirror import CvePromotionShadow, CveRecord
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from cti_core.db.repositories.catalog import CveMirrorRepo, MirrorRecord
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tools.ops import compare_promotion_shadow as cmp
from tools.ops import promote_cve_mirror as pm

UTC = datetime.UTC
SINCE = datetime.date(2026, 3, 1)


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    for cid in ("acme", "globex"):
        s.add(Client(client_id=cid, name=cid.title()))
    s.flush()
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


def mirror(
    s: Session, cve_id: str, vendor: str = "Fortinet", product: str = "FortiOS", day: int = 5
) -> None:
    published = datetime.date(2026, 3, day)
    CveMirrorRepo(s).upsert(
        MirrorRecord(
            cve_id=cve_id,
            published_date=published,
            published_at=datetime.datetime.combine(published, datetime.time(9), tzinfo=UTC),
            modified_at=datetime.datetime.combine(published, datetime.time(10), tzinfo=UTC),
            summary="bug",
        ),
        resolve_all([AffectedEntry(vendor=vendor, product=product)]),
    )


def entry(
    s: Session, name: str, client: str = "acme", *, family: str | None = None, active: bool = True
) -> TechStackEntry:
    e = TechStackEntry(name=name, client_id=client, active=active)
    s.add(e)
    s.flush()
    if family:
        fid = s.execute(select(CatalogFamily.id).where(CatalogFamily.key == family)).scalar_one()
        s.add(TechStackTarget(entry_id=e.id, family_id=fid))
        s.flush()
    return e


def n(s: Session, model: type) -> int:
    return s.scalar(select(func.count()).select_from(model)) or 0


# ── promote_cve_mirror ────────────────────────────────────────────────────────────────────────


def test_select_entries_filters_by_name_and_client(session: Session) -> None:
    mirror(session, "CVE-2026-0001")
    entry(session, "fortigate", family="fortios")
    entry(session, "Legacy")
    entry(session, "x", "globex")
    entry(session, "hidden", active=False)
    names = lambda es: sorted(e.name for e in es)  # noqa: E731
    assert names(pm.select_entries(session)) == ["Legacy", "fortigate", "x"]
    assert names(pm.select_entries(session, client_id="acme")) == ["Legacy", "fortigate"]
    assert names(pm.select_entries(session, names=["LEGACY", " fortigate "])) == [
        "Legacy",
        "fortigate",
    ]


def test_report_mode_rolls_back_and_apply_commits(session: Session) -> None:
    for i in range(1, 4):
        mirror(session, f"CVE-2026-000{i}")
    entry(session, "fortigate", family="fortios")
    session.commit()  # data uji = baseline; yang di-rollback hanya kerja tool
    entries = pm.select_entries(session)

    summary, _ = pm.run(session, entries, mode="shadow", apply=False)
    assert (summary.scanned, summary.matched, summary.shadow) == (3, 3, 3)
    assert n(session, CvePromotionShadow) == 0

    summary, _ = pm.run(session, entries, mode="shadow", apply=True)
    assert summary.shadow == 3 and n(session, CvePromotionShadow) == 3
    assert n(session, CveTracker) == 0

    live, _ = pm.run(session, entries, mode="live", apply=True)
    assert (live.created, live.updated) == (3, 0) and n(session, CveTracker) == 3
    again, _ = pm.run(session, entries, mode="live", apply=True)
    assert (again.created, again.unchanged) == (0, 3)


def test_entry_filter_only_promotes_the_selected_entry_history(session: Session) -> None:
    mirror(session, "CVE-2026-0001")
    mirror(session, "CVE-2026-0002", "Juniper", "Junos OS")
    entry(session, "fortigate", family="fortios")
    entry(session, "junos", family="junos os")
    session.commit()
    only = pm.select_entries(session, names=["junos"])
    summary, _ = pm.run(session, only, mode="live", apply=True)
    assert summary.created == 1
    assert [t for (t,) in session.execute(select(CveTracker.tech))] == ["junos"]


def test_render_lists_counts_and_entries(session: Session) -> None:
    mirror(session, "CVE-2026-0001")
    entry(session, "fortigate", family="fortios")
    session.commit()
    summary, seconds = pm.run(session, pm.select_entries(session), mode="shadow", apply=False)
    out = pm.render(summary, mode="shadow", apply=False, seconds=seconds)
    assert "SHADOW" in out and "LAPORAN" in out and "fortigate" in out and "family=1" in out
    live, seconds = pm.run(session, pm.select_entries(session), mode="live", apply=False)
    assert "baris tracker baru : 1" in pm.render(live, mode="live", apply=False, seconds=seconds)


def test_promote_tool_refuses_while_the_sync_lock_is_held(session: Session) -> None:
    from cti_core.db.engine import get_sync_engine

    mirror(session, "CVE-2026-0001")
    entry(session, "fortigate", family="fortios")
    session.commit()
    with get_sync_engine().connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_KEY})
        try:
            with pytest.raises(pm.Locked):
                pm.run(session, pm.select_entries(session), mode="live", apply=True)
        finally:
            other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
    assert n(session, CveTracker) == 0


def test_promote_main_exits_4_without_matching_entries() -> None:
    assert pm.main(["--mode", "shadow", "--entry", "tidak-ada"]) == 4


# ── compare_promotion_shadow ──────────────────────────────────────────────────────────────────


def tracker_row(
    s: Session, cve_id: str, tech: str, client: str = "acme", day: int = 5
) -> CveTracker:
    row = CveTracker(
        cve_id=cve_id,
        client_id=client,
        tech=tech,
        published=datetime.date(2026, 3, day),
        summary="bug",
    )
    s.add(row)
    s.flush()
    return row


def test_compare_categorises_every_row_and_explains_tracker_only(session: Session) -> None:
    for cve in ("CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003", "CVE-2026-0004"):
        mirror(session, cve)
    mirror(session, "CVE-2026-0006", "Zabbix", "Zabbix")
    entry(session, "fortigate", family="fortios")  # bertarget
    entry(session, "legacy-text")  # teks
    entry(session, "juniper-gone", active=False)
    entry(session, "zabbix-fam", family="zabbix")  # bertarget, CVE-nya tak cocok
    session.commit()
    all_entries = load_entries(session)
    for cve in ("CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0004"):
        promote_record(session, session.get(CveRecord, cve), all_entries, "shadow")

    tracker_row(session, "CVE-2026-0001", "fortigate")  # sama
    tracker_row(session, "CVE-2026-0002", "other")  # tech beda
    # 0004: hanya bayangan
    tracker_row(session, "CVE-2026-0003", "zabbix-fam")  # hanya tracker: target tak cocok
    tracker_row(session, "CVE-2026-0006", "legacy-text")  # hanya tracker: gate teks tak cocok
    tracker_row(session, "CVE-2026-0007", "fortigate")  # hanya tracker: tak ada di mirror
    tracker_row(session, "CVE-2026-0008", "juniper-gone")  # hanya tracker: entri nonaktif
    mirror(session, "CVE-2026-0008")
    tracker_row(session, "CVE-2026-0009", "fortigate")  # FP: disembunyikan
    session.add(CveFalsePositive(cve_id="CVE-2026-0009", client_id="acme"))
    tracker_row(session, "CVE-2025-0001", "fortigate", day=1).published = datetime.date(2025, 1, 1)
    session.flush()

    c = cmp.compare(session, since=SINCE)
    assert [k[0] for k in c.same] == ["CVE-2026-0001"]
    assert [(k[0], a, b) for k, a, b, _ in c.tech_differs] == [
        ("CVE-2026-0002", "other", "fortigate")
    ]
    assert [(k[0], t, s) for k, t, s in c.only_shadow] == [("CVE-2026-0004", "fortigate", "family")]
    assert {k[0]: r for k, _, r in c.only_tracker} == {
        "CVE-2026-0003": cmp.REASON_TARGET_MISS,
        "CVE-2026-0006": cmp.REASON_TEXT_MISS,
        "CVE-2026-0007": cmp.REASON_NOT_IN_MIRROR,
        "CVE-2026-0008": cmp.REASON_ENTRY_GONE,
    }
    assert c.total == 7  # FP dan CVE terbit sebelum --since tidak dihitung
    with_fp = cmp.compare(session, since=SINCE, include_fp=True)
    assert with_fp.total == 8
    assert cmp.compare(session, since=SINCE, client_id="globex").total == 0


def test_compare_render_and_csv(session: Session, tmp_path: Path) -> None:
    mirror(session, "CVE-2026-0001")
    entry(session, "fortigate", family="fortios")
    session.commit()
    promote_record(
        session, session.get(CveRecord, "CVE-2026-0001"), load_entries(session), "shadow"
    )
    tracker_row(session, "CVE-2026-0002", "fortigate")
    c = cmp.compare(session, since=SINCE)
    text_out = cmp.render(c, since=SINCE)
    assert "hanya bayangan     : 1" in text_out and "hanya tracker      : 1" in text_out
    assert cmp.REASON_NOT_IN_MIRROR in text_out and "CVE-2026-0001" in text_out
    path = tmp_path / "cmp.csv"
    cmp.write_csv(c, path)
    rows = list(csv.DictReader(path.open()))
    assert {r["kategori"] for r in rows} == {"hanya_bayangan", "hanya_tracker"}
    assert {r["cve_id"] for r in rows} == {"CVE-2026-0001", "CVE-2026-0002"}


def test_compare_main_exits_4_when_there_is_nothing_to_compare(_migrated_schema: None) -> None:
    assert cmp.main(["--since", "2026-03-01"]) == 4
