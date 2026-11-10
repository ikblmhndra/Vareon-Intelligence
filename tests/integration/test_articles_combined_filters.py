"""Filter gabungan `GET /api/articles` di balik deep link halaman Intelligence (`newsroomHref`):
beberapa filter berbeda dikirim bersamaan dan harus berlaku AND, bukan salah satu. Test ini
mengunci perilaku yang sudah ada (regression), supaya tautan sel risk matrix / profil aktor
tidak diam-diam melebar saat query filter diubah."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_api.services import risk_matrix
from cti_core.db.models.entity import Entity
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.entity_support import seed_entity

pytestmark = pytest.mark.asyncio

TODAY = datetime.date.today()


async def _article(
    session: AsyncSession,
    slug: str,
    *,
    posted_on: datetime.date | None = TODAY,
    **enrichment: object,
) -> int:
    repo = AsyncArticleRepo(session)
    article = await repo.upsert(
        url=f"https://s.example/{slug}", title=slug, source="S", posted_on=posted_on
    )
    if enrichment:
        await repo.set_enrichment(article, **enrichment)  # type: ignore[arg-type]
    return article.id


async def _ids(
    client: AsyncClient, auth_header: Callable[..., dict[str, str]], query: str
) -> tuple[set[int], int]:
    resp = await client.get(f"/api/articles?{query}", headers=auth_header())
    assert resp.status_code == 200
    body = resp.json()
    return {a["id"] for a in body["articles"]}, body["total"]


async def test_actor_and_ttp_and_together(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    both = await _article(
        api_session, "both", threat_actors=["APT41"], ttps=[("T1059", "Command and Scripting")]
    )
    await _article(api_session, "actor-only", threat_actors=["APT41"])
    await _article(api_session, "ttp-only", ttps=[("T1059", "Command and Scripting")])
    await api_session.commit()

    ids, total = await _ids(api_client, auth_header, "threat_actor=APT41&ttp=T1059")
    assert ids == {both}
    assert total == 1


async def test_industry_and_country_and_together(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await AsyncClientRepo(api_session).ensure_default()
    both = await _article(
        api_session, "both", industries=["Finance"], countries=[("ID", "mentioned")]
    )
    await _article(api_session, "industry-only", industries=["Finance"])
    await _article(api_session, "country-only", countries=[("ID", "mentioned")])
    await _article(
        api_session, "other-country", industries=["Finance"], countries=[("US", "mentioned")]
    )
    await api_session.commit()

    ids, total = await _ids(api_client, auth_header, "industry=Finance&country=ID")
    assert ids == {both}
    assert total == 1


async def test_actor_alias_name_matches(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Deep link memakai nama yang dilihat analis; alias harus menemukan artikel aktor kanonik."""
    await AsyncClientRepo(api_session).ensure_default()
    entity: Entity = await api_session.run_sync(
        lambda s: seed_entity(s, "intrusion-set", "APT41", "Wicked Panda", source="galaxy")
    )
    assert entity.id is not None
    apt41 = await _article(api_session, "apt41", threat_actors=["APT41"])
    await _article(api_session, "other", threat_actors=["APT29"])
    await api_session.commit()

    ids, _total = await _ids(api_client, auth_header, "threat_actor=wicked panda")
    assert ids == {apt41}


async def test_total_equals_risk_matrix_current_count(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Angka di sel risk matrix harus sama dengan total daftar yang dibuka dari sel itu."""
    await AsyncClientRepo(api_session).ensure_default()
    for slug in ("cell-1", "cell-2"):
        await _article(api_session, slug, industries=["Finance"], countries=[("ID", "mentioned")])
    # posted_on kosong: tidak masuk matriks, juga tidak masuk filter rentang tanggal
    await _article(
        api_session,
        "undated",
        posted_on=None,
        industries=["Finance"],
        countries=[("ID", "mentioned")],
    )
    await api_session.commit()
    risk_matrix._CACHE.clear()

    start = TODAY - datetime.timedelta(days=30)
    _ids_found, total = await _ids(
        api_client, auth_header, f"industry=Finance&country=ID&posted_on_start={start}"
    )
    resp = await api_client.get("/api/intelligence/risk-matrix?days=30", headers=auth_header())
    assert resp.status_code == 200
    cells = [
        c for c in resp.json()["matrix"] if c["industry"] == "Finance" and c["country"] == "ID"
    ]
    assert len(cells) == 1
    assert cells[0]["current_count"] == 2
    assert total == cells[0]["current_count"]
