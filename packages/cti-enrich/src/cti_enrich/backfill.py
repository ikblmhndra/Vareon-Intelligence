"""Backfill enrichment artikel yang SUDAH tersimpan -- nutup dua bug QA staging
2026-10-01 tanpa manggil LLM atau ngirim alert apa pun:

1. **Threat actor** (BUG-B2/D1): `threat_actor_groups` kosong di staging (gak
   pernah ikut seed cutover), jadi `stages/score.py` gak pernah nemu TA dan
   0 dari 325 artikel punya `article_threat_actors`. Setelah tabel itu
   di-seed (`tools/seed/fase10_reference_data.py`), backfill ini nyocokin
   kamus grup ke JUDUL artikel lama.

   Keterbatasan (sadar): pipeline asli juga nyocokin ke ringkasan + entitas
   NER, tapi ringkasan GAK disimpan di `articles` -- jadi artikel lama cuma
   dapat TA yang disebut di judul. Artikel baru (setelah seed) dapat semua.
   `news_type` gak diubah: cabang routing yang berubah karena TA ketemu
   (Global -> TA Group, Regional -> Regional+TA) menghasilkan `news_type`
   yang sama (lihat `routing.route`), dan alert gak dikirim ulang.
   Artikel "Security Technology & Best Practices" dilewati -- jalur itu
   memang gak pernah di-score (`pipeline.py`), sama kayak kode lama.

2. **Negara `mentioned`** (BUG-D4, Risk Matrix 0 sel): `stages/persist.py`
   dulu cuma nulis sisa negara regex sebagai `mentioned`, bukan gabungan
   regex + victim + actor kayak `mentioned_countries` lama. Backfill
   nambahin baris `mentioned` untuk setiap negara `victim`/`actor` yang
   belum punya.

Cuma MENAMBAH mention (`entity_mentions`, P7c; gak pernah menghapus), idempoten -- aman diulang.
Aktor yang alias-nya sudah tersebut di artikel resolve ke entitas yang sama, jadi tidak ditambah.

    python -m cti_enrich.backfill --dry-run            # hitung saja, rollback
    python -m cti_enrich.backfill [--since 2026-09-01]
"""

from __future__ import annotations

import argparse
import datetime
import sys
from dataclasses import dataclass, field

from cti_core.db.models.article import Article
from cti_core.db.repositories.article import ArticleRepo
from cti_core.db.repositories.threat_reference import list_threat_actor_groups
from cti_core.entity.mentions import MentionInput, country_mention
from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_enrich.routing import threat_actor_names
from cti_enrich.stages.score import NamePatterns, compile_name_patterns, match_names

BEST_PRACTICE_NEWS_TYPE = "Security Technology & Best Practices"
"""`news_type` jalur `security_tech_best_practice` di `pipeline.py` -- tanpa score."""


class BackfillError(RuntimeError):
    """Prasyarat backfill belum terpenuhi -- berhenti, jangan nulis apa pun."""


@dataclass
class BackfillStats:
    scanned: int = 0
    articles_with_new_actors: int = 0
    actor_rows_added: int = 0
    articles_with_new_mentioned: int = 0
    mentioned_rows_added: int = 0
    samples: list[tuple[int, str, list[str]]] = field(default_factory=list)
    """(id, judul, TA baru) -- beberapa contoh buat dicek manusia."""


def backfill_articles(
    session: Session,
    *,
    since: datetime.date | None = None,
    batch_size: int = 500,
    sample_limit: int = 20,
) -> BackfillStats:
    """Cuma `flush()` -- commit/rollback urusan caller (lihat `main`)."""
    groups = list_threat_actor_groups(session)
    if not groups:
        raise BackfillError(
            "tabel `threat_actor_groups` kosong -- jalankan seed dulu "
            "(tools/seed/fase10_reference_data.py), kalau gak backfill TA gak nemu apa pun"
        )
    patterns = compile_name_patterns(groups)

    stats = BackfillStats()
    last_id = 0
    while True:
        stmt = select(Article).where(Article.id > last_id).order_by(Article.id).limit(batch_size)
        if since is not None:
            stmt = stmt.where(Article.posted_on >= since)
        batch = list(session.execute(stmt).scalars())
        if not batch:
            break
        for article in batch:
            stats.scanned += 1
            _backfill_threat_actors(session, article, patterns, stats, sample_limit)
            _backfill_mentioned_countries(session, article, stats)
        last_id = batch[-1].id
        session.flush()
        session.expunge_all()  # artikel batch ini udah ke-flush; jaga memori tetap kecil
    return stats


def _backfill_threat_actors(
    session: Session,
    article: Article,
    patterns: NamePatterns,
    stats: BackfillStats,
    sample_limit: int,
) -> None:
    if article.news_type == BEST_PRACTICE_NEWS_TYPE:
        return
    found = threat_actor_names(
        [g.replace("\\-", "-") for g in match_names(patterns, article.title or "")]
    )
    have = {n.lower() for n in article.entity_names("intrusion-set")}
    new = [name for name in found if name.lower() not in have]
    if not new:
        return
    # alias dari entitas yang sudah disebut -> resolve ke entitas yang sama -> tidak ditambah
    added = ArticleRepo(session).add_mentions(
        article, [MentionInput("intrusion-set", name, "dictionary", name) for name in new]
    )
    if not added:
        return
    ArticleRepo(session).touch_entity_seen(article)  # first/last seen entitas (P7c)
    stats.articles_with_new_actors += 1
    stats.actor_rows_added += added
    if len(stats.samples) < sample_limit:
        stats.samples.append((article.id, article.title, new))


def _backfill_mentioned_countries(session: Session, article: Article, stats: BackfillStats) -> None:
    countries = article.mentions_of("location")
    mentioned = {m.entity_id for m in countries if m.role == "mentioned"}
    missing = list(
        dict.fromkeys(
            m.entity.external_id or m.matched_alias
            for m in countries
            if m.role in ("victim", "actor") and m.entity_id not in mentioned
        )
    )
    if not missing:
        return
    added = ArticleRepo(session).add_mentions(
        article,
        [h for code in missing if (h := country_mention(code, "mentioned", "llm"))],
    )
    if not added:
        return
    ArticleRepo(session).touch_entity_seen(article)  # first/last seen entitas (P7c)
    stats.articles_with_new_mentioned += 1
    stats.mentioned_rows_added += added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="hitung semua lalu rollback")
    ap.add_argument(
        "--since",
        type=datetime.date.fromisoformat,
        default=None,
        help="cuma artikel dengan posted_on >= tanggal ini (YYYY-MM-DD)",
    )
    ap.add_argument("--batch-size", type=int, default=500)
    args = ap.parse_args(argv)

    from cti_core.db.engine import sync_session

    try:
        with sync_session() as session:
            stats = backfill_articles(session, since=args.since, batch_size=args.batch_size)
            if args.dry_run:
                session.rollback()
    except BackfillError as e:
        print(f"GAGAL, tidak ada yang ditulis: {e}", file=sys.stderr)
        return 1

    mode = "DRY-RUN (di-rollback)" if args.dry_run else "DITULIS"
    print(f"== backfill enrichment artikel -- {mode}")
    print(f"artikel dipindai              : {stats.scanned}")
    print(
        f"threat actor                  : +{stats.actor_rows_added} baris "
        f"di {stats.articles_with_new_actors} artikel"
    )
    print(
        f"negara role=mentioned         : +{stats.mentioned_rows_added} baris "
        f"di {stats.articles_with_new_mentioned} artikel"
    )
    for article_id, title, names in stats.samples:
        print(f"  #{article_id} {', '.join(names)}  <- {title[:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
