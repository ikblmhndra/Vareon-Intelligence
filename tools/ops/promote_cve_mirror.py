#!/usr/bin/env python3
"""Jalankan promosi mirror -> techstack terhadap SELURUH mirror (ROADMAP #19, irisan 4).

Ingest harian (`cve.mirror_sync`) hanya memproses record yang baru masuk. Skrip ini untuk dua
keadaan: (1) mengisi riwayat bayangan sebelum perbandingan (`--mode shadow --apply`, lalu
`tools/ops/compare_promotion_shadow.py`), dan (2) entri baru di-Monitor / target diubah: riwayatnya
langsung terisi (`--mode live --apply --entry <nama>`), tanpa tombol "Populate now".

Sifat:
  - DEFAULT-nya laporan: semuanya dikerjakan di DB lalu di-ROLLBACK (angka persis seperti yang
    akan ditulis). `--apply` baru meng-commit.
  - `--mode shadow` hanya menulis `cve_promotion_shadow` (`cve_tracker` tidak disentuh);
    `--mode live` menulis `cve_tracker` (upsert; `detected_on` diisi saat INSERT, enrichment,
    ticket, dan FP tidak disentuh, baris yang ada tidak dihapus).
  - TIDAK mengirim notifikasi Telegram (riwayat bukan "CVE baru"; ringkasan ingest memakai batas
    umur 3 hari).
  - Memakai kunci advisory yang sama dengan `cve.mirror_sync` dan backfill: bila ingest sedang
    jalan, skrip berhenti dan minta diulang.
  - `--entry` (boleh diulang) membatasi ke entri tertentu (nama, huruf kecil) -- jalur "entri baru
    di-Monitor"; `--client` membatasi ke satu client.

Dari host (dev):
    uv run python tools/ops/promote_cve_mirror.py --mode shadow
    uv run python tools/ops/promote_cve_mirror.py --mode shadow --apply

Di server (image worker tidak membawa `tools/`):
    make promote-cve-mirror MODE=shadow [ARGS='--apply --entry fortigate']
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from collections.abc import Sequence

from cti_core.cve_mirror_sync import LOCK_KEY
from cti_core.cve_promotion import (
    EntryView,
    PromoteSummary,
    promote_all,
)
from cti_core.cve_promotion import load_entries as _load_entries
from cti_core.db.engine import sync_session
from sqlalchemy import func, select
from sqlalchemy.orm import Session


class Locked(RuntimeError):
    """`cve.mirror_sync` sedang berjalan (kunci advisory dipegang)."""


def select_entries(
    session: Session, *, client_id: str | None = None, names: Sequence[str] = ()
) -> list[EntryView]:
    wanted = {n.strip().lower() for n in names if n.strip()}
    entries = _load_entries(session, client_id=client_id)
    return [e for e in entries if not wanted or e.name.lower() in wanted]


def render(
    summary: PromoteSummary, *, mode: str, apply: bool, seconds: float, top: int = 25
) -> str:
    lines = [
        f"Mode: {mode.upper()} -- " + ("di-commit (--apply)" if apply else "LAPORAN (di-rollback)"),
        f"Record mirror dibaca : {summary.scanned}",
        f"  cocok >= 1 client  : {summary.matched}",
    ]
    if mode == "shadow":
        lines.append(f"  baris bayangan     : {summary.shadow}")
    else:
        lines += [
            f"  baris tracker baru : {summary.created}",
            f"  diperbarui         : {summary.updated}",
            f"  tidak berubah      : {summary.unchanged}",
        ]
    spec = ", ".join(f"{k}={v}" for k, v in sorted(summary.per_specificity.items()))
    lines.append(f"Kekhususan menang    : {spec or '-'}")
    lines.append("Per entri (CVE yang cocok):")
    for name, n in summary.per_entry.most_common(top):
        lines.append(f"  {name:<30} {n}")
    if len(summary.per_entry) > top:
        lines.append(f"  ... {len(summary.per_entry) - top} entri lain")
    lines.append(f"Waktu: {seconds:.1f} dtk")
    return "\n".join(lines)


def run(
    session: Session,
    entries: Sequence[EntryView],
    *,
    mode: str,
    apply: bool,
    limit: int | None = None,
    batch_size: int = 500,
    verbose: bool = False,
) -> tuple[PromoteSummary, float]:
    if not session.scalar(select(func.pg_try_advisory_lock(LOCK_KEY))):
        raise Locked("cve.mirror_sync sedang berjalan; ulangi sebentar lagi")
    started = time.monotonic()
    try:

        def progress(s: PromoteSummary) -> None:
            if verbose:
                print(
                    f"[{(time.monotonic() - started) / 60:.1f} mnt] {s.scanned} record, "
                    f"cocok={s.matched}",
                    file=sys.stderr,
                    flush=True,
                )

        summary = promote_all(
            session,
            entries,
            mode,  # type: ignore[arg-type]
            batch_size=batch_size,
            limit=limit,
            progress=progress,
        )
        if apply:
            session.commit()
        else:
            session.rollback()
    finally:
        with contextlib.suppress(Exception):  # sesi rusak: kunci lepas saat koneksi ditutup
            session.execute(select(func.pg_advisory_unlock(LOCK_KEY)))
    return summary, time.monotonic() - started


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--mode", choices=("shadow", "live"), required=True)
    ap.add_argument("--apply", action="store_true", help="commit (default: laporan saja)")
    ap.add_argument("--client", default=None, help="hanya entri milik client ini")
    ap.add_argument(
        "--entry", action="append", default=[], help="hanya entri ini (nama; boleh diulang)"
    )
    ap.add_argument("--limit", type=int, default=None, help="berhenti setelah N record (uji coba)")
    ap.add_argument("--batch-size", type=int, default=500)
    args = ap.parse_args(argv)

    with sync_session() as session:
        entries = select_entries(session, client_id=args.client, names=args.entry)
        if not entries:
            print(
                "Tidak ada entri techstack AKTIF yang cocok dengan pilihan ini "
                f"(client={args.client!r}, entry={args.entry!r}); tidak ada yang dikerjakan.",
                file=sys.stderr,
            )
            return 4
        targeted = sum(1 for e in entries if e.has_targets)
        print(
            f"{len(entries)} entri aktif ({targeted} bertarget, {len(entries) - targeted} teks); "
            f"mode {args.mode}{'' if args.apply else ' (laporan)'}.",
            file=sys.stderr,
            flush=True,
        )
        try:
            summary, seconds = run(
                session,
                entries,
                mode=args.mode,
                apply=args.apply,
                limit=args.limit,
                batch_size=args.batch_size,
                verbose=True,
            )
        except Locked as e:
            print(str(e), file=sys.stderr)
            return 3
    print(render(summary, mode=args.mode, apply=args.apply, seconds=seconds))
    if not args.apply:
        print("\nLaporan saja -- tidak ada yang ditulis. Ulangi dengan --apply untuk menyimpan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
