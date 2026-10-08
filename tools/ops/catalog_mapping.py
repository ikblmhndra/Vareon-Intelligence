#!/usr/bin/env python3
"""Pemetaan techstack -> katalog sebagai FILE yang bisa dipindah antar-lingkungan (ROADMAP #19,
irisan 7).

Pemetaan 34 entri dilakukan manusia lewat UI ("Map to catalog", tab Monitored Tech) di dev. Tanpa
staging, prod harus mendapat pemetaan yang SAMA tanpa mengulang klik satu per satu. ID katalog beda
di tiap DB, jadi pemetaan ditulis dengan kunci stabil (`catalog_vendors.key`,
`catalog_families.key`), bukan ID.

Tiga perintah:

  export   tulis pemetaan saat ini ke JSON (`--out`): per entri, nama, client, status aktif, dan
           targetnya.
  import   terapkan file itu ke DB ini: tambah target ke entri yang NAMANYA sama (per client, huruf
           kecil). DEFAULT-nya laporan (di-ROLLBACK); `--apply` baru menyimpan. Idempoten. Target
           yang kuncinya tidak ada di katalog DB ini (mis. backfill mirror prod belum sampai)
           dilaporkan, tidak dibuat. `--create-missing` membuat entri yang belum ada;
           `--with-active` ikut menyalin status aktif/Paused (default: TIDAK, supaya pemetaan tak
           diam-diam menjeda entri di prod).
  suggest  untuk tiap entri yang belum dipetakan, cari kandidat di katalog berdasarkan namanya
           (bahan tinjauan manusia; tidak menulis apa pun). Label sering beda dari nama CNA
           (fortigate = FortiOS), jadi hasil kosong itu wajar: cari manual di UI.

Setelah `import --apply`, isi riwayat entri yang baru dipetakan dengan
`tools/ops/promote_cve_mirror.py --mode shadow|live --entry <nama>` (bila promosi dinyalakan).

    uv run python tools/ops/catalog_mapping.py export --out mapping.json
    uv run python tools/ops/catalog_mapping.py import --file mapping.json            # laporan
    uv run python tools/ops/catalog_mapping.py import --file mapping.json --apply
    uv run python tools/ops/catalog_mapping.py suggest

Di server: `make catalog-mapping CMD=import ARGS='--file /data/mapping.json'` (lihat Makefile).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cti_core.catalog_resolve import VENDOR_NONE_KEY, compact, normalize
from cti_core.db.engine import sync_session
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

FORMAT_VERSION = 1


# ── export ────────────────────────────────────────────────────────────────────────────────────


def export_mapping(session: Session, *, client_id: str | None = None) -> dict[str, Any]:
    stmt = select(TechStackEntry).order_by(TechStackEntry.client_id, TechStackEntry.name)
    if client_id is not None:
        stmt = stmt.where(TechStackEntry.client_id == client_id)
    entries = []
    for e in session.execute(stmt).scalars().all():
        targets: list[dict[str, str]] = []
        for t in e.targets:
            if t.family is not None:
                targets.append(
                    {"kind": "family", "vendor": t.family.vendor.key, "family": t.family.key}
                )
            elif t.vendor is not None:
                targets.append({"kind": "vendor", "vendor": t.vendor.key})
        entries.append(
            {"client_id": e.client_id, "name": e.name, "active": e.active, "targets": targets}
        )
    return {
        "version": FORMAT_VERSION,
        "exported_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "entries": entries,
    }


# ── import ────────────────────────────────────────────────────────────────────────────────────


@dataclass
class ImportReport:
    entries: int = 0
    added: int = 0
    already: int = 0
    created_entries: int = 0
    activity_changed: int = 0
    problems: list[str] = field(default_factory=list)
    per_entry: list[str] = field(default_factory=list)
    applied: bool = False

    def render(self) -> str:
        head = "APPLY (di-commit)" if self.applied else "LAPORAN (di-rollback, tidak menulis)"
        lines = [
            f"Mode: {head}",
            f"Entri di file        : {self.entries}",
            f"  target ditambahkan : {self.added}",
            f"  sudah ada          : {self.already}",
            f"  entri dibuat       : {self.created_entries}",
            f"  status aktif diubah: {self.activity_changed}",
            f"  masalah            : {len(self.problems)}",
        ]
        lines += [f"  - {p}" for p in self.problems]
        lines += ["", *self.per_entry]
        return "\n".join(lines)


def _find_vendor(session: Session, key: str) -> CatalogVendor | None:
    return session.execute(
        select(CatalogVendor).where(CatalogVendor.key == key)
    ).scalar_one_or_none()


def _find_family(session: Session, vendor_key: str, family_key: str) -> CatalogFamily | None:
    return session.execute(
        select(CatalogFamily)
        .join(CatalogVendor, CatalogVendor.id == CatalogFamily.vendor_id)
        .where(CatalogVendor.key == vendor_key, CatalogFamily.key == family_key)
    ).scalar_one_or_none()


def import_mapping(
    session: Session,
    data: dict[str, Any],
    *,
    create_missing: bool = False,
    with_active: bool = False,
) -> ImportReport:
    """Terapkan `data` (hasil `export_mapping`). Tidak commit/rollback: itu urusan pemanggil."""
    if data.get("version") != FORMAT_VERSION:
        raise ValueError(f"versi berkas pemetaan tidak dikenal: {data.get('version')!r}")
    report = ImportReport()
    for raw in data.get("entries", []):
        report.entries += 1
        client_id, name = str(raw["client_id"]), str(raw["name"])
        label = f"{client_id}/{name}"
        entry = session.execute(
            select(TechStackEntry).where(
                TechStackEntry.client_id == client_id,
                func.lower(TechStackEntry.name) == name.lower(),
            )
        ).scalar_one_or_none()
        if entry is None:
            if not create_missing:
                report.problems.append(
                    f"{label}: entri tidak ada di DB ini (pakai --create-missing)"
                )
                continue
            entry = TechStackEntry(
                name=name,
                client_id=client_id,
                source="catalog",
                added_date=datetime.date.today(),
                active=bool(raw.get("active", True)),
                targets=[],
            )
            session.add(entry)
            session.flush()
            report.created_entries += 1
        if with_active and entry.active != bool(raw.get("active", True)):
            entry.active = bool(raw.get("active", True))
            report.activity_changed += 1

        # Dari DB, bukan `entry.targets`: koleksi di memori bisa basi (target ditambah lewat `add`).
        have = {
            (v, f)
            for v, f in session.execute(
                select(TechStackTarget.vendor_id, TechStackTarget.family_id).where(
                    TechStackTarget.entry_id == entry.id
                )
            )
        }
        added = skipped = 0
        for t in raw.get("targets", []):
            vendor = _find_vendor(session, str(t.get("vendor", "")))
            family = None
            if vendor is None:
                report.problems.append(f"{label}: vendor {t.get('vendor')!r} tidak ada di katalog")
                continue
            if t.get("kind") == "family":
                family = _find_family(session, vendor.key, str(t.get("family", "")))
                if family is None:
                    report.problems.append(
                        f"{label}: produk {t.get('vendor')}/{t.get('family')} tidak ada di katalog"
                    )
                    continue
            elif t.get("kind") == "vendor":
                if not vendor.monitorable or vendor.key == VENDOR_NONE_KEY:
                    report.problems.append(f"{label}: vendor {vendor.key!r} tidak bisa di-Monitor")
                    continue
            else:
                report.problems.append(f"{label}: jenis target tidak dikenal {t.get('kind')!r}")
                continue
            ids = (None, family.id) if family is not None else (vendor.id, None)
            if ids in have:
                skipped += 1
                continue
            session.add(TechStackTarget(entry_id=entry.id, vendor_id=ids[0], family_id=ids[1]))
            have.add(ids)
            added += 1
        session.flush()
        report.added += added
        report.already += skipped
        report.per_entry.append(f"{label}: +{added} target, {skipped} sudah ada")
    return report


# ── suggest ───────────────────────────────────────────────────────────────────────────────────


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@dataclass(frozen=True)
class Candidate:
    kind: str
    label: str
    cve_seen_total: int
    exact: bool


def suggest_for(session: Session, name: str, *, top: int = 5) -> list[Candidate]:
    norm, comp = normalize(name), compact(name)
    out: list[Candidate] = []
    if len(comp) >= 2:
        fams = session.execute(
            select(CatalogFamily, CatalogVendor)
            .join(CatalogVendor, CatalogVendor.id == CatalogFamily.vendor_id)
            .where(
                or_(
                    CatalogFamily.key.ilike(_like(norm), escape="\\"),
                    CatalogFamily.display_name.ilike(_like(name.strip()), escape="\\"),
                )
            )
            .order_by(CatalogFamily.cve_seen_total.desc())
            .limit(top * 3)
        ).all()
        out += [
            Candidate(
                "product",
                f"{v.display_name} > {f.display_name}",
                f.cve_seen_total,
                f.key == norm,
            )
            for f, v in fams
        ]
        vendors = session.execute(
            select(CatalogVendor)
            .where(
                or_(
                    CatalogVendor.key.ilike(_like(comp), escape="\\"),
                    CatalogVendor.display_name.ilike(_like(name.strip()), escape="\\"),
                )
            )
            .order_by(CatalogVendor.cve_seen_total.desc())
            .limit(top * 3)
        ).scalars()
        out += [
            Candidate("vendor", v.display_name, v.cve_seen_total, v.key == comp) for v in vendors
        ]
    out.sort(key=lambda c: (not c.exact, -c.cve_seen_total))
    return out[:top]


def render_suggestions(session: Session, *, client_id: str | None, top: int) -> str:
    stmt = select(TechStackEntry).order_by(TechStackEntry.client_id, TechStackEntry.name)
    if client_id is not None:
        stmt = stmt.where(TechStackEntry.client_id == client_id)
    lines: list[str] = []
    unmapped = [e for e in session.execute(stmt).scalars().all() if not e.targets]
    for e in unmapped:
        cands = suggest_for(session, e.name, top=top)
        lines.append(f"{e.client_id}/{e.name}")
        if not cands:
            lines.append(
                "    (tidak ada kandidat; label mungkin beda dari nama CNA, cari manual di UI)"
            )
        for c in cands:
            mark = "  *" if c.exact else "   "
            lines.append(f"  {mark} [{c.kind:<7}] {c.label}  ({c.cve_seen_total} CVE)")
    lines.append("")
    lines.append(
        f"{len(unmapped)} entri belum dipetakan. * = nama cocok persis; tinjau sebelum memetakan."
    )
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="tulis pemetaan saat ini ke JSON")
    ex.add_argument("--out", type=Path, required=True)
    ex.add_argument("--client", default=None)
    im = sub.add_parser("import", help="terapkan berkas pemetaan (laporan dulu)")
    im.add_argument("--file", type=Path, required=True)
    im.add_argument("--apply", action="store_true")
    im.add_argument("--create-missing", action="store_true")
    im.add_argument("--with-active", action="store_true")
    sg = sub.add_parser("suggest", help="kandidat katalog untuk entri yang belum dipetakan")
    sg.add_argument("--client", default=None)
    sg.add_argument("--top", type=int, default=5)
    args = ap.parse_args(argv)

    if args.cmd == "import":
        if not args.file.is_file():
            print(f"berkas tidak ada: {args.file}", file=sys.stderr)
            return 2
        try:
            data = json.loads(args.file.read_text())
        except ValueError as e:
            print(f"bukan JSON: {e}", file=sys.stderr)
            return 2

    with sync_session() as session:
        if args.cmd == "export":
            data = export_mapping(session, client_id=args.client)
            args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            mapped = sum(1 for e in data["entries"] if e["targets"])
            print(f"{len(data['entries'])} entri ({mapped} dipetakan) -> {args.out}")
            return 0
        if args.cmd == "suggest":
            print(render_suggestions(session, client_id=args.client, top=args.top))
            return 0
        try:
            report = import_mapping(
                session, data, create_missing=args.create_missing, with_active=args.with_active
            )
        except (ValueError, KeyError, TypeError) as e:
            print(f"berkas pemetaan tidak valid: {e}", file=sys.stderr)
            return 2
        report.applied = args.apply
        if args.apply:
            session.commit()
        else:
            session.rollback()
    print(report.render())
    if not args.apply:
        print("\nLaporan saja -- tidak ada yang ditulis. Ulangi dengan --apply untuk menyimpan.")
    return 1 if report.problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
