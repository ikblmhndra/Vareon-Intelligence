"""`tools/ops/backfill_cve_published_at.py` -- isi `cve_tracker.published_at` untuk CVE lama.

Yang dikunci: tidak pernah bertindak tanpa bukti (MITRE gagal / 404 / tanpa jam), tidak pernah
menulis kalau tanggal MITRE beda dengan `published` yang tersimpan, dan jam dibaca sebagai UTC."""

from __future__ import annotations

import datetime

import httpx

from tools.ops.backfill_cve_published_at import Row, fetch_published_at, plan, render

UTC = datetime.UTC


def row(cve_id: str, published: datetime.date | None = datetime.date(2026, 8, 31)) -> Row:
    return Row(id=1, cve_id=cve_id, client_id="acme", published=published)


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def record(date_published: str | None) -> dict:
    return {"cveMetadata": {"datePublished": date_published} if date_published else {}}


# ── fetch_published_at ────────────────────────────────────────────────────────


def test_fetch_reads_the_full_publish_time_as_utc() -> None:
    http = client(lambda r: httpx.Response(200, json=record("2026-08-31T13:53:00.000Z")))

    assert fetch_published_at(http, "CVE-1") == datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)


def test_fetch_gives_none_for_a_date_without_time_instead_of_guessing() -> None:
    http = client(lambda r: httpx.Response(200, json=record("2026-08-31")))

    assert fetch_published_at(http, "CVE-1") is None


def test_fetch_gives_none_when_the_record_has_no_publish_date() -> None:
    assert fetch_published_at(client(lambda r: httpx.Response(200, json={})), "CVE-1") is None


def test_fetch_gives_none_on_404_without_retrying() -> None:
    calls: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(str(r.url))
        return httpx.Response(404)

    assert fetch_published_at(client(handler), "CVE-1", sleep=lambda _s: None) is None
    assert len(calls) == 1


def test_fetch_gives_none_when_the_body_is_not_json() -> None:
    http = client(lambda r: httpx.Response(200, content=b"<html>bukan json</html>"))

    assert fetch_published_at(http, "CVE-1") is None


def test_fetch_retries_transient_errors_then_succeeds() -> None:
    answers = iter(
        [
            httpx.Response(503),
            httpx.Response(429),
            httpx.Response(200, json=record("2026-08-31T01:02:03Z")),
        ]
    )
    slept: list[float] = []

    got = fetch_published_at(client(lambda r: next(answers)), "CVE-1", sleep=slept.append)

    assert got == datetime.datetime(2026, 8, 31, 1, 2, 3, tzinfo=UTC)
    assert slept == [5.0, 10.0]  # backoff eksponensial


def test_fetch_gives_up_with_none_after_all_retries() -> None:
    slept: list[float] = []

    got = fetch_published_at(client(lambda r: httpx.Response(500)), "CVE-1", sleep=slept.append)

    assert got is None and len(slept) == 3


def test_fetch_survives_a_dropped_connection() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("putus")

    assert fetch_published_at(client(handler), "CVE-1", sleep=lambda _s: None) is None


# ── plan ──────────────────────────────────────────────────────────────────────

AT = datetime.datetime(2026, 8, 31, 13, 53, tzinfo=UTC)


def test_a_row_whose_mitre_date_matches_is_filled() -> None:
    result = plan([row("CVE-1")], {"CVE-1": AT})

    assert [(f.action, f.published_at) for f in result.findings] == [("fill", AT)]
    assert result.unverified == 0


def test_a_row_without_a_stored_date_is_filled_too() -> None:
    assert [f.action for f in plan([row("CVE-1", published=None)], {"CVE-1": AT}).findings] == [
        "fill"
    ]


def test_a_different_mitre_date_is_reported_never_filled() -> None:
    result = plan([row("CVE-1", datetime.date(2026, 8, 30))], {"CVE-1": AT})

    assert [f.action for f in result.findings] == ["mismatch"]


def test_unverified_when_mitre_gave_nothing() -> None:
    result = plan([row("CVE-1"), row("CVE-2")], {"CVE-1": None})

    assert result.findings == [] and result.unverified == 2  # CVE-2 tidak ada di hasil fetch


def test_one_fetch_serves_every_client_row_of_the_same_cve() -> None:
    rows = [row("CVE-1"), Row(id=2, cve_id="CVE-1", client_id="globex", published=AT.date())]

    assert [f.action for f in plan(rows, {"CVE-1": AT}).findings] == ["fill", "fill"]


def test_render_shows_both_dates_for_a_mismatch() -> None:
    f = plan([row("CVE-1", datetime.date(2026, 8, 30))], {"CVE-1": AT}).findings[0]

    line = render(f)

    assert "MISMATCH" in line and "2026-08-30" in line and "2026-08-31T13:53:00+00:00" in line
