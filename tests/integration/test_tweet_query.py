"""Integration test `AsyncTweetRepo`/`AsyncMonitoredAccountRepo` -- Postgres
REAL (testcontainers). Fase 7.3 (router `tweets`/`monitored_accounts`)."""

from __future__ import annotations

import datetime
from typing import cast

import pytest
from cti_core.db.models.tweet import Tweet
from cti_core.db.repositories.tweet import AsyncMonitoredAccountRepo, AsyncTweetRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    session.add(
        Tweet(
            tweet_id="1001",
            url="https://x.com/a/status/1001",
            text="APAC ransomware group hits a bank",
            author_username="threatfeed",
            posted_on=datetime.datetime(2026, 9, 10, tzinfo=datetime.UTC),
            scan_results={"apac_indicator": True, "ot_status": False},
            confirmed_incident=True,
        )
    )
    session.add(
        Tweet(
            tweet_id="1002",
            url="https://x.com/b/status/1002",
            text="OT system compromised in Europe",
            author_username="othersource",
            posted_on=datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC),
            scan_results={"apac_indicator": False, "ot_status": True},
            confirmed_incident=False,
        )
    )
    session.add(
        Tweet(
            tweet_id="1003",
            url="https://x.com/a/status/1003",
            text="Unrelated tech announcement",
            author_username="threatfeed",
            posted_on=datetime.datetime(2026, 9, 14, tzinfo=datetime.UTC),
            scan_results={},
            confirmed_incident=False,
        )
    )
    await session.flush()


async def _seed_signals(session: AsyncSession) -> None:
    """Baris dengan tiap kunci list: berisi, kosong `[]`, JSON null, dan tidak ada."""
    rows: list[tuple[str, dict[str, object], bool, str | None]] = [
        (
            "2001",
            {
                "apac_indicator": True,
                "ot_status": True,
                "cve_list": ["CVE-2026-0001"],
                "databreach_list": ["acme"],
                "zero_day_list": ["x"],
            },
            True,
            "LockBit Bank",
        ),
        (
            "2002",
            {"cve_list": [], "databreach_list": None, "zero_day_list": []},
            False,
            " lockbit bank ",
        ),
        ("2003", {"cve_list": None}, True, "Zeta Corp"),
        ("2004", {}, False, None),
        ("2005", {"cve_list": ["CVE-2026-0002"]}, False, "   "),
    ]
    for i, (tid, scan, confirmed, victim) in enumerate(rows):
        session.add(
            Tweet(
                tweet_id=tid,
                url=f"https://x.com/a/status/{tid}",
                text=f"post {tid}",
                author_username="threatfeed",
                posted_on=datetime.datetime(2026, 9, 10 + i, tzinfo=datetime.UTC),
                scan_results=scan,
                confirmed_incident=confirmed,
                victim_name=victim,
            )
        )
    await session.flush()


class TestAsyncTweetRepo:
    async def test_list_filtered_no_filters_returns_all(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        tweets, total = await AsyncTweetRepo(async_db_session).list_filtered()
        assert total == 3
        # posted_on desc
        assert tweets[0].tweet_id == "1003"

    async def test_list_filtered_by_apac_only(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        tweets, total = await AsyncTweetRepo(async_db_session).list_filtered(apac_only=True)
        assert total == 1
        assert tweets[0].tweet_id == "1001"

    async def test_list_filtered_by_ot_only(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        tweets, total = await AsyncTweetRepo(async_db_session).list_filtered(ot_only=True)
        assert total == 1
        assert tweets[0].tweet_id == "1002"

    async def test_list_filtered_by_confirmed_only(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        tweets, total = await AsyncTweetRepo(async_db_session).list_filtered(confirmed_only=True)
        assert total == 1
        assert tweets[0].tweet_id == "1001"

    async def test_list_filtered_by_author(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        _, total = await AsyncTweetRepo(async_db_session).list_filtered(author="threatfeed")
        assert total == 2

    async def test_list_filtered_by_search(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        _, total = await AsyncTweetRepo(async_db_session).list_filtered(search="ransomware")
        assert total == 1

    async def test_list_filtered_by_date_range(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        _, total = await AsyncTweetRepo(async_db_session).list_filtered(
            posted_on_start=datetime.datetime(2026, 9, 11, tzinfo=datetime.UTC),
            posted_on_end=datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC),
        )
        assert total == 1

    async def test_list_filtered_by_author_strips_leading_at(
        self, async_db_session: AsyncSession
    ) -> None:
        """QA BUG-B6: placeholder UI "@handle…" -> user ngetik "@threatfeed",
        `author_username` disimpan tanpa `@` -> dulu 0 hasil."""
        await _seed(async_db_session)
        repo = AsyncTweetRepo(async_db_session)
        _, total = await repo.list_filtered(author="@threatfeed")
        assert total == 2
        _, total = await repo.list_filtered(author=" @threatfeed ")
        assert total == 2
        stats = await repo.get_stats(author="@threatfeed")
        assert stats["total"] == 2

    async def test_list_filtered_posted_before_is_exclusive(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed(async_db_session)
        repo = AsyncTweetRepo(async_db_session)
        # 1002 diposting PERSIS 2026-09-12 00:00 UTC -- `posted_before` itu `<`.
        _, total = await repo.list_filtered(
            posted_on_start=datetime.datetime(2026, 9, 10, tzinfo=datetime.UTC),
            posted_before=datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC),
        )
        assert total == 1
        stats = await repo.get_stats(
            posted_before=datetime.datetime(2026, 9, 12, 0, 0, 1, tzinfo=datetime.UTC)
        )
        assert stats["total"] == 2

    async def test_list_filtered_pagination_stable_when_posted_on_ties(
        self, async_db_session: AsyncSession
    ) -> None:
        ts = datetime.datetime(2026, 9, 30, 13, 20, tzinfo=datetime.UTC)
        async_db_session.add_all(
            Tweet(
                tweet_id=f"9{i:03d}",
                url=f"https://x.com/t/status/9{i:03d}",
                text="same second",
                author_username="burst",
                posted_on=ts,
                scan_results={},
            )
            for i in range(45)
        )
        await async_db_session.flush()
        repo = AsyncTweetRepo(async_db_session)
        seen: list[int] = []
        for page in range(1, 8):
            tweets, _ = await repo.list_filtered(page=page, page_size=7)
            seen.extend(t.id for t in tweets)
        assert len(seen) == 45
        assert seen == sorted(seen, reverse=True)

    async def test_get_stats_top_authors(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        stats = await AsyncTweetRepo(async_db_session).get_stats()
        assert stats["total"] == 3
        rows = cast("list[dict[str, object]]", stats["top_authors"])
        by_author = {row["author"]: row["count"] for row in rows}
        assert by_author["threatfeed"] == 2
        assert by_author["othersource"] == 1

    async def test_get_stats_respects_filters(self, async_db_session: AsyncSession) -> None:
        await _seed(async_db_session)
        stats = await AsyncTweetRepo(async_db_session).get_stats(apac_only=True)
        assert stats["total"] == 1

    async def test_get_stats_counters(self, async_db_session: AsyncSession) -> None:
        await _seed_signals(async_db_session)
        stats = await AsyncTweetRepo(async_db_session).get_stats()
        assert stats["total"] == 5
        assert stats["confirmed"] == 2
        assert stats["apac"] == 1
        assert stats["ot"] == 1
        # null / [] / kunci hilang dihitung tidak ada
        assert stats["with_cve"] == 2
        assert stats["databreach"] == 1
        assert stats["zero_day"] == 1

    async def test_get_stats_counters_follow_filters(self, async_db_session: AsyncSession) -> None:
        await _seed_signals(async_db_session)
        repo = AsyncTweetRepo(async_db_session)
        apac = await repo.get_stats(apac_only=True)
        assert (apac["total"], apac["confirmed"], apac["with_cve"], apac["zero_day"]) == (
            1,
            1,
            1,
            1,
        )
        assert apac["top_victims"] == [{"victim": "LockBit Bank", "count": 1}]
        confirmed = await repo.get_stats(confirmed_only=True)
        assert (confirmed["total"], confirmed["apac"], confirmed["with_cve"]) == (2, 1, 1)
        assert confirmed["top_victims"] == [
            {"victim": "LockBit Bank", "count": 1},
            {"victim": "Zeta Corp", "count": 1},
        ]
        ranged = await repo.get_stats(
            posted_on_start=datetime.datetime(2026, 9, 12, tzinfo=datetime.UTC)
        )
        assert ranged["total"] == 3
        assert ranged["confirmed"] == 1
        assert ranged["with_cve"] == 1
        assert ranged["top_victims"] == [{"victim": "Zeta Corp", "count": 1}]

    async def test_get_stats_top_victims(self, async_db_session: AsyncSession) -> None:
        await _seed_signals(async_db_session)
        for i, name in enumerate(["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]):
            async_db_session.add(
                Tweet(
                    tweet_id=f"3{i}",
                    url=f"https://x.com/a/status/3{i}",
                    text="x",
                    author_username="threatfeed",
                    victim_name=name,
                )
            )
        await async_db_session.flush()
        stats = await AsyncTweetRepo(async_db_session).get_stats()
        victims = cast("list[dict[str, object]]", stats["top_victims"])
        # dua varian LockBit melebur (tanpa beda huruf/spasi), None dan kosong dilewati
        assert victims[0] == {"victim": "LockBit Bank", "count": 2}
        assert len(victims) == 5
        # urutan: count desc lalu label
        assert [v["victim"] for v in victims[1:]] == ["Alpha", "Bravo", "Charlie", "Delta"]

    async def test_search_matches_text_handle_victim_and_cve(
        self, async_db_session: AsyncSession
    ) -> None:
        await _seed_signals(async_db_session)
        async_db_session.add(
            Tweet(tweet_id="4001", url="u", text="plain", author_username="rst_cloud")
        )
        await async_db_session.flush()
        repo = AsyncTweetRepo(async_db_session)

        async def ids(q: str) -> set[str]:
            rows, _ = await repo.list_filtered(search=q)
            return {t.tweet_id for t in rows}

        assert await ids("post 2003") == {"2003"}  # teks
        assert await ids("rst_cl") == {"4001"}  # handle
        assert await ids("zeta") == {"2003"}  # korban
        assert await ids("CVE-2026-0002") == {"2005"}  # CVE di scan_results
        # metakarakter LIKE dibaca literal: "_" bukan wildcard satu karakter, "%" bukan semua
        assert await ids("rst_cloud") == {"4001"}
        assert await ids("rstXcloud") == set()
        assert await ids("100%") == set()

    async def test_search_handle_with_at(self, async_db_session: AsyncSession) -> None:
        await _seed_signals(async_db_session)
        async_db_session.add(
            Tweet(tweet_id="4001", url="u", text="plain", author_username="rst_cloud")
        )
        await async_db_session.flush()
        rows, total = await AsyncTweetRepo(async_db_session).list_filtered(search="@rst_cloud")
        assert total == 1
        assert rows[0].tweet_id == "4001"

    async def test_list_filtered_has_cve(self, async_db_session: AsyncSession) -> None:
        await _seed_signals(async_db_session)
        rows, total = await AsyncTweetRepo(async_db_session).list_filtered(has_cve=True)
        assert total == 2
        assert {t.tweet_id for t in rows} == {"2001", "2005"}

    async def test_list_filtered_signal_each_value(self, async_db_session: AsyncSession) -> None:
        await _seed_signals(async_db_session)
        async_db_session.add(
            Tweet(
                tweet_id="4002",
                url="u",
                text="r",
                author_username="x",
                scan_results={"report_status": True, "ot_status": False},
            )
        )
        await async_db_session.flush()
        repo = AsyncTweetRepo(async_db_session)

        async def ids(signal: str) -> set[str]:
            rows, _ = await repo.list_filtered(signal=signal)
            return {t.tweet_id for t in rows}

        assert await ids("ot") == {"2001"}
        assert await ids("zero_day") == {"2001"}
        assert await ids("databreach") == {"2001"}
        assert await ids("report") == {"4002"}

    async def test_filters_combine_with_and(self, async_db_session: AsyncSession) -> None:
        await _seed_signals(async_db_session)
        repo = AsyncTweetRepo(async_db_session)
        kw = {"search": "lockbit", "signal": "ot", "confirmed_only": True, "has_cve": True}
        rows, total = await repo.list_filtered(**kw)
        assert (total, [t.tweet_id for t in rows]) == (1, ["2001"])
        stats = await repo.get_stats(**kw)
        assert stats["total"] == total
        # satu syarat yang tidak cocok mempersempit jadi kosong, tidak pernah melebar
        for narrow in ({"signal": "report"}, {"search": "zeta"}):
            rows, total = await repo.list_filtered(**{**kw, **narrow})
            assert total == 0
            assert (await repo.get_stats(**{**kw, **narrow}))["total"] == 0


class TestAsyncMonitoredAccountRepo:
    async def test_create_normalizes_username(self, async_db_session: AsyncSession) -> None:
        repo = AsyncMonitoredAccountRepo(async_db_session)
        account = await repo.create("@ThreatFeed", "Threat Feed", "some notes")
        assert account.username == "threatfeed"
        assert account.display_name == "Threat Feed"
        assert account.active is True

    async def test_create_rejects_duplicate(self, async_db_session: AsyncSession) -> None:
        repo = AsyncMonitoredAccountRepo(async_db_session)
        await repo.create("threatfeed")
        with pytest.raises(ValueError, match="already monitored"):
            await repo.create("@ThreatFeed")

    async def test_list_all_sorted_by_username(self, async_db_session: AsyncSession) -> None:
        repo = AsyncMonitoredAccountRepo(async_db_session)
        await repo.create("zzz")
        await repo.create("aaa")
        accounts = await repo.list_all()
        assert [a.username for a in accounts] == ["aaa", "zzz"]

    async def test_toggle_active(self, async_db_session: AsyncSession) -> None:
        repo = AsyncMonitoredAccountRepo(async_db_session)
        await repo.create("threatfeed")
        assert await repo.toggle("threatfeed", False) is True
        account = await repo.get("threatfeed")
        assert account is not None
        assert account.active is False

    async def test_toggle_missing_returns_false(self, async_db_session: AsyncSession) -> None:
        repo = AsyncMonitoredAccountRepo(async_db_session)
        assert await repo.toggle("ghost", False) is False

    async def test_remove(self, async_db_session: AsyncSession) -> None:
        repo = AsyncMonitoredAccountRepo(async_db_session)
        await repo.create("threatfeed")
        assert await repo.remove("threatfeed") is True
        assert await repo.get("threatfeed") is None
        assert await repo.remove("threatfeed") is False
