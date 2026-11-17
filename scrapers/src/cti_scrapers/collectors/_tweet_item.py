"""Bentuk `TweetJobItem` (tweet yang menunggu klasifikasi LLM di worker) dari hasil scan regex.

Dipakai dua jalur supaya baris `tweets` (tab X Intel) yang ditulis `monitor_x` dan `tweet_alerts_*`
isinya sama:
  - `monitor_x` (`feeds/monitor_x.py`): tweet mentah twitterapi.io, memakai `scan_results` dan
    `routing_fields`; tweet X resmi memakai `tweet_job_item` (`notify=False`);
  - `tweet_alerts_*` (`collectors/tweet_alerts.py`): tweet netral (`_twitter.Tweet`), memakai
    `tweet_job_item` (`notify=True`).
Scraper TIDAK memanggil LLM: sink menulis job `tweet`, worker yang mengklasifikasi lalu menyimpan
ke `tweets` (`cti_enrich.tweet_job`) dan, kalau `notify`, merutekan alert Telegram dari teks pesan
yang dibangun scraper (`msg_data` di `routing`, `notice_text`).

Modul BUKAN scraper; awalan `_` menandai helper internal paket `collectors`.
"""

from __future__ import annotations

from typing import Any

from cti_enrich.stages.score import ScoreResult
from cti_scraper.items import TweetJobItem

from cti_scrapers.collectors._twitter import Tweet


def scan_results(scan: ScoreResult) -> dict[str, Any]:
    return {
        "apac_indicator": bool(scan.mentioned_countries or scan.mentioned_apac_people),
        "mentioned_group": scan.mentioned_group,
        "mentioned_apac_country": scan.mentioned_countries,
        "mentioned_apac_people": scan.mentioned_apac_people,
        "cve_list": scan.cve_list_title,
        "zero_day_list": scan.zero_day_list,
        "databreach_list": scan.databreach_list,
        "ot_status": scan.ot_status,
        "report_status": scan.report_status,
    }


def routing_fields(scan: ScoreResult) -> dict[str, Any]:
    """Field `TweetRoutingInput` selain `msg_data` (pesan utuh; hanya scraper `notify` yang
    menambahkannya, lewat `tweet_job_item`).
    Kode lama: `related_tech_status` tweet HANYA dari `checkCVE` (vendor CVE cocok tech stack),
    dan cuma dihitung di cabang tanpa grup/negara."""
    return {
        "cve_list": scan.cve_list_title,
        "related_tech_status": scan.related_tech_cve_status,
        "report_status": scan.report_status,
        "ot_status": scan.ot_status,
        "databreach_list": scan.databreach_list,
        "zero_day_list": scan.zero_day_list,
    }


def tweet_job_item(
    tweet: Tweet,
    scan: ScoreResult,
    *,
    notify: bool,
    msg_data: str | None = None,
    notice_text: str | None = None,
) -> TweetJobItem:
    """Tweet netral -> `TweetJobItem` (job `tweet` di `enrich_jobs`; LLM dipanggil worker).
    `msg_data` (pesan utuh untuk `route_tweet`) dan `notice_text` (pesan Telegram) dari
    `tweet_alerts.build_message`; worker tidak punya scan untuk membangunnya sendiri."""
    routing = routing_fields(scan)
    if msg_data is not None:
        routing["msg_data"] = msg_data
    return TweetJobItem(
        tweet_id=tweet.id,
        url=tweet.url,
        text=tweet.text,
        author_username=tweet.username,
        author_name=tweet.author_name,
        author_avatar=tweet.author_avatar,
        author_followers=tweet.author_followers,
        posted_on=tweet.created_at,
        lang=tweet.lang,
        media_urls=list(tweet.media_urls),
        scan_results=scan_results(scan),
        routing=routing,
        notice_text=notice_text,
        notify=notify,
    )
