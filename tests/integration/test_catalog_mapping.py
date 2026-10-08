"""`tools/ops/catalog_mapping.py` di Postgres beneran: pemetaan dipindah lewat kunci katalog (bukan
ID), laporan = rollback, idempoten, masalah dilaporkan (bukan dibuat), dan `suggest` memberi
kandidat."""

from __future__ import annotations

import datetime
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from cti_core.catalog_resolve import AffectedEntry, resolve_all
from cti_core.db.models.auth import Client
from cti_core.db.models.catalog import CatalogFamily
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from cti_core.db.repositories.catalog import CveMirrorRepo, MirrorRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.ops import catalog_mapping as cm

UTC = datetime.UTC


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


def seed_catalog(s: Session) -> None:
    specs = [
        ("CVE-2026-0001", [("Fortinet", "FortiOS")]),
        ("CVE-2026-0002", [("Fortinet", "FortiOS"), ("Fortinet", "FortiProxy")]),
        ("CVE-2026-0003", [("Juniper Networks", "Junos OS"), ("Juniper Networks", "Junos Space")]),
        ("CVE-2026-0004", [("Grafana", "Grafana OSS")]),
        ("CVE-2026-0005", [("", "Orphan Tool")]),
    ]
    for i, (cve, pairs) in enumerate(specs):
        day = datetime.date(2026, 3, 1 + i)
        CveMirrorRepo(s).upsert(
            MirrorRecord(cve_id=cve, published_date=day, summary="s"),
            resolve_all(AffectedEntry(vendor=v, product=p) for v, p in pairs),
        )


def entry(s: Session, name: str, client: str = "acme", *, active: bool = True) -> TechStackEntry:
    e = TechStackEntry(name=name, client_id=client, active=active, targets=[])
    s.add(e)
    s.flush()
    return e


def target(
    s: Session, e: TechStackEntry, *, family: str | None = None, vendor_key: str | None = None
):
    if family:
        fid = s.execute(select(CatalogFamily.id).where(CatalogFamily.key == family)).scalar_one()
        s.add(TechStackTarget(entry_id=e.id, family_id=fid))
    else:
        from cti_core.db.models.catalog import CatalogVendor

        vid = s.execute(
            select(CatalogVendor.id).where(CatalogVendor.key == vendor_key)
        ).scalar_one()
        s.add(TechStackTarget(entry_id=e.id, vendor_id=vid))
    s.flush()
    s.refresh(e, ["targets"])


def n_targets(s: Session) -> int:
    return s.scalar(select(func.count()).select_from(TechStackTarget)) or 0


def test_export_uses_stable_keys_not_ids(session: Session) -> None:
    seed_catalog(session)
    fg, junos, legacy = (
        entry(session, "fortigate"),
        entry(session, "junos"),
        entry(session, "nginx"),
    )
    target(session, fg, family="fortios")
    target(session, junos, family="junos os")
    target(session, junos, family="junos space")
    target(session, entry(session, "grafana"), vendor_key="grafana")
    data = cm.export_mapping(session)
    by_name = {e["name"]: e for e in data["entries"]}
    assert data["version"] == 1 and legacy.name in by_name
    assert by_name["fortigate"]["targets"] == [
        {"kind": "family", "vendor": "fortinet", "family": "fortios"}
    ]
    assert [t["family"] for t in by_name["junos"]["targets"]] == ["junos os", "junos space"]
    assert by_name["grafana"]["targets"] == [{"kind": "vendor", "vendor": "grafana"}]
    assert by_name["nginx"]["targets"] == []
    assert json.loads(json.dumps(data)) == data  # JSON-murni


def test_roundtrip_into_a_fresh_mapping_is_idempotent_and_report_mode_writes_nothing(
    session: Session,
) -> None:
    seed_catalog(session)
    fg, junos = entry(session, "fortigate"), entry(session, "junos")
    target(session, fg, family="fortios")
    target(session, junos, family="junos os")
    target(session, junos, family="junos space")
    data = cm.export_mapping(session)

    session.query(TechStackTarget).delete()  # "prod": entri sama, belum dipetakan
    session.flush()
    session.expire_all()
    assert n_targets(session) == 0
    session.commit()

    report = cm.import_mapping(session, data)
    assert (report.added, report.already, report.problems) == (3, 0, [])
    session.rollback()  # mode laporan
    assert n_targets(session) == 0

    cm.import_mapping(session, data)
    session.commit()
    assert n_targets(session) == 3
    again = cm.import_mapping(session, data)
    assert (again.added, again.already) == (0, 3) and n_targets(session) == 3


def test_import_reports_missing_entries_and_catalog_keys_without_creating_them(
    session: Session,
) -> None:
    seed_catalog(session)
    entry(session, "fortigate")
    data = {
        "version": 1,
        "entries": [
            {
                "client_id": "acme",
                "name": "FortiGate",
                "targets": [  # nama tak peka huruf besar/kecil
                    {"kind": "family", "vendor": "fortinet", "family": "fortios"},
                    {"kind": "family", "vendor": "fortinet", "family": "tidak-ada"},
                    {"kind": "family", "vendor": "vendor-hantu", "family": "x"},
                    {"kind": "vendor", "vendor": "~none"},
                    {"kind": "aneh", "vendor": "fortinet"},
                ],
            },
            {"client_id": "acme", "name": "tidak-ada-entri", "targets": []},
            {"client_id": "globex", "name": "fortigate", "targets": []},  # client lain: tak ketemu
        ],
    }
    report = cm.import_mapping(session, data)
    assert report.added == 1 and len(report.problems) == 6
    joined = "\n".join(report.problems)
    for needle in (
        "tidak-ada",
        "vendor-hantu",
        "tidak bisa di-Monitor",
        "jenis target",
        "tidak ada di DB",
    ):
        assert needle in joined
    assert session.execute(select(func.count()).select_from(TechStackEntry)).scalar_one() == 1


def test_create_missing_and_with_active(session: Session) -> None:
    seed_catalog(session)
    keep = entry(session, "grafana", active=True)
    data = {
        "version": 1,
        "entries": [
            {
                "client_id": "acme",
                "name": "grafana",
                "active": False,
                "targets": [{"kind": "vendor", "vendor": "grafana"}],
            },
            {
                "client_id": "acme",
                "name": "baru",
                "active": True,
                "targets": [{"kind": "family", "vendor": "fortinet", "family": "fortios"}],
            },
        ],
    }
    cm.import_mapping(session, data)
    session.refresh(keep)
    assert keep.active is True  # default: status aktif TIDAK disalin
    report = cm.import_mapping(session, data, create_missing=True, with_active=True)
    session.refresh(keep)
    assert keep.active is False and report.activity_changed == 1 and report.created_entries == 1
    created = session.execute(
        select(TechStackEntry).where(TechStackEntry.name == "baru")
    ).scalar_one()
    assert created.source == "catalog" and len(created.targets) == 1


def test_import_rejects_an_unknown_format_version(session: Session) -> None:
    with pytest.raises(ValueError, match="versi"):
        cm.import_mapping(session, {"version": 99, "entries": []})


def test_suggest_finds_candidates_and_tolerates_label_mismatch(session: Session) -> None:
    seed_catalog(session)
    assert [c.label for c in cm.suggest_for(session, "grafana")][:1] == ["Grafana"]
    assert cm.suggest_for(session, "grafana")[0].exact
    junos = cm.suggest_for(session, "junos")
    assert {c.label for c in junos} >= {
        "Juniper Networks > Junos OS",
        "Juniper Networks > Junos Space",
    }
    assert cm.suggest_for(session, "fortigate") == []  # label != nama CNA (FortiOS)
    assert cm.suggest_for(session, "x") == [] and cm.suggest_for(session, "%") == []
    entry(session, "junos")
    mapped = entry(session, "fortinet")
    target(session, mapped, vendor_key="fortinet")
    text = cm.render_suggestions(session, client_id=None, top=3)
    assert "acme/junos" in text and "acme/fortinet" not in text  # yang sudah dipetakan dilewati
    assert "1 entri belum dipetakan" in text


def test_cli_export_import_suggest_and_errors(session: Session, tmp_path: Path) -> None:
    assert cm.main(["import", "--file", str(tmp_path / "nope.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{ bukan json")
    assert cm.main(["import", "--file", str(bad)]) == 2
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps({"version": 7, "entries": []}))
    assert cm.main(["import", "--file", str(wrong)]) == 2
