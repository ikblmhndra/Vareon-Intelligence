"""Info "diupdate per kapan" dan tombol cek manual untuk tab CVEs.

Dua jalur bisa mengisi `cve_tracker` (ROADMAP #19, `docs/CVE_CATALOG_CUTOVER.md`):
- **scraper `new_cve`** (default; tiap jam, queue `scrape.api`): waktu cek = `scraper_runs`;
- **mirror CVE List V5** (`cve.mirror_sync`, tiap 5 menit): aktif bila promosi mirror `live`, dan
  `new_cve` ditangguhkan (kecuali `KEEP_LEGACY_NEW_CVE`, saat keduanya jalan berdampingan). Waktu
  cek = `polled_at` di `job_state` (`cve_mirror.state`).

Tombol cek manual mengirim tugas yang SAMA dengan jadwal ke jalur yang aktif (API hanya mengirim
tugas lewat nama, tanpa import worker; pola `services/monitor.py` dan `POST /api/scraper/{id}/
trigger`). Ini BUKAN "Populate now" (ROADMAP #3, backfill riwayat): hanya menjalankan cek rutin
sekarang juga. Pengamannya: tidak dobel saat run masih berjalan, dan cooldown singkat (kuota NVD
dan MITRE terbatas).

Cek `new_cve` memproses SEMUA client sekaligus (satu run global), sedangkan angka "CVE baru"
dihitung per client aktif di lingkup yang sama dengan tab CVEs."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from cti_core.celery_client import get_celery_client
from cti_core.config import get_settings
from cti_core.cve_mirror_sync import STATE_KEY, SyncState
from cti_core.db.models.report_state import JobState
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.scraper import AsyncScraperConfigRepo, AsyncScraperRunRepo
from cti_scraper.health import next_run
from cti_scraper.queues import queue_for
from cti_scraper.registry import discover
from cti_scraper.supersede import effective_enabled
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.schemas.cve_check import (
    CheckSourceId,
    CveCheckSource,
    CveCheckTriggered,
    CveFreshness,
)

SCRAPER_ID = "new_cve"
MIRROR_LABEL = "CVE List V5 mirror"
MIRROR_TASK = "cve.mirror_sync"
MIRROR_QUEUE = "maintenance"
"""= `cti_worker.queues.QUEUE_MAINTENANCE` (API tidak boleh import worker)."""
MIRROR_CRON = "*/5 * * * *"
"""= entri beat `cve-mirror-sync` (`cti_worker.beat`)."""

SUCCESS_STATUSES = ("ok", "empty", "partial")
"""Status run yang berarti sumber BENAR-BENAR dicek (bukan gagal fetch, rate limit, dst)."""
RUNNING_STALE_AFTER = datetime.timedelta(minutes=30)
"""Baris `running` lebih tua dari ini dianggap nyangkut (worker mati), bukan sedang berjalan."""
COOLDOWN_S = 120
_COOLDOWN_KEY = "cve:check_new:cooldown"


class CheckError(Exception):
    """Dasar semua alasan pengecekan manual ditolak."""


class CheckAlreadyRunning(CheckError):
    pass


class CheckUnavailable(CheckError):
    pass


class CheckCooldown(CheckError):
    def __init__(self, seconds: int) -> None:
        super().__init__(f"cooldown {seconds}s")
        self.seconds = seconds


class CheckBrokerError(CheckError):
    pass


@dataclass(frozen=True)
class ActiveSources:
    mirror: bool
    scraper: bool


def active_sources() -> ActiveSources:
    """Jalur yang mengisi `cve_tracker` sekarang. Aturan `new_cve` ditangguhkan SAMA dengan
    `cti_scraper.supersede.superseded_by_mirror` (ada test yang mengunci kesamaannya)."""
    cfg = get_settings().cve_mirror
    mirror = cfg.enabled and cfg.promote == "live"
    return ActiveSources(mirror=mirror, scraper=not (mirror and not cfg.keep_legacy_new_cve))


def _latest(values: Sequence[datetime.datetime | None]) -> datetime.datetime | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


async def _scraper_source(session: AsyncSession, now: datetime.datetime) -> CveCheckSource:
    meta = discover()[SCRAPER_ID].meta
    config = await AsyncScraperConfigRepo(session).get(SCRAPER_ID)
    enabled = effective_enabled(meta, config)
    runs = AsyncScraperRunRepo(session)
    succeeded = await runs.latest_finished(SCRAPER_ID, statuses=SUCCESS_STATUSES)
    latest = await runs.latest_finished(SCRAPER_ID)
    schedule = config.schedule if config is not None and config.schedule else meta.schedule
    return CveCheckSource(
        id="new_cve",
        label=meta.source,
        enabled=enabled,
        last_checked_at=succeeded.finished_at if succeeded else None,
        last_run_finished_at=latest.finished_at if latest else None,
        last_run_status=latest.status if latest else None,
        running=await runs.has_running(SCRAPER_ID, started_after=now - RUNNING_STALE_AFTER),
        next_check_at=next_run(schedule, now=now) if enabled else None,
    )


async def _mirror_source(session: AsyncSession, now: datetime.datetime) -> CveCheckSource:
    row = await session.get(JobState, STATE_KEY)
    polled = SyncState.load(row.value if row is not None else None).polled_at
    return CveCheckSource(
        id="mirror",
        label=MIRROR_LABEL,
        enabled=True,
        last_checked_at=polled,
        last_run_finished_at=polled,
        last_run_status=None,
        running=False,  # kunci sync ada di advisory lock DB; cukup tunggu `polled_at` maju
        next_check_at=next_run(MIRROR_CRON, now=now),
    )


async def get_freshness(
    session: AsyncSession,
    *,
    client_id: str,
    tech: Sequence[str] | None,
    exclude_cve_ids: Sequence[str] | None,
    new_since: datetime.datetime | None = None,
    now: datetime.datetime | None = None,
) -> CveFreshness:
    """`tech` dan `exclude_cve_ids` = lingkup tab CVEs (`routers/cve.py::_active_tech_names` dan
    daftar FP client), supaya "CVE terbaru" dan "N CVE baru" cocok dengan yang dilihat analis."""
    now = now or datetime.datetime.now(datetime.UTC)
    active = active_sources()
    sources: list[CveCheckSource] = []
    if active.mirror:
        sources.append(await _mirror_source(session, now))
    if active.scraper:
        sources.append(await _scraper_source(session, now))

    repo = AsyncCveTrackerRepo(session)
    scope: dict[str, Any] = {
        "client_id": client_id,
        "tech": tech,
        "exclude_cve_ids": exclude_cve_ids,
    }
    if new_since is not None and new_since.tzinfo is None:
        new_since = new_since.replace(tzinfo=datetime.UTC)
    return CveFreshness(
        sources=sources,
        last_checked_at=_latest([s.last_checked_at for s in sources]),
        last_run_finished_at=_latest([s.last_run_finished_at for s in sources]),
        running=any(s.running for s in sources),
        newest_detected_at=await repo.newest_detected_on(**scope),
        new_since=None
        if new_since is None
        else await repo.count_detected_since(new_since, **scope),
    )


async def trigger_check(session: AsyncSession, redis: Redis) -> CveCheckTriggered:
    """Kirim tugas cek ke semua jalur yang aktif dan siap. `CheckError` (subclass) bila ditolak.

    Penolakan karena run masih berjalan atau scraper dimatikan TIDAK memakai cooldown: begitu
    keadaan berubah tombol langsung bisa dipakai. Cooldown juga dilepas bila pengiriman gagal."""
    now = datetime.datetime.now(datetime.UTC)
    active = active_sources()
    tasks: list[tuple[CheckSourceId, str, tuple[str, ...], dict[str, str], str]] = []
    running = False
    if active.mirror:
        tasks.append(("mirror", MIRROR_TASK, (), {}, MIRROR_QUEUE))
    if active.scraper:
        meta = discover()[SCRAPER_ID].meta
        config = await AsyncScraperConfigRepo(session).get(SCRAPER_ID)
        if effective_enabled(meta, config):
            if await AsyncScraperRunRepo(session).has_running(
                SCRAPER_ID, started_after=now - RUNNING_STALE_AFTER
            ):
                running = True
            else:
                tasks.append(
                    ("new_cve", "scrape.run", (SCRAPER_ID,), {"trigger": "manual"}, queue_for(meta))
                )
    if not tasks:
        if running:
            raise CheckAlreadyRunning()
        raise CheckUnavailable(f"Scraper '{SCRAPER_ID}' is turned off in the control plane")

    if not await redis.set(_COOLDOWN_KEY, "1", ex=COOLDOWN_S, nx=True):
        remaining = await redis.ttl(_COOLDOWN_KEY)  # -1/-2: kunci tanpa umur / baru saja habis
        raise CheckCooldown(remaining if remaining > 0 else COOLDOWN_S)
    try:
        client = get_celery_client()
        for _source, name, args, kwargs, queue in tasks:
            client.send_task(name, args=args, kwargs=kwargs, queue=queue)
    except Exception as exc:
        await redis.delete(_COOLDOWN_KEY)
        raise CheckBrokerError(str(exc)) from exc
    return CveCheckTriggered(
        status="queued", triggered_at=now, sources=[source for source, *_ in tasks]
    )
