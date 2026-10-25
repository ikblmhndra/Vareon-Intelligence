"""Stage: ekstrak + filter IOC dari teks artikel, plus cek hit C2 feed --
port `nlp.py:314-315` (`iocExtractor.extract_iocs(...)`, `_check_c2_hit`) +
`_get_allowlist()`/`_get_c2_feed()` (TTL cache module-level, nlp.py:111-141).

Cache TTL (300s allowlist, 3600s C2 feed) DIPERTAHANKAN -- ini optimisasi
nyata buat proses worker yang lama hidup (banyak artikel diproses per
proses, gak perlu query Postgres tiap artikel), bukan detail yang aman
dibuang. Beda dari kode lama: sumber datanya `IocAllowlistEntry`/
`ThreatFeedEntry` (Postgres, lewat `cti_core.db.repositories.ioc_reference`),
bukan `news_db.ioc_allowlist`/`threat_feeds` (Mongo)."""

from __future__ import annotations

import time

from cti_core.db.repositories.ioc_reference import get_c2_feed, get_ioc_allowlist
from cti_core.ioc.canonical import canonical
from cti_core.ioc.extractor import extract_iocs as _extract_iocs
from sqlalchemy.orm import Session

_ALLOWLIST_TTL = 300.0
_C2_FEED_TTL = 3600.0

_allowlist_cache: dict[str, set[str]] | None = None
_allowlist_cache_ts = 0.0
_c2_feed_cache: dict[str, set[str]] | None = None
_c2_feed_cache_ts = 0.0


def _get_allowlist(session: Session) -> dict[str, set[str]]:
    global _allowlist_cache, _allowlist_cache_ts
    now = time.monotonic()
    if _allowlist_cache is None or (now - _allowlist_cache_ts) > _ALLOWLIST_TTL:
        try:
            _allowlist_cache = get_ioc_allowlist(session)
        except Exception:
            _allowlist_cache = {"url_domains": set(), "email_domains": set(), "ips": set()}
        _allowlist_cache_ts = now
    return _allowlist_cache


def _get_c2_feed(session: Session) -> dict[str, set[str]]:
    global _c2_feed_cache, _c2_feed_cache_ts
    now = time.monotonic()
    if _c2_feed_cache is None or (now - _c2_feed_cache_ts) > _C2_FEED_TTL:
        try:
            _c2_feed_cache = get_c2_feed(session)
        except Exception:
            _c2_feed_cache = {"ips": set(), "domains": set()}
        _c2_feed_cache_ts = now
    return _c2_feed_cache


def check_c2_hit(ioc_data: dict[str, list[str]], session: Session) -> bool:
    feed = _get_c2_feed(session)
    if not feed["ips"] and not feed["domains"]:
        return False
    # Feed disimpan kanonik (0.8.6); nilai artikel bisa defanged/huruf besar, jadi kanonikkan dulu.
    article_ips = {canonical("ip", v) for v in ioc_data.get("ips", [])}
    article_domains = {canonical("domain", v) for v in ioc_data.get("domains", [])}
    return bool(article_ips & feed["ips"] or article_domains & feed["domains"])


def extract_iocs(text: str, source_url: str, session: Session) -> dict[str, list[str]]:
    if not text:
        return {}
    return _extract_iocs(text, source_url=source_url)
