"""Pengumpul mention CVE di tweet -- separuh pertama `TwitterScrap/trendingCve.py`
(tiap 15 menit); separuh kedua (laporan "Top CVE 6 jam") adalah task beat
`report.trending_cve` (`apps/worker/.../tasks/reports.py`).

Skrip lama menyatukan keduanya: tiap run mengumpulkan, dan run di menit 0 pada jam
kelipatan 6 juga melapor lalu mengosongkan `offset/existCve.json`. Dipisah karena
laporan itu tugas periodik biasa (dan gagal-kirim tidak boleh menghilangkan
hitungan), sedangkan pengumpulan adalah scraper (dedup, health, control plane).

Perbedaan dari skrip lama:
  - Pencarian `CVE-<tahun>-`, jendela 30 menit (2x interval) dan dedup id tweet oleh
    framework -- ganti kursor `since_id` di file. Sumber: twitterapi.io (default) atau API
    resmi X via opsi `provider` (lihat `_twitter.py`) -- di X resmi scraper ini MAHAL
    (semua tweet "CVE-<tahun>-" di seluruh X ditagih per tweet), makanya default-nya tidak
    pindah.
  - Tweet yang menyebut CVE yang sama dua kali dihitung sekali (sama dengan lama).
  - `-filter:quote` bersama `-is:retweet -filter:replies` (padanan `-is:retweet -is:reply
    -is:quote`); sintaks divalidasi langsung ke twitterapi.io.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import CveMentionItem

from cti_scrapers.collectors import _twitter as tw

_RE_CVE = re.compile(r"CVE-\d{4}-\d{1,}", re.IGNORECASE)
_WINDOW = datetime.timedelta(minutes=30)


class TrendingCve(BaseScraper):
    meta = ScraperMeta(
        id="trending_cve",
        content_kind="social",
        source="X/Twitter CVE Trending",
        schedule="*/15 * * * *",
        rate_limit="10/minute",
        credential="twitter",
        options=(tw.HIGH_VOLUME_PROVIDER_OPTION,),
        max_items=200,
        dedup_ttl_days=3,  # id tweet cuma relevan selama jendela pencarian; jangan menumpuk 180 hari
        tags=("migrated", "bespoke", "twitter", "cve"),
        legacy_script="trendingCve",
    )

    def fetch(self, ctx: ScrapeContext) -> Iterator[CveMentionItem]:
        spec = tw.TweetSearch(
            since=ctx.now - _WINDOW,
            keyword=f"CVE-{ctx.now.year}-",
            exclude_quotes=True,
            with_author=False,  # cuma id + isi + URL yang dipakai; hemat tagihan user di X resmi
        )

        found = 0
        for tweet in tw.by_id(tw.search(ctx, spec)):
            if found >= self.meta.max_items:
                return
            cve_ids = list(dict.fromkeys(m.upper() for m in _RE_CVE.findall(tweet.text)))
            if not cve_ids:
                continue
            found += 1
            yield CveMentionItem(tweet_id=tweet.id, cve_ids=cve_ids, url=tweet.url)
