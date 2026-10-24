"""Alert tweet ke Telegram -- gantiin `TwitterScrap/twitter.py` (tiap jam) dan
`twitter30.py` (tiap :30): dua skrip yang 495 dari 498 barisnya IDENTIK, cuma beda
daftar akun (`usernames_1hour.txt` / `usernames_130hour.txt`).

Bedakan dari `monitor_x` (Fase 5): itu MENYIMPAN tweet akun `monitored_accounts` ke
tabel `tweets` buat tab X Intel dan TIDAK mengirim alert; ini mengirim alert berkategori ke
channel Telegram. Sejak 2026-10-16 tweet yang lolos klasifikasi JUGA disimpan ke `tweets`
(satu `TweetItem` per tweet, sebelum notice-nya; `tweets.source` = id scraper ini): di prod
`monitor_x` mati sejak 2026-10-02 (kunci twitterapi.io ditolak, ia tak punya opsi `provider`)
sementara tiga scraper lain pindah ke X resmi, dan tiga akun alert (`blueteamsec1`,
`DarkWebInformer`, `VECERTRadar`) memang tak ada di `monitored_accounts`. Scan dan verdict LLM
sudah dihitung buat alert, jadi menyimpannya tidak menambah panggilan LLM.

Alur per tweet (urutan penting: yang murah dulu, LLM terakhir):
  1. balasan / retweet dibuang (query + cek `isReply`, awalan "RT ");
  2. filter per-akun (`falconfeedsio`, `ecrime_ch`, `h4ckmanac`) -- sama dengan lama;
  3. scan regex (`score_with_lists`): tweet berbau pendanaan dan "Ransomware Alert:"
     dibuang;
  4. klasifikasi LLM (`related_cyber`) -- di kode lama SEBELUM filter 2-3, jadi
     tweet yang toh dibuang tetap makan satu panggilan LLM;
  5. rute ke topik (`tweet_routing.route_tweet`) -> satu `NoticeItem` per topik.

Perbedaan dari skrip lama:
  - SATU query `(from:a OR from:b ...)` per run, bukan satu request per akun
    (free tier twitterapi.io ~1 request/5 detik; lihat `_twitterapi.py`).
  - Sumber data: twitterapi.io (default) ATAU API resmi X v2, dipilih per-scraper lewat
    opsi `provider` di control plane -- lihat `_twitter.py`. Auth ikut sumber yang dipilih.
  - Dedup = id tweet (+ topik) oleh framework, bukan `offset/tweetid.txt` yang
    ditulis SETELAH `time.sleep(3)` per tweet (crash di antaranya = kirim ulang).
  - Jendela pencarian 2x interval jadwal; tweet yang sudah pernah dikirim di
    dalam jendela itu dibuang dedup (dan ikut diklasifikasi ulang -- harga kecil
    dibanding kehilangan tweet kalau satu run terlewat).
  - Skrip lama `exit()` di tengah loop kalau satu akun error -> akun sisanya tidak
    pernah diproses. Sekarang error API = `ParseError` sekali di awal.
  - Pesan dibatasi 4096 karakter (setelah `html.escape`): sejak provider pindah ke X resmi, post
    panjang (`note_tweet`) datang utuh sampai ribuan karakter dan `_notice_sink` menolak notice
    yang lebih panjang (prod 2026-10-16: ~30 item `accepted=false`, 4.139-9.531 karakter). Teks
    tweet yang dipotong, ditutup penanda "truncated"; Tweet URL tetap ada. Filter dan routing
    tetap membaca tweet utuh. Lihat `build_message`.

Bug lama yang DIPERTAHANKAN (perilaku, bukan salah ketik yang perlu diseragamkan):
  - `falconfeedsio`: kondisi hashtag berakhir dengan `re.search(" ", text)` yang
    cocok untuk hampir semua tweet -> praktis tanpa filter.
  - `ecrime_ch`: hanya tweet yang memuat "the shame-site for #ransomware"; yang berbunyi
    "New claim on the shame-site" atau "Ransomware Alert:" lalu dibuang routing --
    kebanyakan tweet akun itu memang berbunyi begitu, jadi yang lolos sedikit.
"""

from __future__ import annotations

import datetime
import html
import re
from collections.abc import Iterator
from typing import ClassVar

from cti_enrich.stages.classify import OpenAIQuotaExhausted, classify
from cti_enrich.stages.score import ScoreResult, score_with_lists
from cti_enrich.tweet_routing import TweetRoutingInput, route_tweet
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import NoticeItem, TweetItem

from cti_scrapers.collectors import _tweet_item
from cti_scrapers.collectors import _twitter as tw

_WIB = datetime.timedelta(hours=7)
_RE_TCO = re.compile(r"(https:\/\/t.co\/\w+)")

_TELEGRAM_LIMIT = 4096
"""Batas satu pesan; SAMA dengan `_TELEGRAM_TEXT_LIMIT` di `cti_scraper.sinks` (dijaga tes). Lebih
dari ini `_notice_sink` menolak notice (`ValueError`), jadi alert tidak terkirim dan item gagal."""
_TRUNCATED = "… [truncated, see Tweet URL]"
_LINKS_MAX = 800
_MENTIONS_MAX = 300
"""Batas daftar tautan dan tiap daftar "Mentioned ..." HANYA saat pesan melewati `_TELEGRAM_LIMIT`.
Bagian tetap (judul, Author, Posted On, Tweet URL) kurang dari 500 karakter, jadi teks tweet tetap
kebagian lebih dari 2000 karakter dalam kasus terburuk (semua daftar penuh)."""


def _passes_account_filter(user: str, text: str) -> bool:
    low = text.lower()
    user = user.lower()
    if user == "falconfeedsio":
        return any(
            tag in low for tag in ("#threatintel", "#cti", "#threatintelligence", "#ransomware")
        ) or (" " in low)
    if user == "ecrime_ch":
        return "the shame-site for #ransomware" in low
    if user == "h4ckmanac":
        return any(tag in low for tag in ("#cyberattack", "#databreach", "#darkweb"))
    return True


def _join_capped(parts: list[str], sep: str, limit: int | None) -> str:
    """Gabung `parts` dengan `sep`. Kalau hasilnya > `limit`, ambil bagian dari depan yang
    muat dan ringkas sisanya jadi "+N more". Satu bagian tidak pernah dipotong di tengah, jadi
    tag `<a>` dan entitas HTML tetap utuh. `limit=None` = tanpa batas."""
    joined = sep.join(parts)
    if limit is None or len(joined) <= limit:
        return joined
    used = len(f"+{len(parts)} more")  # tempat ringkasan; N paling banyak len(parts)
    kept: list[str] = []
    for part in parts:
        if used + len(part) + len(sep) > limit:
            break
        kept.append(part)
        used += len(part) + len(sep)
    return "".join(p + sep for p in kept) + f"+{len(parts) - len(kept)} more"


def _links(tweet: tw.Tweet, limit: int | None = None) -> str:
    seen: list[str] = []
    parts: list[str] = []
    for expanded in tweet.links:
        if not expanded or expanded in seen or expanded == "https://twitter.com":
            continue
        seen.append(expanded)
        parts.append(f"<a href='{html.escape(expanded, quote=True)}'>See Link</a>")
    return _join_capped(parts, " || ", limit)


def _cap(names: list[str], limit: int | None = None) -> str:
    """Nama di-escape SEBELUM digabung supaya `limit` menghitung panjang yang benar-benar terkirim."""
    escaped = [html.escape(n.capitalize().replace("\\-", "-")) for n in names]
    return _join_capped(escaped, " || ", limit)


def _clip_text(text: str, budget: int) -> str:
    """`html.escape(text)` yang panjangnya <= `budget`; kalau kepanjangan, teks dipotong dan
    ditutup `_TRUNCATED`. Pemotongan di teks ASLI (sebelum escape) per karakter: satu `<` atau
    `&` jadi 4-5 karakter, dan memotong hasil escape bisa menyisakan entitas setengah ("&am")."""
    escaped = html.escape(text)
    if len(escaped) <= budget:
        return escaped
    room = budget - len(_TRUNCATED)
    end = used = 0
    for char in text:
        used += len(html.escape(char))
        if used > room:
            break
        end += 1
    return html.escape(text[:end].rstrip()) + _TRUNCATED


def build_message(
    tweet: tw.Tweet, scan: ScoreResult, *, limit: int | None = _TELEGRAM_LIMIT
) -> str:
    """Pesan Telegram (HTML). Panjangnya, setelah `html.escape`, <= `limit`: teks tweet yang
    memotong (post panjang `note_tweet` bisa ribuan karakter), setelah daftar tautan dan
    "Mentioned ..." dibatasi. Pesan yang sudah muat TIDAK diubah sama sekali. `limit=None` =
    pesan utuh, dipakai filter dan routing yang harus membaca seluruh tweet."""
    user = tweet.username
    posted = (tweet.created_at + _WIB).strftime("%H:%M:%S on %Y-%m-%d") if tweet.created_at else "-"
    text = _RE_TCO.sub(" ", tweet.text.replace("\n", " "))
    url = tweet.url
    regional = [*scan.mentioned_countries, *scan.mentioned_apac_people]

    def compose(tweet_html: str, capped: bool) -> str:
        links_max = _LINKS_MAX if capped else None
        mentions_max = _MENTIONS_MAX if capped else None
        msg = (
            f"\n=== <b>NEW TWEET FROM {html.escape(user.upper())}</b> ===\n"
            f"<b>Author</b> : {html.escape(user)}\n"
            f"<b>Tweet</b> : {tweet_html}\n"
            f"<b>Posted On</b> : {posted}\n"
            f"<b>Tweet URL</b> : <a href='{html.escape(url, quote=True)}'>See Tweet</a>\n"
        )
        if links := _links(tweet, links_max):
            msg += f"<b>Link</b> : {links}"
        if scan.mentioned_group:
            msg += f"\n<b>Mentioned Group</b> : {_cap(scan.mentioned_group, mentions_max)}"
        if regional:
            msg += f"\n<b>Mentioned APAC Country/People</b> : {_cap(regional, mentions_max)}"
        return msg

    msg = compose(html.escape(text), capped=False)
    if limit is None or len(msg) <= limit:
        return msg
    fixed = len(compose("", capped=True))  # semua selain teks tweet
    return compose(_clip_text(text, limit - fixed), capped=True)


class TweetAlertScraper(BaseScraper):
    __abstract__ = True

    accounts: ClassVar[tuple[str, ...]]
    window: ClassVar[datetime.timedelta]

    def fetch(self, ctx: ScrapeContext) -> Iterator[NoticeItem | TweetItem]:
        spec = tw.TweetSearch(since=ctx.now - self.window, accounts=self.accounts)

        techstack: list[str] = ctx.reference["techstack"]
        groups: list[str] = ctx.reference["threat_actor_groups"]
        people: list[str] = ctx.reference["monitored_people"]

        found = 0
        for tweet in tw.by_id(tw.search(ctx, spec)):
            for item in self._items(ctx, tweet, techstack, groups, people):
                # Batas per run cuma buat pesan Telegram; arsip `TweetItem` tidak ikut dihitung.
                if isinstance(item, NoticeItem):
                    if found >= self.meta.max_items:
                        return
                    found += 1
                yield item

    def _items(
        self,
        ctx: ScrapeContext,
        tweet: tw.Tweet,
        techstack: list[str],
        groups: list[str],
        people: list[str],
    ) -> Iterator[NoticeItem | TweetItem]:
        text = tweet.text
        user = tweet.username
        if not text or tweet.is_reply or text.startswith("RT "):
            return
        if not _passes_account_filter(user, text):
            return

        scan = score_with_lists(
            title=text,
            body="",
            techstack=techstack,
            group_list=groups,
            apac_people_list=people,
        )
        if scan.funding_keyword:
            return  # noise pendanaan (`tweet_indicator = False` di skrip lama)
        # Utuh (tanpa batas Telegram): filter dan routing harus membaca SELURUH tweet, bukan
        # hanya bagian yang muat di pesan; penanda seperti "#threatreport" sering ada di ekor
        # post panjang. Yang dikirim ke Telegram adalah `build_message(tweet, scan)` di bawah.
        message = build_message(tweet, scan, limit=None)
        if "Ransomware Alert:" in message:
            return

        try:
            verdict = classify(text, task="classify_tweet")
        except OpenAIQuotaExhausted:
            raise
        except Exception as e:
            # Tidak di-yield -> tidak ditandai seen -> dicoba lagi di run berikutnya
            # (selama masih dalam jendela pencarian). Skrip lama: crash seluruh run.
            ctx.log.warning(
                "tweet_alerts: classify() gagal, tweet dilewati", tweet_id=tweet.id, error=str(e)
            )
            return
        if not verdict.related_cyber:
            return

        if user:
            # Arsip X Intel: SEKALI per tweet (bukan per topik), sebelum notice-nya, jadi gagal
            # kirim Telegram tidak menghilangkan arsip dan sebaliknya (dedup `tweet_id` vs
            # `tweet_id:topik` terpisah). Tanpa username kolom `author_username` (NOT NULL) kosong.
            yield _tweet_item.from_tweet(tweet, scan, verdict)

        topics = route_tweet(
            TweetRoutingInput(
                msg_data=message,
                cve_list=scan.cve_list_title,
                # Kode lama: `related_tech_status` tweet HANYA dari `checkCVE` (vendor CVE
                # cocok tech stack), dan cuma dihitung di cabang tanpa grup/negara.
                related_tech_status=scan.related_tech_cve_status,
                report_status=scan.report_status,
                ot_status=scan.ot_status,
                databreach_list=scan.databreach_list,
                zero_day_list=scan.zero_day_list,
            )
        )
        created = tweet.created_at
        notice_text = build_message(tweet, scan)  # <= batas Telegram; `message` bisa lebih panjang
        for topic in topics:
            yield NoticeItem(
                topic=topic,
                text=notice_text,
                key=f"{tweet.id}:{topic}",
                title=f"@{user}: {text[:100]}",
                url=tweet.url,
                posted_on=created.date() if created else None,
            )


_REFERENCE = ("techstack", "threat_actor_groups", "monitored_people")


class TweetAlerts1h(TweetAlertScraper):
    meta = ScraperMeta(
        id="tweet_alerts_1h",
        source="X/Twitter Alerts (hourly list)",
        schedule="5 * * * *",
        rate_limit="10/minute",
        credential="twitter",
        options=(tw.ALERTS_PROVIDER_OPTION,),
        reference_data=_REFERENCE,
        max_items=40,
        tags=("migrated", "bespoke", "twitter"),
        legacy_script="twitter",
    )
    accounts = (
        "blueteamsec1", "DailyDarkWeb", "threatintel", "_CPResearch_", "ecrime_ch",
        "FalconFeedsio", "blackorbird", "ESETresearch", "GroupIB_TI", "anyrun_app",
    )  # fmt: skip
    window = datetime.timedelta(hours=2)


class TweetAlerts30m(TweetAlertScraper):
    meta = ScraperMeta(
        id="tweet_alerts_30m",
        source="X/Twitter Alerts (half-hour list)",
        schedule="35 * * * *",
        rate_limit="10/minute",
        credential="twitter",
        options=(tw.ALERTS_PROVIDER_OPTION,),
        reference_data=_REFERENCE,
        max_items=40,
        tags=("migrated", "bespoke", "twitter"),
        legacy_script="twitter30",
    )
    accounts = (
        "MsftSecIntel", "DarkWebInformer", "MonThreat", "H4ckManac", "Unit42_Intel",
        "ido_cohen2", "stealthmole_int", "rst_cloud", "ValidinLLC", "virusbtn", "VECERTRadar",
    )  # fmt: skip
    window = datetime.timedelta(hours=1)
