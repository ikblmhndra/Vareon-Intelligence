"""Dua daftar kuratif lagi yang `stages/score.py` (Fase 5) butuh buat
regex-match title/body artikel, gantiin Mongo `threatintel.groups` dan
`news_db.apac-people` -- POLA SAMA kayak `techstack.py`/`tweet.py::
MonitoredAccount`/`ioc_reference.py`: "web kurasi, scraper (di sini:
pipeline enrichment) patuh".

CATATAN: dua tabel ini kosong sampai di-seed. Data kuratif ASLI (nama grup
threat actor, nama tokoh APAC yang dipantau) ada di dump Mongo arsip
(`legacy/dump/threatintel/groups.bson`, `legacy/dump/news_db/apac-people.bson`)
-- di-seed `tools/seed/fase10_reference_data.py` (langkah 6 runbook
cutover; dulu cuma `fase5_reference_data.py` yang gak pernah masuk runbook,
jadi staging kosong -- QA 2026-10-01: 0 dari 325 artikel punya TA). Tanpa
data ini, `mentioned_group`/`mentioned_apac_people` bakal selalu kosong.
Artikel yang masuk sebelum seed: `python -m cti_enrich.backfill`.

`country_list` lama (Mongo `apac-country`+`global-country`, ~150 nama
kuratif) SENGAJA gak ikut di-port jadi tabel baru -- diganti
`pycountry.countries` (seluruh negara anggota ISO 3166-1, superset dari
daftar lama) di `stages/score.py`, sekalian nyelesain kebutuhan konversi
nama->kode ISO yang mention negara (`entities.external_id`) minta. Lihat
docstring `score.py::_country_list`.

`source` (Fase 7.3, router `ta_groups`) -- kolom ketinggalan pas Fase 5
sama alasannya kayak `MonitoredAccount.display_name`/`notes`: tabel ini
awalnya cuma dibaca `score.py`, belum ada jalur TULIS lewat API. Port
`ta_service.list_groups()`/`add_group()`/`get_ta_stats()` (grouping by
source, "manual" vs sumber lain) butuh kolom ini."""

from __future__ import annotations

from sqlalchemy import BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class ThreatActorGroup(TimestampMixin, Base):
    __tablename__ = "threat_actor_groups"
    __table_args__ = (UniqueConstraint("name", name="uq_threat_actor_group_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")


class MonitoredPerson(TimestampMixin, Base):
    """Tokoh APAC yang dipantau (pejabat/figur publik) -- gantiin
    `news_db.apac-people`. Bukan `Client`/`User` -- ini murni dictionary
    nama buat NER/regex matching, bukan akun."""

    __tablename__ = "monitored_people"
    __table_args__ = (UniqueConstraint("name", name="uq_monitored_person_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
