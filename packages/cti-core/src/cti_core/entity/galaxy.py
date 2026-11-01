"""Merge alias entitas dari snapshot MISP Galaxy (spec 4.2, `cti-entity merge-aliases`).

Cluster `threat-actor`/`ransomware` menggabungkan entitas `intrusion-set`, cluster `malpedia`
menggabungkan `malware`/`tool`. Target = entitas ATT&CK kalau tepat satu ada di cluster, selain
itu entitas dengan mention terbanyak; semua sinonim yang belum dimiliki siapa pun jadi alias target
(`source=galaxy`).

Menyimpang dari spec 4.2 (Ruling 19): cluster yang tidak cocok dengan entitas mana pun TIDAK
membuat apa pun (tanpa entitas, tanpa alias). Spec meminta entitas baru untuk cluster seperti itu,
tapi snapshot penuh akan membuat ~6,9 ribu entitas bising (termasuk 2.179 famili ransomware lama
sebagai `intrusion-set`) yang semuanya jadi pencocok kamus Tier 1. Sinkronisasi mingguan menangkap
duplikat baru begitu nama itu muncul sebagai entitas dari artikel.

Penjaga risiko R1 (merge otomatis yang salah mencampur dua aktor):
1. cluster yang menyentuh dua entitas ATT&CK berbeda (lewat sinonim apa pun, kuat atau berisiko)
   dilewati seluruhnya (`two_attack`);
2. sinonim di `AMBIGUOUS`/`WINDOWS_UTILITY_NAMES`, atau satu kata umum yang tidak dikurasi ATT&CK
   untuk tipe cluster itu (aturan konteks P4 untuk nama yang asalnya hanya `threat_actor_groups`),
   hanya ditambahkan
   kalau belum dimiliki siapa pun dan TIDAK PERNAH menyebabkan merge entitas yang ada
   (`ambiguous`); entitas yang hanya cocok lewat sinonim seperti itu juga tak bisa jadi target;
3. alias milik entitas lain yang tidak di-merge tidak dipindah; alias ATT&CK/analis menang
   (`owned`), begitu juga nama software ATT&CK di cluster aktor (aturan kamus Tier 1);
4. merge `system:galaxy` yang sudah di-Split analis (baris `entity_split` dengan `merge_audit_id`,
   Ruling 16) tidak pernah diulang untuk pasangan entitas yang sama, arah mana pun (`undone`);
5. tidak ada merge transitif lintas cluster: norm yang muncul di lebih dari satu cluster sejenis
   tidak pernah menjangkar merge dan tidak ditambahkan sebagai alias, dan alias `source=galaxy`
   tidak pernah menjangkar merge (lihat `_plan_cluster`).

Perencanaan murni (`build_plan` di atas `GalaxyState`) dan mensimulasikan merge yang sudah
direncanakan, jadi cluster yang tumpang tindih melihat pemilik barunya dan run kedua tidak
mengubah apa pun. Apply memakai `merge_entities` (audit `entity_merge`, bisa di-Split), satu
SAVEPOINT per merge, deadlock dicoba ulang sekali (enrichment bisa memegang kunci story lewat
trigger feed), `EntityMergeError` dicatat sebagai skip `error` tanpa menggagalkan run.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from cti_core.db.models.entity import EntityAlias, ReferenceSnapshot
from cti_core.entity import ALIAS_SOURCES, alias_norm, collapse_ws
from cti_core.entity.ambiguous import AMBIGUOUS, WINDOWS_UTILITY_NAMES, is_single_token
from cti_core.entity.merge import EntityMergeError, merge_entities, repair_tombstone_mentions
from cti_core.logging import get_logger

Kind = Literal["actor", "malware"]
SkipReason = Literal["two_attack", "ambiguous", "owned", "undone", "error"]

GALAXY_FILES: dict[str, Kind] = {
    "threat-actor": "actor",
    "ransomware": "actor",
    "malpedia": "malware",
}
KIND_TYPES: dict[Kind, tuple[str, ...]] = {
    "actor": ("intrusion-set",),
    "malware": ("malware", "tool"),
}
GALAXY_ACTOR = "system:galaxy"
CSV_COLUMNS = ("action", "cluster", "source_entity", "target_entity", "alias", "reason")
_PROTECTED = ("attack", "analyst")  # sumber alias yang tidak pernah dipindah Galaxy
_DEADLOCK = "40P01"
_DATA_SUBDIR = "data/misp-galaxy"

log = get_logger(component="entity.galaxy")


def snapshot_name(name: str) -> str:
    """Kunci `reference_snapshots.name` untuk salinan yang disimpan task sinkronisasi."""
    return f"misp-galaxy/{name}"


@dataclass(frozen=True)
class GalaxyCluster:
    uuid: str
    value: str
    synonyms: list[str]
    kind: Kind

    def names(self) -> list[str]:
        """Nama cluster lalu sinonimnya, spasi dirapatkan, unik per `alias_norm`, urutan tetap."""
        out: dict[str, str] = {}
        for raw in (self.value, *self.synonyms):
            name = collapse_ws(raw)
            if name and alias_norm(name) not in out:
                out[alias_norm(name)] = name
        return list(out.values())


def load_galaxy(name: str, content: dict[str, Any]) -> list[GalaxyCluster]:
    """Validasi skema minimal (`values` list, tiap cluster punya `uuid` dan `value` string) lalu
    ubah jadi cluster. ValueError kalau file asing atau rusak."""
    kind = GALAXY_FILES.get(name)
    if kind is None:
        raise ValueError(f"galaxy tidak dikenal: {name!r}")
    values = content.get("values") if isinstance(content, dict) else None
    if not isinstance(values, list):
        raise ValueError(f"galaxy {name}: `values` bukan list")
    clusters: list[GalaxyCluster] = []
    for v in values:
        if not isinstance(v, dict) or not isinstance(v.get("value"), str):
            raise ValueError(f"galaxy {name}: cluster tanpa `value` string: {str(v)[:80]}")
        if not isinstance(v.get("uuid"), str):
            raise ValueError(f"galaxy {name}: cluster {v['value']!r} tanpa `uuid`")
        meta = v.get("meta")
        raw = meta.get("synonyms") if isinstance(meta, dict) else None
        synonyms = [s for s in raw if isinstance(s, str)] if isinstance(raw, list) else []
        clusters.append(GalaxyCluster(v["uuid"], v["value"], synonyms, kind))
    return clusters


# ---------------------------------------------------------------------------------------------
# State di memori


@dataclass
class _Ent:
    id: int
    type: str
    name: str
    source: str
    mentions: int = 0
    suppressed: bool = False
    merged_into: int | None = None


@dataclass
class _Alias:
    entity_id: int
    alias: str
    source: str


class GalaxyState:
    """Potret entitas/alias yang relevan untuk cluster; dimutasi saat perencanaan (simulasi)."""

    def __init__(self) -> None:
        self.entities: dict[int, _Ent] = {}
        self.aliases: dict[tuple[str, str], _Alias] = {}
        self.attack_norms: dict[str, list[tuple[str, _Alias]]] = {}
        """Norm -> (tipe, alias) milik alias ATT&CK; dicek per tipe cluster (kurasi ATT&CK)."""
        self.undone_pairs: set[frozenset[int]] = set()

    def add_entity(
        self,
        id: int,
        type: str,
        name: str,
        *,
        source: str,
        mentions: int = 0,
        suppressed: bool = False,
        merged_into: int | None = None,
        aliases: Iterable[tuple[str, str]] = (),
        name_alias: bool = True,
    ) -> None:
        self.entities[id] = _Ent(id, type, name, source, mentions, suppressed, merged_into)
        if name_alias:
            self.add_alias(type, name, id, source if source in ALIAS_SOURCES else "dictionary")
        for alias, alias_source in aliases:
            self.add_alias(type, alias, id, alias_source)

    def add_alias(self, type: str, alias: str, entity_id: int, source: str) -> None:
        norm = alias_norm(alias)
        if (type, norm) in self.aliases:
            return  # (tipe, norm) unik seperti di DB; baris pertama yang berlaku
        row = self.aliases[(type, norm)] = _Alias(entity_id, alias, source)
        if source == "attack":
            self.attack_norms.setdefault(norm, []).append((type, row))

    def live(self, entity_id: int) -> _Ent:
        ent = self.entities[entity_id]
        for _ in range(20):
            if ent.merged_into is None:
                return ent
            ent = self.entities[ent.merged_into]
        raise RuntimeError(f"rantai merge terlalu panjang/siklik untuk entitas {entity_id}")

    def simulate_merge(self, src: _Ent, dst: _Ent) -> None:
        for alias in self.aliases.values():
            if alias.entity_id == src.id:
                alias.entity_id = dst.id
        dst.mentions += src.mentions
        src.merged_into = dst.id


def is_risky_synonym(norm: str, *, attack_curated: bool) -> bool:
    """Penjaga 2: sinonim yang tidak boleh menyebabkan merge."""
    if norm in AMBIGUOUS or norm in WINDOWS_UTILITY_NAMES:
        return True
    return not attack_curated and is_single_token(norm)


# ---------------------------------------------------------------------------------------------
# Rencana


@dataclass(frozen=True)
class PlannedMerge:
    cluster: str
    cluster_uuid: str
    source_id: int
    source_name: str
    target_id: int
    target_name: str
    aliases: tuple[str, ...]
    """Sinonim cluster yang menghubungkan sumber ke target."""


@dataclass(frozen=True)
class PlannedSkip:
    cluster: str
    cluster_uuid: str
    reason: SkipReason
    alias: str
    entity_id: int | None
    entity_name: str
    target_id: int | None
    target_name: str


@dataclass(frozen=True)
class PlannedAlias:
    cluster: str
    cluster_uuid: str
    type: str
    alias: str
    target_id: int
    target_name: str


@dataclass
class GalaxyPlan:
    merges: list[PlannedMerge] = field(default_factory=list)
    skips: list[PlannedSkip] = field(default_factory=list)
    new_aliases: list[PlannedAlias] = field(default_factory=list)


@dataclass(frozen=True)
class _Match:
    name: str
    alias: _Alias
    risky: bool

    @property
    def anchors(self) -> bool:
        """Bisa menjadikan pemiliknya target. Alias `galaxy` tidak pernah: lihat `_plan_cluster`."""
        return not self.risky and self.alias.source != "galaxy"

    @property
    def merges(self) -> bool:
        """Bisa menyebabkan pemiliknya di-merge (alias ATT&CK/analis menang, penjaga 3)."""
        return self.anchors and self.alias.source not in _PROTECTED


def _skip_reason(
    state: GalaxyState, owner: _Ent, ms: list[_Match], target: _Ent | None
) -> SkipReason | None:
    """None = boleh di-merge ke target; selain itu alasan skip."""
    blocked: SkipReason = "ambiguous" if all(m.risky for m in ms) else "owned"
    if target is None or owner.suppressed or owner.type != target.type:
        return blocked
    if owner.source == "attack":  # entitas ATT&CK tidak pernah jadi sumber merge
        return blocked
    if frozenset({owner.id, target.id}) in state.undone_pairs:
        return "undone"
    return None if any(m.merges for m in ms) else blocked


def shared_norms(clusters: Iterable[GalaxyCluster]) -> dict[Kind, set[str]]:
    """Norm yang muncul di lebih dari satu cluster dengan jenis sama (lintas file juga, mis.
    threat-actor + ransomware). Snapshot 2026-10-29: 95 norm aktor, 57 norm malware."""
    seen: dict[tuple[Kind, str], str] = {}
    out: dict[Kind, set[str]] = {"actor": set(), "malware": set()}
    for c in clusters:
        for name in c.names():
            key = (c.kind, alias_norm(name))
            if seen.setdefault(key, c.uuid) != c.uuid:
                out[c.kind].add(key[1])
    return out


def _plan_cluster(state: GalaxyState, c: GalaxyCluster, shared: set[str], plan: GalaxyPlan) -> None:
    """Satu cluster. Pencegah merge transitif lintas cluster (R1, review Task 7):
    - norm yang muncul di lebih dari satu cluster sejenis (`shared`) berisiko: tidak pernah
      menjangkar merge dan tidak ditambahkan sebagai alias;
    - alias `source=galaxy` tidak pernah menjangkar merge, juga lintas run. Uuid cluster tidak
      dicatat di alias (perlu kolom/migrasi baru), jadi aturannya berlaku untuk cluster mana pun.
      Untuk cluster asalnya tidak ada yang hilang: alias galaxy hanya ditambahkan ke target yang
      dijangkar alias non-galaxy di cluster itu, dan alias itu tetap di target kecuali analis
      men-split-nya (lalu memang sebaiknya tidak di-merge ulang otomatis)."""
    types = KIND_TYPES[c.kind]
    matches: dict[int, list[_Match]] = {}
    unowned: list[str] = []
    foreign: list[tuple[str, _Ent]] = []
    for name in c.names():
        norm = alias_norm(name)
        hits = [(t, state.aliases[(t, norm)]) for t in types if (t, norm) in state.aliases]
        curated = state.attack_norms.get(norm, [])
        if not hits:
            other = [a for t, a in curated if t not in types]
            if other:  # nama software ATT&CK di cluster aktor (atau sebaliknya)
                foreign.append((name, state.live(other[0].entity_id)))
            else:
                unowned.append(name)
            continue
        attack_curated = any(t in types for t, _ in curated)
        risky = norm in shared or is_risky_synonym(norm, attack_curated=attack_curated)
        for _, alias in hits:
            owner = state.live(alias.entity_id)
            matches.setdefault(owner.id, []).append(_Match(name, alias, risky))

    def skip(reason: SkipReason, alias: str, ent: _Ent | None, target: _Ent | None) -> None:
        plan.skips.append(
            PlannedSkip(
                c.value,
                c.uuid,
                reason,
                alias,
                None if ent is None else ent.id,
                "" if ent is None else ent.name,
                None if target is None else target.id,
                c.value if target is None else target.name,
            )
        )

    # penjaga 1: setiap pemilik ATT&CK yang tersentuh dihitung, kuat maupun berisiko
    attack_owners = sorted(
        (state.entities[i] for i in matches if state.entities[i].source == "attack"),
        key=lambda e: e.id,
    )
    if len(attack_owners) > 1:
        for e in attack_owners:
            skip("two_attack", matches[e.id][0].name, e, None)
        return
    anchors = [
        state.entities[i]
        for i, ms in matches.items()
        if any(m.anchors for m in ms) and not state.entities[i].suppressed
    ]
    attack = [e for e in anchors if e.source == "attack"]
    target: _Ent | None
    if attack:
        target = attack[0]
    elif anchors:
        target = max(anchors, key=lambda e: (e.mentions, -e.id))
    else:
        target = None

    for owner_id, ms in matches.items():
        owner = state.entities[owner_id]
        if target is not None and owner.id == target.id:
            continue
        reason = _skip_reason(state, owner, ms, target)
        if reason is None:
            assert target is not None
            plan.merges.append(
                PlannedMerge(
                    c.value,
                    c.uuid,
                    owner.id,
                    owner.name,
                    target.id,
                    target.name,
                    tuple(m.name for m in ms if m.merges),
                )
            )
            state.simulate_merge(owner, target)
        else:
            for m in ms:
                skip(reason, m.name, owner, target)
    for name, ent in foreign:
        skip("owned", name, ent, target)

    if target is None:  # Ruling 19: cluster tanpa entitas tidak membuat apa pun
        return
    for name in unowned:
        if alias_norm(name) in shared:  # dipakai cluster lain: bukan milik cluster ini saja
            skip("ambiguous", name, None, target)
            continue
        plan.new_aliases.append(
            PlannedAlias(c.value, c.uuid, target.type, name, target.id, target.name)
        )
        state.add_alias(target.type, name, target.id, "galaxy")


def build_plan(state: GalaxyState, clusters: Iterable[GalaxyCluster]) -> GalaxyPlan:
    """`clusters` = SEMUA cluster run ini (norm bersama dihitung dari seluruhnya)."""
    clusters = list(clusters)
    shared = shared_norms(clusters)
    plan = GalaxyPlan()
    for c in clusters:
        _plan_cluster(state, c, shared[c.kind], plan)
    return plan


def load_state(session: Session, clusters: list[GalaxyCluster]) -> GalaxyState:
    """Baca dari DB hanya alias yang norm-nya muncul di cluster, pemiliknya (beserta rantai
    `merged_into_id`), jumlah mention, dan pasangan merge Galaxy yang sudah di-Split."""
    norms = sorted({alias_norm(n) for c in clusters for n in c.names()})
    alias_rows = session.execute(
        text(
            "SELECT entity_id, entity_type, alias, source FROM entity_aliases"
            " WHERE alias_norm = ANY(:norms) ORDER BY id"
        ),
        {"norms": norms},
    ).all()
    undone = session.execute(
        text(
            "SELECT (m.detail->>'source_id')::bigint, (m.detail->>'into_id')::bigint,"
            " (s.detail->>'into_id')::bigint"
            " FROM audit_log s JOIN audit_log m ON m.id = (s.detail->>'merge_audit_id')::bigint"
            " WHERE s.action = 'entity_split' AND m.action = 'entity_merge'"
            " AND m.username = :actor"
        ),
        {"actor": GALAXY_ACTOR},
    ).all()

    state = GalaxyState()
    want = {r.entity_id for r in alias_rows} | {i for row in undone for i in row if i is not None}
    while want:
        rows = session.execute(
            text(
                "SELECT e.id, e.type, e.name, e.source, e.suppressed, e.merged_into_id,"
                " (SELECT count(*) FROM entity_mentions m WHERE m.entity_id = e.id) AS mentions"
                " FROM entities e WHERE e.id = ANY(:ids)"
            ),
            {"ids": sorted(want)},
        ).all()
        for r in rows:
            state.add_entity(
                r.id,
                r.type,
                r.name,
                source=r.source,
                mentions=r.mentions,
                suppressed=r.suppressed,
                merged_into=r.merged_into_id,
                name_alias=False,
            )
        want = {r.merged_into_id for r in rows if r.merged_into_id is not None} - set(
            state.entities
        )
    for r in alias_rows:
        state.add_alias(r.entity_type, r.alias, r.entity_id, r.source)
    for src, into, split_into in undone:
        live_into = state.live(into).id
        state.undone_pairs.add(frozenset({state.live(src).id, live_into}))
        if split_into is not None:
            state.undone_pairs.add(frozenset({state.live(split_into).id, live_into}))
    return state


def plan_merges(session: Session, clusters: list[GalaxyCluster]) -> GalaxyPlan:
    return build_plan(load_state(session, clusters), clusters)


# ---------------------------------------------------------------------------------------------
# Apply


@dataclass
class GalaxyResult:
    merged: int = 0
    aliases_added: int = 0
    mentions_repaired: int = 0
    """Mention di tombstone yang dipindah/dibuang `repair_tombstone_mentions` sebelum merge."""
    errors: list[PlannedSkip] = field(default_factory=list)
    """Merge yang ditolak `EntityMergeError` (reason `error`); run tetap lanjut."""


def _is_deadlock(exc: DBAPIError) -> bool:
    orig = exc.orig
    return _DEADLOCK in (getattr(orig, "sqlstate", None), getattr(orig, "pgcode", None))


def _add_alias(session: Session, entity_id: int, type: str, alias: str) -> bool:
    row = session.execute(
        insert(EntityAlias)
        .values(
            entity_id=entity_id,
            entity_type=type,
            alias=alias,
            alias_norm=alias_norm(alias),
            source="galaxy",
        )
        .on_conflict_do_nothing()
        .returning(EntityAlias.id)
    ).first()
    return row is not None


def apply_plan(session: Session, plan: GalaxyPlan, *, actor: str = GALAXY_ACTOR) -> GalaxyResult:
    """Perbaiki mention di tombstone dulu (balapan enrichment vs merge), lalu alias baru (hanya
    ke entitas yang sudah ada), lalu merge sesuai urutan rencana. Commit urusan pemanggil."""
    result = GalaxyResult(mentions_repaired=repair_tombstone_mentions(session))
    for a in plan.new_aliases:
        result.aliases_added += _add_alias(session, a.target_id, a.type, a.alias)
    session.flush()

    for m in plan.merges:
        src, dst = m.source_id, m.target_id
        for attempt in (1, 2):
            try:
                with session.begin_nested():
                    merge_entities(session, src, dst, actor=actor)
            except EntityMergeError as exc:
                log.warning("galaxy_merge_rejected", source_id=src, into_id=dst, error=str(exc))
                result.errors.append(
                    PlannedSkip(
                        m.cluster,
                        m.cluster_uuid,
                        "error",
                        "; ".join(m.aliases),
                        src,
                        m.source_name,
                        dst,
                        m.target_name,
                    )
                )
            except DBAPIError as exc:
                if attempt == 1 and _is_deadlock(exc):
                    log.warning("galaxy_merge_deadlock_retry", source_id=src, into_id=dst)
                    continue
                raise
            else:
                result.merged += 1
            break
    return result


# ---------------------------------------------------------------------------------------------
# Sumber


def _package_snapshot(name: str) -> str:
    """Snapshot bawaan paket (`cti_core/entity/data/misp-galaxy/`, Ruling 20): ikut wheel, jadi
    tersedia juga di image Docker yang tidak berisi `tools/`."""
    return files("cti_core.entity").joinpath(_DATA_SUBDIR, f"{name}.json").read_text("utf-8")


def galaxy_sources(session: Session, snapshot_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    """Salinan `reference_snapshots` (disimpan task sinkronisasi) kalau ada, selain itu
    `snapshot_dir` (override CLI) atau snapshot bawaan paket. Urutan kunci = `GALAXY_FILES`
    (aktor dulu, lalu malware)."""
    stored = {
        row.name: row.content
        for row in session.scalars(
            select(ReferenceSnapshot).where(
                ReferenceSnapshot.name.in_([snapshot_name(n) for n in GALAXY_FILES])
            )
        )
    }
    out: dict[str, dict[str, Any]] = {}
    for name in GALAXY_FILES:
        if snapshot_name(name) in stored:
            out[name] = stored[snapshot_name(name)]
            continue
        raw = (
            _package_snapshot(name)
            if snapshot_dir is None
            else (snapshot_dir / f"{name}.json").read_text(encoding="utf-8")
        )
        out[name] = json.loads(raw)
    return out
