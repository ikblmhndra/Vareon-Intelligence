"""Normalisasi TTP ke katalog ATT&CK -- Postgres REAL (testcontainers).

QA 2026-10-01: BUG-C01 (MITRE Heatmap: T1548 3 kolom, T1570/T1110 2 kolom,
angka identik), BUG-04 (Dashboard/Exec top TTP), BUG-B8 (modal artikel),
BUG-C17 (ATT&CK DB gak bisa search by ID), BUG-C18 (citation/markdown mentah).

Data "lama" di sini sengaja ditulis lewat `set_enrichment` dengan pasangan
mentah LLM (persis yang tersimpan di staging sebelum fix) -- agregasi harus
tetap benar SEBELUM backfill, dan backfill harus membereskan barisnya."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article, ArticleTTP
from cti_core.db.models.attack import AttackTactic, AttackTechnique
from cti_core.db.repositories.article import ArticleRepo, AsyncArticleRepo
from cti_core.db.repositories.attack import AsyncAttackQueryRepo, AsyncAttackSyncRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from cti_core.db.repositories.mitre import AsyncMitreHeatmapRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ttp_catalog import (
    load_catalog,
    load_catalog_async,
    remap_article_ttps,
)
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_ttps import Technique, TtpResult
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

_TECHNIQUES = [
    ("T1003", "OS Credential Dumping"),
    ("T1068", "Exploitation for Privilege Escalation"),
    ("T1110", "Brute Force"),
    ("T1548", "Abuse Elevation Control Mechanism"),
    ("T1570", "Lateral Tool Transfer"),
    ("T1203", "Exploitation for Client Execution"),
    ("T1059", "Command and Scripting Interpreter"),
    ("T1059.001", "PowerShell"),
]
_TACTICS = ["Privilege Escalation", "Lateral Movement", "Persistence", "Credential Access"]

# Pasangan mentah LLM per artikel -- bentuk yang bikin kolom dobel di QA.
_RAW_ARTICLES = [
    [("T1548", "Exploitation for Privilege Escalation"), ("T1110", "Credential Dumping")],
    [("T1548", "Abuse Elevation Control Mechanism"), ("T1570", "Lateral Movement")],
    [("T1548", "Privilege Escalation"), ("T1570", "Lateral Tool Transfer")],
    [("T1110", "Brute Force"), ("T1203", "Remote Code Execution")],
]


def _catalog_rows() -> list[object]:
    rows: list[object] = [
        AttackTechnique(
            stix_id=f"attack-pattern--{tid}",
            attack_id=tid,
            name=name,
            tactics=[],
            domains=["enterprise-attack"],
            is_subtechnique="." in tid,
            parent_id=tid.split(".")[0] if "." in tid else None,
        )
        for tid, name in _TECHNIQUES
    ]
    rows += [
        AttackTactic(stix_id=f"x-mitre-tactic--{i}", tactic_id=f"TA{i:04d}", name=n, domains=[])
        for i, n in enumerate(_TACTICS)
    ]
    return rows


async def _seed_async(session: AsyncSession, *, catalog: bool = True) -> None:
    if catalog:
        session.add_all(_catalog_rows())
        await session.flush()
    repo = AsyncArticleRepo(session)
    recent = datetime.date.today() - datetime.timedelta(days=3)
    for i, ttps in enumerate(_RAW_ARTICLES):
        a = await repo.upsert(
            url=f"https://example.com/ttp-{i}", title=f"a{i}", source="s", posted_on=recent
        )
        await repo.set_enrichment(a, industries=["General"], ttps=ttps)


# ── agregasi (fix berlaku SEBELUM backfill) ──────────────────────────────────


@pytest.mark.asyncio
async def test_heatmap_has_one_column_per_technique_id_with_canonical_name(
    async_db_session: AsyncSession,
) -> None:
    await _seed_async(async_db_session)
    heatmap = await AsyncMitreHeatmapRepo(async_db_session).get_heatmap(
        view="industry", days=90, top_rows=5, top_ttps=40
    )
    ids = [t["id"] for t in heatmap["ttps"]]
    assert len(ids) == len(set(ids)), f"kolom dobel: {ids}"
    names = {t["id"]: t["name"] for t in heatmap["ttps"]}
    assert names["T1548"] == "Abuse Elevation Control Mechanism"
    assert names["T1570"] == "Lateral Tool Transfer"
    assert names["T1110"] == "Brute Force"
    assert names["T1203"] == "Exploitation for Client Execution"
    general = heatmap["rows"].index("General")
    assert heatmap["matrix"][general][ids.index("T1548")] == 3


@pytest.mark.asyncio
async def test_dashboard_ttp_counts_and_pir_options_are_per_id(
    async_db_session: AsyncSession,
) -> None:
    await _seed_async(async_db_session)
    counts = await AsyncDashboardRepo(async_db_session).ttp_counts(
        limit=40, posted_on_start=None, posted_on_end=None
    )
    by_id = {tid: (name, cnt) for tid, name, cnt in counts}
    assert len(by_id) == len(counts)
    assert by_id["T1548"] == ("Abuse Elevation Control Mechanism", 3)

    options = await AsyncPIRRepo(async_db_session).get_options(AsyncArticleRepo(async_db_session))
    ids = [t["id"] for t in options["ttps"]]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_aggregation_without_catalog_still_groups_by_id(
    async_db_session: AsyncSession,
) -> None:
    """ATT&CK belum pernah di-sync: nama fallback ke salah satu nama tersimpan,
    tapi tetap SATU kolom per ID."""
    await _seed_async(async_db_session, catalog=False)
    heatmap = await AsyncMitreHeatmapRepo(async_db_session).get_heatmap(
        view="industry", days=90, top_rows=5, top_ttps=40
    )
    ids = [t["id"] for t in heatmap["ttps"]]
    assert len(ids) == len(set(ids))


# ── backfill ─────────────────────────────────────────────────────────────────


def _seed_sync(session: Session) -> list[int]:
    session.add_all(_catalog_rows())
    session.flush()
    repo = ArticleRepo(session)
    ids = []
    for i, ttps in enumerate(_RAW_ARTICLES):
        a = repo.upsert(url=f"https://example.com/remap-{i}", title=f"r{i}", source="s")
        repo.set_enrichment(a, ttps=ttps)
        ids.append(a.id)
    return ids


def _ttps_of(session: Session, article_id: int) -> list[tuple[str, str, str | None, str | None]]:
    rows = session.execute(
        select(
            ArticleTTP.ttp_id,
            ArticleTTP.ttp_name,
            ArticleTTP.extracted_id,
            ArticleTTP.extracted_name,
        )
        .where(ArticleTTP.article_id == article_id)
        .order_by(ArticleTTP.ttp_id)
    ).all()
    return [tuple(r) for r in rows]


def test_remap_article_ttps_backfills_and_is_idempotent(db_session: Session) -> None:
    ids = _seed_sync(db_session)
    stats = remap_article_ttps(db_session, load_catalog(db_session), batch_size=2)
    assert stats.articles_scanned == 4 and stats.articles_changed == 4

    assert _ttps_of(db_session, ids[0]) == [
        ("T1003", "OS Credential Dumping", "T1110", "Credential Dumping"),
        (
            "T1068",
            "Exploitation for Privilege Escalation",
            "T1548",
            "Exploitation for Privilege Escalation",
        ),
    ]
    # nama tactic dibuang
    assert _ttps_of(db_session, ids[1]) == [
        (
            "T1548",
            "Abuse Elevation Control Mechanism",
            "T1548",
            "Abuse Elevation Control Mechanism",
        ),
    ]
    assert _ttps_of(db_session, ids[2]) == [
        ("T1570", "Lateral Tool Transfer", "T1570", "Lateral Tool Transfer"),
    ]
    assert ("T1203", "Exploitation for Client Execution", "T1203", "Remote Code Execution") in (
        _ttps_of(db_session, ids[3])
    )

    again = remap_article_ttps(db_session, load_catalog(db_session))
    assert again.articles_changed == 0


def test_remap_refuses_without_catalog(db_session: Session) -> None:
    from cti_core.attack_ttp import TechniqueCatalog

    with pytest.raises(ValueError, match="Katalog ATT&CK kosong"):
        remap_article_ttps(db_session, TechniqueCatalog())


# ── enrichment baru ──────────────────────────────────────────────────────────


@pytest.fixture
def pipeline_session(_migrated_schema: None) -> Iterator[Session]:
    from cti_core.db.engine import get_sync_engine

    connection = get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


def test_pipeline_persists_normalized_ttps_and_alert_uses_canonical_names(
    pipeline_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    pipeline_session.add_all(_catalog_rows())
    pipeline_session.flush()
    sent: list[object] = []
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: sent.append(result))
    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda title: ClassifyResult(
            related_cyber=True, confidence=0.9, reason="x", industries_impacted=["General"]
        ),
    )
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "Isi artikel. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    captured: dict[str, str] = {}
    real_route = pipeline.routing.route

    def spy_route(inp):  # type: ignore[no-untyped-def]
        captured["ttp_string"] = inp.ttp_string
        return real_route(inp)

    monkeypatch.setattr(pipeline.routing, "route", spy_route)
    monkeypatch.setattr(
        pipeline,
        "extract_ttps",
        lambda s: TtpResult(
            has_techniques=True,
            techniques=[
                Technique("T1110", "Credential Dumping", evidence="Isi artikel."),
                Technique("T1548", "Privilege Escalation", evidence="Isi artikel."),
                Technique("T1203", "Remote Code Execution", evidence="Isi artikel."),
            ],
        ),
    )
    url = "https://example.com/new-article"
    outcome = pipeline.run_pipeline(
        title="t", url=url, posted_on=None, source="s", scraper_id="t", session=pipeline_session
    )
    assert outcome.accepted
    article = pipeline_session.scalar(select(Article).where(Article.url_hash == url_hash(url)))
    assert article is not None
    assert sorted((t.ttp_id, t.ttp_name, t.extracted_name) for t in article.ttps) == [
        ("T1003", "OS Credential Dumping", "Credential Dumping"),
        ("T1203", "Exploitation for Client Execution", "Remote Code Execution"),
    ]
    assert captured["ttp_string"] == (
        "OS Credential Dumping (T1003), Exploitation for Client Execution (T1203)"
    )


# ── katalog ATT&CK: revoked, search ID, deskripsi bersih ─────────────────────


@pytest.mark.asyncio
async def test_sync_stores_revoked_techniques_as_aliases(async_db_session: AsyncSession) -> None:
    def ref(tid: str) -> list[dict[str, str]]:
        return [{"source_name": "mitre-attack", "external_id": tid}]

    by_type = {
        "attack-pattern": [
            {
                "id": "attack-pattern--new",
                "name": "PowerShell",
                "external_references": ref("T1059.001"),
            },
            {
                "id": "attack-pattern--old",
                "name": "PowerShell",
                "revoked": True,
                "external_references": ref("T1086"),
            },
        ],
        "relationship": [
            {
                "id": "relationship--1",
                "relationship_type": "revoked-by",
                "source_ref": "attack-pattern--old",
                "target_ref": "attack-pattern--new",
            },
        ],
    }
    sync = AsyncAttackSyncRepo(async_db_session)
    assert await sync._sync_technique_aliases(by_type, "enterprise-attack") == 1
    await sync._sync_techniques(by_type, "enterprise-attack")

    catalog = await load_catalog_async(async_db_session)
    assert catalog.revoked_ids == {"T1086": "T1059.001"}
    assert catalog.resolve("T1086", "PS") == ("T1059.001", "PowerShell")


@pytest.mark.asyncio
async def test_attack_db_search_by_id_and_clean_description(
    async_db_session: AsyncSession,
) -> None:
    async_db_session.add_all(
        [
            AttackTechnique(
                stix_id="attack-pattern--t1059",
                attack_id="T1059",
                name="Command and Scripting Interpreter",
                description="Abuse (Citation: X) of [PowerShell](https://attack.mitre.org/techniques/T1059/001).",
                tactics=["execution"],
                domains=["enterprise-attack"],
            ),
            AttackTechnique(
                stix_id="attack-pattern--t1566",
                attack_id="T1566",
                name="Phishing",
                tactics=["initial-access"],
                domains=["enterprise-attack"],
            ),
        ]
    )
    await async_db_session.flush()
    repo = AsyncAttackQueryRepo(async_db_session)

    rows, total = await repo.get_techniques(search="T1059")
    assert total == 1 and rows[0]["attack_id"] == "T1059"
    rows, total = await repo.get_techniques(search="t1566")
    assert total == 1 and rows[0]["attack_id"] == "T1566"

    doc = await repo.get_technique("T1059")
    assert doc is not None
    assert doc["description"] == "Abuse of PowerShell."
