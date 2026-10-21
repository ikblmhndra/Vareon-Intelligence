"""Counter berita harian -- gantiin `ScraperNews/supportFile/sendCounter.py` dan
file counter lokal yang ditulis `nlp.py` (`counterAllNews_*.txt`,
`counterRelated_*.txt`, `RELATED_*.txt`, `UNRELATED_*.txt`).

Kode lama menghitung dengan menambah file `.txt` di SETIAP artikel (proses tunggal,
hilang kalau container di-restart, dan skrip pengirim crash kalau salah satu file
belum ada -- hari tanpa artikel related). Sekarang angkanya dihitung dari DB untuk
satu hari LOKAL: `articles` (lolos klasifikasi = related) dan `rejected_articles`
(ditolak klasifikasi = unrelated). Artikel yang GAGAL diproses
(`[enrichment_failed]`, Fase 10.A2) dihitung terpisah -- bukan unrelated.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from cti_core.db.models.article import Article, RejectedArticle
from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_worker.reports.timeutil import local_day_bounds_utc

_FAILED_PREFIX = "[enrichment_failed]"


@dataclass
class DailyCounters:
    day: datetime.date
    related: list[str] = field(default_factory=list)
    unrelated: list[str] = field(default_factory=list)
    failed: int = 0

    @property
    def scraped(self) -> int:
        return len(self.related) + len(self.unrelated) + self.failed

    @property
    def stamp(self) -> str:
        return self.day.strftime("%d_%m_%Y")

    def message(self) -> str:
        text = (
            "\n    === SCRAPED NEWS ALERT ===\n"
            f"Total news scraped on {self.day.strftime('%d %m %Y')}: {self.scraped}\n"
            f"Total unrelated cti news: {len(self.unrelated)}\n"
            f"Total related cti news: {len(self.related)}\n"
        )
        if self.failed:
            text += f"Total gagal diproses (cek Filtered Articles): {self.failed}\n"
        return text

    def files(self) -> dict[str, str]:
        """{nama file: isi} -- yang KOSONG dilewati (kode lama crash / kirim file kosong)."""
        out: dict[str, str] = {}
        if self.unrelated:
            out[f"UNRELATED_{self.stamp}.txt"] = "\n".join(self.unrelated) + "\n"
        if self.related:
            out[f"RELATED_{self.stamp}.txt"] = "\n".join(self.related) + "\n"
        return out


def collect(session: Session, local_day: datetime.date, offset_hours: int) -> DailyCounters:
    start, end = local_day_bounds_utc(local_day, offset_hours)
    related = list(
        session.scalars(
            select(Article.title)
            .where(Article.first_seen_at >= start, Article.first_seen_at < end)
            .order_by(Article.first_seen_at, Article.id)
        )
    )
    counters = DailyCounters(day=local_day, related=related)
    rows = session.execute(
        select(RejectedArticle.title, RejectedArticle.reason, RejectedArticle.failure_kind)
        .where(RejectedArticle.rejected_at >= start, RejectedArticle.rejected_at < end)
        .order_by(RejectedArticle.rejected_at, RejectedArticle.id)
    ).all()
    for title, reason, kind in rows:
        # Prefix ikut dibaca satu rilis: worker lama (rolling deploy) belum menulis `failure_kind`.
        if kind is not None or (reason or "").startswith(_FAILED_PREFIX):
            counters.failed += 1
        else:
            counters.unrelated.append(title)
    return counters
