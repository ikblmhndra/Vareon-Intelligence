"""Lookup langsung satu CVE sembarang (`GET /api/cve/lookup/{cve_id}`): mirror lokal, NVD, CIRCL,
Exploit-DB dan EPSS dipanggil paralel, masing-masing dengan batas waktu sendiri.

Aturan:
- TIDAK menulis apa pun ke tracker/ticket/FP; hanya baca. Audit ditulis router.
- Satu sumber timeout/error tidak menggagalkan lookup: statusnya tercatat per sumber.
- Limit: per user `USER_LIMIT_PER_MIN`/menit (Redis) dan bucket NVD global `NVD_BUCKET_MAX` per
  `NVD_BUCKET_WINDOW_S` detik (kuota NVD dipakai bersama; kunci publik 50 req/30 dtk).
- Cache 6 jam untuk bagian PUBLIK saja (kunci `cve:lookup:{cve_id}`). Cache hanya ditulis bila
  TIDAK ada sumber berstatus error/timeout/rate_limited; hasil sebagian tidak dibekukan 6 jam.
  Field khusus client (`tracked`, `tracker_tech`, `false_positive`) dihitung ulang tiap request,
  jadi client lain tidak pernah melihat tracker client A lewat cache."""

from __future__ import annotations

import asyncio
import datetime
from collections.abc import Awaitable
from typing import Any

import httpx
import structlog
from cti_core.db.repositories.catalog_read import AsyncCatalogRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo, AsyncCveTrackerRepo
from cti_core.runtime_secrets.overlay import effective_settings
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.cve_lookup import (
    CveLookupOut,
    ExploitHit,
    KevInfo,
    LookupSource,
    LookupSourceId,
    LookupSourceStatus,
)
from cti_api.services import cve_lookup

log = structlog.get_logger()

USER_LIMIT_PER_MIN = 10
NVD_BUCKET_MAX = 5
NVD_BUCKET_WINDOW_S = 30
# Bucket NVD ini counter Redis TERSENDIRI, bukan kuota bersama dengan pacing `new_cve` (itu
# in-process, tanpa bucket Redis); angkanya sengaja konservatif (kunci NVD: 50 req/30 dtk).
CACHE_TTL_S = 21600
SOURCE_TIMEOUT_S = 10.0

_NVD_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_CIRCL_URL = "https://cve.circl.lu/api/cve/{cve_id}"
_MAX_AFFECTED = 20
_MAX_REFERENCES = 50
_FAILED: frozenset[LookupSourceStatus] = frozenset({"error", "timeout", "rate_limited"})
_UTC = datetime.UTC


class LookupRateLimited(Exception):
    """Limit per-user terlampaui; `retry_after` dalam detik."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"rate limited, retry in {retry_after}s")
        self.retry_after = retry_after


# ── parser ───────────────────────────────────────────────────────────────────────────────────


def _dt(value: Any) -> datetime.datetime | None:
    """ISO 8601 (dengan/tanpa `Z`/zona) jadi datetime berzona; tanpa zona dianggap UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_UTC)


def _date(value: Any) -> datetime.date | None:
    parsed = _dt(value)
    return parsed.date() if parsed else None


def _en(items: Any) -> str:
    """Teks `value` berbahasa Inggris pertama (fallback: item pertama) dari daftar deskripsi."""
    rows = [r for r in items or [] if isinstance(r, dict) and r.get("value")]
    for row in rows:
        if row.get("lang", "").startswith("en"):
            return str(row["value"]).strip()
    return str(rows[0]["value"]).strip() if rows else ""


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def parse_nvd(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Respons NVD 2.0 (`vulnerabilities[0].cve`) ke field seragam; `None` bila tidak ada CVE."""
    vulns = payload.get("vulnerabilities") or []
    cve = vulns[0].get("cve") if vulns and isinstance(vulns[0], dict) else None
    if not cve:
        return None

    score = severity = vector = None
    for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV40", "cvssMetricV2"):
        metrics = cve.get("metrics", {}).get(key) or []
        if not metrics:
            continue
        pick = next((m for m in metrics if m.get("type") == "Primary"), metrics[0])
        data = pick.get("cvssData", {})
        score = _num(data.get("baseScore"))
        severity = data.get("baseSeverity") or pick.get("baseSeverity")
        vector = data.get("vectorString")
        break

    cwe: list[str] = []
    for weakness in cve.get("weaknesses") or []:
        for desc in weakness.get("description") or []:
            value = desc.get("value", "")
            if value.startswith("CWE-") and value not in cwe:
                cwe.append(value)

    affected: list[str] = []
    for conf in cve.get("configurations") or []:
        for node in conf.get("nodes") or []:
            for match in node.get("cpeMatch") or []:
                parts = str(match.get("criteria", "")).split(":")
                if match.get("vulnerable") and len(parts) > 5:
                    line = " ".join(
                        p for p in (parts[3], parts[4], parts[5]) if p not in ("*", "-")
                    )
                    if line and line not in affected:
                        affected.append(line)

    kev = None
    if cve.get("cisaExploitAdd"):
        kev = KevInfo(
            added=_date(cve.get("cisaExploitAdd")),
            due=_date(cve.get("cisaActionDue")),
            action=str(cve.get("cisaRequiredAction") or ""),
        )

    return {
        "summary": _en(cve.get("descriptions")),
        "published": _date(cve.get("published")),
        "modified": _dt(cve.get("lastModified")),
        "cvss_score": score,
        "cvss_severity": severity,
        "cvss_vector": vector,
        "cwe": cwe,
        "references": [r["url"] for r in cve.get("references") or [] if r.get("url")][
            :_MAX_REFERENCES
        ],
        "affected": affected[:_MAX_AFFECTED],
        "kev": kev,
    }


def parse_circl(payload: dict[str, Any]) -> dict[str, Any] | None:
    """CVE JSON 5 (respons CIRCL `/api/cve/{id}`) ke field seragam; `None` bila bukan record."""
    containers = payload.get("containers")
    cna = containers.get("cna") if isinstance(containers, dict) else None
    if not isinstance(cna, dict):
        return None
    meta = payload.get("cveMetadata", {})

    metrics = list(cna.get("metrics") or [])
    for adp in containers.get("adp") or []:
        metrics.extend(adp.get("metrics") or [])
    score = severity = vector = None
    for key in ("cvssV3_1", "cvssV3_0", "cvssV4_0", "cvssV2_0"):
        found = next((m[key] for m in metrics if isinstance(m.get(key), dict)), None)
        if found:
            score = _num(found.get("baseScore"))
            severity = found.get("baseSeverity")
            vector = found.get("vectorString")
            break

    affected: list[str] = []
    for item in cna.get("affected") or []:
        name = " ".join(p for p in (item.get("vendor"), item.get("product")) if p)
        for ver in item.get("versions") or [{}]:
            line = f"{name} {ver.get('version', '')}".strip()
            if ver.get("lessThan"):
                line += f" < {ver['lessThan']}"
            elif ver.get("lessThanOrEqual"):
                line += f" <= {ver['lessThanOrEqual']}"
            if line and line not in affected:
                affected.append(line)

    cwe: list[str] = []
    for problem in cna.get("problemTypes") or []:
        for desc in problem.get("descriptions") or []:
            cwe_id = desc.get("cweId")
            if cwe_id and cwe_id not in cwe:
                cwe.append(cwe_id)

    return {
        "summary": _en(cna.get("descriptions")),
        "published": _date(meta.get("datePublished")),
        "modified": _dt(meta.get("dateUpdated")),
        "cvss_score": score,
        "cvss_severity": severity,
        "cvss_vector": vector,
        "cwe": cwe,
        "references": [r["url"] for r in cna.get("references") or [] if r.get("url")][
            :_MAX_REFERENCES
        ],
        "affected": affected[:_MAX_AFFECTED],
    }


def merge_fields(*parts: dict[str, Any] | None) -> dict[str, Any]:
    """Gabung per field: nilai tak kosong pertama menang (urutan pemanggilan: NVD, CIRCL, mirror).
    `0` dan `False` dianggap nilai; `None`, `""`, dan list/dict kosong tidak."""
    merged: dict[str, Any] = {}
    for part in parts:
        for key, value in (part or {}).items():
            if value is None or value == "" or value == [] or value == {}:
                continue
            merged.setdefault(key, value)
    return merged


# ── fetcher (modul-level supaya test bisa di-stub) ───────────────────────────────────────────


async def _fetch_nvd(cve_id: str) -> dict[str, Any] | None:
    """Payload mentah NVD 2.0 untuk satu CVE; `None` bila NVD menjawab 404."""
    headers = dict(cve_lookup._HEADERS)
    key = effective_settings().nvd.api_key
    if key:
        headers["apiKey"] = key
    async with httpx.AsyncClient(timeout=SOURCE_TIMEOUT_S, follow_redirects=True) as client:
        resp = await client.get(_NVD_URL, params={"cveId": cve_id}, headers=headers)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data


async def _fetch_circl(cve_id: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=SOURCE_TIMEOUT_S, follow_redirects=True) as client:
        resp = await client.get(_CIRCL_URL.format(cve_id=cve_id), headers=cve_lookup._HEADERS)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data: dict[str, Any] | None = resp.json()
        return data if isinstance(data, dict) else None


# ── orkestrasi ───────────────────────────────────────────────────────────────────────────────

_Result = tuple[LookupSourceStatus, Any]


async def _guarded(coro: Awaitable[Any], *, none_is: LookupSourceStatus = "not_found") -> _Result:
    """Jalankan satu sumber dengan batas waktu; apa pun hasilnya jadi (status, data)."""
    try:
        data = await asyncio.wait_for(coro, SOURCE_TIMEOUT_S)
    except (TimeoutError, httpx.TimeoutException):
        return "timeout", None
    except Exception as exc:
        log.warning("cve_live_lookup.source_failed", error=repr(exc))
        return "error", None
    return ("ok", data) if data else (none_is, None)


async def _mirror_part(
    session: AsyncSession, cve_id: str, client_id: str
) -> tuple[LookupSourceStatus, dict[str, Any] | None]:
    """Baca mirror lokal. Tanpa `wait_for`: membatalkan query di tengah jalan merusak session."""
    try:
        # Savepoint: query gagal hanya me-rollback savepoint, bukan transaksi request
        # (pembacaan tracker/FP sesudahnya tetap jalan).
        async with session.begin_nested():
            row = await AsyncCatalogRepo(session).get_cve(cve_id, client_id)
    except Exception as exc:
        log.warning("cve_live_lookup.mirror_failed", error=repr(exc))
        return "error", None
    if row is None:
        return "not_found", None
    rec = row.record
    return "ok", {
        "summary": rec.summary,
        "published": rec.published_date,
        "modified": rec.modified_at,
        "cvss_score": rec.cvss_score,
        "cvss_severity": rec.cvss_severity,
        "cvss_vector": rec.cvss_vector,
        "references": list(rec.reference_urls or []),
        "affected": list(rec.affected_lines or []),
    }


async def _check_user_limit(redis: Redis, username: str) -> None:
    key = f"cve:lookup:user:{username}"
    count = await redis.incr(key)
    # `ttl < 0` menyembuhkan kunci tanpa TTL (proses mati di antara INCR dan EXPIRE).
    if count == 1 or await redis.ttl(key) < 0:
        await redis.expire(key, 60)
    if count > USER_LIMIT_PER_MIN:
        ttl = await redis.ttl(key)
        raise LookupRateLimited(ttl if ttl > 0 else 60)


async def _take_nvd_token(redis: Redis) -> bool:
    key = "cve:lookup:nvd"
    count = await redis.incr(key)
    if count == 1 or await redis.ttl(key) < 0:
        await redis.expire(key, NVD_BUCKET_WINDOW_S)
    return bool(count <= NVD_BUCKET_MAX)


async def _nvd_source(redis: Redis, cve_id: str) -> _Result:
    if not await _take_nvd_token(redis):
        return "rate_limited", None
    status, payload = await _guarded(_fetch_nvd(cve_id))
    parsed = parse_nvd(payload) if status == "ok" and payload else None
    return ("ok", parsed) if parsed else ("not_found" if status == "ok" else status, None)


async def _circl_source(cve_id: str) -> _Result:
    status, payload = await _guarded(_fetch_circl(cve_id))
    parsed = parse_circl(payload) if status == "ok" and payload else None
    return ("ok", parsed) if parsed else ("not_found" if status == "ok" else status, None)


async def _exploitdb_source(cve_id: str) -> _Result:
    # daftar kosong = pencarian sukses tanpa exploit, bukan "tidak ketemu"
    status, hits = await _guarded(cve_lookup._lookup_exploitdb(cve_id))
    if status == "not_found":
        return "ok", []
    return status, hits


async def _epss_source(cve_id: str) -> _Result:
    status, scores = await _guarded(cve_lookup._fetch_epss_scores([cve_id]))
    entry = scores.get(cve_id) if status == "ok" else None
    return ("ok", entry) if entry else ("not_found" if status == "ok" else status, None)


async def live_lookup(
    session: AsyncSession,
    redis: Redis,
    *,
    cve_id: str,
    client_id: str,
    username: str,
) -> CveLookupOut:
    """Lookup satu CVE (id sudah dinormalisasi). Lihat docstring modul untuk aturan."""
    await _check_user_limit(redis, username)

    cache_key = f"cve:lookup:{cve_id}"
    cached = await redis.get(cache_key)
    if cached:
        out = CveLookupOut.model_validate_json(cached)
        for src in out.sources:
            src.status = "cached"
    else:
        out = await _fetch_public(session, redis, cve_id=cve_id, client_id=client_id)
        if not any(s.status in _FAILED for s in out.sources):
            await redis.set(cache_key, out.model_dump_json(), ex=CACHE_TTL_S)

    # bagian khusus client: selalu dihitung ulang, tidak pernah dari cache
    tracked = await AsyncCveTrackerRepo(session).get_by_cve_ids([cve_id], client_id=client_id)
    out.tracked = bool(tracked)
    out.tracker_tech = tracked[0].tech if tracked else None
    out.false_positive = cve_id in await AsyncCveFalsePositiveRepo(session).list_cve_ids(client_id)
    return out


async def _fetch_public(
    session: AsyncSession, redis: Redis, *, cve_id: str, client_id: str
) -> CveLookupOut:
    mirror, nvd, circl, exploits, epss = await asyncio.gather(
        _mirror_part(session, cve_id, client_id),
        _nvd_source(redis, cve_id),
        _circl_source(cve_id),
        _exploitdb_source(cve_id),
        _epss_source(cve_id),
    )
    now = datetime.datetime.now(_UTC)
    results: dict[LookupSourceId, _Result] = {
        "mirror": mirror,
        "nvd": nvd,
        "circl": circl,
        "exploitdb": exploits,
        "epss": epss,
    }
    fields = merge_fields(nvd[1], circl[1], mirror[1])
    epss_entry: dict[str, Any] = epss[1] or {}
    return CveLookupOut(
        cve_id=cve_id,
        in_mirror=mirror[0] == "ok",
        epss_score=epss_entry.get("epss"),
        epss_percentile=epss_entry.get("percentile"),
        exploits=[
            ExploitHit(
                title=str(h.get("title", "")),
                url=str(h.get("url", "")),
                published=str(h.get("posted_on", "")),
            )
            for h in exploits[1] or []
        ],
        sources=[
            LookupSource(id=sid, status=status, fetched_at=now if status == "ok" else None)
            for sid, (status, _) in results.items()
        ],
        **fields,
    )
