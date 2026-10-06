#!/usr/bin/env python3
"""Isi `cve_tracker.published_at` (jam publish asli MITRE) untuk CVE yang masuk sebelum kolom ada.

Export Excel memakai kolom ini untuk "CVE Reported Date" (`HH:MM DD-MM-YYYY`). Scraper `new_cve`
hanya mengisinya untuk CVE yang ia tulis SESUDAH kolom ada; baris lama tetap NULL dan di export
tampil sebagai tanggal saja. Script ini mengambil ulang record MITRE tiap CVE yang `published_at`
-nya NULL dan membaca `cveMetadata.datePublished` dengan parser yang SAMA dengan scraper.

Pengaman:
  - MITRE tak terjangkau / 404 / tanpa jam di `datePublished` -> dilewati dan dilaporkan.
  - Tanggal dari MITRE (UTC) beda dengan `published` yang tersimpan -> TIDAK ditulis, dilaporkan
    (record berubah, atau baris itu bukan dari MITRE): putuskan manual.
  - Hanya mengisi yang NULL (`WHERE published_at IS NULL`); nilai yang ada tidak pernah ditimpa.

DEFAULT-nya laporan saja (tidak menulis apa pun). `--apply` baru mengubah data.
Idempoten, aman diulang.

Dari host (dev):
    uv run python tools/ops/backfill_cve_published_at.py
    uv run python tools/ops/backfill_cve_published_at.py --client acme --apply

Di server (image worker tidak membawa `tools/`, di-mount read-only seperti runbook 3.2):
    docker run --rm --network <project>_default --env-file .env -v "$PWD/tools:/tools:ro" \\
      --entrypoint python cti-worker:$CTI_TAG /tools/ops/backfill_cve_published_at.py
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import httpx
from cti_scrapers.feeds.new_cve import mitre_datetime

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_MITRE_URL = "https://cveawg.mitre.org/api/cve"
_RETRIES = 3

Action = Literal["fill", "mismatch"]


@dataclass(frozen=True)
class Row:
    """Kolom `cve_tracker` yang dipakai (bukan ORM -- biar bisa diuji tanpa DB)."""

    id: int
    cve_id: str
    client_id: str
    published: datetime.date | None


@dataclass(frozen=True)
class Finding:
    row: Row
    action: Action
    published_at: datetime.datetime


@dataclass
class Plan:
    findings: list[Finding]
    unverified: int = 0


def fetch_published_at(
    http: httpx.Client, cve_id: str, *, sleep: Callable[[float], None] = time.sleep
) -> datetime.datetime | None:
    """Jam publish dari record MITRE; `None` kalau tak bisa dipastikan (404, 429/5xx yang tak
    kunjung reda, jaringan putus, bukan JSON, atau `datePublished` tanpa jam)."""
    for attempt in range(_RETRIES + 1):
        try:
            resp = http.get(f"{_MITRE_URL}/{cve_id}")
        except httpx.TransportError:
            resp = None
        if resp is not None and resp.status_code == 404:
            return None
        if resp is not None and resp.status_code < 400:
            try:
                raw = resp.json().get("cveMetadata", {}).get("datePublished")
            except ValueError:
                return None
            return mitre_datetime(raw)
        if attempt < _RETRIES:
            sleep(5.0 * 2**attempt)
    return None


def plan(rows: Iterable[Row], fetched: Mapping[str, datetime.datetime | None]) -> Plan:
    """Nilai tiap baris. Murni -- tidak menyentuh DB maupun jaringan."""
    result = Plan(findings=[])
    for row in rows:
        published_at = fetched.get(row.cve_id)
        if published_at is None:
            result.unverified += 1
            continue
        if row.published is not None and published_at.date() != row.published:
            result.findings.append(Finding(row, "mismatch", published_at))
        else:
            result.findings.append(Finding(row, "fill", published_at))
    return result


def render(finding: Finding) -> str:
    row = finding.row
    stored = row.published.isoformat() if row.published else "-"
    return (
        f"{finding.action.upper():<8} {row.cve_id:<16} {row.client_id:<14} "
        f"published={stored}  mitre={finding.published_at.isoformat()}"
    )


def load_rows(session: Session, client_id: str | None) -> list[Row]:
    from cti_core.db.models.cve import CveTracker
    from sqlalchemy import select

    stmt = select(
        CveTracker.id, CveTracker.cve_id, CveTracker.client_id, CveTracker.published
    ).where(CveTracker.published_at.is_(None))
    if client_id:
        stmt = stmt.where(CveTracker.client_id == client_id)
    return [
        Row(id=r.id, cve_id=r.cve_id, client_id=r.client_id, published=r.published)
        for r in session.execute(stmt.order_by(CveTracker.id))
    ]


def apply_findings(session: Session, findings: Iterable[Finding]) -> int:
    """Tulis hasil. `mismatch` TIDAK pernah disentuh; yang sudah terisi tidak ditimpa."""
    from cti_core.db.models.cve import CveTracker
    from sqlalchemy import update

    done = 0
    for f in findings:
        if f.action != "fill":
            continue
        updated = session.execute(
            update(CveTracker)
            .where(CveTracker.id == f.row.id, CveTracker.published_at.is_(None))
            .values(published_at=f.published_at)
            .returning(CveTracker.id)
        ).all()
        done += len(updated)
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
        rows = load_rows(session, args.client)
        cve_ids = sorted({r.cve_id for r in rows})
        print(f"{len(rows)} baris tanpa published_at, {len(cve_ids)} CVE unik -- ambil MITRE ...")

        fetched: dict[str, datetime.datetime | None] = {}
        with httpx.Client(
            timeout=30.0, headers={"User-Agent": "vareon-backfill-cve-published-at"}
        ) as http:
            for i, cve_id in enumerate(cve_ids):
                if i:
                    time.sleep(args.delay)
                fetched[cve_id] = fetch_published_at(http, cve_id)

        result = plan(rows, fetched)
        for f in result.findings:
            if f.action == "mismatch":  # yang lancar tidak perlu dicetak satu-satu
                print(render(f))

        fill = sum(f.action == "fill" for f in result.findings)
        mismatch = sum(f.action == "mismatch" for f in result.findings)
        print(
            f"\nakan diisi: {fill} | tanggal beda dengan `published` (dilewati): {mismatch} | "
            f"tak terverifikasi (dilewati): {result.unverified}"
        )
        if not args.apply:
            print("LAPORAN SAJA -- tidak ada yang ditulis. Tambahkan --apply untuk menerapkan.")
            return 0

        done = apply_findings(session, result.findings)
        session.commit()
        print(f"Selesai, di-commit: {done} baris diisi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
