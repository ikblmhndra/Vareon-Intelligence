"""Integration test `AsyncRecapRepo` -- Postgres REAL (testcontainers).
Fase 7.3 (router `recap`, Bagian 5).

Sekalian query CVE yang dipakai recap, `AsyncCveTrackerRepo.list_registered_on` (#21, 2026-10-11):
satu baris per `cve_id` dan urutan tetap. Tracker menyimpan satu baris per client, jadi tanpa itu
satu CVE muncul sekali per client dan 50 baris yang lolos `limit` sembarang."""

from __future__ import annotations

import datetime
from typing import Any

import pytest
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.ioc import IOC
from cti_core.db.models.recap import DailyRecap
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_core.db.models.tweet import Tweet
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo, AsyncCveTrackerRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.recap import AsyncRecapRepo
from cti_core.db.repositories.ta import AsyncTARepo
from cti_core.db.repositories.tweet import AsyncTweetRepo
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

DAY = datetime.date(2026, 3, 1)
"""Tanggal tetap, supaya hasil tidak bergantung pada jam dinding (`detected_on` default `now()`)."""


async def test_upsert_creates_then_updates(async_db_session: AsyncSession) -> None:
    repo = AsyncRecapRepo(async_db_session)
    row = await repo.upsert(
        "2026-09-18",
        headline="quiet day",
        yesterday={"summary": "nothing much"},
        forecast={},
        counts={"articles": 0},
        generated_at=datetime.datetime.now(datetime.UTC),
        model="test-model",
        token_usage={},
        raw_llm=None,
    )
    assert row.headline == "quiet day"

    updated = await repo.upsert("2026-09-18", headline="actually busy", counts={"articles": 5})
    assert updated.id == row.id
    assert updated.headline == "actually busy"
    assert updated.counts == {"articles": 5}


async def test_get_missing_returns_none(async_db_session: AsyncSession) -> None:
    assert await AsyncRecapRepo(async_db_session).get("2026-01-01") is None


async def test_list_recent_ordered_desc(async_db_session: AsyncSession) -> None:
    repo = AsyncRecapRepo(async_db_session)
    for d in ("2026-09-15", "2026-09-17", "2026-09-16"):
        await repo.upsert(
            d,
            headline=d,
            yesterday={},
            forecast={},
            counts={},
            generated_at=datetime.datetime.now(datetime.UTC),
            model="m",
            token_usage={},
            raw_llm=None,
        )
    rows = await repo.list_recent(limit=10)
    assert [r.date for r in rows] == ["2026-09-17", "2026-09-16", "2026-09-15"]


MONDAY = "2026-10-05"
"""Senin: tanggal yang dipakai baris mingguan (`date` = Senin) DAN sebuah baris harian."""
MONDAY_DATE = datetime.date.fromisoformat(MONDAY)


async def _both_kinds_on_monday(repo: AsyncRecapRepo) -> None:
    await repo.upsert(MONDAY, headline="the day", period_start=MONDAY_DATE, period_end=MONDAY_DATE)
    await repo.upsert(
        MONDAY,
        kind="weekly",
        headline="the week",
        period_start=MONDAY_DATE,
        period_end=MONDAY_DATE + datetime.timedelta(days=6),
    )


async def test_a_weekly_and_a_daily_row_can_share_a_date_and_each_is_read_by_kind(
    async_db_session: AsyncSession,
) -> None:
    """Dulu `get(date)` = `scalar_one_or_none()` tanpa `kind`: dua baris di Senin yang sama jadi
    `MultipleResultsFound` (HTTP 500). Sekarang unik di `(kind, date)` dan dibaca per kind."""
    repo = AsyncRecapRepo(async_db_session)
    await _both_kinds_on_monday(repo)

    daily = await repo.get(MONDAY)
    weekly = await repo.get(MONDAY, "weekly")

    assert daily is not None and weekly is not None
    assert (daily.kind, daily.headline) == ("daily", "the day")
    assert (weekly.kind, weekly.headline) == ("weekly", "the week")
    assert weekly.period_end == datetime.date(2026, 10, 11)
    assert daily.id != weekly.id


async def test_upsert_updates_only_the_row_of_its_own_kind(async_db_session: AsyncSession) -> None:
    repo = AsyncRecapRepo(async_db_session)
    await _both_kinds_on_monday(repo)

    await repo.upsert(MONDAY, kind="weekly", headline="the week, regenerated")

    assert (await repo.get(MONDAY, "weekly")).headline == "the week, regenerated"  # type: ignore[union-attr]
    assert (await repo.get(MONDAY)).headline == "the day"  # type: ignore[union-attr]


async def test_a_second_row_of_the_same_kind_and_date_is_rejected_by_the_database(
    async_db_session: AsyncSession,
) -> None:
    """Jaring terakhir di DB: `upsert` tidak pernah membuatnya, tapi jalur lain (SQL tangan,
    balapan dua worker) bisa."""
    await AsyncRecapRepo(async_db_session).upsert(MONDAY, kind="weekly")

    with pytest.raises(IntegrityError, match="uq_daily_recap_kind_date"):
        async with async_db_session.begin_nested():
            async_db_session.add(DailyRecap(date=MONDAY, kind="weekly"))
            await async_db_session.flush()


async def test_kind_defaults_to_daily_for_a_writer_that_does_not_know_about_it(
    async_db_session: AsyncSession,
) -> None:
    """Kode lama (rollback, deploy bergulir) INSERT tanpa `kind`/`period_*`: harus tetap jalan,
    dan barisnya jadi `daily` dengan periode NULL."""
    await async_db_session.execute(
        text(
            "INSERT INTO daily_recaps (date, headline, yesterday, forecast, counts, model, "
            "token_usage) VALUES ('2026-09-01', 'old writer', '{}', '{}', '{}', '', '{}')"
        )
    )

    row = await AsyncRecapRepo(async_db_session).get("2026-09-01")

    assert row is not None
    assert (row.kind, row.period_start, row.period_end) == ("daily", None, None)


async def test_list_recent_returns_both_kinds_with_the_weekly_one_first_on_a_shared_date(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRecapRepo(async_db_session)
    await repo.upsert("2026-09-28", kind="weekly")
    await _both_kinds_on_monday(repo)

    rows = await repo.list_recent(limit=10)

    assert [(r.date, r.kind) for r in rows] == [
        (MONDAY, "weekly"),
        (MONDAY, "daily"),
        ("2026-09-28", "weekly"),
    ]


async def test_get_latest_returns_the_newest_row_of_that_kind_only(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRecapRepo(async_db_session)
    await repo.upsert("2026-09-28", kind="weekly")
    await repo.upsert(MONDAY, kind="weekly")
    await repo.upsert("2026-10-09")  # harian lebih baru dari mingguan mana pun

    latest = await repo.get_latest("weekly")

    assert latest is not None and latest.date == MONDAY
    assert (await repo.get_latest("daily")).date == "2026-10-09"  # type: ignore[union-attr]


async def test_get_latest_is_none_when_the_kind_has_no_rows(async_db_session: AsyncSession) -> None:
    await AsyncRecapRepo(async_db_session).upsert("2026-10-09")

    assert await AsyncRecapRepo(async_db_session).get_latest("weekly") is None


async def test_quality_defaults_to_an_empty_object_and_is_replaced_whole_by_upsert(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRecapRepo(async_db_session)
    created = await repo.upsert(MONDAY, kind="weekly")
    await async_db_session.refresh(created)  # dibaca balik dari DB
    assert created.quality == {}

    await repo.upsert(MONDAY, kind="weekly", quality={"grounding": {"dropped": [], "count": 0}})
    regenerated = await repo.upsert(MONDAY, kind="weekly", quality={"comparison": {"x": 1}})

    assert regenerated.quality == {"comparison": {"x": 1}}  # force-regen: tidak digabung


async def test_get_by_id_reads_one_row_with_or_without_the_row_lock(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRecapRepo(async_db_session)
    row = await repo.upsert(MONDAY, kind="weekly", headline="the week")

    plain = await repo.get_by_id(row.id)
    locked = await repo.get_by_id(row.id, for_update=True)

    assert plain is not None and locked is not None
    assert (plain.headline, locked.id) == ("the week", row.id)
    assert await repo.get_by_id(row.id + 1000) is None


async def test_list_latest_is_newest_first_limited_and_of_one_kind(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRecapRepo(async_db_session)
    for monday in ("2026-09-14", "2026-09-21", "2026-09-28", MONDAY):
        await repo.upsert(monday, kind="weekly")
    await repo.upsert("2026-10-09")  # harian lebih baru: tidak ikut

    rows = await repo.list_latest("weekly", 3)

    assert [r.date for r in rows] == [MONDAY, "2026-09-28", "2026-09-21"]
    assert await repo.list_latest("weekly", 0) == []


async def _clients(session: AsyncSession, *extra: str) -> None:
    """`default` selalu ada; `extra` client tambahan (baris `cve_tracker` punya FK ke `clients`)."""
    repo = AsyncClientRepo(session)
    await repo.ensure_default()
    for client_id in extra:
        await repo.create(client_id=client_id, name=client_id.title(), countries=[])


def _row(cve_id: str, client_id: str = "default", **fields: Any) -> CveTracker:
    """Baris tracker yang jatuh di `DAY` lewat `published` (satu dari tiga kolom tanggal query)."""
    return CveTracker(cve_id=cve_id, client_id=client_id, published=DAY, **fields)


async def test_list_registered_on_returns_a_shared_cve_once(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session, "acme")
    async_db_session.add_all([_row("CVE-2026-0001", "default"), _row("CVE-2026-0001", "acme")])
    await async_db_session.flush()

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_on(DAY)

    assert [r.cve_id for r in rows] == ["CVE-2026-0001"]


async def test_list_registered_on_keeps_the_strongest_row_of_a_shared_cve(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session, "acme", "globex")
    # Yang kuat sengaja kadang masuk dulu, kadang belakangan: pemenang tidak boleh ditentukan
    # urutan sisip.
    async_db_session.add_all(
        [
            # KEV mengalahkan PoC, dan PoC mengalahkan CVSS tertinggi.
            _row("CVE-2026-0001", "default", cve_score=9.9),
            _row("CVE-2026-0001", "acme", poc_available=True, cve_score=5.0),
            _row("CVE-2026-0001", "globex", cisa_kev=True, cve_score=1.0),
            _row("CVE-2026-0002", "acme", poc_available=True),
            _row("CVE-2026-0002", "default", cve_score=9.9),
            # CVSS yang ada mengalahkan CVSS NULL.
            _row("CVE-2026-0003", "default"),
            _row("CVE-2026-0003", "acme", cve_score=3.0),
        ]
    )
    await async_db_session.flush()
    # Seri penuh: baris yang lebih dulu dibuat (id terkecil) yang dipilih, supaya hasilnya stabil.
    # Di-flush satu per satu karena yang diuji adalah `id`, bukan urutan batch INSERT.
    async_db_session.add(_row("CVE-2026-0004", "acme"))
    await async_db_session.flush()
    async_db_session.add(_row("CVE-2026-0004", "default"))
    await async_db_session.flush()

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_on(DAY)

    assert {r.cve_id: r.client_id for r in rows} == {
        "CVE-2026-0001": "globex",
        "CVE-2026-0002": "acme",
        "CVE-2026-0003": "acme",
        "CVE-2026-0004": "acme",
    }


async def test_list_registered_on_orders_kev_then_poc_then_cvss_nulls_last_then_cve_id(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session)
    # Urutan sisip = kebalikan urutan yang diharapkan, supaya urutan heap tak bisa kebetulan benar.
    async_db_session.add_all(
        [
            _row("CVE-2026-0016"),
            _row("CVE-2026-0015"),
            _row("CVE-2026-0014", cve_score=5.0),
            _row("CVE-2026-0013", cve_score=9.0),
            _row("CVE-2026-0009", cve_score=9.0),
            _row("CVE-2026-0012", poc_available=True, cve_score=7.0),
            _row("CVE-2026-0011", cisa_kev=True, cve_score=9.8),
            _row("CVE-2026-0010", cisa_kev=True, poc_available=True, cve_score=5.0),
        ]
    )
    await async_db_session.flush()

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_on(DAY)

    assert [r.cve_id for r in rows] == [
        "CVE-2026-0010",  # KEV + PoC
        "CVE-2026-0011",  # KEV tanpa PoC: CVSS 9.8 tidak melompati PoC di atasnya
        "CVE-2026-0012",  # PoC tanpa KEV
        "CVE-2026-0009",  # CVSS 9.0; seri dengan 0013, jadi cve_id yang lebih kecil dulu
        "CVE-2026-0013",
        "CVE-2026-0014",  # CVSS 5.0
        "CVE-2026-0015",  # tanpa CVSS (NULL) paling belakang, lalu cve_id
        "CVE-2026-0016",
    ]


async def test_list_registered_on_applies_the_limit_after_dedupe(
    async_db_session: AsyncSession,
) -> None:
    """Kalau `limit` dipotong sebelum dedupe, CVE terkuat yang di-track dua client memakai kedua
    slot dan CVE kedua tersingkir."""
    await _clients(async_db_session, "acme")
    async_db_session.add_all(
        [
            _row("CVE-2026-0001", "default", cisa_kev=True),
            _row("CVE-2026-0001", "acme", cisa_kev=True),
            _row("CVE-2026-0002", "default", cve_score=8.0),
            _row("CVE-2026-0003", "default", cve_score=4.0),
        ]
    )
    await async_db_session.flush()

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_on(DAY, limit=2)

    assert [r.cve_id for r in rows] == ["CVE-2026-0001", "CVE-2026-0002"]


async def test_list_registered_on_drops_false_positive_rows_before_picking_the_strongest(
    async_db_session: AsyncSession,
) -> None:
    """FP dibuang SEBELUM baris terkuat dipilih. Kalau tidak, baris FP yang kuat menang lalu
    tersaring, dan CVE-nya hilang padahal client lain masih menganggapnya valid."""
    await _clients(async_db_session, "acme")
    async_db_session.add_all(
        [
            _row("CVE-2026-0001", "default", cisa_kev=True),  # terkuat, tapi di-FP default
            _row("CVE-2026-0001", "acme", cve_score=4.0),
            _row("CVE-2026-0002", "default", cisa_kev=True),  # di-FP semua client yang men-track
            _row("CVE-2026-0002", "acme", cisa_kev=True),
        ]
    )
    await async_db_session.flush()
    fp = AsyncCveFalsePositiveRepo(async_db_session)
    await fp.mark("CVE-2026-0001", "default")
    await fp.mark("CVE-2026-0002", "default")
    await fp.mark("CVE-2026-0002", "acme")

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_on(DAY)

    assert [(r.cve_id, r.client_id) for r in rows] == [("CVE-2026-0001", "acme")]


async def test_list_registered_on_matches_any_of_the_three_date_columns(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session)
    at_day = datetime.datetime(2026, 3, 1, 12, 0, tzinfo=datetime.UTC)
    other = datetime.datetime(2026, 2, 1, 12, 0, tzinfo=datetime.UTC)
    async_db_session.add_all(
        [
            CveTracker(cve_id="CVE-2026-0001", client_id="default", registered_date=at_day),
            CveTracker(cve_id="CVE-2026-0002", client_id="default", detected_on=at_day),
            CveTracker(cve_id="CVE-2026-0003", client_id="default", published=DAY),
            CveTracker(
                cve_id="CVE-2026-0004",
                client_id="default",
                published=DAY - datetime.timedelta(days=1),
                registered_date=other,
                detected_on=other,
            ),
        ]
    )
    await async_db_session.flush()

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_on(DAY)

    assert sorted(r.cve_id for r in rows) == ["CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"]


# --- kolektor rentang tanggal (recap mingguan, #21 PR 2) -----------------------------------------

WEEK_START = datetime.date(2026, 3, 2)
WEEK_END = datetime.date(2026, 3, 8)
"""Senin-Minggu. `DAY` (1 Maret) jatuh sehari SEBELUM pekan ini, dan 9 Maret sehari sesudahnya:
dua sisi batas yang harus ditolak."""


def _on(day: datetime.date, hour: int = 12, minute: int = 0) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=datetime.UTC)


def _cve_on(day: datetime.date, cve_id: str, client_id: str = "default", **f: Any) -> CveTracker:
    return CveTracker(cve_id=cve_id, client_id=client_id, published=day, **f)


async def test_list_registered_between_covers_the_whole_range_inclusive_and_nothing_outside(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session)
    d = datetime.timedelta
    async_db_session.add_all(
        [
            _cve_on(WEEK_START - d(days=1), "CVE-2026-0001"),  # Minggu sebelumnya
            _cve_on(WEEK_START, "CVE-2026-0002"),  # hari pertama
            _cve_on(WEEK_START + d(days=3), "CVE-2026-0003"),
            _cve_on(WEEK_END, "CVE-2026-0004"),  # hari terakhir
            _cve_on(WEEK_END + d(days=1), "CVE-2026-0005"),  # Senin berikutnya
        ]
    )
    await async_db_session.flush()
    repo = AsyncCveTrackerRepo(async_db_session)

    rows = await repo.list_registered_between(WEEK_START, WEEK_END)

    assert sorted(r.cve_id for r in rows) == ["CVE-2026-0002", "CVE-2026-0003", "CVE-2026-0004"]
    assert await repo.count_registered_between(WEEK_START, WEEK_END) == 3


async def test_list_registered_between_dedupes_a_cve_seen_on_two_days_and_keeps_the_strongest(
    async_db_session: AsyncSession,
) -> None:
    """Aturan sama dengan satu hari: satu baris per `cve_id` (terkuat), urutan KEV -> PoC -> CVSS,
    FP dibuang SEBELUM baris terkuat dipilih."""
    await _clients(async_db_session, "acme")
    async_db_session.add_all(
        [
            _cve_on(WEEK_START, "CVE-2026-0001", "default", cve_score=5.0),
            _cve_on(
                WEEK_START + datetime.timedelta(days=4), "CVE-2026-0001", "acme", cisa_kev=True
            ),
            _cve_on(WEEK_START, "CVE-2026-0002", "default", cve_score=9.0),
            _cve_on(WEEK_START, "CVE-2026-0003", "default", cisa_kev=True),  # di-FP default
            _cve_on(WEEK_START, "CVE-2026-0003", "acme", cve_score=2.0),
        ]
    )
    await async_db_session.flush()
    await AsyncCveFalsePositiveRepo(async_db_session).mark("CVE-2026-0003", "default")

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_between(WEEK_START, WEEK_END)

    assert [(r.cve_id, r.client_id) for r in rows] == [
        ("CVE-2026-0001", "acme"),  # KEV menang atas CVSS 5.0 walau di hari dan client lain
        ("CVE-2026-0002", "default"),
        ("CVE-2026-0003", "acme"),  # baris FP-nya dibuang, bukan CVE-nya
    ]


async def test_count_registered_between_is_the_true_total_not_the_length_of_the_limited_list(
    async_db_session: AsyncSession,
) -> None:
    """`counts.cves` mingguan harus jumlah sebenarnya (satu pekan jauh melebihi yang muat di
    prompt), dengan aturan yang sama dengan daftarnya: satu per `cve_id`, FP dibuang."""
    await _clients(async_db_session, "acme")
    async_db_session.add_all(
        [_cve_on(WEEK_START, f"CVE-2026-{n:04d}", cve_score=float(n)) for n in range(1, 6)]
        + [
            _cve_on(WEEK_START, "CVE-2026-0001", "acme"),  # CVE yang sama, client lain: sekali
            _cve_on(WEEK_START, "CVE-2026-0099", "default"),  # satu-satunya baris, di-FP pemiliknya
        ]
    )
    await async_db_session.flush()
    await AsyncCveFalsePositiveRepo(async_db_session).mark("CVE-2026-0099", "default")
    repo = AsyncCveTrackerRepo(async_db_session)

    limited = await repo.list_registered_between(WEEK_START, WEEK_END, limit=2)

    assert [r.cve_id for r in limited] == ["CVE-2026-0005", "CVE-2026-0004"]
    assert await repo.count_registered_between(WEEK_START, WEEK_END) == 5


async def test_list_registered_between_matches_any_of_the_three_date_columns(
    async_db_session: AsyncSession,
) -> None:
    await _clients(async_db_session)
    async_db_session.add_all(
        [
            CveTracker(
                cve_id="CVE-2026-0001", client_id="default", registered_date=_on(WEEK_START)
            ),
            CveTracker(cve_id="CVE-2026-0002", client_id="default", detected_on=_on(WEEK_END)),
            _cve_on(WEEK_START + datetime.timedelta(days=2), "CVE-2026-0003"),
            CveTracker(  # tiga-tiganya di luar pekan
                cve_id="CVE-2026-0004",
                client_id="default",
                published=WEEK_START - datetime.timedelta(days=1),
                registered_date=_on(WEEK_END + datetime.timedelta(days=1)),
                detected_on=_on(WEEK_START - datetime.timedelta(days=30)),
            ),
        ]
    )
    await async_db_session.flush()

    rows = await AsyncCveTrackerRepo(async_db_session).list_registered_between(WEEK_START, WEEK_END)

    assert sorted(r.cve_id for r in rows) == ["CVE-2026-0001", "CVE-2026-0002", "CVE-2026-0003"]


async def test_count_first_seen_iocs_by_type_groups_in_sql_and_respects_the_range(
    async_db_session: AsyncSession,
) -> None:
    d = datetime.timedelta
    async_db_session.add_all(
        [
            IOC(type="ip", value="203.0.113.1", first_seen_at=_on(WEEK_START, 0, 0)),
            IOC(type="ip", value="203.0.113.2", first_seen_at=_on(WEEK_END, 23, 59)),
            IOC(type="domain", value="a.example", first_seen_at=_on(WEEK_START + d(days=2))),
            IOC(type="domain", value="late.example", first_seen_at=_on(WEEK_END + d(days=1), 0, 0)),
            IOC(type="sha256", value="a" * 64, first_seen_at=_on(WEEK_START - d(days=1), 23, 59)),
        ]
    )
    await async_db_session.flush()

    counts = await AsyncIOCRepo(async_db_session).count_first_seen_by_type_between(
        WEEK_START, WEEK_END
    )

    assert counts == {"ip": 2, "domain": 1}


async def test_list_added_threat_actors_between_returns_the_first_n_and_the_true_total(
    async_db_session: AsyncSession,
) -> None:
    d = datetime.timedelta
    async_db_session.add_all(
        [
            ThreatActorGroup(name="Early", created_at=_on(WEEK_START - d(days=1), 23, 59)),
            ThreatActorGroup(name="B", created_at=_on(WEEK_START + d(days=1))),
            ThreatActorGroup(name="A", created_at=_on(WEEK_START + d(days=1))),
            ThreatActorGroup(name="First", created_at=_on(WEEK_START, 0, 5)),
            ThreatActorGroup(name="Last", created_at=_on(WEEK_END, 23, 59)),
            ThreatActorGroup(name="Late", created_at=_on(WEEK_END + d(days=1), 0, 0)),
        ]
    )
    await async_db_session.flush()

    groups, total = await AsyncTARepo(async_db_session).list_added_between(
        WEEK_START, WEEK_END, limit=3
    )

    assert total == 4
    assert [g.name for g in groups] == ["First", "A", "B"]  # paling awal dulu, seri -> nama


def _tweet(n: int, posted: datetime.datetime, **fields: Any) -> Tweet:
    return Tweet(
        tweet_id=str(n),
        url=f"https://x.com/u/status/{n}",
        text=f"tweet {n}",
        author_username="u",
        posted_on=posted,
        **fields,
    )


async def test_list_top_tweets_between_ranks_in_sql_limits_and_excludes_the_upper_bound(
    async_db_session: AsyncSession,
) -> None:
    start, before = _on(WEEK_START, 0, 0), _on(WEEK_END + datetime.timedelta(days=1), 0, 0)
    async_db_session.add_all(
        [
            _tweet(1, _on(WEEK_START, 1), incident_confidence=90),
            _tweet(2, _on(WEEK_START, 2), incident_confidence=50),
            _tweet(3, _on(WEEK_START, 3), confirmed_incident=True, incident_confidence=10),
            _tweet(4, _on(WEEK_START, 4)),  # tanpa confidence: NULL paling belakang
            _tweet(5, before),  # tepat di batas atas: eksklusif
            _tweet(6, start - datetime.timedelta(seconds=1)),  # sebelum jendela
        ]
    )
    await async_db_session.flush()
    repo = AsyncTweetRepo(async_db_session)

    tweets, total = await repo.list_top_between(
        posted_on_start=start, posted_before=before, limit=3
    )

    assert total == 4
    # Insiden terkonfirmasi dulu walau confidence-nya paling kecil, lalu confidence menurun.
    assert [t.tweet_id for t in tweets] == ["3", "1", "2"]


async def test_list_top_articles_between_ranks_in_sql_limits_and_is_inclusive_of_both_ends(
    async_db_session: AsyncSession,
) -> None:
    d = datetime.timedelta
    repo = AsyncArticleRepo(async_db_session)
    # P6 5.2: urut `priority_score` (NULL terakhir); insiden terkonfirmasi tidak lagi didahulukan
    # sendiri (sudah +25 di dalam priority), dan `confidence_score` tidak dipakai lagi.
    rows = [
        ("a-out-before", WEEK_START - d(days=1), 140, True),
        ("b-first-day", WEEK_START, 40, False),
        ("c-confirmed", WEEK_START + d(days=2), 20, True),
        ("d-high", WEEK_START + d(days=3), 90, False),
        ("e-last-day", WEEK_END, 70, False),
        ("f-no-score", WEEK_END, None, False),
        ("g-out-after", WEEK_END + d(days=1), 140, True),
    ]
    for slug, posted, priority, confirmed in rows:
        await repo.upsert(
            url=f"https://x.com/{slug}",
            title=slug,
            source="CISA",
            posted_on=posted,
            priority_score=priority,
            confidence_score=100 - (priority or 0) // 2,
            confirmed_incident=confirmed,
        )

    articles, total = await repo.list_top_between(WEEK_START, WEEK_END, limit=4)

    assert total == 5
    assert [a.title for a in articles] == ["d-high", "e-last-day", "b-first-day", "c-confirmed"]
