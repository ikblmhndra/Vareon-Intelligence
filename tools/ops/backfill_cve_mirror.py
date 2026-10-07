#!/usr/bin/env python3
"""Isi mirror CVE + katalog tech dari clone/zip CVE List V5 (ROADMAP #19, irisan 3).

Ingest harian (`cve.mirror_sync`) hanya membaca jendela fetch terakhir, jadi riwayat awal (2025
sampai sekarang, ~117 ribu CVE) masuk lewat skrip ini SEKALI: parser (`cti_core.cve_record`),
resolver (`cti_core.catalog_resolve`), dan `apply_record` yang sama dengan ingest, jadi hasilnya
identik dengan kalau CVE itu datang lewat delta. Sumber = clone `cvelistV5` (folder berisi `cves/`)
atau zip rilisnya (unduh di mesin yang bisa ke github.com; `docs/CVE_CATALOG_DESIGN.md` 5/8).

Sifat:
  - DEFAULT-nya laporan: semua dikerjakan di DB lalu di-ROLLBACK (angka persis seperti yang akan
    ditulis, tanpa menulis apa pun). `--apply` baru meng-commit.
  - Idempoten dan aman diulang / dijalankan bersamaan dengan `cve.mirror_sync`: memakai kunci
    advisory yang sama (`LOCK_KEY`); bila ingest sedang jalan, skrip berhenti dan minta diulang.
    Record yang lebih lama dari yang tersimpan ditolak (`modified_at`).
  - Record di luar retensi (terbit sebelum 1 Januari tahun lalu), tanpa tanggal, atau bukan
    PUBLISHED dilewati dan dihitung; tahun default = tahun berjalan dan sebelumnya.
  - TIDAK menyentuh `cve_tracker`, ticket, maupun kursor `cve.mirror_sync`.

Dari host (dev):
    uv run python tools/ops/backfill_cve_mirror.py --source /data/cvelistV5
    uv run python tools/ops/backfill_cve_mirror.py --source /data/cvelistV5-main.zip --apply

Di server (image worker tidak membawa `tools/`; mount read-only + data):
    docker compose --env-file docker/stack.env --profile app run --rm --no-deps -T \\
      -v "$PWD/tools:/tools:ro" -v /data:/data:ro --entrypoint python worker \\
      /tools/ops/backfill_cve_mirror.py --source /data/cvelistV5 --apply
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cti_core.cve_mirror_sync import LOCK_KEY, apply_record
from cti_core.db.engine import sync_session
from cti_core.db.models.catalog import CatalogFamily, CatalogVendor
from cti_core.db.models.cve_mirror import CveRecord
from cti_core.db.repositories.catalog import CatalogRepo, CveMirrorRepo
from sqlalchemy import func, select
from sqlalchemy.orm import Session

try:  # dijalankan sebagai skrip (`python tools/ops/...`) atau diimpor sebagai paket (tes)
    from tools.ops.spike_cve_catalog import iter_raw
except ModuleNotFoundError:  # pragma: no cover - jalur skrip
    from spike_cve_catalog import iter_raw  # type: ignore[no-redef]


class Locked(RuntimeError):
    """`cve.mirror_sync` sedang berjalan (kunci advisory dipegang)."""


@dataclass
class Report:
    scanned: int = 0
    parse_errors: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    skip_reasons: Counter[str] = field(default_factory=Counter)
    failed: int = 0
    seconds: float = 0.0
    totals: dict[str, int] = field(default_factory=dict)
    applied: bool = False

    def render(self) -> str:
        lines = [
            "Mode: APPLY (di-commit)"
            if self.applied
            else "Mode: LAPORAN (di-rollback, tidak menulis)",
            f"Berkas dibaca     : {self.scanned}",
            f"  tidak terbaca   : {self.parse_errors}",
            f"  gagal diproses  : {self.failed}",
        ]
        for name in ("created", "updated", "stale", "removed", "skipped"):
            lines.append(f"  {name:<15} : {self.outcomes[name]}")
        for reason, n in self.skip_reasons.most_common():
            lines.append(f"      dilewati ({reason}): {n}")
        lines.append(f"Waktu: {self.seconds:.1f} dtk")
        if self.totals:
            lines.append(
                "Isi tabel sesudahnya: "
                + ", ".join(f"{k}={v}" for k, v in sorted(self.totals.items()))
            )
        return "\n".join(lines)


def _try_lock(session: Session) -> bool:
    return bool(session.scalar(select(func.pg_try_advisory_lock(LOCK_KEY))))


def run(
    session: Session,
    records: Iterable[tuple[str, bytes]],
    *,
    today: datetime.date,
    apply: bool,
    commit_every: int = 500,
    limit: int | None = None,
) -> Report:
    """Proses `records` (nama, isi) ke mirror. `apply=False` = semua di-rollback di akhir."""
    if not _try_lock(session):
        raise Locked("cve.mirror_sync sedang berjalan; ulangi sebentar lagi")
    report = Report(applied=apply)
    started = time.monotonic()
    try:
        catalog = CatalogRepo(session)
        repo = CveMirrorRepo(session, catalog)
        aliases = catalog.alias_map()
        for name, blob in records:
            if limit is not None and report.scanned >= limit:
                break
            report.scanned += 1
            try:
                data = json.loads(blob)
                cve_id = data["cveMetadata"]["cveId"]
                if not isinstance(data, dict) or not isinstance(cve_id, str):
                    raise ValueError("bentuk record tak dikenal")
            except (ValueError, KeyError, TypeError):
                report.parse_errors += 1
                continue
            try:
                with session.begin_nested():
                    outcome, reason = apply_record(
                        repo, data, cve_id=cve_id, today=today, aliases=aliases
                    )
            except Exception as e:
                catalog.reset_cache()
                report.failed += 1
                print(f"GAGAL {name}: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
                continue
            report.outcomes[outcome] += 1
            if outcome == "skipped":
                report.skip_reasons[reason] += 1
            if apply and report.scanned % commit_every == 0:
                session.commit()
            elif report.scanned % commit_every == 0:
                session.flush()
        session.flush()
        report.totals = {
            "cve_records": session.scalar(select(func.count()).select_from(CveRecord)) or 0,
            "catalog_vendors": session.scalar(select(func.count()).select_from(CatalogVendor)) or 0,
            "catalog_families": session.scalar(select(func.count()).select_from(CatalogFamily))
            or 0,
        }
        if apply:
            session.commit()
        else:
            session.rollback()
    finally:
        with contextlib.suppress(Exception):  # sesi rusak: kunci lepas saat koneksi ditutup
            session.execute(select(func.pg_advisory_unlock(LOCK_KEY)))
        report.seconds = time.monotonic() - started
    return report


def main(argv: Sequence[str] | None = None) -> int:
    today = datetime.datetime.now(datetime.UTC).date()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--source", type=Path, required=True, help="clone cvelistV5 atau zip rilisnya")
    ap.add_argument(
        "--years",
        default=f"{today.year - 1},{today.year}",
        help="tahun ID CVE yang dibaca, pisah koma (default: tahun lalu dan berjalan)",
    )
    ap.add_argument("--apply", action="store_true", help="commit (default: laporan saja)")
    ap.add_argument("--limit", type=int, default=None, help="berhenti setelah N berkas (uji coba)")
    ap.add_argument("--commit-every", type=int, default=500)
    args = ap.parse_args(argv)

    if not args.source.exists():
        print(f"sumber tidak ada: {args.source}", file=sys.stderr)
        return 2
    try:
        years = {int(y) for y in args.years.split(",") if y.strip()}
    except ValueError:
        print(f"--years tidak valid: {args.years!r}", file=sys.stderr)
        return 2

    with sync_session() as session:
        try:
            report = run(
                session,
                iter_raw(args.source, years),
                today=today,
                apply=args.apply,
                commit_every=args.commit_every,
                limit=args.limit,
            )
        except Locked as e:
            print(str(e), file=sys.stderr)
            return 3
    print(report.render())
    if not args.apply:
        print("\nLaporan saja -- tidak ada yang ditulis. Ulangi dengan --apply untuk menyimpan.")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
