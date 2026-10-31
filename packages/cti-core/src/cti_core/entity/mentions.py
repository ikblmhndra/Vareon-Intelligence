"""Penulisan `entity_mentions` lewat resolver (P7c Task 8, spec 4.3): satu jalur untuk pipeline,
backfill, analis (IOC) dan perintah sekali jalan, menggantikan tabel link lama.

Aturan identitas sama dengan backfill migrasi (`alembic/versions/entity_model_sql/backfill.sql`):
- negara: `location` lewat kode ISO alpha-2 (`external_id`); kode tak dikenal -> lokasi legacy
  dengan nama = kode;
- sektor: `identity` kelas `class`; label lama lewat `sector_for_label`, "General" tidak
  menghasilkan mention, label tak dikenal -> sektor legacy dengan nama = label;
- CVE: `vulnerability` dengan nama = `external_id` = id CVE;
- teknik: `attack-pattern` lewat id teknik (Ruling 7).
Entitas suppressed tidak pernah mendapat mention ("tidak pernah dicocokkan"). Resolver mengikuti
`merged_into_id`, jadi mention tidak pernah ditulis ke tombstone; id entitas sengaja tidak
di-cache lintas transaksi.
"""

from __future__ import annotations

import datetime
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import ColumnElement, Select, and_, delete, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete, ReturningInsert

from cti_core.db.models.entity import Entity, EntityMention
from cti_core.entity import alias_norm, collapse_ws
from cti_core.entity.countries import ISO_COUNTRY_NAMES
from cti_core.entity.resolve import resolve, resolve_async
from cti_core.entity.sectors import SECTORS, sector_for_label

log = structlog.get_logger()

# Atribut ORM `Article` yang membaca mention (langsung atau lewat view kompatibilitas); di-expire
# sesudah tulis Core supaya pembaca di sesi yang sama melihat keadaan baru.
ARTICLE_MENTION_ATTRS = ("mentions", "countries", "industries", "threat_actors", "ttps", "malware")

# Sumber entitas baru per tipe bila nama belum dikenal (spec 3.1 `entities.source`).
_NEW_SOURCE = {
    "intrusion-set": "dictionary",
    "malware": "dictionary",
    "tool": "dictionary",
    "attack-pattern": "legacy",
    "vulnerability": "cve",
    "campaign": "legacy",
}


@dataclass(frozen=True)
class MentionInput:
    """Satu sebutan entitas. `name` = nama/alias yang di-resolve (untuk `location`: kode ISO,
    untuk `attack-pattern`: nama tampilan bila teknik baru); `matched_alias` = teks yang
    menghasilkan sebutan (disimpan apa adanya, membuat split eksak)."""

    type: str
    name: str
    method: str
    matched_alias: str
    role: str | None = None
    evidence: str | None = None
    extracted: dict[str, Any] | None = None
    external_id: str | None = None


def sector_mention(label: str, method: str) -> MentionInput | None:
    """Label industri lama -> mention sektor; None untuk "General"/kosong (spec 3.3)."""
    clean = collapse_ws(label or "")
    if alias_norm(clean) in ("", "general"):
        return None
    sec = sector_for_label(clean)
    if sec is not None:
        return MentionInput("identity", SECTORS[sec], method, clean, external_id=sec)
    return MentionInput("identity", clean, method, clean)


def country_mention(code: str, role: str | None, method: str) -> MentionInput | None:
    clean = (code or "").strip().upper()
    if not clean:
        return None
    return MentionInput("location", clean, method, clean, role=role, external_id=clean)


def cve_mention(cve_id: str, method: str, *, in_title: bool) -> MentionInput | None:
    clean = (cve_id or "").strip().upper()
    if not clean:
        return None
    return MentionInput(
        "vulnerability", clean, method, clean, extracted={"in_title": in_title}, external_id=clean
    )


def _location_stmt(code: str) -> Select[tuple[Entity]]:
    return select(Entity).where(
        Entity.type == "location", Entity.external_id == code, Entity.merged_into_id.is_(None)
    )


def _resolve_kwargs(hit: MentionInput) -> tuple[str, dict[str, Any]]:
    """Nama + argumen `resolve()` untuk tipe selain `location`."""
    if hit.type == "identity":  # mention identitas di subjek = sektor
        known = hit.external_id in SECTORS
        return hit.name, {
            "source": "sector" if known else "legacy",
            "external_id": hit.external_id if known else None,
            "identity_class": "class",
        }
    source = "analyst" if hit.method == "analyst" else _NEW_SOURCE.get(hit.type, "legacy")
    if hit.type in ("attack-pattern", "vulnerability"):
        return hit.name or (hit.external_id or ""), {
            "source": source,
            "external_id": hit.external_id,
        }
    return hit.name, {"source": source}


def _location_new(code: str) -> tuple[str, dict[str, Any]]:
    if code in ISO_COUNTRY_NAMES:
        return ISO_COUNTRY_NAMES[code], {"source": "iso", "external_id": code}
    return code, {"source": "legacy", "external_id": code}


def _usable(ent: Entity | None) -> Entity | None:
    return None if ent is None or ent.suppressed else ent


def _sector_only(hit: MentionInput, ent: Entity | None) -> Entity | None:
    """Mention identitas di subjek = sektor. Label yang resolve ke organisasi (korban bernama
    sama) dibuang dan dicatat, cermin Ruling 10 (korban bernama sektor tidak ditautkan)."""
    if hit.type != "identity" or ent is None or ent.identity_class == "class":
        return ent
    log.info("sector_label_is_organization", label=hit.matched_alias, entity_id=ent.id)
    return None


def resolve_mention(session: Session, hit: MentionInput) -> Entity | None:
    """Entitas hidup untuk `hit`, atau None (kosong/suppressed)."""
    if not collapse_ws(hit.name or "") and not hit.external_id:
        return None
    if hit.type == "location":
        code = (hit.external_id or hit.name).strip().upper()
        found = session.execute(_location_stmt(code)).scalars().first()
        if found is None:
            name, kw = _location_new(code)
            found = resolve(session, "location", name, **kw)
        return _usable(found)
    name, kw = _resolve_kwargs(hit)
    return _sector_only(hit, _usable(resolve(session, hit.type, name, **kw)))


async def resolve_mention_async(session: AsyncSession, hit: MentionInput) -> Entity | None:
    if not collapse_ws(hit.name or "") and not hit.external_id:
        return None
    if hit.type == "location":
        code = (hit.external_id or hit.name).strip().upper()
        found = (await session.execute(_location_stmt(code))).scalars().first()
        if found is None:
            name, kw = _location_new(code)
            found = await resolve_async(session, "location", name, **kw)
        return _usable(found)
    name, kw = _resolve_kwargs(hit)
    return _sector_only(hit, _usable(await resolve_async(session, hit.type, name, **kw)))


def _order(hits: Sequence[MentionInput]) -> list[int]:
    # Resolve selalu urut (tipe, nama): dua worker yang membuat entitas yang sama dalam urutan
    # berlawanan tidak saling menunggu kunci alias/nama (deadlock).
    return sorted(range(len(hits)), key=lambda i: (hits[i].type, alias_norm(hits[i].name or "")))


def resolve_all(
    session: Session, hits: Iterable[MentionInput]
) -> list[tuple[MentionInput, Entity | None]]:
    """`resolve_mention` untuk semua hit dalam urutan deterministik; hasil urut seperti input
    (supaya "sebutan pertama menang" di `mention_rows` tetap urutan teks)."""
    seq = list(hits)
    ents: list[Entity | None] = [None] * len(seq)
    for i in _order(seq):
        ents[i] = resolve_mention(session, seq[i])
    return list(zip(seq, ents, strict=True))


async def resolve_all_async(
    session: AsyncSession, hits: Iterable[MentionInput]
) -> list[tuple[MentionInput, Entity | None]]:
    seq = list(hits)
    ents: list[Entity | None] = [None] * len(seq)
    for i in _order(seq):
        ents[i] = await resolve_mention_async(session, seq[i])
    return list(zip(seq, ents, strict=True))


def mention_rows(
    subject: dict[str, int], resolved: Iterable[tuple[MentionInput, Entity | None]]
) -> list[dict[str, Any]]:
    """Baris insert, satu per (entitas, role): sebutan pertama menang (dua ejaan satu entitas)."""
    rows: dict[tuple[int, str | None], dict[str, Any]] = {}
    for hit, ent in resolved:
        if ent is None:
            continue
        rows.setdefault(
            (ent.id, hit.role),
            {
                "article_id": None,
                "indicator_id": None,
                "cve_tracker_id": None,
                **subject,
                "entity_id": ent.id,
                "method": hit.method,
                "matched_alias": collapse_ws(hit.matched_alias)[:300] or ent.name,
                "role": hit.role,
                "evidence": hit.evidence,
                "extracted": hit.extracted,
            },
        )
    return list(rows.values())


def insert_mentions(rows: Sequence[dict[str, Any]], *, update: bool) -> ReturningInsert[tuple[int]]:
    """INSERT idempoten pada kunci unik mention. `update=True` (set ulang hasil enrichment)
    memperbarui method/alias/bukti baris yang sudah ada; selain itu baris lama dibiarkan."""
    stmt = insert(EntityMention).values(list(rows))
    if update:
        return stmt.on_conflict_do_update(
            constraint="uq_entity_mentions_subject_entity_role",
            set_={
                "method": stmt.excluded.method,
                "matched_alias": stmt.excluded.matched_alias,
                "evidence": stmt.excluded.evidence,
                "extracted": stmt.excluded.extracted,
            },
        ).returning(EntityMention.id)
    return stmt.on_conflict_do_nothing().returning(EntityMention.id)


def delete_other_mentions(
    article_id: int, types: Sequence[str], keep: Iterable[tuple[int, str | None]]
) -> Delete:
    """Hapus mention artikel bertipe `types` yang (entitas, role)-nya tidak di `keep`."""
    kept = list(keep)
    of_types = select(Entity.id).where(Entity.type.in_(list(types)))
    stmt = (
        delete(EntityMention)
        .where(EntityMention.article_id == article_id, EntityMention.entity_id.in_(of_types))
        .execution_options(synchronize_session=False)  # pemanggil meng-expire relasinya
    )
    if kept:
        # Tiap cabang membandingkan role secara eksplisit (IS NULL / IS NOT NULL) supaya predikat
        # "dipertahankan" tidak pernah NULL: `(entity_id, role) IN (...)` bernilai NULL untuk
        # baris ber-role NULL, dan NOT NULL membuat baris itu tidak pernah terhapus.
        with_role = [(e, r) for e, r in kept if r is not None]
        without_role = [e for e, r in kept if r is None]
        keep_conds: list[ColumnElement[bool]] = []
        if with_role:
            keep_conds.append(
                and_(
                    EntityMention.role.is_not(None),
                    tuple_(EntityMention.entity_id, EntityMention.role).in_(with_role),
                )
            )
        if without_role:
            keep_conds.append(
                and_(EntityMention.role.is_(None), EntityMention.entity_id.in_(without_role))
            )
        stmt = stmt.where(~or_(*keep_conds))
    return stmt


# Satu statement per artikel (spec 4.3): tanggal terbit (posted_on, UTC), cadangan created_at;
# LEAST/GREATEST Postgres mengabaikan NULL, jadi entitas yang belum pernah dilihat ikut terisi.
# Entitas "panas" (negara, sektor) disebut hampir tiap artikel dan worker enrich berjalan paralel:
# baris yang tidak berubah dilewati, dan kunci diambil urut id (NO KEY UPDATE, tidak bentrok
# dengan KEY SHARE dari FK mention) supaya dua transaksi tidak saling deadlock.
_TOUCH_SEEN = text(
    """
    WITH s AS (SELECT coalesce(a.posted_on::timestamp AT TIME ZONE 'UTC', a.created_at) AS at
                 FROM articles a WHERE a.id = :article_id),
         l AS (SELECT e.id FROM entities e, s
                WHERE e.id IN (SELECT entity_id FROM entity_mentions WHERE article_id = :article_id)
                  AND s.at IS NOT NULL
                  AND (e.first_seen IS NULL OR e.first_seen > s.at
                       OR e.last_seen IS NULL OR e.last_seen < s.at)
                ORDER BY e.id
                  FOR NO KEY UPDATE OF e)
    UPDATE entities e
       SET first_seen = least(e.first_seen, s.at), last_seen = greatest(e.last_seen, s.at)
      FROM l, s
     WHERE e.id = l.id
    """
)


def touch_seen(session: Session, article_id: int) -> None:
    session.execute(_TOUCH_SEEN, {"article_id": article_id})


async def touch_seen_async(session: AsyncSession, article_id: int) -> None:
    await session.execute(_TOUCH_SEEN, {"article_id": article_id})


def utc_midnight(day: datetime.date | None) -> datetime.datetime | None:
    if day is None:
        return None
    return datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.UTC)
