"""Lapisan sumber data Twitter/X buat scraper Fase 10.E (`tweet_alerts_*`, `trending_cve`).

Ada DUA sumber, dipilih PER-SCRAPER lewat opsi `provider` di control plane
(`ScraperConfig.options`, dropdown di /scrapers -> detail):

  twitterapi.io  (`_twitterapi.py`)  UTAMA (default, dipaksa duluan). Bayar per kredit, free
                                     tier ~1 request/5 dtk.
  X resmi        (`_x_official.py`)  CADANGAN -- dipakai HANYA kalau twitterapi.io memang tidak
                                     bisa (keputusan user 2026-09-27). API v2 pay-per-use:
                                     tiap tweet yang DIBACA ditagih. Pindah MANUAL (tanpa
                                     auto-fallback), lewat dropdown di control plane.

Scraper (`tweet_alerts`, `trending_cve`) tidak tahu sumbernya: mereka menyusun
`TweetSearch` (apa yang dicari, netral) dan menerima `Tweet` (bentuk netral). Tiap adapter
yang menerjemahkan sintaks query dan bentuk respons API-nya masing-masing.

Dedup TIDAK terpengaruh ganti sumber: kuncinya id tweet (`{id}:{topik}`), sama di kedua
API, jadi pindah sumber di tengah jalan tidak bikin alert dobel.

Modul BUKAN scraper (tanpa subclass `BaseScraper`) -- awalan `_` menandai helper internal
paket `collectors`. `monitor_x.py` (Fase 5, tab X Intel) punya klien twitterapi.io sendiri
(per akun, `since_id`, field profil lengkap) dan sengaja tidak ikut dipindah ke sini; sejak
2026-10-16 ia memakai modul ini hanya untuk opsi `provider=x_official`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cti_scraper.base import ConfigError, OptionChoice, ScrapeContext, ScraperOption

if TYPE_CHECKING:
    from collections.abc import Callable

PROVIDER_KEY = "provider"
TWITTERAPI_IO = "twitterapi_io"
X_OFFICIAL = "x_official"


def provider_option(description: str) -> ScraperOption:
    """Opsi `provider` scraper Twitter. `credential` per pilihan: header yang dipasang
    `Runner` ikut sumber yang dipilih (`X-API-Key` vs `Authorization: Bearer`)."""
    return ScraperOption(
        key=PROVIDER_KEY,
        label="Sumber data Twitter/X",
        choices=(
            OptionChoice(TWITTERAPI_IO, "twitterapi.io (utama)", credential="twitter"),
            OptionChoice(X_OFFICIAL, "X API resmi (cadangan, pay-per-use)", credential="x"),
        ),
        default=TWITTERAPI_IO,
        description=description,
    )


ALERTS_PROVIDER_OPTION = provider_option(
    "twitterapi.io = sumber UTAMA dan tetap dipakai selama masih bisa. X resmi = CADANGAN: "
    "pindah ke sana hanya kalau twitterapi.io memang tidak bisa (kunci ditolak, kredit habis, "
    "layanan mati). X resmi pay-per-use: tiap tweet yang dibaca ditagih "
    "(sekitar $0,005/tweet; tweet yang sama di hari UTC yang sama tidak ditagih dua kali). "
    "Pasang batas belanja di X Developer Console."
)

HIGH_VOLUME_PROVIDER_OPTION = provider_option(
    "PERINGATAN BIAYA: scraper ini mencari SEMUA tweet 'CVE-<tahun>-' di seluruh X -- "
    "ribuan tweet per hari. Di X resmi tiap tweet yang dibaca ditagih (sekitar $0,005), jadi "
    "biayanya bisa ratusan dolar per bulan. Sumber utama tetap twitterapi.io; pindah ke X resmi "
    "hanya kalau twitterapi.io memang tidak bisa."
)


@dataclass(frozen=True, slots=True)
class Tweet:
    """Satu tweet dalam bentuk netral (apa pun sumbernya)."""

    id: str
    text: str
    username: str
    """Tanpa `@`. Kosong kalau sumber tidak menyebutkannya."""
    created_at: datetime.datetime | None
    """Naive UTC (konvensi `ScrapeContext.now`); `None` kalau tidak terbaca."""
    url: str
    links: tuple[str, ...] = ()
    """URL hasil expand yang ada di isi tweet."""
    is_reply: bool = False
    author_name: str | None = None
    author_avatar: str | None = None
    author_followers: int | None = None
    lang: str | None = None
    media_urls: tuple[str, ...] = ()
    """Profil penulis, bahasa, dan media -- hanya yang disediakan sumbernya (twitterapi.io: semua;
    X resmi: nama, avatar, followers, lang; tanpa media). Dipakai `tweet_alerts` untuk menyimpan
    tweet ke `tweets` (tab X Intel); `None`/kosong = sumber tidak menyediakan."""


@dataclass(frozen=True, slots=True)
class TweetSearch:
    """Apa yang dicari, netral. Retweet dan balasan SELALU dikecualikan."""

    since: datetime.datetime
    """Naive UTC. Cuma tweet yang lebih baru dari ini."""
    accounts: tuple[str, ...] = ()
    """Kalau diisi: hanya tweet DARI akun-akun ini (digabung jadi SATU query)."""
    keyword: str = ""
    exclude_quotes: bool = False
    with_author: bool = True
    """Perlu username penulis? `False` = tweet tanpa username (`Tweet.username` kosong, URL
    `x.com/i/status/<id>`). Di X resmi username butuh `expansions=author_id`, dan objek user
    yang ikut dikirim kemungkinan ditagih terpisah (lookup user ~$0,01 per user unik per hari)
    -- scraper yang cuma butuh id/isi tweet (`trending_cve`, ribuan tweet/hari) mematikannya.
    twitterapi.io selalu menyertakan penulis, jadi flag ini tak berpengaruh di sana."""


def search(ctx: ScrapeContext, spec: TweetSearch) -> list[Tweet]:
    """Cari lewat sumber yang dipilih (`ctx.options["provider"]`, default twitterapi.io).
    Error API = `ParseError`/`TransientFetchError` -- TIDAK PERNAH "nol tweet" diam-diam."""
    return _adapter(ctx.options.get(PROVIDER_KEY, TWITTERAPI_IO))(ctx, spec)


def _adapter(provider: str) -> Callable[[ScrapeContext, TweetSearch], list[Tweet]]:
    # Import di sini (bukan di atas): adapter mengimpor tipe dari modul ini.
    if provider == TWITTERAPI_IO:
        from cti_scrapers.collectors import _twitterapi

        return _twitterapi.search
    if provider == X_OFFICIAL:
        from cti_scrapers.collectors import _x_official

        return _x_official.search
    raise ConfigError(f"sumber Twitter '{provider}' tidak dikenal")


def by_id(tweets: list[Tweet]) -> list[Tweet]:
    """Terlama dulu (id tweet naik = waktu naik) -- notice terkirim urut kronologis."""
    return sorted(tweets, key=lambda t: int(t.id))
