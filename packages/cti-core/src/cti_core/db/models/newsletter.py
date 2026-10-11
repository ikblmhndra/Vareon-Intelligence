"""Newsletter mingguan (kurasi analis + LLM summarization) -- gantiin
`news_db.newsletters` + `newsletter_paywall_hints`. Fase 7.3 (router
`newsletter`, Bagian 4).

`sections` (JSONB, bukan tabel anak) -- snapshot artikel yang UDAH
diringkas/di-enrich (title/url/source/key_points/summary/iocs/dst) BUKAN
data relasional yang perlu di-query per-field, murni presentasi arsip
histori ("kartu apa yang ditampilin newsletter minggu X") -- sama alasan
kayak `TAProfile.profile`. `html` juga disimpen utuh (arsip lengkap,
`GET /{id}/html`/`resend` baca langsung dari sini).

**`include_clusters` (fitur campaign clustering) SENGAJA belum diport**
-- itu butuh `cluster_service.py` (784 baris, TF-IDF + Jaccard similarity
buat ngelompokin artikel jadi "campaign"), fitur BERDIRI SENDIRI yang
gak ada di daftar 27 router manapun (dipakai OPSIONAL sama `newsletter`
DAN `mindmap`, tapi bukan salah satu dari keduanya). `campaign_clusters`
di context newsletter SELALU list kosong buat sekarang -- template
Jinja udah nge-guard `{% if campaign_clusters %}`, jadi render tetep
valid, cuma seksi itu gak pernah muncul. Port beneran nyusul kalau
`cluster_service.py` dikerjain (kemungkinan Fase 7.4, di luar scope
per-router Fase 7.3)."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base


class Newsletter(Base):
    __tablename__ = "newsletters"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    """Minggu ISO dari WAKTU PEMBUATAN, bukan jendela yang diliput. Tetap NOT NULL dan tetap
    diisi baris baru supaya baris lama dan UI histori yang masih membaca "Week N, YYYY" jalan."""
    period_start: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    """Jendela yang diliput edisi ini (bulan kalender sebelumnya secara default). NULL di baris
    sebelum kolom ini ada; label tampilannya lalu jatuh ke "Week N, YYYY"."""
    generated_at: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    html: Mapped[str] = mapped_column(Text, nullable=False)
    sections: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """{highlight, apac, global_news, indonesia} -- masing-masing snapshot
    artikel yang di-strip (`_strip_article` lama), lihat docstring modul."""


class NewsletterPaywallHint(Base):
    """Sumber yang kedetek paywall pas `fetch_article_body()` -- dipakai
    UI buat kasih hint "kemungkinan paywall" di daftar sumber, BUKAN
    dipakai buat skip fetch (fetch tetap dicoba tiap kali, hint cuma
    informational). Port apa adanya."""

    __tablename__ = "newsletter_paywall_hints"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    paywall_likely: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_seen: Mapped[str] = mapped_column(String(40), nullable=False)


class NewsletterArticleSummary(Base):
    """Cache ringkasan per artikel (dan bahasa) buat `preview`/`draft-email` newsletter.

    Dulu tiap build mengulang fetch Playwright + satu panggilan LLM per artikel (~10-13 detik
    sendiri), dan `preview` + `draft-email` masing-masing membangun ulang semuanya. Sekarang
    hasilnya disimpan di sini: baris yang ada = tanpa fetch dan tanpa LLM.

    `iocs` dan `cve_ids` ikut di-cache karena keduanya berasal dari BODY yang di-fetch: tanpa
    keduanya, langkah draft yang menulis IOC dan sebutan CVE harus fetch halamannya lagi.
    `cve_ids` = semua CVE id di judul + body SEBELUM disaring true-positive; irisan dengan set
    true-positive dihitung saat build, bukan di-cache, karena set itu berubah (FP ditandai,
    CVE baru di-track) sementara isi artikel tidak.

    `language` ikut kunci supaya edisi bahasa lain tidak menimpa. Prompt saat ini menghasilkan
    bahasa Inggris, jadi semua baris `en` sampai PR bahasa Indonesia."""

    __tablename__ = "newsletter_article_summaries"
    __table_args__ = (
        UniqueConstraint("article_id", "language", name="uq_newsletter_article_summary"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    key_points: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_source: Mapped[str] = mapped_column(String(20), nullable=False)
    """`fetched` (dari body halaman) atau `metadata` (halaman tak terbaca/paywall, ringkasan
    ditulis dari metadata artikel; mudah salah, jadi UI perlu bisa menandainya)."""
    iocs: Mapped[dict[str, list[str]]] = mapped_column(JSONB, nullable=False, default=dict)
    cve_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    token_usage: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False, default=dict)
    """`{}` kalau gateway LLM tidak mengembalikan `usage` (gateway dev kadang begitu)."""
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Waktu ringkasan ini DIBUAT; `regenerate` menimpa baris dan mengisinya ulang."""
