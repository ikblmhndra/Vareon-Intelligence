"""Template newsletter di browser sungguhan (Chromium) pada tiga lebar -- ROADMAP #22.

Marker `playwright` (butuh `uv run playwright install chromium`), sama seperti
`test_golden_trendmicro`. CI memasangnya (`.github/workflows/ci.yml`), jadi di sana test ini
jalan; di laptop tanpa Chromium test di-skip, bukan gagal.

Yang dibuktikan: kontainer 640px di layar lebar, menyusut mengikuti layar di lebar menengah
(tanpa scroll horizontal), dan ditumpuk di 390px dengan padding yang diperkecil. Ini BUKAN bukti
Outlook desktop atau Gmail: itu tangkapan layar dari kotak surat analis (PR 6 di
`docs/PLAN_RECAP_NEWSLETTER.md`)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_logo

from tests.unit.newsletter_sample import sample_context

pytestmark = pytest.mark.playwright

_MEASURE = """() => {
  const rect = (el) => el.getBoundingClientRect();
  const logo = document.querySelector('img');
  const body = document.querySelector('td.body');
  return {
    viewport: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    container: Math.round(rect(document.querySelector('.container')).width),
    bodyPadding: getComputedStyle(body).paddingLeft,
    h1: getComputedStyle(document.querySelector('.h1')).fontSize,
    logo: {
      loaded: logo.complete && logo.naturalWidth > 0,
      natural: logo.naturalWidth,
      width: Math.round(rect(logo).width),
      height: Math.round(rect(logo).height),
    },
    overflowing: [...document.querySelectorAll('body *')]
      .filter((el) => rect(el).right > window.innerWidth + 0.5)
      .map((el) => el.tagName + '.' + el.className),
  };
}"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    sync_api = pytest.importorskip("playwright.sync_api", reason="butuh paket playwright")
    with sync_api.sync_playwright() as pw:
        try:
            chromium = pw.chromium.launch()
        except sync_api.Error as error:
            if "Executable doesn't exist" not in str(error):
                raise  # masalah lain (sandbox, library sistem) harus gagal, bukan di-skip diam-diam
            pytest.skip("Chromium belum terpasang: uv run playwright install chromium")
        yield chromium
        chromium.close()


@pytest.fixture(scope="module")
def displayed_html() -> str:
    """Edisi contoh seperti yang dilihat di preview: logo `cid:` sudah jadi data URI."""
    html = newsletter_service.render_newsletter_html(sample_context())
    return newsletter_logo.with_data_uris(html)


def _measure(browser: Any, html: str, width: int) -> dict[str, Any]:
    page = browser.new_page(viewport={"width": width, "height": 900})
    try:
        page.set_content(html)
        measured: dict[str, Any] = page.evaluate(_MEASURE)
        return measured
    finally:
        page.close()


@pytest.mark.parametrize(
    ("width", "container", "padding", "h1"),
    [
        (800, 640, "36px", "28px"),  # layar lebar: tepat 640px, di tengah
        (640, 616, "36px", "28px"),  # lebar menengah: menyusut (640 - 2 x 12px), tanpa scroll
        (390, 366, "18px", "22px"),  # ponsel: ditumpuk, padding dan judul diperkecil
    ],
)
def test_the_edition_fits_the_viewport_at_each_width(
    browser: Any, displayed_html: str, width: int, container: int, padding: str, h1: str
) -> None:
    m = _measure(browser, displayed_html, width)

    assert m["scrollWidth"] <= m["viewport"], f"scroll horizontal di {width}px: {m}"
    assert m["overflowing"] == []
    assert m["container"] == container
    assert m["bodyPadding"] == padding
    assert m["h1"] == h1


@pytest.mark.parametrize("width", [800, 640, 390])
def test_the_logo_is_loaded_and_shown_at_28px_high_at_every_width(
    browser: Any, displayed_html: str, width: int
) -> None:
    logo = _measure(browser, displayed_html, width)["logo"]

    assert logo["loaded"]
    # Berkas 2x untuk layar retina. Berkasnya 211 px lebar dan ditampilkan 28 px tinggi, jadi lebar
    # tampilnya 105,5 px yang dibulatkan jadi 106: selisih 1 px itu pembulatan, bukan salah ukuran.
    assert abs(logo["natural"] - 2 * logo["width"]) <= 1
    assert (logo["width"], logo["height"]) == (106, 28)
