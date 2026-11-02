#!/usr/bin/env python3
"""Kembalikan antrean `enrich_jobs` (P7g, 0.8.11) ke bentuk lama sebelum rollback image.

Image lama tidak kenal tabel `enrich_jobs`: job `classify` yang menunggu akan terkubur. Script ini
(host-side, hanya lewat database, checkout repo tetap di commit baru) memindahkan SEMUA job
`classify` kembali ke `rejected_articles` sebagai `failure_kind='transient'`,
`auto_replay_count=0`, alasan `[enrichment_failed] requeued after rollback`, supaya
`enrich.auto_replay` lama menguras-nya. Job `ttp` dihapus (artikelnya tetap membawa TTP Tier 1).
Satu transaksi; idempoten (jalan kedua = tidak ada yang dipindah).

Default = LAPORAN (tidak menulis). `--apply` menulis.

    DATABASE__SYNC_URL=postgresql+psycopg://... uv run python tools/ops/requeue_enrich_jobs.py
    DATABASE__SYNC_URL=... uv run python tools/ops/requeue_enrich_jobs.py --apply
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

REASON = "[enrichment_failed] requeued after rollback"

_MOVE_CLASSIFY = text(
    """
    INSERT INTO rejected_articles
        (url, url_hash, title, source, scraper_id, posted_on, reason,
         failure_kind, auto_replay_count, last_auto_replay_at, raw_enrichment)
    SELECT url, url_hash, title, source, scraper_id, posted_on, :reason,
           'transient', 0, NULL, '{}'::jsonb
    FROM enrich_jobs WHERE kind = 'classify'
    ON CONFLICT (url_hash) DO UPDATE SET
        reason = EXCLUDED.reason, failure_kind = 'transient',
        auto_replay_count = 0, last_auto_replay_at = NULL
    """
)


@dataclass(frozen=True)
class Summary:
    classify_pending: int
    classify_failed: int
    ttp: int


def count(session: Session) -> Summary:
    rows = session.execute(
        text("SELECT kind, state, count(*) FROM enrich_jobs GROUP BY kind, state")
    ).all()
    by = {(k, s): int(n) for k, s, n in rows}
    return Summary(
        classify_pending=by.get(("classify", "pending"), 0),
        classify_failed=by.get(("classify", "failed"), 0),
        ttp=by.get(("ttp", "pending"), 0) + by.get(("ttp", "failed"), 0),
    )


def requeue(session: Session) -> Summary:
    """Pindahkan job classify, hapus job ttp. Tidak commit (pemanggil yang memutuskan)."""
    summary = count(session)
    session.execute(_MOVE_CLASSIFY, {"reason": REASON})
    session.execute(text("DELETE FROM enrich_jobs WHERE kind IN ('classify', 'ttp')"))
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--apply", action="store_true", help="tulis perubahan (default: laporan saja)")
    args = ap.parse_args(argv)

    from cti_core.db.engine import get_sync_engine

    with Session(get_sync_engine()) as session:
        if args.apply:
            s = requeue(session)
            session.commit()
        else:
            s = count(session)
            session.rollback()
    print(
        f"classify pending: {s.classify_pending} | classify failed: {s.classify_failed} | "
        f"ttp: {s.ttp}"
    )
    if args.apply:
        print(
            f"Selesai: {s.classify_pending + s.classify_failed} job classify dipindah ke "
            f"rejected_articles (transient), {s.ttp} job ttp dihapus."
        )
    else:
        print("LAPORAN -- tidak ada yang ditulis. Jalankan ulang dengan --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
