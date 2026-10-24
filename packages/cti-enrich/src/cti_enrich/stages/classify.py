"""Stage 1: klasifikasi judul artikel lewat LLM -- port `articleValidator.
articleValidator()` (`ScraperNews/modules/articleValidator.py:17-151`).

Prompt aslinya disalin dari port itu (business logic, bukan boilerplate);
revisi Okt 2026 (0.8.5): indentasi dibuang, field `title` (echo yang tak dipakai
kode) dihapus, enam contoh batas ditambah -- aturan klasifikasi tetap. Cara parse
hasilnya juga diperbaiki -- kode lama:

    llm_response = completion.choices[0].message.json()
    json_string = llm_response.replace("\\n", "").replace("```", "").replace("json", "")
    outer_json = json.loads(json_string)
    outer_json = outer_json['content'].replace(...)
    json_data = json.loads(outer_json)

Dua masalah: (1) `.replace("json", "")` strip literal substring "json" dari
SELURUH envelope, termasuk isi field `title` yang di-echo balik LLM -- judul
yang ngandung kata "JSON" (mis. "New JSON Web Token Flaw") rusak; (2) parse
DUA LAPIS (`message.json()` lalu `json.loads()` lagi) cuma perlu karena gak
ada `response_format={"type":"json_object"}` -- `extractTTPs()` di file yang
SAMA udah pasang ini dan gak butuh hack apa pun. Fix: pasang
`response_format=json_object` di sini juga (extractTTPs, port di
`extract_ttps.py`, jadi acuan gaya yang bener), parse jawaban lewat
`parse_json_response()` (`cti_core.llm.client`) yang cuma strip wrapper
yang emang dikenal (fence ```json, atau `<think>` reasoning model -- bukan
string tebak-tebakan)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import structlog
from cti_core.llm.client import first_choice, get_llm_client, parse_json_response, store_param
from openai import RateLimitError

from cti_enrich.stages.llm_messages import build_messages

log = structlog.get_logger()

_PROMPT = """As a Threat Intelligence analyst, determine whether the following article title provides meaningful insight into the cybersecurity threat landscape.

Classification Instructions:

1. Cyber Threat Relevance:
- Classify as {"related_cyber": true} if the title discusses or implies:
- Cybersecurity incidents
- Threat actor activity
- Industry- or country-level cyber threat reports
- Attack trends
- Cyber-related regulations, risks, or exposure

- Classify as {"related_cyber": false} if the title is primarily about:
- Vendor marketing or promotions
- Product launches or sales
- Company financials or business operations unrelated to threat intelligence
- General IT news with no direct link to cybersecurity threats

- Include a "confidence" score from 0.0 to 1.0 to indicate how strongly the title suggests relevance to threat intelligence.
- Include a brief "reason" explaining your classification.

2. Industry Vertical Impact:
- Identify which industry verticals might be affected using the following list:
["Government & Public Sector", "Finance & Insurance", "Healthcare & Life Sciences", "Energy & Utilities", "Telecommunications", "Information Technology & Software", "Critical Infrastructure", "Retail & E-commerce", "Manufacturing & Industrial", "Education & Research", "Legal & Professional Services", "Media & Entertainment", "Transportation & Logistics", "Real Estate & Construction", "Non-profit & NGOs", "Aerospace & Defense Contractors", "Agriculture & Food", "Mining & Natural Resources", "Hospitality & Travel", "General"]

- Use up to 3 specific industries, or "General" if the title has broad relevance across sectors.
- Do NOT mix "General" with specific industries.

3. Security Technology & Best Practices Classification:
- Classify the title as "security_tech_best_practice": true only if it focuses on:
- Cybersecurity tools, techniques, or architectures (e.g., SIEM, EDR, IAM, SSO, MFA)
- Technical implementations (e.g., Zero Trust, network segmentation, threat modeling)
- Defensive strategies or best practices (e.g., DDoS mitigation, incident response planning)

- Do NOT classify as "security_tech_best_practice": true if the title:
- Discusses threat actors, attack campaigns, data breaches, vulnerabilities, or threat trends
- Is purely promotional, financial, or business-oriented
- Is a vendor report unless it emphasizes actionable implementation guidance

4. Country Role Classification:
- Identify countries or geopolitical entities mentioned in the title and classify each by role:

- "victim_countries": Countries/regions that were attacked, targeted, breached, or compromised.
    Examples: "Indonesia hit by ransomware" -> victim: Indonesia
    "APT targets Philippine government" -> victim: Philippines

- "actor_countries": Countries/regions attributed as the origin of the threat actor or attack.
    Examples: "China-linked APT attacks Indonesia" -> actor: China
    "North Korean hackers steal crypto" -> actor: North Korea

- Rules:
    - Use full English country names (e.g. "Indonesia" not "Indonesian")
    - If a country is both victim and actor in the same title, include in both lists
    - If role is ambiguous (e.g. bilateral cooperation, general regional report), return empty lists
    - Only include countries explicitly mentioned or strongly implied in the title
    - Return empty lists [] if no country role can be determined from the title alone

5. Incident Confirmation Classification:
- Classify as "confirmed_incident": true ONLY if the title indicates a SPECIFIC, CONFIRMED security incident:
    * Names a specific victim organization, government entity, agency, or individual targeted
    * AND/OR explicitly states confirmed impact: data breach occurred, data stolen/exposed, systems encrypted,
    services disrupted, financial loss, system compromise confirmed
    * The incident is presented as having already happened, not predicted or hypothetical

- Classify as "confirmed_incident": false if the title:
    * Is a general threat landscape report, analysis, forecast, or prediction
    * Discloses a CVE/vulnerability without confirmed exploitation against a named victim
    * Discusses a threat actor's general capabilities without referencing a named incident
    * Is a vendor advisory, best practices guide, or educational/research content
    * Uses speculative language: "could", "may", "researchers warn", "risk of"

- "incident_confidence": 0.0-1.0 -- confidence in the confirmed_incident classification:
    * 0.9-1.0: Named victim + confirmed impact + active/recent language
    * 0.7-0.9: Named victim present OR confirmed impact stated (but not both)
    * 0.4-0.7: Implicit victim or ambiguous impact language
    * 0.0-0.4: Weak signal, mostly analytical or predictive

- "incident_indicators": list of signals found, from:
    ["named_victim", "confirmed_breach", "ransomware_deployment", "data_exfiltration",
    "service_disruption", "financial_loss", "government_disclosure", "vendor_disclosure",
    "active_campaign", "zero_day_exploitation"]
    Return [] if confirmed_incident is false.

6. Victim Name Extraction:
- Extract the named victim organization, company, agency, or individual targeted in the incident.
- "victim_name": string or null
    * Set to the organization/entity name if the title names a specific victim (e.g. "MGM Resorts", "Change Healthcare", "Philippine National Police")
    * Set to null if no specific victim is named (general reports, vendor advisories, threat actor profiles, vulnerability disclosures without a named target)
    * Use the exact name as it appears in the title -- do not abbreviate or expand
    * If multiple victims are named, return the first/most prominent one

Boundary examples (title -> verdict):
- "Acme launches new endpoint security suite" -> {"related_cyber": false}
- "Globex earns ISO 27001 certification" -> {"related_cyber": false}
- "Initech named Security Vendor of the Year" -> {"related_cyber": false}
- "What the new data protection regulation means for your business" -> {"related_cyber": false}
- "Critical remote code execution flaw in Widget Server exploited in the wild" -> {"related_cyber": true}
- "Ransomware gang leaks customer data from regional hospital" -> {"related_cyber": true}

Respond strictly in the following JSON format:
{
"related_cyber": true/false,
"confidence": 0.0-1.0,
"reason": "Brief explanation",
"industries_impacted": ["list", "of", "industries"],
"security_tech_best_practice": true/false,
"victim_countries": ["list", "of", "victim", "countries"],
"actor_countries": ["list", "of", "actor", "origin", "countries"],
"confirmed_incident": true/false,
"incident_confidence": 0.0-1.0,
"incident_indicators": ["list", "of", "signals"],
"victim_name": "Organization Name or null"
}
"""


PROMPT_VERSION = hashlib.sha256(_PROMPT.encode()).hexdigest()[:8]
"""Sidik jari `_PROMPT` -- ikut disimpan di audit trail (`ClassifyResult.audit`)
biar keputusan lama bisa dibandingkan lintas revisi prompt (berubah otomatis
kalau prompt diedit, gak perlu dinaikkan manual)."""

_AUDIT_CONTENT_MAX = 4000
"""Batas karakter respons mentah per percobaan di audit trail -- jawaban
normal ~600 karakter; ini cuma pagar buat respons ngaco yang panjang."""


class OpenAIQuotaExhausted(RuntimeError):
    """Kuota/kredit OpenAI habis -- port `articleValidator.OpenAIQuotaExhausted`."""


@dataclass
class ClassifyResult:
    related_cyber: bool
    confidence: float = 0.0
    reason: str = ""
    industries_impacted: list[str] = field(default_factory=list)
    security_tech_best_practice: bool = False
    victim_countries: list[str] = field(default_factory=list)
    actor_countries: list[str] = field(default_factory=list)
    confirmed_incident: bool | None = None
    incident_confidence: float | None = None
    incident_indicators: list[str] = field(default_factory=list)
    victim_name: str | None = None
    audit: dict[str, Any] = field(default_factory=dict)
    """Audit trail respons LLM (`persist()` -> `raw_enrichment["classify"]`):
    model, `PROMPT_VERSION`, dan SETIAP percobaan (isi mentah + `finish_reason`),
    termasuk percobaan gagal yang akhirnya diselamatkan retry. Kosong di
    pemanggil yang gak butuh (test/fixture)."""


def resolve_industries(industries_impacted: list[str]) -> list[str]:
    """Port `nlp.py:324-331` -- "General" kalau MUNCUL SELALU menang
    sendirian, gak digabung sama industri spesifik lain walau keduanya ada
    di respons GPT (prompt minta jangan campur, tapi gak dipaksa skema).
    Dipakai `stages/persist.py` (list buat `ArticleIndustry`) DAN
    `pipeline.py` (display string buat pesan Telegram) -- satu logika,
    dua pemakai, biar gak drift."""
    return ["General"] if "General" in industries_impacted else industries_impacted


_MAX_TOKENS = 3000
"""Kode lama (`articleValidator.py`) gak pasang `max_tokens` sama sekali --
gak masalah waktu itu, OpenAI asli jawab langsung tanpa reasoning tokens.
Gateway dev (9router) modelnya reasoning-style, nulis blok `<think>` yang
gampang makan 300+ token SEBELUM jawaban JSON beneran mulai (ketauan pas
korpus test Fase 5: tanpa `max_tokens` eksplisit, server motong respons di
tengah `<think>`, JSON-nya gak pernah lahir -- `finish_reason` "length",
`parse_json_response()` gagal total, bukan gara-gara bug parsing). Nilai
ini generous secukupnya biar reasoning + 12 field JSON muat -- diverifikasi
langsung: title yang tadinya kepotong sekarang `finish_reason="stop"`."""


_MAX_ATTEMPTS = 3
"""2 retry -- respons kosong/rusak dari gateway reasoning-model itu
transien (ketauan di korpus test Fase 5: rate kegagalan per-panggilan
kira-kira 15-25%, gak ada pola jelas per-title, keliatan kayak hiccup
jaringan/server biasa, bukan input yang genuinely bikin model nyerah).
2 attempt (`_MAX_ATTEMPTS=2`) masih nyisain kegagalan ganda ~kadang --
3 attempt nurunin peluang GAGAL SEMUA jadi kecil banget tanpa retry
berlebihan. Sama semangat retry `TransientFetchError` di `cti_scraper`
(Fase 3) -- gagal transien direspons retry, bukan crash keras. Residual
failure rate SETELAH retry (harusnya kecil) bukan bug yang harus dikejar
ke nol -- itu batas realistis gateway LLM dev yang gak 100% reliable,
dilaporkan apa adanya di hasil korpus test, bukan disembunyiin."""


def classify(title: str, *, task: str = "classify") -> ClassifyResult:
    """`task` menamai panggilan di log `llm_calls`; tweet memakai `classify_tweet`."""
    client, model_name = get_llm_client(task=task)
    last_error: json.JSONDecodeError | None = None
    attempts: list[dict[str, Any]] = []
    for attempt in range(_MAX_ATTEMPTS):
        try:
            completion = client.chat.completions.create(
                model=model_name,
                response_format={"type": "json_object"},
                # Percobaan 1 verbatim; retry pakai bentuk yang dikuatkan (lihat
                # `llm_messages.py` -- persona "Kiro" di gateway dev).
                messages=build_messages(_PROMPT, title, attempt=attempt, tag="article_title"),
                temperature=0,
                n=1,
                max_tokens=_MAX_TOKENS,
                prompt_version=PROMPT_VERSION,
                **store_param(),
            )
        except RateLimitError as e:
            if any(
                code in str(e)
                for code in (
                    "insufficient_funds",
                    "billing_hard_limit_reached",
                    "exceeded your current quota",
                )
            ):
                raise OpenAIQuotaExhausted(f"OpenAI credit exhausted: {e}") from e
            raise

        choice = first_choice(completion)
        content = choice.message.content
        entry: dict[str, Any] = {
            "attempt": attempt,
            "finish_reason": choice.finish_reason,
            "content": (content or "")[:_AUDIT_CONTENT_MAX],
        }
        attempts.append(entry)
        try:
            data = parse_json_response(content)
            entry["parsed"] = True
            break
        except json.JSONDecodeError as e:
            entry["parsed"] = False
            last_error = e
    else:
        assert last_error is not None
        # Gagal total: catatan DB gak ada (exception diteruskan ke Celery),
        # jadi respons mentahnya masuk log -- bahan audit kasus kayak "Kiro".
        log.warning("classify_json_failed", title=title[:200], model=model_name, attempts=attempts)
        raise last_error
    return ClassifyResult(
        related_cyber=bool(data.get("related_cyber")),
        confidence=float(data.get("confidence", 0.0) or 0.0),
        reason=data.get("reason", ""),
        industries_impacted=data.get("industries_impacted", []) or [],
        security_tech_best_practice=bool(data.get("security_tech_best_practice")),
        victim_countries=data.get("victim_countries", []) or [],
        actor_countries=data.get("actor_countries", []) or [],
        confirmed_incident=data.get("confirmed_incident"),
        incident_confidence=data.get("incident_confidence"),
        incident_indicators=data.get("incident_indicators", []) or [],
        victim_name=data.get("victim_name"),
        audit={"model": model_name, "prompt_version": PROMPT_VERSION, "attempts": attempts},
    )
