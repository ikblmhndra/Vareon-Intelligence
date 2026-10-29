"""Port `ScraperNewsWeb/app/services/stix_service.py`. Fase 7.3 (router
`stix`, Bagian 4). Builder STIX 2.1 STATELESS -- baca dari repo lain,
transform ke dict, gak ada tabel/model baru di sini sama sekali (beda
dari `newsletter`/`mindmap` yang punya cache tabel sendiri).

Builder object-level (`_build_indicator`/`_build_threat_actor`/
`_build_attack_pattern`/`_build_malware`/`_build_relationship`/
`_build_course_of_action`) diport BYTE-IDENTIK dari service lama --
cuma 4 fungsi publik (`build_*_stix_bundle`) yang berubah, karena
sumber data sekarang repo Postgres (`AsyncSession` + repo), bukan
`get_database()[COLLECTION]` Mongo langsung.

`_build_indicator()` diport dengan SIGNATURE beda (parameter primitif
type/value/first_seen/tags/seen_count/last_seen, bukan satu dict `ioc`)
supaya bisa dipakai dua sumber yang beda bentuknya: baris ORM `IOC` asli
(`build_ioc_stix_bundle`) DAN IOC sintetis dari `infrastructure.known_iocs`
profil TA (`build_ta_stix_bundle`, dulu `fake_ioc = {...}` dict manual).
Output-nya byte-identik untuk input yang setara -- ini refactor bentuk
parameter doang, BUKAN perubahan perilaku.

`article_id` sekarang `int` (Postgres bigint), bukan Mongo ObjectId hex
string -- lihat docstring `routers/stix.py`."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from cti_core.config import platform_name
from cti_core.db.models.indicator import Indicator
from cti_core.db.models.pir import PIRRequirement
from cti_core.db.repositories.article import AsyncArticleRepo, all_country_codes
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy.ext.asyncio import AsyncSession

# ── Constants ────────────────────────────────────────────────────────────────

# Fixed identity UUID -- deterministik, mewakili platform CTI ini.
_IDENTITY_UUID = "b67d2b96-5e1e-4b78-9e5f-8f3a1c2d4e7a"

_SPEC = "2.1"

# Marking-definition TLP 2.0 resmi OASIS (cti-stix-common-objects, tlp-2.0): id dan bentuk objeknya
# tetap, jadi ditulis apa adanya, bukan diturunkan.
_TLP_EXTENSION_ID = "extension-definition--60a3c5c5-0d10-413e-aab3-9e08dde9e88d"
TLP_MARKING_IDS: dict[str, str] = {
    "clear": "marking-definition--94868c89-83c2-464b-929b-a1a8aa3c8487",
    "green": "marking-definition--bab4a63c-aed9-4cf5-a766-dfca5abac2bb",
    "amber": "marking-definition--55d920b0-5e8b-4f79-9ee9-91f868d9b421",
    "amber+strict": "marking-definition--939a9414-2ddd-4d32-a0cd-375ea402b003",
    "red": "marking-definition--e828b379-4e03-4974-9ac4-e53a884c97c1",
}

_TECHNIQUE_RE = re.compile(r"(T\d{4}(?:\.\d{3})?)\s*(.*)")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _uuid4() -> str:
    return str(uuid.uuid4())


def _uuid5(name: str) -> str:
    """UUID5 deterministik berdasarkan DNS namespace + nama lowercase."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name.lower().strip()))


def _identity_object() -> dict[str, Any]:
    ts = _now()
    return {
        "type": "identity",
        "id": f"identity--{_IDENTITY_UUID}",
        "spec_version": _SPEC,
        "created": ts,
        "modified": ts,
        "name": platform_name(),
        "identity_class": "system",
    }


def _marking_definition(tlp: str) -> dict[str, Any]:
    return {
        "type": "marking-definition",
        "spec_version": _SPEC,
        "id": TLP_MARKING_IDS[tlp],
        "created": "2022-10-01T00:00:00.000Z",
        "name": f"TLP:{tlp.upper()}",
        "extensions": {_TLP_EXTENSION_ID: {"extension_type": "property-extension", "tlp_2_0": tlp}},
    }


def _make_bundle(objects: list[dict[str, Any]]) -> dict[str, Any]:
    """Tiap marking-definition yang dirujuk `object_marking_refs` ikut disertakan sekali, supaya
    bundle berdiri sendiri (konsumen tidak perlu mengambil objek marking dari luar)."""
    used = {ref for o in objects for ref in o.get("object_marking_refs", [])}
    objects = objects + [_marking_definition(t) for t, i in TLP_MARKING_IDS.items() if i in used]
    return {
        "type": "bundle",
        "id": f"bundle--{_uuid4()}",
        "spec_version": _SPEC,
        "objects": objects,
    }


# ── IOC -> STIX pattern ─────────────────────────────────────────────────────

_IOC_PATTERN_MAP = {
    "ip": "[ipv4-addr:value = '{value}']",
    "domain": "[domain-name:value = '{value}']",
    "url": "[url:value = '{value}']",
    "url_with_path": "[url:value = '{value}']",
    "sha256": "[file:hashes.'SHA-256' = '{value}']",
    "sha1": "[file:hashes.'SHA-1' = '{value}']",
    "md5": "[file:hashes.MD5 = '{value}']",
    "email": "[email-addr:value = '{value}']",
}


def _ioc_pattern(ioc_type: str, value: str) -> str | None:
    tmpl = _IOC_PATTERN_MAP.get(ioc_type)
    if tmpl is None:
        return None
    # Backslash dulu, baru kutip: urutan terbalik akan menggandakan backslash dari escape kutip.
    safe_value = value.replace("\\", "\\\\").replace("'", "\\'")
    return tmpl.format(value=safe_value)


def _ioc_type_to_indicator_type(ioc_type: str) -> str:
    mapping = {
        "ip": "malicious-activity",
        "domain": "malicious-activity",
        "url": "malicious-activity",
        "sha256": "malicious-activity",
        "sha1": "malicious-activity",
        "md5": "malicious-activity",
        "email": "compromised",
    }
    return mapping.get(ioc_type, "unknown")


# ── STIX object builders ──────────────────────────────────────────────────────


def _build_indicator(
    ioc_type: str,
    value: str,
    ts: str,
    *,
    first_seen: str | None = None,
    tags: list[str] | None = None,
    seen_count: int | None = None,
    last_seen: str | None = None,
    valid_until: str | None = None,
    # Default None: bundle threat-actor tanpa marking; bundle IOC selalu mengisi TLP indikator.
    tlp: str | None = None,
    created: str | None = None,
    modified: str | None = None,
    revoked: bool = False,
) -> dict[str, Any] | None:
    """Build a STIX 2.1 indicator. `first_seen`/`last_seen` kalau dikasih
    HARUS string tanggal `YYYY-MM-DD` (lihat pemanggil); `valid_until` RFC 3339 dengan `Z`."""
    pattern = _ioc_pattern(ioc_type, value)
    if not pattern:
        return None

    first_seen = first_seen or ts[:10]
    # valid_from harus RFC 3339 / ISO 8601 dengan timezone
    valid_from = f"{first_seen}T00:00:00Z" if len(first_seen) == 10 else first_seen

    # Rumus yang sama dengan kolom `indicators.stix_id` (peka huruf besar), BUKAN `_uuid5`:
    # `_uuid5` melipat huruf sehingga nilai yang hanya beda kapitalisasi bertabrakan.
    indicator_id = f"indicator--{indicator_uuid(ioc_type, value)}"

    obj: dict[str, Any] = {
        "type": "indicator",
        "id": indicator_id,
        "spec_version": _SPEC,
        "created": created or ts,
        "modified": modified or ts,
        "name": f"{ioc_type}: {value}",
        "pattern": pattern,
        "pattern_type": "stix",
        "valid_from": valid_from,
        "indicator_types": [_ioc_type_to_indicator_type(ioc_type)],
    }

    if valid_until:
        obj["valid_until"] = valid_until
    if revoked:
        obj["revoked"] = True
    if tlp:
        obj["object_marking_refs"] = [TLP_MARKING_IDS[tlp]]
    if tags:
        obj["labels"] = tags
    if seen_count is not None:
        obj["x_seen_count"] = seen_count
    if last_seen:
        obj["x_last_seen"] = last_seen

    return obj


def stix_ts(dt: datetime) -> str:
    """RFC 3339 UTC dengan presisi milidetik dan `Z`, bentuk yang dipakai TAXII."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def indicator_to_stix(ind: Indicator) -> dict[str, Any] | None:
    """Satu baris `Indicator` -> objek STIX. Waktu dan id berasal dari baris (bukan `now()`),
    jadi dua pemanggilan menghasilkan objek identik: syarat polling TAXII. `revoked: true` untuk
    revoked DAN allowlisted supaya pelanggan menghapusnya. Tanpa `confidence` (berubah harian)."""
    stix_id = ind.stix_id or indicator_uuid(ind.type, ind.value)
    obj = _build_indicator(
        ind.type,
        ind.value,
        stix_ts(ind.created_at),
        first_seen=stix_ts(ind.valid_from),
        tags=sorted(t.tag for t in ind.tags) or None,
        seen_count=ind.seen_count,
        last_seen=ind.last_seen_at.date().isoformat(),
        valid_until=stix_ts(ind.valid_until) if ind.valid_until else None,
        tlp=ind.tlp,
        created=stix_ts(ind.created_at),
        modified=stix_ts(ind.feed_changed_at),
        revoked=ind.state in ("revoked", "allowlisted"),
    )
    if obj is not None:
        obj["id"] = f"indicator--{stix_id}"
    return obj


def _build_threat_actor(actor_name: str, profile: dict[str, Any], ts: str) -> dict[str, Any]:
    ta_id = f"threat-actor--{_uuid5(actor_name)}"
    identity_info = profile.get("identity", {})
    motivation = profile.get("motivation", {})
    targeting = profile.get("targeting_profile", {})
    meta = profile.get("profile_metadata", {})

    obj: dict[str, Any] = {
        "type": "threat-actor",
        "id": ta_id,
        "spec_version": _SPEC,
        "created": ts,
        "modified": ts,
        "name": identity_info.get("primary_name") or actor_name,
    }

    aliases = identity_info.get("aliases", [])
    if aliases:
        obj["aliases"] = aliases

    actor_type = identity_info.get("actor_type")
    if actor_type:
        obj["threat_actor_types"] = [actor_type]

    primary_motive = motivation.get("primary_motivation")
    if primary_motive:
        obj["primary_motivation"] = primary_motive

    secondary = motivation.get("secondary_motivations", [])
    if secondary:
        obj["secondary_motivations"] = secondary

    sectors = targeting.get("targeted_sectors", [])
    if sectors:
        obj["sectors"] = sectors

    countries = targeting.get("targeted_geographies", [])
    if countries:
        obj["x_targeted_countries"] = countries

    sponsoring_nation = identity_info.get("sponsoring_nation")
    if sponsoring_nation:
        obj["x_sponsoring_nation"] = sponsoring_nation

    active_status = identity_info.get("active_status")
    if active_status:
        obj["x_active_status"] = active_status

    sophistication = profile.get("capability_assessment", {}).get("sophistication_level")
    if sophistication:
        obj["sophistication"] = sophistication

    tlp = meta.get("tlp_marking")
    if tlp:
        obj["x_tlp"] = tlp

    confidence = meta.get("analyst_confidence")
    if confidence:
        confidence_map = {"low": 33, "medium": 66, "high": 85}
        obj["confidence"] = confidence_map.get(confidence, 50)

    # External references: MITRE group ID
    ext_refs = []
    mitre_id = identity_info.get("tracking_ids", {}).get("mitre_group_id")
    if mitre_id:
        ext_refs.append(
            {
                "source_name": "mitre-attack",
                "external_id": mitre_id,
                "url": f"https://attack.mitre.org/groups/{mitre_id}/",
            }
        )
    other_ids = identity_info.get("tracking_ids", {}).get("other_ids", [])
    for oid in other_ids:
        ext_refs.append({"source_name": "vendor", "external_id": oid})
    if ext_refs:
        obj["external_references"] = ext_refs

    return obj


def _build_attack_pattern(technique_str: str, tactic: str, ts: str) -> dict[str, Any]:
    """Build STIX attack-pattern dari string teknik kayak `'T1566 Phishing'`
    atau plain text."""
    match = _TECHNIQUE_RE.match(technique_str.strip())
    if match:
        tech_id = match.group(1)
        tech_name = match.group(2).strip() or technique_str.strip()
        ext_refs = [
            {
                "source_name": "mitre-attack",
                "external_id": tech_id,
                "url": f"https://attack.mitre.org/techniques/{tech_id.replace('.', '/')}/",
            }
        ]
    else:
        tech_name = technique_str.strip()
        ext_refs = []

    obj: dict[str, Any] = {
        "type": "attack-pattern",
        "id": f"attack-pattern--{_uuid5(technique_str)}",
        "spec_version": _SPEC,
        "created": ts,
        "modified": ts,
        "name": tech_name,
        "x_tactic": tactic,
    }
    if ext_refs:
        obj["external_references"] = ext_refs

    return obj


def _build_malware(malware_entry: dict[str, Any] | str, ts: str) -> dict[str, Any]:
    """Build STIX malware object dari entry dict atau plain name string."""
    if isinstance(malware_entry, dict):
        name = malware_entry.get("name", "Unknown Malware")
        mal_type = malware_entry.get("type", "unknown")
        notes = malware_entry.get("notes")
    else:
        name = str(malware_entry)
        mal_type = "unknown"
        notes = None

    obj: dict[str, Any] = {
        "type": "malware",
        "id": f"malware--{_uuid5(name)}",
        "spec_version": _SPEC,
        "created": ts,
        "modified": ts,
        "name": name,
        "is_family": False,
        "malware_types": [mal_type],
    }
    if notes:
        obj["description"] = notes

    return obj


def _build_relationship(
    rel_type: str,
    source_ref: str,
    target_ref: str,
    ts: str,
    description: str | None = None,
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "type": "relationship",
        "id": f"relationship--{_uuid4()}",
        "spec_version": _SPEC,
        "created": ts,
        "modified": ts,
        "relationship_type": rel_type,
        "source_ref": source_ref,
        "target_ref": target_ref,
    }
    if description:
        obj["description"] = description
    return obj


def _build_course_of_action(pir: PIRRequirement, ts: str) -> dict[str, Any]:
    title = pir.title
    description = pir.description
    priority = pir.priority
    owner = pir.owner

    coa_name = f"PIR: {title}"
    coa_id = f"course-of-action--{_uuid5(coa_name)}"

    desc_parts = []
    if description:
        desc_parts.append(description)
    if priority:
        desc_parts.append(f"Priority: {priority}")
    if owner:
        desc_parts.append(f"Owner: {owner}")
    criteria = pir.criteria or {}
    if criteria:
        if criteria.get("threat_actors"):
            desc_parts.append(f"Threat Actors: {', '.join(criteria['threat_actors'])}")
        if criteria.get("industries"):
            desc_parts.append(f"Industries: {', '.join(criteria['industries'])}")
        if criteria.get("countries"):
            desc_parts.append(f"Countries: {', '.join(criteria['countries'])}")
        if criteria.get("ttps"):
            desc_parts.append(f"TTPs: {', '.join(criteria['ttps'])}")
        if criteria.get("keywords"):
            desc_parts.append(f"Keywords: {', '.join(criteria['keywords'])}")

    obj: dict[str, Any] = {
        "type": "course-of-action",
        "id": coa_id,
        "spec_version": _SPEC,
        "created": ts,
        "modified": ts,
        "name": coa_name,
        "x_pir_id": str(pir.id),
        "x_pir_status": pir.status or "active",
        "x_pir_priority": priority,
    }
    if desc_parts:
        obj["description"] = "\n".join(desc_parts)
    if pir.start_date:
        obj["x_start_date"] = pir.start_date.isoformat()
    if pir.end_date:
        obj["x_end_date"] = pir.end_date.isoformat()

    return obj


# ── Public service functions ──────────────────────────────────────────────────


async def build_ta_stix_bundle(session: AsyncSession, actor_name: str) -> dict[str, Any]:
    """Ambil profil TA dan ubah jadi bundle STIX 2.1 berisi identity,
    threat-actor, attack-pattern (dari `capability_assessment.
    attack_techniques`), malware (`known_malware`), indicator (dari
    `infrastructure.known_iocs`), dan relationship yang menghubungkan
    semuanya ke threat-actor. Kalau profil gak ketemu, balikin bundle
    minimal cuma berisi identity -- router yang mutusin 404 dari situ
    (cek `objects` selain identity kosong atau nggak)."""
    ts = _now()
    objects: list[dict[str, Any]] = []

    identity = _identity_object()
    objects.append(identity)

    profile_row = await AsyncTAProfileRepo(session).get_profile(actor_name)
    if profile_row is None:
        return _make_bundle(objects)
    profile = profile_row.profile

    ta_obj = _build_threat_actor(actor_name, profile, ts)
    ta_ref = ta_obj["id"]
    objects.append(ta_obj)

    # ── Attack Patterns ─────────────────────────────────────────────────
    capability = profile.get("capability_assessment", {})
    attack_techniques = capability.get("attack_techniques", {})

    seen_technique_ids: set[str] = set()
    for tactic, techniques in attack_techniques.items():
        if not isinstance(techniques, list):
            continue
        for tech_str in techniques:
            if not tech_str:
                continue
            ap_obj = _build_attack_pattern(tech_str, tactic, ts)
            if ap_obj["id"] not in seen_technique_ids:
                seen_technique_ids.add(ap_obj["id"])
                objects.append(ap_obj)
                objects.append(_build_relationship("uses", ta_ref, ap_obj["id"], ts))

    # ── Malware ─────────────────────────────────────────────────────────
    known_malware = capability.get("known_malware", [])
    seen_malware_ids: set[str] = set()
    for mal_entry in known_malware:
        mal_obj = _build_malware(mal_entry, ts)
        if mal_obj["id"] not in seen_malware_ids:
            seen_malware_ids.add(mal_obj["id"])
            objects.append(mal_obj)
            objects.append(_build_relationship("uses", ta_ref, mal_obj["id"], ts))

    # ── IOC indicators dari infrastructure.known_iocs ──────────────────
    infra = profile.get("infrastructure", {})
    known_iocs = infra.get("known_iocs", {})

    infra_type_map = {"ips": "ip", "domains": "domain", "hashes": "sha256", "urls": "url"}
    seen_indicator_ids: set[str] = set()
    for field, ioc_type in infra_type_map.items():
        values = known_iocs.get(field, [])
        if not isinstance(values, list):
            continue
        for value in values:
            if not value:
                continue
            # Balik defang: [.] -> . dan hxxp -> http
            clean_value = (
                value.replace("[.]", ".")
                .replace("hxxp://", "http://")
                .replace("hxxps://", "https://")
            )
            ind_obj = _build_indicator(ioc_type, clean_value, ts)
            if ind_obj and ind_obj["id"] not in seen_indicator_ids:
                seen_indicator_ids.add(ind_obj["id"])
                objects.append(ind_obj)
                objects.append(_build_relationship("indicates", ind_obj["id"], ta_ref, ts))

    return _make_bundle(objects)


async def build_ioc_stix_bundle(
    session: AsyncSession,
    ioc_type: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Ambil IOC dari `AsyncIOCRepo` dan ubah jadi objek indicator STIX
    2.1 di dalam satu bundle."""
    objects: list[dict[str, Any]] = []

    identity = _identity_object()
    objects.append(identity)

    # Export tidak pernah memuat IOC `auto_suppressed` (bukan indikator), apa pun parameternya.
    iocs, _total = await AsyncIndicatorRepo(session).list_filtered(
        page=1,
        page_size=min(limit, 1000),
        ioc_type=ioc_type,
        include_suppressed=False,
        include_revoked=False,
    )

    for ioc in iocs:
        ind_obj = indicator_to_stix(ioc)
        if ind_obj:
            objects.append(ind_obj)

    return _make_bundle(objects)


async def build_article_stix_bundle(
    session: AsyncSession, article_id: int
) -> dict[str, Any] | None:
    """Ambil satu artikel dan ubah jadi bundle STIX 2.1 berisi identity,
    report object (artikelnya), attack-pattern (dari `article.ttps`),
    threat-actor stub (dari `article.threat_actors`), dan relationship.
    Balikin `None` kalau artikel gak ketemu."""
    article = await AsyncArticleRepo(session).get_by_id(article_id)
    if article is None:
        return None

    ts = _now()
    objects: list[dict[str, Any]] = []

    identity = _identity_object()
    objects.append(identity)

    object_refs: list[str] = [identity["id"]]

    # ── Threat Actor stubs ──────────────────────────────────────────────
    ta_refs: list[str] = []
    for ta in article.threat_actors:
        ta_id = f"threat-actor--{_uuid5(ta.threat_actor)}"
        ta_obj: dict[str, Any] = {
            "type": "threat-actor",
            "id": ta_id,
            "spec_version": _SPEC,
            "created": ts,
            "modified": ts,
            "name": ta.threat_actor,
        }
        objects.append(ta_obj)
        object_refs.append(ta_id)
        ta_refs.append(ta_id)

    # ── Attack Patterns (TTPs) ──────────────────────────────────────────
    ap_refs: list[str] = []
    seen_ap: set[str] = set()
    for ttp in article.ttps:
        tech_str = f"{ttp.ttp_id} {ttp.ttp_name}".strip()
        if not tech_str:
            continue
        ap_obj = _build_attack_pattern(tech_str, "unknown", ts)
        if ap_obj["id"] not in seen_ap:
            seen_ap.add(ap_obj["id"])
            objects.append(ap_obj)
            object_refs.append(ap_obj["id"])
            ap_refs.append(ap_obj["id"])

    # ── Relationships ───────────────────────────────────────────────────
    for ta_ref in ta_refs:
        for ap_ref in ap_refs:
            objects.append(_build_relationship("uses", ta_ref, ap_ref, ts))

    # ── Report object (artikelnya sendiri) ──────────────────────────────
    report_id = f"report--{_uuid5(str(article_id))}"
    published = article.posted_on.isoformat() if article.posted_on else ts[:10]
    report_obj: dict[str, Any] = {
        "type": "report",
        "id": report_id,
        "spec_version": _SPEC,
        "created": ts,
        "modified": ts,
        "name": article.title or "Untitled",
        "published": f"{published}T00:00:00Z",
        "report_types": ["threat-report"],
        "object_refs": object_refs,
    }
    if article.url:
        report_obj["external_references"] = [
            {"source_name": article.source or "unknown", "url": article.url}
        ]
    if article.news_type:
        report_obj["labels"] = [article.news_type]
    industries = [i.industry for i in article.industries]
    if industries:
        report_obj["x_impacted_industries"] = industries
    # Padanan `mentioned_countries` Mongo lama = role apa pun (lihat
    # `all_country_codes`), sama kayak `stix_service.py` lama.
    mentioned_countries = all_country_codes(article)
    if mentioned_countries:
        report_obj["x_mentioned_countries"] = mentioned_countries
    if article.confidence_score is not None:
        report_obj["confidence"] = article.confidence_score

    objects.insert(1, report_obj)  # taruh report tepat setelah identity

    return _make_bundle(objects)


async def build_pir_stix_bundle(session: AsyncSession, client_id: str) -> dict[str, Any]:
    """Ambil PIR aktif MILIK `client_id` dan wakilkan tiap satu sebagai objek course-of-action
    STIX 2.1. Dulu lintas client (`list_active_unscoped`): bundle satu client berisi PIR semua
    client (audit keamanan 2026-10-24)."""
    ts = _now()
    objects: list[dict[str, Any]] = []

    identity = _identity_object()
    objects.append(identity)
    identity_ref = identity["id"]

    pirs = await AsyncPIRRepo(session).list_active_by_client(client_id)  # urut priority naik

    for pir in pirs:
        coa_obj = _build_course_of_action(pir, ts)
        objects.append(coa_obj)
        objects.append(
            _build_relationship(
                "derived-from",
                coa_obj["id"],
                identity_ref,
                ts,
                description=f"PIR managed by {platform_name()}",
            )
        )

    return _make_bundle(objects)
