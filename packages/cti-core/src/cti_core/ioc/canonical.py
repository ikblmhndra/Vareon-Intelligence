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

from cti_core.ioc.extractor import _RE_DEFANG_DOT, _refang

CANONICAL_RULES_VERSION = 1

_RE_DEFANG_AT = re.compile(r"\s*(?:\[@\]|\(@\)|\[at\]|\(at\))\s*", re.IGNORECASE)
_RE_DEFANG_COLON = re.compile(r"\[:\]")
_RE_URL_PARTS = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*://)([^/?#]*)(.*)$", re.DOTALL)
_HASH_TYPES = frozenset({"sha256", "sha1", "md5"})


def _canonical_url(value: str) -> str:
    v = _refang(_RE_DEFANG_COLON.sub(":", value.strip()))
    m = _RE_URL_PARTS.match(v)
    if not m:
        return v
    scheme, authority, rest = m.groups()
    # userinfo (`user:pw@`) tetap apa adanya; hanya host[:port] yang di-lowercase.
    userinfo, sep, host = authority.rpartition("@")
    return f"{scheme.lower()}{userinfo}{sep}{host.lower()}{rest}"


def canonical(ioc_type: str, value: str) -> str:
    if ioc_type == "ip":
        return _RE_DEFANG_DOT.sub(".", value).strip()
    if ioc_type == "domain":
        return _refang(value).lower().rstrip(".")
    if ioc_type == "url":
        return _canonical_url(value)
    if ioc_type == "email":
        return _refang(_RE_DEFANG_AT.sub("@", value)).lower()
    if ioc_type in _HASH_TYPES:
        return value.strip().lower()
    return value.strip()
