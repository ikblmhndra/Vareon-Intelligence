#!/usr/bin/env python3
"""Daftar tiket CVE yatim: baris `cve_tickets` yang tidak punya baris `cve_tracker` untuk pasangan
`(cve_id, client_id)` yang sama.

`cve_tickets` berkunci `(cve_id, client_id)` tanpa FK ke `cve_tracker`. `purge-orphaned` versi
lama membuang baris tracker tanpa melihat tiketnya (sekarang baris ber-tiket dilindungi, lihat
`AsyncCveTrackerRepo.purge_orphaned`), jadi sisa tiket yatim dari masa itu masih bisa ada. Tiket
yatim tidak muncul di tab CVE, ekspor, maupun dashboard (semuanya mulai dari tracker).

HANYA MEMBACA, tidak pernah menulis, dan tidak ada `--apply` (disengaja). Menghapus riwayat
remediasi analis adalah keputusan sendiri, dan tiket yatim tersambung lagi sendiri kalau baris
tracker-nya dibuat ulang (mis. promosi mirror -> tracker sesudah cutover #19 menulis ulang CVE-nya
untuk tech yang sama), jadi jangan hapus sebelum tahu kenapa baris trackernya hilang.

Dari host (dev):
    uv run python tools/ops/check_orphaned_tickets.py
    uv run python tools/ops/check_orphaned_tickets.py --client acme

Di server (image worker tidak membawa `tools/`):
    make check-orphaned-tickets [ARGS='--client acme']
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Orphan:
    """Kolom tiket yang dipakai analis untuk memutuskan (bukan ORM, supaya mudah dirender/diuji)."""

    ticket_id: str
    cve_id: str
    client_id: str
    remediation_status: str
    acknowledged_by: str


def find_orphans(session: Session, client_id: str | None) -> list[Orphan]:
    from cti_core.db.models.cve import CveTicket, CveTracker
    from sqlalchemy import select

    has_tracker = (
        select(CveTracker.id)
        .where(CveTracker.cve_id == CveTicket.cve_id, CveTracker.client_id == CveTicket.client_id)
        .exists()
    )
    stmt = select(CveTicket).where(~has_tracker)
    if client_id:
        stmt = stmt.where(CveTicket.client_id == client_id)
    return [
        Orphan(
            ticket_id=t.ticket_id,
            cve_id=t.cve_id,
            client_id=t.client_id,
            remediation_status=t.remediation_status or "",
            acknowledged_by=t.acknowledged_by or "",
        )
        for t in session.execute(stmt.order_by(CveTicket.client_id, CveTicket.cve_id)).scalars()
    ]


def render(orphan: Orphan) -> str:
    return (
        f"{orphan.ticket_id:<18} {orphan.cve_id:<16} {orphan.client_id:<14} "
        f"status={orphan.remediation_status or '-':<14} acked_by={orphan.acknowledged_by or '-'}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--client", default=None, help="batasi ke satu client_id")
    args = ap.parse_args(argv)

    from cti_core.db.engine import get_sync_engine
    from sqlalchemy.orm import Session

    with Session(get_sync_engine()) as session:
        orphans = find_orphans(session, args.client)

    for orphan in orphans:
        print(render(orphan))
    scope = f"client {args.client}" if args.client else "semua client"
    print(f"\n{len(orphans)} tiket yatim ({scope}). Laporan saja -- tidak ada yang ditulis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
