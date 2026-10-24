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
import json
import re
from pathlib import Path
from typing import Any

from cti_alerts.mailer import create_graph_draft
from cti_core.config import platform_name
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.llm.client import get_llm_client, parse_json_response
from cti_core.llm.usage import prompt_version
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services.email_env import make_env

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_TEMPLATE_FILE = "cve_notification_email.html"

_TZ_UTC7 = datetime.timezone(datetime.timedelta(hours=7))

_SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 60, "LOW": 90}
_SEV_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


# ── LLM helpers (port dari `cveValidator.py`/legacy service) ─────────────────

_VALIDATOR_PROMPT = """You are a Cyber Threat Intelligence manager with 7+ years of expertise.

Analyze the CVE data (a JSON object) and return ONLY a valid JSON object with these fields. No markdown, no code blocks.
Use only facts present in the CVE data; do not invent versions, products or exploitation status.

{
  "product_name": "The possible impacted product name",
  "summary": "Max 50 words describing what attackers can do or what data is exposed",
  "executive_summary": "2-3 sentences for non-technical leadership",
  "risk_context": "1-2 paragraphs (narrative prose, no lists) describing risks if NOT patched. Cover: business impact, compliance violations, exploitation likelihood.",
  "primary_remediation_action": [
    {"version_branch": "affected version branch", "fixed_version": "safe version to upgrade to"}
  ],
  "alternative_remediation_action": [
    "5-7 compensating controls if patching delayed, each max 30 words"
  ],
  "impact": "The impact if CVE exploited"
}

CRITICAL: Return ONLY the JSON object. Start with { and end with }."""

_MITIGATION_PROMPT = """You are a Cyber Threat Intelligence manager with 7+ years of expertise.

Return ONLY a valid JSON object:
{
  "alternative_remediation_action": [
    "Provide 5 to 7 genuinely distinct compensating controls if patching is delayed; fewer distinct controls are better than padded or repeated ones",
    "Each item must be 20-30 words and actionable",
    "NO DUPLICATES - each control must address a different security layer"
  ]
}

CRITICAL: Return ONLY the JSON object. Start with { and end with }."""

# Batas panjang input validator: dulu `str(cve_data)` (repr Python, tanpa batas) sehingga CVE
# dengan ratusan baris `affected`/`reference` mengirim puluhan ribu karakter.
_CVE_INPUT_MAX_CHARS = 6000
_CVE_INPUT_TEXT_CAP = 2000
_CVE_INPUT_LIST_CAP = 20

_TIMELINE = {
    "CRITICAL": "CRITICAL (24-48h)",
    "HIGH": "HIGH (7 days)",
    "MEDIUM": "MEDIUM (30 days)",
    "LOW": "LOW (90 days)",
}
_ATTACK_COMPLEXITY = {"L": "Low", "H": "High"}
_AC_RE = re.compile(r"(?:^|/)AC:([A-Z])")


def computed_fields(cve_data: dict[str, Any]) -> dict[str, str]:
    """Field yang dulu diminta ke model padahal bisa dihitung dari data (spec 2026-10-24 6.1
    butir 4); hasilnya menimpa apa pun yang dikembalikan model. Severity kosong/tak dikenal
    pakai aturan MEDIUM; `affected_version` digabung dari `affected` (baris `cve_affected`)."""
    match = _AC_RE.search(cve_data.get("cvss_vector") or "")
    complexity = _ATTACK_COMPLEXITY.get(match.group(1), "Unknown") if match else "Unknown"
    severity = (cve_data.get("cve_severity") or "").strip().upper()
    affected = [str(a).strip() for a in cve_data.get("affected") or [] if str(a).strip()]
    return {
        "attack_complexity": complexity,
        "recommended_timeline": _TIMELINE.get(severity, _TIMELINE["MEDIUM"]),
        "affected_version": "; ".join(affected) if affected else "Unknown",
        "analysis_timestamp": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
    }


def _clip(value: Any, text_cap: int, list_cap: int) -> Any:
    if isinstance(value, str):
        return value[:text_cap]
    if isinstance(value, list):
        return [_clip(v, text_cap, list_cap) for v in value[:list_cap]]
    return value


def _cve_user_message(cve_data: dict[str, Any]) -> str:
    """JSON valid, maksimal `_CVE_INPUT_MAX_CHARS`: teks dan list dipotong SEBELUM serialisasi
    (bukan memotong string JSON-nya), batasnya dikecilkan bertahap sampai muat."""
    text_cap, list_cap = _CVE_INPUT_TEXT_CAP, _CVE_INPUT_LIST_CAP
    while True:
        payload = {k: _clip(v, text_cap, list_cap) for k, v in cve_data.items()}
        msg = json.dumps(payload, ensure_ascii=False, default=str)
        if len(msg) <= _CVE_INPUT_MAX_CHARS or text_cap == 0:
            return msg
        text_cap //= 2
        list_cap = max(1, list_cap // 2)


def _llm_cve_validator(cve_data: dict[str, Any]) -> dict[str, Any]:
    client, model_name = get_llm_client(task="cve_email_validate")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _VALIDATOR_PROMPT},
            {"role": "user", "content": _cve_user_message(cve_data)},
        ],
        temperature=0,
        n=1,
        prompt_version=prompt_version(_VALIDATOR_PROMPT),
    )
    content = completion.choices[0].message.content
    result = parse_json_response(content or "{}")
    result.update(computed_fields(cve_data))
    return result


def _dedup_mitigation(mitigation_list: list[str]) -> dict[str, Any]:
    client, model_name = get_llm_client(task="cve_email_mitigation")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _MITIGATION_PROMPT},
            {"role": "user", "content": str(mitigation_list)},
        ],
        temperature=0,
        n=1,
        prompt_version=prompt_version(_MITIGATION_PROMPT),
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

    client, model_name = get_llm_client(task="cve_email_risk")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": risk_str},
        ],
        temperature=0,
        n=1,
        prompt_version=prompt_version(prompt),
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
