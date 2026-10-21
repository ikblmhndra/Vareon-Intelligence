"""`cti_enrich.stages.fetch_text` -- hanya http(s) ke alamat publik yang boleh diambil.

Audit 2026-10-21: URL artikel datang dari feed pihak ketiga. `trafilatura.fetch_url` ternyata
mengambil `http://127.0.0.1:<port>/` begitu saja (teksnya jadi isi artikel), dan Chromium fallback
bisa membuka `file://`. IP literal dipakai di sini supaya test tidak butuh DNS."""

from __future__ import annotations

import pytest
from cti_enrich.stages import fetch_text as ft


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8765/a",
        "http://localhost/",
        "http://[::1]/",
        "http://10.8.20.78/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/hosts",
        "ftp://93.184.216.34/x",
    ],
)
def test_non_public_urls_are_never_fetched(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("URL ini tidak boleh diambil")

    monkeypatch.setattr(ft.trafilatura, "fetch_url", boom)
    monkeypatch.setattr(ft, "_fetch_rendered_html", boom)
    assert ft.fetch_text(url) == ""


def test_a_public_url_is_still_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ft.trafilatura, "fetch_url", lambda url, config: "<html>x</html>")
    monkeypatch.setattr(ft.trafilatura, "extract", lambda html: "Isi artikel.")
    assert ft.fetch_text("https://93.184.216.34/post") == "Isi artikel."
