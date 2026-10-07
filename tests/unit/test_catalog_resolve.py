"""`cti_core.catalog_resolve`: (vendor, produk) mentah CNA -> (vendor, keluarga) katalog (#19).

Kasus-kasusnya dari spike di data penuh (`docs/spikes/2026-10-07_cve_catalog_report_v2.md`) dan
dua record CVE asli (`tests/fixtures/spike_cve/`), bukan karangan."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cti_core.catalog_resolve import (
    VENDOR_NONE_KEY,
    AffectedEntry,
    alias_key,
    compact,
    entries_from_cna,
    fold_family,
    junk_reason,
    normalize,
    resolve,
    resolve_all,
    vendor_key,
)

REAL = Path(__file__).resolve().parents[1] / "fixtures" / "spike_cve"


def fam(vendor: str, product: str, **kw: object) -> tuple[str, str]:
    r = resolve(AffectedEntry(vendor=vendor, product=product, **kw))  # type: ignore[arg-type]
    assert r is not None, (vendor, product)
    return r.vendor_key, r.family_key


# ── normalisasi ───────────────────────────────────────────────────────────────────────────────


def test_normalize_is_unicode_aware() -> None:
    assert normalize("Palo_Alto-Networks") == "palo alto networks"
    assert normalize("워드프레스 결제 심플페이") == "워드프레스 결제 심플페이"
    assert compact("简数采集器") == "简数采集器"
    assert compact("Palo Alto") == compact("paloalto")


@pytest.mark.parametrize(
    ("product", "reason"),
    [
        ("n/a", "placeholder"),
        ("_", "placeholder"),
        ("Unspecified", "placeholder"),
        ("firmware", "generik"),
        ("Web Application", "generik"),
        ("1.2.3", "mirip-versi"),
        ("4769", "angka-saja"),
        ("0752-8303-8000-0002", "angka-saja"),
        ("https://oss.growatt.com", "url"),
        ("github.com/golang/glog", "url"),
        # bentuk janggal yang TETAP produk asli (spike pertama salah menghitungnya sebagai sampah)
        ("chatwoot/chatwoot", None),
        ("Giveaways and Contests by RafflePress", None),
        ("MB Custom Post Types & Custom Taxonomies", None),
        ("워드프레스 결제 심플페이", None),
        ("PAN-OS", None),
    ],
)
def test_junk_reason(product: str, reason: str | None) -> None:
    assert junk_reason(product) == reason


# ── vendor ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Palo Alto Networks", "paloaltonetworks"),
        ("palo_alto_networks", "Palo Alto Networks"),
        ("Microsoft", "Microsoft Inc"),
        ("Oracle", "Oracle Corporation"),
        ("D-Link", "D-Link Corporation"),
        ("MongoDB", "MongoDB, Inc."),
        ("Advantech", "Advantech Co., Ltd."),
    ],
)
def test_vendor_spellings_collapse_to_one_key(a: str, b: str) -> None:
    assert vendor_key(a) == vendor_key(b) != VENDOR_NONE_KEY


@pytest.mark.parametrize("vendor", ["", "n/a", "N/A", "unknown", "Unspecified", "_", "x"])
def test_placeholder_vendors_become_no_vendor(vendor: str) -> None:
    assert vendor_key(vendor) == VENDOR_NONE_KEY


def test_legal_suffix_stripping_does_not_merge_n_with_n_a() -> None:
    """Di data nyata akhiran satu huruf menggabungkan vendor `n` dengan `n a`; set dibatasi."""
    assert vendor_key("n a") == VENDOR_NONE_KEY
    assert vendor_key("n") == VENDOR_NONE_KEY  # satu huruf: terlalu pendek jadi kunci


def test_vendor_spellings_the_data_shows_but_that_stay_distinct() -> None:
    """Dikenali sebagai butuh alias/merge manual (bukan bug): kompak + akhiran legal tidak cukup."""
    assert vendor_key("n8n io") != vendor_key("n8n")
    assert vendor_key("graylog2") != vendor_key("graylog")
    assert vendor_key("nagios") != vendor_key("nagios enterprises llc")


def test_no_vendor_identity_is_not_monitorable_at_vendor_level() -> None:
    r = resolve(AffectedEntry(vendor="n/a", product="vmware esxi driver"))
    assert r is not None and not r.vendor_monitorable and r.vendor_display == "(tanpa vendor)"
    ok = resolve(AffectedEntry(vendor="Fortinet", product="FortiOS"))
    assert ok is not None and ok.vendor_monitorable and ok.vendor_display == "Fortinet"


# ── keluarga ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("product", "family"),
    [
        ("windows 10 version 1507", "windows"),
        ("windows 11 version 23h2", "windows"),
        ("windows server 2022", "windows server"),
        ("windows server 2012 r2", "windows server"),
        ("windows server 2025 server core installation", "windows server"),
        ("windows server 2022 23h2 edition server core installation", "windows server"),
        ("dir 605l", "dir"),
        ("php 8 2", "php"),
        ("nginx", "nginx"),
        ("nginx plus", "nginx plus"),
        ("log4j", "log4j"),
        ("microsoft 365 apps for enterprise", "microsoft 365 apps for enterprise"),
        ("7", "7"),  # tidak pernah kosong
    ],
)
def test_fold_family(product: str, family: str) -> None:
    assert fold_family(product) == family


def test_windows_variants_share_one_family_under_one_vendor() -> None:
    keys = {
        fam("Microsoft", p)
        for p in (
            "Windows 10 Version 1507",
            "Windows 10 Version 22H2",
            "Windows 11 version 23H2",
            "Windows 11 Version 23H2",
        )
    }
    assert keys == {("microsoft", "windows")}


def test_server_core_installation_folds_into_its_base_server_family() -> None:
    a = fam("Microsoft", "Windows Server 2025")
    b = fam("Microsoft", "Windows Server 2025 (Server Core installation)")
    assert a == b == ("microsoft", "windows server")


def test_a_family_equal_to_its_vendor_is_not_folded() -> None:
    """`Microsoft 365` -> `microsoft` mencampur satu produk dengan seluruh vendornya."""
    assert fam("Microsoft", "Microsoft 365") == ("microsoft", "microsoft 365")


def test_product_families_that_must_stay_apart() -> None:
    assert fam("F5", "NGINX Open Source") != fam("F5", "NGINX Plus")
    assert fam("Juniper Networks", "Junos OS") != fam("Juniper Networks", "Junos OS Evolved")
    assert fam("Fortinet", "FortiOS") != fam("Fortinet", "FortiProxy")


def test_spelling_variants_of_the_same_product_resolve_to_one_identity() -> None:
    """Kasus kuat dari bagian 4 laporan spike."""
    assert (
        fam("Palo Alto Networks", "PAN-OS")
        == fam("paloaltonetworks", "pan-os")
        == fam("palo_alto_networks", "pan_os")
    )
    assert fam("wolfSSL", "wolfSSL") == fam("wolfssl", "wolfssl")
    assert fam("MongoDB", "MongoDB Server") == fam("MongoDB", "MongoDB server")


# ── CPE dan alias ─────────────────────────────────────────────────────────────────────────────


def test_cpe_wins_over_cna_text_and_wildcards_fall_back() -> None:
    e = AffectedEntry(
        vendor="Palo Alto Networks",
        product="PAN-OS software",
        cpes=("cpe:2.3:o:paloaltonetworks:pan-os:*:*:*:*:*:*:*:*",),
    )
    r = resolve(e)
    assert r is not None and (r.vendor_key, r.family_key, r.source) == (
        "paloaltonetworks",
        "pan os",
        "cpe",
    )
    wild = AffectedEntry(vendor="Acme", product="Widget", cpes=("cpe:2.3:a:*:*:*:*:*:*:*:*:*:*",))
    r2 = resolve(wild)
    assert r2 is not None and (r2.vendor_key, r2.family_key, r2.source) == ("acme", "widget", "cna")


def test_package_name_is_used_when_product_is_missing() -> None:
    r = resolve(AffectedEntry(vendor="npm", package="left-pad"))
    assert r is not None and r.family_key == "left pad"


def test_an_alias_beats_the_automatic_fold() -> None:
    vk = vendor_key("Graylog")
    aliases = {alias_key(vk, "graylog web interface"): "graylog"}

    folded = resolve(AffectedEntry(vendor="Graylog", product="Graylog Web Interface"))
    mapped = resolve(
        AffectedEntry(vendor="Graylog", product="Graylog Web Interface"), aliases=aliases
    )

    assert folded is not None and folded.family_key == "graylog web interface"
    assert (
        mapped is not None and mapped.family_key == "graylog" and mapped.family_display == "Graylog"
    )


def test_junk_products_have_no_identity() -> None:
    assert resolve(AffectedEntry(vendor="Acme", product="n/a")) is None
    assert resolve(AffectedEntry(vendor="Acme", product="")) is None
    assert resolve(AffectedEntry(vendor="Acme", product="https://x.example")) is None


# ── resolve_all / entries_from_cna ────────────────────────────────────────────────────────────


def test_resolve_all_dedupes_variants_and_skips_junk_keeping_order() -> None:
    entries = [
        AffectedEntry(vendor="Microsoft", product="Windows 10 Version 1507"),
        AffectedEntry(vendor="Microsoft", product="Windows 11 Version 23H2"),
        AffectedEntry(vendor="Acme", product="n/a"),
        AffectedEntry(vendor="F5", product="NGINX Plus"),
    ]

    got = [(r.vendor_key, r.family_key) for r in resolve_all(entries)]

    assert got == [("microsoft", "windows"), ("f5", "nginx plus")]


def test_entries_from_cna_tolerates_bad_shapes() -> None:
    cna = {
        "affected": [
            {"vendor": "Acme", "product": "Widget", "cpes": ["cpe:2.3:a:acme:widget:*"]},
            "bukan dict",
            {"vendor": None, "product": None, "cpes": "bukan list"},
        ]
    }
    assert entries_from_cna(cna) == [
        AffectedEntry("Acme", "Widget", "", ("cpe:2.3:a:acme:widget:*",)),
        AffectedEntry("", "", "", ()),
    ]
    assert entries_from_cna({}) == [] and entries_from_cna({"affected": "x"}) == []


def test_real_cve_records_resolve_to_the_expected_identities() -> None:
    def resolved(cve_id: str) -> list[tuple[str, str]]:
        data = json.loads((REAL / f"{cve_id}.json").read_text())
        return [
            (r.vendor_key, r.family_key)
            for r in resolve_all(entries_from_cna(data["containers"]["cna"]))
        ]

    assert resolved("CVE-2025-0282") == [
        ("ivanti", "connect secure"),
        ("ivanti", "policy secure"),
        ("ivanti", "neurons for zta gateways"),
    ]
    # kubernetes ingress-nginx BUKAN F5 nginx: identitasnya terpisah walau nama memuat `nginx`
    assert resolved("CVE-2025-1974") == [("kubernetes", "ingress nginx")]
    assert fam("F5", "NGINX Open Source") != ("kubernetes", "ingress nginx")
