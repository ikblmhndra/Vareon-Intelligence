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


def skipped_card(key: str, name: str, reason: str) -> dict[str, Any]:
    """Kartu untuk IOC yang tidak bisa dicek provider ini (mis. IP non-publik). Tetap ditulis supaya
    IOC-nya tidak dipilih ulang tiap run; tanpa `score`, UI menampilkannya sebagai UNKNOWN."""
    return {
        "key": key,
        "name": name,
        "verdict": "unknown",
        "raw": {"skipped": reason},
        "tags": [],
        "malware_families": [],
    }


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
