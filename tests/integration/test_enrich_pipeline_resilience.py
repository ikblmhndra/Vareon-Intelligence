"""`cti_enrich.pipeline.run_pipeline` -- ketahanan terhadap kegagalan stage.

Pipeline sebelumnya gak punya test otomatis sama sekali (cuma korpus live
Fase 5). Yang dikunci di sini lahir dari e2e staging Fase 10: LLM gagal
ngasih JSON di stage TTP -> exception nembus ke Celery -> SELURUH artikel
(yang sudah lolos klasifikasi) hilang. TTP itu pengayaan opsional, klasifikasi
bukan -- perlakuannya harus beda.

P7g: pipeline tidak memanggil LLM sama sekali. Vonis classify datang dari job `classify`
(`_run` menyelesaikannya dengan vonis palsu lewat `enrich_job_support`), dan LLM TTP = job `ttp`
yang dibuat bersama artikelnya; kegagalan TTP tidak bisa lagi menyentuh artikel.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import select
from sqlalchemy.orm import Session

from tests.integration.enrich_job_support import job_for, run_with_verdict

URL = "https://example.com/incident-report"


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


@pytest.fixture(autouse=True)
def _stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage jaringan diganti; `persist`/`routing` ASLI. LLM tidak dipanggil pipeline lagi (P7g);
    stage LLM dibuat meledak supaya panggilan yang tersisa langsung ketahuan."""
    from cti_enrich.stages import classify as classify_stage
    from cti_enrich.stages import extract_ttps as ttp_stage

    def no_llm(*a: object, **k: object) -> None:
        raise AssertionError("pipeline tidak boleh memanggil LLM")

    monkeypatch.setattr(classify_stage, "classify", no_llm)
    monkeypatch.setattr(ttp_stage, "extract_ttps", no_llm)
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "Isi artikel lengkap. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan insiden ransomware.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())


def _run(session: Session, *, alert: bool = True) -> pipeline.PipelineOutcome:
    return run_with_verdict(
        session,
        RELEVANT,
        alert=alert,
        title="Ransomware hits hospital",
        url=URL,
        posted_on=None,
        source="Test",
        scraper_id="t",
    )


def _article(session: Session) -> Article | None:
    return session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))


def test_accepted_article_is_stored_with_a_pending_ttp_job(
    session: Session, alerts: list[object]
) -> None:
    """TTP LLM tidak lagi dijalankan inline: artikel tersimpan dengan teknik Tier 1 saja,
    `llm_ttp_status='pending'`, dan job `ttp` membawa teks yang akan dikirim ke model."""
    outcome = _run(session)

    assert outcome.accepted and outcome.article_id is not None
    article = _article(session)
    assert article is not None and article.llm_ttp_status == "pending"
    job = job_for(session, URL, "ttp")
    assert job is not None and job.article_id == article.id and job.state == "pending"
    assert job.input_text == pipeline.ttp_job_input(
        "Isi artikel lengkap. " * 40, "Ringkasan insiden ransomware."
    )
    assert job_for(session, URL) is None  # job classify sudah selesai
    assert len(alerts) == 1  # alert tetap keluar sekarang (D1)


def test_empty_summary_skips_the_ttp_job_entirely(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Halaman diblokir -> `fetch_text` "" -> summary "" -> tidak ada job TTP (dan gak ada
    boilerplate WAF yang dikirim ke model)."""
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "")
    monkeypatch.setattr(pipeline, "summarize", lambda text: "")

    outcome = _run(session)

    assert outcome.accepted
    article = _article(session)
    assert article is not None and article.llm_ttp_status == "skipped"
    assert job_for(session, URL, "ttp") is None


def test_replay_without_alert_still_saves_the_article(
    session: Session, alerts: list[object]
) -> None:
    """Vonis yang datang tanpa alert (`alert=False`): tersimpan penuh, TANPA Telegram."""
    outcome = _run(session, alert=False)

    assert outcome.accepted and _article(session) is not None
    assert alerts == []


def test_an_uncertain_title_waits_as_a_classify_job(session: Session, alerts: list[object]) -> None:
    """Dulu classify yang gagal naik ke retry Celery. Sekarang tanpa vonis relevansi artikel
    tidak disimpan maupun ditolak: ia menunggu sebagai job `classify` dengan teks hasil fetch."""
    outcome = pipeline.run_pipeline(
        title="Ransomware hits hospital", url=URL, posted_on=None, source="Test",
        scraper_id="t", session=session,
    )  # fmt: skip

    assert not outcome.accepted and outcome.pending_job_id is not None
    job = session.get(EnrichJob, outcome.pending_job_id)
    assert job is not None and job.kind == "classify" and job.state == "pending"
    assert job.input_text == "Isi artikel lengkap. " * 40
    assert _article(session) is None and alerts == []


def test_a_previously_failed_article_leaves_no_stale_rejected_row_once_it_succeeds(
    session: Session, alerts: list[object]
) -> None:
    """Artikel yang dulu `[enrichment_failed]` lalu berhasil di-replay gak boleh
    muncul dobel (artikel + baris "ditolak") di Filtered Articles."""
    from cti_core.db.models.article import RejectedArticle
    from cti_core.db.repositories.article import RejectedArticleRepo

    RejectedArticleRepo(session).upsert(
        url=URL, title="Ransomware hits hospital", source="Test", reason="[enrichment_failed] X"
    )
    assert session.scalar(
        select(RejectedArticle.id).where(RejectedArticle.url_hash == url_hash(URL))
    )

    _run(session)  # vonis relevan -> sukses penuh

    assert _article(session) is not None
    assert (
        session.scalar(select(RejectedArticle.id).where(RejectedArticle.url_hash == url_hash(URL)))
        is None
    )


# --- penghitung mention CVE (Fase 10.E) ---------------------------------------------


def _mentions(session: Session) -> dict[str, int]:
    from cti_core.db.models.report_state import SCOPE_NEWS
    from cti_core.db.repositories.report_state import CveMentionRepo

    return {m.cve_id: m.counter for m in CveMentionRepo(session).top(SCOPE_NEWS, limit=100)}


def _with_cves(monkeypatch: pytest.MonkeyPatch, title: list[str], body: list[str]) -> None:
    monkeypatch.setattr(
        pipeline.score_stage,
        "score",
        lambda *a, **k: ScoreResult(cve_list_title=title, cve_list_body=body),
    )


def test_a_new_article_bumps_every_cve_it_mentions(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_cves(monkeypatch, ["cve-2026-0001"], ["cve-2026-0001", "cve-2026-0002"])

    _run(session)

    assert _mentions(session) == {"CVE-2026-0001": 2, "CVE-2026-0002": 1}


def test_retrying_an_article_does_not_double_count_its_cves(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alert gagal -> task di-retry atas artikel yang SAMA. Retry berhenti di depan
    (`_known_article`); guard `seen_count` di `_track_cve_mentions` lapis kedua."""
    _with_cves(monkeypatch, ["cve-2026-0001"], [])

    _run(session)
    _run(session)  # retry: artikel sudah ada (seen_count 2)

    assert _mentions(session) == {"CVE-2026-0001": 1}


def test_a_failing_alert_still_keeps_the_mention_counted_once(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alert gagal SESUDAH artikel di-commit. Percobaan ulang atas URL yang sama tidak
    menjalankan pipeline lagi (artikel sudah ada), jadi alert tidak dicoba ulang --
    alert yang gagal hilang, bukan terkirim dobel -- dan mention tetap terhitung sekali."""
    _with_cves(monkeypatch, ["cve-2026-0001"], [])
    attempted: list[object] = []

    def telegram_down(result: object) -> None:
        attempted.append(result)
        raise ConnectionError("telegram down")

    monkeypatch.setattr(pipeline, "route_alerts", telegram_down)
    with pytest.raises(ConnectionError):
        _run(session)
    assert _run(session).duplicate  # retry

    assert len(attempted) == 1
    assert _mentions(session) == {"CVE-2026-0001": 1}


def test_broken_mention_tracking_never_blocks_the_article_or_its_alert(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    from cti_core.db.repositories.report_state import CveMentionRepo

    _with_cves(monkeypatch, ["cve-2026-0001"], [])

    def boom(self: object, *a: object, **k: object) -> int:
        raise RuntimeError("cve_mentions rusak")

    monkeypatch.setattr(CveMentionRepo, "bump", boom)

    outcome = _run(session)

    assert outcome.accepted and _article(session) is not None and len(alerts) == 1
