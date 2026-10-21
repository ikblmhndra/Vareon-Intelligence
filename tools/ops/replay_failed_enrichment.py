#!/usr/bin/env python3
"""Kirim ulang artikel yang GAGAL di-enrich (`rejected_articles.failure_kind`) ke antrian.

Kasus dev 2026-10-16: model LLM salah (`Unsupported model mimo-auto`) membuat 101 artikel gagal
final dan masuk `rejected_articles`; tombol Restore tidak me-re-queue pipeline (ia hanya membuat
artikel "Manually Restored" tanpa enrichment), jadi tidak ada jalan pulang selain tool ini
(ROADMAP #24). Tiap baris dikirim ke `enrich.article` dengan lima argumen yang sama seperti sink
scraper; kalau sukses, pipeline menghapus baris gagalnya sendiri, kalau ditolak klasifikasi barisnya
jadi penolakan biasa, kalau gagal lagi barisnya tetap (dan alert kegagalan berbunyi lagi).

Pengaman:
  - PASTIKAN LLM-nya sehat dulu (`tools/llm/probe_json.py`, atau halaman Admin > Third-party Keys):
    replay saat LLM masih rusak hanya menghasilkan kegagalan yang sama.
  - URL yang SUDAH jadi artikel dilewati (`skip_article_exists`). Artikel stub "Manually Restored"
    (analis menekan Restore) juga dilewati (`stub_restored`): pipeline akan berhenti di
    `_known_article` dan replay diam-diam tidak melakukan apa pun. `--replace-restored-stubs`
    menghapus stub itu dulu (stub tidak punya enrichment; baris anaknya ikut terhapus).
  - Antrian `enrich` dicek tiap kiriman (`ensure_enrich_capacity`); penuh = berhenti dan lapor.
  - `--rate` (default 20 per menit) menjaga worker-nlp (10-13 detik + LLM per artikel) dan kuota.
  - Secara default replay SENYAP: artikel tidak memicu alert Telegram (beritanya sudah basi).
    `--alerts` mengaktifkan alert normal.

DEFAULT-nya laporan saja (tidak mengirim apa pun). `--apply` baru mengirim. Idempoten, aman diulang.

Dari host (dev):
    uv run python tools/ops/replay_failed_enrichment.py --kind permanent
    uv run python tools/ops/replay_failed_enrichment.py --since 2026-10-16 --limit 20 --apply

Di server: `make replay-failed-enrichment ARGS='--since 2026-10-16 --apply'` (Makefile).
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

STUB_NEWS_TYPE = "Manually Restored"
Action = Literal["enqueue", "replace_stub", "stub_restored", "skip_article_exists"]


@dataclass(frozen=True)
class Row:
    """Kolom `rejected_articles` yang dipakai (bukan ORM -- biar bisa diuji tanpa DB)."""

    id: int
    url: str
    title: str
    source: str
    scraper_id: str | None
    posted_on: datetime.date | None
    failure_kind: str
    article_news_type: str | None  # None = belum ada artikel dengan URL ini


def decide(row: Row, *, replace_stubs: bool) -> Action:
    if row.article_news_type is None:
        return "enqueue"
    if row.article_news_type == STUB_NEWS_TYPE:
        return "replace_stub" if replace_stubs else "stub_restored"
    return "skip_article_exists"


def plan(rows: Iterable[Row], *, replace_stubs: bool = False) -> dict[Action, list[Row]]:
    """Kelompokkan baris per aksi. Murni -- tidak menyentuh DB maupun antrian."""
    grouped: dict[Action, list[Row]] = {
        "enqueue": [],
        "replace_stub": [],
        "stub_restored": [],
        "skip_article_exists": [],
    }
    for row in rows:
        grouped[decide(row, replace_stubs=replace_stubs)].append(row)
    return grouped


def enqueue_all(
    rows: Sequence[Row],
    *,
    rate_per_min: float,
    replay: bool,
    send: Callable[[Row, bool], None],
    check_capacity: Callable[[], None],
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Kirim satu per satu dengan jeda `60 / rate`. `check_capacity` yang melempar (antrian penuh)
    menghentikan pengiriman: yang sudah terkirim tetap terkirim, sisanya aman dijalankan ulang."""
    sent = 0
    for row in rows:
        check_capacity()
        send(row, replay)
        sent += 1
        sleep(60.0 / rate_per_min)
    return sent


def load_rows(
    session: Session,
    *,
    kind: str | None = None,
    since: datetime.date | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[Row]:
    from cti_core.db.models.article import Article, RejectedArticle
    from sqlalchemy import select

    stmt = (
        select(
            RejectedArticle.id,
            RejectedArticle.url,
            RejectedArticle.title,
            RejectedArticle.source,
            RejectedArticle.scraper_id,
            RejectedArticle.posted_on,
            RejectedArticle.failure_kind,
            Article.news_type,
        )
        .outerjoin(Article, Article.url_hash == RejectedArticle.url_hash)
        .where(RejectedArticle.failure_kind.is_not(None))
        .order_by(RejectedArticle.rejected_at, RejectedArticle.id)
    )
    if kind:
        stmt = stmt.where(RejectedArticle.failure_kind == kind)
    if since:
        stmt = stmt.where(RejectedArticle.rejected_at >= since)
    if source:
        stmt = stmt.where(RejectedArticle.source == source)
    if limit:
        stmt = stmt.limit(limit)
    return [Row(*r) for r in session.execute(stmt)]


def delete_stubs(session: Session, rows: Iterable[Row]) -> int:
    """Hapus artikel stub "Manually Restored" supaya pipeline tidak berhenti di `_known_article`."""
    from cti_core.db.models.article import Article
    from cti_core.urlkit import url_hash
    from sqlalchemy import delete

    done = 0
    for row in rows:
        result = session.execute(
            delete(Article).where(
                Article.url_hash == url_hash(row.url), Article.news_type == STUB_NEWS_TYPE
            )
        )
        done += result.rowcount or 0
    session.commit()
    return done


def render(row: Row, action: Action) -> str:
    return f"{action.upper():<20} {row.failure_kind:<10} {row.source:<22} {row.url}"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="kirim ke antrian (default: laporan saja)")
    ap.add_argument("--kind", choices=["transient", "json", "permanent"], default=None)
    ap.add_argument("--since", type=datetime.date.fromisoformat, default=None, help="YYYY-MM-DD")
    ap.add_argument("--source", default=None, help="hanya satu sumber (nama persis)")
    ap.add_argument("--limit", type=int, default=None, help="maksimum baris")
    ap.add_argument("--rate", type=float, default=20.0, help="kiriman per menit (default 20)")
    ap.add_argument("--alerts", action="store_true", help="aktifkan alert Telegram normal")
    ap.add_argument(
        "--replace-restored-stubs",
        action="store_true",
        help='hapus artikel stub "Manually Restored" lalu kirim ulang',
    )
    args = ap.parse_args(argv)
    if args.rate <= 0:
        ap.error("--rate harus > 0")

    from cti_core.celery_client import send_enrich_task
    from cti_core.db.engine import get_sync_engine
    from cti_scraper.sinks import BackpressureError, ensure_enrich_capacity
    from sqlalchemy.orm import Session

    with Session(get_sync_engine()) as session:
        rows = load_rows(
            session, kind=args.kind, since=args.since, source=args.source, limit=args.limit
        )
        grouped = plan(rows, replace_stubs=args.replace_restored_stubs)
        for action, items in grouped.items():
            if action != "enqueue":  # yang lancar tidak perlu dicetak satu-satu
                for row in items[:20]:
                    print(render(row, action))
        by_kind = Counter(r.failure_kind for r in rows)
        print(
            f"\n{len(rows)} baris gagal ({dict(by_kind)}) -> kirim: {len(grouped['enqueue'])} | "
            f"hapus stub lalu kirim: {len(grouped['replace_stub'])} | stub Restore dilewati: "
            f"{len(grouped['stub_restored'])} | sudah jadi artikel (dilewati): "
            f"{len(grouped['skip_article_exists'])}"
        )
        if not args.apply:
            print("LAPORAN SAJA -- tidak ada yang dikirim. Pastikan LLM sehat, lalu --apply.")
            return 0

        if grouped["replace_stub"]:
            print(f"Menghapus {delete_stubs(session, grouped['replace_stub'])} artikel stub ...")
        to_send = grouped["enqueue"] + grouped["replace_stub"]
        try:
            sent = enqueue_all(
                to_send,
                rate_per_min=args.rate,
                replay=not args.alerts,
                send=lambda r, replay: send_enrich_task(
                    title=r.title,
                    url=r.url,
                    posted_on=r.posted_on,
                    source=r.source,
                    scraper_id=r.scraper_id,
                    replay=replay,
                ),
                check_capacity=ensure_enrich_capacity,
            )
        except BackpressureError as e:
            print(f"BERHENTI: {e}. Jalankan ulang setelah antrian surut.")
            return 1
        print(f"Selesai: {sent} artikel dikirim ke antrian enrich.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
