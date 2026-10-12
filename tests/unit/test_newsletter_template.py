"""Template email newsletter (`templates/newsletter_email.html`) -- ROADMAP #22, PR template.

Tiga lapis:
1. ATURAN KLIEN EMAIL pada sumber template dan hasil render: Outlook desktop memakai mesin Word,
   yang tidak mengenal flex, grid, gradient, atau CSS eksternal. Tidak ada klien email di
   lingkungan ini, jadi aturan inilah satu-satunya penjaga sampai tangkapan layar analis ada.
2. ISI: judul bagian Inggris, urutan bagian, kartu penuh + "Also Noted", Executive Summary dari
   `custom_intro`, logo `cid:`, catatan analis, escape, dan bagian kosong tidak tampil.
3. SNAPSHOT HTML dari konteks tetap (`newsletter_sample`), supaya perubahan template terlihat
   sebagai diff HTML di review. Snapshot-nya berkas `.html` biasa di `__snapshots__/`.

Render di browser sungguhan (lebar 640 dan 390) ada di `test_newsletter_template_browser.py`."""

from __future__ import annotations

import datetime
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

import pytest
from cti_api.schemas.newsletter import (
    MAX_COMPACT_PER_SECTION,
    MAX_FULL_PER_SECTION,
    MAX_HIGHLIGHTS,
)
from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_edition as edition
from syrupy.assertion import SnapshotAssertion
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

from tests.unit.newsletter_sample import card, row, sample_context

EN_DASH = "\N{EN DASH}"
"""Pemisah rentang di header; konstanta karena ruff (RUF001) menandai EN DASH literal."""

TEMPLATES = Path(newsletter_service.__file__).resolve().parent.parent / "templates"
TEMPLATE = TEMPLATES / "newsletter_email.html"

FORBIDDEN = (
    "display:flex",
    "display:inline-flex",
    "display:grid",
    "display:inline-grid",
    "gradient",
    "<link",
    "@import",
    "stylesheet",
    "<script",
)
"""Tidak dikenal mesin Word (atau diblokir klien): layout modern, gradient, dan CSS/JS eksternal."""


class HtmlSnapshot(SingleFileSnapshotExtension):
    """Snapshot sebagai berkas `.html` apa adanya (bukan format amber), supaya golden-nya bisa
    dibuka di browser dan diff-nya terbaca sebagai HTML."""

    file_extension = "html"
    _write_mode = WriteMode.TEXT


def _render(**overrides: Any) -> str:
    return newsletter_service.render_newsletter_html(sample_context(**overrides))


def _squash(text: str) -> str:
    """Huruf kecil tanpa spasi apa pun: `display: flex` dan `DISPLAY:FLEX` ikut tertangkap."""
    return re.sub(r"\s+", "", text.lower())


def _section_labels(html: str) -> list[str]:
    return re.findall(r'class="section-name"[^>]*>([^<]+)<', html)


# ── 1. Aturan klien email ────────────────────────────────────────────────────


def test_template_source_uses_no_construct_outlook_desktop_cannot_render() -> None:
    source = _squash(TEMPLATE.read_text(encoding="utf-8"))

    for needle in FORBIDDEN:
        assert needle not in source, f"template memuat `{needle}`"


def test_rendered_html_uses_none_of_them_either() -> None:
    """Termasuk yang masuk lewat konteks bawaan (bukan `custom_css` ketikan analis, yang boleh
    apa saja dan tanggung jawab analis)."""
    html = _squash(_render())

    for needle in FORBIDDEN:
        assert needle not in html, f"hasil render memuat `{needle}`"


def test_newsletter_template_stands_alone_and_the_cve_email_still_extends_the_shared_base() -> None:
    """Template newsletter berhenti memakai `_base_email.html` supaya email CVE tidak ikut berubah;
    email CVE tetap memakainya, dan basis bersama itu masih ada."""
    extends = re.compile(r"\{%-?\s*extends\b")

    assert not extends.search(TEMPLATE.read_text(encoding="utf-8"))
    assert (TEMPLATES / "_base_email.html").is_file()
    assert extends.search((TEMPLATES / "cve_notification_email.html").read_text(encoding="utf-8"))


def test_every_table_is_presentational_and_the_logo_has_explicit_dimensions() -> None:
    """`role="presentation"` supaya pembaca layar tidak membacakan layout sebagai tabel data;
    gambar dengan atribut `width`/`height` karena Outlook desktop mengabaikan CSS ukuran gambar."""
    html = _render()

    tables = re.findall(r"<table\b[^>]*>", html)
    assert tables
    assert all('role="presentation"' in t for t in tables)
    [img] = re.findall(r"<img\b[^>]*>", html)
    for attribute in ('alt="', 'width="106"', 'height="28"', 'src="cid:newsletter-logo"'):
        assert attribute in img


def test_the_container_is_fluid_for_browsers_and_fixed_640_for_the_word_engine() -> None:
    """Fixed 640px + padding luar membuat halaman meluber di lebar 481-663px. Browser memakai
    `width:100%;max-width:640px`; Outlook desktop mengabaikan `max-width`, jadi ia mendapat tabel
    640px dari komentar kondisional `[if mso]`."""
    html = _render()

    assert 'style="width:100%;max-width:640px;"' in html
    assert '<!--[if mso]><table role="presentation" align="center" width="640"' in html
    assert "<!--[if mso]></td></tr></table><![endif]-->" in html
    assert "@media only screen and (max-width: 480px)" in html  # ditumpuk di bawah 480px


def test_the_preheader_is_hidden_and_summarises_the_edition() -> None:
    html = _render()

    [preheader] = re.findall(r'<div style="display:none;[^"]*">([^<]*)</div>', html)
    assert "mso-hide:all" in html
    assert preheader.startswith("October 2026: Kelompok ransomware contoh menargetkan")


def test_a_very_long_preheader_is_cut_to_what_inboxes_show() -> None:
    title = "Judul sangat panjang " * 20
    html = _render(highlights=[card(1, title, "S", 1, "T")])

    [preheader] = re.findall(r'<div style="display:none;[^"]*">([^<]*)</div>', html)
    assert len(preheader) <= 141
    assert preheader.endswith("…")


class _Nesting(HTMLParser):
    """Mencatat tag yang ditutup tidak pada tempatnya atau tidak pernah ditutup."""

    _VOID: ClassVar[frozenset[str]] = frozenset({"meta", "img", "br", "hr", "input", "link"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag not in self._VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
            return
        self.errors.append(f"</{tag}> tanpa pasangan (atas stack: {self.stack[-1:]})")
        if tag in self.stack:
            del self.stack[len(self.stack) - self.stack[::-1].index(tag) - 1 :]


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "custom_intro": "",
            "campaign_clusters": [],
            "apac_compact": [],
            "global_news_compact": [],
        },
        {"apac": [], "global_news": [], "indonesia": [], "campaign_clusters": []},
        {"custom_footer": "<p>Footer analis</p>", "custom_css": "a { color: red; }"},
    ],
    ids=[
        "lengkap",
        "tanpa-intro-kampanye-compact",
        "hanya-highlight-dan-compact",
        "footer-dan-css",
    ],
)
def test_rendered_html_is_well_nested_so_the_word_engine_has_nothing_to_guess(
    overrides: dict[str, Any],
) -> None:
    """Browser menebak tag yang hilang dan hasilnya tetap rapi; mesin Word di Outlook desktop
    lebih kaku. Setiap tag dibuka dan ditutup berpasangan, di semua bentuk edisi."""
    parser = _Nesting()
    parser.feed(_render(**overrides))
    parser.close()

    assert parser.errors == []
    assert parser.stack == []


# ── 2. Isi ───────────────────────────────────────────────────────────────────


def test_sections_come_in_the_agreed_order_with_english_headings() -> None:
    html = _render()

    assert _section_labels(html) == [
        "Highlights",
        "Asia Pacific",
        "Global",
        "Indonesia",
        "Campaigns",
    ]
    positions = [html.index(text) for text in ("Executive Summary", "Highlights", "Campaigns")]
    assert positions == sorted(positions)
    assert html.count("Also Noted") == 2  # APAC dan Global; Indonesia tanpa baris compact


def test_the_header_names_the_month_and_range_instead_of_the_iso_week() -> None:
    html = _render()

    assert "October 2026 Edition" in html
    assert f"Period 1 {EN_DASH} 31 October 2026" in html
    assert "Published Monday, 2 November 2026" in html
    assert "Threat Intelligence Newsletter" in html
    assert "Week" not in html  # tidak ada "Week 45" di judul, header, maupun footer
    assert (
        "<title>Vareon Intelligence | Threat Intelligence Newsletter, October 2026</title>" in html
    )


def test_a_custom_period_shows_both_months_in_the_label_and_range() -> None:
    start, end = datetime.date(2026, 9, 28), datetime.date(2026, 10, 4)
    html = _render(
        period_label=edition.period_label(start, end), period_range=edition.period_range(start, end)
    )

    assert "September - October 2026 Edition" in html
    assert f"Period 28 September {EN_DASH} 4 October 2026" in html


def test_the_logo_is_referenced_by_cid_and_nothing_is_embedded() -> None:
    html = _render()

    assert html.count("cid:newsletter-logo") == 1
    assert "data:" not in html


def test_the_executive_summary_is_the_intro_field_rendered_as_typed() -> None:
    html = _render(custom_intro="<p>Ringkasan <b>analis</b>.</p>")

    assert "Executive Summary" in html
    assert "<p>Ringkasan <b>analis</b>.</p>" in html  # HTML analis tidak di-escape (seperti dulu)


def test_without_an_intro_there_is_no_executive_summary_block() -> None:
    html = _render(custom_intro="")

    assert "Executive Summary" not in html


def test_every_highlight_gets_its_own_dark_card() -> None:
    second = card(6, "Highlight kedua", "Sumber", 3, "Phishing", summary="Ringkasan kedua.")
    third = card(7, "Highlight ketiga", "Sumber", 4, "Malware")
    html = _render(highlights=[sample_context()["highlight"], second, third])

    assert html.count('class="highlight-card"') == 3
    assert "Highlight kedua" in html and "Highlight ketiga" in html


def test_full_cards_and_compact_rows_render_different_amounts_of_detail() -> None:
    html = _render()

    # Kartu penuh: poin kunci + ringkasan + tag.
    assert "Email berisi tautan ke halaman login palsu portal pajak." in html
    assert "Kampanye ini memakai kit phishing yang sama" in html
    # Baris compact: judul, sumber, tanggal, tipe -- tanpa ringkasan.
    assert "Peretas menargetkan penyedia telekomunikasi regional" in html
    assert "Contoh Sumber F &nbsp;·&nbsp; 22 Oct 2026 &nbsp;·&nbsp; Intrusion" in html


def test_a_compact_row_never_shows_a_cached_summary() -> None:
    cached = {**row(20, "Artikel compact", "Sumber", 5, "Riset"), "summary": "RINGKASAN-CACHE"}
    cached["key_points"] = ["POIN-CACHE"]
    html = _render(apac_compact=[cached])

    assert "Artikel compact" in html
    assert "RINGKASAN-CACHE" not in html and "POIN-CACHE" not in html


def test_a_section_with_only_compact_rows_still_renders_its_heading_and_list() -> None:
    html = _render(global_news=[], global_news_compact=[row(30, "Hanya baris", "S", 2, "Riset")])

    assert "Global" in _section_labels(html)
    assert "Also Noted &nbsp;·&nbsp; Global" in html
    assert "Hanya baris" in html


def test_an_empty_section_is_not_rendered_at_all() -> None:
    html = _render(indonesia=[], indonesia_compact=[], campaign_clusters=[])

    assert _section_labels(html) == ["Highlights", "Asia Pacific", "Global"]
    assert "Campaigns" not in html


def test_titles_are_escaped_and_only_http_links_survive() -> None:
    evil = card(8, "<script>alert(1)</script> & kawan", "S", 1, "T")
    evil["url"] = "javascript:alert(1)"
    html = _render(apac=[evil])

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; kawan" in html
    assert 'href="javascript:' not in html


def test_analyst_notes_keep_their_line_breaks_and_are_escaped() -> None:
    html = _render()  # highlight punya catatan dua baris

    assert "Periksa akun layanan pihak ketiga di VPN kita.<br>Baris kedua catatan." in html
    assert "Analyst Note" in html

    hostile = card(9, "A", "S", 1, "T", note="<b>tebal</b>\nbaris")
    html = _render(apac=[hostile])
    assert "&lt;b&gt;tebal&lt;/b&gt;<br>baris" in html


def test_tags_show_countries_industries_and_cves_and_actors_only_on_highlights() -> None:
    plain = card(
        10, "Kartu biasa", "S", 1, "T", countries=("ID",), actors=("APT-X",), cves=("CVE-1",)
    )
    html = _render(apac=[plain])

    assert ">Contoh Group<" in html  # aktor di kartu highlight
    assert ">APT-X<" not in html  # aktor di kartu biasa tidak ditampilkan (seperti template lama)
    assert ">CVE-1<" in html and ">ID<" in html


def test_dates_are_shown_short_and_a_missing_date_leaves_no_dangling_separator() -> None:
    html = _render(apac=[card(11, "Tanpa tanggal", "SumberX", 1, "Riset")])
    assert "SumberX &nbsp;·&nbsp; 1 Oct 2026" in html

    undated = card(12, "Tanpa tanggal", "SumberY", 1, "")
    undated["posted_on"] = ""
    html = _render(apac=[undated])
    assert ">SumberY<" in html  # baris meta hanya sumber, tanpa pemisah yatim


def test_the_campaign_block_keeps_its_clusters_and_formats_the_dates() -> None:
    html = _render()

    assert "Ransomware terhadap penyedia layanan terkelola" in html
    assert "31 articles" in html
    assert "6 Oct 2026 &ndash; 27 Oct 2026" in html
    for chip in ("Contoh Group", "T1486", "T1078", "CVE-2026-00000"):
        assert chip in html


def test_custom_css_footer_and_language_are_honoured() -> None:
    html = _render(
        custom_css=".header { background: #1a1a1a !important; }",
        custom_footer="<p>CTI Team &middot; Rahasia</p>",
        language="en",
    )

    assert "<style>.header { background: #1a1a1a !important; }</style>" in html
    assert "<p>CTI Team &middot; Rahasia</p>" in html
    assert "Internal &mdash; Confidential" not in html  # footer ketikan analis menggantikan bawaan
    assert '<html lang="en"' in html
    assert '<html lang="id"' in _render()


def test_the_default_footer_names_the_platform_edition_and_range() -> None:
    html = _render()

    assert "Vareon Intelligence</strong>" in html
    assert f"October 2026 Edition &nbsp;·&nbsp; 1 {EN_DASH} 31 October 2026" in html
    assert "Internal &mdash; Confidential" in html


def test_old_style_contexts_with_only_the_first_highlight_still_render() -> None:
    """Konteks tanpa kunci periode (mis. yang dibangun alat lain) tidak boleh menjatuhkan render:
    bagian yang datanya tidak ada dilewati, bukan error."""
    context = sample_context()
    for key in ("period_range", "published_label"):
        del context[key]

    html = newsletter_service.render_newsletter_html(context)

    assert "Period " not in html
    assert "Threat Intelligence Newsletter" in html


# ── Ukuran (Gmail memotong ~102 KB) ──────────────────────────────────────────


def _dense_edition(*, tags: int, notes: bool) -> dict[str, Any]:
    """Edisi terpadat yang diizinkan batas tier: 3 highlight, 4 kartu penuh dan 15 baris compact
    per bagian, 5 klaster. Teks sepanjang yang diminta prompt (tiga poin sekitar 20 kata, ringkasan
    sekitar 80 kata). `tags` = jumlah tag per kartu (maks 7: tiga negara, dua industri, dua CVE),
    `notes` = catatan analis di SETIAP kartu (bukan hanya highlight)."""
    words = "serangan siber menargetkan organisasi pemerintah melalui kerentanan perangkat jaringan"
    countries = ("Indonesia", "Singapura", "Australia")
    industries = ("Pemerintahan", "Layanan Keuangan")
    cves = ("CVE-2026-11111", "CVE-2026-22222")

    def full(i: int) -> dict[str, Any]:
        return card(
            i,
            f"Judul artikel nomor {i}: kelompok peretas menargetkan penyedia layanan di kawasan",
            "Contoh Sumber Panjang",
            1 + i % 28,
            "Data Breach Article",
            key_points=tuple(f"{words} {words[:40]}" for _ in range(3)),
            summary=" ".join([words] * 8),
            countries=countries[: min(tags, 3)],
            industries=industries[: max(0, min(tags - 3, 2))],
            cves=cves[: max(0, tags - 5)],
            note="Catatan analis yang cukup panjang untuk satu kartu." if notes else "",
        )

    def compact(i: int) -> dict[str, Any]:
        title = f"Judul baris compact {i}: laporan insiden siber di kawasan Asia"
        return row(i, title, "Sumber", 1 + i % 28, "Riset")

    return sample_context(
        highlights=[full(i) for i in range(MAX_HIGHLIGHTS)],
        apac=[full(100 + i) for i in range(MAX_FULL_PER_SECTION)],
        global_news=[full(200 + i) for i in range(MAX_FULL_PER_SECTION)],
        indonesia=[full(300 + i) for i in range(MAX_FULL_PER_SECTION)],
        apac_compact=[compact(400 + i) for i in range(MAX_COMPACT_PER_SECTION)],
        global_news_compact=[compact(500 + i) for i in range(MAX_COMPACT_PER_SECTION)],
        indonesia_compact=[compact(600 + i) for i in range(MAX_COMPACT_PER_SECTION)],
        campaign_clusters=[sample_context()["campaign_clusters"][0]] * 5,
    )


def test_a_full_edition_at_the_tier_limits_with_normal_tags_has_no_size_warning() -> None:
    """Batas tier dan template harus cocok: edisi penuh yang NORMAL (empat tag per kartu, tanpa
    catatan di tiap kartu) tidak boleh sudah memicu peringatan, atau analis tak punya ruang sama
    sekali. Gagal kalau template makin berat atau batas tier dinaikkan tanpa melihat ukurannya."""
    html = newsletter_service.render_newsletter_html(_dense_edition(tags=4, notes=False))

    size = newsletter_service.html_size_bytes(html)
    assert size < newsletter_service.HTML_WARN_BYTES, f"{size} byte"
    assert newsletter_service.size_warning(size) is None


def test_even_the_heaviest_edition_the_tier_limits_allow_fits_under_the_gmail_clip() -> None:
    """Terberat: tujuh tag dan catatan analis di semua kartu. Boleh memicu PERINGATAN (itulah
    gunanya), tapi batas tier sendiri tidak boleh menghasilkan email yang dipotong Gmail."""
    html = newsletter_service.render_newsletter_html(_dense_edition(tags=7, notes=True))

    size = newsletter_service.html_size_bytes(html)
    assert size < newsletter_service.GMAIL_CLIP_BYTES, f"{size} byte"


def test_size_is_counted_in_utf8_bytes_not_characters() -> None:
    assert newsletter_service.html_size_bytes("abc") == 3
    assert newsletter_service.html_size_bytes(EN_DASH) == 3  # en dash = 3 byte
    assert newsletter_service.html_size_bytes("\U0001f1ee\U0001f1e9") == 8


def test_the_size_warning_starts_above_90_kb_and_names_the_gmail_limit() -> None:
    limit = newsletter_service.HTML_WARN_BYTES
    assert limit == 90 * 1024
    assert newsletter_service.GMAIL_CLIP_BYTES == 102 * 1024

    assert newsletter_service.size_warning(0) is None
    assert newsletter_service.size_warning(limit) is None  # tepat di batas belum "di atas"
    warning = newsletter_service.size_warning(limit + 1)
    assert warning is not None
    assert "90 KB" in warning and "102 KB" in warning and "Gmail" in warning
    assert "Also Noted" in warning  # petunjuk apa yang bisa dilakukan analis


# ── 3. Snapshot HTML ─────────────────────────────────────────────────────────


def test_rendered_html_snapshot(snapshot: SnapshotAssertion) -> None:
    """Konteks tetap -> HTML tetap. Diff snapshot ini = diff tampilan email; baca sebelum
    `--snapshot-update`, dan buka berkasnya di browser untuk melihat hasilnya."""
    assert _render() == snapshot(extension_class=HtmlSnapshot)


@pytest.mark.parametrize("language", ["id", "en"])
def test_rendering_is_deterministic(language: str) -> None:
    assert _render(language=language) == _render(language=language)
