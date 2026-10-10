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
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

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


@pytest.fixture
def classify_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def fake_classify(title: str) -> ClassifyResult:
        calls.append(title)
        return ClassifyResult(
            related_cyber=True, confidence=0.9, reason="ransomware", industries_impacted=["General"]
        )

    monkeypatch.setattr(pipeline, "classify", fake_classify)
    return calls


@pytest.fixture(autouse=True)
def _stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage yang butuh LLM/jaringan diganti; `persist`/`routing` ASLI."""
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "Isi artikel lengkap. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan insiden ransomware.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    monkeypatch.setattr(
        pipeline, "extract_ttps", lambda s: pipeline.TtpResult(has_techniques=False)
    )


def _run(
    session: Session, *, source: str, scraper_id: str, url: str = URL
) -> pipeline.PipelineOutcome:
    return pipeline.run_pipeline(
        title="Ransomware hits hospital",
        url=url,
        posted_on=None,
        source=source,
        scraper_id=scraper_id,
        session=session,
    )


def _article(session: Session) -> Article | None:
    return session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))


def test_second_source_for_the_same_url_skips_llm_and_alert(
    session: Session, alerts: list[object], classify_calls: list[str]
) -> None:
    first = _run(session, source="Vendor Blog", scraper_id="vendor")
    second = _run(session, source="Aggregator", scraper_id="aggregator")

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
    _run(session, source="Vendor Blog", scraper_id="vendor")
    second = _run(
        session, source="Aggregator", scraper_id="aggregator", url=f"{URL}?utm_source=rss"
    )

    assert second.duplicate
    assert len(classify_calls) == 1 and len(alerts) == 1


def test_a_rejected_url_is_still_classified_again(
    session: Session,
    alerts: list[object],
    classify_calls: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Penolakan dinilai dari JUDUL, dan feed lain bisa memberi judul berbeda; jalur
    tolak juga tidak mengirim alert. Hanya `articles` yang menghentikan pipeline."""
    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda title: classify_calls.append(title) or ClassifyResult(related_cyber=False),
    )

    first = _run(session, source="Vendor Blog", scraper_id="vendor")
    second = _run(session, source="Aggregator", scraper_id="aggregator")

    assert not first.accepted and not second.accepted
    assert len(classify_calls) == 2
    assert alerts == []


def test_concurrent_tasks_for_the_same_url_enrich_and_alert_once(
    _migrated_schema: None, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dua sesi/koneksi sungguhan, seperti dua proses `worker-nlp`. Task A masih di
    tengah LLM ketika task B datang; B harus menunggu A commit lalu melihat artikelnya."""
    from cti_core.db.engine import get_sync_engine, sync_session

    release_a = threading.Event()
    calls: list[str] = []

    def slow_classify(title: str) -> ClassifyResult:
        calls.append(title)
        assert release_a.wait(timeout=30), "task A tidak pernah dilepas"
        return ClassifyResult(
            related_cyber=True, confidence=0.9, reason="ransomware", industries_impacted=["General"]
        )

    monkeypatch.setattr(pipeline, "classify", slow_classify)

    outcomes: dict[str, pipeline.PipelineOutcome] = {}
    errors: list[BaseException] = []

    def task(name: str, scraper_id: str) -> None:
        try:
            with sync_session() as s:
                outcomes[name] = _run(s, source=name, scraper_id=scraper_id)
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
        assert calls, "task A tidak sampai ke klasifikasi"

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

        assert len(calls) == 1  # LLM sekali
        assert len(alerts) == 1  # alert sekali
        assert not outcomes["A"].duplicate and outcomes["B"].duplicate
        with sync_session() as s:
            article = s.scalar(select(Article).where(Article.url_hash == url_hash(URL)))
            assert article is not None and article.seen_count == 2 and article.source == "A"
    finally:
        release_a.set()
        a.join(timeout=30)
        b.join(timeout=30)
        with sync_session() as s:  # sesi sungguhan meng-commit: bersihkan
            s.execute(delete(Article).where(Article.url_hash == url_hash(URL)))
