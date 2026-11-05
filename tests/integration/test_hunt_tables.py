"""Tabel `sigma_rules` dan `hunt_hypotheses` (P7e, spec 3.1-3.2) pada Postgres NYATA."""

from __future__ import annotations

import uuid

import pytest
from cti_core.db.models.hunt import HuntHypothesis, SigmaRule
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_hunt_tables_roundtrip(db_session: Session) -> None:
    rule_id = uuid.uuid4()
    db_session.add(
        SigmaRule(
            id=rule_id,
            title="t",
            author="a",
            level="high",
            status="test",
            ruleset="core",
            logsource={"product": "windows"},
            techniques=["T1059.001"],
            path="rules/x.yml",
            release="r2026-07-01",
            yaml="title: t",
        )
    )
    db_session.add(
        HuntHypothesis(
            anchor_type="story", anchor_id=987654321, text="h", model="m", generated_by="u"
        )
    )
    db_session.flush()
    rows = db_session.execute(
        select(SigmaRule.id).where(
            SigmaRule.id == rule_id, SigmaRule.techniques.contains(["T1059.001"])
        )
    ).all()
    assert len(rows) == 1


def test_hunt_hypothesis_anchor_type_check(db_session: Session) -> None:
    db_session.add(
        HuntHypothesis(anchor_type="article", anchor_id=1, text="h", model="m", generated_by="u")
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_hunt_hypothesis_anchor_unique(db_session: Session) -> None:
    for _ in range(2):
        db_session.add(
            HuntHypothesis(anchor_type="entity", anchor_id=7, text="h", model="m", generated_by="u")
        )
    with pytest.raises(IntegrityError):
        db_session.flush()
