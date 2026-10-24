"""Bentuk kanonik nilai IOC -- SATU fungsi yang dipanggil setiap penulis IOC sebelum upsert
(enrich persist, `write_article_findings` newsletter, sink deepdarkCTI).

Kenapa: nilai IOC dulu disimpan apa adanya dari artikel (`evil[.]com`, `Evil.COM`, `hxxp://...`),
jadi satu indikator yang sama jadi beberapa baris dan allowlist/pencarian meleset. Aturannya
(spec P2 cheap wins 3.1): refang, lalu huruf kecil HANYA di bagian yang case-insensitive
(host, domain, email, hash; path/query/fragment URL dibiarkan). Tipe tak dikenal hanya di-strip.

Migrasi 0.8.6 membawa SALINAN BEKU aturan ini (tanpa import kode aplikasi); kalau aturan di sini
berubah, naikkan `CANONICAL_RULES_VERSION` dan tulis migrasi baru -- jangan ubah migrasi lama."""

from __future__ import annotations

import re

from cti_core.ioc.extractor import _RE_DEFANG_DOT

CANONICAL_RULES_VERSION = 1

# Pola pemisah titik extractor dipakai ulang, tapi tanpa membedakan huruf besar/kecil
# (`[DOT]`); extractor sendiri tidak diubah.
_RE_DOT = re.compile(_RE_DEFANG_DOT.pattern, re.IGNORECASE)
_RE_DEFANG_AT = re.compile(r"\s*(?:\[@\]|\(@\)|\[at\]|\(at\))\s*", re.IGNORECASE)
_RE_DEFANG_COLON = re.compile(r"\[:\]")
# scheme, pemisah (`://` atau `[:]//`), authority, sisanya (path/query/fragment).
_RE_URL_PARTS = re.compile(r"^([^/?#]*?)(?:\[:\]|:)//([^/?#]*)(.*)$", re.DOTALL)
_RE_HOST_PREFIX = re.compile(r"^([^/?#]*)(.*)$", re.DOTALL)
_HASH_TYPES = frozenset({"sha256", "sha1", "md5"})
_SCHEME_FIX = {"hxxp": "http", "hxxps": "https", "fxp": "ftp"}


def _refang_host(authority: str) -> str:
    """Refang + lowercase host[:port]; userinfo (`user:pw@`) dibiarkan."""
    userinfo, sep, host = authority.rpartition("@")
    host = _RE_DEFANG_COLON.sub(":", _RE_DOT.sub(".", host)).lower()
    return f"{userinfo}{sep}{host}"


def _canonical_url(value: str) -> str:
    """Hanya scheme dan authority yang di-refang/lowercase; path, query, fragment utuh."""
    v = value.strip()
    m = _RE_URL_PARTS.match(v)
    if m:
        scheme, authority, rest = m.groups()
        scheme = scheme.lower()
        scheme = _SCHEME_FIX.get(scheme, scheme)
        return f"{scheme}://{_refang_host(authority)}{rest}"
    authority, rest = _RE_HOST_PREFIX.match(v).groups()  # type: ignore[union-attr]
    return f"{_refang_host(authority)}{rest}"


def canonical(ioc_type: str, value: str) -> str:
    if ioc_type == "ip":
        return _RE_DOT.sub(".", value).strip()
    if ioc_type == "domain":
        return _RE_DOT.sub(".", value).strip().lower().rstrip(".")
    if ioc_type == "url":
        return _canonical_url(value)
    if ioc_type == "email":
        return _RE_DOT.sub(".", _RE_DEFANG_AT.sub("@", value)).strip().lower()
    if ioc_type in _HASH_TYPES:
        return value.strip().lower()
    return value.strip()
