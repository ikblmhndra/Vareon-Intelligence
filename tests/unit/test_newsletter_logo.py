"""Logo newsletter: berkasnya, ikut terbawa ke image, dan pemetaan `cid:` -- ROADMAP #22.

`services/newsletter_logo.py` membaca `templates/newsletter_logo.png` dari dalam paket `cti_api`.
Di image API, paket itu di-install NON-editable dari wheel (`docker/api.Dockerfile`), jadi berkas
yang tidak ikut wheel = `FileNotFoundError` di produksi padahal jalan di laptop. Test paket di
bawah menjaga rantainya: berkas ada di dalam paket, hatchling mengemas seluruh paket,
`.dockerignore` tidak membuangnya, dan Dockerfile menyalin `apps/api`. (Isi wheel yang sebenarnya
diperiksa dengan `uv build --package cti-api --wheel` saat PR ini dibuat.)"""

from __future__ import annotations

import base64
import fnmatch
import re
import struct
import tomllib
from pathlib import Path

import pytest
from cti_alerts.mailer import InlineImage
from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_logo
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
DISPLAY_HEIGHT = 28
"""Tinggi tampil di template (`height="28"`); berkasnya disimpan 2x untuk layar retina."""


def _png_size(data: bytes) -> tuple[int, int]:
    """(lebar, tinggi) dari header IHDR."""
    return struct.unpack(">II", data[16:24])


# ── Berkasnya ────────────────────────────────────────────────────────────────


def test_the_logo_is_a_small_transparent_png_at_twice_the_display_height() -> None:
    data = newsletter_logo.LOGO_PATH.read_bytes()

    assert data.startswith(PNG_MAGIC)
    width, height = _png_size(data)
    assert height == 2 * DISPLAY_HEIGHT
    assert width / height == pytest.approx(2115 / 561, abs=0.02)  # rasio aslinya
    assert len(data) < 20 * 1024  # lampiran inline tetap kecil; aslinya ~60 KB dan 2115x561

    with Image.open(newsletter_logo.LOGO_PATH) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0  # latar transparan: duduk langsung di header burgundy


def test_the_template_displays_the_logo_at_the_size_the_file_was_scaled_for() -> None:
    template = (newsletter_logo.LOGO_PATH.parent / "newsletter_email.html").read_text()
    width, height = _png_size(newsletter_logo.LOGO_PATH.read_bytes())

    assert f'height="{DISPLAY_HEIGHT}"' in template
    assert f'width="{round(width / 2)}"' in template  # lebar tampil = setengah ukuran berkas
    assert height == 2 * DISPLAY_HEIGHT


# ── Ikut terbawa ke image ────────────────────────────────────────────────────


def test_the_logo_lives_inside_the_cti_api_package() -> None:
    package = ROOT / "apps" / "api" / "src" / "cti_api"

    assert newsletter_logo.LOGO_PATH.is_file()
    assert package in newsletter_logo.LOGO_PATH.resolve().parents


def test_the_wheel_packages_the_whole_cti_api_directory() -> None:
    """Hatchling mengemas semua berkas di dalam `packages` (bukan hanya `.py`), selama tidak ada
    `exclude`/`only-include` yang membuangnya. Template HTML sudah bergantung pada hal yang sama."""
    pyproject = tomllib.loads((ROOT / "apps" / "api" / "pyproject.toml").read_text())
    wheel = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel["packages"] == ["src/cti_api"]
    assert not {"exclude", "only-include", "include"} & set(wheel)
    assert "exclude" not in pyproject["tool"]["hatch"]["build"]


def _dockerignore_patterns() -> list[str]:
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _ignored(path: str, patterns: list[str]) -> bool:
    """Perkiraan aturan `.dockerignore`: pola cocok dengan path atau salah satu direktori
    induknya; `!` membatalkan. `fnmatch` mencocokkan `*` melewati `/` (lebih longgar dari
    Docker), jadi perkiraan ini hanya bisa berlebihan menyatakan "dibuang", tidak pernah
    sebaliknya."""
    parts = path.split("/")
    prefixes = ["/".join(parts[: i + 1]) for i in range(len(parts))]
    ignored = False
    for raw in patterns:
        negate = raw.startswith("!")
        pattern = (raw[1:] if negate else raw).rstrip("/")
        candidates = [pattern[3:], pattern] if pattern.startswith("**/") else [pattern]
        if any(fnmatch.fnmatchcase(prefix, c) for prefix in prefixes for c in candidates):
            ignored = not negate
    return ignored


def test_dockerignore_does_not_drop_the_logo_but_does_drop_what_it_should() -> None:
    patterns = _dockerignore_patterns()
    logo = "apps/api/src/cti_api/templates/newsletter_logo.png"

    assert not _ignored(logo, patterns)
    # Penjaga pencocokan di atas sendiri: yang memang dibuang harus tertangkap.
    assert _ignored("docs/mockups/newsletter-redesign.html", patterns)
    assert _ignored(".env", patterns)
    assert _ignored("tests/unit/test_newsletter_logo.py", patterns)


def test_the_api_image_copies_the_api_sources_into_the_wheel_build() -> None:
    dockerfile = (ROOT / "docker" / "api.Dockerfile").read_text()

    assert re.search(r"^COPY apps/api apps/api$", dockerfile, re.M)
    assert "--no-editable --package cti-api" in dockerfile  # dipasang dari wheel, bukan dari /app


# ── Pemetaan cid: ────────────────────────────────────────────────────────────


def test_the_logo_attachment_carries_the_content_id_and_the_file_bytes() -> None:
    image = newsletter_logo.logo_image()

    assert isinstance(image, InlineImage)
    assert image.content_id == newsletter_logo.LOGO_CONTENT_ID == "newsletter-logo"
    assert image.content_type == "image/png"
    assert image.data == newsletter_logo.LOGO_PATH.read_bytes()
    assert image.name == "logo.png"


def test_only_html_that_references_the_logo_gets_the_attachment() -> None:
    new = '<img src="cid:newsletter-logo" alt="x">'

    assert newsletter_logo.inline_images_for(new) == [newsletter_logo.logo_image()]
    # Baris histori lama (dibuat sebelum ada logo) tidak boleh menempelkan lampiran yatim.
    assert newsletter_logo.inline_images_for("<html>edisi lama tanpa logo</html>") == []
    assert newsletter_logo.inline_images_for("") == []


def test_data_uris_replace_cid_with_the_exact_logo_bytes() -> None:
    html = '<p>a</p><img src="cid:newsletter-logo" alt="x"><p>b</p>'

    shown = newsletter_logo.with_data_uris(html)

    assert "cid:" not in shown
    [encoded] = re.findall(r'src="data:image/png;base64,([^"]+)"', shown)
    assert base64.b64decode(encoded) == newsletter_logo.LOGO_PATH.read_bytes()
    assert shown.startswith("<p>a</p>") and shown.endswith("<p>b</p>")


def test_html_without_the_logo_is_returned_unchanged_so_old_history_rows_still_open() -> None:
    old = "<html><body>Edisi lama, tanpa gambar.</body></html>"

    assert newsletter_logo.with_data_uris(old) == old


def test_the_stored_version_is_smaller_than_the_displayed_one_which_is_what_size_checks_use() -> (
    None
):
    html = '<img src="cid:newsletter-logo">'
    shown = newsletter_logo.with_data_uris(html)

    assert newsletter_service.html_size_bytes(html) < newsletter_service.html_size_bytes(shown)
