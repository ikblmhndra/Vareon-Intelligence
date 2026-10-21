"""`cti_enrich.stages.fetch_text` -- halaman blokir WAF BUKAN isi artikel.

Kejadian nyata (e2e staging Fase 10): Arctic Wolf ngeblok fetch kita (403 dari
Wordfence). Playwright `goto` gak raise di 403 dan `page.content()` ngembaliin
halaman blokirnya; trafilatura ngekstrak teksnya; pipeline nganggap itu artikel
-> ringkasan "If you believe Wordfence should be allowing you access..." ->
LLM njawab prosa "saya gak lihat ringkasan artikelnya" -> JSON gagal -> artikel
hilang. Sekarang: teks blokir dibuang, artikel lanjut title-only.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cti_enrich.stages import fetch_text as ft

WORDFENCE = (
    "403 Forbidden\nWHAT? Why am I seeing this?\nYour access to this site was blocked by "
    "Wordfence, a security provider, who protects sites from malicious activity.\n"
    "If you believe Wordfence should be allowing you access to this site, please let "
    "them know using the steps below so they can investigate why this is happening."
)  # persis yang kejadian di produksi (597 karakter)


@pytest.mark.parametrize(
    "text",
    [
        WORDFENCE,
        "Just a moment...\nEnable JavaScript and cookies to continue",
        "Attention Required! | Cloudflare\nPlease enable cookies. You have been blocked.",
        "Access Denied\nYou don't have permission to access this resource.",
    ],
)
def test_block_pages_are_recognised(text: str) -> None:
    assert ft.looks_blocked(text)


def test_a_real_long_article_mentioning_access_denied_is_not_flagged() -> None:
    article = "Attackers received an 'access denied' error when probing the server. " * 60
    assert len(article) > 1500

    assert not ft.looks_blocked(article)


def test_short_genuine_text_without_markers_is_not_flagged() -> None:
    assert not ft.looks_blocked("Patch Tuesday fixes 12 critical flaws in Windows and Office.")
    assert not ft.looks_blocked("")


def _fake_playwright(status: int, html: str):
    class _Page:
        def set_extra_http_headers(self, _h: object) -> None: ...

        def goto(self, _url: str, timeout: int) -> SimpleNamespace:
            return SimpleNamespace(status=status)

        def content(self) -> str:
            return html

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None: ...

    class _Ctx:
        chromium = SimpleNamespace(launch=lambda **_k: _Browser())

        def __enter__(self) -> _Ctx:
            return self

        def __exit__(self, *_a: object) -> None: ...

    return lambda: _Ctx()


def test_rendered_fetch_returns_nothing_on_http_error_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ft, "sync_playwright", _fake_playwright(403, "<html>blocked</html>"))

    assert ft._fetch_rendered_html("https://x.test/a") == ""


def test_rendered_fetch_keeps_content_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft, "sync_playwright", _fake_playwright(200, "<html>ok</html>"))

    assert ft._fetch_rendered_html("https://x.test/a") == "<html>ok</html>"


def test_fetch_text_drops_a_block_page_from_either_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # jalur cepat: trafilatura "berhasil" ngambil, tapi isinya halaman blokir
    monkeypatch.setattr(ft.trafilatura, "fetch_url", lambda *_a, **_k: "<html>x</html>")
    monkeypatch.setattr(ft.trafilatura, "extract", lambda *_a, **_k: WORDFENCE)
    # jalur render juga dapat halaman blokir (status 200 tapi challenge WAF)
    monkeypatch.setattr(ft, "_fetch_rendered_html", lambda _u: "<html>challenge</html>")

    assert ft.fetch_text("https://93.184.216.34/report") == ""  # IP publik: guard URL tanpa DNS


def test_fetch_text_returns_real_article_text(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "Ransomware operators exploited a VPN flaw to breach the hospital. " * 30
    monkeypatch.setattr(ft.trafilatura, "fetch_url", lambda *_a, **_k: "<html>x</html>")
    monkeypatch.setattr(ft.trafilatura, "extract", lambda *_a, **_k: body)

    assert ft.fetch_text("https://93.184.216.34/a") == body
