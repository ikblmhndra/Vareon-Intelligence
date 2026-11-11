"""Task `exec.brief_daily` (`cti_worker.tasks.periodic`): jaminan tidak ada panggilan LLM ganda.
Task dipanggil lewat `.run()` (membuka loop dan engine sendiri lewat `asyncio.run`), jadi test ini
sinkron dan data dikomit beneran lalu dibersihkan. Postgres dan Redis nyata; LLM di-stub dengan
penghitung panggilan."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
import redis
import structlog.testing
from cti_api.services import exec_brief as eb
from cti_core.config import get_settings
from cti_core.db.engine import get_sync_engine
from cti_core.db.models.exec_brief import ExecBrief
from sqlalchemy import delete, select
from sqlalchemy.orm import Session


@pytest.fixture(autouse=True)
def _env(
    _migrated_schema: None, redis_client: redis.Redis, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    kw = redis_client.connection_pool.connection_kwargs
    monkeypatch.setenv("REDIS__URL", f"redis://{quote(str(kw['host']))}:{kw['port']}/0")
    get_settings.cache_clear()
    redis_client.flushall()
    _wipe()
    yield
    _wipe()
    get_settings.cache_clear()


def _wipe() -> None:
    with Session(get_sync_engine()) as s:
        s.execute(delete(ExecBrief))
        s.commit()


def _rows() -> list[ExecBrief]:
    with Session(get_sync_engine()) as s:
        return list(s.scalars(select(ExecBrief)))


def _insert_manual() -> None:
    with Session(get_sync_engine()) as s:
        s.add(
            ExecBrief(
                brief_date=eb.brief_today(),
                markdown="MANUAL",
                filters={"days": 7, "incident_only": False, "confirmed_only": False},
                generated_by="manual",
                model="m",
                prompt_version="pv",
            )
        )
        s.commit()


class Llm:
    def __init__(self, fail: Exception | None = None, answer: str = "# Brief") -> None:
        self.calls = 0
        self.fail = fail
        self.answer = answer

    def __call__(self, _msg: str) -> tuple[str, str]:
        self.calls += 1
        if self.fail:
            raise self.fail
        return self.answer, "stub-model"


def _task() -> dict[str, object]:
    import cti_worker.celery_app  # noqa: F401  -- registrasi task dulu (impor melingkar)
    from cti_worker.tasks.periodic import exec_brief_daily

    return exec_brief_daily.run()


def test_missing_stores_scheduler_row_with_default_filters(monkeypatch) -> None:
    llm = Llm()
    monkeypatch.setattr(eb, "_call_llm", llm)

    assert _task() == {"status": "stored"}

    (row,) = _rows()
    assert (row.generated_by, row.markdown, row.brief_date) == (
        "scheduler",
        "# Brief",
        eb.brief_today(),
    )
    assert row.filters == eb.DEFAULT_FILTERS.as_json()
    assert llm.calls == 1


def test_present_row_makes_no_llm_call(monkeypatch, redis_client: redis.Redis) -> None:
    llm = Llm()
    monkeypatch.setattr(eb, "_call_llm", llm)
    for _ in range(2):  # baris scheduler, lalu baris manual
        _wipe()
        if _ == 0:
            assert _task() == {"status": "stored"}
            llm.calls = 0
        else:
            _insert_manual()
        # Lock dipegang pihak lain: kalau task menyentuh lock, hasilnya `skipped_running`.
        redis_client.set(f"exec_brief:{eb.brief_today().isoformat()}", "other")
        assert _task() == {"status": "present"}
        assert llm.calls == 0
        redis_client.flushall()


def test_lock_held_skips(monkeypatch, redis_client: redis.Redis) -> None:
    llm = Llm()
    monkeypatch.setattr(eb, "_call_llm", llm)
    redis_client.set(f"exec_brief:{eb.brief_today().isoformat()}", "other")

    assert _task() == {"status": "skipped_running"}

    assert llm.calls == 0 and _rows() == []


def test_failure_writes_no_row_and_next_run_retries(monkeypatch, redis_client: redis.Redis) -> None:
    llm = Llm(fail=TimeoutError())
    monkeypatch.setattr(eb, "_call_llm", llm)

    with structlog.testing.capture_logs() as logs:
        assert _task() == {"status": "failed"}

    assert _rows() == [] and llm.calls == 1
    failed = [e for e in logs if e["event"] == "exec_brief_daily_failed"]
    assert failed and failed[0]["error_type"] == "TimeoutError"
    assert redis_client.keys("exec_brief:*") == []  # lock dilepas di finally

    llm.fail = None  # tick berikutnya
    assert _task() == {"status": "stored"}
    assert len(_rows()) == 1 and llm.calls == 2


def test_empty_answer_is_failure(monkeypatch) -> None:
    monkeypatch.setattr(eb, "_call_llm", Llm(answer="  \n"))

    assert _task() == {"status": "failed"}

    assert _rows() == []


def test_manual_row_between_recheck_and_insert_survives(monkeypatch) -> None:
    llm = Llm()
    monkeypatch.setattr(eb, "_call_llm", llm)
    real_draft = eb.draft_brief

    async def draft_then_manual_lands(*a: Any, **k: Any) -> Any:
        draft = await real_draft(*a, **k)
        _insert_manual()  # POST manual masuk sesudah baca-ulang, sebelum insert scheduler
        return draft

    monkeypatch.setattr(eb, "draft_brief", draft_then_manual_lands)

    assert _task() == {"status": "raced"}

    (row,) = _rows()
    assert (row.generated_by, row.markdown) == ("manual", "MANUAL")
    assert llm.calls == 1


def test_purge_keeps_30_days() -> None:
    import datetime

    import cti_worker.celery_app  # noqa: F401  -- registrasi task dulu (impor melingkar)
    from cti_worker.tasks.periodic import exec_purge_briefs

    today = eb.brief_today()
    with Session(get_sync_engine()) as s:
        for back in (31, 30, 0):
            s.add(
                ExecBrief(
                    brief_date=today - datetime.timedelta(days=back),
                    markdown=f"d{back}",
                    filters=eb.DEFAULT_FILTERS.as_json(),
                    generated_by="scheduler",
                    model="m",
                    prompt_version="pv",
                )
            )
        s.commit()

    assert exec_purge_briefs.run() == {"removed": 1}

    assert sorted(r.markdown for r in _rows()) == ["d0", "d30"]
