"""Port `ScraperNewsWeb/app/routers/recap.py`. SELURUH router ini
`require_auth`, port apa adanya (sama kayak kode lama -- gak ada
endpoint publik di sini).

**Dua jenis recap (#21, PR 2).** `kind=weekly`: recap terjadwal satu pekan Senin-Minggu (UTC),
`date` = Senin-nya. `kind=daily`: recap satu hari yang dipicu tangan, default semua endpoint di
sini supaya pemanggil lama tidak berubah. `/latest` mengembalikan recap MINGGUAN terbaru (halaman
Recap membukanya), `/list` memuat kedua jenis dengan `kind` dan rentangnya.

**Kualitas recap mingguan (#21, PR 3).** Dokumen recap membawa `quality` (perbandingan pekan,
laporan grounding, scorecard forecast). Hit rate scorecard 8 pekan dihitung SAAT DIBACA (override
analis mengubah pekan yang sudah lewat) dan ikut di balasan `/latest`, `/{date}?kind=weekly`, dan
override sebagai `hit_rate` di samping `recap`; recap harian tidak punya scorecard, jadi tidak
membawanya."""

from __future__ import annotations

import datetime
from typing import Literal

from cti_core.db.repositories.auth import AsyncAuditLogRepo
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import AuthedUser, get_db, request_ip, require_auth
from cti_api.schemas.recap import ScorecardOverrideIn
from cti_api.services import recap as recap_service

router = APIRouter(prefix="/api/recap", tags=["recap"])

Kind = Literal["daily", "weekly"]


def _parse_date(value: str, name: str = "date") -> datetime.date:
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{name} must be YYYY-MM-DD") from e


@router.get("/list")
async def recap_list(
    limit: int = Query(30, ge=1, le=180),
    user: AuthedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    return {"recaps": await recap_service.list_recaps(session, limit=limit)}


@router.get("/latest")
async def recap_latest(
    user: AuthedUser = Depends(require_auth), session: AsyncSession = Depends(get_db)
) -> dict[str, object]:
    """Recap MINGGUAN terbaru yang tersimpan. Belum ada satu pun: `recap` null dan `date` = Senin
    pekan yang akan dibuat berikutnya (pekan terakhir yang sudah selesai)."""
    doc = await recap_service.get_latest_recap(session, "weekly")
    date = doc["date"] if doc else recap_service.default_week_start().isoformat()
    hit_rate = await recap_service.get_hit_rate(session)
    return {"recap": doc, "date": date, "kind": "weekly", "hit_rate": hit_rate}


@router.get("/{date}")
async def recap_get(
    date: str,
    kind: Kind = Query("daily", description="daily (default) or weekly (date = its Monday)"),
    user: AuthedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    _parse_date(date)
    doc = await recap_service.get_recap(session, date, kind)
    if not doc:
        what = "recap" if kind == "daily" else f"{kind} recap"
        raise HTTPException(status_code=404, detail=f"No {what} for {date}")
    body: dict[str, object] = {"recap": doc}
    if kind == "weekly":
        body["hit_rate"] = await recap_service.get_hit_rate(session)
    return body


@router.post("/generate")
async def recap_generate(
    request: Request,
    date: str | None = Query(None, description="kind=daily: YYYY-MM-DD — defaults to yesterday"),
    force: bool = Query(False, description="Regenerate even if cached"),
    kind: Kind = Query(
        "daily", description="daily: one day by hand (default); weekly: a Monday-Sunday week (UTC)"
    ),
    week_start: str | None = Query(
        None,
        description="kind=weekly: the Monday of the week, YYYY-MM-DD — defaults to the last "
        "finished week; a week whose Sunday has not ended in UTC is refused",
    ),
    user: AuthedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    if kind == "weekly":
        if date:
            raise HTTPException(
                status_code=400, detail="date is for kind=daily; use week_start for kind=weekly"
            )
        start = _parse_date(week_start, "week_start") if week_start else None
        try:
            doc = await recap_service.generate_weekly_recap(session, week_start=start, force=force)
        except recap_service.RecapWindowError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except recap_service.RecapEmptyError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        action = "generate_weekly_recap"
        detail: dict[str, object] = {
            "week_start": doc.get("period_start"),
            "period_end": doc.get("period_end"),
            "force": force,
        }
    else:
        if week_start:
            raise HTTPException(
                status_code=400, detail="week_start is for kind=weekly; use date for kind=daily"
            )
        if date:
            _parse_date(date)
        try:
            doc = await recap_service.generate_daily_recap(session, date=date, force=force)
        except recap_service.RecapEmptyError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        action = "generate_daily_recap"
        detail = {"date": doc.get("date"), "force": force}
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action=action,
        detail=detail,
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"recap": doc}


@router.patch("/{recap_id}/scorecard/{event_id}")
async def recap_override_scorecard(
    recap_id: int,
    event_id: str,
    body: ScorecardOverrideIn,
    request: Request,
    user: AuthedUser = Depends(require_auth),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Verdict analis untuk satu event forecast di scorecard recap `recap_id`. Disimpan di samping
    verdict model (siapa dan kapan), dipakai hit rate sebagai pengganti verdict model, dan ditulis
    ke audit log. `recap_id` = recap pekan yang MEMUAT scorecard itu (pekan yang me-review),
    `event_id` = id event forecast pekan sebelumnya (`f1`, `f2`, ...). Membalas recap yang sudah
    diperbarui dan hit rate yang dihitung ulang. 404 kalau recap, scorecard-nya, atau event-nya
    tidak ada; auth-nya sama dengan `POST /generate` (login saja)."""
    try:
        doc = await recap_service.override_scorecard(
            session, recap_id, event_id, body.verdict, user["username"]
        )
    except recap_service.ScorecardNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    entry = next(e for e in doc["quality"]["scorecard"]["events"] if e["id"] == event_id)
    await AsyncAuditLogRepo(session).write(
        username=user["username"],
        action="override_recap_scorecard",
        target_id=str(recap_id),
        detail={
            "week_start": doc["date"],
            "event_id": event_id,
            "verdict": body.verdict,
            "model_verdict": entry["verdict"],
        },
        ip_address=request_ip(request),
    )
    await session.commit()
    return {"recap": doc, "hit_rate": await recap_service.get_hit_rate(session)}
