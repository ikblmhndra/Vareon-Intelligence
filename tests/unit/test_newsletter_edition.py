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
    assert ed.LEGACY_MAX_PER_SECTION == 5


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


@pytest.mark.parametrize("section", ["apac", "global_news", "indonesia"])
def test_legacy_fields_keep_their_old_cap_of_five_and_the_old_message(section: str) -> None:
    ok = NewsletterSectionsBody(highlight=1, **{section: _ids(5, 10)})
    assert len(ed.plan_sections(ok).full[section]) == 5

    over = NewsletterSectionsBody(highlight=1, **{section: _ids(6, 10)})
    with pytest.raises(ed.SectionLimitError) as exc:
        ed.plan_sections(over)
    assert str(exc.value) == f"{section}: max 5 articles"


# ── Pemisahan tier ───────────────────────────────────────────────────────────


def test_legacy_request_maps_to_one_highlight_and_full_cards_only() -> None:
    plan = ed.plan_sections(
        NewsletterSectionsBody(highlight=9, apac=[1, 2], global_news=[3], indonesia=[])
    )
    assert plan.highlights == [9]
    assert plan.full == {"apac": [1, 2], "global_news": [3], "indonesia": []}
    assert plan.compact == {"apac": [], "global_news": [], "indonesia": []}
    assert plan.all_ids == [9, 1, 2, 3]


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


def test_legacy_and_tier_fields_cannot_be_mixed() -> None:
    with pytest.raises(ValidationError, match="not both"):
        NewsletterSectionsBody(highlight=1, apac_full=[2])
    with pytest.raises(ValidationError, match="not both"):
        NewsletterSectionsBody(highlights=[1], apac=[2])
    with pytest.raises(ValidationError, match="not both"):
        NewsletterSectionsBody(highlight=1, highlights=[2])


def test_a_highlight_is_required_in_either_shape() -> None:
    with pytest.raises(ValidationError, match="highlight is required"):
        NewsletterSectionsBody()
    with pytest.raises(ValidationError, match="highlight is required"):
        NewsletterSectionsBody(apac=[1])
    with pytest.raises(ValidationError, match="highlight is required"):
        NewsletterSectionsBody(apac_full=[1])
    NewsletterSectionsBody(highlight=1)
    NewsletterSectionsBody(highlights=[1])


def test_old_style_request_still_validates_with_every_old_field() -> None:
    """Persis yang dikirim web sekarang (`buildPayload`): tidak boleh mulai ditolak."""
    body = NewsletterSectionsBody(
        highlight=1,
        apac=[2],
        global_news=[3],
        indonesia=[4],
        custom_css="",
        custom_intro="",
        custom_footer="",
        notes={"2": "catatan"},
        include_clusters=True,
        cluster_days=7,
    )
    assert body.highlight == 1
    assert body.period_start is None
    assert body.regenerate == []


def test_period_needs_both_dates_or_neither() -> None:
    with pytest.raises(ValidationError, match="both period_start and period_end"):
        NewsletterSectionsBody(highlight=1, period_start=D(2026, 10, 1))
    with pytest.raises(ValidationError, match="both period_start and period_end"):
        NewsletterSectionsBody(highlight=1, period_end=D(2026, 10, 31))


def test_period_start_must_not_be_after_period_end() -> None:
    with pytest.raises(ValidationError, match="must not be after"):
        NewsletterSectionsBody(highlight=1, period_start=D(2026, 11, 1), period_end=D(2026, 10, 31))
    ok = NewsletterSectionsBody(highlight=1, period_start=D(2026, 10, 5), period_end=D(2026, 10, 5))
    assert ok.period_start == ok.period_end  # satu hari tetap sah


def test_period_accepts_iso_strings_from_json() -> None:
    body = NewsletterSectionsBody.model_validate(
        {"highlight": 1, "period_start": "2026-10-01", "period_end": "2026-10-31"}
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
