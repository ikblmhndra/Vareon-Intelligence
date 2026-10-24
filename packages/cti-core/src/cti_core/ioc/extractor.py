"""SATU IOC extractor -- kanonik, ganti 4 salinan yang sebelumnya nyebar:
`ScraperNews/modules/iocExtractor.py` (yang ini, source aslinya -- 105 dari 120
baris identik sama forknya, udah mulai drift), fork di
`ScraperNewsWeb/app/services/newsletter_service.py:20-180`, helper di
`ioc_allowlist_service.py:26,31`, dan `refang()` sendiri di
`ScraperNewsWeb/wisemap_cti.py:141`.

Port BYTE-IDENTIK dari `iocExtractor.py` -- semua regex, urutan filter, dan
logika allowlist disalin apa adanya, TERMASUK detail yang keliatan aneh (mis.
`_SEP` punya `r'\\.'` dua kali -- itu emang ada di source asli, bukan typo
yang ditambahin di sini). Cuma nama privat yang disesuaikan gaya modul ini.

`allowlist` tetap parameter murni (`dict[str, set[str]]`), BUKAN dependency
ke Postgres session -- resolusi allowlist (baca dari tabel `ioc_allowlist`)
itu tanggung jawab caller (`stages/extract_iocs.py` DAN, Fase 7.3 Bagian 4,
`cti_api.services.newsletter`), bukan modul ini.

**Pindah dari `cti_enrich.ioc` ke `cti_core.ioc` (Fase 7.3 Bagian 4, router
`newsletter`)** -- modul ini ZERO dependency internal (cuma `ipaddress`/`re`
stdlib) dari awal, sengaja didesain importable standalone (lihat alinea di
atas). `newsletter_service.py` lama py FORK sendiri dari extractor ini
(disebut di atas) yang justru mau dieliminasi Fase 5 -- tapi `apps/api`
punya exit criteria (Fase 7, docs/PROGRESS.md): "gak ada import
`cti_scraper`/`cti_enrich` dari API", jadi gak bisa `from cti_enrich.ioc
import ...` langsung dari router `newsletter`. Karena modulnya beneran gak
punya dependency ke `cti_enrich` apa pun, pindah ke `cti_core` (base
package yang UDAH dipakai `cti_enrich` DAN `cti_api` dua-duanya) itu
mekanis murni -- bukan rewrite, nol perubahan perilaku -- dan nyelesain
DUA masalah sekaligus (SATU extractor beneran, gak ngelanggar boundary
API)."""

from __future__ import annotations

import ipaddress as _ipaddress
import re

_SEP = r"(?:\.|\.|\[\.\]|\[\.|\.  \]|\(\.\)|\{\.\}|\[dot\]|\(dot\))"
_DEFANG_SEP = r"(?:\[\.\]|\[\.|\.  \]|\(\.\)|\{\.\}|\[dot\]|\(dot\))"
_LABEL = r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?"
_ALPHA_LABEL = r"(?:[a-zA-Z0-9]*[a-zA-Z][a-zA-Z0-9]*)"

_TLD = (
    r"(?:com|net|org|io|gov|edu|mil|int|info|biz|xyz|ru|cn|de|uk|co|top|site|"
    r"online|tech|app|dev|cloud|red|pw|cc|tv|me|mobi|ly|to|sh|gg|is|am|fm|ac|"
    r"in|jp|fr|eu|au|nz|ca|br|pl|nl|se|no|fi|dk|ch|at|be|il|sg|hk|tw|kr|th|"
    r"id|my|ph|vn|ua|tr|sa|ae|za|ng|ke|gh)"
)

_RE_IP = re.compile(r"\b(?:\d{1,3})(?:\s*" + _SEP + r"\s*(?:\d{1,3})){3}\b")
_RE_VERSION_PREFIX = re.compile(
    r"(?:version|ver|firmware|software|release|patch|build|update|v)\s*[:\s]*"
    r"(\d{1,3}(?:\.\d{1,3}){3})",
    re.IGNORECASE,
)
_RE_URL_PROTO = re.compile(
    r"(?:hxxps?|https?|fxp|ftp)://(?:"
    + _LABEL
    + r"(?:\s*"
    + _SEP
    + r"\s*))+[a-zA-Z]{2,}(?:/[^\s]*)?"
)
_RE_URL_PATH = re.compile(
    r"(?:"
    + _ALPHA_LABEL
    + r"(?:"
    + _SEP
    + r"))"
    + r"(?:"
    + _LABEL
    + r"(?:"
    + _SEP
    + r"))*"
    + _TLD
    + r"/[^\s]+"
)
_RE_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+-]+(?:\s*(?:\[@\]|\[at\]|@|\(@\))\s*)"
    + _LABEL
    + r"(?:\s*"
    + _SEP
    + r"\s*)+[a-zA-Z]{2,}"
)
# `{0,10}`, BUKAN `*` polos kayak source asli -- SATU-SATUNYA deviasi
# disengaja dari port byte-identik (lihat docstring modul). `*` bareng
# `\s*` di dua sisi tiap repetisi bikin ReDoS/catastrophic backtracking:
# ketauan LIVE di korpus test Fase 5 (artikel elastic.co/.../
# operation-bleeding-bear, teks natural 12KB) -- proses gantung TANPA
# BATAS (dibunuh manual setelah >5 menit, CPU 98%). Bug ini ADA di
# `iocExtractor.py` asli juga (regex sama persis), bukan sesuatu yang
# ke-introduce port ini -- tapi ini kelas bug DoS/availability, beda dari
# "logic beda" yang harus dipertahankan verbatim. `{0,10}` cukup buat
# domain defanged asli (gak ada domain nyata >10 label) dan bikin worst-
# case regex engine terbatas, bukan unbounded. Diverifikasi: hasil match
# byte-identik masih sama di korpus 7899 title + 55 body real (lihat
# tests/unit/test_ioc_extractor.py), CUMA beda di teks yang tadinya bikin
# hang (yang gak pernah selesai sama sekali, jadi gak ada "hasil lama"
# buat dibandingin).
_RE_DOMAIN_DEFANGED = re.compile(
    _LABEL
    + r"(?:\s*"
    + _SEP
    + r"\s*"
    + _LABEL
    + r"){0,10}"
    + r"\s*"
    + _DEFANG_SEP
    + r"\s*"
    + r"[a-zA-Z]{2,}"
)
_RE_SHA256 = re.compile(r"\b[a-fA-F0-9]{64}\b")
_RE_SHA1 = re.compile(r"\b[a-fA-F0-9]{40}\b")
_RE_MD5 = re.compile(r"\b[a-fA-F0-9]{32}\b")
_RE_CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)

_PRIVATE_NETWORKS = [
    _ipaddress.ip_network("0.0.0.0/8"),
    _ipaddress.ip_network("10.0.0.0/8"),
    _ipaddress.ip_network("100.64.0.0/10"),
    _ipaddress.ip_network("127.0.0.0/8"),
    _ipaddress.ip_network("169.254.0.0/16"),
    _ipaddress.ip_network("172.16.0.0/12"),
    _ipaddress.ip_network("192.0.0.0/24"),
    _ipaddress.ip_network("192.168.0.0/16"),
    _ipaddress.ip_network("198.18.0.0/15"),
    _ipaddress.ip_network("255.255.255.255/32"),
]

_RE_DEFANG_DOT = re.compile(r"\s*(?:\[\.\]|\[\.|\.  \]|\(\.\)|\{\.\}|\[dot\]|\(dot\)|\\.)\s*")
_RE_DEFANG_PROTO = re.compile(r"^hxx(ps?)://", re.IGNORECASE)
_RE_DEFANG_FXP = re.compile(r"^fxp://", re.IGNORECASE)


def _refang(value: str) -> str:
    v = _RE_DEFANG_DOT.sub(".", value)
    v = _RE_DEFANG_PROTO.sub(r"htt\1://", v)
    v = _RE_DEFANG_FXP.sub("ftp://", v)
    return v.strip()


def refang(value: str) -> str:
    """Bentuk yang bisa dikirim ke layanan luar: `1[.]2[.]3[.]4` -> `1.2.3.4`,
    `hxxps://evil[.]com` -> `https://evil.com`. IOC disimpan apa adanya dari artikel (masih
    defanged kalau artikelnya begitu), jadi enrichment wajib memanggil ini dulu."""
    return _refang(value)


def _is_private_ip(raw: str) -> bool:
    clean = _RE_DEFANG_DOT.sub(".", raw)
    try:
        return any(_ipaddress.ip_address(clean) in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


_RE_EXTRACT_DOMAIN = re.compile(r"^(?:https?://)?([^/:?\s]+)")


def _url_domain(url: str) -> str:
    m = _RE_EXTRACT_DOMAIN.match(url.lower())
    return m.group(1) if m else ""


def _email_domain(email: str) -> str:
    parts = re.split(r"[@\[\(]at[\)\]]", email.lower())
    if len(parts) == 2:
        return parts[1].strip().lstrip("[").rstrip("]").strip()
    if "@" in email:
        return email.split("@", 1)[1].lower()
    return ""


def _filter_iocs(ioc_dict: dict[str, list[str]], source_url: str = "") -> dict[str, list[str]]:
    """Buang HANYA yang pasti bukan indikator: IP privat/reserved dan URL ke domain sumber
    artikelnya sendiri. Allowlist TIDAK lagi membuang di sini (sejak 0.8.6): yang cocok disimpan
    dan ditandai `auto_suppressed` saat persist, lihat `cti_core.ioc.allowlist`."""
    source_domain = _url_domain(source_url) if source_url else ""

    def _ok_ip(v: str) -> bool:
        return not _is_private_ip(v)

    def _ok_url(v: str) -> bool:
        d = _url_domain(v)
        return not (source_domain and (d == source_domain or d.endswith("." + source_domain)))

    filters = {"ips": _ok_ip, "urls": _ok_url, "urls_with_path": _ok_url}
    result: dict[str, list[str]] = {}
    for key, values in ioc_dict.items():
        fn = filters.get(key)
        result[key] = [v for v in values if fn is None or fn(v)]
    return {k: v for k, v in result.items() if v}


def extract_iocs(text: str, source_url: str = "") -> dict[str, list[str]]:
    if not text:
        return {}
    version_numbers = {m.group(1) for m in _RE_VERSION_PREFIX.finditer(text)}
    urls = list(dict.fromkeys(_refang(u) for u in _RE_URL_PROTO.findall(text)))
    text_no_urls = _RE_URL_PROTO.sub(" ", text)
    urls_with_path = list(dict.fromkeys(_refang(u) for u in _RE_URL_PATH.findall(text_no_urls)))
    text_no_urls_or_paths = _RE_URL_PATH.sub(" ", text_no_urls)
    raw = {
        "ips": [ip for ip in dict.fromkeys(_RE_IP.findall(text)) if ip not in version_numbers],
        "urls": urls,
        "urls_with_path": urls_with_path,
        "domains": list(dict.fromkeys(_RE_DOMAIN_DEFANGED.findall(text_no_urls_or_paths))),
        "emails": list(dict.fromkeys(_RE_EMAIL.findall(text))),
        "sha256": list(dict.fromkeys(_RE_SHA256.findall(text))),
        "sha1": list(dict.fromkeys(_RE_SHA1.findall(text))),
        "md5": list(dict.fromkeys(_RE_MD5.findall(text))),
        "cves": list(dict.fromkeys(m.upper() for m in _RE_CVE.findall(text))),
    }
    return _filter_iocs({k: v for k, v in raw.items() if v}, source_url=source_url)
