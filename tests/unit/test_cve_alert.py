"""`cti_scraper.cve_alert.format_summary` -- ringkasan Telegram CVE baru (murni, tanpa DB).

Yang dikunci: urutan severity, batas baris, HTML di-escape (Telegram menolak pesan dengan `<`
liar), dan pesan SELALU muat di batas 4096 karakter Telegram (terlalu panjang = ditolak, alert
hilang)."""

from __future__ import annotations

import datetime

from cti_scraper.cve_alert import NewCve, format_summary

TODAY = datetime.date(2026, 10, 7)


def cve(n: int, severity: str = "HIGH", score: float | None = 7.5, **kw: object) -> NewCve:
    base: dict[str, object] = {
        "cve_id": f"CVE-2026-{n:04d}",
        "tech": "nginx",
        "severity": severity,
        "score": score,
        "published": TODAY,
        "summary": "Heap overflow di modul X",
        "link": f"https://nvd.nist.gov/vuln/detail/CVE-2026-{n:04d}",
    }
    base.update(kw)
    return NewCve(**base)  # type: ignore[arg-type]


def test_title_names_the_client_and_counts_the_cves() -> None:
    text = format_summary("Acme", [cve(1), cve(2)])

    assert "Acme" in text.splitlines()[0] and "(2)" in text.splitlines()[0]
    assert "CVE-2026-0001" in text and "CVE-2026-0002" in text


def test_worst_severity_first_then_higher_score() -> None:
    rows = [
        cve(1, "LOW", 3.1),
        cve(2, "CRITICAL", 9.8),
        cve(3, "HIGH", 8.0),
        cve(4, "HIGH", 7.0),
        cve(5, "", None),  # tanpa severity/skor (CNA tidak mengisi CVSS) -> paling bawah
    ]

    text = format_summary("Acme", rows)
    order = [text.index(f"CVE-2026-000{n}") for n in (2, 3, 4, 1, 5)]

    assert order == sorted(order)
    assert "N/A" in text  # severity kosong tampil jelas, bukan string kosong


def test_more_than_ten_rows_are_cut_with_a_remainder_line() -> None:
    text = format_summary("Acme", [cve(n) for n in range(1, 16)])

    assert text.count("<b>CVE-2026-") == 10
    assert "dan 5 lainnya" in text and "(15)" in text.splitlines()[0]


def test_external_text_is_html_escaped() -> None:
    text = format_summary(
        "A<b>cme & Co",
        [cve(1, tech="<script>", summary='x < y & "z"', link='https://e.com/?a=1&b="2"')],
    )

    assert "<script>" not in text and "&lt;script&gt;" in text
    assert "A&lt;b&gt;cme &amp; Co" in text
    assert "x &lt; y &amp;" in text
    assert 'href="https://e.com/?a=1&amp;b=&quot;2&quot;"' in text


def test_message_always_fits_the_telegram_limit() -> None:
    long = "kata " * 200
    rows = [
        cve(n, summary=long, tech="t" * 200, link="https://nvd.example/" + "p" * 250)
        for n in range(1, 30)
    ]

    text = format_summary("C" * 190, rows)

    assert len(text) < 4096
    assert "lainnya" in text  # baris yang tak muat masuk ke sisa, bukan hilang diam-diam
    assert "(29)" in text.splitlines()[0]


def test_an_absurdly_long_link_is_dropped_not_the_whole_message() -> None:
    text = format_summary("Acme", [cve(1, link="https://x.example/" + "p" * 5000)])

    assert len(text) < 4096 and "CVE-2026-0001" in text and "detail" not in text
