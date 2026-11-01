"""Laporan mingguan "Top 5 threat actor" -- gantiin PASANGAN job Rundeck
`threatactorTrendGraylog` + `threatactorTrendTelegram` (`ScraperNews/threatActorTrend*.py`).

Cara lama: `nlp.py` menulis nama grup tiap artikel ke `supportFile/ThreatActorName.txt`;
job pertama menembakkan isi file itu ke Graylog Cloud sebagai log lalu mengosongkannya;
job kedua bertanya ke Graylog (7 hari terakhir vs 7 hari sebelumnya) dan mengirim
peringkatnya ke Telegram. Graylog cuma dipakai sebagai penyimpan deret waktu.

Sekarang datanya SUDAH ada di Postgres (mention aktor `entity_mentions` + `articles.first_seen_at`),
jadi peringkat dihitung langsung: tanpa Graylog, tanpa file lokal (yang hilang kalau
container di-restart dan bisa kehilangan baris yang ditulis di antara baca dan kosongkan),
tanpa dua token hardcoded.

Sama dengan lama:
  - dua jendela bergulir 7 hari yang berakhir di waktu jalan (bukan pekan kalender);
  - peringkat = jumlah artikel yang menyebut grup itu di pekan ini (5 teratas), lalu tiap
    baris dibandingkan dengan pekan sebelumnya: naik / turun / tidak ada perubahan / baru
    muncul. Judul laporan tetap "BY GROWTH" walau urutannya menurut jumlah, seperti lama.
  - satu artikel yang menyebut satu grup dihitung SEKALI (skrip lama: `set()` per baris).

Beda:
  - nama grup digabung tanpa membedakan huruf besar/kecil (Graylog membedakannya, jadi
    "APT41" dan "Apt41" dulu terhitung dua grup); ditampilkan dengan ejaan yang paling
    sering muncul. Sejak P7c nama = nama entitas, jadi alias satu aktor ("APT36" dan
    "Transparent Tribe") sudah satu grup; aktor suppressed/tombstone tidak ikut;
  - "Baru muncul" tidak lagi memakai persen (lama: jumlah x 100, angka tanpa arti, dan
    tanda kurung penutup berlebih);
  - pekan tanpa satu pun grup -> tidak ada pesan (lama: pesan berisi judul saja);
  - nama grup di-escape karena pesan Telegram berformat HTML.
"""

from __future__ import annotations

import datetime
import html
from collections import Counter
from dataclasses import dataclass

from cti_core.db.models.article import Article
from cti_core.db.repositories.entity import ACTOR, mention_rows
from sqlalchemy import select
from sqlalchemy.orm import Session

TOP_N = 5
WINDOW_DAYS = 7

HEADER = "=== <b>TOP 5 WEEKLY THREAT ACTORS BY GROWTH (%)</b> ==="


@dataclass(frozen=True)
class ActorTrend:
    actor: str
    current: int
    previous: int

    @property
    def growth_pct(self) -> float | None:
        """`None` = tidak ada pembanding (pekan lalu nol)."""
        if self.previous == 0:
            return None
        return (self.current - self.previous) / self.previous * 100

    def line(self) -> str:
        name = html.escape(self.actor)
        pct = self.growth_pct
        if pct is None:
            verdict = "Baru muncul"
        elif pct > 0:
            verdict = f"Naik, {pct:.2f}%"
        elif pct < 0:
            verdict = f"Turun, {abs(pct):.2f}%"
        else:
            verdict = "Tidak ada perubahan"
        return f"- {name}: {self.previous} -> {self.current} ({verdict})"


@dataclass(frozen=True)
class TrendReport:
    rows: list[ActorTrend]

    def message(self) -> str:
        return "\n".join([HEADER, *(r.line() for r in self.rows)])


def _counts(
    session: Session, start: datetime.datetime, end: datetime.datetime
) -> dict[str, tuple[str, int]]:
    """`{nama_kecil: (ejaan_tampil, jumlah_artikel)}` untuk artikel yang pertama kali terlihat
    di [start, end). Satu artikel dihitung SEKALI per grup walau menyebut dua ejaan ("APT41"
    dan "Apt41"). Ejaan tampil = yang paling sering; seri -> urutan abjad paling awal."""
    a = mention_rows(ACTOR)
    rows = session.execute(
        select(a.c.article_id, a.c.name)
        .join(Article, Article.id == a.c.article_id)
        .where(Article.first_seen_at >= start, Article.first_seen_at < end)
    ).all()

    articles: dict[str, set[int]] = {}
    spellings: dict[str, Counter[str]] = {}
    for article_id, actor in rows:
        lowered = actor.lower()
        articles.setdefault(lowered, set()).add(article_id)
        spellings.setdefault(lowered, Counter())[actor] += 1
    return {
        lowered: (min(seen, key=lambda name: (-seen[name], name)), len(articles[lowered]))
        for lowered, seen in spellings.items()
    }


def collect(session: Session, as_of: datetime.datetime, *, top: int = TOP_N) -> TrendReport | None:
    """Jendela [as_of-7 hari, as_of) vs [as_of-14 hari, as_of-7 hari). `None` kalau pekan ini
    tidak ada satu pun grup. `as_of` aware (UTC)."""
    week = datetime.timedelta(days=WINDOW_DAYS)
    current = _counts(session, as_of - week, as_of)
    if not current:
        return None
    previous = _counts(session, as_of - 2 * week, as_of - week)

    ranked = sorted(current.items(), key=lambda kv: (-kv[1][1], kv[0]))[:top]
    return TrendReport(
        rows=[
            ActorTrend(spelling, count, previous.get(lowered, ("", 0))[1])
            for lowered, (spelling, count) in ranked
        ]
    )
