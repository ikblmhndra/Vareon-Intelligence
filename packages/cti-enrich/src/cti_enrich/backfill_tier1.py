"""Backfill Tier 1 (ekstraktor deterministik P4) untuk artikel yang SUDAH tersimpan.

Untuk tiap artikel: ambil ulang teks penuh (`fetch_text`), jalankan `run_tier1`, lalu tambahkan
TTP / threat actor / malware / industri yang belum ada lewat `ArticleRepo.add_tier1`. Murni
ADD-ONLY: baris hasil LLM tidak pernah diubah atau dihapus, dan `raw_enrichment` sengaja tidak
disentuh (jejak `tier1` hanya ditulis pipeline untuk artikel baru) supaya perintah ini aman
diulang. Tanpa LLM dan tanpa alert.

Aktor kanonik tidak ditambah bila artikel sudah punya baris aktor yang lewat kamus yang sama
resolve ke canonical yang sama (Ruling 17): baris lama "Lazarus" (alias) + Tier 1 "Lazarus Group"
-> tidak ada baris baru. Baris lama tidak ditulis ulang ke nama kanonik.

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
from cti_enrich.stages.tier1 import get_dictionary, run_tier1
from cti_enrich.tier1.dictionary import EntityDictionary

log = structlog.get_logger()


@dataclass
class Tier1BackfillStats:
    scanned: int = 0
    fetched: int = 0
    fetch_failed: int = 0
    errored: int = 0
    """Artikel yang gagal di tengah jalan (tier 1/DB/commit): di-rollback, run lanjut."""
    ttp_rows_added: int = 0
    actor_rows_added: int = 0
    malware_rows_added: int = 0
    industry_replaced: int = 0
    """Jumlah ARTIKEL yang industri "General"-nya diganti tebakan keyword."""


def canonical_actor_name(name: str, dictionary: EntityDictionary) -> str | None:
    """Bentuk simpan canonical kamus untuk nama aktor tersimpan (alias -> nama kanonik), atau
    None bila nama tidak ada di kamus atau bukan aktor (malware/tool). Bentuk simpan =
    `capitalize()`, jadi key kamus case-sensitive (alias huruf kapital semua, mis. "NOBELIUM")
    dicoba juga lewat `upper()`. Dipakai juga `cti_enrich.canonicalise_actors`."""
    entries = dictionary.entries
    entity = entries.get(name) or entries.get(name.lower()) or entries.get(name.upper())
    if entity is None or entity.kind != "actor":
        return None
    return threat_actor_names([entity.canonical.lower()])[0]


def _known_actor_names(article: Article, dictionary: EntityDictionary) -> set[str]:
    """Bentuk simpan canonical dari aktor yang sudah dimiliki artikel; aktor Tier 1 di set ini
    dilewati. Nama yang persis sama sudah dilewati `add_tier1`."""
    known: set[str] = set()
    for row in article.threat_actors:
        canonical = canonical_actor_name(row.threat_actor, dictionary)
        if canonical is not None:
            known.add(canonical)
    return known


def _new_actors(article: Article, actors: list[str], session: Session) -> list[str]:
    # Sama seperti pipeline: huruf kecil lalu `threat_actor_names` (bentuk tersimpan).
    known = _known_actor_names(article, get_dictionary(session))
    return [n for n in threat_actor_names([a.lower() for a in actors]) if n not in known]


def _process(
    session: Session,
    article_id: int,
    stats: Tier1BackfillStats,
    *,
    dry_run: bool,
    fetch: Callable[[str], str],
) -> None:
    article = session.get(Article, article_id)
    if article is None:
        return
    try:
        text = fetch(article.url)
    except Exception as exc:
        log.warning("tier1_backfill_fetch_failed", article_id=article_id, error=str(exc))
        text = ""
    if not text:
        stats.fetch_failed += 1
        session.rollback()
        return
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
        threat_actors=_new_actors(article, result.actors, session) if not best_practice else [],
        malware=result.malware,
        industries=result.industries,
    )
    if dry_run:
        session.rollback()
    else:
        session.commit()
    # Statistik baru dihitung setelah commit/rollback sukses, supaya artikel yang gagal
    # tidak ikut terhitung.
    stats.ttp_rows_added += counts["ttps"]
    stats.actor_rows_added += counts["threat_actors"]
    stats.malware_rows_added += counts["malware"]
    if counts["industries"]:
        stats.industry_replaced += 1


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
        stats.scanned += 1
        try:
            _process(session, article_id, stats, dry_run=dry_run, fetch=fetch)
        except Exception as exc:
            # Satu artikel bermasalah (run_tier1, constraint, commit) tidak boleh membuang
            # ringkasan seluruh run: batalkan artikel itu saja lalu lanjut.
            session.rollback()
            stats.errored += 1
            log.warning("tier1_backfill_article_failed", article_id=article_id, error=str(exc))
        finally:
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
    print(f"artikel error      : {stats.errored}")
    print(f"TTP                : +{stats.ttp_rows_added} baris")
    print(f"threat actor       : +{stats.actor_rows_added} baris")
    print(f"malware/tool       : +{stats.malware_rows_added} baris")
    print(f"industri diganti   : {stats.industry_replaced} artikel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
