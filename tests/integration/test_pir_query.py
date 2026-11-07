"""Integration test `AsyncPIRRepo` -- Postgres REAL (testcontainers).
Fase 7.3 (router `pir`, Bagian 2)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.entity_support import seed_entity

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    if await repo.get("acme") is None:
        await repo.create(client_id="acme", name="Acme", countries=[])


async def _seed_articles(article_repo: AsyncArticleRepo) -> None:
    recent = datetime.date.today() - datetime.timedelta(days=2)
    old = datetime.date.today() - datetime.timedelta(days=60)

    a1 = await article_repo.upsert(
        url="https://example.com/apt41-recent",
        title="APT41 hits government network",
        source="gbhacker",
        posted_on=recent,
        news_type="apac",
    )
    await article_repo.set_enrichment(
        a1, threat_actors=["Apt41"], ttps=[("T1574", "Hijack Execution Flow")]
    )

    a2 = await article_repo.upsert(
        url="https://example.com/apt41-old",
        title="APT41 old campaign retrospective",
        source="gbhacker",
        posted_on=old,
        news_type="apac",
    )
    await article_repo.set_enrichment(a2, threat_actors=["Apt41"])

    await article_repo.upsert(
        url="https://example.com/unrelated",
        title="Unrelated vendor product update",
        source="vendorblog",
        posted_on=recent,
        news_type="global",
    )


async def test_create_and_get(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPIRRepo(async_db_session)
    pir = await repo.create(
        {"title": "Track APT41", "criteria": {"threat_actors": ["Apt41"]}}, client_id="default"
    )
    assert pir.status == "active"
    assert pir.priority == "P2"

    fetched = await repo.get_by_id(pir.id)
    assert fetched is not None
    assert fetched.title == "Track APT41"


async def test_list_pirs_scoped_by_client_ordered_by_priority(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPIRRepo(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    await repo.create({"title": "P3 item", "priority": "P3"}, client_id="default")
    await repo.create({"title": "P1 item", "priority": "P1"}, client_id="default")
    await repo.create({"title": "acme item", "priority": "P1"}, client_id="acme")

    rows = await repo.list_pirs(article_repo, "default")
    assert len(rows) == 2
    assert rows[0][0].title == "P1 item"
    assert rows[1][0].title == "P3 item"


async def test_compute_coverage_with_criteria(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed_articles(article_repo)
    repo = AsyncPIRRepo(async_db_session)

    total, last_match, recent = await repo.compute_coverage(
        article_repo, {"threat_actors": ["Apt41"]}, None, None
    )
    assert total == 2
    assert last_match is not None
    assert recent == 1  # cuma a1 (recent) yang masuk window 14 hari


async def test_compute_coverage_empty_criteria_recent_always_zero(
    async_db_session: AsyncSession,
) -> None:
    """Kuirk port apa adanya dari `_compute_coverage()` lama: kriteria
    kosong -> match-all buat total/last_match, tapi `recent` di-hardcode
    0 -- lihat docstring modul `cti_core.db.repositories.pir`."""
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed_articles(article_repo)
    repo = AsyncPIRRepo(async_db_session)

    total, last_match, recent = await repo.compute_coverage(article_repo, {}, None, None)
    assert total == 3
    assert last_match is not None
    assert recent == 0


async def test_list_articles_for_pir_and_notes(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed_articles(article_repo)
    repo = AsyncPIRRepo(async_db_session)
    pir = await repo.create(
        {"title": "Track APT41", "criteria": {"threat_actors": ["Apt41"]}}, client_id="default"
    )

    articles, total = await repo.list_articles_for_pir(pir, article_repo)
    assert total == 2

    await repo.save_note(pir.id, articles[0].url, "worth escalating", "analyst1")
    noted = await repo.urls_with_notes(pir.id, [a.url for a in articles])
    assert noted == {articles[0].url}


async def test_save_note_upserts_by_pir_and_url(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPIRRepo(async_db_session)
    pir = await repo.create({"title": "Track APT41"}, client_id="default")

    first = await repo.save_note(pir.id, "https://example.com/x", "note v1", "analyst1")
    second = await repo.save_note(pir.id, "https://example.com/x", "note v2", "analyst2")
    assert first.id == second.id
    assert second.note == "note v2"
    assert second.analyst == "analyst2"


async def test_get_options_includes_distinct_ttps(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed_articles(article_repo)
    repo = AsyncPIRRepo(async_db_session)

    options = await repo.get_options(article_repo)
    assert "Apt41" in options["threat_actors"]
    assert {"id": "T1574", "name": "Hijack Execution Flow"} in options["ttps"]


async def test_update_and_delete_ignore_client_scope(async_db_session: AsyncSession) -> None:
    """Port apa adanya: sama kayak RFI, `update`/`delete` PIR lama gak
    nge-filter client_id."""
    await _ensure_clients(async_db_session)
    repo = AsyncPIRRepo(async_db_session)
    pir = await repo.create({"title": "Track APT41"}, client_id="default")

    updated = await repo.update(pir.id, {"status": "closed"})
    assert updated is not None
    assert updated.status == "closed"

    assert await repo.delete(pir.id) is True
    assert await repo.get_by_id(pir.id) is None


async def test_pir_note_unique_per_pir_and_url_allows_same_url_different_pir(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPIRRepo(async_db_session)
    pir1 = await repo.create({"title": "PIR 1"}, client_id="default")
    pir2 = await repo.create({"title": "PIR 2"}, client_id="default")

    await repo.save_note(pir1.id, "https://example.com/shared", "note for pir1", "a1")
    await repo.save_note(pir2.id, "https://example.com/shared", "note for pir2", "a2")

    note1 = await repo.get_note(pir1.id, "https://example.com/shared")
    note2 = await repo.get_note(pir2.id, "https://example.com/shared")
    assert note1 is not None and note1.note == "note for pir1"
    assert note2 is not None and note2.note == "note for pir2"


async def test_malware_criterion_matches_malware_and_tool(async_db_session: AsyncSession) -> None:
    """Kriteria `malware` cocok ke mention bertipe malware DAN tool (lewat alias), bukan judul."""
    await _ensure_clients(async_db_session)
    s = async_db_session
    await s.run_sync(lambda sync: seed_entity(sync, "tool", "Cobalt Strike", source="attack"))
    await s.run_sync(
        lambda sync: seed_entity(sync, "malware", "Lumma Stealer", "Lumma", source="attack")
    )
    article_repo = AsyncArticleRepo(s)
    today = datetime.date.today()
    a = await article_repo.upsert(
        url="https://example.com/m-a", title="Intrusion write-up", source="s", posted_on=today
    )
    await article_repo.set_enrichment(a, malware=[("Cobalt Strike", "tool")])
    b = await article_repo.upsert(
        url="https://example.com/m-b", title="Infostealer wave", source="s", posted_on=today
    )
    await article_repo.set_enrichment(b, malware=[("Lumma Stealer", "malware")])
    c = await article_repo.upsert(
        url="https://example.com/m-c", title="Nothing relevant", source="s", posted_on=today
    )
    await article_repo.set_enrichment(c, threat_actors=["Apt41"])

    repo = AsyncPIRRepo(s)
    pir = await repo.create(
        {"title": "Track tooling", "criteria": {"malware": ["cobalt strike", "Lumma"]}},
        client_id="default",
    )
    articles, total = await repo.list_articles_for_pir(pir, article_repo, page=1, page_size=10)
    assert total == 2
    assert {x.id for x in articles} == {a.id, b.id}
    count, _last, recent = await repo.compute_coverage(
        article_repo, pir.criteria, pir.start_date, pir.end_date
    )
    assert count == 2
    assert recent == 2


async def test_old_pir_without_malware_key_unchanged(async_db_session: AsyncSession) -> None:
    """Kriteria lama tanpa kunci `malware` memberi himpunan yang sama seperti sebelumnya."""
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed_articles(article_repo)
    repo = AsyncPIRRepo(async_db_session)
    pir = await repo.create(
        {"title": "Track APT41", "criteria": {"threat_actors": ["Apt41"]}}, client_id="default"
    )
    _articles, total = await repo.list_articles_for_pir(pir, article_repo, page=1, page_size=10)
    assert total == 2
    options = await repo.get_options(article_repo)
    assert options["malware"] == []


async def test_weekly_coverage_counts_matches_per_week(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    await _seed_articles(article_repo)
    repo = AsyncPIRRepo(async_db_session)
    pir = await repo.create(
        {"title": "Track APT41", "criteria": {"threat_actors": ["Apt41"]}}, client_id="default"
    )

    today = datetime.date.today()
    result = await repo.weekly_coverage(pir, weeks=12, today=today)
    assert result is not None
    _, _, rows = result
    assert len(rows) == 12
    assert sum(count for _, count in rows) == 2  # a1 + a2; artikel unrelated tidak ikut
    old = today - datetime.timedelta(days=60)
    old_monday = old - datetime.timedelta(days=old.weekday())
    assert dict(rows)[old_monday] == 1


async def test_weekly_coverage_future_start_returns_none(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncPIRRepo(async_db_session)
    today = datetime.date.today()
    pir = await repo.create(
        {
            "title": "Future",
            "criteria": {"threat_actors": ["Apt41"]},
            "start_date": today + datetime.timedelta(days=30),
        },
        client_id="default",
    )
    assert await repo.weekly_coverage(pir, weeks=12, today=today) is None


async def test_weekly_coverage_trims_first_week_before_mid_week_start(
    async_db_session: AsyncSession,
) -> None:
    """`start_date` di tengah minggu: artikel di minggu yang sama tapi SEBELUM start_date
    tidak dihitung di minggu pertama; artikel pada/sesudah start_date dihitung."""
    await _ensure_clients(async_db_session)
    article_repo = AsyncArticleRepo(async_db_session)
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    # Pakai minggu lalu supaya Rabu dan Senin-Selasa selalu sudah lewat dan dalam jendela.
    week_start = monday - datetime.timedelta(days=7)
    start = week_start + datetime.timedelta(days=2)  # Rabu
    before = week_start + datetime.timedelta(days=1)  # Selasa, sebelum start_date
    for url, day in (("before", before), ("on-start", start)):
        a = await article_repo.upsert(
            url=f"https://example.com/midweek-{url}",
            title=f"APT41 {url}",
            source="gbhacker",
            posted_on=day,
            news_type="apac",
        )
        await article_repo.set_enrichment(a, threat_actors=["Apt41"])
    repo = AsyncPIRRepo(async_db_session)
    pir = await repo.create(
        {
            "title": "Mid-week",
            "criteria": {"threat_actors": ["Apt41"]},
            "start_date": start,
        },
        client_id="default",
    )

    result = await repo.weekly_coverage(pir, weeks=12, today=today)
    assert result is not None
    _, _, rows = result
    assert rows[0][0] == week_start
    assert rows[0][1] == 1  # hanya artikel pada start_date
