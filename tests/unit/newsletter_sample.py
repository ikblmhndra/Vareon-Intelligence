"""Konteks edisi newsletter yang TETAP (data contoh dari mockup
`docs/mockups/newsletter-redesign.html`) untuk test template: snapshot HTML, aturan klien email,
dan render di browser (`playwright`).

Tangan-bangun, tanpa DB dan tanpa jam: `build_newsletter_context()` dites sendiri di
`test_newsletter_summary_cache.py`. Di sini yang diuji adalah template, jadi konteksnya harus
persis sama tiap run supaya snapshot tidak bergeser."""

from __future__ import annotations

import datetime
from typing import Any

from cti_api.services import newsletter_edition as edition

START = datetime.date(2026, 10, 1)
END = datetime.date(2026, 10, 31)

INTRO = (
    "<p>Oktober didominasi aktivitas ransomware terhadap penyedia layanan terkelola di Asia "
    "Pasifik. Kelompok-kelompok yang terlibat masuk lewat kredensial VPN yang bocor tanpa "
    "autentikasi multifaktor.</p>"
    "<p>Pada saat yang sama, dua CVE pada perangkat VPN populer masuk daftar KEV.</p>"
)


def card(
    article_id: int,
    title: str,
    source: str,
    day: int,
    news_type: str,
    *,
    key_points: tuple[str, ...] = (),
    summary: str = "",
    countries: tuple[str, ...] = (),
    industries: tuple[str, ...] = (),
    actors: tuple[str, ...] = (),
    cves: tuple[str, ...] = (),
    note: str = "",
) -> dict[str, Any]:
    """Satu artikel kartu penuh, bentuk keluaran `_enrich_articles` (+ catatan analis bila ada)."""
    article: dict[str, Any] = {
        "id": article_id,
        "title": title,
        "url": f"https://example.com/{article_id}",
        "source": source,
        "posted_on": f"2026-10-{day:02d}",
        "news_type": news_type,
        "key_points": list(key_points),
        "summary": summary,
        "victim_countries": list(countries),
        "impacted_industries": list(industries),
        "threat_actors": list(actors),
        "cve_mentions": list(cves),
    }
    if note:
        article["analyst_note"] = note
    return article


def row(article_id: int, title: str, source: str, day: int, news_type: str) -> dict[str, Any]:
    """Satu baris compact ("Also Noted"), bentuk keluaran `_compact_entry` tanpa cache."""
    return {
        "id": article_id,
        "title": title,
        "url": f"https://example.com/{article_id}",
        "source": source,
        "posted_on": f"2026-10-{day:02d}",
        "news_type": news_type,
    }


def sample_context(**overrides: Any) -> dict[str, Any]:
    """Konteks lengkap: satu highlight, dua kartu APAC + empat baris compact, satu kartu Global +
    tiga baris compact, satu kartu Indonesia, satu klaster kampanye, dan Executive Summary."""
    highlight = card(
        1,
        "Kelompok ransomware contoh menargetkan penyedia layanan terkelola di Asia Pasifik",
        "Contoh Sumber",
        20,
        "Ransomware",
        key_points=(
            "Akses awal lewat kredensial VPN yang bocor, tanpa autentikasi multifaktor.",
            "Data dicuri sebelum enkripsi, lalu dipakai untuk pemerasan ganda.",
        ),
        summary="Penyerang memakai akun administrator yang sama di banyak pelanggan.",
        countries=("Australia",),
        industries=("Layanan TI",),
        actors=("Contoh Group",),
        note="Periksa akun layanan pihak ketiga di VPN kita.\nBaris kedua catatan.",
    )
    context: dict[str, Any] = {
        "week": 45,
        "year": 2026,
        "generated_at": "2026-11-02 02:00 UTC",
        "period_start": START,
        "period_end": END,
        "period_label": edition.period_label(START, END),
        "period_range": edition.period_range(START, END),
        "published_label": edition.long_date(datetime.date(2026, 11, 2)),
        "language": "id",
        "highlight": highlight,
        "highlights": [highlight],
        "apac": [
            card(
                2,
                "Kampanye phishing bertema pajak menyasar instansi di Asia Tenggara",
                "Contoh Sumber B",
                19,
                "Phishing",
                key_points=(
                    "Email berisi tautan ke halaman login palsu portal pajak.",
                    "Domain didaftarkan kurang dari seminggu sebelum kampanye.",
                ),
                summary="Kampanye ini memakai kit phishing yang sama dengan serangan bulan lalu.",
                countries=("Singapura",),
                industries=("Pemerintahan",),
            ),
            card(
                3,
                "Eksploitasi aktif pada perangkat VPN populer, CVE masuk daftar KEV",
                "Contoh Sumber C",
                21,
                "Kerentanan",
                summary="Vendor merilis pembaruan darurat; perangkat lama dipindai secara massal.",
                cves=("CVE-2026-00000",),
            ),
        ],
        "global_news": [
            card(
                4,
                "Rantai pasok paket sumber terbuka disusupi lewat akun pengelola",
                "Contoh Sumber D",
                17,
                "Rantai pasok",
                summary="Versi berbahaya sebuah pustaka populer mencuri token build dari CI.",
                industries=("Perangkat Lunak",),
            )
        ],
        "indonesia": [
            card(
                5,
                "Kebocoran data sebuah layanan daring dilaporkan, data dijual di forum",
                "Contoh Sumber E",
                18,
                "Kebocoran data",
                summary="Pelaku mengklaim memegang jutaan catatan pengguna.",
                countries=("Indonesia",),
                industries=("Layanan Digital",),
            )
        ],
        "apac_compact": [
            row(
                10,
                "Peretas menargetkan penyedia telekomunikasi regional",
                "Contoh Sumber F",
                22,
                "Intrusion",
            ),
            row(
                11,
                "Pemerintah mengumumkan aturan baru pelaporan insiden siber",
                "Contoh Sumber G",
                15,
                "Regulasi",
            ),
            row(
                12,
                "Kelompok pemeras mengklaim data sebuah rumah sakit",
                "Contoh Sumber H",
                12,
                "Ransomware",
            ),
            row(
                13,
                "Pembaruan keamanan bulanan menutup 14 celah",
                "Contoh Sumber I",
                8,
                "Kerentanan",
            ),
        ],
        "global_news_compact": [
            row(
                14,
                "Botnet baru memanfaatkan kamera IP yang belum diperbarui",
                "Contoh Sumber J",
                24,
                "Malware",
            ),
            row(
                15,
                "Operasi penegak hukum membongkar layanan phishing-as-a-service",
                "Contoh Sumber K",
                16,
                "Penindakan",
            ),
            row(
                16,
                "Laporan tahunan menyebut kredensial curian sebagai penyebab utama",
                "Contoh Sumber L",
                9,
                "Riset",
            ),
        ],
        "indonesia_compact": [],
        "campaign_clusters": [
            {
                "name": "Ransomware terhadap penyedia layanan terkelola",
                "size": 31,
                "first_seen": "2026-10-06",
                "last_seen": "2026-10-27",
                "dominant_tas": ["Contoh Group"],
                "attack_techniques": ["T1486", "T1078"],
                "cve_ids": ["CVE-2026-00000"],
            }
        ],
        "custom_css": "",
        "custom_intro": INTRO,
        "custom_footer": "",
    }
    context.update(overrides)
    return context
