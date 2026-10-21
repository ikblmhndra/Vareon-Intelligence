"""Stage: ambil teks artikel dari URL -- port gabungan dua path yang di kode
lama kebetulan sama-sama "ambil isi artikel" tapi lewat DUA library beda:

- Jalur cepat `nlp.py:296-309`: `requests.get()` + `sumy.HtmlParser` (HTML
  DOM lawas, gampang gagal di halaman JS-heavy).
- Jalur fallback `ttpValidator.fetch_article_text()`: Playwright render +
  `newspaper3k` parse, dipanggil pas jalur cepat exception apa pun.

`cti-enrich` udah scaffold `trafilatura` dari Fase 1 (base dependency, bukan
di balik extra `nlp`) -- justru itu alasannya: satu library ekstraksi teks
buat DUA jalur (HTTP langsung, atau HTML hasil render Playwright), bukan
sumy-buat-ekstraksi (nyasar, sumy harusnya cuma buat *summarize*, lihat
`summarize.py`) + newspaper3k terpisah. `_full_article_text` (var lama)
sekarang JADI nilai balik stage ini -- gak ada lagi `_full_article_text or
result` di caller, karena `result` (ringkasan) sekarang stage lain
(`summarize.py`) yang SELALU jalan di atas apa pun yang stage ini hasilin."""

from __future__ import annotations

import ipaddress
import socket
from configparser import ConfigParser
from urllib.parse import urlsplit

import structlog
import trafilatura
from playwright.sync_api import sync_playwright

log = structlog.get_logger()

_USER_AGENT = "Mozilla/5.0"
_HTTP_TIMEOUT_S = 30
_PLAYWRIGHT_TIMEOUT_MS = 30_000
_PLAYWRIGHT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/91.0.4472.124 Safari/537.36"
)


def _fetch_rendered_html(url: str) -> str:
    """Fallback JS-heavy -- port `ttpValidator.fetch_article_text`'s
    Playwright render, minus parsing (extraction diserahkan ke trafilatura,
    satu library buat dua jalur, lihat docstring modul)."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": _PLAYWRIGHT_USER_AGENT})
            response = page.goto(url, timeout=_PLAYWRIGHT_TIMEOUT_MS)
            # `goto` GAK raise di 403/429/5xx -- ngembaliin response error, dan
            # `page.content()` isinya halaman blokir WAF. Tanpa cek ini halaman
            # itu dianggap isi artikel (kejadian nyata: Arctic Wolf/Wordfence).
            blocked = response is not None and response.status >= 400
            content = "" if blocked else page.content()
            browser.close()
        return content
    except Exception:
        return ""


# Halaman "kamu diblokir" dari WAF/anti-bot -- teksnya PENDEK dan mengandung
# frasa khas. Dianggap BUKAN isi artikel: lebih baik title-only daripada
# ngasih boilerplate Wordfence/Cloudflare ke summarize/TTP/IOC/scoring
# (e2e staging Fase 10: LLM njawab "saya gak lihat ringkasan artikelnya",
# JSON gagal, artikel hilang -- dan itu KASUS BERUNTUNG; boilerplate bisa saja
# dihalusinasi jadi TTP).
_BLOCK_MAX_CHARS = 1500
_BLOCK_MARKERS = (
    "blocked by wordfence",
    "wordfence",
    "403 forbidden",
    "access denied",
    "just a moment",
    "attention required",
    "checking your browser",
    "enable javascript and cookies",
    "you have been blocked",
    "request blocked",
    "verify you are human",
    "unusual traffic",
)


def looks_blocked(text: str) -> bool:
    """Teks pendek yang isinya halaman blokir/challenge, bukan artikel.
    Batas panjang jaga false-positive: artikel BENERAN yang menyebut
    "access denied" panjangnya jauh di atas ambang ini."""
    if not text or len(text) > _BLOCK_MAX_CHARS:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _BLOCK_MARKERS)


def _is_public_http_url(url: str) -> bool:
    """URL artikel datang dari feed pihak ketiga. Tanpa cek ini feed yang membawa
    `http://redis:6379/`, `http://169.254.169.254/` atau `file:///proc/self/environ` membuat worker
    (dan Chromium fallback-nya) membaca host internal, lalu isinya masuk ringkasan LLM dan tabel
    `articles`. Yang diizinkan: http(s) ke alamat publik saja. Hostname di-resolve di sini karena
    nama seperti `localhost`, `api` atau `2130706433` tidak kelihatan privat dari tulisannya.

    shortcut: hanya URL awal yang dicek, redirect dan DNS rebinding tidak, upgrade kalau feed
    harus dianggap tak tepercaya sama sekali (butuh fetch sendiri dengan IP yang dikunci)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError):  # ValueError: port di luar rentang
        return False
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


def fetch_text(url: str) -> str:
    """Best-effort teks artikel penuh. String kosong kalau dua-duanya gagal
    atau URL-nya bukan http(s) publik (`_is_public_http_url`)
    -- caller (`pipeline.py`) yang mutusin gimana nanganin artikel tanpa
    teks (skip extract_ttps/score, persis kode lama waktu `result` kosong)."""
    if not _is_public_http_url(url):
        log.warning("fetch_text_blocked_url", url=url)
        return ""
    downloaded = trafilatura.fetch_url(url, config=_trafilatura_config())
    if downloaded:
        text = trafilatura.extract(downloaded) or ""
        if text and not looks_blocked(text):
            return text

    html = _fetch_rendered_html(url)
    if html:
        text = trafilatura.extract(html) or ""
        return "" if looks_blocked(text) else text
    return ""


def _trafilatura_config() -> ConfigParser:
    cfg = trafilatura.settings.use_config()
    cfg.set("DEFAULT", "USER_AGENTS", _USER_AGENT)
    cfg.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(_HTTP_TIMEOUT_S))
    return cfg
