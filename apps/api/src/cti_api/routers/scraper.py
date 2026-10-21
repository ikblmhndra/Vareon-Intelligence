"""Control plane scraper (Fase 9) -- BUKAN port dari legacy, `scraper.js`
lama cuma 2 widget monitoring read-only (survei Fase 8, gap #8: "Fase 9
GAK PUNYA preseden kode buat di-port -- desain dari nol"). Read (list/
detail/runs/items/health) kebuka buat semua user login, write (trigger/
dry-run/enable/disable/config/reset-dedup) admin-only -- semuanya efek
nyata (trigger beneran jalanin scraper produksi, dry-run mukul situs
eksternal asli, enable/disable+config ngubah perilaku produksi), beda
dari widget monitoring pasif yang legacy pernah punya.

`GET /api/scraper` enumerasi `cti_scraper.registry.discover()` (84
scraper) DIGABUNG `ScraperConfig` (override) + run terakhir per scraper
(`AsyncScraperRunRepo.latest_per_scraper()`, SATU query `DISTINCT ON`,
bukan N+1). `GET /health` numpang `cti_scraper.health.
summarize_fleet_health()` (fungsi murni, dipakai bareng task digest
periodik worker) -- endpoint YANG SAMA yang ditunggu placeholder
"Scraper Health" widget di `/dashboard` sejak Grup B (Fase 8).

`GET /health` DIDAFTARIN SEBELUM `GET /{scraper_id}` -- FastAPI cocokin
route berurutan, kalau kebalik "health" bakal ketangkep jadi
`scraper_id="health"` di route generik."""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING

from cti_core import beat_heartbeat
from cti_core.celery_client import get_celery_client
from cti_core.config import get_settings
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.scraper import (
    AsyncScraperConfigRepo,
    AsyncScraperItemRepo,
    AsyncScraperRunRepo,
)
from cti_core.db.repositories.scraper_seen import AsyncScraperSeenRepo
from cti_scraper.health import next_run, summarize_fleet_health
from cti_scraper.options import OptionError, resolve_options, validate_options
from cti_scraper.queues import queue_for
from cti_scraper.registry import discover
from cti_scraper.registry import get as get_scraper_cls
from cti_scraper.supersede import effective_enabled
from fastapi import APIRouter, Depends, HTTPException, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from cti_core.db.models.scraper import ScraperConfig, ScraperItem, ScraperRun
    from cti_scraper.base import ScraperMeta

from cti_api.deps import AuthedUser, get_db, get_redis, request_ip, require_admin, require_auth
from cti_api.schemas.scraper import (
    SchedulerStatusOut,
    ScraperConfigOut,
    ScraperConfigUpdateBody,
    ScraperDetail,
    ScraperDisableBody,
    ScraperDryRunResult,
    ScraperHealthEntryOut,
    ScraperHealthSummary,
    ScraperItemListResponse,
    ScraperItemOut,
    ScraperListItem,
    ScraperListResponse,
    ScraperOptionChoiceOut,
    ScraperOptionOut,
    ScraperResetDedupResult,
    ScraperRunListResponse,
    ScraperRunOut,
    ScraperTriggerResult,
)

router = APIRouter(prefix="/api/scraper", tags=["scraper"], dependencies=[Depends(require_auth)])


async def _scheduler_status(redis: Redis, now: datetime.datetime) -> SchedulerStatusOut:
    """Heartbeat beat (QA BUG-D2/D8). Redis gak bisa dibaca = `unknown`, BUKAN
    500 -- list scraper tetap harus kebuka walau Redis lagi gangguan."""
    stale_after_s = get_settings().worker.beat_heartbeat_stale_s
    try:
        raw = await redis.get(beat_heartbeat.HEARTBEAT_KEY)
    except Exception:
        raw = None
    status = beat_heartbeat.classify(
        beat_heartbeat.parse(raw), now=now, stale_after_s=stale_after_s
    )
    return SchedulerStatusOut(
        state=status.state,
        last_tick_at=status.last_tick.isoformat() if status.last_tick else None,
        started_at=status.started_at.isoformat() if status.started_at else None,
        age_s=round(status.age_s, 1) if status.age_s is not None else None,
        stale_after_s=status.stale_after_s,
    )


def _config_out(config: ScraperConfig | None, default_enabled: bool) -> ScraperConfigOut:
    if config is None:
        return ScraperConfigOut(
            enabled=default_enabled,
            schedule=None,
            rate_limit=None,
            max_items=None,
            paused_reason=None,
            options=None,
            updated_by=None,
            updated_at=None,
        )
    return ScraperConfigOut(
        enabled=config.enabled,
        schedule=config.schedule,
        rate_limit=config.rate_limit,
        max_items=config.max_items,
        paused_reason=config.paused_reason,
        options=config.options or None,
        updated_by=config.updated_by,
        updated_at=config.updated_at.isoformat() if config.updated_at else None,
    )


def _options_out(meta: ScraperMeta, config: ScraperConfig | None) -> list[ScraperOptionOut]:
    effective = resolve_options(meta, config.options if config is not None else None)
    return [
        ScraperOptionOut(
            key=o.key,
            label=o.label,
            description=o.description,
            default=o.default,
            choices=[ScraperOptionChoiceOut(value=c.value, label=c.label) for c in o.choices],
            value=effective[o.key],
        )
        for o in meta.options
    ]


def _run_out(run: ScraperRun) -> ScraperRunOut:
    return ScraperRunOut(
        run_id=run.run_id,
        scraper_id=run.scraper_id,
        trigger=run.trigger,
        status=run.status,
        started_at=run.started_at.isoformat(),
        finished_at=run.finished_at.isoformat() if run.finished_at else None,
        duration_ms=run.duration_ms,
        items_found=run.items_found,
        items_new=run.items_new,
        items_dropped=run.items_dropped,
        items_failed=run.items_failed,
        errors=run.errors,
        celery_task_id=run.celery_task_id,
    )


def _item_out(row: ScraperItem) -> ScraperItemOut:
    return ScraperItemOut(
        id=row.id,
        run_id=row.run_id,
        title=row.title,
        url=row.url,
        accepted=row.accepted,
        reason=row.reason,
        run_at=row.run_at.isoformat(),
    )


@router.get("", response_model=ScraperListResponse)
async def list_scrapers(
    session: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> ScraperListResponse:
    now = datetime.datetime.now(datetime.UTC)
    registry = discover()
    configs = await AsyncScraperConfigRepo(session).get_all()
    latest_runs = await AsyncScraperRunRepo(session).latest_per_scraper()

    items: list[ScraperListItem] = []
    for scraper_id, cls in sorted(registry.items()):
        meta = cls.meta
        config = configs.get(scraper_id)
        run = latest_runs.get(scraper_id)
        enabled = effective_enabled(meta, config)
        schedule = config.schedule if config is not None and config.schedule else meta.schedule
        nxt = next_run(schedule, now=now) if enabled else None
        items.append(
            ScraperListItem(
                id=meta.id,
                source=meta.source,
                runtime=meta.runtime,
                queue=queue_for(meta),
                tags=list(meta.tags),
                enabled=enabled,
                schedule=schedule,
                has_override=config is not None,
                last_run_id=run.run_id if run else None,
                last_status=run.status if run else None,
                last_trigger=run.trigger if run else None,
                last_started_at=run.started_at.isoformat() if run else None,
                last_finished_at=run.finished_at.isoformat() if run and run.finished_at else None,
                last_items_found=run.items_found if run else None,
                last_items_new=run.items_new if run else None,
                next_run_at=nxt.isoformat() if nxt else None,
            )
        )
    return ScraperListResponse(
        scrapers=items, total=len(items), scheduler=await _scheduler_status(redis, now)
    )


@router.get("/health", response_model=ScraperHealthSummary)
async def scraper_health(
    session: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> ScraperHealthSummary:
    registry = discover()
    configs = await AsyncScraperConfigRepo(session).get_all()
    run_repo = AsyncScraperRunRepo(session)
    recent_runs = await run_repo.list_recent_by_scraper_bulk(limit=3)
    last_success = await run_repo.last_success_by_scraper()
    now = datetime.datetime.now(datetime.UTC)
    entries = summarize_fleet_health(
        registry, configs, recent_runs, now=now, last_success=last_success
    )

    counts: dict[str, int] = {}
    problems: list[ScraperHealthEntryOut] = []
    for e in entries:
        counts[e.status] = counts.get(e.status, 0) + 1
        if e.status not in ("ok", "disabled"):
            problems.append(
                ScraperHealthEntryOut(
                    id=e.scraper_id,
                    source=e.source,
                    status=e.status,
                    last_status=e.last_status,
                    last_started_at=e.last_started_at.isoformat() if e.last_started_at else None,
                    reason=e.reason,
                    items_failed_last=e.items_failed_last,
                    consecutive_failing=e.consecutive_failing,
                    last_success_at=e.last_success_at.isoformat() if e.last_success_at else None,
                )
            )
    return ScraperHealthSummary(
        generated_at=now.isoformat(),
        counts=counts,
        scheduler=await _scheduler_status(redis, now),
        problems=problems,
    )


@router.get("/{scraper_id}", response_model=ScraperDetail)
async def get_scraper(scraper_id: str, session: AsyncSession = Depends(get_db)) -> ScraperDetail:
    try:
        cls = get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    meta = cls.meta
    config = await AsyncScraperConfigRepo(session).get(scraper_id)
    return ScraperDetail(
        id=meta.id,
        source=meta.source,
        runtime=meta.runtime,
        credential=meta.credential,
        reference_data=list(meta.reference_data),
        tags=list(meta.tags),
        notes=meta.notes,
        default_schedule=meta.schedule,
        default_rate_limit=meta.rate_limit,
        default_max_items=meta.max_items,
        default_enabled=meta.enabled,
        default_timeout_s=meta.timeout_s,
        default_max_retries=meta.max_retries,
        default_dedup_ttl_days=meta.dedup_ttl_days,
        queue=queue_for(meta),
        options=_options_out(meta, config),
        config=_config_out(config, meta.enabled),
    )


@router.get("/{scraper_id}/runs", response_model=ScraperRunListResponse)
async def list_runs(
    scraper_id: str,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_db),
) -> ScraperRunListResponse:
    try:
        get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    runs, total = await AsyncScraperRunRepo(session).list_by_scraper(
        scraper_id, page=page, page_size=page_size
    )
    return ScraperRunListResponse(
        runs=[_run_out(r) for r in runs], total=total, page=page, page_size=page_size
    )


@router.get("/{scraper_id}/items", response_model=ScraperItemListResponse)
async def list_items(
    scraper_id: str,
    page: int = 1,
    page_size: int = 20,
    accepted: bool | None = None,
    session: AsyncSession = Depends(get_db),
) -> ScraperItemListResponse:
    try:
        get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    rows, total = await AsyncScraperItemRepo(session).list_by_scraper(
        scraper_id, page=page, page_size=page_size, accepted=accepted
    )
    return ScraperItemListResponse(
        items=[_item_out(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.post("/{scraper_id}/trigger", response_model=ScraperTriggerResult)
async def trigger_scraper(
    scraper_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_admin),
) -> ScraperTriggerResult:
    try:
        cls = get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    queue = queue_for(cls.meta)
    async_result = get_celery_client().send_task(
        "scrape.run", args=(scraper_id,), kwargs={"trigger": "manual"}, queue=queue
    )
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="trigger_scraper",
        target_id=scraper_id,
        detail={"queue": queue, "celery_task_id": async_result.id},
        ip_address=request_ip(request),
    )
    await session.commit()
    return ScraperTriggerResult(
        scraper_id=scraper_id, celery_task_id=async_result.id, trigger="manual", queue=queue
    )


@router.post("/{scraper_id}/dry-run", response_model=ScraperDryRunResult)
async def dry_run_scraper(
    scraper_id: str,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_admin),
) -> ScraperDryRunResult:
    try:
        cls = get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None

    # Dry-run mencerminkan run terjadwal: pakai pilihan admin yang tersimpan (mis. sumber
    # Twitter), bukan default kode -- kalau tidak, "uji dulu sebelum ganti" menguji sumber
    # yang salah. `Runner(dry_run=True)` sendiri tidak membaca `scraper_config`.
    config = await AsyncScraperConfigRepo(session).get(scraper_id)
    options = resolve_options(cls.meta, config.options if config is not None else None)

    def _run() -> tuple[str, int, int, list[dict[str, str]]]:
        from cti_scraper.runner import Runner

        if cls.meta.reference_data:
            from cti_core.db.engine import sync_session

            with sync_session() as sync_sess:
                result = Runner(
                    cls, session=sync_sess, dry_run=True, options=options or None
                ).execute(trigger="manual")
        else:
            result = Runner(cls, dry_run=True, options=options or None).execute(trigger="manual")
        return result.status, result.items_found, result.duration_ms, result.errors

    # `Runner.execute()` SINKRON (HTTP/Playwright blocking) -- `to_thread`
    # biar gak nge-block event loop uvicorn selama scraper browser yang
    # lambat jalan (bisa puluhan detik).
    status, items_found, duration_ms, errors = await asyncio.to_thread(_run)
    return ScraperDryRunResult(
        scraper_id=scraper_id,
        status=status,
        items_found=items_found,
        duration_ms=duration_ms,
        errors=errors,
    )


@router.post("/{scraper_id}/enable", response_model=ScraperConfigOut)
async def enable_scraper(
    scraper_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_admin),
) -> ScraperConfigOut:
    try:
        cls = get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    config = await AsyncScraperConfigRepo(session).upsert(
        scraper_id, enabled=True, paused_reason=None, updated_by=admin["username"]
    )
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="enable_scraper",
        target_id=scraper_id,
        ip_address=request_ip(request),
    )
    await session.commit()
    return _config_out(config, cls.meta.enabled)


@router.post("/{scraper_id}/disable", response_model=ScraperConfigOut)
async def disable_scraper(
    scraper_id: str,
    body: ScraperDisableBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_admin),
) -> ScraperConfigOut:
    try:
        cls = get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    config = await AsyncScraperConfigRepo(session).upsert(
        scraper_id, enabled=False, paused_reason=body.reason, updated_by=admin["username"]
    )
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="disable_scraper",
        target_id=scraper_id,
        detail={"reason": body.reason},
        ip_address=request_ip(request),
    )
    await session.commit()
    return _config_out(config, cls.meta.enabled)


@router.put("/{scraper_id}/config", response_model=ScraperConfigOut)
async def update_scraper_config(
    scraper_id: str,
    body: ScraperConfigUpdateBody,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_admin),
) -> ScraperConfigOut:
    """PATCH-style: cuma field yang beneran dikirim client yang kesentuh
    (`model_dump(exclude_unset=True)`) -- `schedule` override baru kepake
    abis beat restart (lihat docstring `cti_worker.beat`), `rate_limit`/
    `max_items` kepake run BERIKUTNYA (`Runner.execute()` baca tiap run,
    H1)."""
    try:
        cls = get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    changes = body.model_dump(exclude_unset=True)
    if changes.get("options"):
        try:
            validate_options(cls.meta, changes["options"])
        except OptionError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    config = await AsyncScraperConfigRepo(session).upsert(
        scraper_id, updated_by=admin["username"], **changes
    )
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="update_scraper_config",
        target_id=scraper_id,
        detail=changes,
        ip_address=request_ip(request),
    )
    await session.commit()
    return _config_out(config, cls.meta.enabled)


@router.post("/{scraper_id}/reset-config", response_model=ScraperConfigOut)
async def reset_scraper_config(
    scraper_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_admin),
) -> ScraperConfigOut:
    """Hapus SEMUA override (`ScraperConfig` row-nya, bukan cuma
    enabled) -- balik ke `ScraperMeta` default kode sepenuhnya."""
    try:
        cls = get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    await AsyncScraperConfigRepo(session).reset(scraper_id)
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="reset_scraper_config",
        target_id=scraper_id,
        ip_address=request_ip(request),
    )
    await session.commit()
    return _config_out(None, cls.meta.enabled)


@router.post("/{scraper_id}/reset-dedup", response_model=ScraperResetDedupResult)
async def reset_scraper_dedup(
    scraper_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
    admin: AuthedUser = Depends(require_admin),
) -> ScraperResetDedupResult:
    """Control plane "lupain semuanya" -- dipanggil analis abis benerin
    parser yang sempat ngeluarin sampah, biar run berikutnya nge-treat
    ulang semua item sebagai baru (bukan ke-dedup ke sampah lama)."""
    try:
        get_scraper_cls(scraper_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="scraper not found") from None
    deleted = await AsyncScraperSeenRepo(session).reset_scraper(scraper_id)
    await AsyncAuditLogRepo(session).write(
        username=admin["username"],
        action="reset_scraper_dedup",
        target_id=scraper_id,
        detail={"deleted": deleted},
        ip_address=request_ip(request),
    )
    await session.commit()
    return ScraperResetDedupResult(scraper_id=scraper_id, deleted=deleted)
