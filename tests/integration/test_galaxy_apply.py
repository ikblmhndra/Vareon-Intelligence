"""`cti-entity merge-aliases` (spec 4.2) pada Postgres NYATA.

Yang dijaga: apply memakai jalur merge yang sama (audit `system:galaxy`, bisa di-Split), run kedua
tidak mengubah apa pun, merge yang dibatalkan analis tidak pernah diulang, dry-run tidak menulis,
satu merge gagal tidak menggagalkan run, deadlock dicoba ulang sekali."""

from __future__ import annotations

import contextlib
import csv
import hashlib
import json
import pathlib
from collections.abc import Iterator
from typing import Any

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.entity import Entity, EntityAlias, EntityMention, ReferenceSnapshot
from cti_core.entity import alias_norm, galaxy
from cti_core.entity import cli as entity_cli
from cti_core.entity.galaxy import (
    GalaxyCluster,
    apply_plan,
    galaxy_sources,
    load_galaxy,
    plan_merges,
)
from cti_core.entity.merge import EntityMergeError, split_aliases
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

MINI = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "galaxy" / "mini-threat-actor.json"
)
IS = "intrusion-set"
_n = 0


def _entity(
    s: Session, name: str, *aliases: str, source: str = "dictionary", mentions: int = 0
) -> Entity:
    e = Entity(type=IS, stix_id=f"{IS}--galaxy-{name}", name=name, source=source)
    s.add(e)
    s.flush()
    alias_source = source if source in ("attack", "analyst") else "dictionary"
    for a in (name, *aliases):
        s.add(
            EntityAlias(
                entity_id=e.id,
                entity_type=IS,
                alias=a,
                alias_norm=alias_norm(a),
                source=alias_source,
            )
        )
    global _n
    for _ in range(mentions):
        _n += 1
        art = Article(url=f"http://g/{_n}", url_hash=f"galaxy-{_n}", title="t", source="src")
        s.add(art)
        s.flush()
        s.add(
            EntityMention(
                article_id=art.id, entity_id=e.id, method="dictionary", matched_alias=name
            )
        )
    s.flush()
    return e


def _seed(s: Session) -> dict[str, Entity]:
    return {
        "apt29": _entity(s, "APT29", "Cozy Bear", source="attack", mentions=2),
        "ursa": _entity(s, "Cloaked Ursa", mentions=1),
        "lazarus": _entity(s, "Lazarus Group", source="attack"),
        "kimsuky": _entity(s, "Kimsuky", source="attack"),
        "okta": _entity(s, "0ktapus", mentions=3),
        "libra": _entity(s, "Muddled Libra", mentions=1),
        "panda": _entity(s, "Mustang Panda", mentions=1),
        "basin": _entity(s, "Basin", mentions=4),
    }


def _clusters() -> list[GalaxyCluster]:
    return load_galaxy("threat-actor", json.loads(MINI.read_text()))


def _counts(s: Session) -> tuple[int, int, int, int]:
    return (
        s.scalar(select(func.count()).select_from(Entity)) or 0,
        s.scalar(select(func.count()).select_from(EntityAlias)) or 0,
        s.scalar(select(func.count()).select_from(EntityMention)) or 0,
        s.scalar(select(func.count()).select_from(AuditLogEntry)) or 0,
    )


def _owner(s: Session, alias: str) -> Entity | None:
    return s.scalar(
        select(Entity)
        .join(EntityAlias, EntityAlias.entity_id == Entity.id)
        .where(EntityAlias.entity_type == IS, EntityAlias.alias_norm == alias_norm(alias))
    )


def test_apply_merges_and_adds_aliases(db_session: Session) -> None:
    s = db_session
    e = _seed(s)
    result = apply_plan(s, plan_merges(s, _clusters()))
    assert result.merged == 2
    s.refresh(e["ursa"])
    s.refresh(e["libra"])
    s.refresh(e["basin"])
    assert e["ursa"].merged_into_id == e["apt29"].id
    assert e["libra"].merged_into_id == e["okta"].id
    assert e["basin"].merged_into_id is None
    owner = _owner(s, "Nobelium")
    assert owner is not None and owner.id == e["apt29"].id
    owner = _owner(s, "Bronze President")
    assert owner is not None and owner.id == e["panda"].id
    new = _owner(s, "BNC-01")
    assert new is not None and new.name == "Brand New Crew" and new.source == "galaxy"
    galaxy_alias = s.scalar(
        select(EntityAlias.source).where(EntityAlias.alias_norm == alias_norm("Nobelium"))
    )
    assert galaxy_alias == "galaxy"
    audits = s.scalars(
        select(AuditLogEntry).where(
            AuditLogEntry.action == "entity_merge", AuditLogEntry.username == "system:galaxy"
        )
    ).all()
    assert len(audits) == 2
    assert _owner(s, "Hidden Cobra") is None  # cluster dua-ATT&CK tidak menyentuh apa pun


def test_second_run_noop(db_session: Session) -> None:
    s = db_session
    _seed(s)
    apply_plan(s, plan_merges(s, _clusters()))
    before = _counts(s)
    plan = plan_merges(s, _clusters())
    assert plan.merges == [] and plan.new_aliases == []
    result = apply_plan(s, plan)
    assert result.merged == 0 and result.aliases_added == 0 and result.created_entities == 0
    assert _counts(s) == before


def test_undone_merge_not_redone(db_session: Session) -> None:
    s = db_session
    e = _seed(s)
    apply_plan(s, plan_merges(s, _clusters()))
    moved = s.scalars(
        select(EntityAlias.id).where(EntityAlias.alias_norm == alias_norm("Cloaked Ursa"))
    ).all()
    split_aliases(s, e["apt29"].id, list(moved), actor="analyst1")
    s.refresh(e["ursa"])
    assert e["ursa"].merged_into_id is None

    plan = plan_merges(s, _clusters())
    assert all(m.source_id != e["ursa"].id for m in plan.merges)
    assert ("undone", e["ursa"].id) in {(k.reason, k.entity_id) for k in plan.skips}
    apply_plan(s, plan)
    s.refresh(e["ursa"])
    assert e["ursa"].merged_into_id is None  # tetap terpisah


def test_dry_run_writes_nothing(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    s = db_session
    _seed(s)
    before = _counts(s)
    _patch_cli(monkeypatch, s)
    assert entity_cli.main(["merge-aliases", "--dry-run", "--csv", str(tmp_path / "p.csv")]) == 0
    assert _counts(s) == before
    actions = {r["action"] for r in csv.DictReader((tmp_path / "p.csv").open())}
    assert {"merge", "alias", "skip"} <= actions


def test_cli_csv_columns(
    db_session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    s = db_session
    _seed(s)
    _patch_cli(monkeypatch, s)
    out = tmp_path / "plan.csv"
    assert entity_cli.main(["merge-aliases", "--csv", str(out)]) == 0  # default dry-run
    with out.open() as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)
    assert header == ["action", "cluster", "source_entity", "target_entity", "alias", "reason"]
    assert ["merge", "APT29", "Cloaked Ursa", "APT29", "Cloaked Ursa", ""] in rows
    assert ["skip", "Mustang Panda", "Basin", "Mustang Panda", "Basin", "ambiguous"] in rows


def test_cli_apply_merges(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    s = db_session
    e = _seed(s)
    _patch_cli(monkeypatch, s)
    assert entity_cli.main(["merge-aliases", "--apply"]) == 0
    s.refresh(e["ursa"])
    assert e["ursa"].merged_into_id == e["apt29"].id


def test_galaxy_sources_prefers_stored_copy(db_session: Session) -> None:
    s = db_session
    content = {"values": [{"uuid": "x", "value": "Stored Only"}]}
    s.add(
        ReferenceSnapshot(
            name=galaxy.snapshot_name("threat-actor"),
            sha256=hashlib.sha256(json.dumps(content).encode()).hexdigest(),
            content=content,
        )
    )
    s.flush()
    sources = galaxy_sources(s)
    assert sources["threat-actor"] == content
    assert len(sources["malpedia"]["values"]) > 1000  # salinan repo


def test_merge_error_is_skipped_and_run_continues(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = db_session
    e = _seed(s)
    real = galaxy.merge_entities

    def flaky(session: Session, source_id: int, into_id: int, *, actor: str) -> Any:
        if source_id == e["ursa"].id:
            raise EntityMergeError("boom")
        return real(session, source_id, into_id, actor=actor)

    monkeypatch.setattr(galaxy, "merge_entities", flaky)
    result = apply_plan(s, plan_merges(s, _clusters()))
    assert result.merged == 1
    assert [(k.reason, k.entity_id) for k in result.errors] == [("error", e["ursa"].id)]
    s.refresh(e["libra"])
    assert e["libra"].merged_into_id == e["okta"].id


class _Deadlock(Exception):
    sqlstate = "40P01"


def test_deadlock_retried_once(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    s = db_session
    e = _seed(s)
    real = galaxy.merge_entities
    calls: list[int] = []

    def deadlock_once(session: Session, source_id: int, into_id: int, *, actor: str) -> Any:
        calls.append(source_id)
        if calls.count(source_id) == 1 and source_id == e["ursa"].id:
            raise OperationalError("UPDATE ...", {}, _Deadlock())
        return real(session, source_id, into_id, actor=actor)

    monkeypatch.setattr(galaxy, "merge_entities", deadlock_once)
    result = apply_plan(s, plan_merges(s, _clusters()))
    assert result.merged == 2 and result.errors == []
    assert calls.count(e["ursa"].id) == 2


def _patch_cli(monkeypatch: pytest.MonkeyPatch, s: Session) -> None:
    @contextlib.contextmanager
    def fake_session() -> Iterator[Session]:
        yield s

    monkeypatch.setattr(entity_cli, "sync_session", fake_session)
    monkeypatch.setattr(
        entity_cli,
        "galaxy_sources",
        lambda session, snapshot_dir=None: {"threat-actor": json.loads(MINI.read_text())},
    )
