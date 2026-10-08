"""Port `ScraperNewsWeb/app/services/epss_service.py` +
`cisa_kev_service.py` + `exploit_db_service.py`. Fase 7.4 Grup B (survei
2026-09-19). Tiga lookup eksternal CVE (FIRST.org EPSS, katalog CISA
KEV, pencarian exploit-db), digabung satu file -- ketiganya kecil
(86+86+127 baris), satu tema ("enrichment CVE eksternal"), satu router
(`cve.py`, udah diport sebelumnya).

Fungsi publik di sini (`run_epss_lookup`/`run_cisa_kev_lookup`/
`run_exploit_db_bulk_lookup`/`run_exploit_db_single_lookup`) sengaja
`session`-pertama, pola sama kayak service lain sesi ini -- INI FONDASI
buat Fase 7.8 ("CVE enrichment", salah satu dari 5 loop yang pindah ke
Celery beat): loop itu lama-nya manggil TEPAT fungsi `lookup_all_true_
positives()` yang sama, cuma dari scheduler bukan tombol manual. Begitu
7.8 dikerjain, tinggal bungkus fungsi-fungsi ini jadi task beat, gak
perlu nulis ulang."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from sqlalchemy.ext.asyncio import AsyncSession

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
_TIMEOUT = 30

# ── EPSS (FIRST.org) ─────────────────────────────────────────────────────────

_EPSS_URL = "https://api.first.org/data/v1/epss"
_EPSS_BATCH_SIZE = 100


async def _fetch_epss_scores(cve_ids: list[str]) -> dict[str, dict[str, Any]]:
    """`{cve_id_upper: {epss, percentile, date}}`."""
    if not cve_ids:
        return {}
    results: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i in range(0, len(cve_ids), _EPSS_BATCH_SIZE):
            batch = cve_ids[i : i + _EPSS_BATCH_SIZE]
            params: dict[str, str | int] = {"cve": ",".join(batch), "limit": _EPSS_BATCH_SIZE}
            resp = await client.get(_EPSS_URL, params=params, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            for entry in data.get("data", []):
                cve_id = entry.get("cve", "").strip().upper()
                if cve_id:
                    results[cve_id] = {
                        "epss": float(entry.get("epss", 0)),
                        "percentile": float(entry.get("percentile", 0)),
                        "date": entry.get("date", ""),
                    }
    return results


async def run_epss_lookup(session: AsyncSession, *, client_id: str | None = None) -> dict[str, Any]:
    """Fetch skor EPSS buat semua CVE true-positive di DB, simpen hasilnya."""
    repo = AsyncCveTrackerRepo(session)
    tp_ids = await repo.list_true_positive_cve_ids(client_id)
    upper_ids = [cid.upper() for cid in tp_ids]

    scores = await _fetch_epss_scores(upper_ids)
    await repo.apply_epss_scores(scores)

    return {
        "checked": len(tp_ids),
        "scored": len(scores),
        "no_data": len(tp_ids) - len(scores),
    }


# ── CISA KEV ─────────────────────────────────────────────────────────────────

_CISA_KEV_URL = (
    "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
)


async def _fetch_cisa_kev() -> dict[str, dict[str, Any]]:
    """Fetch seluruh katalog CISA KEV. `{cve_id_upper: vuln_dict}`."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(_CISA_KEV_URL, headers=_HEADERS)
        resp.raise_for_status()
        data = resp.json()

    catalog: dict[str, dict[str, Any]] = {}
    for vuln in data.get("vulnerabilities", []):
        cve_id = vuln.get("cveID", "").strip().upper()
        if cve_id:
            catalog[cve_id] = vuln
    return catalog


async def run_cisa_kev_lookup(
    session: AsyncSession, *, client_id: str | None = None
) -> dict[str, Any]:
    """Cross-reference semua CVE true-positive di DB vs katalog KEV penuh."""
    repo = AsyncCveTrackerRepo(session)
    tp_ids = await repo.list_true_positive_cve_ids(client_id)

    catalog = await _fetch_cisa_kev()
    matched = await repo.apply_cisa_kev_hits(catalog, tp_ids)

    return {
        "checked": len(tp_ids),
        "matched": len(matched),
        "catalog_size": len(catalog),
        "matched_cves": matched,
    }


# ── exploit-db ───────────────────────────────────────────────────────────────

_EXPLOITDB_SEARCH = "https://www.exploit-db.com/search"
_EXPLOITDB_HEADERS = {
    **_HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.exploit-db.com/",
}
_EXPLOITDB_TIMEOUT = 20


def _strip_cve_prefix(cve_id: str) -> str:
    return re.sub(r"^CVE-", "", cve_id, flags=re.IGNORECASE)


def _extract_title(description: Any) -> str:
    """API exploit-db BERUBAH BENTUK sejak kode lama ditulis -- `description`
    SEKARANG list `[edb_id_str, title_str]` (ketauan pas live-test asli,
    bukan tebakan), bukan string polos kayak yang diasumsikan
    `exploit_db_service.py` lama (`row.get("description", "").strip()`
    langsung, crash `AttributeError` kalau dibiarin). Ini BUKAN "port apa
    adanya" -- kontrak API eksternal yang beneran berubah, bukan
    keputusan desain lama yang perlu dipertahanin. String polos tetap
    didukung buat jaga-jaga API balik ke bentuk lama lagi."""
    if isinstance(description, list):
        return str(description[1]).strip() if len(description) > 1 else ""
    return str(description or "").strip()


async def _lookup_exploitdb(cve_id: str) -> list[dict[str, Any]]:
    numeric_id = _strip_cve_prefix(cve_id)
    async with httpx.AsyncClient(timeout=_EXPLOITDB_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(
            _EXPLOITDB_SEARCH, params={"cve": numeric_id}, headers=_EXPLOITDB_HEADERS
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for row in data.get("data", []):
        edb_id = str(row.get("id", "")).strip()
        if not edb_id:
            continue
        href = (row.get("href") or f"exploits/{edb_id}").lstrip("/")
        results.append(
            {
                "edb_id": edb_id,
                "title": _extract_title(row.get("description")),
                "posted_on": (row.get("date_published") or "").strip(),
                "url": f"https://www.exploit-db.com/{href}",
                "source": "exploit-db",
                "type": "exploit",
            }
        )
    return results


async def run_exploit_db_single_lookup(session: AsyncSession, cve_id: str) -> dict[str, Any]:
    """Lookup satu CVE ke exploit-db, simpen hasilnya. Balikin ringkasan."""
    try:
        exploits = await _lookup_exploitdb(cve_id)
        await AsyncCveTrackerRepo(session).apply_exploit_hits(cve_id, exploits)
        return {"cve_id": cve_id, "found": len(exploits), "error": None}
    except Exception as exc:
        return {"cve_id": cve_id, "found": 0, "error": str(exc)}


async def run_exploit_db_bulk_lookup(
    session: AsyncSession, *, client_id: str | None = None
) -> dict[str, Any]:
    """Exploit-db lookup buat SEMUA CVE true-positive, batch 5 + jeda 1
    detik antar-batch -- port rate-limit lama (situs exploit-db gak
    punya API resmi, hormatin biar gak diblokir)."""
    tp_ids = await AsyncCveTrackerRepo(session).list_true_positive_cve_ids(client_id)

    results: list[dict[str, Any]] = []
    batch_size = 5
    for i in range(0, len(tp_ids), batch_size):
        batch = tp_ids[i : i + batch_size]
        # Sekuensial per-CVE (bukan asyncio.gather) -- satu AsyncSession
        # gak aman dipakai concurrent, constraint yang sama udah
        # didokumentasikan berkali-kali sesi ini. Legacy nge-gather satu
        # batch (motor/Mongo aman concurrent); throttle "batch 5 + jeda 1s"
        # tetap dipertahankan buat exploit-db-nya sendiri (rate-limit situs
        # eksternal, bukan soal DB), jalan sekuensial per-item di dalam
        # tiap "batch" logis.
        for cid in batch:
            results.append(await run_exploit_db_single_lookup(session, cid))
        if i + batch_size < len(tp_ids):
            await asyncio.sleep(1)

    total_found = sum(r["found"] for r in results)
    total_errors = sum(1 for r in results if r["error"])
    return {
        "checked": len(results),
        "with_exploits": sum(1 for r in results if r["found"] > 0),
        "total_found": total_found,
        "errors": total_errors,
        "details": results,
    }
