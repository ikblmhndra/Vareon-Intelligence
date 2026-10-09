"""Teks `affected` yang dibangun `parse_cve_record` dari `containers.cna.affected[].versions[]`.

Ditemukan di dev (2026-10-09): 46 dari 333 teks `affected` berbentuk
`mariadb-connector-nodejs: <= >= 3.3.0, < 3.5.4`. CNA seperti GitHub menulis rentangnya sendiri di
field `version` (`">= 3.3.0, < 3.5.4"`, `"< 3.2.5"`), sedangkan parser meng-awali SEMUA `version`
dengan `<=`. Hasilnya dua operator, dan teks itu ikut mengisi Affected Version di form Ticket.
Bentuk yang sudah benar (`lessThan`, `lessThanOrEqual`, versi polos) tidak boleh berubah: `new_cve`
menulis string ini ke `cve_affected` dan UI memecahnya di `": "` pertama (`parseAffected`).
"""

from __future__ import annotations

from typing import Any

import pytest
from cti_core.cve_record import parse_cve_record


def affected_of(*versions: dict[str, Any], product: str = "widget") -> list[str]:
    cna = {"affected": [{"vendor": "acme", "product": product, "versions": list(versions)}]}
    data = {"containers": {"cna": cna}}
    detail = parse_cve_record(data, cve_id="CVE-2026-1", link="L", summary="s")
    return list(detail.fields["affected"])


# ── bentuk lama: tidak boleh berubah ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        # `lessThan` menang atas `version`; batas bawah (`version`) memang tidak ikut ditulis
        ({"status": "affected", "version": "3.3.0", "lessThan": "3.5.4"}, "widget: < 3.5.4"),
        ({"status": "affected", "version": "0", "lessThan": "9.9"}, "widget: < 9.9"),
        (
            {"status": "affected", "version": "22.7R2", "lessThanOrEqual": "22.7R2.4"},
            "widget: <= 22.7R2.4",
        ),
        # versi polos tanpa operator: perilaku lama `<= X`
        ({"status": "affected", "version": "1.12.0"}, "widget: <= 1.12.0"),
        ({"status": "affected", "version": "0"}, "widget: <= 0"),
        ({"status": "affected", "version": "v2.0.1-rc.1"}, "widget: <= v2.0.1-rc.1"),
        ({"status": "affected", "version": "22.7R2.4"}, "widget: <= 22.7R2.4"),
    ],
)
def test_bentuk_yang_sudah_benar_tidak_berubah(version: dict[str, Any], expected: str) -> None:
    assert affected_of(version) == [expected]


def test_versi_unaffected_tetap_dilewati() -> None:
    assert affected_of({"status": "unaffected", "version": "2.0"}) == []


# ── teks bebas di `version`: dipakai apa adanya ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (">= 3.3.0, < 3.5.4", "widget: >= 3.3.0, < 3.5.4"),
        ("< 3.2.5", "widget: < 3.2.5"),
        ("<= 2.0", "widget: <= 2.0"),
        ("= 1.2.3", "widget: = 1.2.3"),
        ("  >= 1.0  ", "widget: >= 1.0"),
        ("All other versions", "widget: All other versions"),
        ("1.2.3 and earlier", "widget: 1.2.3 and earlier"),
        ("unspecified", "widget: unspecified"),
    ],
)
def test_teks_bebas_tidak_diawali_operator_lagi(text: str, expected: str) -> None:
    assert affected_of({"status": "affected", "version": text}) == [expected]


@pytest.mark.parametrize("blank", ["", "   "])
def test_version_kosong_dilewati(blank: str) -> None:
    assert affected_of({"status": "affected", "version": blank}) == []


def test_record_gaya_github_cna_menghasilkan_satu_baris_per_rentang() -> None:
    """Bentuk nyata CVE-2026-107385 (mariadb-connector-nodejs) di dev, sebelum perbaikan:
    `<= < 3.2.5`, `<= >= 3.3.0, < 3.3.4`, dst."""
    got = affected_of(
        {"status": "affected", "version": "< 3.2.5"},
        {"status": "affected", "version": ">= 3.3.0, < 3.3.4"},
        {"status": "affected", "version": ">= 3.4.0, < 3.4.7"},
        {"status": "affected", "version": ">= 3.5.0-rc.0, < 3.5.4"},
        product="mariadb-connector-nodejs",
    )
    assert got == [
        "mariadb-connector-nodejs: < 3.2.5",
        "mariadb-connector-nodejs: >= 3.3.0, < 3.3.4",
        "mariadb-connector-nodejs: >= 3.4.0, < 3.4.7",
        "mariadb-connector-nodejs: >= 3.5.0-rc.0, < 3.5.4",
    ]


def test_hasil_bisa_dipecah_ui_di_titik_dua_spasi_pertama() -> None:
    """`parseAffected` (web) memecah di `": "` pertama: produk di kiri, constraint di kanan."""
    (line,) = affected_of({"status": "affected", "version": ">= 3.3.0, < 3.5.4"}, product="x")
    product, constraint = line.split(": ", 1)
    assert (product, constraint) == ("x", ">= 3.3.0, < 3.5.4")
