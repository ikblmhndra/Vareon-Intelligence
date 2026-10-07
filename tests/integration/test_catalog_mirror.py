"""Skema katalog + mirror CVE + target Monitor di Postgres beneran (ROADMAP #19, irisan 2).

Yang dikunci: statistik katalog naik SEKALI per CVE (idempoten, tahan urutan, tidak turun saat
retensi), retensi tahun kalender hanya menyentuh mirror (tidak `cve_tracker`, ticket, katalog),
constraint target (vendor XOR keluarga, unik per entri), FK `RESTRICT` ke katalog, dan entri
techstack lama tetap aktif tanpa target. Resolver-nya sendiri dites murni di
`tests/unit/test_catalog_resolve.py`."""

from __future__ import annotations

import datetime

import pytest
from cti_core.catalog_resolve import AffectedEntry, resolve_all
from cti_core.db.models.auth import Client
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.cve_mirror import CveRecord, CveRecordProduct
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from cti_core.db.repositories.catalog import (
    CatalogError,
    CatalogRepo,
    CveMirrorRepo,
    MirrorRecord,
    retention_cutoff,
)
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

D = datetime.date
UTC = datetime.UTC


def rec(cve_id: str, published: datetime.date, **kw: object) -> MirrorRecord:
    kw.setdefault("summary", "s")
    return MirrorRecord(cve_id=cve_id, published_date=published, **kw)  # type: ignore[arg-type]


def ids(*pairs: tuple[str, str]) -> list:
    return resolve_all(AffectedEntry(vendor=v, product=p) for v, p in pairs)


FORTI = ("Fortinet", "FortiOS")
PAN = ("Palo Alto Networks", "PAN-OS")


def vendor(s: Session, key: str) -> CatalogVendor:
    return s.execute(select(CatalogVendor).where(CatalogVendor.key == key)).scalar_one()


def family(s: Session, key: str) -> CatalogFamily:
    return s.execute(select(CatalogFamily).where(CatalogFamily.key == key)).scalar_one()


# ── retensi ───────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("today", "cutoff"),
    [
        (D(2026, 10, 7), D(2025, 1, 1)),
        (D(2026, 12, 31), D(2025, 1, 1)),
        (D(2027, 1, 1), D(2026, 1, 1)),
        (D(2027, 6, 1), D(2026, 1, 1)),
    ],
)
def test_retention_cutoff_is_jan_first_of_previous_year(today: D, cutoff: D) -> None:
    assert retention_cutoff(today) == cutoff


# ── statistik katalog ─────────────────────────────────────────────────────────────────────────


def test_upsert_counts_each_cve_once_per_family_and_vendor(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    # dua produk satu vendor dalam satu CVE: vendor dihitung SEKALI, tiap keluarga sekali
    r = repo.upsert(
        rec("CVE-2026-0001", D(2026, 3, 1)), ids(FORTI, ("Fortinet", "FortiProxy"), PAN)
    )
    assert r.created and r.new_links == 3
    assert vendor(db_session, "fortinet").cve_seen_total == 1
    assert vendor(db_session, "paloaltonetworks").cve_seen_total == 1
    assert family(db_session, "fortios").cve_seen_total == 1
    assert family(db_session, "fortiproxy").cve_seen_total == 1


def test_upsert_is_idempotent(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    record, resolved = rec("CVE-2026-0002", D(2026, 3, 1)), ids(FORTI)
    repo.upsert(record, resolved)
    again = repo.upsert(record, resolved)
    assert not again.created and again.new_links == 0
    assert family(db_session, "fortios").cve_seen_total == 1
    assert vendor(db_session, "fortinet").cve_seen_total == 1
    assert db_session.scalar(select(func.count()).select_from(CveRecordProduct)) == 1


def test_second_cve_for_same_family_increments(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    repo.upsert(rec("CVE-2026-0003", D(2026, 3, 1)), ids(FORTI))
    repo.upsert(rec("CVE-2026-0004", D(2026, 4, 1)), ids(FORTI))
    assert family(db_session, "fortios").cve_seen_total == 2
    assert vendor(db_session, "fortinet").cve_seen_total == 2
    assert vendor(db_session, "fortinet").first_seen == D(2026, 3, 1)
    assert vendor(db_session, "fortinet").last_cve_at == D(2026, 4, 1)


def test_dates_are_order_independent(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    repo.upsert(rec("CVE-2026-0005", D(2026, 5, 1)), ids(FORTI))
    repo.upsert(rec("CVE-2026-0006", D(2026, 2, 1)), ids(FORTI))  # backfill datang belakangan
    v = vendor(db_session, "fortinet")
    assert (v.first_seen, v.last_cve_at) == (D(2026, 2, 1), D(2026, 5, 1))


def test_update_adds_and_drops_families_without_double_counting(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    t1 = datetime.datetime(2026, 3, 1, tzinfo=UTC)
    repo.upsert(rec("CVE-2026-0007", D(2026, 3, 1), modified_at=t1), ids(FORTI))
    t2 = t1 + datetime.timedelta(days=1)
    result = repo.upsert(
        rec("CVE-2026-0007", D(2026, 3, 1), modified_at=t2), ids(("Fortinet", "FortiProxy"))
    )
    assert result.new_links == 1
    row = repo.get("CVE-2026-0007")
    assert row is not None
    assert sorted(p.product_norm for p in row.products) == ["fortiproxy"]
    # keluarga yang dilepas TIDAK turun (statistik hanya naik); vendor tidak dihitung dua kali
    assert family(db_session, "fortios").cve_seen_total == 1
    assert family(db_session, "fortiproxy").cve_seen_total == 1
    assert vendor(db_session, "fortinet").cve_seen_total == 1


def test_stale_record_is_rejected(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    new = datetime.datetime(2026, 3, 2, tzinfo=UTC)
    old = datetime.datetime(2026, 3, 1, tzinfo=UTC)
    repo.upsert(rec("CVE-2026-0008", D(2026, 3, 1), modified_at=new, summary="baru"), ids(FORTI))
    result = repo.upsert(
        rec("CVE-2026-0008", D(2026, 3, 1), modified_at=old, summary="lama"), ids(PAN)
    )
    assert result.skipped_stale and result.new_links == 0
    row = repo.get("CVE-2026-0008")
    assert row is not None and row.summary == "baru"
    assert [p.product_norm for p in row.products] == ["fortios"]


def test_cve_without_identity_is_kept_and_flagged(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    result = repo.upsert(rec("CVE-2026-0009", D(2026, 3, 1)), ids(("n/a", "n/a")))
    row = repo.get("CVE-2026-0009")
    assert row is not None and row.has_identity is False and result.family_ids == ()


def test_vendorless_product_goes_to_none_vendor_not_monitorable(db_session: Session) -> None:
    CveMirrorRepo(db_session).upsert(rec("CVE-2026-0010", D(2026, 3, 1)), ids(("", "Some Widget")))
    v = vendor(db_session, "~none")
    assert v.monitorable is False
    assert vendor(db_session, "~none").display_name == "(tanpa vendor)"


def test_cna_display_name_replaces_cpe_spelling(db_session: Session) -> None:
    repo = CveMirrorRepo(db_session)
    cpe = AffectedEntry(
        vendor="x", product="y", cpes=("cpe:2.3:a:palo_alto_networks:pan-os:*:*:*:*:*:*:*:*",)
    )
    repo.upsert(rec("CVE-2026-0011", D(2026, 3, 1)), resolve_all([cpe]))
    assert vendor(db_session, "paloaltonetworks").display_source == "cpe"
    repo.upsert(rec("CVE-2026-0012", D(2026, 3, 2)), ids(PAN))
    v = vendor(db_session, "paloaltonetworks")
    assert (v.display_name, v.display_source) == ("Palo Alto Networks", "cna")


def test_overlong_names_are_truncated_not_rejected(db_session: Session) -> None:
    long_product = "p" * 900
    CveMirrorRepo(db_session).upsert(
        rec("CVE-2026-0013", D(2026, 3, 1)), ids(("Acme", long_product))
    )
    fam = db_session.execute(
        select(CatalogFamily).join(CatalogVendor).where(CatalogVendor.key == "acme")
    ).scalar_one()
    assert len(fam.key) == 400 and len(fam.display_name) == 500


# ── retensi tidak menyentuh yang lain ─────────────────────────────────────────────────────────


def test_purge_only_touches_mirror(db_session: Session) -> None:
    db_session.add(Client(client_id="acme", name="Acme"))
    db_session.flush()
    db_session.add(
        CveTracker(
            cve_id="CVE-2025-1111",
            client_id="acme",
            tech="fortios",
            published=D(2025, 2, 1),
            summary="s",
        )
    )
    repo = CveMirrorRepo(db_session)
    repo.upsert(rec("CVE-2025-1111", D(2025, 2, 1)), ids(FORTI))
    repo.upsert(rec("CVE-2026-1111", D(2026, 2, 1)), ids(FORTI))
    db_session.flush()

    assert repo.purge_expired(D(2026, 12, 31)) == 0  # 2025 masih disimpan di 2026
    assert repo.purge_expired(D(2027, 1, 1)) == 1  # 2027-01-01: terbitan 2025 dibuang

    assert repo.get("CVE-2025-1111") is None
    assert repo.get("CVE-2026-1111") is not None
    # anak ikut terhapus lewat cascade, tapi katalog + statistik + tracker utuh
    assert db_session.scalar(select(func.count()).select_from(CveRecordProduct)) == 1
    assert family(db_session, "fortios").cve_seen_total == 2
    assert vendor(db_session, "fortinet").cve_seen_total == 2
    assert db_session.scalar(select(func.count()).select_from(CveTracker)) == 1


# ── alias ─────────────────────────────────────────────────────────────────────────────────────


def test_alias_map_and_validation(db_session: Session) -> None:
    mirror = CveMirrorRepo(db_session)
    mirror.upsert(rec("CVE-2026-0020", D(2026, 3, 1)), ids(("Acme", "Widget Pro")))
    cat = mirror.catalog
    fam = family(db_session, "widget pro")
    cat.add_alias("acme|widgetpro2", fam, created_by="admin")
    assert cat.alias_map() == {"acme|widgetpro2": "widget pro"}
    assert cat.add_alias("acme|widgetpro2", fam).alias_key == "acme|widgetpro2"  # idempoten
    with pytest.raises(CatalogError):
        cat.add_alias("globex|widgetpro", fam)  # menyeberang vendor
    other = CatalogRepo(db_session)
    mirror.upsert(rec("CVE-2026-0021", D(2026, 3, 1)), ids(("Acme", "Gadget")))
    with pytest.raises(CatalogError):
        other.add_alias("acme|widgetpro2", family(db_session, "gadget"))  # sudah ke keluarga lain

    # alias dipakai resolver: produk dengan kunci itu masuk keluarga yang ditunjuk
    resolved = resolve_all(
        [AffectedEntry(vendor="Acme", product="Widget Pro 2")], aliases=cat.alias_map()
    )
    assert [r.family_key for r in resolved] == ["widget pro"]


# ── target Monitor ────────────────────────────────────────────────────────────────────────────


def _entry(s: Session, name: str = "junos") -> TechStackEntry:
    s.add(Client(client_id="acme", name="Acme"))
    s.flush()
    e = TechStackEntry(name=name, client_id="acme")
    s.add(e)
    s.flush()
    return e


def test_legacy_entry_is_active_without_targets(db_session: Session) -> None:
    e = _entry(db_session)
    db_session.refresh(e)
    assert e.active is True
    assert db_session.scalar(select(func.count()).select_from(TechStackTarget)) == 0


def test_target_requires_exactly_one_of_vendor_or_family(db_session: Session) -> None:
    CveMirrorRepo(db_session).upsert(rec("CVE-2026-0030", D(2026, 3, 1)), ids(FORTI))
    e = _entry(db_session)
    v, f = vendor(db_session, "fortinet"), family(db_session, "fortios")
    for kwargs in ({}, {"vendor_id": v.id, "family_id": f.id}):
        with pytest.raises(IntegrityError), db_session.begin_nested():
            db_session.add(TechStackTarget(entry_id=e.id, **kwargs))
            db_session.flush()
    db_session.add(TechStackTarget(entry_id=e.id, family_id=f.id))
    db_session.flush()


def test_target_is_unique_per_entry_but_entry_may_have_many(db_session: Session) -> None:
    CveMirrorRepo(db_session).upsert(
        rec("CVE-2026-0031", D(2026, 3, 1)), ids(FORTI, ("Fortinet", "FortiProxy"))
    )
    e = _entry(db_session)
    f1, f2 = family(db_session, "fortios"), family(db_session, "fortiproxy")
    db_session.add_all(
        [
            TechStackTarget(entry_id=e.id, family_id=f1.id),
            TechStackTarget(entry_id=e.id, family_id=f2.id),
        ]
    )
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(TechStackTarget(entry_id=e.id, family_id=f1.id))
        db_session.flush()


def test_catalog_rows_referenced_by_targets_or_mirror_cannot_be_deleted(
    db_session: Session,
) -> None:
    CveMirrorRepo(db_session).upsert(rec("CVE-2026-0032", D(2026, 3, 1)), ids(FORTI))
    e = _entry(db_session)
    f = family(db_session, "fortios")
    db_session.add(TechStackTarget(entry_id=e.id, family_id=f.id))
    db_session.flush()
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text("DELETE FROM catalog_families WHERE id = :i"), {"i": f.id})
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text("DELETE FROM catalog_vendors WHERE id = :i"), {"i": f.vendor_id})


def test_deleting_entry_cascades_its_targets_only(db_session: Session) -> None:
    CveMirrorRepo(db_session).upsert(rec("CVE-2026-0033", D(2026, 3, 1)), ids(FORTI))
    e = _entry(db_session)
    f = family(db_session, "fortios")
    db_session.add(TechStackTarget(entry_id=e.id, family_id=f.id))
    db_session.flush()
    db_session.execute(text("DELETE FROM techstack_entries WHERE id = :i"), {"i": e.id})
    assert db_session.scalar(select(func.count()).select_from(TechStackTarget)) == 0
    assert db_session.scalar(select(func.count()).select_from(CatalogFamily)) == 1
    assert db_session.get(CveRecord, "CVE-2026-0033") is not None
