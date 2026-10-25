"""CISA KEV -- referensi scraper bespoke KEDUA: `BaseScraper` langsung,
nge-`yield` `ArticleItem` biasa (bukan tipe custom kayak
`ransomware_live.py`) tapi logikanya gak muat di `ApiScraper.field_map`
(butuh filter tanggal + gabung banyak URL jadi satu string).

Bandingkan sama `ScraperNews/cisacatalogThreat.py` asli. DUA bug lama
DIPERTAHANKAN SENGAJA biar cocok golden test lawan fixture Fase 0 --
diperbaiki pas migrasi beneran (Fase 4), bukan di sini:

  1. `cve_link[:-3]` niatnya motong " || " (4 karakter) tapi cuma motong 3
     -- nyisain SATU SPASI di akhir URL. Kebukti persis di fixture:
     `'...CVE-2026-58704 '` (spasi trailing).
  2. Label push_job lama ("NEW CISA CATALOG VULNERABILITY", tanpa kata
     "FROM") bikin `nlp.py` lama IndexError -- dicatat di KNOWN_BROKEN.md,
     TIDAK relevan lagi di sini karena framework baru gak parsing label
     buat ekstrak nama sumber.

`related_tech_stack` (cocokin `vendorProject` ke tech stack organisasi)
SENGAJA DIBUANG -- itu concern-nya `cti_enrich` (Fase 5) yang punya akses
ke tabel `techstack_entries`, bukan scraper. Scraper cuma nge-yield artikel
mentah; enrichment yang nentuin relevansinya.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import timedelta

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.items import ArticleItem

_URL_RE = re.compile(r"https:\/\/[a-zA-Z0-9\-._~:\/?#\[\]@!$&'()*+,;=%]+")


class CisaKev(BaseScraper):
    meta = ScraperMeta(
        id="cisa_kev",
        content_kind="kev",
        default_relevance="always",
        source="CISA KEV",
        schedule="*/30 * * * *",
        max_items=1000,  # snapshot katalog penuh, difilter tanggal di dalam fetch()
        tags=("cve", "collector"),
        legacy_label="NEW CISA CATALOG VULNERABILITY",
        legacy_script="cisacatalogThreat",
    )

    def fetch(self, ctx: ScrapeContext) -> Iterator[ArticleItem]:
        resp = ctx.http.get(
            "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
        )
        try:
            payload = resp.json()
        except ValueError as e:
            raise ParseError(f"respons bukan JSON valid: {e}") from e

        vulns = payload.get("vulnerabilities")
        if not isinstance(vulns, list):
            raise ParseError("respons gak punya key 'vulnerabilities' berbentuk list")

        today = ctx.now.date().isoformat()
        yesterday = (ctx.now.date() - timedelta(days=1)).isoformat()

        found = 0
        for vuln in vulns:
            if found >= self.meta.max_items:
                return
            if vuln.get("dateAdded") not in (today, yesterday):
                continue

            cve_id = vuln.get("cveID")
            if not cve_id:
                continue

            links = _URL_RE.findall(str(vuln.get("notes", "")))
            joined = "".join(f"{link} || " for link in links)[:-3]  # bug lama, lihat docstring
            if not joined:
                continue

            found += 1
            yield ArticleItem(title=cve_id, url=joined, posted_on=ctx.now.date())
