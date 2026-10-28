"""Port `ScraperNewsWeb/app/services/fp_analytics_service.py`. Fase 7.4
Grup D. Heuristik false-positive IOC (domain/IP/email benign dikenal +
tren FP per-source dari `IOCFeedback`), fully self-contained -- gak
nyentuh service lain.

Cache TTL module-level (`_fp_analytics_cache`), pola sama kayak
`spike.py`/`risk_matrix.py` (Fase 7.3 Bagian 5): per-proses uvicorn,
BUKAN per-cluster (kalau API di-scale >1 worker, tiap worker punya cache
sendiri) -- keterbatasan yang sama juga ada di legacy (satu proses
uvicorn), bukan regresi baru di sini."""

from __future__ import annotations

import datetime
import ipaddress
import time
from typing import Any

from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from sqlalchemy.ext.asyncio import AsyncSession

_BENIGN_DOMAINS: frozenset[str] = frozenset(
    {
        "amazonaws.com",
        "cloudflare.com",
        "google.com",
        "microsoft.com",
        "akamai.net",
        "fastly.net",
        "cloudfront.net",
        "azureedge.net",
        "googleusercontent.com",
        "googleapis.com",
        "gstatic.com",
        "github.com",
        "githubusercontent.com",
        "windows.net",
        "azure.com",
        "office.com",
        "sharepoint.com",
        "yahoo.com",
        "outlook.com",
        "gmail.com",
        "hotmail.com",
        "live.com",
    }
)

_BENIGN_EMAIL_PROVIDERS: frozenset[str] = frozenset(
    {
        "gmail.com",
        "yahoo.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "icloud.com",
        "protonmail.com",
        "mail.com",
        "aol.com",
    }
)

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_fp_analytics_cache: dict[str, Any] | None = None
_fp_analytics_cache_ts: float = 0.0
_FP_CACHE_TTL = 300.0

_AL_TYPE_BY_IOC_TYPE = {"url": "url_domain", "email": "email_domain", "ip": "ip"}
"""Legacy juga punya `url_with_path` -> `url_domain` -- tipe itu gak ada
di `IOC._VALID_TYPES` skema baru (cuma `url`), jadi di-drop."""


def _matches_benign_domain(value: str) -> tuple[bool, str]:
    v = value.lower().strip()
    for d in _BENIGN_DOMAINS:
        if v == d or v.endswith("." + d):
            return True, f"matches known CDN/cloud domain {d}"
    return False, ""


def _is_private_ip(value: str) -> tuple[bool, str]:
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return False, ""
    for net in _PRIVATE_NETWORKS:
        if addr in net:
            return True, f"IP in private/reserved range {net}"
    return False, ""


def _matches_benign_email_domain(value: str) -> tuple[bool, str]:
    domain = value.lower().split("@")[-1] if "@" in value else ""
    if domain in _BENIGN_EMAIL_PROVIDERS:
        return True, f"common email provider domain {domain}"
    return False, ""


def _is_benign_url(value: str) -> tuple[bool, str]:
    lower = value.lower()
    for d in _BENIGN_DOMAINS:
        if (
            f"://{d}/" in lower
            or f"://{d}" == lower
            or lower.startswith(f"https://{d}")
            or lower.startswith(f"http://{d}")
        ):
            return True, f"URL from known benign domain {d}"
    return False, ""


def invalidate_fp_cache() -> None:
    global _fp_analytics_cache
    _fp_analytics_cache = None


async def get_fp_analytics(session: AsyncSession, *, force: bool = False) -> dict[str, Any]:
    global _fp_analytics_cache, _fp_analytics_cache_ts
    now_mono = time.monotonic()
    if (
        not force
        and _fp_analytics_cache is not None
        and (now_mono - _fp_analytics_cache_ts) < _FP_CACHE_TTL
    ):
        return _fp_analytics_cache

    now = datetime.datetime.now(datetime.UTC)
    cutoff_30d = now - datetime.timedelta(days=30)

    fp_by_source: dict[str, dict[str, Any]] = {}
    fp_by_type: dict[str, dict[str, Any]] = {}
    fp_by_day: dict[str, dict[str, int]] = {}
    suggested_map: dict[str, dict[str, Any]] = {}

    iocs = await AsyncIndicatorRepo(session).list_with_feedback()
    for ioc in iocs:
        tp, fp = ioc.tp_count, ioc.fp_count

        if ioc.sources:
            sname = ioc.sources[0].source_name or "unknown"
            bucket = fp_by_source.setdefault(
                sname, {"total_iocs": 0, "fp_count": 0, "fp_rate": 0.0}
            )
            bucket["total_iocs"] += 1
            bucket["fp_count"] += fp

        type_bucket = fp_by_type.setdefault(
            ioc.type, {"total_iocs": 0, "fp_count": 0, "fp_rate": 0.0}
        )
        type_bucket["total_iocs"] += 1
        type_bucket["fp_count"] += fp

        if fp >= 3 and tp == 0:
            al_type = _AL_TYPE_BY_IOC_TYPE.get(ioc.type)
            if al_type:
                suggested_map[f"{ioc.type}:{ioc.value}"] = {
                    "ioc_type": ioc.type,
                    "value": ioc.value,
                    "allowlist_type": al_type,
                    "fp_count": fp,
                }

        for fb in ioc.feedback:
            if fb.submitted_at < cutoff_30d:
                continue
            day = fb.submitted_at.date().isoformat()
            day_bucket = fp_by_day.setdefault(day, {"fp_count": 0, "total_count": 0})
            day_bucket["total_count"] += 1
            if fb.verdict == "fp":
                day_bucket["fp_count"] += 1

    for d in fp_by_source.values():
        total = d["total_iocs"]
        d["fp_rate"] = round(d["fp_count"] / total, 3) if total else 0.0
    for d in fp_by_type.values():
        total = d["total_iocs"]
        d["fp_rate"] = round(d["fp_count"] / total, 3) if total else 0.0

    fp_trend = [
        {
            "date": day,
            "fp_count": v["fp_count"],
            "total_count": v["total_count"],
            "fp_rate": round(v["fp_count"] / v["total_count"], 3) if v["total_count"] else 0.0,
        }
        for day, v in sorted(fp_by_day.items())
    ]

    result = {
        "fp_by_source": fp_by_source,
        "fp_by_type": fp_by_type,
        "suggested_allowlist": list(suggested_map.values()),
        "fp_trend": fp_trend,
    }

    _fp_analytics_cache = result
    _fp_analytics_cache_ts = now_mono
    return result


async def get_fp_source_rates(session: AsyncSession) -> dict[str, dict[str, Any]]:
    analytics = await get_fp_analytics(session)
    return analytics.get("fp_by_source", {})  # type: ignore[no-any-return]


async def auto_suppress_check(
    session: AsyncSession, ioc_type: str, value: str, source_name: str | None = None
) -> dict[str, Any]:
    should_suppress = False
    reason = ""
    confidence = 0.0

    if ioc_type == "domain":
        should_suppress, reason = _matches_benign_domain(value)
        confidence = 0.95 if should_suppress else 0.0
    elif ioc_type == "ip":
        should_suppress, reason = _is_private_ip(value)
        confidence = 0.99 if should_suppress else 0.0
    elif ioc_type == "url":
        should_suppress, reason = _is_benign_url(value)
        confidence = 0.95 if should_suppress else 0.0
    elif ioc_type == "email":
        should_suppress, reason = _matches_benign_email_domain(value)
        confidence = 0.90 if should_suppress else 0.0

    if not should_suppress and source_name:
        source_rates = await get_fp_source_rates(session)
        sr = source_rates.get(source_name)
        if sr and sr["total_iocs"] >= 10 and sr["fp_rate"] > 0.5:
            should_suppress = True
            reason = (
                f"source '{source_name}' has {sr['fp_rate'] * 100:.0f}% FP rate "
                f"({sr['fp_count']}/{sr['total_iocs']} IOCs)"
            )
            confidence = min(0.5 + sr["fp_rate"] * 0.4, 0.90)

    return {"should_suppress": should_suppress, "reason": reason, "confidence": confidence}
