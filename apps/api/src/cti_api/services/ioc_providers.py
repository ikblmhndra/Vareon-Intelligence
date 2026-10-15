"""Klien dan pemetaan provider reputasi IOC (ROADMAP #4).

Tiap provider menghasilkan SATU kartu dengan bentuk yang sudah dibaca
`apps/web/src/components/intelligence/ioc/ioc-detail-dialog.tsx` (`IocEnrichmentProvider`):
`key`, `name`, `verdict` (`malicious` | `suspicious` | `clean` | `unknown`), `score` (0-100,
opsional),
`raw` (peta nama -> string/angka, tanpa boolean), `tags`, `malware_families`. Pemetaan dari respons
provider ke kartu adalah fungsi MURNI (dites tanpa jaringan); klien HTTP-nya tipis: satu GET,
`raise_for_status()`, lalu petakan. Kegagalan (status, jaringan, bentuk respons) sengaja dibiarkan
naik ke pemanggil (`ioc_enrichment`), yang memutuskan berhenti atau lanjut dan tidak pernah mencatat
pesan exception (bisa memuat potongan kunci).

Hanya LOOKUP (GET). Tidak ada endpoint submit/scan: IOC yang disimpan platform berasal dari artikel
publik, tetapi mengirimnya ke layanan scan publik tetap akan membuat catatan dan tidak dibutuhkan
untuk reputasi.
"""

from __future__ import annotations

import base64
from collections import Counter
from collections.abc import Mapping
from typing import Any

import httpx

ABUSEIPDB = "abuseipdb"
ABUSEIPDB_NAME = "AbuseIPDB"
_ABUSEIPDB_URL = "https://api.abuseipdb.com/api/v2/check"
_ABUSEIPDB_MAX_AGE_DAYS = 90
ABUSEIPDB_MALICIOUS = 75
ABUSEIPDB_SUSPICIOUS = 25
"""Ambang `abuseConfidenceScore` (0-100) ke verdict. Angka awal yang bisa disetel."""

VIRUSTOTAL = "virustotal"
VIRUSTOTAL_NAME = "VirusTotal"
_VT_BASE = "https://www.virustotal.com/api/v3"
VT_MALICIOUS_ENGINES = 3
"""Mesin yang menandai berbahaya agar verdict `malicious`; 1-2 mesin (atau >= 3 `suspicious`) =
`suspicious`. Satu-dua mesin sering salah-positif. Angka awal yang bisa disetel."""
VT_SUSPICIOUS_ENGINES = 3

OTX = "otx"
OTX_NAME = "AlienVault OTX"
_OTX_BASE = "https://otx.alienvault.com/api/v1/indicators"
OTX_MALICIOUS_PULSES = 3
"""Banyaknya pulse komunitas yang memuat indikator agar verdict `malicious`; 1-2 = `suspicious`;
nol = `unknown` (OTX tidak pernah menyatakan sesuatu bersih). Pulse bisa memuat indikator jinak
sebagai konteks, jadi ini petunjuk, bukan vonis. Angka awal yang bisa disetel."""
_OTX_TAG_LIMIT = 8
_OTX_FAMILY_LIMIT = 6

_TIMEOUT = httpx.Timeout(20.0)


def make_client() -> httpx.AsyncClient:
    """Klien bersama satu run enrichment; timeout eksplisit supaya satu provider yang menggantung
    tidak menahan run."""
    return httpx.AsyncClient(timeout=_TIMEOUT, headers={"User-Agent": "vareon-ioc-enrichment"})


def _present(values: Mapping[str, Any]) -> dict[str, Any]:
    """Buang nilai kosong (`None`, string kosong); 0 dan angka lain tetap."""
    return {k: v for k, v in values.items() if v is not None and v != ""}


def abuseipdb_card(data: Mapping[str, Any]) -> dict[str, Any]:
    """Isi `data` dari `GET /api/v2/check` -> kartu. Skor kepercayaan penyalahgunaan 0-100 langsung
    jadi `score`. Skor 0 tanpa satu pun laporan = `unknown` (AbuseIPDB tidak pernah menyatakan IP
    "bersih", hanya belum ada yang melaporkan)."""
    score = int(data.get("abuseConfidenceScore") or 0)
    reports = int(data.get("totalReports") or 0)
    if score >= ABUSEIPDB_MALICIOUS:
        verdict = "malicious"
    elif score >= ABUSEIPDB_SUSPICIOUS:
        verdict = "suspicious"
    elif reports > 0:
        verdict = "clean"
    else:
        verdict = "unknown"
    return {
        "key": ABUSEIPDB,
        "name": ABUSEIPDB_NAME,
        "verdict": verdict,
        "score": score,
        "raw": _present(
            {
                "abuse_confidence": score,
                "total_reports": data.get("totalReports"),
                "distinct_reporters": data.get("numDistinctUsers"),
                "last_reported": data.get("lastReportedAt"),
                "country": data.get("countryCode"),
                "isp": data.get("isp"),
                "usage_type": data.get("usageType"),
                "domain": data.get("domain"),
            }
        ),
        "tags": ["tor"] if data.get("isTor") else [],
        "malware_families": [],
    }


def _unknown_card(key: str, name: str, raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "verdict": "unknown",
        "raw": raw,
        "tags": [],
        "malware_families": [],
    }


def skipped_card(key: str, name: str, reason: str) -> dict[str, Any]:
    """Kartu untuk IOC yang tidak bisa dicek provider ini (mis. IP non-publik). Tetap ditulis supaya
    IOC-nya tidak dipilih ulang tiap run; tanpa `score`, UI menampilkannya sebagai UNKNOWN."""
    return _unknown_card(key, name, {"skipped": reason})


def not_found_card(key: str, name: str) -> dict[str, Any]:
    """Provider menjawab 404: indikator belum pernah dilihatnya. Itu hasil sah (bukan galat), dan
    tetap ditulis supaya tidak ditanyakan ulang sebelum TTL habis."""
    return _unknown_card(key, name, {"note": f"not seen by {name}"})


async def lookup_abuseipdb(http: httpx.AsyncClient, api_key: str, ip: str) -> dict[str, Any]:
    resp = await http.get(
        _ABUSEIPDB_URL,
        params={"ipAddress": ip, "maxAgeInDays": _ABUSEIPDB_MAX_AGE_DAYS},
        headers={"Key": api_key, "Accept": "application/json"},
    )
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("response has no data object")
    return abuseipdb_card(data)


# ── VirusTotal ──────────────────────────────────────────────────────────────────────────────────


def virustotal_url_id(url: str) -> str:
    """Pengenal URL untuk `GET /urls/{id}`: base64 urlsafe tanpa padding; VirusTotal yang
    mengkanonikalkan URL-nya."""
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def virustotal_card(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """`data.attributes` objek VirusTotal (IP, domain, URL, atau file) -> kartu. `score` = persen
    mesin yang menandai (berbahaya + mencurigakan) dari yang menilai; verdict menurut jumlah
    mesin."""
    stats = attributes.get("last_analysis_stats") or {}
    malicious = int(stats.get("malicious") or 0)
    suspicious = int(stats.get("suspicious") or 0)
    rated = sum(
        int(stats.get(k) or 0) for k in ("harmless", "malicious", "suspicious", "undetected")
    )
    if rated == 0:
        verdict = "unknown"
    elif malicious >= VT_MALICIOUS_ENGINES:
        verdict = "malicious"
    elif malicious >= 1 or suspicious >= VT_SUSPICIOUS_ENGINES:
        verdict = "suspicious"
    else:
        verdict = "clean"
    flagged = malicious + suspicious
    classification = attributes.get("popular_threat_classification") or {}
    label = classification.get("suggested_threat_label")
    return {
        "key": VIRUSTOTAL,
        "name": VIRUSTOTAL_NAME,
        "verdict": verdict,
        "score": round(100 * flagged / rated) if rated else 0,
        "raw": _present(
            {
                "detections": f"{flagged}/{rated}" if rated else None,
                "reputation": attributes.get("reputation"),
                "file_name": attributes.get("meaningful_name"),
                "file_type": attributes.get("type_description"),
                "network_owner": attributes.get("as_owner"),
                "country": attributes.get("country"),
            }
        ),
        "tags": [str(t) for t in attributes.get("tags") or []],
        "malware_families": [str(label)] if label else [],
    }


def _virustotal_path(ioc_type: str, value: str) -> str:
    if ioc_type == "ip":
        return f"/ip_addresses/{value}"
    if ioc_type == "domain":
        return f"/domains/{value}"
    if ioc_type == "url":
        return f"/urls/{virustotal_url_id(value)}"
    if ioc_type in {"sha256", "sha1", "md5"}:
        return f"/files/{value}"
    raise ValueError(f"unsupported ioc type: {ioc_type}")


async def lookup_virustotal(
    http: httpx.AsyncClient, api_key: str, ioc_type: str, value: str
) -> dict[str, Any]:
    """Hanya GET (lookup); tidak pernah mengirim URL/berkas untuk dipindai. 404 = belum pernah
    dilihat VirusTotal (bukan galat)."""
    resp = await http.get(
        f"{_VT_BASE}{_virustotal_path(ioc_type, value)}", headers={"x-apikey": api_key}
    )
    if resp.status_code == 404:
        return not_found_card(VIRUSTOTAL, VIRUSTOTAL_NAME)
    resp.raise_for_status()
    payload = resp.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    attributes = data.get("attributes") if isinstance(data, dict) else None
    if not isinstance(attributes, dict):
        raise ValueError("response has no attributes object")
    return virustotal_card(attributes)


# ── AlienVault OTX ──────────────────────────────────────────────────────────────────────────────


def _family_name(family: Any) -> str:
    if isinstance(family, Mapping):
        return str(family.get("display_name") or family.get("id") or family.get("name") or "")
    return str(family or "")


def otx_card(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Respons `/indicators/<jenis>/<nilai>/general` -> kartu. Tanpa `score` (OTX tidak punya skor
    0-100); verdict menurut jumlah pulse yang memuat indikator. Tag dan keluarga malware diambil
    dari pulse-nya (tag yang paling sering dulu)."""
    info = payload.get("pulse_info") or {}
    count = int(info.get("count") or 0)
    pulses = [p for p in info.get("pulses") or [] if isinstance(p, Mapping)]
    tag_counts = Counter(str(t) for p in pulses for t in p.get("tags") or [] if t)
    families = list(
        dict.fromkeys(
            n for p in pulses for f in p.get("malware_families") or [] if (n := _family_name(f))
        )
    )
    if count >= OTX_MALICIOUS_PULSES:
        verdict = "malicious"
    elif count >= 1:
        verdict = "suspicious"
    else:
        verdict = "unknown"
    return {
        "key": OTX,
        "name": OTX_NAME,
        "verdict": verdict,
        "raw": _present(
            {
                "pulses": count,
                "reputation": payload.get("reputation") or None,
                "country": payload.get("country_name"),
                "asn": payload.get("asn"),
            }
        ),
        "tags": [t for t, _ in tag_counts.most_common(_OTX_TAG_LIMIT)],
        "malware_families": families[:_OTX_FAMILY_LIMIT],
    }


def _otx_section(ioc_type: str, value: str) -> str:
    if ioc_type == "ip":
        return "IPv6" if ":" in value else "IPv4"
    if ioc_type == "domain":
        return "domain"
    if ioc_type in {"sha256", "sha1", "md5"}:
        return "file"
    raise ValueError(f"unsupported ioc type: {ioc_type}")


async def lookup_otx(
    http: httpx.AsyncClient, api_key: str, ioc_type: str, value: str
) -> dict[str, Any]:
    """404 = OTX belum pernah melihat indikator itu (bukan galat). URL belum didukung (butuh
    penyandian path yang berbeda dan belum diverifikasi)."""
    resp = await http.get(
        f"{_OTX_BASE}/{_otx_section(ioc_type, value)}/{value}/general",
        headers={"X-OTX-API-KEY": api_key},
    )
    if resp.status_code == 404:
        return not_found_card(OTX, OTX_NAME)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("response is not an object")
    return otx_card(payload)
