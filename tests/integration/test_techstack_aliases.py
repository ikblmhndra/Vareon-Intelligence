"""`techstack_entries.aliases` -- ROADMAP #19 fase 1, Postgres sungguhan (testcontainers).

Yang dikunci: migrasi mengisi alias seed berdasarkan `lower(name)` dan membiarkan nama lain;
resolver reference data menggabungkan alias lintas client; `prioritize_campaign_cves` memakai alias
entri dan tidak lagi mencocokkan substring (`go` ~ `google`)."""

from __future__ import annotations

import datetime
from collections.abc import Iterator

import pytest
from cti_api.services import cve_priority as svc
from cti_core.db.models.auth import Client
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.techstack import TechStackEntry
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_scraper.reference_data import resolve_reference_data
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from tests.integration.conftest import _find_repo_root

_PREVIOUS_REVISION = "e8c2a4b6d1f3"


@pytest.fixture
def migration_at_previous_revision(_migrated_schema: None) -> Iterator[None]:
    """Turunkan skema satu langkah (sebelum kolom `aliases`), lalu pulihkan ke head. Pemulihan
    di `finally` supaya test lain di database bersama ini tidak ketinggalan skema lama."""
    from alembic.config import Config

    from alembic import command

    root = _find_repo_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.downgrade(cfg, _PREVIOUS_REVISION)
    try:
        yield
    finally:
        command.upgrade(cfg, "head")


def test_migration_seeds_aliases_by_lowercase_name(migration_at_previous_revision: None) -> None:
    from alembic.config import Config
    from cti_core.db.engine import get_sync_engine
    from sqlalchemy import text

    from alembic import command

    engine = get_sync_engine()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO clients (client_id, name) VALUES ('seedtest', 'Seed')"))
        for name in ("Palo Alto", "MIKROTIK", "wazuh", "tech-yang-tak-ada-di-seed"):
            conn.execute(
                text("INSERT INTO techstack_entries (name, client_id) VALUES (:name, 'seedtest')"),
                {"name": name},
            )

    root = _find_repo_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        rows = dict(
            conn.execute(
                text("SELECT name, aliases FROM techstack_entries WHERE client_id = 'seedtest'")
            ).all()
        )
        conn.execute(text("DELETE FROM clients WHERE client_id = 'seedtest'"))
        conn.commit()

    assert "pan-os" in rows["Palo Alto"]  # kunci seed `palo alto` cocok dengan `Palo Alto`
    assert rows["MIKROTIK"] == ["routeros"]
    assert rows["wazuh"] == []  # tidak ada di seed -> kosong, bukan NULL
    assert rows["tech-yang-tak-ada-di-seed"] == []


def test_reference_data_merges_aliases_across_clients(db_session: Session) -> None:
    for cid in ("acme", "globex"):
        db_session.add(Client(client_id=cid, name=cid.title()))
    db_session.add_all(
        [
            TechStackEntry(name="Palo_Alto", client_id="acme", aliases=["pan-os", "panos"]),
            TechStackEntry(
                name="palo alto", client_id="globex", aliases=["pan-os", "globalprotect"]
            ),
            TechStackEntry(name="wazuh", client_id="acme", aliases=[]),
        ]
    )
    db_session.flush()

    ref = resolve_reference_data(("techstack_aliases",), db_session)["techstack_aliases"]

    # kunci ternormalisasi, gabungan tanpa duplikat, tech tanpa alias tidak ikut
    assert ref == {"palo alto": ["globalprotect", "pan-os", "panos"]}


async def test_new_entries_default_to_no_aliases(async_db_session: AsyncSession) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    entry = TechStackEntry(name="okta", client_id="default", added_date=datetime.date(2026, 10, 7))
    async_db_session.add(entry)
    await async_db_session.flush()
    await async_db_session.refresh(entry)

    assert entry.aliases == []


async def test_prioritize_counts_a_cve_under_an_alias_and_ignores_substrings(
    async_db_session: AsyncSession,
) -> None:
    await AsyncClientRepo(async_db_session).ensure_default()
    async_db_session.add_all(
        [
            TechStackEntry(name="palo alto", client_id="default", aliases=["pan-os"]),
            TechStackEntry(name="google", client_id="default"),
            CveTracker(cve_id="CVE-2026-1001", client_id="default", tech="PAN-OS", cve_score=5.0),
            CveTracker(cve_id="CVE-2026-1002", client_id="default", tech="go", cve_score=5.0),
        ]
    )
    await async_db_session.flush()

    result = await svc.prioritize_campaign_cves(
        async_db_session, ["CVE-2026-1001", "CVE-2026-1002"], client_id="default"
    )
    by_id = {r["cve_id"]: r["in_tech_stack"] for r in result}

    assert by_id == {"CVE-2026-1001": True, "CVE-2026-1002": False}
