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
tetap terlihat walau gateway tidak melaporkan token.

**Recap MINGGUAN (#21, PR 2, 2026-10-11)** -- `generate_weekly_recap()`, yang dijadwalkan beat
(Senin 00:15 UTC); recap harian tinggal pemicu tangan (`POST /api/recap/generate?kind=daily`).
- Jendela = Senin-Minggu menurut TANGGAL UTC (tanggal yang sudah dipakai kolektor: `posted_on`,
  `func.date(...)`), `date` baris = Senin. Pekan baru boleh dibuat setelah Minggunya lewat di UTC
  (`ensure_week_finished`): kalau tidak, tangan yang menjalankannya hari Jumat akan menyimpan pekan
  yang bolong, dan run terjadwal (`force=False`) lalu mengembalikan baris cache itu. `func.date()`
  atas timestamptz mengikuti timezone sesi DB, jadi jendela ini cuma berarti UTC kalau sesinya UTC
  (`_warn_unless_db_is_utc` memberi peringatan, bukan error).
- Prompt dibangun dari AGREGAT, bukan dari rentang yang dilebarkan: tiap kategori diambil N
  teratas menurut sinyal (urutan dan batasnya dikerjakan di SQL, lihat `list_top_between`), plus
  TOTAL sebenarnya per kategori lewat count/GROUP BY, dan artikel satu klaster kampanye diringkas
  jadi satu baris. `counts` yang disimpan = total sebenarnya, BUKAN panjang daftar yang dipotong.
- Pekan tanpa artikel, tweet, maupun CVE TIDAK memanggil LLM: hasil deterministik "tidak ada
  aktivitas" (`model=""`, `token_usage` menandai panggilan dilewati).
- Isi recap mingguan disimpan di kolom `yesterday` (nama lama, lihat `DailyRecap`); `kind='weekly'`
  membedakannya dari baris harian di Senin yang sama.

**Kualitas recap mingguan (#21, PR 3, 2026-10-12)** -- semuanya dihitung KODE dan disimpan di
`quality`, tanpa panggilan LLM tambahan; recap harian TIDAK tersentuh (prompt, keluaran, dan alurnya
sama persis).
- `grounding` (modul bersama `services/grounding.py`, dipakai lagi newsletter di PR 8): tiap CVE id,
  actor, tema kampanye, dan sumber di keluaran harus ada di masukan prompt; story diverifikasi lewat
  `article_id` (tiap baris artikel di prompt membawa `[#<id>]`), bukan judul, dan yang lolos mendapat
  `url`. Yang gagal dibuang dari yang ditampilkan DAN dicatat di `quality.grounding.dropped`.
  Pembangun prompt mengembalikan himpunan masukannya bersama prompt (`WeeklyPrompt.known`), jadi
  pemeriksaan tidak pernah memakai himpunan yang berbeda dari yang dilihat model.
- `comparison` (`services/recap_quality.py`): selisih `counts` dan item baru terhadap baris mingguan
  pekan SEBELUMNYA yang bersebelahan (tanggal tepat 7 hari sebelumnya). Pekan yang bolong tidak
  dibandingkan dengan pekan yang lebih jauh: itu bukan lagi "dibanding pekan lalu".
- `scorecard`: panggilan LLM yang sama juga me-review forecast pekan lalu (id `f1`, `f2`, ... ditulis
  kode menurut posisi; baris lama tanpa id diturunkan dari posisi, tidak dimigrasi). Override analis
  disimpan di samping verdict model dan dibawa saat force regen. Hit rate 8 pekan dihitung saat
  dibaca (`get_hit_rate`), karena override mengubah pekan yang sudah lewat.
- Pekan pertama (tanpa baris sebelumnya) tidak punya `comparison` maupun `scorecard`; pekan sepi
  (tanpa LLM) tidak punya `grounding` maupun `scorecard`. Pekan yang dibuat TIDAK berurutan (mis. 5
  Okt sebelum 28 Sep) tidak mendapat perbandingan/scorecard itu sampai di-force-regen, karena hanya
  dihitung saat dibuat."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import datetime
import time
from collections.abc import Callable
from typing import Any

import structlog
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.recap import AsyncRecapRepo
from cti_core.db.repositories.ta import AsyncTARepo
from cti_core.db.repositories.tweet import AsyncTweetRepo
from cti_core.llm.client import get_llm_client, parse_json_response, usage_from
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import campaign as campaign_service
from cti_api.services import grounding, recap_quality
from cti_api.services.source_score import get_source_reliability

log = structlog.get_logger()

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


async def _collect_campaigns(
    session: AsyncSession, *, start: datetime.date | None = None, end: datetime.date | None = None
) -> list[dict[str, Any]]:
    """Tanpa `start`/`end` (recap harian): 7 hari terakhir dihitung dari hari ini, perilaku lama.
    Recap mingguan memberi jendelanya, supaya pekan yang di-backfill dapat klaster pekannya."""
    try:
        campaigns = await campaign_service.get_recent_campaigns(
            session, days=7, min_size=3, start=start, end=end
        )
    except Exception:
        # Dulu diam-diam (port apa adanya); sekarang tercatat, karena recap tanpa seksi kampanye
        # tidak kelihatan bedanya dari pekan yang memang tanpa kampanye.
        log.warning("recap_campaigns_failed", exc_info=True)
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


def _article_line(a: Any, *, with_id: bool = False) -> str:
    """`with_id`: awali baris dengan `[#<id>]` (prompt MINGGUAN: story diverifikasi lewat id itu).
    Bawaannya tanpa id, supaya prompt harian tidak berubah satu byte pun."""
    actors = ", ".join(t.threat_actor for t in a.threat_actors[:3])
    tag = f"[#{a.id}] " if with_id else ""
    return f"- {tag}[{a.source}] {_truncate(a.title, 200)}" + (
        f" | actors: {actors}" if actors else ""
    )


def _tweet_line(t: Any) -> str:
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
    return (
        f"- @{t.author_username}{flag_str}: {_truncate(t.text, 240)}"
        + (f" | groups: {groups}" if groups else "")
        + (f" | CVEs: {cves_t}" if cves_t else "")
    )


def _cve_line(c: Any) -> str:
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
    return f"- {c.cve_id} ({', '.join(bits)}): {_truncate(c.summary, 160)}"


def _ioc_line(ioc_counts: dict[str, int]) -> str:
    return (
        ", ".join(f"{k}={v}" for k, v in sorted(ioc_counts.items(), key=lambda x: -x[1])) or "none"
    )


def _campaign_line(c: dict[str, Any]) -> str:
    theme = c.get("theme") or c.get("label") or "(unlabeled)"
    size = c.get("size") or len(c.get("article_ids") or [])
    actors = ", ".join((c.get("threat_actors") or [])[:3])
    return f"- {theme} — {size} articles" + (f" | actors: {actors}" if actors else "")


def _new_ta_line(ta: Any) -> str:
    return f"- {ta.name} (source: {ta.source or 'manual'})"


def _build_user_message(
    date_iso: str,
    articles: list[Any],
    tweets: list[Any],
    iocs: list[Any],
    cves: list[Any],
    campaigns: list[dict[str, Any]],
    new_tas: list[Any],
) -> str:
    article_lines = [_article_line(a) for a in articles[:_MAX_ARTICLES]]
    tweet_lines = [_tweet_line(t) for t in tweets[:_MAX_TWEETS]]
    cve_lines = [_cve_line(c) for c in cves[:_MAX_CVES]]

    ioc_counts: dict[str, int] = {}
    for i in iocs:
        ioc_counts[i.type] = ioc_counts.get(i.type, 0) + 1
    ioc_line = _ioc_line(ioc_counts)

    camp_lines = [_campaign_line(c) for c in campaigns[:_MAX_CAMPAIGNS]]
    new_ta_lines = [_new_ta_line(ta) for ta in new_tas]

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


def _call_llm(user_msg: str, system_prompt: str = SYSTEM_PROMPT) -> tuple[str, str, dict[str, int]]:
    """`(isi balasan, nama model, pemakaian)`. Pemakaian = `usage_from` (kosong kalau gateway tidak
    mengirim `usage`) + `wall_ms`: waktu panggilan API termasuk retry klien. Diukur DI SINI, di
    dalam fungsi yang jalan di thread (`asyncio.to_thread`), supaya antre event loop tidak ikut.
    `system_prompt` bawaannya prompt HARIAN; recap mingguan memberi `WEEKLY_SYSTEM_PROMPT`."""
    client, model_name = get_llm_client()
    started = time.monotonic()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
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
        existing = await repo.get(date_iso, "daily")
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
        period_start=day,
        period_end=day,
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


# ── Recap mingguan (#21, PR 2) ──────────────────────────────────────────────

_WEEKLY_MAX_ARTICLES = 80
_WEEKLY_MAX_TWEETS = 50
_WEEKLY_MAX_CVES = 40
_WEEKLY_MAX_CAMPAIGNS = 10
_WEEKLY_MAX_NEW_TAS = 20
_WEEKLY_POOL_FACTOR = 3
"""Batas baris tiap seksi prompt mingguan (campaign: yang teratas menurut severity; sisanya cuma ikut
terhitung di judul seksi). Sedikit di atas batas harian (60/50/30/8), BUKAN 7x: seminggu itu ~7x
volume, tapi prompt dibangun dari agregat. Angkanya masih perkiraan -- baseline token belum diukur
(ROADMAP #21) -- jadi satu tempat ini yang diubah setelah baseline ada. `_WEEKLY_POOL_FACTOR`:
kandidat artikel yang dimuat dari DB = `_WEEKLY_MAX_ARTICLES` x ini, lalu disusun ulang dengan sinyal
yang tidak ada di kolom (ukuran klaster, keandalan sumber) dan dipotong ke `_WEEKLY_MAX_ARTICLES`."""

_WEEKLY_MAX_TOP_STORIES = 8
_WEEKLY_MAX_TOP_TWEETS = 6
_WEEKLY_MAX_LIKELY_EVENTS = 5
"""Batas KELUARAN yang diminta prompt mingguan; sama dengan harian sampai baseline mengizinkan lebih."""

_WEEKLY_SCHEMA = """You are a Senior Cyber Threat Intelligence Analyst producing a weekly desk-brief for analysts.

Output STRICT JSON (no markdown, no code fences). Schema:

{
  "headline": "<one sentence overall posture for the week>",
  "recap": {
    "summary": "<4-6 sentence narrative recap of the week's notable cyber events from both news and social/X chatter: lead with the biggest stories and the trend, not a day-by-day list>",
    "top_stories": [
      {"article_id": <int, the number in the [#id] marker of the article line this story is about>, "title": "<article title>", "why_it_matters": "<1 sentence>", "source": "<source name>"}
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
    "summary": "<2-3 sentence forecast for the next 1-2 weeks based ONLY on the signals provided>",
    "likely_events": [
      {"event": "<predicted event>", "basis": "<concrete signal that justifies this — must reference items in the input>", "confidence": "low|med|high"}
    ],
    "watch_items": ["<thing analysts should keep an eye on next week>", "..."]
  },
  "forecast_review": [
    {"id": "<id of a LAST WEEK'S FORECAST item, e.g. f1>", "verdict": "happened|partly|not_happened|unclear", "evidence": "<one line from this week's input>"}
  ]
}

"""
_WEEKLY_RULES = f"""Rules:
- The input is an AGGREGATE of the whole week. Counts are exact totals; each list holds only the strongest items of its category, so never present a list length as a total.
- A story marked "cluster: N articles" stands for N related articles about the same campaign: do not count it as a single article and do not list that campaign twice.
- Ground every forecast item in a concrete input signal. If there is no basis, omit the item.
- Do not invent CVE IDs, threat actor names, or campaigns not in the input.
- Keep top_stories to <={_WEEKLY_MAX_TOP_STORIES}, top_tweets to <={_WEEKLY_MAX_TOP_TWEETS}, likely_events to <={_WEEKLY_MAX_LIKELY_EVENTS}.
- Every top_stories item MUST carry the article_id of the single article line it is based on: the number in that line's [#id] marker (123 for [#123]). A story without a valid article_id is discarded.
- Copy CVE IDs, threat actor names and campaign themes exactly as they appear in the input. Anything that does not appear in the input is discarded.
- If the input has a "LAST WEEK'S FORECAST" section, return exactly one forecast_review item per listed id, judged ONLY from this week's input: happened (it occurred), partly (it partly occurred), not_happened (the input shows it did not occur), unclear (the input says nothing either way), each with one line of evidence. Without that section return an empty forecast_review.
- If the week had no notable activity, say so plainly — do not fabricate.
"""
WEEKLY_SYSTEM_PROMPT = _WEEKLY_SCHEMA + _WEEKLY_RULES


class RecapWindowError(ValueError):
    """Jendela recap mingguan tidak valid: bukan hari Senin, atau pekannya belum selesai di UTC.
    Router menjawabnya HTTP 400."""


def _today_utc() -> datetime.date:
    """Titik tunggal "hari ini" (UTC), dipisah supaya test bisa membekukannya lewat monkeypatch."""
    return datetime.datetime.now(datetime.UTC).date()


def week_window(week_start: datetime.date) -> tuple[datetime.date, datetime.date]:
    """`(Senin, Minggu)` pekan yang dimulai `week_start`; tolak kalau bukan hari Senin."""
    if week_start.weekday() != 0:
        raise RecapWindowError(
            f"week_start must be a Monday, got {week_start.isoformat()} "
            f"({week_start.strftime('%A')})"
        )
    return week_start, week_start + datetime.timedelta(days=6)


def last_finished_week_start(today: datetime.date) -> datetime.date:
    """Senin pekan terakhir yang SUDAH selesai di UTC pada `today`. Senin: `today - 7`; hari lain
    juga benar (run terjadwal yang telat, mis. worker mati Senin, tetap dapat pekan yang barusan
    lewat, bukan tanggal yang bukan Senin)."""
    return today - datetime.timedelta(days=today.weekday() + 7)


def default_week_start() -> datetime.date:
    """Pekan yang dibuat kalau pemanggil tidak menyebut `week_start`: yang terakhir selesai."""
    return last_finished_week_start(_today_utc())


def ensure_week_finished(week_end: datetime.date, today: datetime.date) -> None:
    """Pekan baru boleh dirangkum setelah Minggunya lewat di UTC. Kalau tidak, hasilnya pekan yang
    bolong dan tersimpan sebagai cache: run terjadwal (`force=False`) hari Senin akan mengembalikan
    baris itu, bukan pekan yang utuh."""
    if week_end >= today:
        raise RecapWindowError(
            f"week ending {week_end.isoformat()} (Sunday) is not finished yet in UTC "
            f"(today is {today.isoformat()}); it can be generated from "
            f"{(week_end + datetime.timedelta(days=1)).isoformat()}"
        )


@dataclasses.dataclass(frozen=True)
class WeeklyInputs:
    """Yang dikumpulkan untuk satu pekan: item yang MASUK prompt, plus total sebenarnya per kategori.

    `articles` = pasangan `(artikel, ukuran klaster kampanyenya atau 0)`, sudah diurutkan menurut
    sinyal dan satu baris per klaster. `campaigns` = SEMUA klaster pekan itu (urutan severity,
    dari `get_recent_campaigns`); prompt memuat sebagian, tapi jumlahnya yang masuk `counts`."""

    start: datetime.date
    end: datetime.date
    articles: list[tuple[Any, int]]
    articles_total: int
    tweets: list[Any]
    tweets_total: int
    cves: list[Any]
    cves_total: int
    ioc_by_type: dict[str, int]
    new_tas: list[Any]
    new_tas_total: int
    campaigns: list[dict[str, Any]]

    @property
    def iocs_total(self) -> int:
        return sum(self.ioc_by_type.values())

    @property
    def counts(self) -> dict[str, int]:
        """Total SEBENARNYA (bukan panjang daftar yang dipotong), kunci sama dengan recap harian."""
        return {
            "articles": self.articles_total,
            "tweets": self.tweets_total,
            "iocs": self.iocs_total,
            "cves": self.cves_total,
            "campaigns": len(self.campaigns),
            "new_threat_actors": self.new_tas_total,
        }

    @property
    def has_activity(self) -> bool:
        """Ada yang layak dirangkum: artikel, tweet, atau CVE. IOC/threat actor saja tidak cukup."""
        return bool(self.articles_total or self.tweets_total or self.cves_total)


def _rank_weekly_articles(
    pool: list[Any], cluster_by_article: dict[int, tuple[int, int]]
) -> list[tuple[Any, int]]:
    """Susun ulang kandidat dari SQL (sudah menurut insiden terkonfirmasi + `confidence_score`)
    dengan dua sinyal yang tidak ada di kolom, lalu ambil `_WEEKLY_MAX_ARTICLES`, SATU baris per
    klaster kampanye.

    Urutan: insiden terkonfirmasi, `confidence_score`, ukuran klaster (kampanye yang diberitakan
    banyak sumber), keandalan sumber (heuristik nama sumber; 'A' terbaik), terbaru. Artikel satu
    klaster setelah wakil pertamanya dilewati: klaster itu sudah terwakili satu baris yang memuat
    ukurannya (dan satu baris di seksi kampanye).

    `cluster_by_article`: id artikel -> (indeks klaster, ukuran klaster)."""

    def signal(a: Any) -> tuple[Any, ...]:
        size = cluster_by_article.get(a.id, (0, 0))[1]
        return (
            not a.confirmed_incident,
            -(a.confidence_score or 0),
            -size,
            get_source_reliability(a.source),
            -(a.posted_on.toordinal() if a.posted_on else 0),
            -a.id,
        )

    lines: list[tuple[Any, int]] = []
    represented: set[int] = set()
    for a in sorted(pool, key=signal):
        cluster = cluster_by_article.get(a.id)
        if cluster is not None:
            if cluster[0] in represented:
                continue
            represented.add(cluster[0])
        lines.append((a, cluster[1] if cluster else 0))
        if len(lines) == _WEEKLY_MAX_ARTICLES:
            break
    return lines


async def _collect_weekly(
    session: AsyncSession, start: datetime.date, end: datetime.date
) -> WeeklyInputs:
    """Kumpulkan satu pekan. Urutan dan batas dikerjakan di SQL (`list_top_between` dkk) dan total
    lewat count/GROUP BY: pekan penuh TIDAK dimuat lalu dipotong. Berurutan, bukan `gather`: satu
    `AsyncSession` tidak aman dipakai bersamaan."""
    campaigns = await _collect_campaigns(session, start=start, end=end)
    cluster_by_article = {
        article_id: (idx, c["size"])
        for idx, c in enumerate(campaigns)
        for article_id in c["article_ids"]
    }

    pool, articles_total = await AsyncArticleRepo(session).list_top_between(
        start, end, limit=_WEEKLY_MAX_ARTICLES * _WEEKLY_POOL_FACTOR
    )
    articles = _rank_weekly_articles(pool, cluster_by_article)

    tweets, tweets_total = await AsyncTweetRepo(session).list_top_between(
        posted_on_start=datetime.datetime.combine(start, datetime.time.min, tzinfo=datetime.UTC),
        posted_before=datetime.datetime.combine(
            end + datetime.timedelta(days=1), datetime.time.min, tzinfo=datetime.UTC
        ),
        limit=_WEEKLY_MAX_TWEETS,
    )

    cve_repo = AsyncCveTrackerRepo(session)
    cves = await cve_repo.list_registered_between(start, end, limit=_WEEKLY_MAX_CVES)
    cves_total = await cve_repo.count_registered_between(start, end)

    ioc_by_type = await AsyncIOCRepo(session).count_first_seen_by_type_between(start, end)
    new_tas, new_tas_total = await AsyncTARepo(session).list_added_between(
        start, end, limit=_WEEKLY_MAX_NEW_TAS
    )

    return WeeklyInputs(
        start=start,
        end=end,
        articles=articles,
        articles_total=articles_total,
        tweets=tweets,
        tweets_total=tweets_total,
        cves=cves,
        cves_total=cves_total,
        ioc_by_type=ioc_by_type,
        new_tas=new_tas,
        new_tas_total=new_tas_total,
        campaigns=campaigns,
    )


def _of(total: int, shown: int, how: str) -> str:
    """ "412 total, 60 strongest shown" kalau ada yang dipotong; "5 total" kalau semuanya tampil.
    `how` = apa yang dihitung baris yang tampil. Artikel memakai "story lines", BUKAN "strongest":
    artikel satu klaster berbagi satu baris, jadi baris < total belum berarti ada yang terbuang."""
    return f"{total} total" if shown >= total else f"{total} total, {shown} {how} shown"


@dataclasses.dataclass(frozen=True)
class WeeklyPrompt:
    """Pesan user prompt mingguan DAN apa yang BOLEH muncul di keluarannya (`known`).

    Himpunan itu dibangun dari baris-baris yang SAMA yang ditulis ke pesan, di fungsi yang sama:
    pemeriksaan grounding tidak pernah memakai himpunan yang berbeda dari yang dilihat model."""

    user_message: str
    known: grounding.Known


def _prompt_actor_names(inputs: WeeklyInputs, campaigns: list[dict[str, Any]]) -> list[str]:
    """Nama threat actor yang TERCETAK di prompt. Irisan `[:3]` meniru `_article_line`,
    `_tweet_line`, dan `_campaign_line`: yang tidak tercetak tidak ikut dianggap dikenal."""
    names = [t.threat_actor for a, _ in inputs.articles for t in a.threat_actors[:3]]
    for tweet in inputs.tweets:
        names += ((tweet.scan_results or {}).get("mentioned_group") or [])[:3]
    for campaign in campaigns:
        names += (campaign.get("threat_actors") or [])[:3]
    return names + [ta.name for ta in inputs.new_tas]


def _review_line(event: dict[str, str]) -> str:
    return (
        f"- [{event['id']}] {_truncate(event['event'], 200)}"
        f" | basis: {_truncate(event['basis'], 240) or 'n/a'}"
        f" | confidence: {event['confidence'] or 'n/a'}"
    )


def _build_weekly_prompt(
    inputs: WeeklyInputs, review_events: list[dict[str, str]] | None = None
) -> WeeklyPrompt:
    """`review_events` = forecast pekan lalu (`recap_quality.events_for_review`): kalau ada, prompt
    memuat seksi "LAST WEEK'S FORECAST" dan model me-review tiap id di `forecast_review`, di
    panggilan yang sama (tanpa panggilan tambahan). Pekan pertama tidak punya seksi itu."""
    start, end = inputs.start.isoformat(), inputs.end.isoformat()
    window = f"{start}..{end}"

    article_lines = [
        _article_line(a, with_id=True) + (f" | cluster: {size} articles" if size else "")
        for a, size in inputs.articles
    ]
    tweet_lines = [_tweet_line(t) for t in inputs.tweets]
    cve_lines = [_cve_line(c) for c in inputs.cves]
    shown_campaigns = inputs.campaigns[:_WEEKLY_MAX_CAMPAIGNS]
    camp_lines = [_campaign_line(c) for c in shown_campaigns]
    new_ta_lines = [_new_ta_line(ta) for ta in inputs.new_tas]
    review_lines = [_review_line(e) for e in review_events or []]
    review_section = (
        "\n== LAST WEEK'S FORECAST (judge each item against this week's input; return one "
        "forecast_review item per id) ==\n" + "\n".join(review_lines) + "\n"
        if review_lines
        else ""
    )

    message = f"""WEEKLY RECAP WINDOW: {start} (Monday) to {end} (Sunday), UTC calendar dates
The counts below are exact totals for the whole week; each list holds only the strongest items.

== NEWS ROOM ARTICLES POSTED {window} ({_of(inputs.articles_total, len(article_lines), "story lines")}; articles of one campaign collapsed into one line) ==
{chr(10).join(article_lines) if article_lines else "  (none)"}

== X / TWITTER POSTS {window} ({_of(inputs.tweets_total, len(tweet_lines), "strongest")}) ==
{chr(10).join(tweet_lines) if tweet_lines else "  (none)"}

== NEW / UPDATED CVES {window} ({_of(inputs.cves_total, len(cve_lines), "strongest")}; ranked KEV, PoC, CVSS) ==
{chr(10).join(cve_lines) if cve_lines else "  (none)"}

== NEW IOCS {window} ({inputs.iocs_total} total) ==
{_ioc_line(inputs.ioc_by_type)}

== NEW THREAT ACTORS ADDED TO DATABASE {window} ({_of(inputs.new_tas_total, len(new_ta_lines), "first")}) ==
{chr(10).join(new_ta_lines) if new_ta_lines else "  (none)"}

== ACTIVE CAMPAIGN CLUSTERS {window} ({_of(len(inputs.campaigns), len(camp_lines), "most severe")}; momentum context for forecast) ==
{chr(10).join(camp_lines) if camp_lines else "  (none)"}
{review_section}
Now produce the JSON recap+forecast per the schema. Remember: forecast must cite concrete signals from above.
"""
    known = grounding.Known.build(
        text=message,
        threat_actors=_prompt_actor_names(inputs, shown_campaigns),
        campaigns=[c.get("theme") or c.get("label") or "" for c in shown_campaigns],
        sources=[a.source for a, _ in inputs.articles],
        articles={
            a.id: grounding.ArticleRef(url=a.url, source=a.source) for a, _ in inputs.articles
        },
    )
    return WeeklyPrompt(user_message=message, known=known)


def _weekly_prompt_items(inputs: WeeklyInputs) -> dict[str, int]:
    """Item tiap seksi yang BENAR-BENAR masuk prompt (kunci sama dengan `_prompt_items` harian).
    IOC masuk sebagai hitungan per tipe, jadi semuanya terwakili."""
    return {
        "articles": len(inputs.articles),
        "tweets": len(inputs.tweets),
        "cves": len(inputs.cves),
        "iocs": inputs.iocs_total,
        "campaigns": min(len(inputs.campaigns), _WEEKLY_MAX_CAMPAIGNS),
        "new_threat_actors": len(inputs.new_tas),
    }


def _no_activity_result(start: datetime.date, end: datetime.date) -> dict[str, Any]:
    """Hasil deterministik untuk pekan tanpa artikel, tweet, maupun CVE: tanpa panggilan LLM
    (ROADMAP #21, optimasi 3). Bentuknya sama dengan keluaran model, jadi halaman tidak perlu
    cabang khusus."""
    return {
        "headline": "No notable cyber activity this week.",
        "recap": {
            "summary": (
                f"No articles, X posts or CVEs were recorded between {start.isoformat()} and "
                f"{end.isoformat()} (UTC), so there is nothing to summarise."
            ),
            "top_stories": [],
            "top_tweets": [],
            "active_threat_actors": [],
            "new_threat_actors_added": [],
            "notable_cves": [],
            "active_campaigns": [],
            "apac_signals": [],
        },
        "forecast": {
            "summary": "No forecast: there were no signals this week to base one on.",
            "likely_events": [],
            "watch_items": [],
        },
    }


async def _warn_unless_db_is_utc(session: AsyncSession) -> None:
    """Jendela mingguan dihitung dengan `func.date(timestamptz)`, yang mengikuti timezone SESI DB.
    Kalau sesinya bukan UTC, hari bergeser (mis. sesi WIB: Minggu 17:00-24:00 UTC masuk Senin) dan
    pekannya salah tanpa ada error. Yang diperiksa PERILAKUNYA, bukan namanya: tanggal sebuah
    instan UTC di musim dingin dan musim panas harus tetap sama, jadi 'GMT' lolos dan zona dengan
    DST tidak. Peringatan, bukan exception: recap yang meleset sedikit lebih baik daripada tidak
    ada, dan operator bisa memperbaiki timezone-nya lalu `force=true`."""
    row = (
        await session.execute(
            text(
                "SELECT current_setting('TimeZone'),"
                " (TIMESTAMPTZ '2026-01-01 23:30:00+00')::date,"
                " (TIMESTAMPTZ '2026-07-01 23:30:00+00')::date"
            )
        )
    ).one()
    zone, winter, summer = row
    if (winter, summer) != (datetime.date(2026, 1, 1), datetime.date(2026, 7, 1)):
        log.warning(
            "recap_weekly_db_timezone_not_utc",
            timezone=zone,
            detail="func.date(timestamptz) follows the session timezone; week windows may shift",
        )


def _ground_weekly(
    parsed: dict[str, Any], known: grounding.Known
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keluaran model terhadap masukannya: `(keluaran yang sudah bersih, laporan grounding)`.

    Bagian terstruktur dulu (daftar CVE, actor, kampanye, story), lalu CVE id di teks bebas seluruh
    keluaran (termasuk `forecast_review`), supaya jalur di laporan cocok dengan yang disimpan dan id
    yang sudah keluar dari daftar tidak dicatat dua kali. Balasan yang bukan JSON (`_raw`) tidak
    punya apa-apa untuk diperiksa."""
    grounder = grounding.Grounder(known)
    if "_raw" in parsed:
        return {}, grounder.report()
    output = copy.deepcopy(parsed)
    recap = output.get("recap")

    def check(field: str, method: Callable[..., list[Any]], *args: Any, **kwargs: Any) -> None:
        if isinstance(recap, dict) and field in recap:
            recap[field] = method(f"recap.{field}", recap[field], *args, **kwargs)

    check("top_stories", grounder.stories)
    check("notable_cves", grounder.cve_list)
    check("active_threat_actors", grounder.name_list, "threat_actors")
    check("new_threat_actors_added", grounder.name_list, "threat_actors", key="name")
    check("active_campaigns", grounder.name_list, "campaigns", key="theme")
    cleaned: dict[str, Any] = grounder.free_text("", output)
    return cleaned, grounder.report()


async def generate_weekly_recap(
    session: AsyncSession, week_start: datetime.date | None = None, force: bool = False
) -> dict[str, Any]:
    """Generate (atau ambil cache) recap SATU PEKAN Senin-Minggu (tanggal UTC). `week_start` = hari
    Senin-nya; kosong = pekan terakhir yang sudah selesai. Pekan yang Minggunya belum lewat di UTC
    ditolak (`RecapWindowError`), juga dengan `force`. Recap pekan ini sudah ada dan `force=False`:
    balikin yang lama, tanpa LLM.

    Pekan tanpa artikel, tweet, dan CVE tidak memanggil LLM (`_no_activity_result`).

    Kualitasnya (#21, PR 3) disimpan di `quality`, semuanya dihitung kode: `grounding` (keluaran
    model diperiksa terhadap masukannya), `scorecard` (panggilan LLM yang SAMA me-review forecast
    pekan lalu) dan `comparison` (terhadap pekan sebelumnya yang bersebelahan). Force regen
    menghitung ulang semuanya; override analis di scorecard dibawa, tidak dihapus."""
    today = _today_utc()
    start, end = week_window(week_start if week_start is not None else default_week_start())
    ensure_week_finished(end, today)
    week_iso = start.isoformat()
    repo = AsyncRecapRepo(session)

    existing = await repo.get(week_iso, "weekly")
    if existing is not None and not force:
        return _to_dict(existing, cached=True)

    await _warn_unless_db_is_utc(session)
    inputs = await _collect_weekly(session, start, end)
    # Hanya pekan yang BERSEBELAHAN (tanggal tepat 7 hari sebelumnya): pekan yang bolong tidak
    # dibandingkan dengan yang lebih jauh, itu bukan lagi "dibanding pekan lalu".
    previous_row = await repo.get((start - datetime.timedelta(days=7)).isoformat(), "weekly")
    previous = _to_dict(previous_row, cached=True) if previous_row is not None else None
    quality: dict[str, Any] = {}

    if inputs.has_activity:
        review_events = (
            recap_quality.events_for_review(previous["forecast"], limit=_WEEKLY_MAX_LIKELY_EVENTS)
            if previous is not None
            else []
        )
        prompt = _build_weekly_prompt(inputs, review_events)
        raw, model_name, llm_usage = await asyncio.to_thread(
            _call_llm, prompt.user_message, WEEKLY_SYSTEM_PROMPT
        )
        parsed = _extract_json(raw)
        output, quality["grounding"] = _ground_weekly(parsed, prompt.known)
        if previous is not None and review_events:
            quality["scorecard"] = recap_quality.build_scorecard(
                recap_quality.week_ref(previous),
                review_events,
                output.get("forecast_review"),
                replacing=(existing.quality or {}).get("scorecard") if existing else None,
            )
        token_usage = {
            **llm_usage,
            "input_chars": len(prompt.user_message),
            "prompt_items": _weekly_prompt_items(inputs),
        }
        raw_llm = raw if "_raw" in parsed else None
    else:
        output, model_name, raw_llm = _no_activity_result(start, end), "", None
        token_usage = {"skipped": True, "reason": "no_activity"}

    recap_body = output.get("recap", {})
    forecast = output.get("forecast", {})
    if isinstance(forecast, dict) and "likely_events" in forecast:
        forecast = {
            **forecast,
            "likely_events": recap_quality.stamp_event_ids(forecast["likely_events"]),
        }
    # Dihitung dari keluaran yang SUDAH lolos grounding: "baru pekan ini" tidak boleh memuat
    # karangan yang sudah dibuang.
    comparison = recap_quality.build_comparison(inputs.counts, recap_body, previous)
    if comparison is not None:
        quality["comparison"] = comparison

    row = await repo.upsert(
        week_iso,
        kind="weekly",
        period_start=start,
        period_end=end,
        headline=output.get("headline", ""),
        yesterday=recap_body,
        forecast=forecast,
        counts=inputs.counts,
        generated_at=datetime.datetime.now(datetime.UTC),
        model=model_name,
        token_usage=token_usage,
        quality=quality,
        raw_llm=raw_llm,
    )
    log.info(
        "recap_weekly_generated",
        kind="weekly",
        period_start=week_iso,
        period_end=end.isoformat(),
        counts=inputs.counts,
        token_usage=token_usage,
        model=model_name,
        skipped=not inputs.has_activity,
        parse_failed=raw_llm is not None,
        grounding_dropped=quality.get("grounding", {}).get("count", 0),
        scorecard=recap_quality.verdict_counts(quality.get("scorecard")),
        force=force,
    )
    return _to_dict(row, cached=False)


# ── Pembacaan ────────────────────────────────────────────────────────────────


def _period(row: Any) -> tuple[datetime.date, datetime.date]:
    """Rentang baris; baris lama (sebelum kolom periode ada, atau ditulis kode lama) jatuh ke
    `date`: satu hari."""
    day = datetime.date.fromisoformat(row.date)
    return row.period_start or day, row.period_end or day


def _to_dict(row: Any, *, cached: bool) -> dict[str, Any]:
    period_start, period_end = _period(row)
    return {
        "id": row.id,
        "kind": row.kind,
        "date": row.date,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "headline": row.headline,
        "yesterday": row.yesterday,
        "forecast": row.forecast,
        "counts": row.counts,
        "generated_at": row.generated_at.isoformat(),
        "model": row.model,
        "token_usage": row.token_usage,
        "quality": row.quality or {},
        "raw_llm": row.raw_llm,
        "cached": cached,
    }


async def get_recap(session: AsyncSession, date: str, kind: str = "daily") -> dict[str, Any] | None:
    row = await AsyncRecapRepo(session).get(date, kind)
    if row is None:
        return None
    return _to_dict(row, cached=True)


async def get_latest_recap(session: AsyncSession, kind: str) -> dict[str, Any] | None:
    """Recap `kind` dengan tanggal terbaru yang tersimpan (halaman Recap membuka yang mingguan)."""
    row = await AsyncRecapRepo(session).get_latest(kind)
    if row is None:
        return None
    return _to_dict(row, cached=True)


async def list_recaps(session: AsyncSession, limit: int = 30) -> list[dict[str, Any]]:
    """Kedua jenis, dengan `kind` dan rentangnya (satu hari buat yang harian)."""
    rows = await AsyncRecapRepo(session).list_recent(limit)
    items = []
    for r in rows:
        period_start, period_end = _period(r)
        items.append(
            {
                "date": r.date,
                "kind": r.kind,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "headline": r.headline,
                "counts": r.counts,
                "generated_at": r.generated_at.isoformat(),
            }
        )
    return items


# ── Scorecard: override analis dan hit rate ──────────────────────────────────


class ScorecardNotFoundError(LookupError):
    """Recap, scorecard-nya, atau event yang mau di-override tidak ada. Router menjawabnya 404."""


async def override_scorecard(
    session: AsyncSession, recap_id: int, event_id: str, verdict: str, username: str
) -> dict[str, Any]:
    """Verdict analis (`happened | partly | not_happened | unclear`) untuk event `event_id` di
    scorecard recap `recap_id`, disimpan DI SAMPING verdict model dengan siapa dan kapan; hit rate
    memakainya. `recap_id` = baris yang MEMUAT scorecard (recap pekan yang me-review), `event_id` =
    id event forecast pekan sebelumnya yang di-review di sana.

    Barisnya dikunci (`FOR UPDATE`) sampai transaksi selesai: `quality` dibaca, satu entri diubah,
    lalu seluruh JSONB ditulis, jadi dua analis yang menimpa event berbeda di saat yang sama akan
    saling menghapus tanpa kunci itu. Pemanggil yang commit (dan menulis audit log)."""
    row = await AsyncRecapRepo(session).get_by_id(recap_id, for_update=True)
    if row is None:
        raise ScorecardNotFoundError(f"No recap with id {recap_id}")
    scorecard = (row.quality or {}).get("scorecard")
    if not isinstance(scorecard, dict):
        raise ScorecardNotFoundError(f"Recap {recap_id} has no forecast scorecard")
    try:
        updated = recap_quality.apply_override(
            scorecard, event_id, verdict, by=username, at=datetime.datetime.now(datetime.UTC)
        )
    except LookupError as e:
        raise ScorecardNotFoundError(f"Recap {recap_id} has no scorecard entry {event_id}") from e
    row.quality = {**row.quality, "scorecard": updated}  # objek baru: ORM tak melihat mutasi JSONB
    await session.flush()
    return _to_dict(row, cached=True)


async def get_hit_rate(session: AsyncSession) -> dict[str, Any]:
    """Hit rate scorecard di `recap_quality.HIT_RATE_WEEKS` recap mingguan terakhir, dihitung SAAT
    DIBACA: override analis mengubah pekan yang sudah lewat, jadi angka yang disimpan akan basi."""
    rows = await AsyncRecapRepo(session).list_latest("weekly", recap_quality.HIT_RATE_WEEKS)
    return recap_quality.hit_rate([{"date": r.date, "quality": r.quality} for r in rows])
