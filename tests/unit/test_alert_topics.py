"""Topik Telegram yang dipakai kode harus terdaftar di `.env.example`.

Topik yang tak ada di `TELEGRAM__THREAD_IDS` bikin pengiriman gagal (`UnknownAlertTopic`)
-- kelihatan, tapi baru saat produksi mengirim alert pertama dengan topik itu. Fase 10.E
menambah lima topik (`notd`, `debug`, `library_advisory`, `logbook`, `top_ta`) dan banyak literal
baru; test ini menangkap salah ketik/topik yang lupa didaftarkan SEBELUM deploy.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re

import cti_enrich.tweet_routing as tweet_routing

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Dipakai kode, dikelompokkan menurut asalnya (cek manual saat menambah topik baru).
EXPECTED = {
    "article routing": {"global", "apac", "apac_indo", "apt", "ot", "zero_day", "data_breach",
                        "data_breach_indo", "vendor_report", "tech_stack", "tech_stack_unrelated",
                        "best_practice"},
    "sink/alert lain": {"darkweb", "pir", "scraper_health"},
    "Fase 10.E": {"notd", "debug", "library_advisory", "logbook", "top_ta"},
    "github PoC (2026-10-02)": {"github_poc"},
    "feed Twitter (2026-10-02)": {"feed_twitter"},
    "ringkasan CVE baru (2026-10-07)": {"cve_new"},
}  # fmt: skip


def _topics_in(filename: str) -> set[str]:
    for line in (ROOT / filename).read_text().splitlines():
        if line.startswith("TELEGRAM__THREAD_IDS="):
            return set(json.loads(line.split("=", 1)[1]))
    raise AssertionError(f"TELEGRAM__THREAD_IDS tidak ada di {filename}")


def env_topics() -> set[str]:
    return _topics_in(".env.example")


def test_prod_template_declares_exactly_the_same_topics_as_env_example() -> None:
    """Template produksi yang ketinggalan satu topik = `UnknownAlertTopic` di hari pertama prod
    (terjadi: `github_poc` ditambahkan ke satu file saja akan lolos tanpa test ini)."""
    assert _topics_in(".env.prod.template") == env_topics()


def test_every_expected_topic_is_declared_in_env_example() -> None:
    declared = env_topics()
    expected = set().union(*EXPECTED.values())

    assert expected - declared == set(), "topik dipakai kode tapi belum ada di .env.example"
    assert declared - expected == set(), "topik di .env.example tapi tak dipakai (usang?)"


def test_topic_literals_passed_to_alert_functions_are_all_declared() -> None:
    """Pindai sumber: `send_alert("x"`, `send_document("x"`, `send_file("x"`, `topic="x"`,
    `alert_topics.append("x")` -- salah ketik topik baru ketahuan di sini."""
    pattern = re.compile(
        r"""(?:send_alert|send_document|send_file)\(\s*["']([a-z_]+)["']"""
        r"""|\btopic(?:\s*:\s*[\w\[\]]+)?\s*=\s*["']([a-z_]+)["']"""
        r"""|alert_topics\.append\(\s*["']([a-z_]+)["']"""
    )
    found: dict[str, set[str]] = {}
    for base in ("apps", "packages", "scrapers", "tools"):
        for path in (ROOT / base).rglob("*.py"):
            if "site-packages" in path.parts or ".venv" in path.parts:
                continue
            for match in pattern.finditer(path.read_text(encoding="utf-8")):
                topic = next(g for g in match.groups() if g)
                found.setdefault(topic, set()).add(str(path.relative_to(ROOT)))

    unknown = {t: sorted(files) for t, files in found.items() if t not in env_topics()}
    assert unknown == {}, f"topik tak terdaftar di .env.example: {unknown}"
    assert {"notd", "debug", "logbook", "library_advisory"} <= set(
        found
    )  # pemindai memang menemukan


def test_topics_returned_by_tweet_routing_are_declared() -> None:
    source = inspect.getsource(tweet_routing.route_tweet)
    tokens = {t for t in re.findall(r'"([a-z_]+)"', source)} | {tweet_routing.FEED_TOPIC}

    assert tokens - env_topics() == set()
    assert {"zero_day", "data_breach_indo", "vendor_report", "feed_twitter"} <= tokens
