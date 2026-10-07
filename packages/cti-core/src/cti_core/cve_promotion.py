"""Pencocokan mirror -> techstack dan promosi ke `cve_tracker` (ROADMAP #19, irisan 4;
`docs/CVE_CATALOG_DESIGN.md` 4 dan 8).

Dua lapis, sengaja dipisah:

1. **`choose` (murni)**: diberi satu CVE (keluarga/vendor katalog + teks) dan entri techstack
   aktif, tentukan per client entri mana yang menang. Tanpa DB, jadi aturannya dikunci tes murni.
2. **`promote_record` / `promote_all` (DB)**: menerapkan hasil itu menurut mode.

Aturan pencocokan (keputusan user 2026-10-07 + desain 4):
- Entri **dengan target**: cocok hanya lewat target (keluarga yang ada di CVE, atau vendor yang ada
  di CVE). Nama entri TIDAK dicocokkan lewat teks, itu inti pindah ke katalog.
- Entri **tanpa target** (entri lama/custom, semua entri produksi saat ini): gate teks lama
  (`tech_match.relevant_techs` terhadap vendor/produk CVE, ringkasan sebagai cadangan), jadi
  perilaku mereka tidak berubah.
- Satu baris per (CVE, client) (invarian: satu tech per baris). Bila beberapa entri cocok:
  paling spesifik menang (target keluarga > target vendor > teks), lalu nama paling awal menurut
  abjad (aturan `new_cve`), lalu `entry_id`, agar deterministik.

Mode (`Settings.cve_mirror.promote`):
- `off`: tidak melakukan apa pun.
- `shadow`: hanya menulis `cve_promotion_shadow` (untuk dibandingkan dengan `cve_tracker` hasil
  `new_cve`); `cve_tracker` tidak disentuh.
- `live`: menulis `cve_tracker` lewat `CveTrackerRepo.upsert_with_status`. `detected_on` diisi
  server saat INSERT dan tidak pernah ditimpa; kolom enrichment (KEV, EPSS, PoC, ...) dan
  ticket/FP tidak disentuh. Baris yang DIBUAT dicatat di `Session.info[NEW_CVE_ROWS_KEY]` sehingga
  ringkasan Telegram CVE baru (`cti_scraper.sinks.finish_run`) jalan tanpa diubah.

Baris `cve_tracker` yang sudah ada tidak pernah dihapus di sini (ticket/ACK berkunci
`(cve_id, client_id)` tanpa FK): bila CVE berhenti cocok, barisnya tetap.
"""

from __future__ import annotations

import datetime
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from cti_core.db.models.cve import CveTracker
from cti_core.db.models.cve_mirror import CvePromotionShadow, CveRecord
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from cti_core.db.repositories.cve import CveTrackerRepo
from cti_core.tech_match import relevant_techs

Mode = Literal["off", "shadow", "live"]

NEW_CVE_ROWS_KEY = "cve_new_rows"
"""Kunci `Session.info`: [(cve_id, client_id)] baris `cve_tracker` yang DIBUAT run ini
(`cti_scraper.sinks.finish_run` membacanya untuk ringkasan Telegram)."""

SPEC_TEXT = 0
SPEC_VENDOR = 1
SPEC_FAMILY = 2
SPEC_LABELS = {SPEC_TEXT: "text", SPEC_VENDOR: "vendor", SPEC_FAMILY: "family"}


@dataclass(frozen=True)
class EntryView:
    entry_id: int
    client_id: str
    name: str
    vendor_ids: frozenset[int] = frozenset()
    family_ids: frozenset[int] = frozenset()

    @property
    def has_targets(self) -> bool:
        return bool(self.vendor_ids or self.family_ids)


@dataclass(frozen=True)
class RecordView:
    cve_id: str
    summary: str = ""
    vendor_ids: frozenset[int] = frozenset()
    family_ids: frozenset[int] = frozenset()
    texts: tuple[str, ...] = ()
    """vendor/produk CVE sebagai teks (bahan gate teks entri tanpa target)."""


@dataclass(frozen=True)
class Choice:
    entry: EntryView
    specificity: int

    @property
    def label(self) -> str:
        return SPEC_LABELS[self.specificity]


def _specificity(record: RecordView, entry: EntryView) -> int | None:
    if entry.has_targets:
        if entry.family_ids & record.family_ids:
            return SPEC_FAMILY
        if entry.vendor_ids & record.vendor_ids:
            return SPEC_VENDOR
        return None
    if relevant_techs([entry.name], record.summary, list(record.texts)):
        return SPEC_TEXT
    return None


def choose(record: RecordView, entries: Iterable[EntryView]) -> dict[str, Choice]:
    """`{client_id: pilihan}` untuk satu CVE. Klien tanpa entri yang cocok tidak muncul."""
    best: dict[str, tuple[tuple[int, str, int], Choice]] = {}
    for entry in entries:
        spec = _specificity(record, entry)
        if spec is None:
            continue
        key = (-spec, entry.name, entry.entry_id)
        kept = best.get(entry.client_id)
        if kept is None or key < kept[0]:
            best[entry.client_id] = (key, Choice(entry, spec))
    return {client: choice for client, (_, choice) in best.items()}


# ── DB ────────────────────────────────────────────────────────────────────────────────────────


def load_entries(
    session: Session,
    *,
    client_id: str | None = None,
    entry_ids: Sequence[int] | None = None,
) -> list[EntryView]:
    """Entri techstack AKTIF beserta targetnya. Entri nonaktif tidak pernah dicocokkan."""
    stmt = select(TechStackEntry).where(TechStackEntry.active.is_(True))
    if client_id is not None:
        stmt = stmt.where(TechStackEntry.client_id == client_id)
    if entry_ids is not None:
        stmt = stmt.where(TechStackEntry.id.in_(entry_ids))
    entries = session.execute(stmt).scalars().all()
    if not entries:
        return []
    vendors: dict[int, set[int]] = {}
    families: dict[int, set[int]] = {}
    targets = session.execute(
        select(TechStackTarget).where(TechStackTarget.entry_id.in_([e.id for e in entries]))
    ).scalars()
    for t in targets:
        if t.vendor_id is not None:
            vendors.setdefault(t.entry_id, set()).add(t.vendor_id)
        if t.family_id is not None:
            families.setdefault(t.entry_id, set()).add(t.family_id)
    return [
        EntryView(
            entry_id=e.id,
            client_id=e.client_id,
            name=e.name,
            vendor_ids=frozenset(vendors.get(e.id, ())),
            family_ids=frozenset(families.get(e.id, ())),
        )
        for e in entries
    ]


def record_view(rec: CveRecord) -> RecordView:
    texts: list[str] = []
    for p in rec.products:
        texts.extend(t for t in (p.vendor_raw, p.product_raw, p.product_norm) if t)
    return RecordView(
        cve_id=rec.cve_id,
        summary=rec.summary,
        vendor_ids=frozenset(p.vendor_id for p in rec.products),
        family_ids=frozenset(p.family_id for p in rec.products),
        texts=tuple(texts),
    )


@dataclass
class PromoteOutcome:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    shadow: int = 0
    matched_clients: int = 0
    choices: dict[str, Choice] = field(default_factory=dict)


def _tracker_fields(rec: CveRecord, tech: str) -> dict[str, object]:
    """Padanan `sinks._cve_sink`: nilai default parser lama (skor 0.0, vektor "") dipertahankan
    supaya baris hasil promosi sama bentuknya dengan hasil `new_cve`."""
    stamp = rec.modified_at or rec.published_at
    fields: dict[str, object] = {
        "tech": tech,
        "link": rec.link,
        "summary": rec.summary,
        "published": rec.published_date,
        "cve_modified_date": stamp.date() if stamp else rec.published_date,
        "solutions": rec.solutions,
        "cve_score": rec.cvss_score if rec.cvss_score is not None else 0.0,
        "cve_severity": rec.cvss_severity,
        "cvss_vector": rec.cvss_vector or "",
    }
    if rec.published_at is not None:  # jangan menimpa jam yang sudah ada dengan NULL
        fields["published_at"] = rec.published_at
    return fields


def _promote_live(session: Session, rec: CveRecord, client_id: str, tech: str) -> str:
    existing = session.execute(
        select(CveTracker).where(CveTracker.cve_id == rec.cve_id, CveTracker.client_id == client_id)
    ).scalar_one_or_none()
    fields = _tracker_fields(rec, tech)
    if existing is not None:
        record_day = fields["cve_modified_date"]
        unchanged = existing.tech == tech and (
            existing.cve_modified_date is not None
            and isinstance(record_day, datetime.date)
            and existing.cve_modified_date >= record_day
        )
        if unchanged:
            return "unchanged"
    _row, created = CveTrackerRepo(session).upsert_with_status(
        cve_id=rec.cve_id,
        client_id=client_id,
        references=list(rec.reference_urls),
        affected=list(rec.affected_lines),
        **fields,
    )
    if created:
        session.info.setdefault(NEW_CVE_ROWS_KEY, []).append((rec.cve_id, client_id))
        return "created"
    return "updated"


def _promote_shadow(session: Session, rec: CveRecord, choices: dict[str, Choice]) -> int:
    for client_id, choice in choices.items():
        stmt = pg_insert(CvePromotionShadow).values(
            cve_id=rec.cve_id,
            client_id=client_id,
            tech=choice.entry.name,
            entry_id=choice.entry.entry_id,
            specificity=choice.label,
            published_date=rec.published_date,
        )
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["cve_id", "client_id"],
                set_={
                    "tech": stmt.excluded.tech,
                    "entry_id": stmt.excluded.entry_id,
                    "specificity": stmt.excluded.specificity,
                    "published_date": stmt.excluded.published_date,
                    "evaluated_at": stmt.excluded.evaluated_at,
                },
            )
        )
    # Bayangan = cerminan evaluasi TERKINI: klien yang tak lagi cocok dibuang.
    stale = delete(CvePromotionShadow).where(CvePromotionShadow.cve_id == rec.cve_id)
    if choices:
        stale = stale.where(CvePromotionShadow.client_id.notin_(list(choices)))
    session.execute(stale)
    return len(choices)


def promote_record(
    session: Session, rec: CveRecord, entries: Sequence[EntryView], mode: Mode
) -> PromoteOutcome:
    """Terapkan `mode` untuk satu record mirror. `off` tidak melakukan apa pun."""
    out = PromoteOutcome()
    if mode == "off":
        return out
    out.choices = choose(record_view(rec), entries)
    out.matched_clients = len(out.choices)
    if mode == "shadow":
        out.shadow = _promote_shadow(session, rec, out.choices)
        return out
    for client_id, choice in out.choices.items():
        status = _promote_live(session, rec, client_id, choice.entry.name)
        setattr(out, status, getattr(out, status) + 1)
    return out


def forget_shadow(session: Session, cve_id: str) -> None:
    """CVE dibuang dari mirror (REJECTED): cerminannya ikut dibuang. Baris tracker tetap."""
    session.execute(delete(CvePromotionShadow).where(CvePromotionShadow.cve_id == cve_id))


@dataclass
class PromoteSummary:
    scanned: int = 0
    matched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    shadow: int = 0
    per_entry: Counter[str] = field(default_factory=Counter)
    per_specificity: Counter[str] = field(default_factory=Counter)


def promote_all(
    session: Session,
    entries: Sequence[EntryView],
    mode: Mode,
    *,
    batch_size: int = 500,
    limit: int | None = None,
    progress: Callable[[PromoteSummary], None] | None = None,
    progress_every: int = 5000,
) -> PromoteSummary:
    """Terapkan `mode` ke SELURUH mirror (entri baru di-Monitor: riwayat langsung terisi). Tidak
    meng-commit: pemanggil yang memutuskan (laporan = rollback). Memanggil `expunge_all()` tiap
    batch (ratusan ribu record tak boleh menumpuk di identity map): jangan pegang objek ORM
    lintas panggilan ini."""
    summary = PromoteSummary()
    if mode == "off" or not entries:
        return summary
    last = ""
    while True:
        batch = (
            session.execute(
                select(CveRecord)
                .where(CveRecord.cve_id > last)
                .options(selectinload(CveRecord.products))
                .order_by(CveRecord.cve_id)
                .limit(batch_size)
            )
            .scalars()
            .all()
        )
        if not batch:
            break
        for rec in batch:
            if limit is not None and summary.scanned >= limit:
                return summary
            summary.scanned += 1
            out = promote_record(session, rec, entries, mode)
            if out.matched_clients:
                summary.matched += 1
            summary.created += out.created
            summary.updated += out.updated
            summary.unchanged += out.unchanged
            summary.shadow += out.shadow
            for choice in out.choices.values():
                summary.per_entry[choice.entry.name] += 1
                summary.per_specificity[choice.label] += 1
            if progress and summary.scanned % progress_every == 0:
                progress(summary)
        last = batch[-1].cve_id
        session.flush()
        session.expunge_all()  # 100 ribu+ record: jangan menahan semuanya di identity map
    return summary
