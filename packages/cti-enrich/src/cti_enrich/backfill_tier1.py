"""Backfill Tier 1 (ekstraktor deterministik P4) untuk artikel yang SUDAH tersimpan.

Untuk tiap artikel: ambil ulang teks penuh (`fetch_text`), jalankan `run_tier1`, lalu tambahkan
TTP / threat actor / malware / industri yang belum ada lewat `ArticleRepo.add_tier1`. Murni
ADD-ONLY: baris hasil LLM tidak pernah diubah atau dihapus, dan `raw_enrichment` sengaja tidak
disentuh (jejak `tier1` hanya ditulis pipeline untuk artikel baru) supaya perintah ini aman
diulang. Tanpa LLM dan tanpa alert.

Artikel "Security Technology & Best Practices" diperlakukan sama seperti di pipeline: tanpa
teknik dan TANPA aktor (Ruling 11), hanya malware + industri.

Commit per artikel -- run panjang (jaringan per artikel) tidak boleh menahan satu transaksi.
`--dry-run` melakukan rollback tiap artikel, jadi hanya menghitung.

    python -m cti_enrich.backfill_tier1 --dry-run
    python -m cti_enrich.backfill_tier1 [--since 2026-09-01] [--limit 200] [--sleep 1.0]
"""

from __future__ import annotations

import argparse
import datetime
import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog
from cti_core.attack_ttp import NormalizedTTP
from cti_core.db.models.article import Article
from cti_core.db.repositories.article import ArticleRepo
from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_enrich.backfill import BEST_PRACTICE_NEWS_TYPE
from cti_enrich.routing import threat_actor_names
from cti_enrich.stages.fetch_text import fetch_text
from cti_enrich.stages.tier1 import run_tier1

log = structlog.get_logger()


@dataclass
class Tier1BackfillStats:
    scanned: int = 0
    fetched: int = 0
    fetch_failed: int = 0
    ttp_rows_added: int = 0
    actor_rows_added: int = 0
    malware_rows_added: int = 0
    industry_replaced: int = 0
    """Jumlah ARTIKEL yang industri "General"-nya diganti tebakan keyword."""


def backfill_tier1(
    session: Session,
    *,
    since: datetime.date | None,
    limit: int | None,
    sleep: float,
    dry_run: bool,
    fetch: Callable[[str], str] = fetch_text,
) -> Tier1BackfillStats:
    """Proses artikel urut `id` naik. Commit (atau rollback bila `dry_run`) per artikel."""
    stats = Tier1BackfillStats()
    stmt = select(Article.id).order_by(Article.id)
    if since is not None:
        stmt = stmt.where(Article.posted_on >= since)
    # Daftar id diambil di muka: sesi di-commit/rollback tiap artikel, kursor terbuka tidak aman.
    ids = list(session.execute(stmt).scalars())
    if limit is not None:
        ids = ids[:limit]

    for article_id in ids:
        article = session.get(Article, article_id)
        if article is None:
            continue
        stats.scanned += 1
        try:
            text = fetch(article.url)
        except Exception as exc:
            log.warning("tier1_backfill_fetch_failed", article_id=article_id, error=str(exc))
            text = ""
        if not text:
            stats.fetch_failed += 1
            session.rollback()
            continue
        stats.fetched += 1

        best_practice = article.news_type == BEST_PRACTICE_NEWS_TYPE
        result = run_tier1(
            session=session,
            title=article.title or "",
            text=text,
            victim_name=article.victim_name,
            techniques=not best_practice,
        )
        counts = ArticleRepo(session).add_tier1(
            article,
            ttps=[
                NormalizedTTP(t.ttp_id, t.ttp_name, source=t.source, evidence=t.evidence)
                for t in result.techniques
            ],
            # Sama seperti pipeline: huruf kecil lalu `threat_actor_names` (bentuk tersimpan).
            threat_actors=(
                [] if best_practice else threat_actor_names([a.lower() for a in result.actors])
            ),
            malware=result.malware,
            industries=result.industries,
        )
        stats.ttp_rows_added += counts["ttps"]
        stats.actor_rows_added += counts["threat_actors"]
        stats.malware_rows_added += counts["malware"]
        if counts["industries"]:
            stats.industry_replaced += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
        if sleep > 0:
            time.sleep(sleep)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="hitung semua lalu rollback")
    ap.add_argument(
        "--since",
        type=datetime.date.fromisoformat,
        default=None,
        help="cuma artikel dengan posted_on >= tanggal ini (YYYY-MM-DD)",
    )
    ap.add_argument("--limit", type=int, default=None, help="maksimal artikel yang dipindai")
    ap.add_argument("--sleep", type=float, default=0.0, help="jeda detik antar artikel")
    args = ap.parse_args(argv)

    from cti_core.db.engine import sync_session

    with sync_session() as session:
        stats = backfill_tier1(
            session, since=args.since, limit=args.limit, sleep=args.sleep, dry_run=args.dry_run
        )

    mode = "DRY-RUN (di-rollback)" if args.dry_run else "DITULIS"
    print(f"== backfill tier 1 -- {mode}")
    print(f"artikel dipindai   : {stats.scanned}")
    print(f"teks diambil       : {stats.fetched} (gagal/kosong: {stats.fetch_failed})")
    print(f"TTP                : +{stats.ttp_rows_added} baris")
    print(f"threat actor       : +{stats.actor_rows_added} baris")
    print(f"malware/tool       : +{stats.malware_rows_added} baris")
    print(f"industri diganti   : {stats.industry_replaced} artikel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
