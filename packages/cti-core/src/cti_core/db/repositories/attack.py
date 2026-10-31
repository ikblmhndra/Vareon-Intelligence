"""AsyncAttackSyncRepo (fetch+upsert STIX) + AsyncAttackQueryRepo (baca
katalog) -- port `ScraperNewsWeb/app/services/attack_sync_service.py`.
Fase 7.3 (router `attack`, Bagian 3, PRASYARAT `ta_groups`/`mitre`/
`crossref` -- sama pola `techstack` sebelum `cve`).

Full-text search Mongo (`$text`) -> `ILIKE` di sini, konsisten sama
router lain yang udah di-port (gak ada satu pun yang pakai Postgres
`tsvector`/GIN sejauh ini) -- bukan downgrade fitur, translate mekanis.

Upsert per-domain pakai `INSERT ... ON CONFLICT (stix_id) DO UPDATE`
batched (500/batch, port angka yang sama dari `_bulk_write()` lama).
`domains` (ARRAY) butuh merge-dedup manual di klausa `SET` (`array_agg
DISTINCT` atas gabungan array lama+baru) -- itu yang bikin `$addToSet`
Mongo beda dari overwrite biasa, kalau di-skip re-sync domain yang sama
bakal numpuk entry domain duplikat di array."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.attack_ttp import clean_attack_text
from cti_core.config import platform_name
from cti_core.db.models.attack import (
    AttackGroup,
    AttackMitigation,
    AttackRelationship,
    AttackSoftware,
    AttackSyncLog,
    AttackTactic,
    AttackTechnique,
    AttackTechniqueAlias,
)
from cti_core.db.models.entity import Entity, EntityAlias, Relationship
from cti_core.entity import RELATIONSHIP_TYPES, alias_norm, collapse_ws

DOMAINS: dict[str, dict[str, str]] = {
    "enterprise": {
        "key": "enterprise",
        "label": "Enterprise ATT&CK",
        "url": "https://raw.githubusercontent.com/mitre/cti/master/enterprise-attack/enterprise-attack.json",
        "stix_domain": "enterprise-attack",
    },
    "ics": {
        "key": "ics",
        "label": "ICS ATT&CK",
        "url": "https://raw.githubusercontent.com/mitre/cti/master/ics-attack/ics-attack.json",
        "stix_domain": "ics-attack",
    },
    "mobile": {
        "key": "mobile",
        "label": "Mobile ATT&CK",
        "url": "https://raw.githubusercontent.com/mitre/cti/master/mobile-attack/mobile-attack.json",
        "stix_domain": "mobile-attack",
    },
}

_TIMEOUT = httpx.Timeout(300.0)
_HEADERS = {"User-Agent": "cti-platform/1.0 (ATT&CK sync)"}


def _mitre_ref(obj: dict[str, Any]) -> dict[str, Any]:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return cast("dict[str, Any]", ref)
    return {}


def _extract_id(obj: dict[str, Any]) -> str:
    return cast(str, _mitre_ref(obj).get("external_id", ""))


def _extract_url(obj: dict[str, Any]) -> str:
    return cast(str, _mitre_ref(obj).get("url", ""))


def _technique_search(search: str) -> Any:
    """Cari by nama ATAU ID ("T1059" / "t1059.001" / "1059") -- QA BUG-C17:
    analis biasanya nyari pakai ID, dulu cuma nama yang di-ILIKE."""
    term = search.strip()
    return or_(
        AttackTechnique.name.ilike(f"%{term}%"),
        AttackTechnique.attack_id.ilike(f"%{term}%"),
    )


_ENTITY_TYPES = ("intrusion-set", "malware", "tool", "attack-pattern", "campaign")
_CHUNK = 500


def _is_dead(obj: dict[str, Any]) -> bool:
    """Objek revoked/deprecated tidak dibuat sebagai entitas (entitas lama tidak dihapus)."""
    return bool(
        obj.get("revoked") or obj.get("x-mitre-deprecated") or obj.get("x_mitre_deprecated")
    )


def _attack_entity_row(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Petakan objek STIX ATT&CK ke baris `entities` + daftar alias resmi (nama dulu).

    Sama dengan backfill migrasi: grup -> intrusion-set, software -> malware/tool, teknik ->
    attack-pattern (external_id = id teknik huruf besar; alias hanya id itu, Ruling 7),
    campaign -> campaign. Return None bila tipe tak dikenal / mati / tanpa id atau nama."""
    type_ = obj.get("type")
    if type_ not in _ENTITY_TYPES or _is_dead(obj):
        return None
    ext_id: str | None = collapse_ws(_extract_id(obj)) or None
    name = collapse_ws(obj.get("name", ""))
    if not alias_norm(name):
        return None
    if type_ == "attack-pattern":
        if not ext_id:
            return None  # identitas teknik = id teknik (Ruling 7)
        ext_id = ext_id.upper()
        aliases = [ext_id]
    else:
        # grup/software/campaign tanpa id tetap dibuat (external_id NULL), seperti backfill
        raw = obj.get("x-mitre-aliases") or obj.get("x_mitre_aliases") or obj.get("aliases") or []
        aliases = [name, *raw]
    return {
        "stix_id": obj["id"],
        "type": type_,
        "name": name,
        "description": obj.get("description") or None,
        "external_id": ext_id,
        "aliases": aliases,
    }


async def upsert_attack_entities(
    session: AsyncSession, bundle_objects: list[dict[str, Any]]
) -> dict[str, int]:
    """Upsert objek ATT&CK dari satu bundle ke `entities`, `entity_aliases`, `relationships`.

    Kunci = `stix_id` ATT&CK. Entitas hidup non-ATT&CK yang sudah ada dengan nama sama (per
    tipe; teknik: id teknik sama) DIADOPSI (Ruling 25): `source='attack'`, `stix_id`/`external_id`/
    `name` dari ATT&CK; deskripsi ATT&CK hanya mengisi deskripsi yang kosong (Ruling 27); alias dan
    mention analis tetap. Entitas ATT&CK yang sudah ada diperbarui (trigger feed membump jam).
    Alias resmi ditambah dengan `ON CONFLICT DO NOTHING` (alias analis tak pernah dihapus/ditimpa,
    alias resmi lama tak dibuang). Urutan seperti backfill: baris diurut `stix_id`, alias nama
    sendiri dulu baru alias lain, jadi bentrokan alias dimenangkan nama sendiri lalu `stix_id`
    terkecil. Tombstone merge dibiarkan; bentrok nama dengan entitas lain dilewati. Relasi hanya
    tipe di CHECK `RELATIONSHIP_TYPES`, ujung tombstone mengikuti `merged_into_id`; provenance
    `attack`, confidence 85. Return: jumlah objek yang DILIHAT (bukan yang baru dibuat) per tipe,
    plus `relationship` (relasi yang kedua ujungnya ada)."""
    rows = sorted(
        (r for o in bundle_objects if (r := _attack_entity_row(o))), key=lambda r: r["stix_id"]
    )
    counts = {t: 0 for t in _ENTITY_TYPES}
    for r in rows:
        counts[r["type"]] += 1

    adopted_now: set[str] = set()  # diadopsi di panggilan ini: deskripsi lama tidak ditimpa
    # 1a. adopsi entitas non-ATT&CK yang identitasnya sama (Ruling 25/27)
    for i in range(0, len(rows), _CHUNK):
        chunk = rows[i : i + _CHUNK]
        have = set(
            (
                await session.execute(
                    select(Entity.stix_id).where(Entity.stix_id.in_([r["stix_id"] for r in chunk]))
                )
            ).scalars()
        )
        todo = [r for r in chunk if r["stix_id"] not in have]
        if not todo:
            continue
        names = {(r["type"], r["name"].lower()): r for r in todo if r["type"] != "attack-pattern"}
        techs = {r["external_id"]: r for r in todo if r["type"] == "attack-pattern"}
        cand = (
            await session.execute(
                select(Entity.id, Entity.type, Entity.name, Entity.external_id, Entity.description)
                .where(
                    Entity.source != "attack",
                    Entity.merged_into_id.is_(None),
                    or_(
                        func.lower(Entity.name).in_([n for _, n in names]),
                        Entity.external_id.in_(list(techs)),
                    ),
                )
                .order_by(Entity.id)
            )
        ).all()
        adopted = adopted_now
        for eid, etype, ename, eext, edesc in cand:
            row = (
                techs.get(eext) if etype == "attack-pattern" else names.get((etype, ename.lower()))
            )
            if row is None or row["type"] != etype or row["stix_id"] in adopted:
                continue
            adopted.add(row["stix_id"])
            values: dict[str, Any] = {
                "source": "attack",
                "stix_id": row["stix_id"],
                "name": row["name"],
            }
            if row["external_id"] is not None:
                values["external_id"] = row["external_id"]
            if not edesc and row["description"]:
                values["description"] = row["description"]
            try:
                async with session.begin_nested():
                    await session.execute(update(Entity).where(Entity.id == eid).values(**values))
            except IntegrityError:
                adopted.discard(row["stix_id"])

    # 1b. entitas baru (bentrok apa pun dilewati)
    for i in range(0, len(rows), _CHUNK):
        await session.execute(
            pg_insert(Entity)
            .values(
                [
                    {k: r[k] for k in ("stix_id", "type", "name", "description", "external_id")}
                    | {"source": "attack"}
                    for r in rows[i : i + _CHUNK]
                ]
            )
            .on_conflict_do_nothing()
        )

    # 1c. perbarui entitas ATT&CK yang berubah (UPDATE Core: savepoint tak meng-expire objek ORM)
    ids: dict[str, int] = {}
    for i in range(0, len(rows), _CHUNK):
        chunk = rows[i : i + _CHUNK]
        found = await session.execute(
            select(
                Entity.stix_id, Entity.id, Entity.name, Entity.description, Entity.external_id
            ).where(
                Entity.stix_id.in_([r["stix_id"] for r in chunk]),
                Entity.merged_into_id.is_(None),
            )
        )
        cur = {sid: (eid, n, d, x) for sid, eid, n, d, x in found.all()}
        for r in chunk:
            if r["stix_id"] not in cur:
                continue  # bentrok nama atau tombstone: dilewati
            eid, n, d, x = cur[r["stix_id"]]
            ids[r["stix_id"]] = eid
            desc = d if r["stix_id"] in adopted_now else r["description"]
            if (n, d, x) != (r["name"], desc, r["external_id"]):
                try:
                    async with session.begin_nested():
                        await session.execute(
                            update(Entity)
                            .where(Entity.id == eid)
                            .values(
                                name=r["name"],
                                description=desc,
                                external_id=r["external_id"],
                            )
                        )
                except IntegrityError:
                    pass  # nama baru bentrok dengan entitas lain; biarkan nama lama

    # 2. alias resmi (source=attack), dua putaran seperti backfill: nama sendiri, lalu alias
    def _alias_rows(own: bool) -> list[dict[str, Any]]:
        return [
            {
                "entity_id": ids[r["stix_id"]],
                "entity_type": r["type"],
                "alias": collapse_ws(a),
                "alias_norm": alias_norm(a),
                "source": "attack",
            }
            for r in rows
            if r["stix_id"] in ids
            for idx, a in enumerate(r["aliases"])
            if alias_norm(a) and ((idx == 0) == own)
        ]

    alias_rows = _alias_rows(True) + _alias_rows(False)
    for i in range(0, len(alias_rows), _CHUNK):
        await session.execute(
            pg_insert(EntityAlias).values(alias_rows[i : i + _CHUNK]).on_conflict_do_nothing()
        )

    # 3. relasi: kedua ujung entitas (bisa dari domain lain; tombstone -> entitas hidup)
    wanted = [
        o
        for o in bundle_objects
        if o.get("type") == "relationship"
        and o.get("relationship_type") in RELATIONSHIP_TYPES
        and not _is_dead(o)
        and o.get("source_ref")
        and o.get("target_ref")
    ]
    refs = {o["source_ref"] for o in wanted} | {o["target_ref"] for o in wanted}
    ref_ids: dict[str, int] = {s: ids[s] for s in refs if s in ids}
    missing = sorted(refs - set(ref_ids))
    for i in range(0, len(missing), _CHUNK):
        found_ids = await session.execute(
            select(Entity.stix_id, Entity.id).where(Entity.stix_id.in_(missing[i : i + _CHUNK]))
        )
        ref_ids.update({s: eid for s, eid in found_ids.all()})
    for _ in range(20):  # ikuti merged_into_id sampai entitas hidup
        mid = list(set(ref_ids.values()))
        up: dict[int, int] = {}
        for i in range(0, len(mid), _CHUNK):
            res = await session.execute(
                select(Entity.id, Entity.merged_into_id).where(
                    Entity.id.in_(mid[i : i + _CHUNK]), Entity.merged_into_id.is_not(None)
                )
            )
            up.update({a: b for a, b in res.all() if b is not None})
        if not up:
            break
        ref_ids = {s: up.get(e, e) for s, e in ref_ids.items()}
    rel_rows = [
        {
            "stix_id": o["id"],
            "relationship_type": o["relationship_type"],
            "source_entity_id": ref_ids[o["source_ref"]],
            "target_entity_id": ref_ids[o["target_ref"]],
            "confidence": 85,
            "provenance": "attack",
            "description": o.get("description") or None,
        }
        for o in wanted
        if o["source_ref"] in ref_ids and o["target_ref"] in ref_ids
    ]
    for i in range(0, len(rel_rows), _CHUNK):
        chunk = rel_rows[i : i + _CHUNK]
        existing = {
            s: d
            for s, d in (
                await session.execute(
                    select(Relationship.stix_id, Relationship.description).where(
                        Relationship.stix_id.in_([r["stix_id"] for r in chunk]),
                        Relationship.provenance == "attack",
                    )
                )
            ).all()
        }
        for r in chunk:
            if r["stix_id"] in existing and existing[r["stix_id"]] != r["description"]:
                await session.execute(
                    update(Relationship)
                    .where(Relationship.stix_id == r["stix_id"])
                    .values(description=r["description"])
                )
        await session.execute(pg_insert(Relationship).values(chunk).on_conflict_do_nothing())
    await session.flush()
    return {**counts, "relationship": len(rel_rows)}


class AsyncAttackSyncRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _bulk_upsert(
        self, model: type[Any], rows: list[dict[str, Any]], update_cols: list[str]
    ) -> None:
        if not rows:
            return
        table_name: str = model.__tablename__
        for i in range(0, len(rows), 500):
            chunk = rows[i : i + 500]
            stmt = pg_insert(model).values(chunk)
            set_: dict[str, Any] = {col: getattr(stmt.excluded, col) for col in update_cols}
            if "domains" in update_cols:
                set_["domains"] = text(
                    f"(SELECT COALESCE(array_agg(DISTINCT d), ARRAY[]::varchar[]) "
                    f"FROM unnest({table_name}.domains || excluded.domains) AS d)"
                )
            stmt = stmt.on_conflict_do_update(index_elements=["stix_id"], set_=set_)
            await self.session.execute(stmt)
        await self.session.flush()

    async def _set_log(self, domain_key: str, fields: dict[str, Any]) -> None:
        stmt = pg_insert(AttackSyncLog).values(domain_key=domain_key, **fields)
        stmt = stmt.on_conflict_do_update(index_elements=["domain_key"], set_=fields)
        await self.session.execute(stmt)
        await self.session.commit()

    async def sync_domain(self, domain_key: str) -> dict[str, Any]:
        """Fetch + upsert satu domain ATT&CK. Return sync result dict."""
        if domain_key not in DOMAINS:
            raise ValueError(f"Unknown domain: {domain_key}")

        meta = DOMAINS[domain_key]
        stix_domain = meta["stix_domain"]
        started_at = datetime.now(UTC)

        prev = await self.session.get(AttackSyncLog, domain_key)
        prev_counts = {
            "technique_count": prev.technique_count if prev else 0,
            "group_count": prev.group_count if prev else 0,
            "software_count": prev.software_count if prev else 0,
            "mitigation_count": prev.mitigation_count if prev else 0,
        }

        await self._set_log(
            domain_key,
            {
                "domain": stix_domain,
                "label": meta["label"],
                "status": "syncing",
                "last_attempted": started_at.isoformat(),
                "error": None,
            },
        )

        try:
            async with (
                httpx.AsyncClient(
                    timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
                ) as client,
                client.stream("GET", meta["url"]) as resp,
            ):
                resp.raise_for_status()
                total_bytes = int(resp.headers.get("content-length", 0))
                downloaded = 0
                last_reported = 0
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes(chunk_size=512 * 1024):
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if downloaded - last_reported >= 5 * 1024 * 1024:
                        last_reported = downloaded
                        pct = (
                            f"{downloaded * 100 // total_bytes}%"
                            if total_bytes
                            else f"{downloaded // 1024 // 1024}MB"
                        )
                        await self._set_log(
                            domain_key,
                            {
                                "phase": "downloading",
                                "bytes_downloaded": downloaded,
                                "bytes_total": total_bytes,
                                "download_pct": pct,
                            },
                        )
                raw_bytes = b"".join(chunks)
            bundle = json.loads(raw_bytes)
        except Exception as e:
            await self._set_log(
                domain_key,
                {
                    "status": "error",
                    "phase": None,
                    "error": str(e),
                    "last_attempted": started_at.isoformat(),
                },
            )
            raise

        await self._set_log(domain_key, {"phase": "parsing & writing"})

        objects: list[dict[str, Any]] = bundle.get("objects", [])
        by_type: dict[str, list[dict[str, Any]]] = {}
        for obj in objects:
            by_type.setdefault(obj["type"], []).append(obj)

        version = ""
        mitre_modified = ""
        for obj in by_type.get("x-mitre-collection", []):
            version = obj.get("x-mitre-version", "")
            mitre_modified = obj.get("modified", "")
        if not version or not mitre_modified:
            for obj in by_type.get("attack-pattern", []):
                if not version:
                    version = obj.get("x-mitre-version", "")
                if not mitre_modified:
                    mitre_modified = obj.get("modified", "")
                if version and mitre_modified:
                    break

        await self._sync_technique_aliases(by_type, stix_domain)
        counts = {
            "technique_count": await self._sync_techniques(by_type, stix_domain),
            "tactic_count": await self._sync_tactics(by_type, stix_domain),
            "mitigation_count": await self._sync_mitigations(by_type, stix_domain),
            "group_count": await self._sync_groups(by_type, stix_domain),
            "software_count": await self._sync_software(by_type, stix_domain),
            "relationship_count": await self._sync_relationships(by_type, stix_domain),
        }
        await upsert_attack_entities(self.session, objects)

        finished_at = datetime.now(UTC)
        delta = {
            f"delta_{k}": (counts[k] - prev_counts[k]) if prev_counts.get(k) else None
            for k in ("technique_count", "group_count", "software_count", "mitigation_count")
        }
        sync_fields = {
            "domain": stix_domain,
            "label": meta["label"],
            "version": version,
            "mitre_modified": mitre_modified,
            "last_sync": finished_at.isoformat(),
            "status": "success",
            "error": None,
            "phase": None,
            "bytes_downloaded": None,
            "bytes_total": None,
            "download_pct": None,
            **counts,
            **delta,
        }
        await self._set_log(domain_key, sync_fields)
        return {"domain_key": domain_key, **sync_fields}

    async def _sync_techniques(
        self, by_type: dict[str, list[dict[str, Any]]], stix_domain: str
    ) -> int:
        rows = []
        for obj in by_type.get("attack-pattern", []):
            if obj.get("revoked") or obj.get("x-mitre-deprecated"):
                continue
            attack_id = _extract_id(obj)
            if not attack_id:
                continue
            tactics = [
                kc["phase_name"]
                for kc in obj.get("kill_chain_phases", [])
                if kc.get("kill_chain_name", "").startswith("mitre")
            ]
            parent_id = None
            if obj.get("x-mitre-is-subtechnique") and "." in attack_id:
                parent_id = attack_id.split(".")[0]
            rows.append(
                {
                    "stix_id": obj["id"],
                    "attack_id": attack_id,
                    "name": obj.get("name", ""),
                    "description": obj.get("description", ""),
                    "url": _extract_url(obj),
                    "tactics": tactics,
                    "is_subtechnique": bool(obj.get("x-mitre-is-subtechnique")),
                    "parent_id": parent_id,
                    "version": obj.get("x-mitre-version", ""),
                    "created": obj.get("created", ""),
                    "modified": obj.get("modified", ""),
                    "platforms": obj.get("x-mitre-platforms", []),
                    "data_sources": obj.get("x-mitre-data-sources", []),
                    "detection": obj.get("x-mitre-detection", ""),
                    "domains": [stix_domain],
                }
            )
        await self._bulk_upsert(
            AttackTechnique,
            rows,
            [
                "attack_id",
                "name",
                "description",
                "url",
                "tactics",
                "is_subtechnique",
                "parent_id",
                "version",
                "created",
                "modified",
                "platforms",
                "data_sources",
                "detection",
                "domains",
            ],
        )
        return len(rows)

    async def _sync_technique_aliases(
        self, by_type: dict[str, list[dict[str, Any]]], stix_domain: str
    ) -> int:
        """Technique REVOKED (`_sync_techniques` ngelewatin ini) -> tabel
        alias, plus `revoked-by` dari relationship bundel yang sama. Dipakai
        normalisasi TTP artikel (`cti_core.attack_ttp`), bukan UI ATT&CK DB."""
        revoked_by = {
            obj.get("source_ref", ""): obj.get("target_ref", "")
            for obj in by_type.get("relationship", [])
            if obj.get("relationship_type") == "revoked-by"
        }
        rows = []
        for obj in by_type.get("attack-pattern", []):
            if not obj.get("revoked"):
                continue
            attack_id = _extract_id(obj)
            if not attack_id:
                continue
            rows.append(
                {
                    "stix_id": obj["id"],
                    "attack_id": attack_id,
                    "name": obj.get("name", ""),
                    "revoked_by_stix_id": revoked_by.get(obj["id"]) or None,
                    "domains": [stix_domain],
                }
            )
        await self._bulk_upsert(
            AttackTechniqueAlias, rows, ["attack_id", "name", "revoked_by_stix_id", "domains"]
        )
        return len(rows)

    async def _sync_tactics(
        self, by_type: dict[str, list[dict[str, Any]]], stix_domain: str
    ) -> int:
        rows = [
            {
                "stix_id": obj["id"],
                "tactic_id": _extract_id(obj),
                "name": obj.get("name", ""),
                "shortname": obj.get("x-mitre-shortname", ""),
                "description": obj.get("description", ""),
                "url": _extract_url(obj),
                "domains": [stix_domain],
            }
            for obj in by_type.get("x-mitre-tactic", [])
        ]
        await self._bulk_upsert(
            AttackTactic,
            rows,
            ["tactic_id", "name", "shortname", "description", "url", "domains"],
        )
        return len(rows)

    async def _sync_mitigations(
        self, by_type: dict[str, list[dict[str, Any]]], stix_domain: str
    ) -> int:
        rows = []
        for obj in by_type.get("course-of-action", []):
            if obj.get("x-mitre-deprecated"):
                continue
            mit_id = _extract_id(obj)
            if not mit_id or not mit_id.startswith("M"):
                continue
            rows.append(
                {
                    "stix_id": obj["id"],
                    "mitigation_id": mit_id,
                    "name": obj.get("name", ""),
                    "description": obj.get("description", ""),
                    "url": _extract_url(obj),
                    "modified": obj.get("modified", ""),
                    "domains": [stix_domain],
                }
            )
        await self._bulk_upsert(
            AttackMitigation,
            rows,
            ["mitigation_id", "name", "description", "url", "modified", "domains"],
        )
        return len(rows)

    async def _sync_groups(self, by_type: dict[str, list[dict[str, Any]]], stix_domain: str) -> int:
        rows = []
        for obj in by_type.get("intrusion-set", []):
            if obj.get("x-mitre-deprecated"):
                continue
            group_id = _extract_id(obj)
            if not group_id:
                continue
            rows.append(
                {
                    "stix_id": obj["id"],
                    "group_id": group_id,
                    "name": obj.get("name", ""),
                    "aliases": obj.get("aliases", []),
                    "description": obj.get("description", ""),
                    "url": _extract_url(obj),
                    "created": obj.get("created", ""),
                    "modified": obj.get("modified", ""),
                    "domains": [stix_domain],
                }
            )
        await self._bulk_upsert(
            AttackGroup,
            rows,
            ["group_id", "name", "aliases", "description", "url", "created", "modified", "domains"],
        )
        return len(rows)

    async def _sync_software(
        self, by_type: dict[str, list[dict[str, Any]]], stix_domain: str
    ) -> int:
        rows = []
        for sw_type in ("malware", "tool"):
            for obj in by_type.get(sw_type, []):
                if obj.get("x-mitre-deprecated"):
                    continue
                sw_id = _extract_id(obj)
                if not sw_id:
                    continue
                rows.append(
                    {
                        "stix_id": obj["id"],
                        "software_id": sw_id,
                        "name": obj.get("name", ""),
                        "software_type": sw_type,
                        "aliases": obj.get("x-mitre-aliases", []),
                        "description": obj.get("description", ""),
                        "url": _extract_url(obj),
                        "platforms": obj.get("x-mitre-platforms", []),
                        "modified": obj.get("modified", ""),
                        "domains": [stix_domain],
                    }
                )
        await self._bulk_upsert(
            AttackSoftware,
            rows,
            [
                "software_id",
                "name",
                "software_type",
                "aliases",
                "description",
                "url",
                "platforms",
                "modified",
                "domains",
            ],
        )
        return len(rows)

    async def _sync_relationships(
        self, by_type: dict[str, list[dict[str, Any]]], stix_domain: str
    ) -> int:
        await self.session.execute(
            delete(AttackRelationship).where(AttackRelationship.domain == stix_domain)
        )
        rows = []
        for obj in by_type.get("relationship", []):
            if obj.get("x-mitre-deprecated") or obj.get("revoked"):
                continue
            src_ref = obj.get("source_ref", "")
            tgt_ref = obj.get("target_ref", "")
            if not src_ref or not tgt_ref:
                continue
            rows.append(
                {
                    "stix_id": obj["id"],
                    "relationship_type": obj.get("relationship_type", ""),
                    "source_ref": src_ref,
                    "source_type": src_ref.split("--")[0] if "--" in src_ref else "",
                    "target_ref": tgt_ref,
                    "target_type": tgt_ref.split("--")[0] if "--" in tgt_ref else "",
                    "description": obj.get("description", ""),
                    "domain": stix_domain,
                }
            )
        await self._bulk_upsert(
            AttackRelationship,
            rows,
            [
                "relationship_type",
                "source_ref",
                "source_type",
                "target_ref",
                "target_type",
                "description",
                "domain",
            ],
        )
        return len(rows)

    async def sync_all_domains(self) -> list[dict[str, Any]]:
        results = []
        for key in DOMAINS:
            try:
                results.append(await self.sync_domain(key))
            except Exception as e:
                results.append({"domain_key": key, "status": "error", "error": str(e)})
        return results

    async def get_sync_status(self) -> list[dict[str, Any]]:
        result = await self.session.execute(select(AttackSyncLog))
        logs = {row.domain_key: row for row in result.scalars().all()}
        out: list[dict[str, Any]] = []
        for key, meta in DOMAINS.items():
            row = logs.get(key)
            if row is None:
                out.append(
                    {
                        "domain_key": key,
                        "label": meta["label"],
                        "stix_domain": meta["stix_domain"],
                        "version": None,
                        "last_sync": None,
                        "status": "never",
                    }
                )
            else:
                out.append({c.name: getattr(row, c.name) for c in AttackSyncLog.__table__.columns})
        return out


class AsyncAttackQueryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _row_dict(row: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
        cols = row.__table__.columns.keys()
        return {c: getattr(row, c) for c in cols if c not in exclude and c != "id"}

    async def get_techniques(
        self,
        *,
        domain: str | None = None,
        tactic: str | None = None,
        search: str | None = None,
        is_subtechnique: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(AttackTechnique)
        if domain:
            stmt = stmt.where(AttackTechnique.domains.contains([domain]))
        if tactic:
            stmt = stmt.where(AttackTechnique.tactics.contains([tactic]))
        if is_subtechnique is not None:
            stmt = stmt.where(AttackTechnique.is_subtechnique == is_subtechnique)
        if search:
            stmt = stmt.where(_technique_search(search))

        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AttackTechnique.attack_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [
            self._row_dict(r, exclude=("description", "detection", "stix_id")) for r in rows
        ], total

    async def get_technique(self, attack_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(AttackTechnique).where(AttackTechnique.attack_id == attack_id)
        )
        tech = result.scalars().first()
        if tech is None:
            return None
        stix_id = tech.stix_id
        doc = self._row_dict(tech, exclude=("stix_id",))
        doc["description"] = clean_attack_text(tech.description)
        doc["detection"] = clean_attack_text(tech.detection)

        mit_rels = (
            (
                await self.session.execute(
                    select(AttackRelationship.source_ref).where(
                        AttackRelationship.target_ref == stix_id,
                        AttackRelationship.relationship_type == "mitigates",
                    )
                )
            )
            .scalars()
            .all()
        )
        mitigations = []
        if mit_rels:
            mits = (
                (
                    await self.session.execute(
                        select(AttackMitigation).where(AttackMitigation.stix_id.in_(mit_rels))
                    )
                )
                .scalars()
                .all()
            )
            mitigations = [
                {
                    "mitigation_id": m.mitigation_id,
                    "name": m.name,
                    "description": clean_attack_text(m.description)[:300],
                }
                for m in mits
            ]

        grp_rels = (
            (
                await self.session.execute(
                    select(AttackRelationship.source_ref).where(
                        AttackRelationship.target_ref == stix_id,
                        AttackRelationship.source_type == "intrusion-set",
                        AttackRelationship.relationship_type == "uses",
                    )
                )
            )
            .scalars()
            .all()
        )
        groups = []
        if grp_rels:
            grps = (
                (
                    await self.session.execute(
                        select(AttackGroup).where(AttackGroup.stix_id.in_(grp_rels))
                    )
                )
                .scalars()
                .all()
            )
            groups = [{"group_id": g.group_id, "name": g.name} for g in grps]

        sub_techniques = []
        if not tech.is_subtechnique:
            subs = (
                (
                    await self.session.execute(
                        select(AttackTechnique)
                        .where(AttackTechnique.parent_id == attack_id)
                        .order_by(AttackTechnique.attack_id)
                    )
                )
                .scalars()
                .all()
            )
            sub_techniques = [{"attack_id": s.attack_id, "name": s.name} for s in subs]

        sw_rels = (
            (
                await self.session.execute(
                    select(AttackRelationship.source_ref).where(
                        AttackRelationship.target_ref == stix_id,
                        AttackRelationship.source_type.in_(["malware", "tool"]),
                        AttackRelationship.relationship_type == "uses",
                    )
                )
            )
            .scalars()
            .all()
        )
        software = []
        if sw_rels:
            sws = (
                (
                    await self.session.execute(
                        select(AttackSoftware).where(AttackSoftware.stix_id.in_(sw_rels))
                    )
                )
                .scalars()
                .all()
            )
            software = [
                {"software_id": s.software_id, "name": s.name, "software_type": s.software_type}
                for s in sws
            ]

        doc["mitigations"] = mitigations
        doc["groups"] = groups
        doc["software"] = software
        doc["sub_techniques"] = sub_techniques
        return doc

    async def get_distinct_tactics_field(self, domain: str | None = None) -> list[str]:
        stmt = select(func.unnest(AttackTechnique.tactics)).distinct()
        if domain:
            stmt = stmt.where(AttackTechnique.domains.contains([domain]))
        result = await self.session.execute(stmt)
        return sorted(v for v in result.scalars().all() if v)

    async def get_tactics(self, domain: str | None = None) -> list[dict[str, Any]]:
        stmt = select(AttackTactic).order_by(AttackTactic.tactic_id)
        if domain:
            stmt = stmt.where(AttackTactic.domains.contains([domain]))
        rows = (await self.session.execute(stmt)).scalars().all()
        return [self._row_dict(r, exclude=("stix_id",)) for r in rows]

    async def get_groups(
        self,
        *,
        domain: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(AttackGroup)
        if domain:
            stmt = stmt.where(AttackGroup.domains.contains([domain]))
        if search:
            stmt = stmt.where(AttackGroup.name.ilike(f"%{search}%"))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AttackGroup.group_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [self._row_dict(r, exclude=("description", "stix_id")) for r in rows], total

    async def get_group_by_name_or_alias_ci(self, name: str) -> AttackGroup | None:
        """Port `ioc_service.get_ioc_ta_links()`'s regex `$or` lama
        (case-insensitive match nama ATAU salah satu alias) -- Fase 7.4
        Grup D. Tabel `attack_groups` kecil (~150 baris), jadi scan alias
        di Python aman; gak ada cara bersih buat case-insensitive match di
        ARRAY(String) Postgres tanpa unnest per-baris yang sama beratnya."""
        needle = name.strip().lower()
        if not needle:
            return None
        exact = await self.session.execute(
            select(AttackGroup).where(func.lower(AttackGroup.name) == needle)
        )
        grp = exact.scalars().first()
        if grp is not None:
            return grp
        all_groups = (await self.session.execute(select(AttackGroup))).scalars().all()
        for g in all_groups:
            if any((a or "").strip().lower() == needle for a in (g.aliases or [])):
                return g
        return None

    async def get_group(self, group_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(AttackGroup).where(AttackGroup.group_id == group_id)
        )
        grp = result.scalars().first()
        if grp is None:
            return None
        stix_id = grp.stix_id
        doc = self._row_dict(grp, exclude=("stix_id",))
        doc["description"] = clean_attack_text(grp.description)

        rels = (
            await self.session.execute(
                select(AttackRelationship.target_ref, AttackRelationship.description).where(
                    AttackRelationship.source_ref == stix_id,
                    AttackRelationship.target_type == "attack-pattern",
                    AttackRelationship.relationship_type == "uses",
                )
            )
        ).all()
        tech_ids = [r.target_ref for r in rels]
        rel_descs = {r.target_ref: r.description for r in rels}
        techniques = []
        if tech_ids:
            techs = (
                (
                    await self.session.execute(
                        select(AttackTechnique)
                        .where(AttackTechnique.stix_id.in_(tech_ids))
                        .order_by(AttackTechnique.attack_id)
                    )
                )
                .scalars()
                .all()
            )
            techniques = [
                {
                    "attack_id": t.attack_id,
                    "name": t.name,
                    "tactics": t.tactics,
                    "context": clean_attack_text(rel_descs.get(t.stix_id, ""))[:200],
                }
                for t in techs
            ]

        sw_rels = (
            (
                await self.session.execute(
                    select(AttackRelationship.target_ref).where(
                        AttackRelationship.source_ref == stix_id,
                        AttackRelationship.relationship_type == "uses",
                        AttackRelationship.target_type.in_(["malware", "tool"]),
                    )
                )
            )
            .scalars()
            .all()
        )
        software = []
        if sw_rels:
            sws = (
                (
                    await self.session.execute(
                        select(AttackSoftware).where(AttackSoftware.stix_id.in_(sw_rels))
                    )
                )
                .scalars()
                .all()
            )
            software = [
                {"software_id": s.software_id, "name": s.name, "software_type": s.software_type}
                for s in sws
            ]

        doc["techniques"] = techniques
        doc["software"] = software
        return doc

    async def get_software(
        self,
        *,
        domain: str | None = None,
        sw_type: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(AttackSoftware)
        if domain:
            stmt = stmt.where(AttackSoftware.domains.contains([domain]))
        if sw_type:
            stmt = stmt.where(AttackSoftware.software_type == sw_type)
        if search:
            stmt = stmt.where(AttackSoftware.name.ilike(f"%{search}%"))
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AttackSoftware.software_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [self._row_dict(r, exclude=("description", "stix_id")) for r in rows], total

    async def get_software_item(self, software_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(AttackSoftware).where(AttackSoftware.software_id == software_id)
        )
        sw = result.scalars().first()
        if sw is None:
            return None
        stix_id = sw.stix_id
        doc = self._row_dict(sw, exclude=("stix_id",))
        doc["description"] = clean_attack_text(sw.description)

        grp_rels = (
            (
                await self.session.execute(
                    select(AttackRelationship.source_ref).where(
                        AttackRelationship.target_ref == stix_id,
                        AttackRelationship.source_type == "intrusion-set",
                        AttackRelationship.relationship_type == "uses",
                    )
                )
            )
            .scalars()
            .all()
        )
        groups = []
        if grp_rels:
            grps = (
                (
                    await self.session.execute(
                        select(AttackGroup).where(AttackGroup.stix_id.in_(grp_rels))
                    )
                )
                .scalars()
                .all()
            )
            groups = [{"group_id": g.group_id, "name": g.name} for g in grps]

        tech_rels = (
            (
                await self.session.execute(
                    select(AttackRelationship.target_ref).where(
                        AttackRelationship.source_ref == stix_id,
                        AttackRelationship.target_type == "attack-pattern",
                        AttackRelationship.relationship_type == "uses",
                    )
                )
            )
            .scalars()
            .all()
        )
        techniques = []
        if tech_rels:
            techs = (
                (
                    await self.session.execute(
                        select(AttackTechnique)
                        .where(AttackTechnique.stix_id.in_(tech_rels))
                        .order_by(AttackTechnique.attack_id)
                    )
                )
                .scalars()
                .all()
            )
            techniques = [
                {"attack_id": t.attack_id, "name": t.name, "tactics": t.tactics} for t in techs
            ]

        doc["groups"] = groups
        doc["techniques"] = techniques
        return doc

    async def get_mitigations(
        self,
        *,
        domain: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        stmt = select(AttackMitigation)
        if domain:
            stmt = stmt.where(AttackMitigation.domains.contains([domain]))
        if search:
            stmt = stmt.where(
                AttackMitigation.name.ilike(f"%{search}%")
                | AttackMitigation.description.ilike(f"%{search}%")
            )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    stmt.order_by(AttackMitigation.mitigation_id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            )
            .scalars()
            .all()
        )
        return [
            {
                **self._row_dict(r, exclude=("stix_id",)),
                "description": clean_attack_text(r.description),
            }
            for r in rows
        ], total

    async def get_navigator_layer(
        self,
        *,
        domain: str | None = None,
        tactic: str | None = None,
        search: str | None = None,
        is_subtechnique: bool | None = None,
        group_id: str | None = None,
    ) -> dict[str, Any]:
        stmt = select(AttackTechnique.attack_id, AttackTechnique.name, AttackTechnique.tactics)
        if domain:
            stmt = stmt.where(AttackTechnique.domains.contains([domain]))
        if tactic:
            stmt = stmt.where(AttackTechnique.tactics.contains([tactic]))
        if is_subtechnique is not None:
            stmt = stmt.where(AttackTechnique.is_subtechnique == is_subtechnique)
        if search:
            stmt = stmt.where(_technique_search(search))

        if group_id:
            grp = (
                await self.session.execute(
                    select(AttackGroup.stix_id).where(AttackGroup.group_id == group_id)
                )
            ).scalar_one_or_none()
            if grp:
                rel_ids = (
                    (
                        await self.session.execute(
                            select(AttackRelationship.target_ref).where(
                                AttackRelationship.source_ref == grp,
                                AttackRelationship.target_type == "attack-pattern",
                                AttackRelationship.relationship_type == "uses",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                stmt = stmt.where(AttackTechnique.stix_id.in_(rel_ids))
            # grp not found: port apa adanya -- legacy gak nge-restrict
            # apa pun di kasus ini (filter _id gak keisi), jadi di sini
            # juga gak nambah where() sama sekali (bukan return kosong).

        techniques = (await self.session.execute(stmt)).all()

        nav_domain = domain or "enterprise-attack"
        description = (
            f"Techniques used by {group_id}"
            if group_id
            else (
                f"Techniques: tactic={tactic}"
                if tactic
                else (f"Techniques: domain={domain}" if domain else "ATT&CK DB export")
            )
        )

        return {
            "name": f"{platform_name()} — ATT&CK DB",
            "versions": {"attack": "16", "navigator": "4.5", "layer": "4.5"},
            "domain": nav_domain,
            "description": description,
            "techniques": [
                {
                    "techniqueID": t.attack_id,
                    "color": "#0C969C",
                    "score": 1,
                    "enabled": True,
                    "metadata": [],
                    "links": [],
                }
                for t in techniques
                if t.attack_id
            ],
            "gradient": {"colors": ["#ffffff", "#0C969C"], "minValue": 0, "maxValue": 1},
            "legendItems": [],
            "metadata": [],
            "links": [],
            "showTacticRowBackground": True,
            "tacticRowBackground": "#162B2C",
            "selectTechniquesAcrossTactics": True,
            "selectSubtechniquesWithParent": False,
        }
