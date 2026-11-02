"""Dispatcher `enrich.llm_dispatch` (P7g Task 5, spec 4.5) dan kiriman langsung job baru dari
pipeline, terhadap Postgres REAL.

Semua `sync_session()` (dispatcher, `run_job`, pencatat `llm_calls`) diarahkan ke satu sesi test
yang di-rollback di akhir (commit = lepas SAVEPOINT). Broker Celery, kedalaman antrian `enrich`,
dan alert diganti pencatat. Breaker membaca `llm_calls`, jadi "LLM" palsu di simulasi gangguan
menulis barisnya lewat jalur pencatatan asli (`record_call`) dan mencapnya dengan jam simulasi.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import openai
import pytest
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.llm_call import LlmCall
from cti_core.db.repositories.enrich_job import EnrichJobRepo
from cti_core.db.repositories.llm_call import LlmCallRepo
from cti_core.llm.breaker import BREAKER_TASKS, LEASE, OPEN_AFTER, RECENT_CALLS, breaker_state
from cti_enrich import jobs, pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_ttps import TtpResult
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from tests.integration.enrich_job_support import share_session

PREFIX = "https://example.com/llm-dispatch/"
BODY = "The hospital confirmed a ransomware attack this week. Systems were encrypted. " * 3
VERDICT = ClassifyResult(
    related_cyber=True, confidence=0.9, reason="ransomware", industries_impacted=["Healthcare"]
)
_REQ = httpx.Request("POST", "http://gw/v1/chat/completions")


@pytest.fixture
def session(_migrated_schema: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    import cti_core.db.engine as engine

    # Impor worker (dan semua modul task-nya) SEBELUM `sync_session` diganti: modul yang
    # mengimpor `sync_session` di level modul akan menyimpan versi palsu yang terikat ke koneksi
    # test ini, lalu gagal di test lain sesudah koneksinya ditutup.
    import cti_worker.celery_app  # noqa: F401

    connection = engine.get_sync_engine().connect()
    connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    share_session(monkeypatch, s)

    @contextmanager
    def _shared() -> Iterator[Session]:
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise

    # Dispatcher dan `record_call` mengimpor `sync_session` saat dipanggil.
    monkeypatch.setattr(engine, "sync_session", _shared)
    # Tabel bersama antar test: mulai dari kosong di dalam transaksi ini (di-rollback di akhir).
    s.execute(delete(LlmCall))
    s.execute(delete(EnrichJob))
    s.commit()
    try:
        yield s
    finally:
        s.close()
        connection.rollback()
        connection.close()


@pytest.fixture
def mod(session: Session) -> Any:
    from cti_worker.tasks import llm_dispatch

    return llm_dispatch


class Wire:
    def __init__(self) -> None:
        self.sent: list[int] = []
        self.down_alerts: list[int] = []
        self.depth: int | None = 0
        self.fail_send = False

    def send(self, job_id: int, decision: str | None = None) -> None:
        if self.fail_send:
            raise ConnectionError("broker mati")
        self.sent.append(job_id)


@pytest.fixture
def wire(mod: Any, monkeypatch: pytest.MonkeyPatch, redis_client: Any) -> Wire:
    import redis

    # Penanda canary disimpan di Redis efemeral beneran.
    redis_client.flushall()
    monkeypatch.setattr(redis.Redis, "from_url", lambda *_a, **_k: redis_client)
    w = Wire()
    monkeypatch.setattr("cti_core.celery_client.send_enrich_llm", w.send)
    monkeypatch.setattr(pipeline, "send_enrich_llm", w.send)
    monkeypatch.setattr("cti_scraper.sinks.enrich_queue_depth", lambda: w.depth)
    monkeypatch.setattr(mod, "alert_llm_down", lambda waiting: w.down_alerts.append(waiting))
    return w


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage berat/jaringan diganti; `persist`/Tier 1/`apply_ttps` asli."""
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: None)
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: BODY)
    monkeypatch.setattr(pipeline, "resolve_story", lambda **kw: None)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    monkeypatch.setattr(jobs, "extract_ttps", lambda text: TtpResult(has_techniques=False))


def _jobs(session: Session, n: int, *, kind: str = "classify") -> list[int]:
    repo = EnrichJobRepo(session)
    ids = []
    for i in range(n):
        job = repo.create(
            kind=kind,
            url=f"{PREFIX}{kind}-{i}",
            title=f"Judul {i}",
            source="Test",
            scraper_id="t",
            posted_on=None,
            input_text=BODY,
            context={},
        )
        assert job is not None
        ids.append(job.id)
    session.commit()
    return ids


def _calls(session: Session, statuses: list[str], at: datetime.datetime) -> None:
    """Baris `llm_calls` terbaru dulu = elemen pertama `statuses`."""
    for i, status in enumerate(reversed(statuses)):
        session.add(
            LlmCall(
                at=at - datetime.timedelta(seconds=len(statuses) - i),
                task="classify",
                model="stub",
                status=status,
                latency_ms=1,
            )
        )
    session.commit()


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)


# ── dispatch ───────────────────────────────────────────────────────────────────────────


def test_closed_sends_at_most_a_batch_classify_first(
    session: Session, mod: Any, wire: Wire
) -> None:
    ttp = _jobs(session, 3, kind="ttp")
    classify = _jobs(session, 25)

    result = mod.dispatch(_now())

    assert result == {"sent": 20, "failed": 0, "limit": 20}
    assert wire.sent == classify[:20]  # classify dulu, tertua dulu; ttp menunggu
    assert not set(ttp) & set(wire.sent)
    assert wire.down_alerts == []


def test_closed_respects_the_room_left_in_the_enrich_queue(
    session: Session, mod: Any, wire: Wire
) -> None:
    from cti_core.config import get_settings

    _jobs(session, 10)
    wire.depth = get_settings().scraper.enrich_queue_max_depth - 4

    assert mod.dispatch(_now()) == {"sent": 4, "failed": 0, "limit": 4}


def test_half_open_sends_exactly_one_canary(session: Session, mod: Any, wire: Wire) -> None:
    now = _now()
    _jobs(session, 5)
    _calls(session, ["error"] * 3, now - datetime.timedelta(minutes=3))  # cooldown 2 mnt lewat

    assert mod.dispatch(now) == {"sent": 1, "failed": 0, "limit": 1}
    assert wire.down_alerts == []


def test_half_open_sends_no_second_canary_while_the_first_is_in_flight(
    session: Session, mod: Any, wire: Wire
) -> None:
    """Canary lambat (> 1 menit): selama belum ada baris `llm_calls` baru, putaran berikutnya
    tidak mengirim canary kedua (spec 4.4: tepat satu)."""
    now = _now()
    _jobs(session, 5)
    _calls(session, ["error"] * 3, now - datetime.timedelta(minutes=3))

    assert mod.dispatch(now)["sent"] == 1
    assert mod.dispatch(now + datetime.timedelta(minutes=1))["sent"] == 0
    assert mod.dispatch(now + datetime.timedelta(minutes=2))["sent"] == 0
    assert len(wire.sent) == 1

    # Canary-nya gagal (baris baru), cooldown n=4 (4 mnt) lewat: canary berikutnya boleh.
    later = now + datetime.timedelta(minutes=3)
    _calls(session, ["error"], later)
    assert mod.dispatch(later + datetime.timedelta(minutes=5))["sent"] == 1
    assert len(wire.sent) == 2


def test_open_sends_nothing_and_alerts_with_the_waiting_count(
    session: Session, mod: Any, wire: Wire
) -> None:
    now = _now()
    _jobs(session, 4)
    _jobs(session, 2, kind="ttp")
    _calls(session, ["error", "empty", "error"], now)

    assert mod.dispatch(now) == {"sent": 0, "failed": 0, "limit": 0}
    assert wire.sent == []
    assert wire.down_alerts == [6]


def test_open_with_nothing_waiting_does_not_alert(session: Session, mod: Any, wire: Wire) -> None:
    """Tanpa job tidak ada canary yang bisa menutup breaker; alert-nya akan berulang selamanya."""
    now = _now()
    _calls(session, ["error"] * 3, now)

    assert mod.dispatch(now)["sent"] == 0
    assert wire.down_alerts == []


def test_claim_is_committed_before_send(session: Session, mod: Any, wire: Wire) -> None:
    """Kirim gagal sesudah commit: job tetap tersewa (lease 15 mnt) dan tidak dikirim ulang di
    menit yang sama; sesudah lease habis dikirim lagi."""
    now = _now()
    ids = _jobs(session, 3)
    wire.fail_send = True

    assert mod.dispatch(now) == {"sent": 0, "failed": 3, "limit": 20}

    leased = session.scalars(select(EnrichJob.next_attempt_at).where(EnrichJob.id.in_(ids)))
    assert set(leased) == {now + datetime.timedelta(minutes=15)}
    wire.fail_send = False
    assert mod.dispatch(now + datetime.timedelta(seconds=30))["sent"] == 0
    assert mod.dispatch(now + datetime.timedelta(minutes=15))["sent"] == 3


def test_task_wraps_dispatch_with_the_current_time(mod: Any, wire: Wire) -> None:
    task = mod.llm_dispatch
    assert task.name == "enrich.llm_dispatch" and task.queue == "maintenance"
    assert task.run() == {"sent": 0, "failed": 0, "limit": 20}


# ── kiriman langsung dari pipeline ─────────────────────────────────────────────────────


def _arrive(session: Session, i: int) -> pipeline.PipelineOutcome:
    outcome = pipeline.run_pipeline(
        title=f"Ransomware gang hits hospital number {i}",
        url=f"{PREFIX}article-{i}",
        posted_on=None,
        source="Test",
        scraper_id="t",
        session=session,
    )
    session.commit()
    return outcome


def test_new_classify_job_is_sent_at_once_only_when_closed(
    session: Session, wire: Wire, stages: None
) -> None:
    first = _arrive(session, 1)
    assert first.pending_job_id is not None and wire.sent == [first.pending_job_id]

    _calls(session, ["error"] * OPEN_AFTER, _now())
    second = _arrive(session, 2)
    assert second.pending_job_id is not None
    assert wire.sent == [first.pending_job_id]  # breaker terbuka: dispatcher yang mengirim


def test_new_ttp_job_is_sent_at_once_when_closed(
    session: Session, wire: Wire, stages: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "classify", lambda title: VERDICT)
    outcome = _arrive(session, 1)
    assert outcome.pending_job_id is not None

    assert jobs.run_job(wire.sent.pop()) == "done"

    ttp = session.scalar(select(EnrichJob).where(EnrichJob.kind == "ttp"))
    assert ttp is not None and wire.sent == [ttp.id]


def test_an_immediately_sent_job_is_leased_against_the_dispatcher(
    session: Session, mod: Any, wire: Wire, stages: None
) -> None:
    """Kiriman langsung ikut menyewa job (`LEASE`) di transaksi yang membuatnya: putaran dispatcher
    berikutnya tidak mengirimnya lagi selagi worker mungkin masih memprosesnya; kalau job itu tidak
    pernah jalan, dispatcher mengirimnya sesudah sewa habis."""
    now = _now()
    outcome = _arrive(session, 1)
    job_id = outcome.pending_job_id
    assert job_id is not None and wire.sent == [job_id]

    assert mod.dispatch(now + datetime.timedelta(minutes=1))["sent"] == 0
    assert mod.dispatch(now + LEASE + datetime.timedelta(minutes=1))["sent"] == 1
    assert wire.sent == [job_id, job_id]


def test_an_immediately_sent_ttp_job_is_leased(
    session: Session, mod: Any, wire: Wire, stages: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "classify", lambda title: VERDICT)
    now = _now()
    _arrive(session, 1)
    assert jobs.run_job(wire.sent.pop()) == "done"
    ttp = session.scalar(select(EnrichJob).where(EnrichJob.kind == "ttp"))
    assert ttp is not None and wire.sent == [ttp.id]

    assert mod.dispatch(now + datetime.timedelta(minutes=1))["sent"] == 0


def test_a_closed_breaker_read_leaves_unsent_jobs_due_when_open(
    session: Session, mod: Any, wire: Wire, stages: None
) -> None:
    """Breaker terbuka: job baru TIDAK disewa, jadi dispatcher (canary) bisa mengambilnya."""
    now = _now()
    _calls(session, ["error"] * OPEN_AFTER, now - datetime.timedelta(minutes=3))
    outcome = _arrive(session, 1)
    assert wire.sent == []
    job = session.get(EnrichJob, outcome.pending_job_id)
    assert job is not None and job.next_attempt_at <= now


def test_a_failing_send_never_breaks_the_pipeline(
    session: Session, mod: Any, wire: Wire, stages: None
) -> None:
    wire.fail_send = True

    outcome = _arrive(session, 1)

    assert outcome.pending_job_id is not None
    assert session.get(EnrichJob, outcome.pending_job_id) is not None  # dispatcher yang kirim
    wire.fail_send = False
    assert mod.dispatch(_now() + LEASE)["sent"] == 1  # sesudah sewanya habis


# ── simulasi gangguan gateway ────────────────────────────────────────────────────────


def test_outage_then_recovery_drains_without_manual_action(
    session: Session,
    mod: Any,
    wire: Wire,
    stages: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """30 artikel datang selagi gateway membalas 503. Panggilan LLM yang gagal hanya: tiga kiriman
    langsung sebelum breaker terbuka (`OPEN_AFTER`), lalu paling banyak satu per putaran dispatcher
    yang setengah terbuka (canary). Sesudah gateway pulih, putaran dispatcher biasa menguras semua
    job sampai habis tanpa tindakan manual."""
    from cti_core.llm.usage import record_call

    clock = [datetime.datetime.now(datetime.UTC)]
    down = [True]
    calls = [0]

    def fake_classify(title: str) -> ClassifyResult:
        calls[0] += 1
        status = "error" if down[0] else "ok"
        record_call(
            task="classify",
            model="stub",
            prompt_version=None,
            status=status,
            error_type="InternalServerError" if down[0] else None,
            http_status=503 if down[0] else 200,
            prompt_tokens=None,
            completion_tokens=None,
            latency_ms=1,
        )
        # `at` bawaan = now() transaksi test; cap dengan jam simulasi.
        newest = select(func.max(LlmCall.id)).scalar_subquery()
        session.execute(update(LlmCall).where(LlmCall.id == newest).values(at=clock[0]))
        session.commit()
        if down[0]:
            raise openai.InternalServerError(
                "503", response=httpx.Response(503, request=_REQ), body=None
            )
        return VERDICT

    monkeypatch.setattr(jobs, "classify", fake_classify)

    def drain() -> None:
        while wire.sent:
            jobs.run_job(wire.sent.pop(0), now=clock[0])

    def breaker() -> str:
        recent = LlmCallRepo(session).recent_for_tasks(BREAKER_TASKS, limit=RECENT_CALLS)
        return breaker_state(recent, clock[0]).state

    def rounds(n: int, until: Callable[[], bool] = lambda: False) -> int:
        half_open = 0
        for _ in range(n):
            clock[0] += datetime.timedelta(minutes=1)
            half_open += breaker() == "half_open"
            mod.dispatch(clock[0])
            drain()
            if until():
                break
        return half_open

    # 1) Kedatangan: artikel tersimpan sebagai job, tidak ada yang hilang.
    for i in range(30):
        _arrive(session, i)
        drain()
    counts = EnrichJobRepo(session).counts()
    assert (counts.pending_classify, counts.failed) == (30, 0)
    assert calls[0] == OPEN_AFTER  # kiriman langsung berhenti begitu breaker terbuka

    # 2) Gangguan berlanjut satu jam: hanya canary.
    before = calls[0]
    half_open = rounds(60)
    assert 0 < calls[0] - before <= half_open
    assert wire.down_alerts and set(wire.down_alerts) == {30}
    assert EnrichJobRepo(session).counts().pending_classify == 30

    # 3) Gateway pulih: putaran dispatcher menguras semuanya sendiri.
    down[0] = False

    def drained() -> bool:
        c = EnrichJobRepo(session).counts()
        return c.pending_classify + c.pending_ttp + c.failed == 0

    rounds(240, until=drained)

    assert drained()
    assert session.scalar(select(func.count()).select_from(EnrichJob)) == 0
    stored = session.scalar(
        select(func.count()).select_from(Article).where(Article.url.like(f"{PREFIX}%"))
    )
    rejected = session.scalar(
        select(func.count())
        .select_from(RejectedArticle)
        .where(RejectedArticle.url.like(f"{PREFIX}%"))
    )
    assert stored + rejected == 30
