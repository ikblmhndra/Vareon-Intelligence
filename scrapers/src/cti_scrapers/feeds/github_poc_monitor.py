"""GitHub CVE POC Monitor -- BESPOKE, subclass `BaseScraper` langsung.
Nge-`yield` `CvePocItem` dari DUA strategi pencarian yang konvergen ke
tipe yang sama (`ScraperNews/githubPOCMonitor.py` asli motong dua ini jadi
"Phase 1"/"Phase 2" terpisah, di sini disatuin karena OUTPUT-nya sama):

1. **Broad**: search repo GitHub berpola nama `cve-{tahun}-*` (tahun ini +
   tahun lalu), filter techstack lewat data vendor/produk dari MITRE.
   Gak butuh CVE-nya udah ke-track di `cve_tracker` kita -- nemuin POC buat
   CVE yang MUNGKIN belum pernah ketauan `new_cve.py`.
2. **Targeted**: buat tiap CVE yang UDAH ke-track (`reference_data=
   "true_positive_cves"`, bukan false-positive), search spesifik
   `{cve_id} in:name,description`, skip URL yang udah tercatat.

Bandingkan sama script lama:
- `MongoClient` langsung + baca `cve_tracker`/`cve_false_positives` di
  tengah script -- diganti `ctx.reference["true_positive_cves"]` (`Runner`
  yang query, lihat docstring `ScrapeContext`).
- Bookkeeping `offset/githubpoc.txt` manual -- gak dibutuhin, dedup
  `CvePocItem` (`cve_id:url`) udah namespace per scraper_id di framework.
- `time.sleep(3)`/`time.sleep(2)` manual -- `meta.rate_limit` yang urus.
  Di-set match limit ASLI GitHub Search API (30/menit terautentikasi,
  BEDA dari REST biasa 5000/jam) -- lebih ketat dari limit scraper GitHub
  lain (`blackorbird.py` dkk, yang cuma mukul endpoint REST biasa).
- Telegram alert (`send_alert_poc`): SEKARANG ada (2026-10-02), sebagai `NoticeItem` topik `github_poc`
  yang menyertai `CvePocItem` -- HANYA dari pencarian broad (legacy: cuma fase 1 yang mengirim; fase 2
  menulis DB saja). Beda dari legacy, sengaja: (1) sekali per repo -- alert "UPDATED CVE POC" (tiap SHA
  baru) dihapus; (2) hanya repo yang dibuat <= `_ALERT_MAX_AGE` (3 hari) -- tanpa ini deploy ke DB yang
  sudah berisi (dedup `NoticeItem` baru, repo lama belum "seen") membanjiri channel dengan PoC lama;
  (3) semua teks dari luar di-`html.escape` (legacy: satu `<` di deskripsi repo membuat Telegram menolak
  pesan). Sink `NoticeItem` tidak menelan kegagalan: kirim gagal -> item di-retry run berikutnya,
  sementara `CvePocItem`-nya tetap tersimpan.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import CvePocItem, NoticeItem
from cti_scraper.schedule import spread

from cti_scrapers.feeds._pacing import get_waiting

_SEARCH_URL = "https://api.github.com/search/repositories"
_MITRE_URL = "https://cveawg.mitre.org/api/cve"


_CVE_ID_RE = re.compile(r"(cve-\d{4}-\d+)")

# 4 repo yang kebukti false-positive (nama/deskripsi kebetulan mirip CVE
# POC tapi bukan) -- diambil apa adanya dari script lama.
_WHITELIST_URLS = frozenset(
    {
        "https://github.com/ThoristKaw/Anydesk-Exploit-CVE-2025-12654-RCE-Builder",
        "https://github.com/Subha-coder-hash/Anydesk-Exploit-CVE-2025-12654-RCE-Builder",
        "https://github.com/Yuweixn/Anydesk-Exploit-CVE-2025-12654-RCE-Builder",
        "https://github.com/Taonauz/Anydesk-Exploit-CVE-2025-12654-RCE-Builder",
    }
)


_ALERT_MAX_AGE = timedelta(days=3)
"""Repo yang dibuat lebih lama dari ini TIDAK di-alert (tetap disimpan ke `cve_tracker.pocs`)."""
_WIB = timedelta(hours=7)
_DESC_MAX = 500
_AFFECTED_MAX = 800
"""Batas karakter field panjang: `NoticeItem` > 4096 karakter ditolak sink (scraper yang memotong)."""


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _poc_notice(
    result: dict[str, Any], *, cve_id: str, vendor: str, affected: str, now: datetime
) -> NoticeItem | None:
    """Alert Telegram untuk SATU repo PoC baru (port `send_alert_poc` fase 1 legacy), atau `None`
    kalau repo-nya terlalu lama / `created_at`-nya tidak terbaca (umur tak bisa dinilai)."""
    try:
        created = datetime.strptime(result["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    except (KeyError, TypeError, ValueError):
        return None
    if now - created > _ALERT_MAX_AGE:
        return None

    esc = html.escape
    repo_url = result["html_url"]
    name = result["name"]
    posted = (created + _WIB).strftime("%H:%M:%S %d-%m-%Y")
    text = (
        "\n        === <b>NEW CVE POC ON GITHUB</b> ===\n"
        f"<b>Posted On</b>: {posted}\n"
        f"<b>CVE</b>: {esc(cve_id.upper())}\n"
        "<b>Repo</b>:\n"
        f"    <b>Name</b>: {esc(name)} POC for {esc(vendor)}\n"
        f"    <b>Owner</b>: {esc(result['owner']['login'])}\n"
        f"    <b>Description</b>: {esc(_clip(result.get('description') or '', _DESC_MAX))}\n"
        f"    <b>Language</b>: {esc(result.get('language') or '-')}\n"
        f"<b>Affected CVE Product Version</b>: {esc(_clip(affected, _AFFECTED_MAX))}\n"
        f'<b>Github Link</b>: <a href="{esc(repo_url)}">Link</a>'
    )
    return NoticeItem(
        topic="github_poc",
        text=text,
        # Awalan "alert:" WAJIB: `CvePocItem.dedup_key()` = "<cve>:<url>" di namespace scraper_id yang
        # sama -- key identik membuat salah satunya dibuang sebagai duplikat.
        key=f"alert:{cve_id}:{repo_url}",
        title=f"{cve_id.upper()} POC: {name}",
        url=repo_url,
        posted_on=created.date(),
    )


def _poc_type(name: str, desc: str) -> str:
    return "exploit" if re.search(r"\bexploit\b", f"{name} {desc}".lower()) else "poc"


def _mitre_vendor_product(ctx: ScrapeContext, cve_id: str) -> tuple[str, str]:
    try:
        data = get_waiting(ctx, f"{_MITRE_URL}/{cve_id.upper()}").json()
    except Exception:  # MITRE kadang balikin bentuk gak terduga -- gak fatal di sini
        return "Unknown", "Unknown"

    cna = data.get("containers", {})
    for container_key in ("cna", "adp"):
        container = cna.get(container_key)
        affected_list = container.get("affected") if isinstance(container, dict) else None
        if not affected_list:
            continue
        vendor = ""
        products = []
        for aff in affected_list:
            vendor = aff.get("vendor", vendor)
            if "product" in aff:
                products.append(aff["product"])
        if vendor or products:
            return vendor or "Unknown", " || ".join(products) or "Unknown"
    return "Unknown", "Unknown"


class GithubPocMonitor(BaseScraper):
    meta = ScraperMeta(
        id="github_poc_monitor",
        content_kind="vendor_research",
        source="GitHub CVE POC Monitor",
        schedule=spread("0 * * * *", "github_poc_monitor"),
        rate_limit="30/minute",  # limit GitHub Search API, BUKAN REST biasa (5000/jam)
        max_items=100,
        credential="github",
        reference_data=("techstack", "true_positive_cves"),
        tags=("migrated", "bespoke", "cve"),
        legacy_label="NEW CVE POC ON GITHUB",
        legacy_script="githubPOCMonitor",
    )

    def fetch(self, ctx: ScrapeContext) -> Iterator[CvePocItem | NoticeItem]:
        found = 0
        for item in self._broad_search(ctx):
            if isinstance(item, CvePocItem):  # `NoticeItem` pasangannya tidak ikut dihitung
                if found >= self.meta.max_items:
                    return
                found += 1
            yield item
        for item in self._targeted_search(ctx):
            if found >= self.meta.max_items:
                return
            found += 1
            yield item

    def _broad_search(self, ctx: ScrapeContext) -> Iterator[CvePocItem | NoticeItem]:
        tech_list: list[str] = ctx.reference["techstack"]
        if not tech_list:
            return
        tech_lower = [t.lower() for t in tech_list]

        year_list = [str(ctx.now.year), str((ctx.now - timedelta(days=360)).year)]
        for year in year_list:
            results = []
            for page in (1, 2):
                url = (
                    f"{_SEARCH_URL}?q=cve-{year}-*&sort=updated&order=desc&per_page=50&page={page}"
                )
                items = get_waiting(ctx, url).json().get("items", [])
                if not items:
                    break
                results.extend(items)

            for result in results:
                if result.get("fork"):
                    continue
                repo_url = result["html_url"]
                if repo_url in _WHITELIST_URLS:
                    continue

                repo_name = result["name"]
                repo_desc = result.get("description") or ""
                match = _CVE_ID_RE.search(repo_name.lower().replace("_", "-")) or _CVE_ID_RE.search(
                    repo_desc.lower().replace("_", "-")
                )
                if match is None:
                    continue
                cve_id = match.group(1)

                vendor, affected_prod = _mitre_vendor_product(ctx, cve_id)
                haystack = f"{vendor} {repo_desc} {affected_prod}".lower()
                if not any(re.search(rf"\b{re.escape(t)}\b", haystack) for t in tech_lower):
                    continue

                yield CvePocItem(
                    cve_id=cve_id,
                    url=repo_url,
                    source=result["owner"]["login"],
                    poc_type=_poc_type(repo_name, repo_desc),
                )
                notice = _poc_notice(
                    result, cve_id=cve_id, vendor=vendor, affected=affected_prod, now=ctx.now
                )
                if notice is not None:
                    yield notice

    def _targeted_search(self, ctx: ScrapeContext) -> Iterator[CvePocItem]:
        for entry in ctx.reference["true_positive_cves"]:
            cve_id: str = entry["cve_id"]
            existing_urls: set[str] = entry["poc_urls"]

            url = (
                f"{_SEARCH_URL}?q={cve_id}+in:name,description"
                "&sort=updated&order=desc&per_page=10&page=1"
            )
            items = get_waiting(ctx, url).json().get("items", [])

            for result in items:
                if result.get("fork"):
                    continue
                repo_url = result["html_url"]
                if repo_url in _WHITELIST_URLS or repo_url in existing_urls:
                    continue

                repo_name = result["name"]
                repo_desc = result.get("description") or ""
                name_lower = repo_name.lower().replace("_", "-")
                if cve_id.lower() not in name_lower and cve_id.lower() not in repo_desc.lower():
                    continue

                yield CvePocItem(
                    cve_id=cve_id,
                    url=repo_url,
                    source=result["owner"]["login"],
                    poc_type=_poc_type(repo_name, repo_desc),
                )
