"""ransomware.live -- referensi scraper BESPOKE: subclass `BaseScraper`
LANGSUNG (bukan family manapun), nge-`yield` `RansomwareVictimItem` alih-
alih `ArticleItem`. Sink registry (sinks.py) yang route ke
`ransomware_victims`, MELEWATI pipeline enrichment artikel -- gak ada
`if scraper.is_special` di framework buat ngizinin ini.

Bandingkan sama `ScraperNews/ransomwareLiveThreat.py` asli: preload seluruh
keyset ke RAM (`get_existing_ransomware_keys()`), fetch bulan berjalan
doang, resolusi nama negara via `pycountry`. Framework baru ngilangin
preload-keyset (dedup lewat `ScraperSeen`, lihat dedup.py) dan resolusi
nama negara (`country` penuh itu data turunan dari `country_code`, gak
disimpan ganda -- lihat catatan skema Fase 2).

Bug BELUM diperbaiki di sini secara sengaja (biar cocok golden test lawan
fixture Fase 0): scraper cuma nge-fetch bulan BERJALAN, jadi korban yang
kepublikasi di akhir bulan bisa kelewat kalau scraper baru jalan lagi awal
bulan depan. Diperbaiki pas migrasi beneran (Fase 4), bukan di sini.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterator

from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.errors import ParseError
from cti_scraper.items import RansomwareVictimItem


def _iso_date(value: object) -> datetime.date | None:
    """API balikin separator campur ("...T...:00" atau "... ...:00.ffffff",
    lihat fixture Fase 0) -- ambil bagian tanggal doang, buang jam/zona.
    Value kosong/None -> None."""
    text = str(value or "").split("T")[0].split(" ")[0]
    return datetime.date.fromisoformat(text) if text else None


class RansomwareLive(BaseScraper):
    meta = ScraperMeta(
        id="ransomware_live",
        content_kind="news",
        source="ransomware.live",
        schedule="17 * * * *",
        rate_limit="4/minute",
        max_items=500,  # snapshot bulanan, bukan feed artikel -- bukan 50 biasa
        dedup_ttl_days=400,  # korban dirujuk lintas batas tahun
        tags=("ransomware", "collector"),
        legacy_label="NEW RANSOMWARE VICTIM",
        legacy_script="ransomwareLiveThreat",
    )

    def fetch(self, ctx: ScrapeContext) -> Iterator[RansomwareVictimItem]:
        year, month = ctx.now.year, ctx.now.month
        resp = ctx.http.get(f"https://api.ransomware.live/v2/victims/{year}/{month}")

        if resp.status_code == 404:
            ctx.log.info("no_victims_this_month", year=year, month=month)
            return

        try:
            payload = resp.json()
        except ValueError as e:
            raise ParseError(f"respons bukan JSON valid: {e}") from e
        if not isinstance(payload, list):
            raise ParseError(f"diharap list, dapet {type(payload).__name__}")

        for row in payload[: self.meta.max_items]:
            group_name = str(row.get("group", ""))
            victim = str(row.get("victim", ""))
            if not group_name or not victim:
                continue
            yield RansomwareVictimItem(
                group_name=group_name,
                victim=victim,
                country_code=str(row.get("country", "")).upper(),
                industry=str(row.get("activity", "")),
                published=_iso_date(row.get("attackdate")),
                discovered=_iso_date(row.get("discovered")),
                domain=str(row.get("domain", "")),
                description=str(row.get("description", "")),
                post_url=row.get("claim_url") or "Unknown",
                ransom=row.get("ransom"),
                data_size=row.get("data_size"),
                screenshot=str(row.get("screenshot", "")),
            )
