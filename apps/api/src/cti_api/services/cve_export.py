"""Port `ScraperNewsWeb/app/services/cve_export_service.py`. Fase 7.4
Grup C (2026-09-23). Export CVE tracker + ticket jadi Excel, nulis ke
salinan template `.xlsx` (baris data mulai row 16, header row 15 --
`_DATA_START_ROW`/`_HEADER_ROW` di bawah, sama posisi kayak template
lama).

**BUG DITEMUKAN & DIPERBAIKI, bukan port apa adanya** -- query legacy
`export_cves_to_excel()` TIDAK PERNAH nge-scope `client_id` SAMA SEKALI,
baik buat query CVE (`cve_col.find(query)` polos) MAUPUN query false-
positive (`fp_col.find({})` polos). Semua endpoint LAIN di router yang
sama (list/stats/ticket/acknowledge) konsisten scope per-client lewat
`effective_client_id()` -- export-nya doang kelewatan. Di deployment
multi-tenant beneran ini KEBOCORAN DATA lintas client (analis client A
export "CVE tracker saya", dapetnya malah CVE+ticket SEMUA client). Beda
dari `exec_dashboard`'s widget lintas-client (itu MEMANG didesain global
buat ringkasan eksekutif, tujuannya beda) -- export di sini fitur
"tracker personal per-client", jadi ini genuinely oversight, bukan
desain. Diperbaiki: di-scope `client_id`, bukan diikutin."""

from __future__ import annotations

import datetime
import io
import zoneinfo
from copy import copy
from pathlib import Path
from typing import Any

import openpyxl
from cti_core.db.models.cve import CveTicket, CveTracker
from cti_core.db.repositories.cve import (
    AsyncCveFalsePositiveRepo,
    AsyncCveTicketRepo,
    AsyncCveTrackerRepo,
)
from sqlalchemy.ext.asyncio import AsyncSession

_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "CVE_Tracker_template.xlsx"
_TRACKER_SHEET = "CVE Ticket Tracker"
_DATA_START_ROW = 16
_TZ = zoneinfo.ZoneInfo("Asia/Jakarta")

# Kolom A = "No" (nomor urut 1..N, header kosong di template). Kolom 4 ("CVE Reported Date") +
# 5 ("Reported by System") formatnya `HH:MM DD-MM-YYYY` (WIB); kolom 15 (`acknowledge_time`) =
# timestamp lengkap `YYYY-MM-DD HH:MM:SS` (WIB), bukan ISO `T`.
#
# - Kolom 4 = jam publish asli dari MITRE (`CveTracker.published_at`). Baris yang belum punya jamnya
#   (masuk sebelum kolom itu ada dan belum di-backfill) jatuh ke tanggal `published` saja
#   (`DD-MM-YYYY`) -- jam yang ditebak lebih buruk daripada tidak ada. `cve_reported_date` di
#   `CveTicket` legacy (readonly di UI, gak pernah beneran di-override) SENGAJA di-drop pas desain
#   skema baru, lihat docstring `CveTicket`.
# - Kolom 5 = `CveTracker.detected_on`: kapan scraper pertama kali dapat CVE ini.
#
# Kolom (1-based) -> (sumber, nama field). Sumber "cve" = `CveTracker`, "ticket" = `CveTicket`.
_COL_REPORTED_DATE = 4
_COL_REPORTED_BY_SYSTEM = 5
_LAST_COL = 22
_COL_MAP: dict[int, tuple[str, str]] = {
    2: ("ticket", "ticket_id"),
    3: ("cve", "cve_id"),
    6: ("cve", "cve_severity"),
    7: ("cve", "cve_score"),
    8: ("ticket", "affected_asset"),
    9: ("ticket", "affected_version"),
    10: ("ticket", "fixed_version"),
    11: ("ticket", "asset_owner"),
    12: ("ticket", "owner_email"),
    13: ("ticket", "owner_team"),
    14: ("ticket", "active_exploitation"),
    15: ("ticket", "acknowledge_time"),
    16: ("ticket", "remediation_date_plan"),
    17: ("ticket", "remediation_status"),
    18: ("ticket", "actual_remediation_date"),
    19: ("ticket", "escalation_required"),
    20: ("ticket", "comments"),
    21: ("ticket", "risk_acceptance"),
    22: ("ticket", "closure_date"),
}


def _fmt(val: Any) -> Any:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, datetime.datetime):
        if val.tzinfo is not None:
            val = val.astimezone(_TZ)
        return val.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(val, datetime.date):
        return val.isoformat()
    return val


def _fmt_stamp(val: datetime.datetime | datetime.date | None) -> str:
    """`HH:MM DD-MM-YYYY` di WIB (mis. `20:53 31-08-2026`). `date` murni (tanpa jam) jadi
    `DD-MM-YYYY` saja. Teks, bukan nilai tanggal Excel -- sama seperti logbook manual lama."""
    if val is None:
        return ""
    if isinstance(val, datetime.datetime):  # cek duluan: datetime adalah subclass date
        if val.tzinfo is not None:
            val = val.astimezone(_TZ)
        return val.strftime("%H:%M %d-%m-%Y")
    return val.strftime("%d-%m-%Y")


def _cell_value(col_idx: int, cve: CveTracker, ticket: CveTicket | None) -> Any:
    if col_idx == _COL_REPORTED_DATE:
        return _fmt_stamp(cve.published_at or cve.published)
    if col_idx == _COL_REPORTED_BY_SYSTEM:
        return _fmt_stamp(cve.detected_on)

    source, field = _COL_MAP[col_idx]
    if source == "cve":
        return _fmt(getattr(cve, field, None))

    val = getattr(ticket, field, None) if ticket is not None else None
    if not val and field == "affected_asset":
        val = cve.tech
    if not val and field == "affected_version":
        # sama kayak prefill form ticket di UI (`cve-ticket-tab.tsx`):
        # constraint dari tiap entry `"<produk>: <constraint>"`.
        val = ", ".join(a.affected.split(": ", 1)[1] for a in cve.affected if ": " in a.affected)
    if not val and field == "fixed_version":
        val = cve.solutions
    if not val and field == "active_exploitation":
        val = "Yes" if cve.active_exploitation else ""
    return _fmt(val)


def _copy_style(src_cell: Any, dst_cell: Any) -> None:
    if src_cell.has_style:
        dst_cell.font = copy(src_cell.font)
        dst_cell.fill = copy(src_cell.fill)
        dst_cell.border = copy(src_cell.border)
        dst_cell.alignment = copy(src_cell.alignment)
        dst_cell.number_format = src_cell.number_format


async def export_cves_to_excel(
    session: AsyncSession,
    *,
    client_id: str,
    date_start: datetime.date | None = None,
    date_end: datetime.date | None = None,
    search: str | None = None,
    severity: list[str] | None = None,
    tech: list[str] | None = None,
    include_fp: bool = False,
    ack_filter: str | None = None,
    date_basis: str = "detected",
) -> bytes:
    exclude_ids: list[str] = []
    if not include_fp:
        exclude_ids = await AsyncCveFalsePositiveRepo(session).list_cve_ids(client_id)

    cves = await AsyncCveTrackerRepo(session).list_for_export(
        client_id=client_id,
        tech=tech,
        severity=severity,
        search=search,
        date_start=date_start,
        date_end=date_end,
        exclude_cve_ids=exclude_ids,
        ack_filter=ack_filter,
        date_basis=date_basis,
    )
    cve_ids = [c.cve_id for c in cves]
    tickets = await AsyncCveTicketRepo(session).get_by_cve_ids(cve_ids, client_id)

    wb = openpyxl.load_workbook(_TEMPLATE_PATH)
    ws = wb[_TRACKER_SHEET]

    style_ref: list[Any] = []
    if ws.max_row >= _DATA_START_ROW:
        style_ref = list(ws[_DATA_START_ROW])
        ws.delete_rows(_DATA_START_ROW, ws.max_row - _DATA_START_ROW + 1)

    for row_offset, cve in enumerate(cves):
        row_num = _DATA_START_ROW + row_offset
        ticket = tickets.get(cve.cve_id)

        ws.cell(row=row_num, column=1).value = row_offset + 1
        if style_ref:
            _copy_style(style_ref[0], ws.cell(row=row_num, column=1))

        for col_idx in range(2, _LAST_COL + 1):
            cell = ws.cell(row=row_num, column=col_idx)
            cell.value = _cell_value(col_idx, cve, ticket)
            ref_idx = col_idx - 1
            if style_ref and ref_idx < len(style_ref):
                _copy_style(style_ref[ref_idx], cell)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
