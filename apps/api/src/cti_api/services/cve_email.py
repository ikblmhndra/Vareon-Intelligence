"""Port `ScraperNewsWeb/app/services/cve_email_service.py`. Fase 7.4
Grup C (2026-09-23). Draft notifikasi CVE (3 panggilan LLM buat
validasi+dedup + render Jinja2 + draft Microsoft Graph), dipicu
`POST /api/cve/draft-email` dengan `cve_ids` + `ticket_id` opsional
(auto-generate lewat `AsyncCveTicketRepo.get_next_ticket_id()` kalau
kosong -- port `router` lama, bukan service ini).

**Graph-only, SMTP gak diport** -- keputusan yang sama kayak
`cti_alerts.mailer` (Bagian 4): `GraphSettings` udah ada, `SmtpSettings`
gak ada di config baru, `.env` produksi cuma isi kredensial Graph.
`create_graph_draft()` (`cti_alerts.mailer`, di-generalize namanya dari
`send_newsletter_email` biar Grup C ini bisa numpang, bukan duplikat
ulang logic Graph API) yang dipakai buat dispatch-nya.

`vendor_advisory_url` di sini CUMA `url` polos, TANPA suffix `(tags)`
kayak legacy (`ref["url"] + f" ({tags})"`) -- `CveReference` (Fase 2)
emang cuma nyimpen `url`, `tags` gak dinormalisasi ke tabel anak. Gap
kecil yang didokumentasikan, bukan bug -- cosmetic doang, gak
mempengaruhi isi/kebenaran notifikasi.

3 panggilan LLM (`_llm_cve_validator` per-CVE, `_dedup_mitigation`+
`_dedup_risk_context` sekali per-batch di akhir) SENGAJA sync, dibungkus
`asyncio.to_thread()` di caller -- pola yang sama kayak `newsletter.py`
(`generate_article_summary`), bukan `run_in_executor` legacy (API
`asyncio` yang sama, `to_thread` cuma alias modern).

**TODO sebelum deploy ke production**: `draft_email_for_cves()` BELUM
live-tested terhadap LLM/Graph API asli -- keputusan user (2026-09-23,
Grup C) buat nunda live-test (ada cost token + bikin draft asli di
mailbox) sampai deket waktu deploy. Verifikasi sekarang cuma mocked
integration test (`tests/integration/test_cve_email_service.py`) --
JANGAN anggap fitur ini "fully verified" sebelum live-test beneran
kejadian."""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from typing import Any

from cti_alerts.mailer import create_graph_draft
from cti_core.config import platform_name
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.llm.client import get_llm_client, parse_json_response
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services.email_env import make_env

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_TEMPLATE_FILE = "cve_notification_email.html"

_TZ_UTC7 = datetime.timezone(datetime.timedelta(hours=7))

_SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 60, "LOW": 90}
_SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


# ── LLM helpers (port apa adanya dari `cveValidator.py`/legacy service) ───────


def _llm_cve_validator(cve_data: dict[str, Any]) -> dict[str, Any]:
    prompt = """You are a Cyber Threat Intelligence manager with 7+ years of expertise.

Analyze the CVE data and return ONLY a valid JSON object with these fields. No markdown, no code blocks.

{
  "product_name": "The possible impacted product name",
  "summary": "Max 50 words describing what attackers can do or what data is exposed",
  "executive_summary": "2-3 sentences for non-technical leadership",
  "risk_context": "1-2 paragraphs (narrative prose, no lists) describing risks if NOT patched. Cover: business impact, compliance violations, exploitation likelihood.",
  "primary_remediation_action": [
    {"version_branch": "affected version branch", "fixed_version": "safe version to upgrade to"}
  ],
  "affected_version": "version X or below is affected based on 'affected' key",
  "alternative_remediation_action": [
    "5-7 compensating controls if patching delayed, each max 30 words"
  ],
  "attack_complexity": "Low or High from cvss_vector AC:",
  "impact": "The impact if CVE exploited",
  "recommended_timeline": "CRITICAL (24-48h) / HIGH (7 days) / MEDIUM (30 days) / LOW (90 days)",
  "analysis_timestamp": "ISO 8601 timestamp"
}

CRITICAL: Return ONLY the JSON object. Start with { and end with }."""

    client, model_name = get_llm_client()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": str(cve_data)},
        ],
        temperature=0,
        n=1,
    )
    content = completion.choices[0].message.content
    result = parse_json_response(content or "{}")
    return result


def _dedup_mitigation(mitigation_list: list[str]) -> dict[str, Any]:
    prompt = """You are a Cyber Threat Intelligence manager with 7+ years of expertise.

Return ONLY a valid JSON object:
{
  "alternative_remediation_action": [
    "Provide EXACTLY 7 unique, non-overlapping compensating controls if patching is delayed",
    "Each item must be 20-30 words and actionable",
    "NO DUPLICATES - each control must address a different security layer"
  ]
}

CRITICAL: Return ONLY the JSON object. Start with { and end with }."""

    client, model_name = get_llm_client()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": str(mitigation_list)},
        ],
        temperature=0,
        n=1,
    )
    content = completion.choices[0].message.content
    result = parse_json_response(content or "{}")
    return result


def _dedup_risk_context(risk_str: str) -> str:
    prompt = """You are a Cyber Threat Intelligence analyst writing impact assessments.

Generate a concise HTML impact statement (max 100 words) covering:
1. Direct technical impact
2. Business consequences (data breach, financial loss, operational disruption)
3. Exploitation likelihood based on attack complexity
4. Time-sensitive risk factors

Wrap important phrases in <strong> tags. Return only the HTML fragment, no surrounding tags."""

    client, model_name = get_llm_client()
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": risk_str},
        ],
        temperature=0,
        n=1,
    )
    return completion.choices[0].message.content or ""


# ── Email rendering ───────────────────────────────────────────────────────────


def _render_email(context: dict[str, Any]) -> str:
    env = make_env(_TEMPLATE_DIR)
    return env.get_template(_TEMPLATE_FILE).render(platform_name=platform_name(), **context)


def _highest_severity(cves: list[dict[str, Any]]) -> str:
    for sev in _SEV_ORDER:
        if any(c["severity"].upper() == sev for c in cves):
            return sev
    return "LOW"


# ── Main entry point (dipanggil router `cve`) ─────────────────────────────────


async def draft_email_for_cves(
    session: AsyncSession, cve_ids: list[str], ticket_id: str, *, client_id: str
) -> dict[str, Any]:
    """Hanya baris `cve_tracker` milik `client_id`: tanpa itu CVE yang di-track beberapa client
    muncul dobel di email dan `product_name` (dari baris pertama) bisa milik client lain."""
    cves = await AsyncCveTrackerRepo(session).get_by_cve_ids(cve_ids, client_id=client_id)
    if not cves:
        raise ValueError("No CVE documents found for provided IDs")

    product_name = (cves[0].tech or "Unknown Product").replace("%20", " ").title()

    accumulated: dict[str, Any] = {
        "product_name": product_name,
        "cves": [],
        "remediation_fixes": [],
        "mitigations": [],
        "vendor_advisory_url": [],
        "risk_parts": [],
    }

    for cve in cves:
        cve_data = {
            "cve_id": cve.cve_id,
            "tech": cve.tech,
            "summary": cve.summary,
            "cve_severity": cve.cve_severity,
            "cve_score": cve.cve_score,
            "cvss_vector": cve.cvss_vector,
            "published": cve.published.isoformat() if cve.published else "",
            "solutions": cve.solutions,
            "affected": [a.affected for a in cve.affected],
            "reference": [r.url for r in cve.references],
        }
        validated = await asyncio.to_thread(_llm_cve_validator, cve_data)

        accumulated["cves"].append(
            {
                "id": cve.cve_id,
                "severity": cve.cve_severity or "MEDIUM",
                "impact": (validated.get("summary") or "").replace("\xa0", " "),
            }
        )

        for fix in validated.get("primary_remediation_action", []):
            if isinstance(fix, dict) and fix not in accumulated["remediation_fixes"]:
                accumulated["remediation_fixes"].append(fix)

        for alt in validated.get("alternative_remediation_action", []):
            if alt not in accumulated["mitigations"]:
                accumulated["mitigations"].append(alt)

        for ref in cve.references:
            if ref.url not in accumulated["vendor_advisory_url"]:
                accumulated["vendor_advisory_url"].append(ref.url)

        risk = validated.get("risk_context", "")
        if risk and risk not in accumulated["risk_parts"]:
            accumulated["risk_parts"].append(risk)

    deduped_mit = await asyncio.to_thread(_dedup_mitigation, accumulated["mitigations"])
    mitigations = deduped_mit.get("alternative_remediation_action", accumulated["mitigations"])

    risk_html = await asyncio.to_thread(_dedup_risk_context, " || ".join(accumulated["risk_parts"]))

    today = datetime.datetime.now(_TZ_UTC7)
    highest_sev = _highest_severity(accumulated["cves"])
    remediation_days = _SLA_DAYS.get(highest_sev, 90)

    context = {
        "cve_count": len(accumulated["cves"]),
        "product_name": accumulated["product_name"],
        "due_date": (today + datetime.timedelta(days=remediation_days)).strftime("%B %d, %Y"),
        "plan_date": (today + datetime.timedelta(days=3)).strftime("%B %d, %Y"),
        "email_date": today.strftime("%B %d, %Y"),
        "highest_severity": highest_sev,
        "remediation_days": remediation_days,
        "cves": accumulated["cves"],
        "risk_context": risk_html,
        "remediation_fixes": accumulated["remediation_fixes"],
        "mitigations": mitigations,
        "vendor_advisory_url": accumulated["vendor_advisory_url"],
        "timeline_actions": [
            {
                "description": "CTI Team Detect CVE",
                "owner": "CTI Team",
                "due_date": today.strftime("%b %d, %Y"),
                "critical": False,
            },
            {
                "description": "Acknowledge Receipt",
                "owner": "Product Owner",
                "due_date": (today + datetime.timedelta(days=1)).strftime("%b %d, %Y"),
                "critical": False,
            },
            {
                "description": "Submit Remediation Plan",
                "owner": "Product Owner",
                "due_date": "",
                "critical": False,
            },
            {
                "description": "Complete Patching/Remediation",
                "owner": "Product Owner",
                "due_date": "",
                "critical": True,
            },
            {
                "description": "Verification",
                "owner": "CTI Team",
                "due_date": "Maximum Day + 3 After Complete Patching",
                "critical": False,
            },
        ],
        "tracking_id": ticket_id,
        "classification": "Internal - Confidential",
    }

    html_content = _render_email(context)
    subject = (
        f"[ACTION REQUIRED] {len(accumulated['cves'])} CVE(s) in {accumulated['product_name']}"
    )
    email_id = await asyncio.to_thread(create_graph_draft, html_content, subject)

    return {
        "email_id": email_id,
        "method": "graph",
        "subject": subject,
        "cve_count": len(accumulated["cves"]),
    }
