"""Bentuk satu edisi newsletter yang tidak butuh IO: batas tier, pemisahan tier dari request, dan
periode (bulan) yang diliput beserta label, rentang tanggal, dan subject-nya.

Dipisah dari `newsletter.py` (DB, Playwright, LLM) supaya bisa dites tanpa Docker, dan supaya PR
berikutnya (template, ranking, composer) mengimpor batas yang SAMA dari satu tempat, bukan
menyalin angkanya.

Tier (ROADMAP #22, "Design: density"): kartu PENUH vs baris COMPACT per section. Angka batasnya
(`MAX_*`) hidup di `schemas/newsletter.py`, satu tempat, dan diimpor di sini supaya
`cti_api.services.newsletter_edition.MAX_*` tetap bisa dipakai pemanggil lain."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from cti_api.schemas.newsletter import (
    MAX_COMPACT_PER_SECTION,
    MAX_FULL_PER_SECTION,
    MAX_HIGHLIGHTS,
    NewsletterSectionsBody,
)

SECTIONS = ("apac", "global_news", "indonesia")

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
"""Daftar tetap, bukan `strftime("%B")`: nama bulan dari locale server bisa berbeda per mesin,
dan label ini masuk ke subject/histori yang harus sama di mana pun dibuat."""

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_EN_DASH = "\u2013"
"""Ditulis sebagai escape: ruff (RUF001) menandai EN DASH literal sebagai karakter yang mirip tanda
hubung biasa, padahal di sini memang tanda pisah rentang."""

SUBJECT_PREFIX = "[CTI Newsletter] Threat Intelligence Digest \u2014 "


class SectionLimitError(ValueError):
    """Request melewati batas jumlah artikel; pesannya siap dipakai sebagai `detail` HTTP 400."""


@dataclass(frozen=True)
class SectionPlan:
    """Id artikel per tier, dari field request tier."""

    highlights: list[int]
    full: dict[str, list[int]]
    compact: dict[str, list[int]]

    @property
    def all_ids(self) -> list[int]:
        """Semua id yang perlu dimuat dari DB, unik, urut kemunculan."""
        ids = list(self.highlights)
        for section in SECTIONS:
            ids += self.full[section]
            ids += self.compact[section]
        return list(dict.fromkeys(ids))


def _check_limit(name: str, ids: list[int], limit: int) -> None:
    if len(ids) > limit:
        raise SectionLimitError(f"{name}: max {limit} articles")


def plan_sections(body: NewsletterSectionsBody) -> SectionPlan:
    """Petakan request ke tier dan terapkan batasnya (`SectionLimitError` -> HTTP 400)."""
    _check_limit("highlights", body.highlights, MAX_HIGHLIGHTS)
    for section in SECTIONS:
        _check_limit(f"{section}_full", getattr(body, f"{section}_full"), MAX_FULL_PER_SECTION)
        _check_limit(
            f"{section}_compact", getattr(body, f"{section}_compact"), MAX_COMPACT_PER_SECTION
        )

    return SectionPlan(
        highlights=list(body.highlights),
        full={s: list(getattr(body, f"{s}_full")) for s in SECTIONS},
        compact={s: list(getattr(body, f"{s}_compact")) for s in SECTIONS},
    )


# ── Periode ────────────────────────────────────────────────────────────────


def default_period(
    now_utc: datetime.datetime, utc_offset_hours: int
) -> tuple[datetime.date, datetime.date]:
    """Bulan kalender SEBELUM hari ini menurut jam lokal (WIB), awal dan akhir inklusif.

    Hari ini dihitung di zona lokal, bukan UTC: pada 1 Nov 03:00 WIB (31 Okt 20:00 UTC) tim sudah
    ada di November, jadi edisinya Oktober, bukan September. Januari jatuh ke Desember tahun
    sebelumnya tanpa kasus khusus karena awal bulan dikurangi satu hari."""
    today = (now_utc + datetime.timedelta(hours=utc_offset_hours)).date()
    end = today.replace(day=1) - datetime.timedelta(days=1)
    return end.replace(day=1), end


def period_label(start: datetime.date, end: datetime.date) -> str:
    """Label periode: nama bulan dan tahun ("October 2026") untuk satu bulan; rentang lintas bulan
    disebut apa adanya ("September - October 2026", "December 2026 - January 2027") supaya
    label tidak menyesatkan."""
    first = f"{_MONTHS[start.month - 1]} {start.year}"
    if (start.year, start.month) == (end.year, end.month):
        return first
    last = f"{_MONTHS[end.month - 1]} {end.year}"
    if start.year == end.year:
        return f"{_MONTHS[start.month - 1]} - {last}"
    return f"{first} - {last}"


def edition_label(
    period_start: datetime.date | None, period_end: datetime.date | None, week: int, year: int
) -> str:
    """Label edisi di histori: label periode kalau terisi, selain itu "Week N, YYYY" seperti
    baris lama (sebelum kolom periode ada)."""
    if period_start is not None and period_end is not None:
        return period_label(period_start, period_end)
    return f"Week {week}, {year}"


def period_range(start: datetime.date, end: datetime.date) -> str:
    """Rentang tanggal untuk header, dipisah EN DASH: `1 - 31 October 2026`; lintas bulan
    `28 September - 4 October 2026`; lintas tahun menyebut kedua tahun; satu hari saja
    `1 October 2026`."""
    first = f"{start.day} {_MONTHS[start.month - 1]}"
    last = f"{end.day} {_MONTHS[end.month - 1]} {end.year}"
    if start == end:
        return last
    if start.year != end.year:
        first = f"{first} {start.year}"
    elif start.month == end.month:
        first = str(start.day)
    return f"{first} {_EN_DASH} {last}"


def long_date(day: datetime.date) -> str:
    """Tanggal panjang seperti `Monday, 2 November 2026`; nama hari dan bulan dari daftar tetap,
    bukan locale server."""
    return f"{_WEEKDAYS[day.weekday()]}, {day.day} {_MONTHS[day.month - 1]} {day.year}"


def short_date(value: object) -> str:
    """`2026-10-20` jadi `20 Oct 2026` untuk baris artikel. Tanggal artikel datang sebagai teks
    ISO (`posted_on`, kosong kalau sumbernya tidak memberi tanggal); yang bukan ISO dikembalikan
    apa adanya dan yang kosong tetap kosong, supaya satu artikel aneh tidak menjatuhkan render."""
    text = str(value or "")
    try:
        day = datetime.date.fromisoformat(text[:10])
    except ValueError:
        return text
    return f"{day.day} {_MONTHS[day.month - 1][:3]} {day.year}"


def newsletter_subject(
    period_start: datetime.date | None, period_end: datetime.date | None, week: int, year: int
) -> str:
    """Subject email SATU tempat: dipakai `draft-email` (dari konteks) dan `resend` (dari baris
    histori). "[CTI Newsletter] Threat Intelligence Digest — October 2026", atau "Week N, YYYY"
    untuk baris lama tanpa periode. Dulu keduanya menulis "Week N" sendiri-sendiri."""
    return SUBJECT_PREFIX + edition_label(period_start, period_end, week, year)
