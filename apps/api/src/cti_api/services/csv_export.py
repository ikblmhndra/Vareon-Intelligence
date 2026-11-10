"""Helper CSV bersama untuk export halaman Intelligence (SR, IOC; redesign 2b).

Kenapa ada guard `safe_cell`: sel CSV yang diawali `=`, `+`, `-`, `@`, tab atau CR dieksekusi
sebagai formula oleh Excel/Sheets (CSV injection) -- nilai seperti judul artikel atau nilai IOC
berasal dari sumber luar. Awalan `'` menetralkan formula tanpa mengubah isi yang terbaca.
Hanya awalan di posisi pertama yang dijaga; spasi di depan (`" =1"`) tidak dieksekusi
spreadsheet, jadi dibiarkan apa adanya.

Sengaja TERPISAH dari `_csv` di `routers/v2_indicators.py`: itu kontrak mesin (feed untuk
konsumen seperti Splunk), jadi nilainya tidak boleh dimodifikasi dengan awalan `'`; export
untuk manusia di sini membutuhkan guard itu. BOM UTF-8 ditambah supaya Excel membaca
nama non-ASCII dengan benar."""

from __future__ import annotations

import csv
import datetime
import io
from collections.abc import Iterable, Mapping, Sequence

from fastapi import Response

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> str | int | float:
    """Normalkan satu nilai ke sel CSV; string berawalan formula diberi `'` di depan."""
    if value is None:
        return ""
    if isinstance(value, bool):  # sebelum int: bool subclass int, jangan jadi 1/0
        return "true" if value else "false"
    if isinstance(value, int | float):
        return value
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return ";".join(str(safe_cell(v)) for v in value)
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


def csv_response(
    header: Sequence[str],
    rows: Iterable[Sequence[object]],
    filename: str,
    *,
    headers: Mapping[str, str] | None = None,
) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow([safe_cell(h) for h in header])
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return Response(
        "﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', **(headers or {})},
    )
