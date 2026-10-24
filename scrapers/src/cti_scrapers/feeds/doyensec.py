"""Doyensec -- hasil migrasi otomatis dari `ScraperNews/doyensecThreat.py`
(codemod Fase 4, family RSS). Cek `migration_report.json` buat detail
ekstraksi. WAJIB lewat `dry-run` + `verify` sebelum `enable` -- lihat
docs/ADDING_A_SCRAPER.md.

Bug migrasi ketemu census 2026-09-30: `feeds` itu Atom (`<feed xmlns="...">`,
`<entry>`, `<link href="..."/>`), TAPI codemod nge-generate scraper ini pakai
default `RSSScraper` yang RSS-shaped (`item_path=".//item"`, `link` `.text`) --
gak pernah ada override Atom sejak awal. Diverifikasi live: `blog.doyensec.com/
atom.xml` beneran Atom, bukan situs yang baru pindah format."""

from __future__ import annotations

from cti_scraper.base import ScraperMeta
from cti_scraper.families.rss import RSSScraper
from cti_scraper.schedule import spread

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class Doyensec(RSSScraper):
    meta = ScraperMeta(
        id="doyensec",
        content_kind="vendor_research",
        source="Doyensec",
        schedule=spread("46 * * * *", "doyensec"),
        tags=("migrated",),
        legacy_label="NEW ARTICLE FROM DOYENSEC",
        legacy_script="doyensecThreat",
    )
    feeds = ("https://blog.doyensec.com/atom.xml",)
    item_path = f".//{_ATOM_NS}entry"
    title_path = f"{_ATOM_NS}title"
    link_path = f"{_ATOM_NS}link"
    link_attr = "href"
