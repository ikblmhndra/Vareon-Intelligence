"""Unit test `cti_api.services.newsletter_edition` (batas tier, pemisahan tier, periode) dan
validasi bentuk request `NewsletterSectionsBody` -- semuanya murni, tanpa DB (ROADMAP #22, PR 5)."""

from __future__ import annotations

import datetime

import pytest
from cti_api.schemas.newsletter import NewsletterSectionsBody
from cti_api.services import newsletter_edition as ed
from pydantic import ValidationError

UTC = datetime.UTC
D = datetime.date


def _ids(n: int, start: int = 1) -> list[int]:
    return list(range(start, start + n))


# ── Batas ────────────────────────────────────────────────────────────────────


def test_limits_are_the_agreed_starting_values() -> None:
    """Angka awal yang disetel setelah edisi pertama; test ini menahan perubahan tak sengaja."""
    assert ed.MAX_HIGHLIGHTS == 3
    assert ed.MAX_FULL_PER_SECTION == 4
    assert ed.MAX_COMPACT_PER_SECTION == 15


def test_tiered_request_at_the_limits_is_accepted() -> None:
    body = NewsletterSectionsBody(
        highlights=_ids(3),
        apac_full=_ids(4, 10),
        global_news_full=_ids(4, 20),
        indonesia_full=_ids(4, 30),
        apac_compact=_ids(15, 100),
        global_news_compact=_ids(15, 200),
        indonesia_compact=_ids(15, 300),
    )
    plan = ed.plan_sections(body)
    assert len(plan.highlights) == 3
    assert all(len(plan.full[s]) == 4 and len(plan.compact[s]) == 15 for s in ed.SECTIONS)


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("highlights", 3),
        ("apac_full", 4),
        ("global_news_full", 4),
        ("indonesia_full", 4),
        ("apac_compact", 15),
        ("global_news_compact", 15),
        ("indonesia_compact", 15),
    ],
)
def test_one_over_the_limit_is_rejected_with_a_message_naming_the_field(
    field: str, limit: int
) -> None:
    kwargs: dict[str, list[int]] = {field: _ids(limit + 1)}
    if field != "highlights":
        kwargs["highlights"] = [999]  # bentuk valid: butuh satu highlight
    body = NewsletterSectionsBody(**kwargs)
    with pytest.raises(ed.SectionLimitError) as exc:
        ed.plan_sections(body)
    assert str(exc.value) == f"{field}: max {limit} articles"


# ── Pemisahan tier ───────────────────────────────────────────────────────────


def test_tiered_request_is_split_per_section_and_tier() -> None:
    plan = ed.plan_sections(
        NewsletterSectionsBody(
            highlights=[10, 11],
            apac_full=[1, 2],
            apac_compact=[3, 4],
            global_news_compact=[5],
            indonesia_full=[6],
        )
    )
    assert plan.highlights == [10, 11]
    assert plan.full == {"apac": [1, 2], "global_news": [], "indonesia": [6]}
    assert plan.compact == {"apac": [3, 4], "global_news": [5], "indonesia": []}
    assert plan.all_ids == [10, 11, 1, 2, 3, 4, 5, 6]


def test_all_ids_lists_an_article_once_even_when_the_request_repeats_it() -> None:
    plan = ed.plan_sections(
        NewsletterSectionsBody(highlights=[1], apac_full=[1, 2], global_news_compact=[2, 3])
    )
    assert plan.all_ids == [1, 2, 3]


# ── Bentuk request ───────────────────────────────────────────────────────────


def test_a_highlight_is_required() -> None:
    with pytest.raises(ValidationError, match="highlight is required"):
        NewsletterSectionsBody()
    with pytest.raises(ValidationError, match="highlight is required"):
        NewsletterSectionsBody(apac_full=[1])
    NewsletterSectionsBody(highlights=[1])


def test_the_old_request_fields_are_gone() -> None:
    """`highlight`, `apac`, `global_news` dan `indonesia` dihapus setelah composer baru (PR 9) tidak
    lagi mengirimnya. Pydantic mengabaikan field asing, jadi request lama bukan lagi bentuk yang
    sah: tanpa `highlights` ia ditolak, dan sisanya tidak diam-diam menjadi kartu penuh."""
    for old in ("highlight", "apac", "global_news", "indonesia"):
        assert old not in NewsletterSectionsBody.model_fields
    with pytest.raises(ValidationError, match="highlight is required"):
        NewsletterSectionsBody.model_validate({"highlight": 1, "apac": [2]})
    body = NewsletterSectionsBody.model_validate({"highlights": [1], "apac": [2]})
    assert ed.plan_sections(body).full["apac"] == []


def test_the_request_the_composer_sends_validates_with_every_field() -> None:
    """Persis yang dikirim composer baru (`buildRequestBody`): tidak boleh mulai ditolak."""
    body = NewsletterSectionsBody(
        highlights=[1],
        apac_full=[2],
        apac_compact=[5],
        global_news_full=[3],
        indonesia_full=[4],
        custom_css="",
        custom_intro="<p>ringkasan</p>",
        custom_footer="",
        notes={"2": "catatan"},
        include_clusters=True,
        cluster_days=7,
        language="en",
        regenerate=[2],
        period_start=D(2026, 10, 1),
        period_end=D(2026, 10, 31),
    )
    assert body.highlights == [1]
    assert body.language == "en"
    assert body.regenerate == [2]


def test_period_needs_both_dates_or_neither() -> None:
    with pytest.raises(ValidationError, match="both period_start and period_end"):
        NewsletterSectionsBody(highlights=[1], period_start=D(2026, 10, 1))
    with pytest.raises(ValidationError, match="both period_start and period_end"):
        NewsletterSectionsBody(highlights=[1], period_end=D(2026, 10, 31))


def test_period_start_must_not_be_after_period_end() -> None:
    with pytest.raises(ValidationError, match="must not be after"):
        NewsletterSectionsBody(
            highlights=[1], period_start=D(2026, 11, 1), period_end=D(2026, 10, 31)
        )
    ok = NewsletterSectionsBody(
        highlights=[1], period_start=D(2026, 10, 5), period_end=D(2026, 10, 5)
    )
    assert ok.period_start == ok.period_end  # satu hari tetap sah


def test_period_accepts_iso_strings_from_json() -> None:
    body = NewsletterSectionsBody.model_validate(
        {"highlights": [1], "period_start": "2026-10-01", "period_end": "2026-10-31"}
    )
    assert (body.period_start, body.period_end) == (D(2026, 10, 1), D(2026, 10, 31))


# ── Periode bawaan: bulan kalender sebelumnya di WIB ─────────────────────────


@pytest.mark.parametrize(
    ("now_utc", "offset", "expected"),
    [
        # Senin 2 Nov 09:00 WIB (= 02:00 UTC): edisi Oktober.
        (datetime.datetime(2026, 11, 2, 2, 0, tzinfo=UTC), 7, (D(2026, 10, 1), D(2026, 10, 31))),
        # Januari -> Desember tahun SEBELUMNYA.
        (datetime.datetime(2027, 1, 4, 2, 0, tzinfo=UTC), 7, (D(2026, 12, 1), D(2026, 12, 31))),
        # 31 Okt 20:00 UTC sudah 1 Nov 03:00 WIB: tim ada di November, jadi Oktober...
        (datetime.datetime(2026, 10, 31, 20, 0, tzinfo=UTC), 7, (D(2026, 10, 1), D(2026, 10, 31))),
        # ...sedangkan instan yang sama tanpa offset masih 31 Okt: September.
        (datetime.datetime(2026, 10, 31, 20, 0, tzinfo=UTC), 0, (D(2026, 9, 1), D(2026, 9, 30))),
        # Februari kabisat.
        (datetime.datetime(2028, 3, 1, 0, 0, tzinfo=UTC), 7, (D(2028, 2, 1), D(2028, 2, 29))),
        # Hari terakhir bulan UTC yang sudah tanggal 1 di WIB.
        (datetime.datetime(2026, 3, 31, 18, 0, tzinfo=UTC), 7, (D(2026, 3, 1), D(2026, 3, 31))),
        # Tengah bulan dan awal Januari pukul 00:00.
        (datetime.datetime(2026, 10, 15, 12, 0, tzinfo=UTC), 7, (D(2026, 9, 1), D(2026, 9, 30))),
        (datetime.datetime(2026, 1, 1, 0, 0, tzinfo=UTC), 7, (D(2025, 12, 1), D(2025, 12, 31))),
    ],
)
def test_default_period_is_the_previous_calendar_month_in_local_time(
    now_utc: datetime.datetime, offset: int, expected: tuple[datetime.date, datetime.date]
) -> None:
    assert ed.default_period(now_utc, offset) == expected


# ── Label ────────────────────────────────────────────────────────────────────


def test_period_label_for_a_single_month_uses_fixed_english_names() -> None:
    assert ed.period_label(D(2026, 10, 1), D(2026, 10, 31)) == "October 2026"
    assert ed.period_label(D(2026, 1, 1), D(2026, 1, 31)) == "January 2026"
    assert ed.period_label(D(2026, 12, 1), D(2026, 12, 31)) == "December 2026"


def test_period_label_for_a_partial_month_still_names_that_month() -> None:
    assert ed.period_label(D(2026, 10, 5), D(2026, 10, 18)) == "October 2026"


def test_period_label_across_months_names_both() -> None:
    assert ed.period_label(D(2026, 9, 28), D(2026, 10, 4)) == "September - October 2026"
    assert ed.period_label(D(2026, 12, 28), D(2027, 1, 3)) == "December 2026 - January 2027"


def test_edition_label_prefers_the_period_and_falls_back_to_the_iso_week() -> None:
    assert ed.edition_label(D(2026, 10, 1), D(2026, 10, 31), 45, 2026) == "October 2026"
    assert ed.edition_label(None, None, 39, 2026) == "Week 39, 2026"
    # Baris yang entah bagaimana hanya punya salah satu tanggal tidak menebak.
    assert ed.edition_label(D(2026, 10, 1), None, 39, 2026) == "Week 39, 2026"


# ── Rentang, tanggal, subject (ROADMAP #22, PR template) ─────────────────────


EN_DASH = "\N{EN DASH}"
"""Pemisah rentang di header; konstanta karena ruff (RUF001) menandai EN DASH literal."""


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (D(2026, 10, 1), D(2026, 10, 31), f"1 {EN_DASH} 31 October 2026"),
        (D(2026, 9, 28), D(2026, 10, 4), f"28 September {EN_DASH} 4 October 2026"),
        (D(2026, 12, 28), D(2027, 1, 3), f"28 December 2026 {EN_DASH} 3 January 2027"),
        (D(2026, 10, 1), D(2026, 10, 1), "1 October 2026"),
        (D(2026, 2, 1), D(2026, 2, 28), f"1 {EN_DASH} 28 February 2026"),
    ],
)
def test_period_range_names_the_dates_with_an_en_dash(
    start: datetime.date, end: datetime.date, expected: str
) -> None:
    assert ed.period_range(start, end) == expected


def test_long_date_uses_fixed_english_names() -> None:
    assert ed.long_date(D(2026, 11, 2)) == "Monday, 2 November 2026"
    assert ed.long_date(D(2027, 1, 3)) == "Sunday, 3 January 2027"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-20", "20 Oct 2026"),
        ("2026-05-02", "2 May 2026"),
        ("2026-10-20T08:30:00+00:00", "20 Oct 2026"),  # datetime ISO: hanya bagian tanggal
        ("", ""),  # sumber tanpa tanggal
        (None, ""),
        ("kemarin", "kemarin"),  # bukan ISO: apa adanya, tidak menjatuhkan render
    ],
)
def test_short_date_formats_iso_dates_and_leaves_anything_else_alone(
    value: object, expected: str
) -> None:
    assert ed.short_date(value) == expected


def test_subject_uses_the_period_label_when_the_row_has_a_period() -> None:
    subject = ed.newsletter_subject(D(2026, 10, 1), D(2026, 10, 31), 45, 2026)

    assert subject == "[CTI Newsletter] Threat Intelligence Digest — October 2026"


def test_subject_falls_back_to_the_iso_week_for_rows_without_a_period() -> None:
    subject = ed.newsletter_subject(None, None, 38, 2026)

    assert subject == "[CTI Newsletter] Threat Intelligence Digest — Week 38, 2026"


def test_subject_for_a_custom_range_names_both_months() -> None:
    subject = ed.newsletter_subject(D(2026, 9, 28), D(2026, 10, 4), 40, 2026)

    assert subject.endswith("— September - October 2026")


def test_fields_added_after_the_web_was_written_stay_optional_in_the_generated_types() -> None:
    """openapi-typescript menjadikan field ber-`default` di body request WAJIB di tipe TS
    (`defaultNonNullable`), sehingga halaman web yang belum mengirimnya gagal compile; ketahuan
    saat `language` ditambah dengan `default="id"`. Field baru memakai `default_factory` (tanpa
    kunci `default` di kontrak), seperti `regenerate` dan field tier dari PR 5. Web baru (PR 9)
    boleh mengirimnya; yang lama tidak dipaksa."""
    schema = NewsletterSectionsBody.model_json_schema()

    for name in ("language", "regenerate", "highlights", "apac_full", "apac_compact"):
        assert "default" not in schema["properties"][name], name
        assert name not in schema.get("required", []), name
    assert schema["properties"]["language"]["enum"] == ["id", "en"]
