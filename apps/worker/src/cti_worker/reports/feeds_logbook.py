"""Logbook Threat Information Feeds (Excel, bulanan) -- gantiin skrip Rundeck lama
(`report.py` + `modules/test.py`, di luar repo ini).

Inventaris sumber Threat Information, satu baris per scraper terdaftar, dimasukkan ke templat
dokumen resmi (`templates/feeds_logbook_template.xlsx`, disalin dari `templateNEW.xlsx` user)
lengkap dengan blok tanda tangan.

Perbedaan dari skrip lama:
  - Data dari registry scraper Vareon (`registry.discover()`), bukan daftar job Rundeck project
    `Threat-Information` + grep URL/nama library di file Python tiap job. Sejak cutover job
    Rundeck dimatikan, jadi laporan Oktober 2026 menulis 194 dari 200 baris "Disabled /
    TEMPORARY DISABLED": laporannya menggambarkan sistem yang sudah pensiun.
  - Satu baris per scraper. Skrip lama satu baris per domain (pilih Request > XML > Selenium);
    dua scraper di host yang sama sekarang jadi dua baris.
  - Status = `supersede.effective_enabled` (aturan yang sama dengan beat), dan Notes diturunkan
    dari control plane + health (`notes_for`), bukan deskripsi job yang ditulis tangan ("WEB
    ERROR"). Scraper yang aktif tapi rusak terus-menerus kini tertulis `ERROR`, bukan "Running"
    polos.
  - Last Update = run terakhir yang benar-benar memberi item baru (`items_new > 0`) sampai akhir
    periode. Skrip lama memakai mtime file offset scraper (maksudnya sama), dan di host lama
    hasilnya `18 April 2026` massal atau `01 Januari 1` (`datetime.min`).
  - Semua tanggal berbahasa Indonesia (`logbook.format_date_id`; header lama pakai nama bulan
    Inggris), dan paragraf Notes ikut diganti periodenya (skrip lama tidak pernah mengganti
    "1 Mei 2025 -- 31 Mei 2025" bawaan templat).
  - Nama + jabatan penandatangan SENGAJA kosong (diisi tangan saat tanda tangan); skrip lama
    meng-hardcode nama orang.
  - Mengembalikan bytes (tanpa file sementara di disk).

Yang dipertahankan: border tipis, sel rata tengah, wrap di Domain, Status italic, gaya
`Hyperlink` "Link to Scrape", dan merge blok tanda tangan SESUDAH `insert_rows` (openpyxl tidak
menggeser merged range maupun tinggi baris saat menyisipkan baris).
"""

from __future__ import annotations

import calendar
import copy
import io
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from importlib import resources
from typing import TYPE_CHECKING, Any, Literal

import openpyxl
from cti_core.db.repositories.scraper import ScraperConfigRepo, ScraperRunRepo
from cti_scraper.health import compute_health, run_is_failing
from cti_scraper.inventory import hosts, method_for, source_urls
from cti_scraper.registry import discover
from cti_scraper.supersede import disabled_by, effective_enabled
from openpyxl.styles import Alignment, Border, Side

from cti_worker.reports.logbook import format_date_id
from cti_worker.reports.timeutil import local_day_bounds_utc, local_now

if TYPE_CHECKING:
    from cti_core.db.models.scraper import ScraperConfig, ScraperRun
    from cti_scraper.base import ScraperMeta
    from sqlalchemy.orm import Session

_EN_DASH = chr(0x2013)
_NOTES_PERIOD = re.compile(rf"\d{{1,2}} \w+ \d{{4}} {_EN_DASH} \d{{1,2}} \w+ \d{{4}}")
_NOTES_INTRO = "Laporan ini disusun setiap bulan"
_LINK_TEXT = "Link to Scrape"
_ERROR_STREAK = 3
_thin = Side(style="thin")
_B_THIN = Border(top=_thin, right=_thin, left=_thin, bottom=_thin)
_CENTER = Alignment(horizontal="center", vertical="center")
_CENTER_WRAP = Alignment(horizontal="center", vertical="center", wrap_text=True)


@dataclass(frozen=True)
class FeedRow:
    added: date | None
    domain: str
    status: Literal["Running", "Disabled"]
    method: str
    link: str
    last_update: date | None
    notes: str
    source: str
    """Tidak dicetak; kunci urut kedua sesudah `added`."""


def period_for(day: date) -> tuple[date, date]:
    """Periode laporan: tanggal 1 bulan `day` sampai `day`. Run terjadwal hanya jalan di hari
    terakhir bulan (sebulan penuh); run manual di tengah bulan memberi periode parsial."""
    return day.replace(day=1), day


def is_last_day_of_month(day: date) -> bool:
    return day.day == calendar.monthrange(day.year, day.month)[1]


def notes_for(
    meta: ScraperMeta,
    config: ScraperConfig | None,
    runs: Sequence[ScraperRun],
    *,
    now: datetime,
) -> str:
    """Kolom Notes. Laporan ini dokumen bulanan yang ditandatangani, jadi hanya keadaan yang
    BERTAHAN yang ditulis, bukan kedip saat laporan dibuat.

    Dimatikan: alasan operator (`paused_reason`) menang, lalu mirror CVE, lalu kode
    (`meta.enabled=False` = alasan permanen di docstring scraper, bukan "temporary"), sisanya
    `TEMPORARY DISABLED` seperti laporan lama. Jalan: dari input health yang sama dengan digest
    worker. `ERROR` butuh 3 run selesai terbaru yang semuanya gagal dan tidak satu pun
    `backpressure`: `degraded` saja (cukup run terakhir gagal) ikut menghitung `timeout`,
    `rate_limited` dan backpressure se-armada, sehingga antrean enrich yang penuh saat laporan
    dibuat akan menandai feed yang sehat."""
    reason = disabled_by(meta, config)
    if reason is not None:
        if config is not None and config.paused_reason:
            return config.paused_reason
        if reason == "mirror":
            return "REPLACED BY CVE MIRROR"
        if reason == "code":
            return "DISABLED"
        return "TEMPORARY DISABLED"

    health = compute_health(meta, config, list(runs), now=now)
    if health == "stale":
        return "NO RUN RECORDED"
    if health == "dead":
        return "NOT RUNNING"
    # Sama dengan `cti_scraper.health._finished`: `running`/`overlap` bukan hasil run.
    finished = [r for r in runs if r.status not in ("running", "overlap")][:_ERROR_STREAK]
    if len(finished) == _ERROR_STREAK and all(
        run_is_failing(r) and r.status != "backpressure" for r in finished
    ):
        return "ERROR"
    return "-"


def collect(session: Session, *, end: date, offset_hours: int, now: datetime) -> list[FeedRow]:
    """Satu `FeedRow` per scraper terdaftar, urut `added` lalu `source`. Status dan Notes adalah
    potret SAAT laporan dibuat (seperti skrip lama); hanya Last Update yang dibatasi akhir
    periode, supaya replay bulan lampau tidak menampilkan tanggal sesudah bulan itu."""
    registry = discover()
    configs = ScraperConfigRepo(session).get_all()
    run_repo = ScraperRunRepo(session)
    # 5, bukan 3: baris `running`/`overlap` saat laporan dibuat tidak boleh menyempitkan jendela
    # 3 run SELESAI yang dipakai `notes_for` untuk ERROR.
    recent_runs = run_repo.list_recent_by_scraper_bulk(limit=5)
    _, period_end_utc = local_day_bounds_utc(end, offset_hours)
    last_new = run_repo.last_new_items_by_scraper(before=period_end_utc)

    rows: list[FeedRow] = []
    for scraper_id, cls in registry.items():
        meta = cls.meta
        config = configs.get(scraper_id)
        urls = source_urls(cls)  # contract test: tiap scraper punya minimal satu URL
        ts = last_new.get(scraper_id)
        rows.append(
            FeedRow(
                added=meta.added,
                domain=", ".join(hosts(urls)),
                status="Running" if effective_enabled(meta, config) else "Disabled",
                method=method_for(cls),
                link=urls[0],
                last_update=local_now(offset_hours, now_utc=ts).date() if ts else None,
                notes=notes_for(meta, config, recent_runs.get(scraper_id, []), now=now),
                source=meta.source,
            )
        )
    rows.sort(key=lambda r: (r.added or date.min, r.source))
    return rows


def _date_or_dash(day: date | None) -> str:
    return format_date_id(day) if day else "-"


def _find_row(ws: Any, match: Callable[[int], bool], *, start: int = 1) -> int:
    """Nomor baris pertama (dari `start`) yang memenuhi `match`. Posisi dicari dari isi templat,
    bukan koordinat tetap, supaya edit templat tidak diam-diam menulis ke sel yang salah."""
    for row in range(start, ws.max_row + 1):
        if match(row):
            return row
    raise LookupError("feeds logbook template: expected cell not found")


def build(rows: Sequence[FeedRow], *, start: date, end: date) -> bytes:
    template = resources.files("cti_worker.reports").joinpath(
        "templates/feeds_logbook_template.xlsx"
    )
    with resources.as_file(template) as path:
        workbook = openpyxl.load_workbook(path)
    ws = workbook[workbook.sheetnames[0]]

    first, last = format_date_id(start, zero_pad=False), format_date_id(end, zero_pad=False)
    ws["I4"].value = f"Tanggal : {last}"
    ws["E5"].value = f"Logbook Threat Information Feeds Periode\n{first} - {last}"
    notes = ws.cell(
        row=_find_row(ws, lambda r: str(ws.cell(r, 4).value).startswith(_NOTES_INTRO)), column=4
    )
    notes.value = _NOTES_PERIOD.sub(f"{first} {_EN_DASH} {last}", notes.value, count=1)

    # Kolom B "No" juga ada di header legenda (B7); header tabel = "No" + "Added Date".
    header = _find_row(
        ws, lambda r: ws.cell(r, 2).value == "No" and ws.cell(r, 3).value == "Added Date"
    )

    # Tinggi baris di bawah header (baris label tanda tangan) ikut turun: insert_rows tidak
    # memindahkannya, jadi tanpa ini satu baris data jadi lebih tinggi dan label kehilangan tinggi.
    heights = {r: d.height for r, d in ws.row_dimensions.items() if r > header and d.height}
    for r in heights:
        ws.row_dimensions[r].height = None
    for r, height in heights.items():
        ws.row_dimensions[r + len(rows)].height = height

    ws.insert_rows(header + 1, len(rows))
    for no, row in enumerate(rows, start=1):
        r = header + no
        values = (
            no,
            _date_or_dash(row.added),
            row.domain,
            row.status,
            row.method,
            _LINK_TEXT,
            _date_or_dash(row.last_update),
            row.notes,
        )
        for column, value in enumerate(values, start=2):
            cell = ws.cell(row=r, column=column, value=value)
            if column == 7:
                cell.style = "Hyperlink"  # gaya bernama menimpa border/alignment: pasang duluan
                cell.hyperlink = row.link
            cell.border = _B_THIN
            cell.alignment = _CENTER_WRAP if column == 4 else _CENTER  # Domain bisa banyak host
        status = ws.cell(row=r, column=5)
        italic = copy.copy(status.font)
        italic.i = True
        status.font = italic

    # Label, nama, jabatan: E:F dan G:H digabung + kotak penuh dan rata tengah, seperti keluaran
    # skrip lama. Border kanan diambil dari sel kiri saat merge, jadi kotak dipasang sebelum merge.
    label = _find_row(ws, lambda r: ws.cell(r, 5).value == "Disusun Oleh", start=header + 1)
    for r in (label, label + 8, label + 9):
        for left, right in ((5, 6), (7, 8)):
            anchor = ws.cell(row=r, column=left)
            anchor.border = _B_THIN
            anchor.alignment = _CENTER
            ws.merge_cells(start_row=r, start_column=left, end_row=r, end_column=right)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def filename_for(end: date) -> str:
    """Nama file sama dengan laporan lama, supaya arsip tetap berurutan."""
    return f"Logbook Threat Information Feeds {end.isoformat()}.xlsx"


def caption(start: date, end: date) -> str:
    """Format caption lama, tanpa baris `Reporter: @...` (tidak ada orang yang di-hardcode)."""
    return (
        "\n    === <b>THREAT INFORMATION FEEDS REPORT</b> ===\n"
        f"<b>Start Entry Date</b>: {format_date_id(start)}\n"
        f"<b>End Entry Date</b>: {format_date_id(end)}"
    )
