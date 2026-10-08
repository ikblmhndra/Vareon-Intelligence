"""Info "diupdate per kapan" dan pemicu cek manual CVE di tab CVEs (`services/cve_check.py`)."""

from __future__ import annotations

import datetime
from typing import Literal

from pydantic import BaseModel

CheckSourceId = Literal["new_cve", "mirror"]


class CveCheckSource(BaseModel):
    """Satu jalur yang mengisi `cve_tracker`: scraper `new_cve` (default) atau mirror CVE List V5
    (bila promosi mirror `live`)."""

    id: CheckSourceId
    label: str
    enabled: bool
    """`False` = dimatikan di control plane (`ScraperConfig.enabled`); tidak ada cek otomatis."""
    last_checked_at: datetime.datetime | None
    """Selesai terakhir yang SUKSES (`ok`/`empty`/`partial`). Mirror: `polled_at` sync terakhir."""
    last_run_finished_at: datetime.datetime | None
    """Percobaan terakhir yang selesai, apa pun statusnya (mirror: sama dengan checked)."""
    last_run_status: str | None
    running: bool
    next_check_at: datetime.datetime | None
    """Slot cek otomatis berikutnya menurut jadwal; `None` bila dimatikan."""


class CveFreshness(BaseModel):
    sources: list[CveCheckSource]
    last_checked_at: datetime.datetime | None
    """Yang terbaru dari semua jalur: "diupdate per kapan"."""
    last_run_finished_at: datetime.datetime | None
    running: bool
    newest_detected_at: datetime.datetime | None
    """CVE terbaru yang tercatat di tab CVEs (client aktif, tech dimonitor, tanpa FP)."""
    new_since: int | None
    """Hanya terisi bila `new_since` diberikan: jumlah CVE baru tercatat sejak waktu itu."""


class CveCheckTriggered(BaseModel):
    status: Literal["queued"]
    triggered_at: datetime.datetime
    sources: list[CheckSourceId]
