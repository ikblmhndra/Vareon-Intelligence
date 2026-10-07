"""`new_cve` -- jam publish MITRE (`published_at`). Export Excel butuh jamnya buat kolom
"CVE Reported Date"; `published` (tanggal saja) tidak cukup. Scraper dulu memotong
`datePublished` jadi tanggal."""

from __future__ import annotations

import datetime

import pytest
from cti_scraper.items import CveItem
from cti_scrapers.feeds.new_cve import NewCve, mitre_datetime

from tests.unit.scraper_helpers import json_response, make_ctx

UTC = datetime.UTC
CAND = {"id": "CVE-2026-2222", "tech": "acme", "link": "x", "summary": "s"}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-08-31T13:53:00.000Z", datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)),
        ("2026-08-31T13:53:00Z", datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)),
        # tanpa penanda zona = UTC (CVE JSON 5.x)
        ("2026-08-31T13:53:00", datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)),
        # offset eksplisit dikonversi ke UTC, bukan dibuang
        ("2026-08-31T20:53:00+07:00", datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)),
        (
            "2026-08-31T13:53:00.123456Z",
            datetime.datetime(2026, 8, 31, 13, 53, 0, 123456, tzinfo=UTC),
        ),
    ],
)
def test_mitre_datetime_parses_full_timestamps_to_utc(
    raw: str, expected: datetime.datetime
) -> None:
    assert mitre_datetime(raw) == expected


@pytest.mark.parametrize(
    "raw", [None, "", "2026-08-31", "2026-08-31T", "not a date", "2026-13-45T10:00:00Z"]
)
def test_mitre_datetime_gives_none_instead_of_guessing_a_time(raw: str | None) -> None:
    assert mitre_datetime(raw) is None


def test_mitre_detail_carries_published_at_next_to_the_date() -> None:
    record = {
        "cveMetadata": {"datePublished": "2026-08-31T13:53:00.000Z"},
        "containers": {"cna": {"affected": [], "metrics": []}},
    }
    ctx = make_ctx(NewCve, lambda r: json_response(record))

    fields = NewCve()._mitre_detail(ctx, CAND).fields

    assert fields["published"] == datetime.date(2026, 8, 31)
    assert fields["published_at"] == datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)
    # kontrak ke CveItem: semua key `fields` harus field item yang valid
    item = CveItem(client_id="default", tech="acme", **fields)
    assert item.published_at == fields["published_at"]


def test_mitre_detail_without_a_publish_time_leaves_published_at_empty() -> None:
    record = {
        "cveMetadata": {"datePublished": "2026-08-31"},
        "containers": {"cna": {"affected": [], "metrics": []}},
    }
    ctx = make_ctx(NewCve, lambda r: json_response(record))

    fields = NewCve()._mitre_detail(ctx, CAND).fields

    assert fields["published"] == datetime.date(2026, 8, 31)
    assert fields["published_at"] is None
