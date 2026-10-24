"""Port `ScraperNewsWeb/app/services/ta_profile_service.py` (fungsi LLM +
cross-ref CVE-nya) -- `generate_ta_profile()`/`get_ta_profile()`. Fase
7.3 (router `ta_groups`, Bagian 3).

Klien LLM lewat `cti_core.llm.client.get_llm_client()` -- Fase 7.5, module
ini gak numpang duplikat sempit sendiri lagi (lihat docstring
`cti_core.llm.client` soal relokasi)."""

from __future__ import annotations

import asyncio
import datetime
import re
from typing import Any

from cti_core.db.models.article import Article, ArticleThreatActor
from cti_core.db.repositories.attack import AsyncAttackQueryRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo, build_ta_name_pattern
from cti_core.llm.client import get_llm_client, parse_json_response
from cti_core.llm.usage import prompt_version
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_SYSTEM_PROMPT = """You are a Senior Cyber Threat Intelligence Analyst. Your task is to produce a structured,
analyst-grade threat actor profile based on the input provided (report text, article,
threat intelligence source, or actor name).

The profile must be grounded in verified reporting. For any field where information is
unavailable or unconfirmed, use null and set the corresponding confidence field to "low"
or "unknown". Do not fabricate or infer beyond what is stated in the source material.

The user message holds the provided context: the MITRE ATT&CK record matched to this actor
(group ID, aliases, software and techniques), or a note that no ATT&CK group matches, and the
titles of recent articles about the actor. The fields capability_assessment.known_malware,
capability_assessment.exploited_vulnerabilities, capability_assessment.attack_techniques and
infrastructure.known_iocs must be filled only from the provided context: software listed there,
CVE IDs that appear there, technique IDs listed there, and indicators that appear there. When
the context has none, leave them empty ([] or empty lists per tactic / IOC type). Do not add
items from general knowledge to these fields.

Return ONLY a valid JSON object — no preamble, no markdown fencing, no commentary.

Use this exact schema:

{
  "profile_metadata": {
    "generated_at": "<ISO 8601 timestamp>",
    "source_document": "<title or URL of source>",
    "analyst_confidence": "<low | medium | high>",
    "tlp_marking": "<TLP:WHITE | TLP:GREEN | TLP:AMBER | TLP:RED>"
  },
  "identity": {
    "primary_name": "<most common name>",
    "aliases": ["<alias1>", "<alias2>"],
    "tracking_ids": {
      "mitre_group_id": "<Gxxxx or null>",
      "other_ids": ["<vendor-specific IDs e.g. UNC1234, TA505>"]
    },
    "actor_type": "<nation-state | criminal | hacktivist | insider | unknown>",
    "sponsoring_nation": "<country or null>",
    "affiliated_group": "<criminal org, APT cluster, or null>",
    "first_observed": "<YYYY or YYYY-MM or null>",
    "last_active": "<YYYY-MM or 'ongoing' or null>",
    "active_status": "<active | inactive | suspected inactive | unknown>"
  },
  "motivation": {
    "primary_motivation": "<espionage | financial | ransomware | hacktivism | sabotage | unknown>",
    "secondary_motivations": ["<motivation2>"],
    "strategic_objectives": ["<objective1>", "<objective2>"],
    "targeting_approach": "<opportunistic | targeted | both | unknown>"
  },
  "targeting_profile": {
    "targeted_sectors": ["<sector1>", "<sector2>"],
    "targeted_geographies": ["<country or region>"],
    "targeted_organization_types": ["<gov | bfsi | telco | healthcare | energy | etc>"],
    "confirmed_victim_industries": ["<specific industry verticals from reporting>"],
    "high_value_assets_targeted": ["<data types, systems, or roles sought>"]
  },
  "capability_assessment": {
    "sophistication_level": "<low | medium | high | nation-state>",
    "development_capability": "<custom | commodity | mixed>",
    "known_malware": [
      {
        "name": "<malware name>",
        "type": "<backdoor | loader | ransomware | stealer | wiper | rat | rootkit | other>",
        "notes": "<brief description or null>"
      }
    ],
    "known_tools": ["<tool1>", "<tool2>"],
    "exploited_vulnerabilities": [
      {
        "cve_id": "<CVE-YYYY-NNNNN>",
        "product": "<affected product>",
        "notes": "<exploitation context or null>"
      }
    ],
    "attack_techniques": {
      "initial_access": ["<technique ID + name>"],
      "execution": ["<technique ID + name>"],
      "persistence": ["<technique ID + name>"],
      "privilege_escalation": ["<technique ID + name>"],
      "defense_evasion": ["<technique ID + name>"],
      "credential_access": ["<technique ID + name>"],
      "discovery": ["<technique ID + name>"],
      "lateral_movement": ["<technique ID + name>"],
      "collection": ["<technique ID + name>"],
      "exfiltration": ["<technique ID + name>"],
      "command_and_control": ["<technique ID + name>"],
      "impact": ["<technique ID + name>"]
    }
  },
  "infrastructure": {
    "c2_patterns": ["<description of C2 behavior>"],
    "hosting_preferences": ["<bulletproof hosting | cloud abuse | compromised infra | etc>"],
    "known_iocs": {
      "ips": ["<defanged IP>"],
      "domains": ["<defanged domain>"],
      "hashes": ["<SHA256>"],
      "urls": ["<defanged URL>"]
    },
    "infrastructure_reuse": "<yes | no | unknown>",
    "infrastructure_notes": "<any relevant pattern notes or null>"
  },
  "campaign_history": [
    {
      "campaign_name": "<name or null>",
      "date_range": "<YYYY-MM to YYYY-MM or 'ongoing'>",
      "targeted_sectors": ["<sector>"],
      "targeted_regions": ["<region>"],
      "notable_techniques": ["<TTP summary>"],
      "source_reference": "<report title or URL>"
    }
  ],
  "detection_and_defense": {
    "detection_opportunities": [
      {
        "layer": "<network | endpoint | identity | email | cloud>",
        "description": "<what to look for>",
        "mitre_technique_ref": "<T#### or null>"
      }
    ],
    "recommended_mitigations": [
      {
        "mitigation": "<action>",
        "mitre_mitigation_id": "<M#### or null>",
        "priority": "<immediate | short-term | long-term>"
      }
    ],
    "existing_detection_rules": {
      "yara": ["<rule name or source>"],
      "sigma": ["<rule name or source>"]
    }
  },
  "organizational_relevance": {
    "sector_relevance": "<low | medium | high | critical>",
    "relevance_rationale": "<explanation of why this actor is relevant to your sector>",
    "aligned_ttp_to_threat_surface": ["<TTP that maps to your environment>"],
    "monitoring_priority": "<low | medium | high | critical>",
    "recommended_actions": [
      {
        "timeframe": "<immediate | 30-day | 90-day>",
        "action": "<specific recommendation>"
      }
    ]
  },
  "intelligence_gaps": [
    "<unanswered question or unknown field that requires further research>"
  ],
  "references": [
    {
      "title": "<report or article title>",
      "source": "<vendor / publisher>",
      "url": "<URL or null>",
      "date": "<YYYY-MM-DD or null>"
    }
  ]
}"""


def _build_user_message(
    actor_name: str, news: list[dict[str, Any]], attack_group: dict[str, Any] | None
) -> str:
    """Blok konteks yang jadi SATU-SATUNYA sumber malware/CVE/teknik/IOC di profil (spec
    2026-10-24 6.1 butir 2): dulu model hanya menerima nama aktor (+ judul berita) dan mengisi
    field itu dari ingatannya sendiri. `attack_group` = hasil `AsyncAttackQueryRepo.get_group()`
    (software + teknik lewat `attack_relationships`), None kalau nama tidak cocok grup mana pun."""
    lines = [f"Threat actor: {actor_name}", "", "MITRE ATT&CK context:"]
    if attack_group is None:
        lines.append("- No MITRE ATT&CK group matches this name or its aliases.")
    else:
        lines.append(
            f"- Group: {attack_group.get('name', '')} ({attack_group.get('group_id', '')})"
        )
        lines.append(f"- Aliases: {', '.join(attack_group.get('aliases') or []) or 'none'}")
        software = attack_group.get("software") or []
        lines.append("- Software:" if software else "- Software: none listed")
        lines.extend(
            f"  - {sw['name']} ({sw['software_id']}, {sw['software_type']})" for sw in software
        )
        techniques = attack_group.get("techniques") or []
        lines.append("- Techniques:" if techniques else "- Techniques: none listed")
        lines.extend(
            f"  - {t['attack_id']} {t['name']} ({', '.join(t.get('tactics') or [])})"
            for t in techniques
        )
    lines += ["", "Recent reporting (newest first):"]
    if not news:
        lines.append("- none")
    for a in news:
        lines.append(
            f"- [{a.get('posted_on', 'n/d')}] {a.get('title', '')} "
            f"(source: {a.get('source', '')}, url: {a.get('url', '')})"
        )
    return "\n".join(lines)


async def build_profile_input(session: AsyncSession, actor_name: str) -> tuple[str, str | None]:
    """Return (user message, MITRE group ID yang cocok atau None)."""
    news = await AsyncTAProfileRepo(session).fetch_recent_news(actor_name)
    attack_repo = AsyncAttackQueryRepo(session)
    grp = await attack_repo.get_group_by_name_or_alias_ci(actor_name)
    attack_group = await attack_repo.get_group(grp.group_id) if grp is not None else None
    mitre_group_id = attack_group["group_id"] if attack_group else None
    return _build_user_message(actor_name, news, attack_group), mitre_group_id


def apply_overrides(
    profile: dict[str, Any], mitre_group_id: str | None, now: datetime.datetime
) -> dict[str, Any]:
    """Field yang tidak boleh ditebak model: waktu pembuatan, TLP (profil dari sumber terbuka),
    dan ID grup ATT&CK (dari pencocokan DB, bukan ingatan model). Dict perantara dibuat kalau
    model tidak mengembalikannya."""
    metadata = profile.get("profile_metadata")
    if not isinstance(metadata, dict):
        metadata = profile["profile_metadata"] = {}
    metadata["generated_at"] = now.isoformat()
    metadata["tlp_marking"] = "TLP:CLEAR"
    identity = profile.get("identity")
    if not isinstance(identity, dict):
        identity = profile["identity"] = {}
    tracking = identity.get("tracking_ids")
    if not isinstance(tracking, dict):
        tracking = identity["tracking_ids"] = {}
    tracking["mitre_group_id"] = mitre_group_id
    return profile


_TECHNIQUE_ID_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b")


def filter_techniques_to_context(profile: dict[str, Any], context: str) -> dict[str, Any]:
    """Buang teknik yang ID-nya tidak ada di konteks yang dikirim ke model. Larangan di prompt
    saja tidak cukup: di dev (0.8.5, Scattered Spider) 1 dari 55 teknik (T1485) tidak ada di
    konteks ATT&CK maupun berita. Entri tanpa ID ikut dibuang; sub-teknik harus tercantum
    persis (T1059 di konteks tidak meloloskan T1059.001). Key taktik dipertahankan (list
    kosong), web sudah menyembunyikan taktik kosong."""
    cap = profile.get("capability_assessment")
    techniques = cap.get("attack_techniques") if isinstance(cap, dict) else None
    if not isinstance(techniques, dict):
        return profile
    allowed = set(_TECHNIQUE_ID_RE.findall(context))
    for tactic, entries in techniques.items():
        if isinstance(entries, list):
            techniques[tactic] = [
                e
                for e in entries
                if isinstance(e, str)
                and (m := _TECHNIQUE_ID_RE.search(e)) is not None
                and m.group(0) in allowed
            ]
    return profile


_PROMPT_VERSION = prompt_version(_SYSTEM_PROMPT)


def _call_llm(user_msg: str) -> dict[str, Any]:
    client, model_name = get_llm_client(task="ta_profile")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        prompt_version=_PROMPT_VERSION,
    )
    raw = completion.choices[0].message.content
    result = parse_json_response(raw or "{}")
    return result


_CVE_ID_RE = re.compile(r"CVE-\d{4}-\d{4,7}", re.IGNORECASE)


async def _enrich_profile_cves(session: AsyncSession, profile: dict[str, Any]) -> dict[str, Any]:
    """Cross-reference `exploited_vulnerabilities` LLM vs `cve_tracker`
    real -- port `ta_profile_service._enrich_profile_cves()` apa adanya."""
    actor_name: str = profile.get("_actor_name", "")

    capability = profile.get("capability_assessment") or {}
    exploited_vulns: list[dict[str, Any]] = capability.get("exploited_vulnerabilities") or []

    profile_cve_ids: set[str] = set()
    for entry in exploited_vulns:
        cve_id = (entry.get("cve_id") or "").upper().strip()
        if _CVE_ID_RE.match(cve_id):
            profile_cve_ids.add(cve_id.upper())

    article_cve_ids: set[str] = set()
    if actor_name:
        pattern = build_ta_name_pattern(actor_name)
        result = await session.execute(
            select(Article.title)
            .outerjoin(Article.threat_actors)
            .where(
                (ArticleThreatActor.threat_actor.op("~*")(pattern))
                | (Article.title.op("~*")(pattern))
            )
            .distinct()
        )
        for (title,) in result.all():
            for cve in _CVE_ID_RE.findall(title or ""):
                article_cve_ids.add(cve.upper())

    all_cve_ids = profile_cve_ids | article_cve_ids
    if not all_cve_ids:
        profile["_article_cves"] = []
        return profile

    tracker_rows = await AsyncCveTrackerRepo(session).get_by_cve_ids(list(all_cve_ids))
    tracker_map = {row.cve_id.upper(): row for row in tracker_rows}

    for entry in exploited_vulns:
        cve_id = (entry.get("cve_id") or "").upper().strip()
        row = tracker_map.get(cve_id)
        if row:
            entry["_confirmed"] = True
            entry["_cve_score"] = row.cve_score
            entry["_cve_severity"] = row.cve_severity
            entry["_cisa_kev"] = row.cisa_kev
            entry["_poc_available"] = row.poc_available
            entry["_tech"] = row.tech
            entry["_link"] = row.link
            entry["_active_exploitation"] = row.active_exploitation
        else:
            entry["_confirmed"] = False

    extra_cve_ids = article_cve_ids - profile_cve_ids
    article_cves_list: list[dict[str, Any]] = []
    for cve_id in sorted(extra_cve_ids):
        row = tracker_map.get(cve_id)
        extra_entry: dict[str, Any] = {"cve_id": cve_id}
        if row:
            extra_entry["_confirmed"] = True
            extra_entry["_cve_score"] = row.cve_score
            extra_entry["_cve_severity"] = row.cve_severity
            extra_entry["_cisa_kev"] = row.cisa_kev
            extra_entry["_poc_available"] = row.poc_available
            extra_entry["_tech"] = row.tech
            extra_entry["_link"] = row.link
            extra_entry["_active_exploitation"] = row.active_exploitation
            extra_entry["_summary"] = row.summary
        else:
            extra_entry["_confirmed"] = False
        article_cves_list.append(extra_entry)

    profile["_article_cves"] = article_cves_list
    return profile


async def generate_ta_profile(session: AsyncSession, actor_name: str) -> dict[str, Any]:
    profile_repo = AsyncTAProfileRepo(session)
    user_msg, mitre_group_id = await build_profile_input(session, actor_name)
    profile = await asyncio.to_thread(_call_llm, user_msg)
    now = datetime.datetime.now(datetime.UTC)
    apply_overrides(profile, mitre_group_id, now)
    filter_techniques_to_context(profile, user_msg)
    profile["_actor_name"] = actor_name
    profile["_generated_at"] = now.isoformat()

    await profile_repo.save_profile(actor_name, profile)
    # Enrich in-memory buat response doang -- enrichment TIDAK dipersist,
    # port apa adanya (`_enrich_profile_cves` dipanggil SETELAH save).
    return await _enrich_profile_cves(session, profile)


async def get_ta_profile_enriched(session: AsyncSession, actor_name: str) -> dict[str, Any] | None:
    row = await AsyncTAProfileRepo(session).get_profile(actor_name)
    if row is None:
        return None
    profile = dict(row.profile)
    profile["_actor_name"] = row.actor_name
    profile["_generated_at"] = row.generated_at.isoformat()
    return await _enrich_profile_cves(session, profile)
