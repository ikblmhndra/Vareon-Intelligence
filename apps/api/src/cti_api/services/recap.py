"""Port `ScraperNewsWeb/app/services/recap_service.py`. Fase 7.3 (router
`recap`, Bagian 5). Recap harian (news + X intel yang masuk hari itu) +
forecast 1-3 hari, di-generate LLM, cached per tanggal.

`_collect_campaigns()` (Fase 7.4 Grup A, 2026-09-23) sekarang manggil
`cti_api.services.campaign.get_recent_campaigns()` beneran. `try/except
-> []` tetap dipertahankan (port apa adanya).

**1 bug legacy DITEMUKAN & DIPERBAIKI, bukan port apa adanya**:
`_build_user_message()` (di bawah) baca field `theme`/`label`/
`article_ids`/`threat_actors` dari tiap campaign dict -- field itu SAMA
SEKALI GAK ADA di output `get_recent_campaigns()` (yang punya
`cluster_name`/`summary_title`/`member_article_ids`/`dominant_tas`).
Ketauan lewat baca `recap_service.py` ASLI: `_collect_campaigns()`
legacy JUGA manggil `get_recent_campaigns()` LANGSUNG tanpa mapping
apa pun -- artinya section "active campaigns" di prompt LLM legacy
SELALU nampilin "(unlabeled) — 0 articles" buat SEMUA campaign, dari
awal fitur ini ditulis. Bukan asimetri yang dipertahankan (gak ada niat
desain di balik field yang gak pernah match), diperbaiki di sini:
`_collect_campaigns()` nge-map field yang bener sebelum dikirim ke
`_build_user_message()`.

Artikel gak punya field `cves` langsung di skema baru (array mention CVE
per-artikel ala Mongo) -- anotasi "CVEs: ..." per baris artikel di prompt
lama di-drop, bagian "NEW/UPDATED CVES" (`_collect_cves`) sendiri udah
nutup sinyal itu. Sort artikel pakai `source_score.get_source_reliability()`
(heuristik nama sumber) gantiin field `source_reliability` per-dokumen
lama yang gak ada analognya di `Article` (grading itu sekarang query
terpisah lewat `AsyncSourceReliabilityRepo`, bukan kolom artikel).

**`_extract_json()` (Fase 7.5, "buang duplikasi")** dulu regex sendiri
(fence-strip + brace-extraction) yang HAMPIR sama kayak `cti_core.llm.
client.parse_json_response()` tapi gak nahan `<think>...</think>`
preamble -- sekarang numpang fungsi kanonik itu, dibungkus try/except
biar kontrak lama (gak pernah raise, fallback `{"_raw": raw}` yang
dipakai `generate_daily_recap()` buat mutusin nyimpen `raw_llm` atau
kagak) tetap sama persis.

**`token_usage` (#21, 2026-10-11)** dulu SELALU `{}`: `usage` dari completion gak pernah dibaca,
jadi biaya satu recap gak kelihatan dan target "token lebih sedikit" gak punya angka pembanding.
Sekarang isinya token dari gateway (`usage_from`, kosong kalau gateway diam), `wall_ms` (waktu
panggilan API, diukur di `_call_llm`), `input_chars` (panjang pesan user) dan `prompt_items`
(berapa item tiap seksi yang BENAR-BENAR masuk prompt). Dua yang terakhir ada supaya ukuran prompt
tetap terlihat walau gateway tidak melaporkan token."""

from __future__ import annotations

import asyncio
import datetime
import time
from typing import Any

from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.recap import AsyncRecapRepo
from cti_core.db.repositories.ta import AsyncTARepo
from cti_core.db.repositories.tweet import AsyncTweetRepo
from cti_core.llm.client import get_llm_client, parse_json_response, usage_from
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import campaign as campaign_service
from cti_api.services.source_score import get_source_reliability

SYSTEM_PROMPT = """You are a Senior Cyber Threat Intelligence Analyst producing a daily desk-brief for analysts.

Output STRICT JSON (no markdown, no code fences). Schema:

{
  "headline": "<one sentence overall posture for yesterday>",
  "recap": {
    "summary": "<3-5 sentence narrative recap of yesterday's notable cyber events from both news and social/X chatter>",
    "top_stories": [
      {"title": "<article title>", "why_it_matters": "<1 sentence>", "source": "<source name>"}
    ],
    "top_tweets": [
      {"author": "<username>", "summary": "<what they reported>", "signal": "<incident|cve|ttp|other>"}
    ],
    "active_threat_actors": ["<name>", "..."],
      "new_threat_actors_added": [{"name": "<name>", "source": "<source>"}],
    "notable_cves": ["CVE-YYYY-NNNNN", "..."],
    "active_campaigns": [
      {"theme": "<cluster theme>", "article_count": <int>, "why_it_matters": "<1 sentence>"}
    ],
    "apac_signals": ["<APAC-specific items>", "..."]
  },
  "forecast": {
    "summary": "<2-3 sentence forecast for next 1-3 days based ONLY on the signals provided>",
    "likely_events": [
      {"event": "<predicted event>", "basis": "<concrete signal that justifies this — must reference items in the input>", "confidence": "low|med|high"}
    ],
    "watch_items": ["<thing analysts should keep eye on today>", "..."]
  }
}

Rules:
- Ground every forecast item in a concrete input signal. If there is no basis, omit the item.
- Do not invent CVE IDs, threat actor names, or campaigns not in the input.
- Keep top_stories to <=8, top_tweets to <=6, likely_events to <=5.
- If yesterday had no notable activity, say so plainly — do not fabricate.
"""


def _yesterday(date_str: str | None) -> str:
    if date_str:
        return date_str
    d = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _truncate(s: str | None, n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


async def _collect_articles(session: AsyncSession, day: datetime.date) -> list[Any]:
    articles, _total = await AsyncArticleRepo(session).list_filtered(
        posted_on_start=day, posted_on_end=day, page_size=200
    )
    articles.sort(key=lambda a: get_source_reliability(a.source))
    return articles


async def _collect_tweets(session: AsyncSession, day: datetime.date) -> list[Any]:
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=datetime.UTC)
    end = start + datetime.timedelta(days=1)
    tweets, _total = await AsyncTweetRepo(session).list_filtered(
        posted_on_start=start, posted_before=end, page_size=150
    )
    tweets.sort(key=lambda t: t.incident_confidence or 0, reverse=True)
    return tweets


async def _collect_iocs(session: AsyncSession, day: datetime.date) -> list[Any]:
    return await AsyncIOCRepo(session).list_first_seen_on(day, limit=200)


async def _collect_cves(session: AsyncSession, day: datetime.date) -> list[Any]:
    return await AsyncCveTrackerRepo(session).list_registered_on(day, limit=50)


async def _collect_new_threat_actors(session: AsyncSession, day: datetime.date) -> list[Any]:
    return await AsyncTARepo(session).list_added_on(day)


async def _collect_campaigns(session: AsyncSession) -> list[dict[str, Any]]:
    try:
        campaigns = await campaign_service.get_recent_campaigns(session, days=7, min_size=3)
    except Exception:
        return []
    return [
        {
            "theme": c.get("cluster_name") or c.get("summary_title") or "",
            "article_ids": c.get("member_article_ids") or [],
            "size": c.get("size") or 0,
            "threat_actors": c.get("dominant_tas") or [],
        }
        for c in campaigns
    ]


_MAX_ARTICLES = 60
_MAX_TWEETS = 50
_MAX_CVES = 30
_MAX_CAMPAIGNS = 8
"""Berapa baris tiap seksi yang dimuat `_build_user_message`; sisanya cuma ikut terhitung di judul
seksi. Satu tempat buat prompt DAN `_prompt_items`, supaya jumlah yang dicatat tidak melenceng dari
yang benar-benar dikirim. IOC (satu baris hitungan per tipe) dan threat actor baru tidak dipotong."""


def _prompt_items(
    articles: list[Any],
    tweets: list[Any],
    iocs: list[Any],
    cves: list[Any],
    campaigns: list[dict[str, Any]],
    new_tas: list[Any],
) -> dict[str, int]:
    """Item tiap seksi yang BENAR-BENAR masuk prompt (setelah dipotong `_MAX_*`), bukan total yang
    dikumpulkan (itu `counts`). IOC masuk sebagai hitungan per tipe, jadi semuanya terwakili."""
    return {
        "articles": min(len(articles), _MAX_ARTICLES),
        "tweets": min(len(tweets), _MAX_TWEETS),
        "cves": min(len(cves), _MAX_CVES),
        "iocs": len(iocs),
        "campaigns": min(len(campaigns), _MAX_CAMPAIGNS),
        "new_threat_actors": len(new_tas),
    }


def _build_user_message(
    date_iso: str,
    articles: list[Any],
    tweets: list[Any],
    iocs: list[Any],
    cves: list[Any],
    campaigns: list[dict[str, Any]],
    new_tas: list[Any],
) -> str:
    article_lines = []
    for a in articles[:_MAX_ARTICLES]:
        actors = ", ".join(t.threat_actor for t in a.threat_actors[:3])
        article_lines.append(
            f"- [{a.source}] {_truncate(a.title, 200)}" + (f" | actors: {actors}" if actors else "")
        )

    tweet_lines = []
    for t in tweets[:_MAX_TWEETS]:
        sr = t.scan_results or {}
        flags = []
        if t.confirmed_incident:
            flags.append("CONFIRMED-INCIDENT")
        if sr.get("apac_indicator"):
            flags.append("APAC")
        if sr.get("ot_status"):
            flags.append("OT")
        if sr.get("zero_day_list"):
            flags.append("0DAY")
        if sr.get("databreach_list"):
            flags.append("BREACH")
        groups = ", ".join((sr.get("mentioned_group") or [])[:3])
        cves_t = ", ".join((sr.get("cve_list") or [])[:3])
        flag_str = f" [{' '.join(flags)}]" if flags else ""
        tweet_lines.append(
            f"- @{t.author_username}{flag_str}: {_truncate(t.text, 240)}"
            + (f" | groups: {groups}" if groups else "")
            + (f" | CVEs: {cves_t}" if cves_t else "")
        )

    cve_lines = []
    for c in cves[:_MAX_CVES]:
        bits = []
        if c.cve_score is not None:
            bits.append(f"CVSS {c.cve_score}")
        if c.cve_severity:
            bits.append(c.cve_severity)
        if c.tech:
            bits.append(f"tech: {c.tech}")
        if c.cisa_kev:
            bits.append("KEV")
        if c.poc_available:
            bits.append("PoC")
        cve_lines.append(f"- {c.cve_id} ({', '.join(bits)}): {_truncate(c.summary, 160)}")

    ioc_counts: dict[str, int] = {}
    for i in iocs:
        ioc_counts[i.type] = ioc_counts.get(i.type, 0) + 1
    ioc_line = (
        ", ".join(f"{k}={v}" for k, v in sorted(ioc_counts.items(), key=lambda x: -x[1])) or "none"
    )

    camp_lines = []
    for c in campaigns[:_MAX_CAMPAIGNS]:
        theme = c.get("theme") or c.get("label") or "(unlabeled)"
        size = c.get("size") or len(c.get("article_ids") or [])
        actors = ", ".join((c.get("threat_actors") or [])[:3])
        camp_lines.append(
            f"- {theme} — {size} articles" + (f" | actors: {actors}" if actors else "")
        )

    new_ta_lines = [f"- {ta.name} (source: {ta.source or 'manual'})" for ta in new_tas]

    return f"""DAILY RECAP TARGET DATE: {date_iso} (UTC)

== NEWS ROOM ARTICLES POSTED {date_iso} ({len(articles)} total) ==
{chr(10).join(article_lines) if article_lines else "  (none)"}

== X / TWITTER POSTS ON {date_iso} ({len(tweets)} cyber-relevant) ==
{chr(10).join(tweet_lines) if tweet_lines else "  (none)"}

== NEW / UPDATED CVES ON {date_iso} ({len(cves)} total) ==
{chr(10).join(cve_lines) if cve_lines else "  (none)"}

== NEW IOCS ON {date_iso} ({len(iocs)} total) ==
{ioc_line}

== NEW THREAT ACTORS ADDED TO DATABASE ON {date_iso} ({len(new_tas)} total) ==
{chr(10).join(new_ta_lines) if new_ta_lines else "  (none)"}

== ACTIVE CAMPAIGN CLUSTERS (last 7d, momentum context for forecast) ==
{chr(10).join(camp_lines) if camp_lines else "  (none)"}

Now produce the JSON recap+forecast per the schema. Remember: forecast must cite concrete signals from above.
"""


def _extract_json(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return parse_json_response(raw)
    except Exception:
        return {"_raw": raw}


def _call_llm(user_msg: str) -> tuple[str, str, dict[str, int]]:
    """`(isi balasan, nama model, pemakaian)`. Pemakaian = `usage_from` (kosong kalau gateway tidak
    mengirim `usage`) + `wall_ms`: waktu panggilan API termasuk retry klien. Diukur DI SINI, di
    dalam fungsi yang jalan di thread (`asyncio.to_thread`), supaya antre event loop tidak ikut."""
    client, model_name = get_llm_client()
    started = time.monotonic()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        n=1,
    )
    wall_ms = int((time.monotonic() - started) * 1000)
    return (
        completion.choices[0].message.content or "",
        model_name,
        {**usage_from(completion), "wall_ms": wall_ms},
    )


async def generate_daily_recap(
    session: AsyncSession, date: str | None = None, force: bool = False
) -> dict[str, Any]:
    """Generate (atau ambil cache) recap buat tanggal ini (default kemarin).
    Kalau recap tanggal ini udah ada dan `force=False`, balikin yang lama."""
    date_iso = _yesterday(date)
    repo = AsyncRecapRepo(session)

    if not force:
        existing = await repo.get(date_iso)
        if existing is not None:
            return _to_dict(existing, cached=True)

    day = datetime.date.fromisoformat(date_iso)
    articles = await _collect_articles(session, day)
    tweets = await _collect_tweets(session, day)
    iocs = await _collect_iocs(session, day)
    cves = await _collect_cves(session, day)
    campaigns = await _collect_campaigns(session)
    new_tas = await _collect_new_threat_actors(session, day)

    user_msg = _build_user_message(date_iso, articles, tweets, iocs, cves, campaigns, new_tas)
    raw, model_name, llm_usage = await asyncio.to_thread(_call_llm, user_msg)
    parsed = _extract_json(raw)

    row = await repo.upsert(
        date_iso,
        headline=parsed.get("headline", ""),
        yesterday=parsed.get("recap", {}),
        forecast=parsed.get("forecast", {}),
        counts={
            "articles": len(articles),
            "tweets": len(tweets),
            "iocs": len(iocs),
            "cves": len(cves),
            "campaigns": len(campaigns),
            "new_threat_actors": len(new_tas),
        },
        generated_at=datetime.datetime.now(datetime.UTC),
        model=model_name,
        token_usage={
            **llm_usage,
            "input_chars": len(user_msg),
            "prompt_items": _prompt_items(articles, tweets, iocs, cves, campaigns, new_tas),
        },
        raw_llm=raw if "_raw" in parsed else None,
    )
    return _to_dict(row, cached=False)


def _to_dict(row: Any, *, cached: bool) -> dict[str, Any]:
    return {
        "id": row.id,
        "date": row.date,
        "headline": row.headline,
        "yesterday": row.yesterday,
        "forecast": row.forecast,
        "counts": row.counts,
        "generated_at": row.generated_at.isoformat(),
        "model": row.model,
        "token_usage": row.token_usage,
        "raw_llm": row.raw_llm,
        "cached": cached,
    }


async def get_recap(session: AsyncSession, date: str) -> dict[str, Any] | None:
    row = await AsyncRecapRepo(session).get(date)
    if row is None:
        return None
    return _to_dict(row, cached=True)


async def list_recaps(session: AsyncSession, limit: int = 30) -> list[dict[str, Any]]:
    rows = await AsyncRecapRepo(session).list_recent(limit)
    return [
        {
            "date": r.date,
            "headline": r.headline,
            "counts": r.counts,
            "generated_at": r.generated_at.isoformat(),
        }
        for r in rows
    ]
