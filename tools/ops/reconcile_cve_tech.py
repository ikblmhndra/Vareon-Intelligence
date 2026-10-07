#!/usr/bin/env python3
"""Rekonsiliasi kolom Tech di `cve_tracker` dengan produk yang beneran terdampak (0.2.1).

Sebelum 0.2.1, `new_cve` mencatat CVE di bawah tech yang kata kuncinya cuma disebut sambil lalu
di deskripsi (CVE Zabbix yang menyebut MariaDB tercatat sebagai `mariadb`). Scraper sudah
diperbaiki, tapi baris lama yang salah tidak ditulis ulang -- CVE itu sekarang ditolak filter,
jadi tidak pernah di-fetch lagi. Script ini mengambil ulang record MITRE tiap CVE di tracker dan
menilai tiap baris dengan aturan yang SAMA dengan scraper (`cti_scrapers.feeds.new_cve`):

  - tech cocok dengan produk terdampak     -> dibiarkan
  - tidak cocok, tapi tech LAIN milik client yang sama cocok -> RETAG ke tech itu
  - tidak cocok sama sekali                -> DELETE (baris + penanda false positive-nya)
  - tidak cocok sama sekali, tapi sudah punya ticket/ACK -> REVIEW: TIDAK pernah dihapus
    otomatis, putuskan manual
  - MITRE tak terjangkau / tak ada data (tanpa produk dan tanpa ringkasan) -> dilewati, dilaporkan

DEFAULT-nya laporan saja (tidak menulis apa pun). `--apply` baru mengubah data -- jalankan
laporannya dulu dan baca. Idempoten, aman diulang.

Dari host (dev):
    uv run python tools/ops/reconcile_cve_tech.py
    uv run python tools/ops/reconcile_cve_tech.py --client acme --apply

Di server (dari folder repo; `tools/` di-mount read-only, image worker tidak membawanya):
    docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \\
      -v "$PWD/tools:/tools:ro" --entrypoint python worker /tools/ops/reconcile_cve_tech.py
(tambahkan `--client acme` dan/atau `--apply` di ujung perintah yang sama)
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import httpx
from cti_core.tech_match import AliasMap
from cti_scrapers.feeds.new_cve import affected_products, relevant_techs, usable_products

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_MITRE_URL = "https://cveawg.mitre.org/api/cve"
_RETRIES = 3

Action = Literal["retag", "delete", "review"]


@dataclass(frozen=True)
class Row:
    """Kolom `cve_tracker` yang dipakai penilaian (bukan ORM -- biar bisa diuji tanpa DB)."""

    id: int
    cve_id: str
    client_id: str
    tech: str
    summary: str
    affected: tuple[str, ...]
    """Teks "Affected" yang tampil di UI -- hanya buat laporan."""
    has_ticket: bool


@dataclass(frozen=True)
class Finding:
    row: Row
    action: Action
    new_tech: str | None = None


@dataclass
class Plan:
    findings: list[Finding]
    ok: int = 0
    unverified: int = 0


def fetch_products(
    http: httpx.Client, cve_id: str, *, sleep: Callable[[float], None] = time.sleep
) -> list[str] | None:
    """Produk terdampak dari record MITRE; `None` kalau tak bisa dipastikan (404, 429/5xx yang
    tak kunjung reda, jaringan putus, bukan JSON) -- penilai TIDAK boleh bertindak atas `None`."""
    for attempt in range(_RETRIES + 1):
        try:
            resp = http.get(f"{_MITRE_URL}/{cve_id}")
        except httpx.TransportError:
            resp = None
        if resp is not None and resp.status_code == 404:
            return None
        if resp is not None and resp.status_code < 400:
            try:
                cna = resp.json().get("containers", {}).get("cna", {})
            except ValueError:
                return None
            return affected_products(cna)
        if attempt < _RETRIES:
            sleep(5.0 * 2**attempt)
    return None


def plan(
    rows: Iterable[Row],
    products_by_cve: Mapping[str, list[str] | None],
    client_techs: Mapping[str, Sequence[str]],
    alias_map: AliasMap | None = None,
) -> Plan:
    """Nilai tiap baris. Murni -- tidak menyentuh DB maupun jaringan. `alias_map` = alias per
    tech (`load_alias_map`); harus sama dengan yang dipakai scraper, kalau tidak tool menilai dengan
    definisi "cocok" yang berbeda dan menghapus data yang sah."""
    result = Plan(findings=[])
    for row in rows:
        products = products_by_cve.get(row.cve_id)
        if products is None or (not usable_products(products) and not row.summary.strip()):
            result.unverified += 1  # tanpa bukti apa pun -> jangan menebak
            continue
        if relevant_techs([row.tech], row.summary, products, alias_map):
            result.ok += 1
            continue
        others = sorted(t for t in client_techs.get(row.client_id, ()) if t != row.tech)
        better = relevant_techs(others, row.summary, products, alias_map)
        if better:
            result.findings.append(Finding(row, "retag", better[0]))
        elif row.has_ticket:
            result.findings.append(Finding(row, "review"))
        else:
            result.findings.append(Finding(row, "delete"))
    return result


def render(finding: Finding, products: Sequence[str] | None) -> str:
    row = finding.row
    shown = list(row.affected[:3]) or list(dict.fromkeys(products or []))[:3]
    more = len(row.affected) - 3
    affected = ", ".join(shown) + (f" +{more}" if more > 0 else "") or "-"
    tech = f"{row.tech} -> {finding.new_tech}" if finding.action == "retag" else row.tech
    note = "  (punya ticket/ACK -- putuskan manual)" if finding.action == "review" else ""
    return (
        f"{finding.action.upper():<7} {row.cve_id:<16} {row.client_id:<14} {tech:<28} "
        f"| affected: {affected}{note}"
    )


def load_alias_map(session: Session) -> dict[str, list[str]]:
    """`techstack_entries.aliases` dalam bentuk yang sama dengan reference data scraper."""
    from cti_core.db.models.techstack import TechStackEntry
    from cti_core.tech_match import build_alias_map
    from sqlalchemy import select

    return build_alias_map(
        session.execute(select(TechStackEntry.name, TechStackEntry.aliases)).all()  # type: ignore[arg-type]
    )


def load_rows(session: Session, client_id: str | None) -> tuple[list[Row], dict[str, list[str]]]:
    from cti_core.db.models.cve import CveAffected, CveTicket, CveTracker
    from cti_core.db.models.techstack import TechStackEntry
    from sqlalchemy import select

    stmt = select(
        CveTracker.id,
        CveTracker.cve_id,
        CveTracker.client_id,
        CveTracker.tech,
        CveTracker.summary,
    ).where(CveTracker.tech.is_not(None))
    if client_id:
        stmt = stmt.where(CveTracker.client_id == client_id)
    base = session.execute(stmt.order_by(CveTracker.id)).all()

    affected: dict[int, list[str]] = defaultdict(list)
    for tracker_id, text in session.execute(
        select(CveAffected.cve_tracker_id, CveAffected.affected).order_by(CveAffected.id)
    ):
        affected[tracker_id].append(text)
    ticketed = {
        (cve_id, cid)
        for cve_id, cid in session.execute(select(CveTicket.cve_id, CveTicket.client_id))
    }

    techs: dict[str, list[str]] = defaultdict(list)
    for cid, name in session.execute(select(TechStackEntry.client_id, TechStackEntry.name)):
        techs[cid].append(name)

    rows = [
        Row(
            id=r.id,
            cve_id=r.cve_id,
            client_id=r.client_id,
            tech=r.tech,
            summary=r.summary or "",
            affected=tuple(affected.get(r.id, ())),
            has_ticket=(r.cve_id, r.client_id) in ticketed,
        )
        for r in base
    ]
    return rows, techs


def apply_findings(session: Session, findings: Iterable[Finding]) -> dict[str, int]:
    """Tulis hasil penilaian. `review` TIDAK pernah disentuh."""
    from cti_core.db.models.cve import CveFalsePositive, CveTracker
    from sqlalchemy import delete, update

    done = {"retag": 0, "delete": 0}
    for f in findings:
        if f.action == "retag":
            session.execute(
                update(CveTracker).where(CveTracker.id == f.row.id).values(tech=f.new_tech)
            )
            done["retag"] += 1
        elif f.action == "delete":
            # ORM, bukan DELETE mentah: anak-anaknya (references/affected/pocs/...) ikut cascade.
            tracker = session.get(CveTracker, f.row.id)
            if tracker is not None:
                session.delete(tracker)
            session.execute(
                delete(CveFalsePositive).where(
                    CveFalsePositive.cve_id == f.row.cve_id,
                    CveFalsePositive.client_id == f.row.client_id,
                )
            )
            done["delete"] += 1
    session.flush()
    return done


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="tulis perubahan (default: laporan saja)")
    ap.add_argument("--client", default=None, help="batasi ke satu client_id")
    ap.add_argument(
        "--delay", type=float, default=1.0, help="jeda antar request MITRE, detik (default 1)"
    )
    args = ap.parse_args(argv)

    from cti_core.db.engine import get_sync_engine
    from sqlalchemy.orm import Session

    with Session(get_sync_engine()) as session:
        rows, client_techs = load_rows(session, args.client)
        alias_map = load_alias_map(session)
        cve_ids = sorted({r.cve_id for r in rows})
        print(f"{len(rows)} baris, {len(cve_ids)} CVE unik -- mengambil record MITRE ...")

        products: dict[str, list[str] | None] = {}
        with httpx.Client(
            timeout=30.0, headers={"User-Agent": "vareon-reconcile-cve-tech"}
        ) as http:
            for i, cve_id in enumerate(cve_ids):
                if i:
                    time.sleep(args.delay)
                products[cve_id] = fetch_products(http, cve_id)

        result = plan(rows, products, client_techs, alias_map)
        for f in result.findings:
            print(render(f, products.get(f.row.cve_id)))

        counts = {
            a: sum(f.action == a for f in result.findings) for a in ("retag", "delete", "review")
        }
        print(
            f"\nsesuai: {result.ok} | retag: {counts['retag']} | delete: {counts['delete']} | "
            f"review manual: {counts['review']} | tak terverifikasi (dilewati): {result.unverified}"
        )
        if not args.apply:
            print("LAPORAN SAJA -- tidak ada yang ditulis. Tambahkan --apply untuk menerapkan.")
            return 0

        done = apply_findings(session, result.findings)
        session.commit()
        print(f"Selesai, di-commit: {done['retag']} di-retag, {done['delete']} dihapus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
