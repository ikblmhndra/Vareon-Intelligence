"""Feed indikator REST untuk mesin (P7b 4.3). Auth `require_token`, bukan JWT."""

from __future__ import annotations

import csv
import datetime
import io
from typing import Literal

from cti_core.indicator.stix_id import indicator_uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.deps import get_db
from cti_api.machine_auth import MachinePrincipal, require_token
from cti_api.schemas.feed import IndicatorFeedItem, IndicatorFeedPage
from cti_api.services.feed import decode_cursor, feed_page

router = APIRouter(prefix="/api/v2", tags=["machine-api"])

STATES = ("active", "expired", "revoked", "allowlisted")
FIELDS = list(IndicatorFeedItem.model_fields)


def _item(ind) -> IndicatorFeedItem:  # type: ignore[no-untyped-def]
    return IndicatorFeedItem(
        id=ind.id,
        stix_id=f"indicator--{ind.stix_id or indicator_uuid(ind.type, ind.value)}",
        type=ind.type,
        value=ind.value,
        state=ind.state,
        valid_from=ind.valid_from,
        valid_until=ind.valid_until,
        first_seen=ind.first_seen_at,
        last_seen=ind.last_seen_at,
        seen_count=ind.seen_count,
        confidence=ind.confidence_score,
        tlp=ind.tlp,
        pap=ind.pap,
        tags=sorted(t.tag for t in ind.tags),
        revoked_at=ind.revoked_at,
        changed_at=ind.feed_changed_at,
    )


def _csv(items: list[IndicatorFeedItem], next_cursor: str | None) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(FIELDS)
    for it in items:
        row = it.model_dump()
        row["tags"] = ";".join(it.tags)
        writer.writerow(
            [
                ""
                if row[f] is None
                else (row[f].isoformat() if isinstance(row[f], datetime.datetime) else row[f])
                for f in FIELDS
            ]
        )
    headers = {"X-Next-Cursor": next_cursor} if next_cursor else {}
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8", headers=headers)


@router.get("/indicators", response_model=IndicatorFeedPage)
async def list_indicators(
    request: Request,
    state: list[str] = Query(["active"]),
    type_: list[str] | None = Query(None, alias="type"),
    changed_after: datetime.datetime | None = None,
    cursor: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    format_: Literal["json", "csv"] | None = Query(None, alias="format"),
    _principal: MachinePrincipal = Depends(require_token("indicators:read")),
    session: AsyncSession = Depends(get_db),
) -> IndicatorFeedPage | Response:
    states = None if "any" in state else state
    if states is not None and (bad := [s for s in states if s not in STATES]):
        raise HTTPException(400, f"Unknown state: {', '.join(bad)}")
    if changed_after is not None and changed_after.tzinfo is None:
        raise HTTPException(400, "changed_after must include a timezone offset")
    after = None
    if cursor is not None:
        try:
            after = decode_cursor(cursor)
        except ValueError:
            raise HTTPException(400, "Invalid cursor") from None
    page = await feed_page(
        session,
        max_tlp=_principal.max_tlp,
        limit=limit,
        states=states,
        types=type_,
        changed_after=changed_after,
        after=after,
    )
    items = [_item(i) for i in page.items]
    if format_ == "csv" or (format_ is None and "text/csv" in request.headers.get("accept", "")):
        return _csv(items, page.next_cursor)
    return IndicatorFeedPage(items=items, next_cursor=page.next_cursor)
