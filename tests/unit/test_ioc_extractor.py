"""cti_core.ioc.extractor -- port byte-identik dari `iocExtractor.py`
(diverifikasi terpisah, otomatis, lawan korpus 7899 title + 55 body artikel
real dari dump arsip -- lihat docs/PROGRESS.md item 5.9). Test di sini
nyakup tiap tipe IOC + satu regresi yang genuinely penting: ReDoS.

Pindah dari `cti_enrich.ioc` ke `cti_core.ioc` Fase 7.3 Bagian 4 (router
`newsletter` butuh extractor ini, `apps/api` gak boleh import `cti_enrich`)
-- lihat docstring `cti_core/ioc/extractor.py`."""

from __future__ import annotations

import signal

import pytest
from cti_core.ioc.extractor import extract_iocs


def test_extracts_ip() -> None:
    result = extract_iocs("Connects to 45.33.32.156 for C2.")
    assert result["ips"] == ["45.33.32.156"]


def test_extracts_defanged_ip() -> None:
    """IP TIDAK di-refang -- beda dari URL (`_refang()` cuma diterapkan ke
    hasil `_RE_URL_PROTO`, bukan `_RE_IP`). Port apa adanya dari source asli."""
    result = extract_iocs("Connects to 45[.]33[.]32[.]156 for C2.")
    assert result["ips"] == ["45[.]33[.]32[.]156"]


def test_extracts_hashes() -> None:
    result = extract_iocs("sha256 " + "a" * 64 + " sha1 " + "b" * 40 + " md5 " + "c" * 32)
    assert result["sha256"] == ["a" * 64]
    assert result["sha1"] == ["b" * 40]
    assert result["md5"] == ["c" * 32]


def test_extracts_cve() -> None:
    result = extract_iocs("Exploits CVE-2024-12345 in the wild.")
    assert result["cves"] == ["CVE-2024-12345"]


def test_extracts_defanged_url() -> None:
    result = extract_iocs("Payload at hxxps://evil[.]com/drop.exe")
    assert result["urls"] == ["https://evil.com/drop.exe"]


def test_extracts_email() -> None:
    result = extract_iocs("Contact admin[at]evil.com for ransom.")
    assert result["emails"] == ["admin[at]evil.com"]


def test_allowlist_filters_source_domain() -> None:
    result = extract_iocs(
        "See https://good.com/page for details.",
        source_url="https://good.com/article",
    )
    assert result == {}


def test_allowlist_filters_configured_domain() -> None:
    result = extract_iocs(
        "See https://wiz.io/blog for details.",
        allowlist={"url_domains": {"wiz.io"}, "email_domains": set(), "ips": set()},
    )
    assert result == {}


def test_private_ip_excluded() -> None:
    result = extract_iocs("Internal host 192.168.1.1 talked to 8.8.8.8.")
    assert result["ips"] == ["8.8.8.8"]


def test_empty_text_returns_empty_dict() -> None:
    assert extract_iocs("") == {}


def test_no_iocs_returns_empty_dict() -> None:
    assert extract_iocs("Just a plain sentence with no indicators at all.") == {}


class _AlarmTimeout(Exception):
    pass


def test_domain_defanged_regex_does_not_catastrophically_backtrack() -> None:
    """Regresi ReDoS -- ketemu LIVE lewat korpus test Fase 5 (artikel real
    elastic.co/security-labs/threat-command/operation-bleeding-bear, ~12KB
    teks natural, `extract_iocs()` gantung TANPA BATAS, proses dibunuh
    manual setelah >5 menit CPU 98%). Root cause: `_RE_DOMAIN_DEFANGED`
    lama pakai `(?:...)*` gak dibatasi, kombinasi `\\s*` di dua sisi tiap
    repetisi bikin backtracking eksponensial di teks yang HAMPIR (tapi gak
    pernah) cocok -- prosa Inggris biasa penuh pola "kata. kata. kata."
    yang mirip struktur domain multi-label. Fix: `{0,10}` (gak ada domain
    asli >10 label). Test ini reproduce bentuk teks yang sama (banyak
    "word." berulang) dengan timeout keras -- kalau regexnya balik jadi
    unbounded lagi, test ini gantung/gagal, bukan cuma lambat.

    Ambang alarm 60 detik, BUKAN 5 (CI #17, 2026-10-07): `{0,10}` terbatas tapi
    konstanta biayanya besar -- waktunya LINEAR (±0,45 ms per karakter: 1,3 s untuk
    500 pengulangan, 2,7 s untuk 1000, 5,4 s untuk 2000 di mesin dev; ±5 s di runner
    GitHub), jadi ambang 5 s tepat di batas dan merah-hijau mengikuti kecepatan
    runner, padahal bukan ReDoS. Regex tak terbatas (`*`) tumbuh EKSPONENSIAL (x16
    tiap +4 pengulangan; 24 s pada 22 pengulangan, tak selesai pada 2000), jadi
    ambang 60 s tetap pasti menangkap regresi yang dimaksud tanpa bergantung pada
    kecepatan mesin."""
    pathological = "word. " * 2000 + " end"

    def _handler(signum: int, frame: object) -> None:
        raise _AlarmTimeout()

    old_handler = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(60)
    try:
        extract_iocs(pathological)
    except _AlarmTimeout:
        pytest.fail("extract_iocs() gantung >60s -- _RE_DOMAIN_DEFANGED balik ReDoS")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
