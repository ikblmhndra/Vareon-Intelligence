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
heavy per artikel (bukan bug, port apa adanya)."""

from __future__ import annotations

import asyncio
import datetime
import json
import re
from pathlib import Path
from typing import Any

from cti_core.config import platform_name
from cti_core.db.models.article import Article
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.ioc_reference import AsyncIocAllowlistRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from cti_core.ioc.extractor import extract_iocs
from cti_core.llm.client import get_llm_client, parse_json_response
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import campaign as campaign_service
from cti_api.services.email_env import make_env

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_NEWSLETTER_EMAIL_TEMPLATE = "newsletter_email.html"

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


def _llm_summarize_with_body(title: str, body: str) -> dict[str, Any]:
    prompt = """You are a Cyber Threat Intelligence analyst writing a weekly newsletter.
Summarize this threat article concisely for a security leadership audience.

Return ONLY valid JSON (no markdown, no code blocks):
{
  "key_points": ["point 1 (max 20 words)", "point 2 (max 20 words)", "point 3 (max 20 words)"],
  "summary": "2-3 sentence paragraph covering what happened, who is affected, and the threat significance. Max 80 words."
}"""
    client, model_name = get_llm_client()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Title: {title}\n\nArticle body:\n{body[:4000]}"},
        ],
        temperature=0,
        n=1,
    )
    content = completion.choices[0].message.content
    result = parse_json_response(content or "{}")
    return result


def _llm_summarize_from_metadata(article: dict[str, Any]) -> dict[str, Any]:
    prompt = """You are a Cyber Threat Intelligence analyst writing a weekly newsletter.
Based on available metadata, generate plausible key points and a summary for this threat news item.
Note: full article text is unavailable (possible paywall).

Return ONLY valid JSON (no markdown, no code blocks):
{
  "key_points": ["point 1 (max 20 words)", "point 2 (max 20 words)", "point 3 (max 20 words)"],
  "summary": "2-3 sentence paragraph covering the likely threat context based on metadata. Max 80 words. Do not mention that the article was paywalled."
}"""
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
    client, model_name = get_llm_client()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(meta)},
        ],
        temperature=0,
        n=1,
    )
    content = completion.choices[0].message.content
    result = parse_json_response(content or "{}")
    return result


async def generate_article_summary(article: dict[str, Any], body: str | None) -> dict[str, Any]:
    if body:
        result = await asyncio.to_thread(_llm_summarize_with_body, article.get("title", ""), body)
        result["body_source"] = "fetched"
    else:
        result = await asyncio.to_thread(_llm_summarize_from_metadata, article)
        result["body_source"] = "metadata"
    return result


# ── CVE correlation ──────────────────────────────────────────────────────────


async def _get_tp_cve_ids(session: AsyncSession) -> set[str]:
    """True-positive CVE id set: CVE yang masih dianggap valid oleh minimal satu client (FP itu
    per `(cve_id, client_id)`, lihat `list_true_positive_cve_ids`). Newsletter bersifat global,
    jadi bukan per client. Port `_get_tp_cve_ids()` lama, yang hanya mengecualikan FP client
    "default": CVE yang FP di "default" tapi valid di client lain jadi tidak pernah ditandai, dan
    CVE yang di-FP-kan semua client selain "default" tetap ditandai."""
    return set(await AsyncCveTrackerRepo(session).list_true_positive_cve_ids())


def _find_cve_mentions(title: str, body: str | None, tp_cve_set: set[str]) -> list[str]:
    text = title + " " + (body or "")
    found = {m.upper() for m in _RE_CVE.findall(text)}
    return sorted(found & tp_cve_set)


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
    session: AsyncSession, articles: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fetch body + generate summary + IOC extraction + CVE correlation
    per article -- SEKUENSIAL (bukan `asyncio.gather` kayak kode lama),
    karena masing-masing butuh browser Playwright sendiri + write DB
    lewat SATU AsyncSession yang gak aman dipakai concurrent (lihat
    catatan sama di `AsyncPIRRepo.list_pirs`)."""
    tp_cve_set, allowlist = await asyncio.gather(
        _get_tp_cve_ids(session), _get_allowlist_sets(session)
    )

    results = []
    for article in articles:
        body, _ = await fetch_article_body(
            session, article.get("url", ""), article.get("source", "")
        )
        summary = await generate_article_summary(article, body)
        if body:
            iocs = await asyncio.to_thread(extract_iocs, body, article.get("url", ""), allowlist)
        else:
            iocs = {}
        cve_hits = _find_cve_mentions(article.get("title", ""), body, tp_cve_set)
        if cve_hits:
            posted_on = article.get("posted_on", "")
            for cid in cve_hits:
                await AsyncCveTrackerRepo(session).add_newsletter_mention(
                    cid,
                    title=article.get("title", ""),
                    url=article.get("url", ""),
                    source=article.get("source", ""),
                    mention_date=posted_on,
                )
        if iocs:
            ioc_repo = AsyncIOCRepo(session)
            for field_key, values in iocs.items():
                for value in values:
                    await ioc_repo.upsert(
                        type=_IOC_TYPE_MAP.get(field_key, field_key),
                        value=value,
                        source_url=article.get("url", ""),
                        source_name=article.get("source", ""),
                        article_id=article.get("id"),
                    )
        results.append(
            {
                **article,
                **summary,
                "iocs": iocs,
                "cve_mentions": cve_hits,
                "possibly_exploited_wild": bool(cve_hits),
            }
        )
    return results


_IOC_TYPE_MAP = {
    "ips": "ip",
    "domains": "domain",
    "urls": "url",
    "urls_with_path": "url_with_path",
    "emails": "email",
    "sha256": "sha256",
    "sha1": "sha1",
    "md5": "md5",
    "cves": "cve",
}


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


async def build_newsletter_context(
    session: AsyncSession,
    highlight: dict[str, Any],
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
) -> dict[str, Any]:
    notes = notes or {}
    all_articles = [highlight, *apac, *global_news, *indonesia]

    enriched = await _enrich_articles(session, all_articles)

    raw_clusters: list[dict[str, Any]] = []
    if include_clusters:
        campaigns = await campaign_service.get_recent_campaigns(
            session, days=cluster_days, min_size=3
        )
        raw_clusters = campaigns[:5]

    highlight_enriched = _inject_analyst_note(enriched[0], notes)
    apac_count = len(apac)
    global_count = len(global_news)

    n = 1
    apac_enriched = [_inject_analyst_note(a, notes) for a in enriched[n : n + apac_count]]
    n += apac_count
    global_enriched = [_inject_analyst_note(a, notes) for a in enriched[n : n + global_count]]
    n += global_count
    indonesia_enriched = [_inject_analyst_note(a, notes) for a in enriched[n:]]

    now = _now()
    iso_cal = now.isocalendar()

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
        "highlight": highlight_enriched,
        "apac": apac_enriched,
        "global_news": global_enriched,
        "indonesia": indonesia_enriched,
        "custom_css": custom_css,
        "custom_intro": custom_intro,
        "custom_footer": custom_footer,
        "campaign_clusters": campaign_clusters,
    }


def render_newsletter_html(context: dict[str, Any]) -> str:
    env = make_env(_TEMPLATE_DIR)
    template = env.get_template(_NEWSLETTER_EMAIL_TEMPLATE)
    return template.render(platform_name=platform_name(), **context)


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
    }
    row = await AsyncNewsletterRepo(session).save(
        week=context["week"],
        year=context["year"],
        generated_at=context["generated_at"],
        created_by=created_by,
        html=html,
        sections=sections,
    )
    return row.id
