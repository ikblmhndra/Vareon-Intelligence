"""ANY.RUN Malware Trends -- BESPOKE, subclass `BaseScraper` langsung.
Nge-`yield` `MalwareTrendItem`, satu per posisi ranking di leaderboard
"Top 10 Malware Trends" ANY.RUN.

`ScraperNews/anyrunTrendThreat.py` asli **gak pernah nulis apa pun** --
`featured_message` dihitung terus dibuang, gak ada `push_job()` ATAU
`is_new_and_mark()` sama sekali (dikonfirmasi: fixture Fase 0-nya
`expected_items.json` isinya `[]` di semua hari rekam). Lihat
KNOWN_BROKEN.md. Keputusan user (Fase 4): lanjutin jadi fitur beneran,
bukan sekadar migrasi -- makanya ada tabel (`malware_trends`), Item
(`MalwareTrendItem`), sink, dan repo BARU yang gak ada padanannya di
skema lama.

XPath disalin apa adanya dari script lama, TERMASUK offset ganjil
`recent_count` mulai dari 3 (bukan 1) -- li[1]/li[2] di halaman itu
BUKAN kartu trend (kemungkinan header/promo section), kartu trend
beneran mulai li[3]. `recent_count = i + 2` sepanjang loop `range(1,11)`,
disalin sebagai `{i}` yang dievaluasi `i + 2` di `_card()`.

**Beda dari script lama**: `href`-nya RELATIF (`/malware-trends/kali365/`),
script lama gak pernah gabungin base_url -- gak masalah dulu karena
`featured_message`-nya emang gak pernah dipakai/ditampilin (lihat di atas).
Sekarang beneran jadi field URL yang bakal dipakai web/orang buat klik,
jadi digabung ke absolut di sini (`urljoin`), bukan diwarisin relatif.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import urljoin

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.items import Item, MalwareTrendItem
from cti_scraper.schedule import spread

_SOURCE = "any.run"
_URL = "https://any.run/malware-trends/"
_BASE_URL = "https://any.run"


def _card(i: int) -> str:
    li = i + 2  # script lama: recent_count mulai 3, sinkron sama i mulai 1
    return f"/html/body/section/div/div[2]/div/div/ul/li[{li}]/a"


class AnyRunTrends(BaseScraper):
    meta = ScraperMeta(
        id="any_run_trends",
        content_kind="vendor_research",
        source="ANY.RUN Malware Trends",
        schedule=spread("0 0 * * 1", "any_run_trends"),  # mingguan, cocok "past 7 days"
        runtime="browser",
        rate_limit="6/minute",
        max_items=10,
        tags=("migrated", "bespoke"),
        legacy_label=None,  # script lama gak pernah push_job, gak ada label buat dipertahankan
        legacy_script="anyrunTrendThreat",
    )

    def dedup_key(self, item: Item) -> str | None:
        """Selalu upsert ulang -- posisi ranking bisa geser dalam hari yang
        sama antar-run, unique constraint `(source, snapshot_date, rank)`
        di tabel yang jaga "satu baris per posisi per hari"."""
        return None

    def fetch(self, ctx: ScrapeContext) -> Iterator[MalwareTrendItem]:
        snapshot_date = ctx.now.date()
        with ctx.page() as page:
            page.goto(_URL, wait_until="domcontentloaded")

            for i in range(1, self.meta.max_items + 1):
                card = _card(i)
                name = page.locator(f"xpath={card}/div[2]/h2").text_content()
                href = page.locator(f"xpath={card}").get_attribute("href")
                malware_type = page.locator(f"xpath={card}/div[3]").text_content()
                report_count = page.locator(f"xpath={card}/div[6]").text_content()

                if not name or not href:
                    continue

                yield MalwareTrendItem(
                    source=_SOURCE,
                    snapshot_date=snapshot_date,
                    rank=i,
                    malware_name=name.strip(),
                    malware_type=(malware_type or "").strip() or None,
                    url=urljoin(_BASE_URL, href.strip()),
                    report_count=(report_count or "").strip() or None,
                )
