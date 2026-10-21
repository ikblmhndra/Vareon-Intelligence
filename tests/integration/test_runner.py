"""`cti_scraper.runner.Runner` -- cold-start guard + backpressure enrich
(Fase 10.A) dan jalur dedup two-phase yang dilewatinnya.

Sebelum file ini, Runner/`DedupStore`/`ScraperSeenRepo` GAK punya test
otomatis sama sekali (cuma diverifikasi live pas Fase 3/9). Guard-guard
Fase 10 nyentuh jalur itu langsung, jadi test-nya sekalian nutup lubang
tersebut: dedup dasar (duplikat dibuang, item gagal di-release), bukan cuma
guard-nya.

Scraper palsu di sini `__abstract__ = True` -- bukan buat "bohong", tapi biar
`__init_subclass__` gak nyelipin mereka ke registry global (contract test
iterasi SEMUA scraper terdaftar). `Runner` nerima kelas langsung, gak butuh
registry. `dispatch` di-patch (sink asli ngirim ke Celery/Redis).
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterator

import pytest
from cti_core.db.models.scraper import ScraperItem, ScraperRun, ScraperSeen
from cti_core.db.repositories.scraper import ScraperItemRepo
from cti_core.db.repositories.scraper_seen import ScraperSeenRepo
from cti_core.urlkit import canonicalize_url
from cti_scraper.base import BaseScraper, ScrapeContext, ScraperMeta
from cti_scraper.dedup import compute_dedup_key
from cti_scraper.items import ArticleItem, Item, RansomwareVictimItem
from cti_scraper.runner import Runner
from sqlalchemy import func, select
from sqlalchemy.orm import Session

SCRAPER_ID = "test-cold-start"


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
    """Sesi sync per-test yang BOLEH commit/rollback di dalamnya (Runner
    dua-duanya) tanpa nyentuh isolasi antar test: `create_savepoint` bikin
    commit()/rollback() cuma nutup SAVEPOINT, transaksi luar di-rollback di
    akhir. (Fixture `db_session` bawaan gak cocok -- mode defaultnya bikin
    `rollback()` dari Runner ngebunuh transaksi luarnya.)"""
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


@pytest.fixture
def dispatched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """URL yang beneran sampai ke sink, urut dispatch."""
    seen: list[str] = []

    def fake_dispatch(item: Item, meta: ScraperMeta, session: Session) -> None:
        seen.append(getattr(item, "url", None) or getattr(item, "victim", "?"))

    monkeypatch.setattr("cti_scraper.runner.dispatch", fake_dispatch)
    return seen


def make_scraper(items: Callable[[], list[Item]], *, max_items: int = 50) -> type[BaseScraper]:
    class _Scraper(BaseScraper):
        __abstract__ = True
        meta = ScraperMeta(id=SCRAPER_ID, source="Test", schedule="0 * * * *", max_items=max_items)

        def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
            yield from items()

    return _Scraper


def article(n: int, day: int | None = None) -> ArticleItem:
    return ArticleItem(
        title=f"Artikel {n}",
        url=f"https://example.com/post/{n}",
        posted_on=datetime.date(2026, 9, day) if day else None,
    )


def seen_states(session: Session) -> dict[str, str]:
    session.expire_all()
    rows = session.execute(
        select(ScraperSeen.dedup_key, ScraperSeen.state).where(ScraperSeen.scraper_id == SCRAPER_ID)
    ).all()
    return {k: s for k, s in rows}


def item_log(session: Session) -> dict[str, tuple[bool, str | None]]:
    rows = session.execute(
        select(ScraperItem.url, ScraperItem.accepted, ScraperItem.reason).where(
            ScraperItem.scraper_id == SCRAPER_ID
        )
    ).all()
    return {u: (a, r) for u, a, r in rows}


def key_of(n: int) -> str:
    return compute_dedup_key(SCRAPER_ID, canonicalize_url(f"https://example.com/post/{n}"))


# --- cold start: cap -------------------------------------------------------


def test_cold_scraper_enriches_only_newest_n_and_marks_rest_seen(
    session: Session, dispatched: list[str]
) -> None:
    feed = [article(n, day=n) for n in range(1, 9)]  # tanggal naik: 8 = terbaru
    runner = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=3)

    result = runner.execute()

    assert result.status == "ok"
    assert result.items_found == 8
    assert result.items_new == 3
    assert result.items_dropped == 5
    assert sorted(dispatched) == [f"https://example.com/post/{n}" for n in (6, 7, 8)]
    # SEMUA 8 ditandai done -- yang kena cap gak boleh muncul lagi di run kedua.
    states = seen_states(session)
    assert len(states) == 8
    assert set(states.values()) == {"done"}
    log = item_log(session)
    assert log["https://example.com/post/8"] == (True, None)
    assert log["https://example.com/post/1"] == (False, "cold_start_cap")


def test_cold_start_picks_newest_by_date_not_feed_order(
    session: Session, dispatched: list[str]
) -> None:
    # Feed "terlama dulu" -- kasus yang bakal salah kalau cuma ambil N pertama.
    feed = [article(n, day=n) for n in range(1, 9)]
    runner = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=2)

    runner.execute()

    assert sorted(dispatched) == ["https://example.com/post/7", "https://example.com/post/8"]


def test_cold_start_keeps_feed_order_when_articles_have_no_date(
    session: Session, dispatched: list[str]
) -> None:
    feed = [article(n) for n in range(1, 7)]
    runner = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=2)

    runner.execute()

    # Sort stabil: tanpa tanggal, N pertama di feed yang menang (feed umumnya terbaru-dulu).
    assert dispatched == ["https://example.com/post/1", "https://example.com/post/2"]


def test_default_cap_comes_from_settings(session: Session, dispatched: list[str]) -> None:
    feed = [article(n, day=n) for n in range(1, 9)]
    runner = Runner(make_scraper(lambda: feed), session=session)  # tanpa override

    result = runner.execute()

    assert result.items_new == 5  # Settings.scraper.cold_start_max_items default
    assert len(dispatched) == 5


def test_cap_is_bounded_by_meta_max_items(session: Session, dispatched: list[str]) -> None:
    feed = [article(n, day=n) for n in range(1, 7)]
    runner = Runner(
        make_scraper(lambda: feed, max_items=2), session=session, cold_start_max_items=5
    )

    runner.execute()

    assert len(dispatched) == 2


# --- cold vs warm ----------------------------------------------------------


def test_second_run_is_warm_and_not_capped(session: Session, dispatched: list[str]) -> None:
    first = [article(n, day=n) for n in range(1, 5)]
    fresh = [article(n, day=n) for n in range(5, 12)]  # 7 artikel BARU
    feed = list(first)
    scraper_cls = make_scraper(lambda: feed)

    Runner(scraper_cls, session=session, cold_start_max_items=2).execute()
    dispatched.clear()
    feed[:] = first + fresh
    result = Runner(scraper_cls, session=session, cold_start_max_items=2).execute()

    assert result.items_new == 7  # SEMUA yang baru, gak kena cap
    assert result.items_dropped == 4  # 4 lama = duplikat
    assert sorted(dispatched) == sorted(f"https://example.com/post/{n}" for n in range(5, 12))


def test_seeded_dedup_row_means_warm_no_cap(session: Session, dispatched: list[str]) -> None:
    """Warm start (seed `scraper_seen` dari dump lama): satu baris aja cukup
    bikin scraper dianggap warm, jadi item baru sejak dump gak kebuang."""
    ScraperSeenRepo(session).try_reserve(dedup_key=key_of(999), scraper_id=SCRAPER_ID, lease_s=900)
    ScraperSeenRepo(session).commit(key_of(999), ttl_days=180)
    feed = [article(n, day=n) for n in range(1, 9)]
    runner = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=3)

    result = runner.execute()

    assert result.items_new == 8
    assert len(dispatched) == 8


def test_reset_dedup_makes_scraper_cold_again(session: Session, dispatched: list[str]) -> None:
    feed = [article(n, day=n) for n in range(1, 7)]
    scraper_cls = make_scraper(lambda: feed)
    Runner(scraper_cls, session=session, cold_start_max_items=6).execute()
    assert ScraperSeenRepo(session).has_any(SCRAPER_ID)
    dispatched.clear()

    ScraperSeenRepo(session).reset_scraper(SCRAPER_ID)
    session.commit()
    assert not ScraperSeenRepo(session).has_any(SCRAPER_ID)
    result = Runner(scraper_cls, session=session, cold_start_max_items=2).execute()

    assert result.items_new == 2  # cap jalan lagi, bukan re-ingest seluruh feed
    assert len(dispatched) == 2


# --- yang GAK boleh kena cap ------------------------------------------------


def test_non_article_items_are_never_capped(session: Session, dispatched: list[str]) -> None:
    feed: list[Item] = [
        RansomwareVictimItem(group_name="g", victim=f"victim-{n}", post_url=f"u{n}")
        for n in range(6)
    ]
    runner = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=2)

    result = runner.execute()

    assert result.items_new == 6
    assert len(dispatched) == 6


def test_dry_run_is_never_capped_and_writes_nothing() -> None:
    feed = [article(n, day=n) for n in range(1, 7)]
    runner = Runner(make_scraper(lambda: feed), dry_run=True, cold_start_max_items=2)

    result = runner.execute()

    assert result.items_found == 6
    assert result.items_new == 0


def test_cap_zero_disables_the_guard(session: Session, dispatched: list[str]) -> None:
    feed = [article(n, day=n) for n in range(1, 7)]
    runner = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=0)

    result = runner.execute()

    assert result.items_new == 6


# --- dedup two-phase (belum pernah ke-test sebelumnya) ----------------------


def test_duplicate_within_a_run_is_dropped(session: Session, dispatched: list[str]) -> None:
    feed = [article(1, day=1), article(1, day=1), article(2, day=2)]
    runner = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=0)

    result = runner.execute()

    assert result.items_new == 2
    assert result.items_dropped == 1
    # URL yang sama dapat DUA baris log: yang pertama diterima, kedua duplikat.
    rows = session.execute(
        select(ScraperItem.accepted, ScraperItem.reason).where(
            ScraperItem.url == "https://example.com/post/1"
        )
    ).all()
    assert sorted(rows, key=lambda r: r.accepted) == [(False, "duplicate"), (True, None)]


def test_sink_failure_releases_the_lease_so_next_run_retries(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = [article(1, day=1), article(2, day=2)]
    scraper_cls = make_scraper(lambda: feed)
    calls: list[str] = []
    fail_on = {"https://example.com/post/1"}

    def flaky(item: Item, meta: ScraperMeta, session: Session) -> None:
        url = item.url  # type: ignore[attr-defined]
        if url in fail_on:
            raise RuntimeError("broker mati")
        calls.append(url)

    monkeypatch.setattr("cti_scraper.runner.dispatch", flaky)

    first = Runner(scraper_cls, session=session, cold_start_max_items=0).execute()

    assert first.items_failed == 1
    assert first.status == "partial"  # bukan "ok": ada item yang gagal (ROADMAP #24)
    assert first.items_new == 1
    assert key_of(1) not in seen_states(session)  # lease dilepas, BUKAN ditandai seen
    assert seen_states(session)[key_of(2)] == "done"

    fail_on.clear()
    second = Runner(scraper_cls, session=session, cold_start_max_items=0).execute()

    assert second.items_new == 1  # artikel 1 dicoba lagi
    assert calls == ["https://example.com/post/2", "https://example.com/post/1"]


def test_done_state_survives_a_failing_item_log(
    session: Session, dispatched: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresi: `dedup.commit()` cuma flush. Dulu state "done" numpang commit
    `_log_item()`; kalau log itu gagal -> rollback -> item balik in_flight ->
    di-dispatch ULANG begitu lease basi (= enrich + alert Telegram dobel)."""

    def boom(self: ScraperItemRepo, **kwargs: object) -> None:
        raise RuntimeError("tabel log lagi bermasalah")

    monkeypatch.setattr(ScraperItemRepo, "create", boom)
    feed = [article(1, day=1)]

    result = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=0).execute()

    assert result.items_new == 1
    assert seen_states(session) == {key_of(1): "done"}


def test_has_any_counts_rows_only_for_that_scraper(session: Session) -> None:
    repo = ScraperSeenRepo(session)
    repo.try_reserve(dedup_key=key_of(1), scraper_id=SCRAPER_ID, lease_s=900)

    assert repo.has_any(SCRAPER_ID)
    assert not repo.has_any("scraper-lain")
    assert session.scalar(select(func.count()).select_from(ScraperSeen)) == 1


# --- backpressure enrich (Fase 10.1e) ---------------------------------------


class _Depth:
    """Kedalaman antrian `enrich` yang bisa diatur test: nilai tetap, atau
    urutan nilai per panggilan (buat nyimulasiin antrian numpuk di tengah run)."""

    def __init__(self, *values: int) -> None:
        self._values = list(values)

    def __call__(self) -> int:
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]


@pytest.fixture
def enrich_sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Sink `ArticleItem` ASLI (bukan `dispatch` palsu) -- yang di-fake cuma
    ujungnya: producer Celery. Isinya URL yang beneran di-`send_task`."""
    sent: list[str] = []

    class _FakeCelery:
        def send_task(self, name: str, *, kwargs: dict[str, str], queue: str) -> None:
            assert (name, queue) == ("enrich.article", "enrich")
            sent.append(kwargs["url"])

    monkeypatch.setattr("cti_core.celery_client.get_celery_client", lambda: _FakeCelery())
    return sent


def _set_depth(monkeypatch: pytest.MonkeyPatch, depth: _Depth) -> None:
    monkeypatch.setattr("cti_scraper.sinks._enrich_queue_depth", depth)


def test_full_enrich_queue_stops_the_run_and_leaves_items_retryable(
    session: Session, enrich_sent: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = [article(n, day=n) for n in range(1, 4)]
    scraper_cls = make_scraper(lambda: feed)
    _set_depth(monkeypatch, _Depth(5000))  # >= batas default 2000

    result = Runner(scraper_cls, session=session, cold_start_max_items=0).execute()

    assert result.status == "backpressure"
    assert result.items_failed == 0  # bukan kegagalan item
    assert enrich_sent == []
    assert seen_states(session) == {}  # BELUM ditandai seen -> bisa dicoba lagi
    assert result.items_found == 1  # berhenti di item pertama, sisanya gak disentuh
    persisted = session.scalar(select(ScraperRun.status).where(ScraperRun.run_id == result.run_id))
    assert persisted == "backpressure"  # kelihatan di control plane
    assert list(item_log(session).values()) == [(False, "backpressure")]

    _set_depth(monkeypatch, _Depth(0))  # antrian surut
    retry = Runner(scraper_cls, session=session, cold_start_max_items=0).execute()

    assert retry.status == "ok"
    assert sorted(enrich_sent) == [f"https://example.com/post/{n}" for n in (1, 2, 3)]


def test_backpressure_midrun_keeps_what_was_already_sent(
    session: Session, enrich_sent: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = [article(n, day=n) for n in range(1, 6)]
    _set_depth(monkeypatch, _Depth(0, 0, 5000))  # penuh di item ke-3

    result = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=0).execute()

    assert result.status == "backpressure"
    assert result.items_new == 2
    assert enrich_sent == ["https://example.com/post/1", "https://example.com/post/2"]
    states = seen_states(session)
    assert set(states) == {key_of(1), key_of(2)}  # 3 (yang ditolak) + sisanya bebas
    assert set(states.values()) == {"done"}


def test_backpressure_guard_off_when_limit_is_zero(
    session: Session, enrich_sent: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "cti_scraper.sinks.get_settings",
        lambda: SimpleNamespace(scraper=SimpleNamespace(enrich_queue_max_depth=0)),
    )
    _set_depth(monkeypatch, _Depth(10**6))
    feed = [article(1, day=1)]

    result = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=0).execute()

    assert result.status == "ok"
    assert enrich_sent == ["https://example.com/post/1"]


# --- credential kosong (Fase 10.B: ketauan pas nyusun daftar key staging) ----


def test_missing_credential_is_a_clean_failed_run_not_a_stuck_one(
    session: Session, dispatched: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scraper `credential="nvd"` tapi `NVD__API_KEY` kosong. Dulu
    `resolve_credential_headers` dipanggil SEBELUM blok `try` di `_run_body`:
    ConfigError nembus `execute()`, run nyangkut `running` selamanya (gak ada
    `finish`), Celery task-nya crash tiap jadwal. Harus jadi run GAGAL yang
    jelas penyebabnya (kelihatan di control plane), bukan run hantu."""

    # `get_settings()` juga baca `.env` di cwd -- kosongin lewat env (menang atas
    # dotenv) biar test gak bergantung ke key yang kebetulan ada di `.env` dev.
    from cti_core.config import get_settings

    monkeypatch.setenv("NVD__API_KEY", "")
    get_settings.cache_clear()

    class _NeedsKey(BaseScraper):
        __abstract__ = True
        meta = ScraperMeta(id=SCRAPER_ID, source="Test", schedule="0 * * * *", credential="nvd")

        def fetch(self, ctx: ScrapeContext) -> Iterator[Item]:
            yield article(1, day=1)

    result = Runner(_NeedsKey, session=session, cold_start_max_items=0).execute()

    assert result.status == "fetch_error"
    assert result.errors[0]["stage"] == "config"
    assert result.errors[0]["type"] == "ConfigError"
    assert "nvd" in result.errors[0]["message"]
    assert dispatched == []  # gak ada request tanpa auth yang lolos
    persisted = session.scalar(select(ScraperRun.status).where(ScraperRun.run_id == result.run_id))
    assert persisted == "fetch_error"  # BUKAN "running"
    get_settings.cache_clear()


def test_a_setup_failure_closes_the_run_instead_of_leaving_it_running(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup `_run_body` (opsi, kredensial, referensi DB) ada di luar `try` fetch: dulu exception di
    sana meninggalkan run `running` selamanya dan mematikan task (dev: 8 run yatim)."""

    def broken(*_a: object, **_k: object) -> dict[str, str]:
        raise RuntimeError("opsi rusak")

    monkeypatch.setattr("cti_scraper.runner.resolve_options", broken)

    result = Runner(make_scraper(lambda: []), session=session, cold_start_max_items=0).execute()

    assert result.status == "fetch_error"
    assert result.errors[0]["stage"] == "setup" and "opsi rusak" in result.errors[0]["message"]
    run = session.scalar(select(ScraperRun).where(ScraperRun.run_id == result.run_id))
    assert run is not None and run.status == "fetch_error" and run.finished_at is not None


def test_run_is_finished_even_when_the_db_session_broke_midway(
    session: Session, dispatched: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regresi e2e staging Fase 10: koneksi DB putus di tengah run ->
    transaksi "inactive" -> `finish()` raise PendingRollbackError -> task
    crash, run nyangkut `running` SELAMANYA. Run harus tetap ditutup."""
    from cti_scraper import runner as runner_module
    from sqlalchemy import text

    def broken_reserve(self: object, *, scraper_id: str, raw_key: str) -> str | None:
        session.execute(text("select 1/0"))  # bikin transaksi sesi jadi tak-valid
        return None

    monkeypatch.setattr(runner_module.DedupStore, "reserve", broken_reserve)
    feed = [article(1, day=1)]

    result = Runner(make_scraper(lambda: feed), session=session, cold_start_max_items=0).execute()

    assert result.status == "fetch_error"
    persisted = session.scalar(select(ScraperRun.status).where(ScraperRun.run_id == result.run_id))
    assert persisted == "fetch_error"  # BUKAN "running"


# --- prime (cutover): tandai semuanya seen tanpa efek samping ---------------------------


def test_prime_marks_every_item_seen_and_dispatches_nothing(
    session: Session, dispatched: list[str]
) -> None:
    feed = [article(n, day=n) for n in range(1, 7)]
    scraper_cls = make_scraper(lambda: feed)

    primed = Runner(scraper_cls, session=session, prime=True).execute()

    assert dispatched == []  # NOL yang dikirim (cold-start cap biasa masih meloloskan N)
    assert primed.items_found == 6 and primed.items_new == 0 and primed.items_dropped == 6
    assert set(seen_states(session).values()) == {"done"} and len(seen_states(session)) == 6
    assert {reason for _, reason in item_log(session).values()} == {"primed"}


def test_after_priming_only_genuinely_new_items_get_through_and_uncapped(
    session: Session, dispatched: list[str]
) -> None:
    old = [article(n, day=n) for n in range(1, 5)]
    new = [article(n, day=n) for n in range(5, 9)]  # 4 item baru > cap dingin 2
    Runner(make_scraper(lambda: old), session=session, prime=True).execute()

    result = Runner(
        make_scraper(lambda: old + new), session=session, cold_start_max_items=2
    ).execute()

    assert sorted(dispatched) == sorted(f"https://example.com/post/{n}" for n in range(5, 9))
    assert result.items_new == 4  # scraper sudah hangat -> tanpa cap


def test_prime_also_silences_non_article_sinks(session: Session, dispatched: list[str]) -> None:
    """Item non-artikel biasanya lolos cap dingin (riwayat berguna); prime tidak."""
    victim = RansomwareVictimItem(
        group_name="g", victim="v", country_code="ID", industry="i", published="2026-09-01"
    )

    result = Runner(make_scraper(lambda: [victim]), session=session, prime=True).execute()

    assert dispatched == [] and result.items_new == 0 and len(seen_states(session)) == 1


def test_priming_twice_is_harmless_and_never_reaches_the_sink(
    session: Session, dispatched: list[str]
) -> None:
    scraper_cls = make_scraper(lambda: [article(1)])
    Runner(scraper_cls, session=session, prime=True).execute()
    again = Runner(scraper_cls, session=session, prime=True).execute()

    assert dispatched == [] and again.items_dropped == 1  # sudah seen -> duplikat biasa
