"""Resolver entitas P7c: nama mentah -> entitas hidup. Kembaran SQL: `entity_resolve()`
(`alembic/versions/entity_model_sql/resolve.sql`); aturan normalisasi dan urutan langkah sama.

Urutan: cari alias `(type, alias_norm)` dan ikuti `merged_into_id`; kalau belum ada, sisipkan
entitas + alias dengan `ON CONFLICT DO NOTHING` lalu baca ulang (aman untuk worker paralel,
tanpa retry berbasis exception). `stix_id` uuid5 yang sudah dipakai (tombstone merge, entitas
yang di-rename lalu alias lamanya dihapus) diganti uuid4, sama dengan split di `merge.py`; insert
yang bentrok di `(type, external_id)` (mis. analis membuat "Log4Shell" ber-external_id CVE, lalu
artikel menyebut CVE itu) menempelkan alias ke entitas hidup pemilik external_id tsb.
Entitas `suppressed` tetap dikembalikan: pemanggil yang memutuskan.
Nama tampilan mempertahankan huruf besar-kecil pemanggil (spasi dirapatkan); alias baru
memakai `source` pemanggil, atau `legacy` bila itu bukan sumber alias (cve, iso, sector,
ransomware; P7c Task 8).

`attack-pattern` (Ruling 7): identitas = id teknik, karena nama ATT&CK tidak unik (sub-teknik di
induk berbeda, lintas domain). `external_id` wajib; alias satu-satunya = id teknik, `stix_id`
diturunkan dari id itu, `name` tetap nama tampilan. Kembaran SQL: `entity_resolve_technique()`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import ReturningInsert

from cti_core.db.models.entity import Entity, EntityAlias
from cti_core.entity import ALIAS_SOURCES, alias_norm, collapse_ws, entity_stix_id

_MAX_HOPS = 20  # batas rantai merged_into_id; lebih dari ini dianggap siklus
TECHNIQUE = "attack-pattern"


def _key(type: str, name: str, external_id: str | None) -> str:
    """Teks yang jadi alias/kunci identitas: nama, atau id teknik untuk attack-pattern."""
    if type != TECHNIQUE:
        return name
    if not external_id or not collapse_ws(external_id):
        raise ValueError("attack-pattern butuh external_id (id teknik)")
    return external_id.upper()  # id teknik ATT&CK selalu huruf besar (T1566.001)


def _lookup(type: str, norm: str) -> Select[tuple[Entity]]:
    return (
        select(Entity)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(EntityAlias.entity_type == type, EntityAlias.alias_norm == norm)
    )


def _by_name(type: str, norm: str, key: str) -> Select[tuple[int]]:
    match = Entity.external_id == key if type == TECHNIQUE else func.lower(Entity.name) == norm
    return select(Entity.id).where(Entity.type == type, match, Entity.merged_into_id.is_(None))


def _by_external_id(type: str, external_id: str) -> Select[tuple[int]]:
    return select(Entity.id).where(
        Entity.type == type, Entity.external_id == external_id, Entity.merged_into_id.is_(None)
    )


def _stix_taken(stix: str) -> Select[tuple[int]]:
    return select(Entity.id).where(Entity.stix_id == stix)


def _fresh_stix(type: str, key: str, taken: bool) -> str:
    """uuid5 dari kunci; uuid4 kalau uuid5 itu sudah dipakai entitas lain (tombstone/rename)."""
    return f"{type}--{uuid.uuid4()}" if taken else entity_stix_id(type, key)


def _new_entity(
    type: str, display: str, stix: str, source: str, external_id: str | None, cls: str | None
) -> ReturningInsert[tuple[int]]:
    return (
        insert(Entity)
        .values(
            type=type,
            stix_id=stix,
            name=display,
            source=source,
            external_id=external_id,
            identity_class=cls,
        )
        .on_conflict_do_nothing()
        .returning(Entity.id)
    )


def _new_alias(entity_id: int, type: str, display: str, norm: str, source: str) -> Insert:
    # sumber entitas yang bukan sumber alias (cve, iso, sector, ransomware) -> alias `legacy`,
    # sama dengan backfill migrasi (CHECK `entity_aliases.source`)
    alias_source = source if source in ALIAS_SOURCES else "legacy"
    return (
        insert(EntityAlias)
        .values(
            entity_id=entity_id,
            entity_type=type,
            alias=display,
            alias_norm=norm,
            source=alias_source,
        )
        .on_conflict_do_nothing()
    )


def resolve(
    session: Session,
    type: str,
    name: str,
    *,
    source: str,
    external_id: str | None = None,
    identity_class: str | None = None,
) -> Entity:
    display = collapse_ws(name)
    key = collapse_ws(_key(type, name, external_id))
    if type == TECHNIQUE:
        external_id = key
    norm = alias_norm(key)

    def find() -> Entity | None:
        found = session.execute(_lookup(type, norm)).scalars().first()
        for _ in range(_MAX_HOPS):
            if found is None or found.merged_into_id is None:
                return found
            found = session.get(Entity, found.merged_into_id)
        raise RuntimeError(f"rantai merge terlalu panjang/siklik untuk {type} {name!r}")

    if (found := find()) is not None:
        return found
    taken = session.execute(_stix_taken(entity_stix_id(type, key))).first() is not None
    stix = _fresh_stix(type, key, taken)
    new_id = session.execute(
        _new_entity(type, display, stix, source, external_id, identity_class)
    ).scalar()
    if new_id is None:  # nama/external_id sudah dipakai entitas hidup tanpa alias ini
        new_id = session.execute(_by_name(type, norm, key)).scalar_one_or_none()
        if new_id is None and external_id:
            new_id = session.execute(_by_external_id(type, external_id)).scalar_one_or_none()
        if new_id is None:
            raise RuntimeError(f"resolve gagal membuat/menemukan {type} {name!r}")
    session.execute(_new_alias(new_id, type, key, norm, source))
    if (found := find()) is None:
        raise RuntimeError(f"resolve gagal untuk {type} {name!r}")
    return found


async def resolve_async(
    session: AsyncSession,
    type: str,
    name: str,
    *,
    source: str,
    external_id: str | None = None,
    identity_class: str | None = None,
) -> Entity:
    display = collapse_ws(name)
    key = collapse_ws(_key(type, name, external_id))
    if type == TECHNIQUE:
        external_id = key
    norm = alias_norm(key)

    async def find() -> Entity | None:
        found = (await session.execute(_lookup(type, norm))).scalars().first()
        for _ in range(_MAX_HOPS):
            if found is None or found.merged_into_id is None:
                return found
            found = await session.get(Entity, found.merged_into_id)
        raise RuntimeError(f"rantai merge terlalu panjang/siklik untuk {type} {name!r}")

    if (found := await find()) is not None:
        return found
    taken = (await session.execute(_stix_taken(entity_stix_id(type, key)))).first() is not None
    stix = _fresh_stix(type, key, taken)
    new_id = (
        await session.execute(_new_entity(type, display, stix, source, external_id, identity_class))
    ).scalar()
    if new_id is None:
        new_id = (await session.execute(_by_name(type, norm, key))).scalar_one_or_none()
        if new_id is None and external_id:
            new_id = (
                await session.execute(_by_external_id(type, external_id))
            ).scalar_one_or_none()
        if new_id is None:
            raise RuntimeError(f"resolve gagal membuat/menemukan {type} {name!r}")
    await session.execute(_new_alias(new_id, type, key, norm, source))
    if (found := await find()) is None:
        raise RuntimeError(f"resolve gagal untuk {type} {name!r}")
    return found
