"""Alert tweet ke Telegram -- gantiin `TwitterScrap/twitter.py` (tiap jam) dan
`twitter30.py` (tiap :30): dua skrip yang 495 dari 498 barisnya IDENTIK, cuma beda
daftar akun (`usernames_1hour.txt` / `usernames_130hour.txt`).

Bedakan dari `monitor_x` (Fase 5): itu MENYIMPAN tweet akun `monitored_accounts` ke
tabel `tweets` buat tab X Intel dan TIDAK mengirim alert; ini sebaliknya -- tidak
menyimpan apa-apa, cuma mengirim alert berkategori ke channel Telegram.

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
from cti_scraper.items import NoticeItem

from cti_scrapers.collectors import _twitter as tw

_WIB = datetime.timedelta(hours=7)
_RE_TCO = re.compile(r"(https:\/\/t.co\/\w+)")


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


def _links(tweet: tw.Tweet) -> str:
    seen: list[str] = []
    parts: list[str] = []
    for expanded in tweet.links:
        if not expanded or expanded in seen or expanded == "https://twitter.com":
            continue
        seen.append(expanded)
        parts.append(f"<a href='{html.escape(expanded, quote=True)}'>See Link</a>")
    return " || ".join(parts)


def _cap(names: list[str]) -> str:
    return " || ".join(n.capitalize().replace("\\-", "-") for n in names)


def build_message(tweet: tw.Tweet, scan: ScoreResult) -> str:
    user = tweet.username
    posted = (tweet.created_at + _WIB).strftime("%H:%M:%S on %Y-%m-%d") if tweet.created_at else "-"
    text = _RE_TCO.sub(" ", tweet.text.replace("\n", " "))
    url = tweet.url

    msg = (
        f"\n=== <b>NEW TWEET FROM {html.escape(user.upper())}</b> ===\n"
        f"<b>Author</b> : {html.escape(user)}\n"
        f"<b>Tweet</b> : {html.escape(text)}\n"
        f"<b>Posted On</b> : {posted}\n"
        f"<b>Tweet URL</b> : <a href='{html.escape(url, quote=True)}'>See Tweet</a>\n"
    )
    if links := _links(tweet):
        msg += f"<b>Link</b> : {links}"
    if scan.mentioned_group:
        msg += f"\n<b>Mentioned Group</b> : {html.escape(_cap(scan.mentioned_group))}"
    regional = [*scan.mentioned_countries, *scan.mentioned_apac_people]
    if regional:
        msg += f"\n<b>Mentioned APAC Country/People</b> : {html.escape(_cap(regional))}"
    return msg


class TweetAlertScraper(BaseScraper):
    __abstract__ = True

    accounts: ClassVar[tuple[str, ...]]
    window: ClassVar[datetime.timedelta]

    def fetch(self, ctx: ScrapeContext) -> Iterator[NoticeItem]:
        spec = tw.TweetSearch(since=ctx.now - self.window, accounts=self.accounts)

        techstack: list[str] = ctx.reference["techstack"]
        groups: list[str] = ctx.reference["threat_actor_groups"]
        people: list[str] = ctx.reference["monitored_people"]

        found = 0
        for tweet in tw.by_id(tw.search(ctx, spec)):
            for notice in self._notices(ctx, tweet, techstack, groups, people):
                if found >= self.meta.max_items:
                    return
                found += 1
                yield notice

    def _notices(
        self,
        ctx: ScrapeContext,
        tweet: tw.Tweet,
        techstack: list[str],
        groups: list[str],
        people: list[str],
    ) -> Iterator[NoticeItem]:
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
        message = build_message(tweet, scan)
        if "Ransomware Alert:" in message:
            return

        try:
            verdict = classify(text)
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
        for topic in topics:
            yield NoticeItem(
                topic=topic,
                text=message,
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
