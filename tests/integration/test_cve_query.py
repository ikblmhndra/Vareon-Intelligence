"""Integration test `AsyncCveTrackerRepo`/`AsyncCveFalsePositiveRepo` --
Postgres REAL (testcontainers). Fase 7.3 (router `cve`)."""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo, AsyncCveTrackerRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _ensure_clients(session: AsyncSession) -> None:
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    if await repo.get("acme") is None:
        await repo.create(client_id="acme", name="Acme", countries=[])


async def _seed(session: AsyncSession, client_id: str = "default") -> dict[str, str]:
    await _ensure_clients(session)
    rows = [
        CveTracker(
            cve_id="CVE-2026-0001",
            client_id=client_id,
            tech="WordPress",
            summary="Stored XSS in a WordPress plugin",
            cve_score=9.8,
            cve_severity="CRITICAL",
            published=datetime.date(2026, 9, 1),
        ),
        CveTracker(
            cve_id="CVE-2026-0002",
            client_id=client_id,
            tech="Linux",
            summary="Kernel privilege escalation",
            cve_score=7.5,
            cve_severity="HIGH",
            published=datetime.date(2026, 9, 5),
        ),
        CveTracker(
            cve_id="CVE-2026-0003",
            client_id=client_id,
            tech="nginx",
            summary="Config parsing bug",
            cve_score=3.1,
            cve_severity="LOW",
            published=datetime.date(2026, 9, 10),
        ),
    ]
    for row in rows:
        session.add(row)
    await session.flush()
    return {"critical": "CVE-2026-0001", "high": "CVE-2026-0002", "low": "CVE-2026-0003"}


class TestAsyncCveTrackerRepo:
    async def test_list_filtered_scoped_to_client(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session, "default")
        await _seed(async_db_session, "acme")

        cves, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(client_id="default")
        assert total == 3
        assert len(cves) == 3

    async def test_list_filtered_by_tech(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        cves, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(
            client_id="default", tech=["Linux"]
        )
        assert total == 1
        assert cves[0].cve_id == "CVE-2026-0002"

    async def test_list_filtered_by_severity(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        cves, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(
            client_id="default", severity=["critical"]
        )
        assert total == 1
        assert cves[0].cve_id == "CVE-2026-0001"

    async def test_list_filtered_by_search(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        _, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(
            client_id="default", search="kernel"
        )
        assert total == 1

    async def test_list_filtered_by_date_range(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        _, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(
            client_id="default",
            date_start=datetime.date(2026, 9, 4),
            date_end=datetime.date(2026, 9, 8),
        )
        assert total == 1

    async def test_list_filtered_excludes_false_positive_ids(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        _, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(
            client_id="default", exclude_cve_ids=["CVE-2026-0001"]
        )
        assert total == 2

    async def test_list_filtered_sort_by_tech_asc(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        cves, _ = await AsyncCveTrackerRepo(async_db_session).list_filtered(
            client_id="default", sort_by="tech", sort_dir="asc"
        )
        assert [c.tech for c in cves] == ["Linux", "WordPress", "nginx"]

    async def test_get_stats_buckets_by_severity_score(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        stats = await AsyncCveTrackerRepo(async_db_session).get_stats(client_id="default")
        assert stats == {"total": 3, "critical": 1, "high": 1, "medium": 0, "low": 1, "unrated": 0}

    async def test_get_stats_severity_filter_only_affects_total(
        self, async_db_session: AsyncSession
    ) -> None:
        """Port perilaku lama: filter severity di list utama TAPI bucket
        lain tetap ngitung semua data -- kalau enggak, milih satu severity
        bikin bucket lain selalu 0 (gak informatif)."""
        await _seed(async_db_session)
        stats = await AsyncCveTrackerRepo(async_db_session).get_stats(
            client_id="default", severity=["critical"]
        )
        assert stats["total"] == 1
        assert stats["critical"] == 1
        assert stats["high"] == 1
        assert stats["low"] == 1

    async def test_get_tech_list_sorted_and_distinct(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        techs = await AsyncCveTrackerRepo(async_db_session).get_tech_list("default")
        assert techs == ["Linux", "WordPress", "nginx"]

    async def test_get_stats_counts_cves_without_cvss_as_unrated(
        self, async_db_session: AsyncSession
    ) -> None:
        """CNA yang tidak mengisi CVSS membuat scraper menulis skor 0.0 (atau NULL untuk baris
        lama). Dulu CVE itu masuk `total` tapi tidak masuk bucket mana pun, jadi kartu stats tidak
        pernah menjumlah ke total."""
        await _ensure_clients(async_db_session)
        async_db_session.add_all(
            [
                CveTracker(cve_id="CVE-2026-0801", client_id="default", tech="x", cve_score=9.5),
                CveTracker(cve_id="CVE-2026-0802", client_id="default", tech="x", cve_score=0.0),
                CveTracker(cve_id="CVE-2026-0803", client_id="default", tech="x", cve_score=None),
            ]
        )
        await async_db_session.flush()

        stats = await AsyncCveTrackerRepo(async_db_session).get_stats(client_id="default")
        assert stats["total"] == 3
        assert stats["unrated"] == 2
        assert sum(stats[k] for k in ("critical", "high", "medium", "low", "unrated")) == 3

    async def test_date_basis_decides_which_date_the_range_filters(
        self, async_db_session: AsyncSession
    ) -> None:
        """List/stats dan export dulu memakai tanggal berbeda (published vs detected_on) di balik
        input From/To yang sama. Kini dasarnya eksplisit (`date_basis`) dan "detected" dibaca
        sebagai hari kalender WIB, sama dengan dashboard: 18.00 UTC 30 Sep = 01.00 WIB 1 Okt."""
        await _ensure_clients(async_db_session)
        async_db_session.add(
            CveTracker(
                cve_id="CVE-2026-0901",
                client_id="default",
                tech="x",
                published=datetime.date(2026, 9, 15),
                detected_on=datetime.datetime(2026, 9, 30, 18, 0, tzinfo=datetime.UTC),
            )
        )
        await async_db_session.flush()
        repo = AsyncCveTrackerRepo(async_db_session)
        oct_1 = datetime.date(2026, 10, 1)

        _, by_published = await repo.list_filtered(client_id="default", date_start=oct_1)
        _, by_detected = await repo.list_filtered(
            client_id="default", date_start=oct_1, date_basis="detected"
        )
        stats = await repo.get_stats(client_id="default", date_start=oct_1, date_basis="detected")
        assert (by_published, by_detected, stats["total"]) == (0, 1, 1)

        # export tetap default ke "detected" (laporan bulanan), dan bisa diganti ke "published"
        assert len(await repo.list_for_export(client_id="default", date_start=oct_1)) == 1
        assert (
            await repo.list_for_export(
                client_id="default", date_start=oct_1, date_basis="published"
            )
            == []
        )

    async def test_get_article_mentions_matches_cve_id_in_title(
        self, async_db_session: AsyncSession
    ) -> None:
        async_db_session.add(
            Article(
                url="https://example.com/a",
                url_hash="hash-a",
                title="Exploit for CVE-2026-0001 found in the wild",
                source="test",
            )
        )
        async_db_session.add(
            Article(
                url="https://example.com/b",
                url_hash="hash-b",
                title="Unrelated article",
                source="test",
            )
        )
        await async_db_session.flush()

        mentions = await AsyncCveTrackerRepo(async_db_session).get_article_mentions(
            ["CVE-2026-0001", "CVE-2026-0002"]
        )
        assert len(mentions["CVE-2026-0001"]) == 1
        assert mentions["CVE-2026-0001"][0]["url"] == "https://example.com/a"
        assert mentions["CVE-2026-0002"] == []

    async def test_get_article_mentions_does_not_match_longer_cve_number(
        self, async_db_session: AsyncSession
    ) -> None:
        """`CVE-2026-1234` bukan penyebutan `CVE-2026-12345` -- hanya batas angka yang dicek,
        tanda baca di sekitarnya tetap boleh."""
        titles = {
            "longer": "Mass exploitation of CVE-2026-12345 continues",
            "exact": "Patch now: (CVE-2026-1234), says vendor",
        }
        for key, title in titles.items():
            async_db_session.add(
                Article(url=f"https://example.com/{key}", url_hash=key, title=title, source="t")
            )
        await async_db_session.flush()

        mentions = await AsyncCveTrackerRepo(async_db_session).get_article_mentions(
            ["CVE-2026-1234", "CVE-2026-12345"]
        )
        assert [m["url"] for m in mentions["CVE-2026-1234"]] == ["https://example.com/exact"]
        assert [m["url"] for m in mentions["CVE-2026-12345"]] == ["https://example.com/longer"]

    async def test_get_article_mentions_empty_input_returns_empty_dict(
        self, async_db_session: AsyncSession
    ) -> None:
        assert await AsyncCveTrackerRepo(async_db_session).get_article_mentions([]) == {}

    async def test_purge_orphaned_dry_run_does_not_delete(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        result = await AsyncCveTrackerRepo(async_db_session).purge_orphaned(
            client_id="default", active_tech_names=["WordPress"], dry_run=True
        )
        assert result["dry_run"] is True
        assert result["would_delete"] == 2
        assert set(result["cve_ids"]) == {"CVE-2026-0002", "CVE-2026-0003"}

        _, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(client_id="default")
        assert total == 3

    async def test_purge_orphaned_actually_deletes(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        result = await AsyncCveTrackerRepo(async_db_session).purge_orphaned(
            client_id="default", active_tech_names=["WordPress"], dry_run=False
        )
        assert result["dry_run"] is False
        assert result["deleted"] == 2

        _, total = await AsyncCveTrackerRepo(async_db_session).list_filtered(client_id="default")
        assert total == 1

    async def test_purge_orphaned_no_active_tech_deletes_all(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        result = await AsyncCveTrackerRepo(async_db_session).purge_orphaned(
            client_id="default", active_tech_names=[], dry_run=True
        )
        assert result["would_delete"] == 3

    async def test_purge_orphaned_cascades_false_positive_delete(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        fp_repo = AsyncCveFalsePositiveRepo(async_db_session)
        await fp_repo.mark("CVE-2026-0002", "default")

        await AsyncCveTrackerRepo(async_db_session).purge_orphaned(
            client_id="default", active_tech_names=["WordPress"], dry_run=False
        )
        assert await fp_repo.list_cve_ids("default") == []


class TestAsyncCveFalsePositiveRepo:
    async def test_mark_and_list(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        repo = AsyncCveFalsePositiveRepo(async_db_session)
        await repo.mark("CVE-2026-0001", "default", marked_by="admin1")
        assert await repo.list_cve_ids("default") == ["CVE-2026-0001"]

    async def test_mark_is_idempotent(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        repo = AsyncCveFalsePositiveRepo(async_db_session)
        await repo.mark("CVE-2026-0001", "default")
        await repo.mark("CVE-2026-0001", "default")
        assert await repo.list_cve_ids("default") == ["CVE-2026-0001"]

    async def test_unmark_removes_entry(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        repo = AsyncCveFalsePositiveRepo(async_db_session)
        await repo.mark("CVE-2026-0001", "default")
        await repo.unmark("CVE-2026-0001", "default")
        assert await repo.list_cve_ids("default") == []

    async def test_unmark_missing_entry_is_noop(self, async_db_session: AsyncSession) -> None:
        repo = AsyncCveFalsePositiveRepo(async_db_session)
        await repo.unmark("CVE-2026-9999", "default")  # gak raise

    async def test_bulk_mark_skips_already_marked(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        repo = AsyncCveFalsePositiveRepo(async_db_session)
        await repo.mark("CVE-2026-0001", "default")

        count = await repo.bulk_mark(["CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"], "default")
        assert count == 2
        assert set(await repo.list_cve_ids("default")) == {
            "CVE-2026-0001",
            "CVE-2026-0002",
            "CVE-2026-0003",
        }

    async def test_fp_scoped_per_client(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session, "default")
        await _seed(async_db_session, "acme")
        repo = AsyncCveFalsePositiveRepo(async_db_session)
        await repo.mark("CVE-2026-0001", "default")

        assert await repo.list_cve_ids("default") == ["CVE-2026-0001"]
        assert await repo.list_cve_ids("acme") == []


class TestNewsletterMentions:
    """`AsyncCveTrackerRepo.add_newsletter_mention`/`list_all_distinct_cve_ids`
    -- Fase 7.3 (router `newsletter`, Bagian 4)."""

    async def test_add_newsletter_mention(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        repo = AsyncCveTrackerRepo(async_db_session)

        added = await repo.add_newsletter_mention(
            "CVE-2026-0001",
            title="Actively exploited in the wild",
            url="https://example.com/article",
            source="gbhacker",
            mention_date="2026-09-19",
        )
        assert added is True

        cve = await repo.get_by_cve_id_any_client("CVE-2026-0001")
        assert cve is not None
        assert len(cve.newsletter_mentions) == 1
        assert cve.newsletter_mentions[0].url == "https://example.com/article"

    async def test_add_newsletter_mention_dedups_by_url(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        repo = AsyncCveTrackerRepo(async_db_session)

        await repo.add_newsletter_mention(
            "CVE-2026-0001",
            title="t1",
            url="https://example.com/x",
            source="s",
            mention_date="2026-09-19",
        )
        added_again = await repo.add_newsletter_mention(
            "CVE-2026-0001",
            title="t2",
            url="https://example.com/x",
            source="s",
            mention_date="2026-09-20",
        )
        assert added_again is False

        cve = await repo.get_by_cve_id_any_client("CVE-2026-0001")
        assert cve is not None
        assert len(cve.newsletter_mentions) == 1

    async def test_add_newsletter_mention_unknown_cve_is_noop(
        self, async_db_session: AsyncSession
    ) -> None:
        repo = AsyncCveTrackerRepo(async_db_session)
        added = await repo.add_newsletter_mention(
            "CVE-9999-9999", title="t", url="https://example.com/x", source="s", mention_date=""
        )
        assert added is False

    async def test_list_all_distinct_cve_ids(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session, "default")
        await _seed(async_db_session, "acme")
        repo = AsyncCveTrackerRepo(async_db_session)

        ids = await repo.list_all_distinct_cve_ids()
        assert set(ids) == {"CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"}
