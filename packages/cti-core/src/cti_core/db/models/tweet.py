"""X/Twitter intel -- gantiin `news_db.tweets` + `monitored_accounts`.

`monitored_accounts` itu salah satu dari TIGA pola "web kurasi, scraper
patuh" yang udah kebukti bagus di sistem lama (dua lainnya: ioc_allowlist,
techstack) -- lihat plan §8.3. Framework baru men-generalisasi pola ini,
bukan cuma niruin.

Field hasil regex-scan (`scan_results`) sengaja JSONB, BUKAN tabel anak --
beda dari Article yang dinormalisasi penuh. Alasannya: ini hasil pencocokan
regex sekali pakai dari `monitorX.py:33-90` buat satu tweet, bukan data
relasional yang perlu di-query lintas baris (gak ada use case "semua tweet
yang nyebut Indonesia sebagai victim" yang butuh index terpisah, beda sama
Article.countries yang emang butuh itu).
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class MonitoredAccount(TimestampMixin, Base):
    __tablename__ = "monitored_accounts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """Kolom yang kepake router `monitored_accounts.py` (Fase 7.3) tapi
    belum ada di skema Fase 5 -- tabelnya waktu itu cuma dibaca scraper
    (`monitorX.py`), belum ada jalur TULIS lewat API."""


class Tweet(TimestampMixin, Base):
    __tablename__ = "tweets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tweet_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    author_username: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    author_name: Mapped[str | None] = mapped_column(String(200))
    author_avatar: Mapped[str | None] = mapped_column(Text)
    author_followers: Mapped[int | None] = mapped_column(Integer)

    source: Mapped[str] = mapped_column(
        String(100), nullable=False, default="monitor_x", server_default="monitor_x"
    )
    """`scraper_id` yang PERTAMA menyimpan tweet ini (`monitor_x`, `tweet_alerts_1h`,
    `tweet_alerts_30m`); tweet yang sudah ada tidak diperbarui (insert-only), jadi ini bukan
    "pernah di-alert". Dipakai `tweet_last_seen_ids` (cuma baris `monitor_x`): tanpa itu, tweet
    alert yang lebih baru menggeser `since_id` `monitor_x` dan tweet yang ditolak filter alert
    tidak pernah terambil. Baris lama bernilai `monitor_x` (dulu satu-satunya penulis)."""

    posted_on: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    lang: Mapped[str | None] = mapped_column(String(10))
    media_urls: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scan_results: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """apac_indicator, mentioned_group, mentioned_apac_country,
    mentioned_apac_people, cve_list, zero_day_list, databreach_list,
    ot_status, report_status -- lihat monitorX.py:33-90."""

    confidence_score: Mapped[int | None] = mapped_column(SmallInteger)
    confirmed_incident: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    industries_impacted: Mapped[list[str]] = mapped_column(
        ARRAY(String(150)), nullable=False, default=list
    )
    victim_countries: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, default=list
    )
    actor_countries: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, default=list
    )
    victim_name: Mapped[str | None] = mapped_column(String(300))
    incident_confidence: Mapped[int | None] = mapped_column(SmallInteger)
    incident_indicators: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)), nullable=False, default=list
    )
    """Fase 5: field LLM (`cti_enrich.stages.classify.classify()`, SATU
    client yang sama dipakai `nlp_scan()`) yang ketinggalan pas Fase 2 --
    dulu cuma `confidence_score`/`confirmed_incident` yang ke-port. Array
    Postgres (bukan JSONB) karena ini daftar string pendek yang gak butuh
    query per-elemen, beda sama `Article.countries` yang emang perlu
    dinormalisasi -- lihat catatan `scan_results` di atas soal alasan
    serupa (satu tweet, sekali pakai, gak ada "semua tweet yang..." query)."""
