"""Bentuk `TweetItem` (baris tabel `tweets`, tab X Intel) dari hasil scan regex dan klasifikasi LLM.

Dipakai dua jalur supaya baris `tweets` yang ditulis `monitor_x` dan `tweet_alerts_*` isinya sama:
  - `monitor_x` (`feeds/monitor_x.py`): tweet mentah twitterapi.io, memakai `scan_results` dan
    `llm_fields`;
  - `tweet_alerts_*` (`collectors/tweet_alerts.py`): tweet netral (`_twitter.Tweet`), memakai
    `from_tweet`. Scan dan klasifikasi sudah dihitung untuk alert, jadi menyimpannya tidak
    menambah panggilan LLM.

Modul BUKAN scraper; awalan `_` menandai helper internal paket `collectors`.
"""

from __future__ import annotations

from typing import Any

from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from cti_scraper.items import TweetItem

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


def llm_fields(llm: ClassifyResult | None) -> dict[str, Any]:
    """Field LLM `TweetItem`; `llm=None` (klasifikasi gagal, tweet tetap disimpan) = nilai kosong."""
    return {
        "confidence_score": round(llm.confidence * 100) if llm and llm.confidence else None,
        "confirmed_incident": bool(llm.confirmed_incident) if llm else False,
        "industries_impacted": llm.industries_impacted if llm else [],
        "victim_countries": llm.victim_countries if llm else [],
        "actor_countries": llm.actor_countries if llm else [],
        "victim_name": llm.victim_name if llm else None,
        "incident_confidence": (
            round(llm.incident_confidence * 100)
            if llm and llm.incident_confidence is not None
            else None
        ),
        "incident_indicators": llm.incident_indicators if llm else [],
    }


def from_tweet(tweet: Tweet, scan: ScoreResult, llm: ClassifyResult | None) -> TweetItem:
    return TweetItem(
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
        **llm_fields(llm),
    )
