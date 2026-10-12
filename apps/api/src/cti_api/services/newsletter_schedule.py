"""Jadwal bulanan newsletter (ROADMAP #22, PR 8): KAPAN saran edisi disiapkan sendiri.

Beat memicu `newsletter.prepare_monthly` tiap hari kerja pukul 09:00 WIB; task-nya memanggil
`prepare_monthly` di sini, yang hanya bekerja pada hari kerja pertama bulan itu dan hari-hari
sesudahnya dalam jendela kejar (`should_prepare`).

**Hari kerja pertama = Senin-Jumat pertama bulan itu.** Hari libur nasional TIDAK dilacak
(keputusan user 2026-10-11): kalau hari itu libur (1 Jan 2027 hari Jumat), sarannya sekadar sudah
siap sebelum analis kembali, dan karena tidak ada yang dikirim otomatis, menyiapkan lebih awal
tidak merugikan. Maka tidak ada daftar libur dan tidak ada setting baru.

**Idempoten tanpa status tambahan.** Satu saran per jendela (`newsletter_suggestions` unik di
`(period_start, period_end)`) adalah tandanya: begitu bulan sebelumnya punya saran, hari-hari
berikutnya tidak melakukan apa-apa. Pengiriman ganda (`acks_late`) paling banyak membayar satu
panggilan LLM lagi. Hari-hari sesudah hari kerja pertama adalah KEJAR kalau worker sempat mati,
jadi edisinya telat, bukan hilang; batas 7 hari mencegah deploy di tengah bulan membuat saran
untuk bulan yang sudah terkirim. Sesudah jendela itu hanya rebuild dengan tangan
(`POST /api/newsletter/suggestion/rebuild`) yang berlaku."""

from __future__ import annotations

import datetime
from typing import Any

from cti_core.config import get_settings
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import newsletter_edition, newsletter_suggestion

PREPARE_WINDOW_DAYS = 7
"""Berapa hari sesudah hari kerja pertama (inklusif) saran masih disiapkan otomatis."""

_SATURDAY = 5


def first_weekday(year: int, month: int) -> datetime.date:
    """Senin-Jumat pertama bulan itu: tanggal 1 kalau jatuh di hari kerja, kalau tidak Senin
    berikutnya (1 Nov 2026 hari Minggu -> 2 Nov; 1 Agu 2026 hari Sabtu -> 3 Agu)."""
    day = datetime.date(year, month, 1)
    if day.weekday() >= _SATURDAY:
        day += datetime.timedelta(days=7 - day.weekday())
    return day


def should_prepare(today: datetime.date, has_suggestion_for_previous_month: bool) -> bool:
    """`today` ada dalam `PREPARE_WINDOW_DAYS` hari (inklusif) dari hari kerja pertama bulannya,
    DAN bulan sebelumnya belum punya saran. `today` = tanggal lokal laporan (WIB), bukan UTC."""
    if has_suggestion_for_previous_month:
        return False
    first = first_weekday(today.year, today.month)
    return first <= today <= first + datetime.timedelta(days=PREPARE_WINDOW_DAYS)


async def prepare_monthly(session: AsyncSession, now_utc: datetime.datetime) -> dict[str, Any]:
    """Siapkan saran bulan sebelumnya kalau sudah waktunya (`should_prepare`), selain itu kembali
    segera tanpa menyentuh LLM. Tidak commit: pemanggilnya (task) yang commit.

    Jendelanya bulan kalender sebelumnya menurut zona laporan, jendela default yang sama dengan
    `POST /suggestion/rebuild` tanpa body. Mengembalikan ringkasan kecil untuk hasil task."""
    offset = get_settings().worker.report_utc_offset_hours
    today = (now_utc + datetime.timedelta(hours=offset)).date()
    period_start, period_end = newsletter_edition.default_period(now_utc, offset)
    existing = await AsyncNewsletterRepo(session).get_suggestion(period_start, period_end)
    if not should_prepare(today, existing is not None):
        return {"prepared": False, "period_start": period_start.isoformat()}
    row = await newsletter_suggestion.build_suggestion(session, period_start, period_end)
    return {
        "prepared": True,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "suggestion_id": row.id,
        "items": len(row.items),
        "summary": bool(row.summary_text),
    }
