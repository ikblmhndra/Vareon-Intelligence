"""`article_cves` -- CVE id yang disebut sebuah artikel (judul atau isi).

Dulu CVE disimpan sebagai IOC bertipe `cve`; itu salah tempat (CVE bukan indikator jaringan,
tanpa decay/feedback/enrichment yang bermakna). Tabel ini cuma relasi artikel -> CVE.
"""

from __future__ import annotations

import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base


class ArticleCve(Base):
    __tablename__ = "article_cves"
    __table_args__ = (Index("ix_article_cves_cve_id", "cve_id"),)

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    cve_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    """Huruf besar, mis. `CVE-2026-1234`."""
    in_title: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
