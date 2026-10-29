"""Skema feed mesin REST (P7b 4.3). Urutan field = urutan kolom CSV."""

import datetime

from pydantic import BaseModel


class IndicatorFeedItem(BaseModel):
    id: int
    stix_id: str
    type: str
    value: str
    state: str
    valid_from: datetime.datetime
    valid_until: datetime.datetime | None
    first_seen: datetime.datetime
    last_seen: datetime.datetime
    seen_count: int
    confidence: int
    tlp: str
    pap: str
    tags: list[str]
    revoked_at: datetime.datetime | None
    changed_at: datetime.datetime


class IndicatorFeedPage(BaseModel):
    items: list[IndicatorFeedItem]
    next_cursor: str | None
