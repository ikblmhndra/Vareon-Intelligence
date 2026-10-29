"""Integration test `cti_api.services.fp_analytics` -- Postgres REAL
(testcontainers). Fase 7.4 Grup D."""

from __future__ import annotations

import pytest
from cti_api.services import fp_analytics as svc
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seeded_ioc_with_feedback(
    repo: AsyncIndicatorRepo, *, ioc_type: str, value: str, source_name: str, verdicts: list[str]
):
    created = await repo.upsert(
        type=ioc_type, value=value, source_url="https://x.com", source_name=source_name
    )
    ioc = await repo.get_by_id(created.id)
    assert ioc is not None
    for v in verdicts:
        ioc = await repo.get_by_id(ioc.id)
        assert ioc is not None
        await repo.add_feedback(ioc, verdict=v, submitted_by="analyst1")
    fetched = await repo.get_by_id(created.id)
    assert fetched is not None
    return fetched


async def test_get_fp_analytics_aggregates_by_source_and_type(
    async_db_session: AsyncSession,
) -> None:
    svc.invalidate_fp_cache()
    repo = AsyncIndicatorRepo(async_db_session)
    await _seeded_ioc_with_feedback(
        repo, ioc_type="ip", value="1.1.1.1", source_name="SourceA", verdicts=["fp", "fp"]
    )
    await _seeded_ioc_with_feedback(
        repo, ioc_type="domain", value="evil.example", source_name="SourceA", verdicts=["tp"]
    )

    result = await svc.get_fp_analytics(async_db_session, force=True)
    assert result["fp_by_source"]["SourceA"]["total_iocs"] == 2
    assert result["fp_by_source"]["SourceA"]["fp_count"] == 2
    assert result["fp_by_type"]["ip"]["fp_count"] == 2
    assert result["fp_by_type"]["domain"]["fp_count"] == 0


async def test_get_fp_analytics_suggests_allowlist_for_fp_heavy_ioc(
    async_db_session: AsyncSession,
) -> None:
    svc.invalidate_fp_cache()
    repo = AsyncIndicatorRepo(async_db_session)
    await _seeded_ioc_with_feedback(
        repo,
        ioc_type="url",
        value="https://benign.example/path",
        source_name="SourceB",
        verdicts=["fp", "fp", "fp"],
    )

    result = await svc.get_fp_analytics(async_db_session, force=True)
    suggestions = result["suggested_allowlist"]
    assert len(suggestions) == 1
    assert suggestions[0]["allowlist_type"] == "url_domain"
    assert suggestions[0]["fp_count"] == 3


async def test_get_fp_analytics_no_suggestion_when_tp_present(
    async_db_session: AsyncSession,
) -> None:
    svc.invalidate_fp_cache()
    repo = AsyncIndicatorRepo(async_db_session)
    await _seeded_ioc_with_feedback(
        repo,
        ioc_type="url",
        value="https://mixed.example/path",
        source_name="SourceC",
        verdicts=["fp", "fp", "fp", "tp"],
    )

    result = await svc.get_fp_analytics(async_db_session, force=True)
    assert result["suggested_allowlist"] == []


async def test_get_fp_analytics_ignores_iocs_without_feedback(
    async_db_session: AsyncSession,
) -> None:
    svc.invalidate_fp_cache()
    repo = AsyncIndicatorRepo(async_db_session)
    await repo.upsert(type="ip", value="8.8.8.8", source_url="https://x.com", source_name="SourceD")

    result = await svc.get_fp_analytics(async_db_session, force=True)
    assert result["fp_by_source"] == {}
    assert result["fp_by_type"] == {}


async def test_get_fp_analytics_caches_until_force(async_db_session: AsyncSession) -> None:
    svc.invalidate_fp_cache()
    repo = AsyncIndicatorRepo(async_db_session)
    await _seeded_ioc_with_feedback(
        repo, ioc_type="ip", value="2.2.2.2", source_name="SourceE", verdicts=["fp"]
    )

    first = await svc.get_fp_analytics(async_db_session, force=True)
    assert first["fp_by_source"]["SourceE"]["total_iocs"] == 1

    # tambah 1 IOC lagi TANPA `force` -- cache 300s TTL masih kepake,
    # hasil harusnya sama kayak `first`
    await _seeded_ioc_with_feedback(
        repo, ioc_type="ip", value="3.3.3.3", source_name="SourceE", verdicts=["fp"]
    )
    cached = await svc.get_fp_analytics(async_db_session)
    assert cached["fp_by_source"]["SourceE"]["total_iocs"] == 1

    forced = await svc.get_fp_analytics(async_db_session, force=True)
    assert forced["fp_by_source"]["SourceE"]["total_iocs"] == 2
    svc.invalidate_fp_cache()


class TestAutoSuppressCheck:
    async def test_private_ip_suppressed(self, async_db_session: AsyncSession) -> None:
        result = await svc.auto_suppress_check(async_db_session, "ip", "10.0.0.5")
        assert result["should_suppress"] is True
        assert result["confidence"] == 0.99

    async def test_public_ip_not_suppressed(self, async_db_session: AsyncSession) -> None:
        result = await svc.auto_suppress_check(async_db_session, "ip", "8.8.8.8")
        assert result["should_suppress"] is False

    async def test_known_cdn_domain_suppressed(self, async_db_session: AsyncSession) -> None:
        result = await svc.auto_suppress_check(async_db_session, "domain", "cdn.cloudflare.com")
        assert result["should_suppress"] is True
        assert result["confidence"] == 0.95

    async def test_gmail_email_suppressed(self, async_db_session: AsyncSession) -> None:
        result = await svc.auto_suppress_check(async_db_session, "email", "someone@gmail.com")
        assert result["should_suppress"] is True
        assert result["confidence"] == 0.90

    async def test_unknown_domain_not_suppressed(self, async_db_session: AsyncSession) -> None:
        result = await svc.auto_suppress_check(async_db_session, "domain", "totally-evil.example")
        assert result["should_suppress"] is False

    async def test_high_fp_rate_source_suppressed(self, async_db_session: AsyncSession) -> None:
        svc.invalidate_fp_cache()
        repo = AsyncIndicatorRepo(async_db_session)
        for i in range(10):
            await _seeded_ioc_with_feedback(
                repo,
                ioc_type="domain",
                value=f"host{i}.example",
                source_name="BadSource",
                verdicts=["fp"] if i < 6 else ["tp"],
            )
        result = await svc.auto_suppress_check(
            async_db_session, "domain", "brandnew.example", "BadSource"
        )
        assert result["should_suppress"] is True
        assert "BadSource" in result["reason"]
        svc.invalidate_fp_cache()
