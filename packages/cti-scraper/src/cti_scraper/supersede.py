"""Scraper yang DIGANTIKAN pipeline mirror CVE (ROADMAP #19, irisan 7: cutover).

Begitu promosi mirror `live` (`CVE_MIRROR__PROMOTE=live` dan `CVE_MIRROR__ENABLED=true`), tracker
diisi `cve.mirror_sync` + `cti_core.cve_promotion`. `new_cve` yang jalan bersamaan meng-upsert baris
yang SAMA (tech bisa bergantian antara pilihan mirror dan pilihan abjad `new_cve`), jadi ia
ditangguhkan:

- tidak dijadwalkan beat (`cti_worker.beat`), dan `Runner` menolak menjalankannya (status
  `disabled`, jaring pengaman bila dipicu manual atau jadwal lama masih di memori beat);
- dihitung `disabled` oleh health (bukan `stale`/`dead` selamanya di digest Telegram);
- tampil nonaktif di daftar scraper.

**Rollback = ubah flag, tanpa migrasi**: `CVE_MIRROR__PROMOTE=off` (atau `shadow`) lalu restart
worker/beat, `new_cve` jalan lagi. `CVE_MIRROR__KEEP_LEGACY_NEW_CVE=true` membiarkannya tetap jalan
berdampingan (masa tumpang tindih / cadangan; tidak ada data hilang, hanya `tech` yang bisa
bergantian).

Env dibaca sekali per proses, jadi cutover/rollback berlaku setelah worker, beat, dan api
direstart. Control plane (`ScraperConfig.enabled`) tetap menang: scraper yang dimatikan di sana
tetap mati.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cti_core.config import get_settings

if TYPE_CHECKING:
    from cti_core.db.models.scraper import ScraperConfig

    from cti_scraper.base import ScraperMeta

SUPERSEDED_BY_MIRROR = frozenset({"new_cve"})


def superseded_by_mirror(scraper_id: str) -> bool:
    """`scraper_id` ditangguhkan karena pipeline mirror CVE sudah `live`."""
    if scraper_id not in SUPERSEDED_BY_MIRROR:
        return False
    cfg = get_settings().cve_mirror
    return cfg.enabled and cfg.promote == "live" and not cfg.keep_legacy_new_cve


def effective_enabled(meta: ScraperMeta, config: ScraperConfig | None) -> bool:
    """Aturan tunggal "scraper ini jalan?" untuk beat, health, daftar API: control plane (atau
    `ScraperMeta.enabled` bila tak ada baris config) DAN tidak sedang digantikan mirror."""
    enabled = config.enabled if config is not None else meta.enabled
    return enabled and not superseded_by_mirror(meta.id)
