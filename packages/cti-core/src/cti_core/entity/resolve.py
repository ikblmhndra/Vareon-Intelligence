"""Resolver entitas P7c: nama mentah -> entitas hidup. Kembaran SQL: `entity_resolve()`
(`alembic/versions/entity_model_sql/resolve.sql`); aturan normalisasi dan urutan langkah sama.

Urutan: cari alias `(type, alias_norm)` dan ikuti `merged_into_id`; kalau belum ada, sisipkan
entitas + alias dengan `ON CONFLICT DO NOTHING` lalu baca ulang (aman untuk worker paralel,
tanpa retry berbasis exception). Entitas `suppressed` tetap dikembalikan: pemanggil yang memutuskan.
Nama tampilan mempertahankan huruf besar-kecil pemanggil (spasi dirapatkan); alias baru
memakai `source` pemanggil.
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import Insert, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import ReturningInsert

from cti_core.db.models.entity import Entity, EntityAlias
from cti_core.entity import alias_norm, collapse_ws, entity_stix_id

_MAX_HOPS = 20  # batas rantai merged_into_id; lebih dari ini dianggap siklus


def _lookup(type: str, norm: str) -> Select[tuple[Entity]]:
    return (
        select(Entity)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(EntityAlias.entity_type == type, EntityAlias.alias_norm == norm)
    )


def _by_name(type: str, norm: str) -> Select[tuple[Entity]]:
    return select(Entity).where(
        Entity.type == type, func.lower(Entity.name) == norm, Entity.merged_into_id.is_(None)
    )


def _new_entity(
    type: str, display: str, source: str, external_id: str | None, cls: str | None
) -> ReturningInsert[tuple[int]]:
    return (
        insert(Entity)
        .values(
            type=type,
            stix_id=entity_stix_id(type, display),
            name=display,
            source=source,
            external_id=external_id,
            identity_class=cls,
        )
        .on_conflict_do_nothing()
        .returning(Entity.id)
    )


def _new_alias(entity_id: int, type: str, display: str, norm: str, source: str) -> Insert:
    return (
        insert(EntityAlias)
        .values(
            entity_id=entity_id, entity_type=type, alias=display, alias_norm=norm, source=source
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
    norm = alias_norm(name)

    def find() -> Entity | None:
        found = session.execute(_lookup(type, norm)).scalars().first()
        for _ in range(_MAX_HOPS):
            if found is None or found.merged_into_id is None:
                return found
            found = session.get(Entity, found.merged_into_id)
        raise RuntimeError(f"rantai merge terlalu panjang/siklik untuk {type} {name!r}")

    if (found := find()) is not None:
        return found
    new_id = session.execute(
        _new_entity(type, display, source, external_id, identity_class)
    ).scalar()
    if new_id is None:  # nama sudah dipakai entitas hidup tanpa alias ini
        existing = session.execute(_by_name(type, norm)).scalar_one_or_none()
        if existing is None:
            raise RuntimeError(f"resolve gagal membuat/menemukan {type} {name!r}")
        new_id = existing.id
    session.execute(_new_alias(new_id, type, display, norm, source))
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
    norm = alias_norm(name)

    async def find() -> Entity | None:
        found = (await session.execute(_lookup(type, norm))).scalars().first()
        for _ in range(_MAX_HOPS):
            if found is None or found.merged_into_id is None:
                return found
            found = await session.get(Entity, found.merged_into_id)
        raise RuntimeError(f"rantai merge terlalu panjang/siklik untuk {type} {name!r}")

    if (found := await find()) is not None:
        return found
    new_id = (
        await session.execute(_new_entity(type, display, source, external_id, identity_class))
    ).scalar()
    if new_id is None:
        existing = (await session.execute(_by_name(type, norm))).scalar_one_or_none()
        if existing is None:
            raise RuntimeError(f"resolve gagal membuat/menemukan {type} {name!r}")
        new_id = existing.id
    await session.execute(_new_alias(new_id, type, display, norm, source))
    if (found := await find()) is None:
        raise RuntimeError(f"resolve gagal untuk {type} {name!r}")
    return found
