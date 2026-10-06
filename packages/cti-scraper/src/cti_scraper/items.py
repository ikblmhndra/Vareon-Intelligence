"""Item yang boleh di-`yield` scraper. `fetch()` gak pernah nulis DB
langsung -- dia `yield` salah satu dari ini, sink registry (sinks.py) yang
nentuin tujuannya dari TIPE-nya. Ini jalan keluar scraper bespoke tanpa
`if scraper.is_special` di mana pun: mau nulis bentuk dokumen sendiri,
`yield` tipe Item yang beda, bukan minta pengecualian ke framework.
"""

from __future__ import annotations

import datetime
from typing import Any

from cti_core.urlkit import canonicalize_url
from pydantic import BaseModel, ConfigDict, Field


class Item(BaseModel):
    """Base. Jangan dipakai langsung -- subclass ini yang di-`yield`."""

    model_config = ConfigDict(extra="forbid")

    def dedup_key(self) -> str | None:
        """Identitas stabil buat item ini. `None` artinya item ini gak
        dedup sama sekali (mis. collector snapshot penuh yang emang mau
        nulis ulang tiap kali). Framework nge-hash ini bareng scraper_id
        (lihat dedup.py) -- jangan hash sendiri di sini."""
        raise NotImplementedError


class ArticleItem(Item):
    """Item paling umum -- ~91 dari job aktif Rundeck nge-yield ini.
    Masuk pipeline enrichment (Fase 5), bukan langsung ke tabel `articles`."""

    title: str
    url: str
    posted_on: datetime.date | None = None
    summary: str | None = None
    author: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    """Passthrough spesifik-family -- mis. kategori RSS, field API mentah
    yang belum tentu kepake tapi sayang dibuang. Bukan tempat nulis field
    yang beneran dipakai; itu harusnya jadi field asli di atas."""

    def dedup_key(self) -> str:
        return canonicalize_url(self.url)


class NoticeItem(Item):
    """Pesan Telegram MURNI -- gak lewat enrichment (LLM/klasifikasi) dan gak
    nulis tabel apa pun. Jalur keluar buat job lama yang cuma "pantau sesuatu ->
    kabari channel": watcher commit GitHub, advisory library, alert tweet
    (Fase 10.E). Beda dari `ArticleItem`: artikel itu MATERI yang dianalisis;
    notice itu SUDAH jadi pesan, tinggal dikirim.

    `key` = identitas dedup (SHA commit, id advisory, id tweet, dst) -- dipilih
    penulis scraper, BUKAN URL, karena satu commit bisa jadi banyak notice dan
    sebaliknya. Kegagalan kirim TIDAK ditelan (lihat sink): item di-release dan
    dicoba lagi di run berikutnya -- notice yang hilang diam-diam itu dulu jadi
    masalah `send_alert_*` lama (`except Exception: pass`)."""

    topic: str
    """Kunci `TELEGRAM__THREAD_IDS` (mis. "apt", "vendor_report")."""
    text: str
    """Badan pesan, HTML Telegram. Field dari sumber luar WAJIB di-`html.escape`
    oleh scraper -- satu `<` liar bikin Telegram nolak seluruh pesan."""
    key: str
    title: str = ""
    """Ringkasan satu baris buat log `ScraperItem`; kosong -> diambil dari `text`."""
    url: str = ""
    posted_on: datetime.date | None = None
    """Cuma buat mengurutkan "terbaru dulu" di cold-start cap."""
    attachment_name: str | None = None
    attachment_text: str | None = None
    """Kalau diisi, pesan dikirim sebagai DOKUMEN (`attachment_name`) dgn `text`
    sbg caption -- gantiin `send_report_file` lama."""

    def dedup_key(self) -> str:
        return self.key


class CveMentionItem(Item):
    """Mention CVE di SATU tweet -> naikkan penghitung `cve_mentions` (scope tweet)
    buat laporan "Top CVE 6 jam" (Fase 10.E, gantiin `TwitterScrap/trendingCve.py`).
    Tanpa alert langsung: cuma menghitung. `dedup_key()` = id tweet, jadi tweet yang
    muncul lagi di jendela pencarian berikutnya TIDAK menghitung dobel -- itu yang
    dulu dikerjakan kursor `offset/lastTweetId.txt`."""

    tweet_id: str
    cve_ids: list[str]
    """Unik per tweet (satu tweet menyebut CVE yang sama dua kali dihitung SEKALI,
    sama dengan `dict.fromkeys(re.findall(...))` skrip lama)."""
    url: str = ""

    def dedup_key(self) -> str:
        return self.tweet_id


class RansomwareVictimItem(Item):
    """Nulis langsung ke `ransomware_victims`, MELEWATI pipeline enrichment
    artikel -- lihat sinks.py. Ini contoh kanonik "scraper bespoke", gantiin
    `ransomwareLiveThreat.py`."""

    group_name: str
    victim: str
    country_code: str = ""
    industry: str = ""
    published: datetime.date | None = None
    discovered: datetime.date | None = None
    domain: str = ""
    description: str = ""
    post_url: str = "Unknown"
    ransom: str | None = None
    data_size: str | None = None
    screenshot: str = ""

    def dedup_key(self) -> str:
        # Format WAJIB 5 bagian match persis `offset_string` di
        # ransomwareLiveThreat.py lama -- ketauan dari golden test, bukan
        # ditebak: draft pertama field ini cuma 4 bagian (lupa `industry`).
        return (
            f"{self.group_name}:{self.victim}:{self.country_code}:{self.industry}:{self.published}"
        )


class CveItem(Item):
    """Nulis ke `cve_tracker`. Sink dipasang pas Fase 4 nge-port
    `newCveThreat.py` (lihat `scrapers/.../feeds/new_cve.py`), sesuai
    keputusan "gak bangun lebih dulu dari kebutuhan" yang sama kayak Fase 2."""

    cve_id: str
    client_id: str
    tech: str | None = None
    link: str | None = None
    summary: str | None = None
    published: datetime.date | None = None
    published_at: datetime.datetime | None = None
    """Jam publish lengkap dari MITRE (tz-aware, UTC). `published` di atas cuma tanggalnya."""
    cve_modified_date: datetime.date | None = None
    """Tanggal MITRE terakhir update record ini -- field DB `CveTracker`
    udah ada dari Fase 2, tapi ketinggalan di draft awal Item ini (Fase 3
    nulis "sink belum didaftarin" -- ini momen finalisasi-nya). Dipakai
    web nanti buat nunjukin CVE mana yang baru berubah, BUKAN buat
    keputusan alert (itu ranah cti-alerts, di luar scraper)."""
    references: list[str] = Field(default_factory=list)
    affected: list[str] = Field(default_factory=list)
    solutions: str | None = None
    cve_score: float | None = None
    cve_severity: str | None = None
    cvss_vector: str | None = None

    def dedup_key(self) -> str:
        return f"{self.cve_id}:{self.client_id}"


class CvePocItem(Item):
    """Nambahin SATU POC/exploit repo ke `cve_tracker.pocs` (baris yang
    `cve_id`-nya cocok, lintas client) -- MELEWATI pipeline artikel, gantiin
    `githubPOCMonitor.py`. Beda dari `CveItem`: dedup NORMAL (bukan
    di-override `None`) -- satu URL POC gak berubah lagi begitu ketemu,
    gak kayak `CveItem` yang datanya bisa di-update MITRE kapan aja."""

    cve_id: str
    url: str
    source: str = ""
    poc_type: str = "poc"
    """"poc" atau "exploit" -- klasifikasi regex sederhana (lihat scraper)."""

    def dedup_key(self) -> str:
        return f"{self.cve_id}:{self.url}"


class MalwareTrendItem(Item):
    """Nulis ke `malware_trends`, MELEWATI pipeline artikel -- gantiin
    `anyrunTrendThreat.py`. Satu Item = satu POSISI RANKING di satu HARI
    (bukan satu artikel), sesuai `dedup_key()` yang nyertain `snapshot_date`
    -- leaderboard berubah hari ke hari, disimpen sebagai time-series,
    bukan ditimpa."""

    source: str
    snapshot_date: datetime.date
    rank: int
    malware_name: str
    malware_type: str | None = None
    url: str
    report_count: str | None = None

    def dedup_key(self) -> str:
        return f"{self.source}:{self.snapshot_date}:{self.rank}"


class PackageVulnItem(Item):
    """Nulis ke `package_vulns`. Sink belum didaftarin -- sama alasan CveItem."""

    ecosystem: str
    package: str
    vuln_id: str
    severity: str | None = None
    epss: float | None = None
    kev: bool = False
    aliases: list[str] = Field(default_factory=list)

    def dedup_key(self) -> str:
        return f"{self.ecosystem}:{self.package}:{self.vuln_id}"


class IocFeedItem(Item):
    """Nulis ke `iocs` (+ `threat_feed_entries` kalau ada IOC kategori
    "c2") DAN kirim SATU alert Telegram topic "darkweb" -- gantiin
    `deepdarkCTI.py` (Fase 5). SATU Item = SATU commit GitHub, BUKAN satu
    IOC -- satu commit bisa ngandung banyak IOC baru sekaligus, semuanya
    numpuk di `iocs` di bawah. `dedup_key()` = SHA commit, persis
    granularitas `offset/deepdarkCTI_offset.txt` lama."""

    commit_sha: str
    commit_message: str
    commit_author: str
    commit_date: datetime.datetime
    commit_url: str
    files_changed: list[dict[str, Any]] = Field(default_factory=list)
    """[{filename, additions, deletions, patch_preview}] -- badan pesan
    Telegram, udah final formatnya di titik ekstraksi (`fetch()`), sink
    cuma nyusun jadi teks."""
    iocs: list[dict[str, str]] = Field(default_factory=list)
    """[{type, value, category}] -- `type` udah salah satu dari 8 nilai
    kanonik `IOC.type` (lihat `cti_enrich.stages.persist._IOC_TYPE_MAP`),
    `category` = folder asal (c2/ioc/phishing/ransomware/tor/darkweb)."""

    def dedup_key(self) -> str:
        return self.commit_sha


class TweetItem(Item):
    """Nulis ke `tweets` -- gantiin `monitorX.py::build_tweet_doc` +
    `upsert_tweet` (Fase 5). `dedup_key()` = tweet_id, SELALU dedup normal
    (bukan `None` kayak `MalwareTrendItem`) -- tweet gak berubah isinya
    setelah diposting, beda dari artikel yang bisa di-edit."""

    tweet_id: str
    url: str
    text: str
    author_username: str
    author_name: str | None = None
    author_avatar: str | None = None
    author_followers: int | None = None
    posted_on: datetime.datetime | None = None
    lang: str | None = None
    media_urls: list[str] = Field(default_factory=list)

    scan_results: dict[str, Any] = Field(default_factory=dict)
    """apac_indicator, mentioned_group, mentioned_apac_country,
    mentioned_apac_people, cve_list, zero_day_list, databreach_list,
    ot_status, report_status -- lihat `Tweet.scan_results` (Fase 2)."""
    confidence_score: int | None = None
    confirmed_incident: bool = False
    industries_impacted: list[str] = Field(default_factory=list)
    victim_countries: list[str] = Field(default_factory=list)
    actor_countries: list[str] = Field(default_factory=list)
    victim_name: str | None = None
    incident_confidence: int | None = None
    incident_indicators: list[str] = Field(default_factory=list)

    def dedup_key(self) -> str:
        return self.tweet_id
