"""Klasifikasi kesehatan scraper (Fase 9, plan §8) -- FUNGSI MURNI, gak ada
I/O di sini sama sekali. Ditaruh di `cti_scraper` (bukan
`apps/api/services`) biar `apps/api` (`GET /api/scraper/health`) DAN
`apps/worker` (task digest periodik) bisa numpang logic yang SAMA tanpa
depends ke satu sama lain -- pelajaran yang sama kayak `queue_for()`
pindah dari `cti_worker` ke sini (H2): apps depends ke packages, bukan
ke apps lain.

5 status (`Exit criteria` Fase 9 nyebut 4 -- `disabled` ditambahin karena
tanpa itu scraper yang SENGAJA dimatiin operator bakal salah keklasifikasi
`dead` seiring waktu, padahal dia emang gak dijadwalin fetch sama sekali
selagi `enabled=False`, beat skip dia total dari schedule -- lihat
`cti_worker.beat._scraper_configs()`):

  disabled   -- `ScraperConfig.enabled=False`, atau (kalau scraper itu gak punya baris config)
                `ScraperMeta.enabled=False` di kode -- aturan yang sama dgn beat. Bukan masalah,
                operator/waiver yang minta.
  stale      -- gak pernah ada `ScraperRun` sama sekali buat scraper ini.
  dead       -- run terakhir `started_at` lebih dari 3x interval jadwal
                yang diharapkan -- "scraper yang dimatiin (infra-nya,
                bukan config) kedeteksi dead dalam 3 interval."
  degraded   -- run terakhir status GAGAL (`fetch_error`/`parse_error`/
                `rate_limited`/`timeout`/`backpressure`) -- kedeteksi
                SATU run ("selector yang dirusak kedeteksi parse_error
                dalam 1 interval"), gak nunggu 3x kayak `dead`.
  zero_yield -- 3 run TERAKHIR berturut-turut semuanya `status="empty"`
                (jalan sukses, nol item tiap kali -- bisa selector rusak
                ATAU sumbernya emang lagi sepi, keduanya worth di-flag).
  ok         -- gak masuk kategori manapun di atas.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from croniter import croniter

from cti_scraper.supersede import effective_enabled

if TYPE_CHECKING:
    from cti_core.db.models.scraper import ScraperConfig, ScraperRun

    from cti_scraper.base import BaseScraper, ScraperMeta

HealthStatus = Literal["ok", "disabled", "stale", "dead", "degraded", "zero_yield"]

_BAD_STATUSES = frozenset({"fetch_error", "parse_error", "rate_limited", "timeout", "backpressure"})
_ZERO_YIELD_STREAK = 3
_DEAD_INTERVAL_MULTIPLIER = 3
_MIN_INTERVAL = datetime.timedelta(minutes=1)
"""Jaring pengaman kalau cron malformed/aneh ngasilin interval ~0 --
jangan sampai `dead` ke-trigger langsung abis satu run."""


def expected_interval(cron: str, *, now: datetime.datetime | None = None) -> datetime.timedelta:
    """Gap antara DUA fire time terjadwal terakhir sebelum `now` -- pakai
    `croniter` (udah jadi dependency `cti-scraper` sejak awal, tapi gak
    pernah kepake di mana pun sebelum ini) biar bener buat cron kompleks
    (`5-59/15 * * * *` hasil `spread()`, bukan cuma `*/N` polos)."""
    now = now or datetime.datetime.now(datetime.UTC)
    it = croniter(cron, now)
    prev1: datetime.datetime = it.get_prev(datetime.datetime)
    prev2: datetime.datetime = it.get_prev(datetime.datetime)
    gap: datetime.timedelta = prev1 - prev2
    return max(gap, _MIN_INTERVAL)


def next_run(cron: str, *, now: datetime.datetime | None = None) -> datetime.datetime | None:
    """Slot jadwal berikutnya SESUDAH `now` (UTC) -- kolom "Next Run" di `/scrapers`
    (QA BUG-D8). `None` kalau cron gak bisa di-parse (jangan bikin satu cron aneh
    nge-500-in seluruh list). Ini jadwal yang SEHARUSNYA; beneran nembak atau
    nggak tergantung beat hidup -- makanya UI menampilkannya bareng status
    heartbeat (`cti_core.beat_heartbeat`)."""
    now = now or datetime.datetime.now(datetime.UTC)
    try:
        nxt: datetime.datetime = croniter(cron, now).get_next(datetime.datetime)
    except (ValueError, KeyError):
        return None
    return nxt


def compute_health(
    meta: ScraperMeta,
    config: ScraperConfig | None,
    recent_runs: list[ScraperRun],
    *,
    now: datetime.datetime | None = None,
) -> HealthStatus:
    """`recent_runs` HARUS urut `started_at` DESC (run terbaru duluan) --
    caller yang jamin (`AsyncScraperRunRepo.list_recent_by_scraper()`/
    versi sync-nya)."""
    # Aturan SAMA dengan `cti_worker.beat` (`config.enabled if config is not None else
    # meta.enabled`): scraper yang dimatikan di KODE (`meta.enabled=False`, mis. waiver census
    # 2026-10-01) gak pernah dijadwalkan beat, jadi tanpa ini dia nongol `degraded` lalu `dead`
    # selamanya di sweep + digest Telegram padahal gak ada yang salah.
    if not effective_enabled(meta, config):  # + digantikan mirror CVE (`supersede`)
        return "disabled"

    if not recent_runs:
        return "stale"

    now = now or datetime.datetime.now(datetime.UTC)
    latest = recent_runs[0]

    cron = config.schedule if config is not None and config.schedule else meta.schedule
    interval = expected_interval(cron, now=now)
    if now - latest.started_at > interval * _DEAD_INTERVAL_MULTIPLIER:
        return "dead"

    if latest.status in _BAD_STATUSES:
        return "degraded"

    streak = recent_runs[:_ZERO_YIELD_STREAK]
    if len(streak) == _ZERO_YIELD_STREAK and all(r.status == "empty" for r in streak):
        return "zero_yield"

    return "ok"


@dataclass
class ScraperHealthEntry:
    scraper_id: str
    source: str
    status: HealthStatus
    last_status: str | None
    last_started_at: datetime.datetime | None


def summarize_fleet_health(
    registry: dict[str, type[BaseScraper]],
    configs: dict[str, ScraperConfig],
    recent_runs: dict[str, list[ScraperRun]],
    *,
    now: datetime.datetime | None = None,
) -> list[ScraperHealthEntry]:
    """Orkestrasi `compute_health()` lintas SEMUA scraper terdaftar --
    caller nyuapin data yang UDAH di-fetch (`registry.discover()`,
    `ScraperConfigRepo.get_all()`, `ScraperRunRepo.
    list_recent_by_scraper_bulk()`), fungsi ini gak nyentuh DB. Dipakai
    `GET /api/scraper/health` (async) DAN task digest periodik (sync,
    worker) -- kedua caller beda gaya fetch, orkestrasi-nya sama."""
    now = now or datetime.datetime.now(datetime.UTC)
    out: list[ScraperHealthEntry] = []
    for scraper_id, cls in sorted(registry.items()):
        meta = cls.meta
        config = configs.get(scraper_id)
        runs = recent_runs.get(scraper_id, [])
        out.append(
            ScraperHealthEntry(
                scraper_id=scraper_id,
                source=meta.source,
                status=compute_health(meta, config, runs, now=now),
                last_status=runs[0].status if runs else None,
                last_started_at=runs[0].started_at if runs else None,
            )
        )
    return out
