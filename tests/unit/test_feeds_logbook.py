"""`cti_worker.reports.feeds_logbook` -- logbook "Threat Information Feeds" bulanan.

Yang dikunci: aturan periode, aturan kolom Notes (hanya keadaan yang bertahan, bukan kedip saat
laporan dibuat), dan isi sel workbook (header, baris, hyperlink, blok tanda tangan yang
penandatangannya sengaja kosong). Dibaca balik dengan openpyxl, bukan piksel.
"""

from __future__ import annotations

import io
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from importlib import resources
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest
from cti_scraper import supersede
from cti_scrapers.feeds.anyrun import Anyrun
from cti_worker.reports.feeds_logbook import (
    FeedRow,
    build,
    caption,
    filename_for,
    is_last_day_of_month,
    notes_for,
    period_for,
)

NOW = datetime(2026, 10, 31, 0, 0, tzinfo=UTC)
META = replace(Anyrun.meta, schedule="0 * * * *", enabled=True)  # tiap jam: dead sesudah 3 jam


def _config(*, enabled: bool = True, paused_reason: str | None = None) -> Any:
    return SimpleNamespace(enabled=enabled, paused_reason=paused_reason, schedule=None)


def _runs(*statuses: str) -> list[Any]:
    """Run terbaru duluan, berjarak 10 menit (jauh di bawah ambang `dead`)."""
    return [
        SimpleNamespace(status=s, started_at=NOW - timedelta(minutes=10 * (i + 1)), items_failed=0)
        for i, s in enumerate(statuses)
    ]


def load(data: bytes) -> Any:
    return openpyxl.load_workbook(io.BytesIO(data)).active


ROW_A = FeedRow(
    added=date(2026, 3, 5),
    domain="any.run",
    status="Running",
    method="XML",
    link="https://any.run/cybersecurity-blog/feed/",
    last_update=date(2026, 10, 20),
    notes="-",
    source="Anyrun",
)
ROW_B = FeedRow(
    added=date(2026, 4, 18),
    domain="www.cisa.gov",
    status="Disabled",
    method="Request",
    link="https://www.cisa.gov/news-events/cybersecurity-advisories",
    last_update=None,
    notes="DISABLED",
    source="CISA",
)


def test_period_runs_from_the_first_of_the_month_to_the_given_day() -> None:
    assert period_for(date(2026, 11, 20)) == (date(2026, 11, 1), date(2026, 11, 20))
    assert is_last_day_of_month(date(2026, 2, 28)) and not is_last_day_of_month(date(2026, 10, 30))
    assert is_last_day_of_month(date(2026, 12, 31)) and not is_last_day_of_month(date(2028, 2, 28))


def test_disabled_notes_follow_reason_then_mirror_then_code_then_temporary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutdown = _config(enabled=False, paused_reason="WEB HAS BEEN SHUTDOWN")
    assert notes_for(META, shutdown, [], now=NOW) == "WEB HAS BEEN SHUTDOWN"

    monkeypatch.setattr(supersede, "superseded_by_mirror", lambda sid: sid == "new_cve")
    assert notes_for(replace(META, id="new_cve"), None, [], now=NOW) == "REPLACED BY CVE MIRROR"

    assert notes_for(replace(META, enabled=False), None, _runs("ok"), now=NOW) == "DISABLED"
    assert notes_for(META, _config(enabled=False), _runs("ok"), now=NOW) == "TEMPORARY DISABLED"


def _notes(*statuses: str) -> str:
    """Notes scraper aktif (tanpa baris config) dengan run berstatus `statuses`."""
    return notes_for(META, None, _runs(*statuses), now=NOW)


def test_running_notes_flag_only_lasting_problems() -> None:
    assert _notes() == "NO RUN RECORDED"

    old = [SimpleNamespace(status="ok", started_at=NOW - timedelta(hours=4), items_failed=0)]
    assert notes_for(META, None, old, now=NOW) == "NOT RUNNING"

    assert _notes("fetch_error", "fetch_error", "fetch_error") == "ERROR"
    # backpressure = antrean enrich penuh se-armada, bukan kerusakan sumber ini
    assert _notes("backpressure", "fetch_error", "fetch_error") == "-"
    assert _notes("timeout") == "-"  # satu kegagalan = kedip
    assert _notes("fetch_error", "ok", "ok") == "-"
    assert _notes("empty", "empty", "empty") == "-"  # zero_yield: sumber sepi bukan kerusakan


def test_error_streak_skips_runs_that_are_not_results() -> None:
    # `running`/`overlap` tidak mengambil data: dilewati, 3 run SELESAI terbaru yang dinilai.
    assert _notes("running", "fetch_error", "fetch_error", "fetch_error") == "ERROR"
    assert _notes("overlap", "fetch_error", "fetch_error", "fetch_error") == "ERROR"
    assert _notes("running", "fetch_error", "fetch_error") == "-"


def test_workbook_fills_header_rows_and_leaves_signers_blank() -> None:
    ws = load(build([ROW_A, ROW_B], start=date(2026, 10, 1), end=date(2026, 10, 31)))

    assert ws["I4"].value == "Tanggal : 31 Oktober 2026"
    assert (
        ws["E5"].value
        == "Logbook Threat Information Feeds Periode\n1 Oktober 2026 - 31 Oktober 2026"
    )
    assert "1 Oktober 2026 \u2013 31 Oktober 2026" in ws["D15"].value
    assert "Mei 2025" not in ws["D15"].value
    assert [c.value for c in ws[22][1:9]] == [
        1, "05 Maret 2026", "any.run", "Running", "XML", "Link to Scrape", "20 Oktober 2026", "-",
    ]  # fmt: skip
    assert [c.value for c in ws[23][1:4]] == [2, "18 April 2026", "www.cisa.gov"]
    assert ws["G22"].hyperlink.target == "https://any.run/cybersecurity-blog/feed/"
    assert ws["E22"].font.i
    assert ws["D22"].alignment.wrap_text
    assert ws["B22"].border.left.style == "thin" and ws["I23"].border.bottom.style == "thin"
    # blok tanda tangan turun 2 baris: label 30, nama 38, jabatan 39
    assert ws["E30"].value == "Disusun Oleh" and ws["G30"].value == "Disetujui Oleh"
    # tinggi baris label di templat (19, baris 28) ikut turun; insert_rows tidak memindahkannya
    assert ws.row_dimensions[30].height == 19.0 and ws.row_dimensions[28].height is None
    assert all(ws[c].value in (None, "") for c in ("E38", "G38", "E39", "G39"))
    merged = {str(r) for r in ws.merged_cells.ranges}
    assert {"E30:F30", "G30:H30", "E38:F38", "G38:H38", "E39:F39", "G39:H39"} <= merged


def test_template_and_report_carry_no_review_comments() -> None:
    # Templat user membawa komentar review Excel yang sudah selesai; komentar ikut tercetak di tiap
    # laporan dan (setelah legenda digeser) menempel di sel yang salah, jadi semuanya dibuang.
    template = resources.files("cti_worker.reports").joinpath(
        "templates/feeds_logbook_template.xlsx"
    )
    with resources.as_file(template) as path:
        sheets = [load(path.read_bytes())]
    sheets.append(load(build([ROW_A], start=date(2026, 10, 1), end=date(2026, 10, 31))))

    for ws in sheets:
        assert [c.coordinate for row in ws.iter_rows() for c in row if c.comment] == []


def test_missing_dates_render_as_dash() -> None:
    row = replace(ROW_A, added=None, last_update=None)
    ws = load(build([row], start=date(2026, 10, 1), end=date(2026, 10, 31)))

    assert ws["C22"].value == "-" and ws["H22"].value == "-"


def test_filename_and_caption() -> None:
    assert filename_for(date(2026, 10, 31)) == "Logbook Threat Information Feeds 2026-10-31.xlsx"
    assert caption(date(2026, 10, 1), date(2026, 10, 31)) == (
        "\n    === <b>THREAT INFORMATION FEEDS REPORT</b> ===\n"
        "<b>Start Entry Date</b>: 01 Oktober 2026\n<b>End Entry Date</b>: 31 Oktober 2026"
    )
