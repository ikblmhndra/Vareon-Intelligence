"""Backfill story untuk artikel yang SUDAH tersimpan sebelum P3 -- mengelompokkan berita sama
jadi `stories` dengan resolver yang sama persis seperti pipeline live
(`cti_enrich.story.resolver`), tanpa LLM dan tanpa alert.

Cara kerja: artikel tanpa `story_id` diurut `(first_seen_at, id)`, CVE kuncinya dari
`article_cves` (`key_cves`, batas yang sama dengan pipeline). Tiap artikel masuk story yang
cocok (`story_match` = aturan) atau membuka story baru (`story_match` = "lead"). Hanya
`stories`, `articles.story_id` dan `articles.story_match` yang ditulis; `stories.classify`
dibiarkan NULL (diisi anggota berikutnya yang lolos klasifikasi LLM). Idempoten: artikel yang
sudah punya `story_id` dilewati.

Keterbatasan (sadar): kandidat in-memory dimulai KOSONG tiap run, story yang dibuat pipeline
live tidak dimuat. Jalankan sebelum story live menumpuk (atau terima bahwa artikel lama dan
story live bisa tidak bertemu).

    python -m cti_enrich.story_backfill --dry-run            # hitung saja, rollback
    python -m cti_enrich.story_backfill [--since 2026-09-01]
"""

from __future__ import annotations

import argparse
import datetime
from dataclasses import dataclass, field

from cti_core.config import get_settings
from cti_core.db.models.article import Article
from cti_core.db.repositories.article_cve import ArticleCveRepo
from cti_core.db.repositories.story import StoryCandidate, StoryMember, StoryRepo
from sqlalchemy import Date as SqlDate
from sqlalchemy import cast, select
from sqlalchemy.orm import Session

from cti_enrich.story.resolver import ArticleKeys, key_cves, resolve

TOP_STORIES = 10


@dataclass
class BackfillReport:
    stories: int = 0
    followups: int = 0
    top: list[tuple[int, int]] = field(default_factory=list)
    """(story_id, jumlah anggota) -- 10 story terbesar, terbesar dulu."""


def backfill(session: Session, *, since: datetime.date | None, dry_run: bool) -> BackfillReport:
    """Tulis di dalam savepoint: `dry_run` membatalkannya, selain itu commit urusan caller."""
    cfg = get_settings().story
    stories = StoryRepo(session)
    cves = ArticleCveRepo(session)

    stmt = (
        select(Article.id, Article.title, Article.source, Article.first_seen_at)
        .where(Article.story_id.is_(None))
        .order_by(Article.first_seen_at, Article.id)
    )
    if since is not None:
        stmt = stmt.where(cast(Article.first_seen_at, SqlDate) >= since)
    rows = session.execute(stmt).all()
    article_cves = cves.cve_ids_by_article([r.id for r in rows])

    report = BackfillReport()
    members: dict[int, int] = {}
    candidates: dict[int, StoryCandidate] = {}
    savepoint = session.begin_nested()
    for article_id, title, source, at in rows:
        key = key_cves(article_cves.get(article_id, set()), cfg.max_key_cves)
        match = resolve(
            ArticleKeys(title=title, source=source, cve_ids=key, at=at),
            list(candidates.values()),
            cfg,
        )
        if match is None:
            story_id = stories.create(title=title, source=source, cve_ids=set(key), now=at)
            rule = "lead"
            report.stories += 1
            prev = None
        else:
            story_id, rule = match.story_id, match.rule
            report.followups += 1
            prev = candidates[story_id]

        session.execute(
            Article.__table__.update()
            .where(Article.id == article_id)
            .values(story_id=story_id, story_match=rule)
        )
        stories.attach(story_id, article_id=article_id, cve_ids=set(key), now=at, classify=None)

        members[story_id] = members.get(story_id, 0) + 1
        member = StoryMember(title=title, source=source)
        candidates[story_id] = StoryCandidate(
            id=story_id,
            cve_ids=(prev.cve_ids | key) if prev else key,
            first_seen_at=prev.first_seen_at if prev else at,
            last_seen_at=max(prev.last_seen_at, at) if prev else at,
            members=[*prev.members, member] if prev else [member],
            has_classify=False,
        )

    report.top = sorted(members.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_STORIES]
    if dry_run:
        savepoint.rollback()
    else:
        savepoint.commit()
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="hitung semua lalu rollback")
    ap.add_argument(
        "--since",
        type=datetime.date.fromisoformat,
        default=None,
        help="cuma artikel dengan first_seen_at >= tanggal ini (YYYY-MM-DD)",
    )
    args = ap.parse_args(argv)

    from cti_core.db.engine import sync_session

    with sync_session() as session:
        report = backfill(session, since=args.since, dry_run=args.dry_run)
        if args.dry_run:
            session.rollback()

    mode = "DRY-RUN (di-rollback)" if args.dry_run else "DITULIS"
    print(f"== backfill story -- {mode}")
    print(f"story baru                    : {report.stories}")
    print(f"follow-up (menempel ke story) : {report.followups}")
    for story_id, count in report.top:
        print(f"  story #{story_id}: {count} artikel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
