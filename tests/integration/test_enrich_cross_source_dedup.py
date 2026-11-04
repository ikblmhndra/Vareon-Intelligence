"""`run_pipeline` atas URL yang SUDAH jadi artikel -- tanpa LLM, tanpa alert.

Dedup scraper (`scraper_seen`) di-namespace per `scraper_id`, jadi URL yang sama
dari dua feed (atau dari feed yang sama sesudah TTL dedup habis) dua-duanya
lolos ke `enrich.article`. Dulu tiap kedatangan menjalankan SELURUH pipeline
(klasifikasi + TTP lewat LLM) dan mengirim alert Telegram LAGI; `ArticleRepo.
upsert` cuma menaikkan `seen_count` dan menimpa enrichment-nya. Sekarang
kedatangan kedua hanya menaikkan `seen_count`/`last_seen_at`.

Dua task untuk URL yang sama bisa jalan BERSAMAAN di `worker-nlp`
(concurrency > 1); pemeriksaan "sudah ada?" saja kalah balapan karena artikel
baru ditulis di akhir pipeline. Test terakhir mengunci penguncian per URL.

P7g: vonis LLM classify datang dari job `classify`; `_run` menyelesaikannya dengan vonis palsu
(`enrich_job_support`). URL yang job `classify`-nya masih menunggu juga duplikat.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.story import Story
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from tests.integration.enrich_job_support import job_for, run_with_verdict

URL = "https://example.com/ransomware-hits-hospital"


@pytest.fixture
def session(_migrated_schema: None) -> Iterator[Session]:
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
def alerts(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    sent: list[object] = []
    monkeypatch.setattr(pipeline, "route_alerts", lambda result: sent.append(result))
    return sent


RELEVANT = ClassifyResult(
    related_cyber=True, confidence=0.9, reason="ransomware", industries_impacted=["General"]
)


@pytest.fixture
def classify_calls() -> list[str]:
    """Judul yang sampai ke "LLM" (job `classify` yang diselesaikan `_run`)."""
    return []


@pytest.fixture(autouse=True)
def _stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage yang butuh LLM/jaringan diganti; `persist`/`routing` ASLI."""
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "Isi artikel lengkap. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan insiden ransomware.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())


def _run(
    session: Session,
    *,
    source: str,
    scraper_id: str,
    url: str = URL,
    calls: list[str] | None = None,
    verdict: ClassifyResult = RELEVANT,
) -> pipeline.PipelineOutcome:
    outcome = run_with_verdict(
        session,
        verdict,
        title="Ransomware hits hospital",
        url=url,
        posted_on=None,
        source=source,
        scraper_id=scraper_id,
    )
    if calls is not None and not outcome.duplicate:
        calls.append("Ransomware hits hospital")
    return outcome


def _article(session: Session) -> Article | None:
    return session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))


def test_second_source_for_the_same_url_skips_llm_and_alert(
    session: Session, alerts: list[object], classify_calls: list[str]
) -> None:
    first = _run(session, source="Vendor Blog", scraper_id="vendor", calls=classify_calls)
    second = _run(session, source="Aggregator", scraper_id="aggregator", calls=classify_calls)

    assert classify_calls == ["Ransomware hits hospital"]  # LLM sekali saja
    assert len(alerts) == 1  # alert sekali saja
    assert first.accepted and not first.duplicate
    assert second.accepted and second.duplicate
    assert second.article_id == first.article_id

    article = _article(session)
    assert article is not None
    assert article.seen_count == 2
    assert article.source == "Vendor Blog"  # sumber pertama dipertahankan
    assert article.scraper_id == "vendor"


def test_tracking_parameters_do_not_defeat_the_check(
    session: Session, alerts: list[object], classify_calls: list[str]
) -> None:
    """Kunci = `url_hash` (URL dikanonikalisasi), sama dengan kunci unik `articles`."""
    _run(session, source="Vendor Blog", scraper_id="vendor", calls=classify_calls)
    second = _run(
        session,
        source="Aggregator",
        scraper_id="aggregator",
        url=f"{URL}?utm_source=rss",
        calls=classify_calls,
    )

    assert second.duplicate
    assert len(classify_calls) == 1 and len(alerts) == 1


def test_a_rejected_url_is_still_classified_again(
    session: Session,
    alerts: list[object],
    classify_calls: list[str],
) -> None:
    """Penolakan dinilai dari JUDUL, dan feed lain bisa memberi judul berbeda; jalur
    tolak juga tidak mengirim alert. Hanya `articles` (dan job `classify` yang masih menunggu)
    yang menghentikan pipeline."""
    rejected = ClassifyResult(related_cyber=False)
    first = _run(
        session, source="Vendor Blog", scraper_id="vendor", calls=classify_calls, verdict=rejected
    )
    second = _run(
        session,
        source="Aggregator",
        scraper_id="aggregator",
        calls=classify_calls,
        verdict=rejected,
    )

    assert not first.accepted and not second.accepted
    assert len(classify_calls) == 2
    assert alerts == []


def test_pending_classify_job_makes_a_second_arrival_a_duplicate(
    session: Session, alerts: list[object]
) -> None:
    """Review Focus 1 di Postgres: job `classify` menunggu (gateway mati), URL yang sama datang lagi
    dari feed lain dengan judul lain -> tanpa job kedua, tanpa artikel, tanpa alert."""
    first = pipeline.run_pipeline(
        title="Ransomware hits hospital", url=URL, posted_on=None, source="Vendor Blog",
        scraper_id="vendor", session=session,
    )  # fmt: skip
    second = pipeline.run_pipeline(
        title="Hospital hit by ransomware, patients diverted", url=f"{URL}?utm_source=rss",
        posted_on=None, source="Aggregator", scraper_id="aggregator", session=session,
    )  # fmt: skip

    assert first.pending_job_id is not None and second.duplicate
    job = job_for(session, URL)
    assert job is not None and job.id == first.pending_job_id and job.source == "Vendor Blog"
    assert session.scalar(select(func.count()).select_from(EnrichJob)) == 1
    assert _article(session) is None and alerts == []


def test_concurrent_tasks_for_the_same_url_create_one_job(
    _migrated_schema: None, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dua sesi/koneksi sungguhan, seperti dua proses `worker-nlp`. Task A masih di
    tengah `prepare` (fetch) ketika task B datang; B harus menunggu A commit lalu melihat job
    `classify`-nya. Sejak P7g kunci URL tidak lagi dipegang selama panggilan LLM."""
    from cti_core.db.engine import get_sync_engine, sync_session

    release_a = threading.Event()
    calls: list[str] = []

    def slow_fetch(url: str) -> str:
        calls.append(url)
        assert release_a.wait(timeout=30), "task A tidak pernah dilepas"
        return "Isi artikel lengkap. " * 40

    monkeypatch.setattr(pipeline, "fetch_text", slow_fetch)

    outcomes: dict[str, pipeline.PipelineOutcome] = {}
    errors: list[BaseException] = []

    def task(name: str, scraper_id: str) -> None:
        try:
            with sync_session() as s:
                outcomes[name] = pipeline.run_pipeline(
                    title="Ransomware hits hospital", url=URL, posted_on=None, source=name,
                    scraper_id=scraper_id, session=s,
                )  # fmt: skip
        except BaseException as e:  # dilaporkan di thread utama
            errors.append(e)

    def waiting_advisory_locks() -> int:
        with get_sync_engine().connect() as conn:
            return int(
                conn.scalar(
                    select(func.count())
                    .select_from(text("pg_locks"))
                    .where(text("locktype = 'advisory' AND NOT granted"))
                )
                or 0
            )

    a = threading.Thread(target=task, args=("A", "vendor"))
    b = threading.Thread(target=task, args=("B", "aggregator"))
    try:
        a.start()
        deadline = time.monotonic() + 10
        while not calls and time.monotonic() < deadline:  # A sudah memegang URL-nya
            time.sleep(0.05)
        assert calls, "task A tidak sampai ke fetch"

        b.start()
        deadline = time.monotonic() + 10
        while waiting_advisory_locks() < 1 and time.monotonic() < deadline:  # B antre di kunci
            time.sleep(0.05)
        assert waiting_advisory_locks() == 1, "task B tidak menunggu kunci URL"

        release_a.set()
        a.join(timeout=30)
        b.join(timeout=30)
        assert not a.is_alive() and not b.is_alive()
        assert errors == []

        assert len(calls) == 1  # fetch sekali: B berhenti di depan
        assert alerts == []  # belum ada vonis, belum ada alert
        assert outcomes["A"].pending_job_id is not None and outcomes["B"].duplicate
        with sync_session() as s:
            jobs = s.scalars(select(EnrichJob).where(EnrichJob.url_hash == url_hash(URL))).all()
            assert [(j.kind, j.source) for j in jobs] == [("classify", "A")]
            assert s.scalar(select(Article.id).where(Article.url_hash == url_hash(URL))) is None
    finally:
        release_a.set()
        a.join(timeout=30)
        b.join(timeout=30)
        with sync_session() as s:  # sesi sungguhan meng-commit: bersihkan
            s.execute(delete(EnrichJob).where(EnrichJob.url_hash == url_hash(URL)))
            s.execute(delete(Article).where(Article.url_hash == url_hash(URL)))
            # Story (P3) yang ikut ter-commit: kalau tertinggal ber-`classify`, test lain dengan
            # judul sama mewarisinya dan tidak memanggil classify palsunya.
            s.execute(delete(Story).where(Story.title == "Ransomware hits hospital"))
