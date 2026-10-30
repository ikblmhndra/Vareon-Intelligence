"""Tiga tabel pendukung router `ta_groups` (Fase 7.3, Bagian 3) --
gantiin Mongo `ta_whitelist`/`ta_watchlist`/`ta_profiles`. Nama grup
threat actor sendiri (list utama, kurasi buat `mentioned_group` matching
`cti_enrich.stages.score`) TETAP `ThreatActorGroup`
(`db/models/threat_reference.py`, Fase 5) -- BUKAN tabel baru di sini,
biar gak ada dua sumber kebenaran buat daftar nama TA yang sama (satu
dipakai enrichment, satu dipakai admin UI) kayak yang keliatan kalau
dibikin tabel baru terpisah.

`TAWhitelistEntry` -- daftar nama yang SENGAJA DITOLAK jadi TA group
(dicek `add_group()` sebelum insert, diisi otomatis pas `delete_group()`)
-- bukan "whitelist" dalam arti diizinkan, lebih ke suppression list.
Global, gak per-client (kode lama juga gak nge-scope ini).

`TAWatchlistEntry` -- per-client, daftar TA yang lagi dipantau aktif
analis (beda dari `ThreatActorGroup` yang cuma dictionary nama buat
matching, watchlist ini urusan prioritas monitoring per tenant).

`TAProfile` -- profil terstruktur hasil LLM (`generate_ta_profile()`,
system prompt gede di `ta_profile_service.py` lama), JSONB buat isi
profil (15+ section bersarang: identity/motivation/capability_assessment/
dst) -- CAIR (schema LLM, bisa berubah antar versi prompt), bukan
relasional yang perlu di-query per-field. `actor_name` kolom asli
(bukan di dalam JSONB) karena itu yang dipakai buat lookup/upsert."""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class TAWhitelistEntry(Base):
    __tablename__ = "ta_whitelist"
    __table_args__ = ({"info": {"compat_view": True}},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    """Disimpen LOWERCASE -- port apa adanya (`name.lower()` di kode lama,
    baik pas `add_group()` nge-cek maupun `delete_group()` nge-isi)."""
    added_date: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TAWatchlistEntry(TimestampMixin, Base):
    __tablename__ = "ta_watchlist"
    __table_args__ = ({"info": {"compat_view": True}},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False, index=True
    )


class TAProfile(Base):
    __tablename__ = "ta_profiles"
    __table_args__ = ({"info": {"compat_view": True}},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """Seluruh hasil JSON LLM (`profile_metadata`/`identity`/`motivation`/
    `targeting_profile`/`capability_assessment`/`infrastructure`/
    `campaign_history`/`detection_and_defense`/`organizational_relevance`/
    `intelligence_gaps`/`references`) -- schema di `ta_profile_service.py`
    lama (`_SYSTEM_PROMPT`), disimpen utuh apa adanya, gak dipecah kolom."""
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
