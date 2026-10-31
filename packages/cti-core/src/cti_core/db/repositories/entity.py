"""Helper baca entitas untuk repository (P7c Task 11, plan Decision 4): pembaca tabel link lama
(`article_threat_actors`, `article_ttps`, ...) kini membaca `entity_mentions` join `entities`
lewat SATU subquery, jadi tiap pembaca cukup mengganti referensi kolom.

Pemetaan kolom lama -> kolom `mention_rows()`: nama aktor/malware -> `name`; `ttp_id` ->
`external_id` (nama teknik -> `name`); `country_code` -> `external_id`; `industry` -> `name`
(nama tampilan sektor, plan Decision 3); `cve_id` -> `external_id`; `source` lama -> `method`.

Hanya entitas HIDUP: tidak suppressed (pengganti `ta_whitelist`) dan bukan tombstone merge.
Penulis sudah me-resolve ke entitas hidup, tapi mention lama milik entitas yang kemudian
di-suppress tetap tersimpan (unsuppress memulihkannya, spec 3.4), jadi pembaca yang menyaring.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.sql.selectable import Subquery

from cti_core.db.models.entity import Entity, EntityAlias, EntityMention
from cti_core.entity import alias_norm

ACTOR = "intrusion-set"
TECHNIQUE = "attack-pattern"
COUNTRY = "location"
SECTOR = "identity"
CVE = "vulnerability"
MALWARE_TYPES = ("malware", "tool")


def live_entity() -> ColumnElement[bool]:
    """Entitas yang boleh tampil di pembaca: tidak suppressed dan bukan tombstone."""
    return and_(Entity.suppressed.is_(False), Entity.merged_into_id.is_(None))


def mention_rows(*types: str) -> Subquery:
    """Subquery satu baris per mention entitas hidup, bertipe `types` (kosong = semua tipe).

    Kolom: `article_id, indicator_id, cve_tracker_id, entity_id, name, external_id, type, method,
    matched_alias, role, evidence, extracted`. Mention `identity` di subjek selalu sektor (kelas
    `class`); korban bernama (organisasi) tidak pernah dibaca sebagai industri (Ruling 10).
    Tiap panggilan membuat subquery baru, jadi aman di-join lebih dari sekali dalam satu query."""
    stmt = (
        select(
            EntityMention.article_id,
            EntityMention.indicator_id,
            EntityMention.cve_tracker_id,
            EntityMention.entity_id,
            Entity.name,
            Entity.external_id,
            Entity.type,
            EntityMention.method,
            EntityMention.matched_alias,
            EntityMention.role,
            EntityMention.evidence,
            EntityMention.extracted,
        )
        .join(Entity, Entity.id == EntityMention.entity_id)
        .where(live_entity(), or_(Entity.type != SECTOR, Entity.identity_class == "class"))
    )
    if types:
        stmt = stmt.where(Entity.type.in_(types))
    return stmt.subquery()


def entity_ids_named(types: str | Iterable[str], names: Iterable[str]) -> Select[tuple[int]]:
    """Id entitas hidup bertipe `types` yang punya alias = salah satu `names` (case-insensitive,
    spasi dirapatkan -- `alias_norm`). Nama dari pengguna (filter, PIR, watchlist) dicocokkan
    lewat ini, jadi "apt36" menemukan "Transparent Tribe". Alias entitas yang di-merge sudah
    dipindah ke target (spec 3.4), jadi cukup menyaring entitas hidup."""
    type_list = [types] if isinstance(types, str) else list(types)
    norms = sorted({alias_norm(n) for n in names if n and alias_norm(n)})
    return (
        select(EntityAlias.entity_id)
        .join(Entity, Entity.id == EntityAlias.entity_id)
        .where(
            EntityAlias.entity_type.in_(type_list),
            EntityAlias.alias_norm.in_(norms),
            live_entity(),
        )
    )


def entity_ids_matching_column(type: str, names: Any) -> Select[tuple[int]]:
    """Seperti `entity_ids_named`, tapi nama datang dari kolom tabel lain (`names` = kolom
    ORM, mis. `ThreatActorGroup.name`) -- dinormalisasi di SQL lewat `entity_alias_norm()`
    (kembaran `alias_norm`, Ruling 6), jadi tidak ada daftar bind tak terbatas."""
    return (
        select(EntityAlias.entity_id)
        .join(Entity, Entity.id == EntityAlias.entity_id)
        .where(
            EntityAlias.entity_type == type,
            EntityAlias.alias_norm.in_(select(func.entity_alias_norm(names))),
            live_entity(),
        )
    )
