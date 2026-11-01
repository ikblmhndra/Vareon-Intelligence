"""MITRE ATT&CK katalog (technique/tactic/mitigation/group/software +
relationship) -- gantiin `attack_techniques`/`attack_tactics`/
`attack_mitigations`/`attack_groups`/`attack_software`/
`attack_relationships`/`attack_sync_log` (Mongo). Bagian 3 (survei 21
router sisa, docs/PROGRESS.md) -- prasyarat `ta_groups`/`mitre`/`crossref`,
sama pola dependency kayak `techstack` sebelum `cve`.

Isi tabel ini diisi SATU-SATUNYA lewat `sync_domain()` (fetch bundel STIX
dari GitHub `mitre/cti`) -- gak ada scraper/enrichment yang nulis ke sini.

`stix_id` (bukan `attack_id`/`group_id`/dst) yang jadi kunci upsert --
port persis `_id: obj["id"]` Mongo lama (STIX object id, UUID-prefixed-
by-type, unik lintas bundel). `attack_id`/`group_id`/dst (kode manusia-
readable "T1059"/"G0016") SENGAJA gak diberi UNIQUE constraint -- kode
lama juga gak menjaminnya unik lintas domain (Enterprise/ICS/Mobile
masing-masing bundel STIX terpisah).

`domains` (ARRAY, bukan tabel anak) -- port `$addToSet: {domains: ...}`
Mongo lama. Dalam praktiknya biasanya cuma satu elemen (STIX id gak
pernah reused lintas domain bundel MITRE), tapi mekanismenya (upsert by
stix_id + tambah ke set) dipertahankan apa adanya, bukan disederhanain
jadi kolom `domain` tunggal berdasarkan asumsi soal data MITRE yang bisa
aja berubah.

Field list-of-string lain (`tactics`/`platforms`/`data_sources`/
`aliases`) juga ARRAY, bukan tabel anak -- gak ada use case "semua
technique yang punya platform X" yang butuh index terpisah di sini
(beda dari mention aktor artikel yang emang query-heavy), pola sama
kayak `Tweet.industries_impacted` dkk."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class AttackTechnique(TimestampMixin, Base):
    __tablename__ = "attack_techniques"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    attack_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tactics: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)
    is_subtechnique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_id: Mapped[str | None] = mapped_column(String(20))
    """`attack_id` parent (mis. "T1059" buat "T1059.001") -- string derivasi
    apa adanya, BUKAN FK. Parent bisa aja belum ke-sync (sync per-domain
    independen), jadi validasi referensial gak dipaksakan di sini."""
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    created: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    modified: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    platforms: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)
    data_sources: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, default=list
    )
    detection: Mapped[str] = mapped_column(Text, nullable=False, default="")
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)


class AttackTechniqueAlias(TimestampMixin, Base):
    """Technique REVOKED dari bundel STIX (`revoked: true`, mis. T1086
    "PowerShell" -> T1059.001, T1193 "Spearphishing Attachment" ->
    T1566.001). `attack_techniques` SENGAJA gak nyimpen objek revoked (UI
    ATT&CK DB cuma nampilin yang aktif), tapi nama/ID lamanya masih sering
    dipakai LLM -- tabel ini yang dipakai `cti_core.attack_ttp` buat
    memetakan nama/ID lama ke technique penggantinya (QA BUG-C01).

    `revoked_by_stix_id` dari relationship `revoked-by` di bundel yang
    sama; dipetakan ke `attack_id` pengganti saat katalog dibangun (join ke
    `attack_techniques.stix_id`), bukan FK -- sama alasan `parent_id`."""

    __tablename__ = "attack_technique_aliases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    attack_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    revoked_by_stix_id: Mapped[str | None] = mapped_column(String(100))
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)


class AttackTactic(TimestampMixin, Base):
    __tablename__ = "attack_tactics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    tactic_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shortname: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)


class AttackMitigation(TimestampMixin, Base):
    __tablename__ = "attack_mitigations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    mitigation_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    modified: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)


class AttackGroup(TimestampMixin, Base):
    __tablename__ = "attack_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    group_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    modified: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)


class AttackSoftware(TimestampMixin, Base):
    __tablename__ = "attack_software"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    software_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    software_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    platforms: Mapped[list[str]] = mapped_column(ARRAY(String(50)), nullable=False, default=list)
    modified: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    domains: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)


class AttackRelationship(Base):
    """Port `attack_relationships` -- `source_ref`/`target_ref` nunjuk ke
    `stix_id` di atas via MATCHING STRING, bukan FK asli (relationship
    bisa nunjuk STIX id yang belum/gak pernah ke-sync sebagai baris
    sendiri, mis. `identity`/`campaign` objek yang gak kita simpan)."""

    __tablename__ = "attack_relationships"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stix_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    source_ref: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    target_ref: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    domain: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    """SATU domain (bukan array) -- port apa adanya, `sync_domain()` lama
    nge-`delete_many({"domain": stix_domain})` + tulis ulang penuh tiap
    sync (relationship gak di-upsert-merge kayak technique/group/dst)."""


class AttackSyncLog(Base):
    """Port `attack_sync_log` -- status + progress live per domain sync
    (`status`: never|syncing|success|error). `domain_key` sebagai PK
    natural (3 baris tetap: enterprise/ics/mobile), sama pola `Client.
    client_id`."""

    __tablename__ = "attack_sync_log"

    domain_key: Mapped[str] = mapped_column(String(20), primary_key=True)
    domain: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    label: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="never")
    version: Mapped[str | None] = mapped_column(String(20))
    mitre_modified: Mapped[str | None] = mapped_column(String(40))
    last_attempted: Mapped[str | None] = mapped_column(String(40))
    last_sync: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text)
    phase: Mapped[str | None] = mapped_column(String(30))
    bytes_downloaded: Mapped[int | None] = mapped_column(BigInteger)
    bytes_total: Mapped[int | None] = mapped_column(BigInteger)
    download_pct: Mapped[str | None] = mapped_column(String(10))
    technique_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tactic_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mitigation_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    group_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    software_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    relationship_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    delta_technique_count: Mapped[int | None] = mapped_column(BigInteger)
    delta_group_count: Mapped[int | None] = mapped_column(BigInteger)
    delta_software_count: Mapped[int | None] = mapped_column(BigInteger)
    delta_mitigation_count: Mapped[int | None] = mapped_column(BigInteger)
