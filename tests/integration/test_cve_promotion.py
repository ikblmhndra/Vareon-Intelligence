"""Promosi mirror -> `cve_tracker`/bayangan di Postgres beneran (ROADMAP #19, irisan 4).

Yang dikunci: mode `off`/`shadow`/`live`, tidak menyentuh enrichment/ticket/`detected_on`, tidak
pernah menghapus baris tracker, tech mengikuti entri paling spesifik, jalur sync end-to-end
(termasuk ringkasan Telegram lewat `finish_run`), retensi membuang bayangan, REJECTED,
`promote_all`, dan entri nonaktif tidak ikut dicari. Aturan `choose` dites murni di
`tests/unit/test_cve_promotion.py`.
"""

from __future__ import annotations

import datetime
import itertools
import json
from collections.abc import Iterator
from typing import Any

import pytest
from cti_core.catalog_resolve import AffectedEntry, resolve_all
from cti_core.cve_mirror_sync import DELTA_URL, FetchError, sync_once
from cti_core.cve_promotion import (
    NEW_CVE_ROWS_KEY,
    forget_shadow,
    load_entries,
    promote_all,
    promote_record,
)
from cti_core.db.models.auth import Client
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.cve import CveFalsePositive, CveTicket, CveTracker
from cti_core.db.models.cve_mirror import CvePromotionShadow, CveRecord
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from cti_core.db.repositories.catalog import CveMirrorRepo, MirrorRecord
from sqlalchemy import func, select
from sqlalchemy.orm import Session

D = datetime.date
UTC = datetime.UTC
NOW = datetime.datetime.now(UTC)
TODAY = NOW.date()
FORTI = ("Fortinet", "FortiOS")
DEFAULT_PUBLISHED = D(2026, 3, 1)
BASE = "https://raw.githubusercontent.com/CVEProject/cvelistV5/main/cves/2026/"


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


def add_record(
    s: Session,
    cve_id: str,
    *pairs: tuple[str, str],
    published: datetime.date = DEFAULT_PUBLISHED,
    modified: datetime.datetime | None = None,
    summary: str = "bug",
    **kw: Any,
) -> CveRecord:
    resolved = resolve_all(AffectedEntry(vendor=v, product=p) for v, p in pairs)
    rec = MirrorRecord(
        cve_id=cve_id,
        published_date=published,
        published_at=datetime.datetime.combine(published, datetime.time(10), tzinfo=UTC),
        modified_at=modified or datetime.datetime.combine(published, datetime.time(11), tzinfo=UTC),
        summary=summary,
        link=f"https://nvd.nist.gov/vuln/detail/{cve_id}",
        reference_urls=["https://example.org/a"],
        affected_lines=["FortiOS: < 7.0"],
        **kw,
    )
    CveMirrorRepo(s).upsert(rec, resolved)
    row = s.get(CveRecord, cve_id)
    assert row is not None
    return row


def add_entry(
    s: Session,
    name: str,
    client: str = "acme",
    *,
    vendors: tuple[str, ...] = (),
    families: tuple[str, ...] = (),
    active: bool = True,
) -> TechStackEntry:
    e = TechStackEntry(name=name, client_id=client, active=active)
    s.add(e)
    s.flush()
    for key in vendors:
        s.add(
            TechStackTarget(
                entry_id=e.id,
                vendor_id=s.execute(
                    select(CatalogVendor.id).where(CatalogVendor.key == key)
                ).scalar_one(),
            )
        )
    for key in families:
        s.add(
            TechStackTarget(
                entry_id=e.id,
                family_id=s.execute(
                    select(CatalogFamily.id).where(CatalogFamily.key == key)
                ).scalar_one(),
            )
        )
    s.flush()
    return e


def tracker(s: Session, cve_id: str = "CVE-2026-0001", client: str = "acme") -> CveTracker | None:
    return s.execute(
        select(CveTracker).where(CveTracker.cve_id == cve_id, CveTracker.client_id == client)
    ).scalar_one_or_none()


def shadow_rows(s: Session) -> list[tuple[str, str, str, str]]:
    return [
        tuple(r)
        for r in s.execute(
            select(
                CvePromotionShadow.cve_id,
                CvePromotionShadow.client_id,
                CvePromotionShadow.tech,
                CvePromotionShadow.specificity,
            ).order_by(CvePromotionShadow.cve_id, CvePromotionShadow.client_id)
        ).all()
    ]


def count(s: Session, model: Any) -> int:
    return s.scalar(select(func.count()).select_from(model)) or 0


# ── entri ─────────────────────────────────────────────────────────────────────────────────────


def test_load_entries_returns_only_active_entries_with_their_targets(session: Session) -> None:
    add_record(session, "CVE-2026-0001", FORTI, ("Fortinet", "FortiProxy"))
    add_entry(session, "forti", vendors=("fortinet",))
    add_entry(session, "fortigate", families=("fortios", "fortiproxy"))
    add_entry(session, "legacy")
    add_entry(session, "hidden", active=False)
    add_entry(session, "other-client", "globex", families=("fortios",))
    by_name = {e.name: e for e in load_entries(session)}
    assert set(by_name) == {"forti", "fortigate", "legacy", "other-client"}
    assert len(by_name["fortigate"].family_ids) == 2 and not by_name["legacy"].has_targets
    assert {e.name for e in load_entries(session, client_id="globex")} == {"other-client"}
    only = load_entries(session, entry_ids=[by_name["legacy"].entry_id])
    assert [e.name for e in only] == ["legacy"]


# ── live ──────────────────────────────────────────────────────────────────────────────────────


def test_live_creates_a_tracker_row_shaped_like_new_cve(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", families=("fortios",))
    out = promote_record(session, rec, load_entries(session), "live")
    assert (out.created, out.updated, out.shadow) == (1, 0, 0)
    row = tracker(session)
    assert row is not None
    assert row.tech == "fortigate"
    assert row.link == "https://nvd.nist.gov/vuln/detail/CVE-2026-0001"
    assert row.summary == "bug" and row.published == D(2026, 3, 1)
    assert row.published_at == rec.published_at and row.cve_modified_date == D(2026, 3, 1)
    assert (row.cve_score, row.cvss_vector) == (0.0, "")  # default parser lama dipertahankan
    assert [r.url for r in row.references] == ["https://example.org/a"]
    assert [a.affected for a in row.affected] == ["FortiOS: < 7.0"]
    assert row.detected_on is not None
    assert session.info[NEW_CVE_ROWS_KEY] == [("CVE-2026-0001", "acme")]
    assert count(session, CvePromotionShadow) == 0


def test_live_is_idempotent_and_reports_new_rows_only_once(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", families=("fortios",))
    entries = load_entries(session)
    promote_record(session, rec, entries, "live")
    detected = tracker(session).detected_on  # type: ignore[union-attr]
    again = promote_record(session, rec, entries, "live")
    assert (again.created, again.updated, again.unchanged) == (0, 0, 1)
    assert session.info[NEW_CVE_ROWS_KEY] == [("CVE-2026-0001", "acme")]
    assert tracker(session).detected_on == detected  # type: ignore[union-attr]


def test_live_update_keeps_enrichment_ticket_fp_and_detected_on(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", families=("fortios",))
    entries = load_entries(session)
    promote_record(session, rec, entries, "live")
    row = tracker(session)
    assert row is not None
    row.cisa_kev, row.epss_score, row.poc_available = True, 0.9, True
    session.add(CveTicket(cve_id="CVE-2026-0001", client_id="acme", ticket_id="T-1"))
    session.add(CveFalsePositive(cve_id="CVE-2026-0001", client_id="acme"))
    session.flush()
    detected = row.detected_on

    newer = add_record(
        session,
        "CVE-2026-0001",
        FORTI,
        summary="diperbarui",
        modified=datetime.datetime(2026, 3, 9, 12, tzinfo=UTC),
    )
    out = promote_record(session, newer, entries, "live")
    assert out.updated == 1
    session.refresh(row)
    assert row.summary == "diperbarui" and row.cve_modified_date == D(2026, 3, 9)
    assert (row.cisa_kev, row.epss_score, row.poc_available) == (True, 0.9, True)
    assert row.detected_on == detected
    assert count(session, CveTicket) == 1 and count(session, CveFalsePositive) == 1


def test_live_tech_follows_the_most_specific_entry_on_an_existing_row(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    vendor = add_entry(session, "fortinet", vendors=("fortinet",))
    promote_record(session, rec, load_entries(session), "live")
    assert tracker(session).tech == "fortinet"  # type: ignore[union-attr]
    add_entry(session, "fortigate", families=("fortios",))
    out = promote_record(session, rec, load_entries(session), "live")
    assert out.updated == 1 and tracker(session).tech == "fortigate"  # type: ignore[union-attr]
    assert vendor.id is not None


def test_live_never_deletes_a_tracker_row_that_stops_matching(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    entry = add_entry(session, "fortigate", families=("fortios",))
    promote_record(session, rec, load_entries(session), "live")
    entry.active = False
    session.flush()
    out = promote_record(session, rec, load_entries(session), "live")
    assert out.matched_clients == 0
    assert tracker(session) is not None


def test_live_writes_one_row_per_client(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", "acme", families=("fortios",))
    add_entry(session, "fortinet", "globex", vendors=("fortinet",))
    out = promote_record(session, rec, load_entries(session), "live")
    assert out.created == 2
    assert tracker(session, client="acme").tech == "fortigate"  # type: ignore[union-attr]
    assert tracker(session, client="globex").tech == "fortinet"  # type: ignore[union-attr]


# ── off dan shadow ────────────────────────────────────────────────────────────────────────────


def test_off_does_nothing(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", families=("fortios",))
    out = promote_record(session, rec, load_entries(session), "off")
    assert out.choices == {} and count(session, CveTracker) == 0
    assert count(session, CvePromotionShadow) == 0


def test_shadow_records_the_decision_without_touching_the_tracker(session: Session) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", families=("fortios",))
    add_entry(session, "legacy-text-fortios")  # tanpa target, teks tak cocok
    out = promote_record(session, rec, load_entries(session), "shadow")
    assert (out.shadow, out.created) == (1, 0)
    assert shadow_rows(session) == [("CVE-2026-0001", "acme", "fortigate", "family")]
    assert count(session, CveTracker) == 0 and NEW_CVE_ROWS_KEY not in session.info


def test_shadow_mirrors_the_current_evaluation_and_drops_clients_that_stop_matching(
    session: Session,
) -> None:
    rec = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", "acme", families=("fortios",))
    other = add_entry(session, "fortinet", "globex", vendors=("fortinet",))
    promote_record(session, rec, load_entries(session), "shadow")
    assert [r[1] for r in shadow_rows(session)] == ["acme", "globex"]
    other.active = False
    session.flush()
    promote_record(session, rec, load_entries(session), "shadow")
    assert [r[1] for r in shadow_rows(session)] == ["acme"]
    session.get(TechStackEntry, load_entries(session)[0].entry_id).active = False  # type: ignore[union-attr]
    session.flush()
    promote_record(session, rec, load_entries(session), "shadow")
    assert shadow_rows(session) == []


def test_forget_shadow_and_retention_remove_only_the_mirror_side(session: Session) -> None:
    old = add_record(session, "CVE-2025-0001", FORTI, published=D(2025, 5, 1))
    new = add_record(session, "CVE-2026-0001", FORTI)
    add_entry(session, "fortigate", families=("fortios",))
    entries = load_entries(session)
    for rec in (old, new):
        promote_record(session, rec, entries, "shadow")
    promote_record(session, old, entries, "live")
    assert count(session, CvePromotionShadow) == 2
    CveMirrorRepo(session).purge_expired(D(2027, 1, 1))
    assert [r[0] for r in shadow_rows(session)] == ["CVE-2026-0001"]
    assert tracker(session, "CVE-2025-0001") is not None  # tracker tak tersentuh retensi
    forget_shadow(session, "CVE-2026-0001")
    assert shadow_rows(session) == []


# ── promote_all ───────────────────────────────────────────────────────────────────────────────


def test_promote_all_covers_the_whole_mirror_and_can_be_limited_to_entries(
    session: Session,
) -> None:
    for i in range(1, 6):
        add_record(session, f"CVE-2026-000{i}", FORTI if i % 2 else ("Juniper", "Junos OS"))
    forti = add_entry(session, "fortigate", families=("fortios",))
    add_entry(session, "junos", families=("junos os",))
    all_entries = load_entries(session)
    seen: list[int] = []
    done = promote_all(
        session,
        all_entries,
        "shadow",
        batch_size=2,
        progress=lambda s: seen.append(s.scanned),
        progress_every=2,
    )
    assert (done.scanned, done.matched, done.shadow) == (5, 5, 5)
    assert done.per_entry == {"fortigate": 3, "junos": 2}
    assert done.per_specificity == {"family": 5} and seen == [2, 4]

    only = promote_all(session, load_entries(session, entry_ids=[forti.id]), "live", batch_size=2)
    assert (only.created, only.matched) == (3, 3)
    assert count(session, CveTracker) == 3
    assert promote_all(session, all_entries, "off").scanned == 0
    assert promote_all(session, [], "live").scanned == 0
    assert promote_all(session, all_entries, "shadow", limit=2).scanned == 2


# ── jalur sync end-to-end ─────────────────────────────────────────────────────────────────────


_TICKS = itertools.count(0, 5)
"""Tiap `Net` baru = jendela fetch yang lebih baru (kalau tidak, sync kedua dianggap noop)."""


class Net:
    def __init__(self, *cves: tuple[str, dict[str, Any]]) -> None:
        self.files: dict[str, Any] = {}
        self.calls = 0
        new = []
        for cve_id, rec in cves:
            link = f"{BASE}{cve_id}.json"
            self.files[link] = rec
            new.append({"cveId": cve_id, "githubLink": link, "dateUpdated": "2026-10-07T10:57:00Z"})
        self.files[DELTA_URL] = {
            "fetchTime": (NOW + datetime.timedelta(minutes=next(_TICKS))).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            ),
            "numberOfChanges": len(new),
            "new": new,
            "updated": [],
            "error": [],
        }

    def __call__(self, url: str) -> bytes:
        self.calls += 1
        if url not in self.files:
            raise FetchError(url)
        return json.dumps(self.files[url]).encode()


def cve_json(cve_id: str, *, published: datetime.date = TODAY, state: str = "PUBLISHED") -> dict:
    return {
        "cveMetadata": {
            "cveId": cve_id,
            "state": state,
            "datePublished": f"{published.isoformat()}T08:00:00.000Z",
            "dateUpdated": f"{published.isoformat()}T09:00:00.000Z",
        },
        "containers": {
            "cna": {
                "descriptions": [{"lang": "en", "value": "FortiOS overflow"}],
                "affected": [{"vendor": "Fortinet", "product": "FortiOS"}],
            }
        },
    }


def test_sync_live_promotes_new_records_and_sends_one_telegram_summary(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cti_scraper.sinks import finish_run

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr("cti_alerts.telegram.send_alert", lambda t, m: sent.append((t, m)))
    # entri harus ada SEBELUM sync (katalog dibuat sync): dua tahap, seperti pemakaian nyata
    sync_once(session, Net(("CVE-2026-0100", cve_json("CVE-2026-0100"))), NOW)
    add_entry(session, "fortigate", families=("fortios",))
    net = Net(
        ("CVE-2026-0101", cve_json("CVE-2026-0101")), ("CVE-2026-0102", cve_json("CVE-2026-0102"))
    )
    report = sync_once(session, net, NOW + datetime.timedelta(minutes=5), promote="live")
    assert (report.created, report.promoted_new, report.failed) == (2, 2, 0)
    assert tracker(session, "CVE-2026-0101").tech == "fortigate"  # type: ignore[union-attr]
    assert (
        tracker(session, "CVE-2026-0100") is None
    )  # masuk sebelum entri ada: riwayat = promote_all

    session.commit()
    finish_run(session)
    assert len(sent) == 1 and sent[0][0] == "cve_new"
    assert "CVE-2026-0101" in sent[0][1] and "CVE-2026-0102" in sent[0][1]


def test_sync_shadow_writes_only_the_shadow_and_off_writes_neither(session: Session) -> None:
    sync_once(session, Net(("CVE-2026-0100", cve_json("CVE-2026-0100"))), NOW)
    add_entry(session, "fortigate", families=("fortios",))
    r = sync_once(
        session,
        Net(("CVE-2026-0101", cve_json("CVE-2026-0101"))),
        NOW + datetime.timedelta(minutes=5),
        promote="shadow",
    )
    assert (r.shadow_rows, r.promoted_new) == (1, 0)
    assert shadow_rows(session) == [("CVE-2026-0101", "acme", "fortigate", "family")]
    assert count(session, CveTracker) == 0
    r = sync_once(
        session,
        Net(("CVE-2026-0102", cve_json("CVE-2026-0102"))),
        NOW + datetime.timedelta(minutes=10),
    )
    assert (r.shadow_rows, r.promoted_new) == (0, 0) and len(shadow_rows(session)) == 1


def test_sync_rejected_record_forgets_the_shadow_but_keeps_the_tracker_row(
    session: Session,
) -> None:
    sync_once(session, Net(("CVE-2026-0100", cve_json("CVE-2026-0100"))), NOW)
    add_entry(session, "fortigate", families=("fortios",))
    sync_once(session, Net(("CVE-2026-0101", cve_json("CVE-2026-0101"))), at(5), promote="shadow")
    sync_once(session, Net(("CVE-2026-0102", cve_json("CVE-2026-0102"))), at(10), promote="live")
    assert tracker(session, "CVE-2026-0102") is not None
    rejected = Net(
        ("CVE-2026-0101", cve_json("CVE-2026-0101", state="REJECTED")),
        ("CVE-2026-0102", cve_json("CVE-2026-0102", state="REJECTED")),
    )
    report = sync_once(session, rejected, at(15), promote="shadow")
    assert report.removed == 2
    assert shadow_rows(session) == []
    assert tracker(session, "CVE-2026-0102") is not None  # ticket/ACK tak boleh yatim


def at(minutes: int) -> datetime.datetime:
    return NOW + datetime.timedelta(minutes=minutes)


def test_a_failing_promotion_retries_the_record_instead_of_half_applying_it(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    sync_once(session, Net(("CVE-2026-0100", cve_json("CVE-2026-0100"))), NOW)
    add_entry(session, "fortigate", families=("fortios",))

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("promosi gagal")

    monkeypatch.setattr("cti_core.cve_mirror_sync.promote_record", boom)
    net = Net(("CVE-2026-0101", cve_json("CVE-2026-0101")))
    r = sync_once(session, net, at(5), promote="live")
    assert (r.failed, r.created) == (1, 0)
    assert session.get(CveRecord, "CVE-2026-0101") is None  # savepoint: record ikut dibatalkan


# ── reference data ────────────────────────────────────────────────────────────────────────────


def test_inactive_entries_are_not_searched_or_matched_by_reference_data(session: Session) -> None:
    from cti_scraper.reference_data import (
        _resolve_techstack,
        _resolve_techstack_by_client,
    )

    add_entry(session, "visible")
    add_entry(session, "hidden", active=False)
    assert "visible" in _resolve_techstack(session) and "hidden" not in _resolve_techstack(session)
    by_client = _resolve_techstack_by_client(session)
    assert by_client["acme"] == ["visible"]
