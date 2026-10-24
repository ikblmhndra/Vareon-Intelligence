"""Port `ScraperNewsWeb/app/services/newsletter_service.py`. Fase 7.3
(router `newsletter`, Bagian 4).

Ekstraksi IOC lewat `cti_core.ioc.extractor` (BUKAN fork lokal kayak kode
lama -- lihat docstring modul itu). LLM lewat `cti_core.llm.client`
(Fase 7.5, gak numpang duplikat sempit lokal lagi).

`include_clusters`/`campaign_clusters` (Fase 7.4 Grup A, 2026-09-23)
sekarang jalan -- `cti_api.services.campaign.get_recent_campaigns()`
("mesin cluster" Pipeline 2), diambil 5 campaign teratas, field yang
dikirim ke template newsletter dipangkas (`name`/`size`/`first_seen`/
`last_seen`/`dominant_tas`/`dominant_industries`/`dominant_countries`/
`attack_techniques`/`cve_ids`).

Body artikel di-fetch pakai Playwright (real headless browser) + IOC
regex-scan + LLM summarization -- proses ini genuinely lambat/network-
heavy per artikel (bukan bug, port apa adanya). Sejak PR 5 (ROADMAP #22)
hasilnya di-CACHE per artikel (`newsletter_article_summaries`), jadi
mengulang preview, atau draft sesudah preview, tidak fetch dan tidak
memanggil LLM lagi. Membangun konteks sendiri hanya menulis dua cache
(ringkasan dan hint paywall); IOC dan sebutan CVE baru ditulis oleh
`write_article_findings()` saat draft dibuat (dulu ikut tertulis tiap
preview).

Bahasa (ROADMAP #22): `key_points` dan `summary` ditulis dalam bahasa permintaan (`language`,
Indonesia secara default) di panggilan LLM yang SAMA dengan ringkasannya; istilah berulang
diseragamkan glosarium di `newsletter_glossary`, dan bahasa ikut kunci cache. Template email
(`templates/newsletter_email.html`) merujuk logo lewat `cid:` (`newsletter_logo`)."""

from __future__ import annotations

import asyncio
import datetime
import json
import re
from collections.abc import Collection, Mapping
from functools import partial
from pathlib import Path
from typing import Any

from cti_core.config import get_settings, platform_name
from cti_core.db.models.article import Article
from cti_core.db.models.newsletter import NewsletterArticleSummary
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.ioc_reference import AsyncIocAllowlistRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from cti_core.ioc.allowlist import allowlist_match
from cti_core.ioc.canonical import canonical
from cti_core.ioc.extractor import extract_iocs
from cti_core.llm.client import get_llm_client, parse_json_response, usage_from
from cti_core.llm.usage import prompt_version
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.newsletter import DEFAULT_SUMMARY_LANGUAGE, SummaryLanguage
from cti_api.services import campaign as campaign_service
from cti_api.services import newsletter_edition, newsletter_glossary, newsletter_logo
from cti_api.services.email_env import make_env

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_NEWSLETTER_EMAIL_TEMPLATE = "newsletter_email.html"

GMAIL_CLIP_BYTES = 102 * 1024
"""Gmail memotong pesan yang HTML-nya lebih besar dari ~102 KB dan menyembunyikan sisanya di balik
"View entire message" (footer dan bagian bawah edisi ikut hilang)."""

HTML_WARN_BYTES = 90 * 1024
"""Batas peringatan di preview, di bawah batas Gmail supaya analis sempat memindahkan kartu ke
"Also Noted" atau membuangnya. CSS inline membuat HTML berat (satu kartu penuh sekitar 2-3 KB)."""

_RE_CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)

_PAYWALL_KEYWORDS = [
    "subscribe to read",
    "sign in to read",
    "premium content",
    "create an account to continue",
    "subscribe now to continue",
    "this content is for subscribers",
    "to continue reading",
    "already a subscriber",
    "login to read",
    "register to read",
]
_PAYWALL_MIN_BODY_LEN = 150

try:
    from playwright_stealth import stealth_async as _stealth_async

    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False


# ── Allowlist ──────────────────────────────────────────────────────────────


async def _get_allowlist_sets(session: AsyncSession) -> dict[str, set[str]]:
    entries = await AsyncIocAllowlistRepo(session).list_all()
    url_domains: set[str] = set()
    email_domains: set[str] = set()
    ips: set[str] = set()
    for e in entries:
        if e.type == "url_domain":
            url_domains.add(e.value.lower())
        elif e.type == "email_domain":
            email_domains.add(e.value.lower())
        elif e.type == "ip":
            ips.add(e.value)
    return {"url_domains": url_domains, "email_domains": email_domains, "ips": ips}


# ── Paywall + article body fetching ─────────────────────────────────────────


def _is_paywall(html: str, body: str | None) -> bool:
    if not body or len(body) < _PAYWALL_MIN_BODY_LEN:
        html_lower = html.lower()
        return any(kw in html_lower for kw in _PAYWALL_KEYWORDS)
    return False


async def fetch_article_body(
    session: AsyncSession, url: str, source: str
) -> tuple[str | None, bool]:
    """Returns (body_text | None, paywall_detected)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None, False

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()
            if _STEALTH_AVAILABLE:
                await _stealth_async(page)

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                html = await page.content()
            finally:
                await browser.close()

        import trafilatura

        body = await asyncio.to_thread(
            trafilatura.extract, html, include_comments=False, include_tables=False
        )
        paywall = _is_paywall(html, body)

        if paywall:
            await AsyncNewsletterRepo(session).upsert_paywall_hint(
                source, last_seen=datetime.datetime.now(datetime.UTC).isoformat()
            )
            return None, True

        return body, False

    except Exception:
        return None, False


# ── LLM summarization ────────────────────────────────────────────────────────


_LANGUAGE_SLOT = "<<language>>"

_PROMPT_WITH_BODY = """You are a Cyber Threat Intelligence analyst writing a monthly newsletter.
Summarize this threat article concisely for a security leadership audience.

<<language>>

Return ONLY valid JSON (no markdown, no code blocks):
{
  "key_points": ["point 1 (max 20 words)", "point 2 (max 20 words)", "point 3 (max 20 words)"],
  "summary": "2-3 sentence paragraph covering what happened, who is affected, and the threat significance. Max 80 words."
}"""

_PROMPT_FROM_METADATA = """You are a Cyber Threat Intelligence analyst writing a monthly newsletter.
The full article text is unavailable. You receive only the metadata of this threat news item as JSON.
Summarise only what that metadata states. Do not add facts, numbers, names, dates, impacts or
attribution that are not in the metadata, and do not guess what the article probably says.
If the metadata supports fewer than 3 key points, return fewer (at least 1).

<<language>>

Return ONLY valid JSON (no markdown, no code blocks):
{
  "key_points": ["1 to 3 points, each max 20 words, each stated in the metadata"],
  "summary": "1-3 sentences restating only the metadata. Max 80 words."
}"""
"""Kedua prompt meminta bahasa dalam SATU panggilan yang sama dengan ringkasannya (tanpa panggilan
terjemahan kedua, jadi biaya per artikel tidak naik); blok bahasa + glosariumnya datang dari
`newsletter_glossary`. Kata "weekly" di prompt lama jadi "monthly": edisinya bulanan sekarang dan
kata itu menarik model ke "this week" di teks. Prompt metadata dulu meminta poin yang "plausible"
dan melarang menyebut paywall, jadi model mengarang isi artikel; sejak 2026-10-24 (spec LLM calls
self-healing 6.1) ia hanya meringkas metadata yang diberikan, boleh kurang dari 3 poin, dan
`body_source` di cache tetap menandai ringkasan yang begitu (peringatan "Summary from metadata
only" di composer tidak berubah)."""


def _prompt(template: str, language: SummaryLanguage) -> str:
    return template.replace(_LANGUAGE_SLOT, newsletter_glossary.language_instructions(language))


def _llm_summarize_with_body(
    title: str, body: str, *, language: SummaryLanguage
) -> tuple[dict[str, Any], str, dict[str, int]]:
    """Return (hasil parse, nama model, token usage); dua terakhir ikut disimpan di cache."""
    system = _prompt(_PROMPT_WITH_BODY, language)
    client, model_name = get_llm_client(task="newsletter_article")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Title: {title}\n\nArticle body:\n{body[:4000]}"},
        ],
        temperature=0,
        n=1,
        response_format={"type": "json_object"},
        prompt_version=prompt_version(system),
    )
    content = completion.choices[0].message.content
    result = parse_json_response(content or "{}")
    return result, model_name, usage_from(completion)


def _llm_summarize_from_metadata(
    article: dict[str, Any], *, language: SummaryLanguage
) -> tuple[dict[str, Any], str, dict[str, int]]:
    meta = {
        "title": article.get("title", ""),
        "source": article.get("source", ""),
        "news_type": article.get("news_type", ""),
        "mentioned_countries": article.get("mentioned_countries", []),
        "victim_countries": article.get("victim_countries", []),
        "impacted_industries": article.get("impacted_industries", []),
        "threat_actors": article.get("threat_actors", []),
        "ttps": [t.get("name", "") for t in article.get("ttps", [])],
    }
    system = _prompt(_PROMPT_FROM_METADATA, language)
    client, model_name = get_llm_client(task="newsletter_metadata")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(meta)},
        ],
        temperature=0,
        n=1,
        response_format={"type": "json_object"},
        prompt_version=prompt_version(system),
    )
    content = completion.choices[0].message.content
    result = parse_json_response(content or "{}")
    return result, model_name, usage_from(completion)


def _summary_from_row(row: NewsletterArticleSummary) -> dict[str, Any]:
    return {
        "key_points": row.key_points,
        "summary": row.summary,
        "body_source": row.body_source,
        "iocs": row.iocs,
        "cve_ids": row.cve_ids,
    }


async def generate_article_summary(
    session: AsyncSession,
    article: dict[str, Any],
    *,
    allowlist: dict[str, set[str]],
    regenerate: bool = False,
    language: SummaryLanguage = DEFAULT_SUMMARY_LANGUAGE,
) -> dict[str, Any]:
    """Ringkasan satu artikel, CACHE DULU (`newsletter_article_summaries`, kunci artikel + bahasa).

    Baris ada = langsung dipakai: tanpa fetch Playwright dan tanpa LLM. Tidak ada (atau
    `regenerate`) = fetch body, satu panggilan LLM, ekstrak IOC dan CVE id dari body itu, simpan.
    `language` menentukan bahasa ringkasan SEKALIGUS baris cache yang dibaca dan ditimpa: edisi
    Indonesia dan Inggris dari artikel yang sama tidak saling memakai atau menimpa.
    Return `{key_points, summary, body_source, iocs, cve_ids}`; `cve_ids` semua CVE di judul +
    body, BELUM disaring true-positive (lihat `_enrich_articles`).

    Hasil kosong (LLM membalas `{}`/tanpa isi) TIDAK di-cache: dulu itu gagal sementara yang
    dicoba lagi build berikutnya, sekarang akan nempel selamanya kalau disimpan.

    Catatan: gagal fetch sementara (timeout, jaringan) juga jadi ringkasan `metadata` yang
    di-cache; `body_source` menandainya dan `regenerate` adalah jalan keluarnya. IOC tidak lagi
    disaring allowlist di sini (parameter `allowlist` tinggal sisa): penandaan `auto_suppressed`
    terjadi saat `write_article_findings` menulis ke `iocs`."""
    repo = AsyncNewsletterRepo(session)
    if not regenerate:
        cached = await repo.get_article_summary(article["id"], language)
        if cached is not None:
            return _summary_from_row(cached)

    title = article.get("title", "")
    url = article.get("url", "")
    body, _ = await fetch_article_body(session, url, article.get("source", ""))
    if body:
        result, model, usage = await asyncio.to_thread(
            partial(_llm_summarize_with_body, title, body, language=language)
        )
        body_source = "fetched"
        iocs = await asyncio.to_thread(extract_iocs, body, url)
    else:
        result, model, usage = await asyncio.to_thread(
            partial(_llm_summarize_from_metadata, article, language=language)
        )
        body_source = "metadata"
        iocs = {}
    summary: dict[str, Any] = {
        "key_points": result.get("key_points") or [],
        "summary": result.get("summary") or "",
        "body_source": body_source,
        "iocs": iocs,
        "cve_ids": _extract_cve_ids(title, body),
    }
    if summary["key_points"] or summary["summary"]:
        await repo.upsert_article_summary(
            article_id=article["id"],
            language=language,
            model=model,
            token_usage=usage,
            **summary,
        )
    return summary


# ── CVE correlation ──────────────────────────────────────────────────────────


async def _get_tp_cve_ids(session: AsyncSession) -> set[str]:
    """True-positive CVE id set: CVE yang masih dianggap valid oleh minimal satu client (FP itu
    per `(cve_id, client_id)`, lihat `list_true_positive_cve_ids`). Newsletter bersifat global,
    jadi bukan per client. Port `_get_tp_cve_ids()` lama, yang hanya mengecualikan FP client
    "default": CVE yang FP di "default" tapi valid di client lain jadi tidak pernah ditandai, dan
    CVE yang di-FP-kan semua client selain "default" tetap ditandai."""
    return set(await AsyncCveTrackerRepo(session).list_true_positive_cve_ids())


def _extract_cve_ids(title: str, body: str | None) -> list[str]:
    """Semua CVE id di judul + body, huruf besar, unik, terurut, SEBELUM disaring true-positive.

    Inilah yang di-cache (`cve_ids`): isi artikel tidak berubah, sedangkan set true-positive
    berubah (FP ditandai, CVE baru di-track), jadi irisannya dihitung ulang tiap build."""
    text = title + " " + (body or "")
    return sorted({m.upper() for m in _RE_CVE.findall(text)})


def _find_cve_mentions(cve_ids: Collection[str], tp_cve_set: set[str]) -> list[str]:
    """Irisan CVE id artikel dengan set true-positive SEKARANG, terurut."""
    return sorted(set(cve_ids) & tp_cve_set)


# ── Article dict shape ───────────────────────────────────────────────────────


def _article_dict(article: Article) -> dict[str, Any]:
    return {
        "id": article.id,
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "posted_on": article.posted_on.isoformat() if article.posted_on else "",
        "news_type": article.news_type or "",
        "mentioned_countries": [c.country_code for c in article.countries if c.role == "mentioned"],
        "victim_countries": [c.country_code for c in article.countries if c.role == "victim"],
        "impacted_industries": [i.industry for i in article.industries],
        "threat_actors": [t.threat_actor for t in article.threat_actors],
        "ttps": [{"id": t.ttp_id, "name": t.ttp_name} for t in article.ttps],
    }


async def fetch_articles_by_ids(session: AsyncSession, ids: list[int]) -> dict[int, dict[str, Any]]:
    rows = await AsyncArticleRepo(session).get_by_ids(ids)
    return {aid: _article_dict(a) for aid, a in rows.items()}


# ── Newsletter assembly ───────────────────────────────────────────────────────


async def _enrich_articles(
    session: AsyncSession,
    articles: list[dict[str, Any]],
    *,
    regenerate: Collection[int] = (),
    language: SummaryLanguage = DEFAULT_SUMMARY_LANGUAGE,
) -> list[dict[str, Any]]:
    """Ringkasan + IOC + korelasi CVE per article -- SEKUENSIAL (bukan `asyncio.gather` kayak kode
    lama), karena masing-masing butuh browser Playwright sendiri + write DB
    lewat SATU AsyncSession yang gak aman dipakai concurrent (lihat
    catatan sama di `AsyncPIRRepo.list_pirs`).

    Dari cache kalau ada (`generate_article_summary`). Fungsi ini TIDAK menulis IOC dan sebutan
    CVE: itu `write_article_findings()`, dipanggil sekali saat draft dibuat. Dulu keduanya
    ditulis di sini, jadi tiap preview menambah `seen_count` IOC dan sumbernya lagi.

    `cve_mentions` = CVE id di cache yang masih true-positive SEKARANG; dihitung tiap build dan
    tidak di-cache, karena set true-positive berubah sementara isi artikel tidak. `regenerate` =
    id artikel yang melewati cache, SEKALI per build (kemunculan kedua artikel yang sama sudah
    memakai baris yang baru ditulis)."""
    tp_cve_set, allowlist = await asyncio.gather(
        _get_tp_cve_ids(session), _get_allowlist_sets(session)
    )

    pending_regenerate = set(regenerate)
    results = []
    for article in articles:
        article_id = article.get("id")
        summary = await generate_article_summary(
            session,
            article,
            allowlist=allowlist,
            regenerate=article_id in pending_regenerate,
            language=language,
        )
        pending_regenerate.discard(article_id)
        cve_hits = _find_cve_mentions(summary["cve_ids"], tp_cve_set)
        results.append(
            {
                **article,
                "key_points": summary["key_points"],
                "summary": summary["summary"],
                "body_source": summary["body_source"],
                "iocs": summary["iocs"],
                "cve_mentions": cve_hits,
                "possibly_exploited_wild": bool(cve_hits),
            }
        )
    return results


_IOC_TYPE_MAP = {
    "ips": "ip",
    "domains": "domain",
    "urls": "url",
    "urls_with_path": "url",
    "emails": "email",
    "sha256": "sha256",
    "sha1": "sha1",
    "md5": "md5",
    "cves": "cve",
}


async def write_article_findings(session: AsyncSession, context: dict[str, Any]) -> None:
    """Tulis IOC dan sebutan CVE dari artikel kartu-penuh edisi ini (data dari cache, tanpa fetch).

    Dipanggil SEKALI per draft, sesudah draft Outlook jadi dan baris histori disimpan. Tiap
    artikel sekali walau muncul dua kali di edisi. Baris compact tidak ikut: tanpa fetch tidak ada
    IOC, dan "ikut kalau kebetulan sudah di-cache" membuat hasilnya bergantung riwayat cache."""
    cve_repo = AsyncCveTrackerRepo(session)
    ioc_repo = AsyncIOCRepo(session)
    allowlist = await _get_allowlist_sets(session)
    seen: set[Any] = set()
    for article in (
        *context["highlights"],
        *context["apac"],
        *context["global_news"],
        *context["indonesia"],
    ):
        article_id = article.get("id")
        if article_id in seen:
            continue
        seen.add(article_id)
        for cid in article.get("cve_mentions", []):
            await cve_repo.add_newsletter_mention(
                cid,
                title=article.get("title", ""),
                url=article.get("url", ""),
                source=article.get("source", ""),
                mention_date=article.get("posted_on", ""),
            )
        for field_key, values in article.get("iocs", {}).items():
            for value in values:
                ioc_type = _IOC_TYPE_MAP.get(field_key, field_key)
                canon = canonical(ioc_type, value)
                await ioc_repo.upsert(
                    type=ioc_type,
                    value=canon,
                    source_url=article.get("url", ""),
                    source_name=article.get("source", ""),
                    article_id=article_id,
                    suppression_reason=allowlist_match(ioc_type, canon, allowlist),
                )


def _inject_analyst_note(article: dict[str, Any], notes: dict[str, str]) -> dict[str, Any]:
    note = notes.get(str(article.get("id", "")), "").strip()
    if note:
        return {**article, "analyst_note": note}
    return article


def _now() -> datetime.datetime:
    """Titik indirection tunggal buat `datetime.now()` -- dipatch lewat
    `patch.object(newsletter_service, "_now", ...)` di test snapshot supaya
    `week`/`year`/`generated_at` gak ikut geser tiap minggu kalender asli
    berganti (lihat `test_newsletter_router_snapshot.py`)."""
    return datetime.datetime.now(datetime.UTC)


def _default_period(now: datetime.datetime) -> tuple[datetime.date, datetime.date]:
    """Bulan kalender sebelumnya menurut zona laporan (`worker.report_utc_offset_hours`, WIB)."""
    return newsletter_edition.default_period(now, get_settings().worker.report_utc_offset_hours)


def _local_date(now: datetime.datetime) -> datetime.date:
    """Tanggal `now` di zona laporan (WIB), bukan UTC: Senin 02:00 UTC sudah Senin 09:00 bagi tim,
    dan 20:00 UTC sudah hari berikutnya."""
    offset = datetime.timedelta(hours=get_settings().worker.report_utc_offset_hours)
    return (now + offset).date()


def _compact_entry(
    article: dict[str, Any], cached: NewsletterArticleSummary | None
) -> dict[str, Any]:
    """Satu baris compact dari baris artikel: tanpa fetch dan tanpa LLM. Ringkasan di cache
    dipakai kalau ada (artikel yang pernah jadi kartu penuh), selain itu hanya metadata."""
    entry: dict[str, Any] = {
        "id": article.get("id"),
        "title": article.get("title", ""),
        "url": article.get("url", ""),
        "source": article.get("source", ""),
        "posted_on": article.get("posted_on", ""),
        "news_type": article.get("news_type", ""),
    }
    if cached is not None:
        entry["key_points"] = cached.key_points
        entry["summary"] = cached.summary
    return entry


async def build_newsletter_context(
    session: AsyncSession,
    highlights: dict[str, Any] | list[dict[str, Any]],
    apac: list[dict[str, Any]],
    global_news: list[dict[str, Any]],
    indonesia: list[dict[str, Any]],
    *,
    custom_css: str = "",
    custom_intro: str = "",
    custom_footer: str = "",
    notes: dict[str, str] | None = None,
    include_clusters: bool = False,
    cluster_days: int = 7,
    compact: Mapping[str, list[dict[str, Any]]] | None = None,
    period_start: datetime.date | None = None,
    period_end: datetime.date | None = None,
    regenerate: Collection[int] = (),
    language: SummaryLanguage = DEFAULT_SUMMARY_LANGUAGE,
) -> dict[str, Any]:
    """Susun konteks template dari artikel yang sudah dipilih. Menulis HANYA dua cache (ringkasan
    dan hint paywall); tidak ada baris `newsletters`, IOC, atau sebutan CVE (lihat modul ini).

    `highlights`: satu dict (bentuk lama) atau daftar dict. `apac`/`global_news`/`indonesia`:
    kartu penuh. `compact`: `{section: [artikel]}` baris compact, dari baris artikel (+ cache bila
    ada), tanpa fetch dan tanpa LLM. `period_*`: keduanya atau tidak sama sekali; kosong = bulan
    kalender sebelumnya menurut `_now()` di zona laporan.

    Kunci konteks yang dibaca template (`templates/newsletter_email.html`): `highlights` (semua kartu
    highlight; `highlight` = yang pertama, dipakai kartu histori lama), `apac`/`global_news`/
    `indonesia` (kartu penuh), `apac_compact`/`global_news_compact`/`indonesia_compact` (baris
    "Also Noted"), `period_label`/`period_range`/`published_label`, `language`, `custom_*`, dan
    `campaign_clusters`. Cluster kampanye masih memakai `cluster_days` (hitung mundur dari hari ini);
    pindah ke tanggal jendela menyusul."""
    notes = notes or {}
    compact = compact or {}
    highlight_cards = [highlights] if isinstance(highlights, dict) else list(highlights)
    if not highlight_cards:
        raise ValueError("newsletter butuh minimal satu highlight")
    all_articles = [*highlight_cards, *apac, *global_news, *indonesia]

    enriched = await _enrich_articles(
        session, all_articles, regenerate=regenerate, language=language
    )

    raw_clusters: list[dict[str, Any]] = []
    if include_clusters:
        campaigns = await campaign_service.get_recent_campaigns(
            session, days=cluster_days, min_size=3
        )
        raw_clusters = campaigns[:5]

    n = len(highlight_cards)
    highlights_enriched = [_inject_analyst_note(a, notes) for a in enriched[:n]]
    apac_count = len(apac)
    global_count = len(global_news)

    apac_enriched = [_inject_analyst_note(a, notes) for a in enriched[n : n + apac_count]]
    n += apac_count
    global_enriched = [_inject_analyst_note(a, notes) for a in enriched[n : n + global_count]]
    n += global_count
    indonesia_enriched = [_inject_analyst_note(a, notes) for a in enriched[n:]]

    cached = await AsyncNewsletterRepo(session).get_article_summaries(
        [a["id"] for section in newsletter_edition.SECTIONS for a in compact.get(section, [])],
        language,
    )
    compact_rows = {
        section: [_compact_entry(a, cached.get(a["id"])) for a in compact.get(section, [])]
        for section in newsletter_edition.SECTIONS
    }

    now = _now()
    iso_cal = now.isocalendar()
    if period_start is None or period_end is None:
        period_start, period_end = _default_period(now)

    campaign_clusters = [
        {
            "name": c.get("summary_title") or c.get("cluster_id", ""),
            "size": c.get("size", 0),
            "first_seen": c.get("first_seen", ""),
            "last_seen": c.get("last_seen", ""),
            "dominant_tas": c.get("dominant_tas", [])[:5],
            "dominant_industries": c.get("dominant_industries", [])[:3],
            "dominant_countries": c.get("dominant_countries", [])[:3],
            "attack_techniques": c.get("attack_techniques", [])[:5],
            "cve_ids": c.get("cve_ids", [])[:5],
        }
        for c in raw_clusters
    ]

    return {
        "week": iso_cal[1],
        "year": iso_cal[0],
        "generated_at": now.strftime("%Y-%m-%d %H:%M UTC"),
        "period_start": period_start,
        "period_end": period_end,
        "period_label": newsletter_edition.period_label(period_start, period_end),
        "period_range": newsletter_edition.period_range(period_start, period_end),
        "published_label": newsletter_edition.long_date(_local_date(now)),
        "language": language,
        "highlight": highlights_enriched[0],
        "highlights": highlights_enriched,
        "apac": apac_enriched,
        "global_news": global_enriched,
        "indonesia": indonesia_enriched,
        "apac_compact": compact_rows["apac"],
        "global_news_compact": compact_rows["global_news"],
        "indonesia_compact": compact_rows["indonesia"],
        "custom_css": custom_css,
        "custom_intro": custom_intro,
        "custom_footer": custom_footer,
        "campaign_clusters": campaign_clusters,
    }


def render_newsletter_html(context: dict[str, Any]) -> str:
    """HTML edisi dengan logo dirujuk lewat `cid:` -- versi yang DIKIRIM dan DISIMPAN. Untuk
    ditampilkan di browser lewat `newsletter_logo.with_data_uris()`."""
    env = make_env(_TEMPLATE_DIR)
    env.filters["short_date"] = newsletter_edition.short_date
    template = env.get_template(_NEWSLETTER_EMAIL_TEMPLATE)
    return template.render(
        platform_name=platform_name(), logo_cid=newsletter_logo.LOGO_CONTENT_ID, **context
    )


def body_sources(context: dict[str, Any]) -> dict[str, str]:
    """`{str(article_id): "fetched" | "metadata"}` untuk semua kartu penuh edisi ini (highlight dan
    tiga section). `metadata` = halamannya tidak terbaca (paywall) sehingga ringkasannya ditulis
    dari metadata saja; composer menandainya supaya analis memeriksanya. Baris compact tidak punya
    ringkasan baru, jadi tidak ada di sini. Kunci string karena JSON; artikel yang sama sebagai
    highlight dan kartu section memakai satu baris cache, jadi nilainya pasti sama."""
    cards = [
        *context["highlights"],
        *context["apac"],
        *context["global_news"],
        *context["indonesia"],
    ]
    return {str(card["id"]): card.get("body_source", "") for card in cards}


def html_size_bytes(html: str) -> int:
    """Ukuran HTML dalam byte UTF-8, yang dihitung Gmail. Ukur versi `cid:` (yang dikirim), bukan
    versi data URI untuk preview yang lebih besar beberapa KB."""
    return len(html.encode("utf-8"))


def size_warning(html_bytes: int) -> str | None:
    """Peringatan bagi analis kalau email mendekati batas potong Gmail, atau None."""
    if html_bytes <= HTML_WARN_BYTES:
        return None
    return (
        f"The email is {html_bytes / 1024:.0f} KB. Gmail clips messages above about "
        f"{GMAIL_CLIP_BYTES // 1024} KB and hides the rest behind a link, so readers may miss the "
        "end of the edition. Move cards to Also Noted or remove some before creating the draft."
    )


# ── Persistence ───────────────────────────────────────────────────────────────


def _strip_article(a: dict[str, Any]) -> dict[str, Any]:
    """Simpen field yang perlu buat rekonstruksi kartu histori doang --
    port `_strip_article()` lama."""
    return {
        "id": a.get("id"),
        "title": a.get("title", ""),
        "url": a.get("url", ""),
        "source": a.get("source", ""),
        "posted_on": a.get("posted_on", ""),
        "news_type": a.get("news_type", ""),
        "key_points": a.get("key_points", []),
        "summary": a.get("summary", ""),
        "body_source": a.get("body_source", ""),
        "iocs": a.get("iocs", {}),
        "cve_mentions": a.get("cve_mentions", []),
        "possibly_exploited_wild": a.get("possibly_exploited_wild", False),
    }


async def save_newsletter(
    session: AsyncSession, context: dict[str, Any], html: str, created_by: str
) -> int:
    sections = {
        "highlight": _strip_article(context["highlight"]),
        "apac": [_strip_article(a) for a in context["apac"]],
        "global_news": [_strip_article(a) for a in context["global_news"]],
        "indonesia": [_strip_article(a) for a in context["indonesia"]],
        # Kunci tier (PR 5): `highlight` di atas tetap yang pertama supaya kartu histori lama
        # jalan; baris compact sudah ringkas dari `_compact_entry`, tidak perlu di-strip lagi.
        "highlights": [_strip_article(a) for a in context["highlights"]],
        "apac_compact": context["apac_compact"],
        "global_news_compact": context["global_news_compact"],
        "indonesia_compact": context["indonesia_compact"],
    }
    row = await AsyncNewsletterRepo(session).save(
        week=context["week"],
        year=context["year"],
        period_start=context["period_start"],
        period_end=context["period_end"],
        generated_at=context["generated_at"],
        created_by=created_by,
        html=html,
        sections=sections,
    )
    return row.id
