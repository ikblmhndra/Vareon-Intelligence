"""`cti_enrich.pipeline.run_pipeline` -- ketahanan terhadap kegagalan stage.

Pipeline sebelumnya gak punya test otomatis sama sekali (cuma korpus live
Fase 5). Yang dikunci di sini lahir dari e2e staging Fase 10: LLM gagal
ngasih JSON di stage TTP -> exception nembus ke Celery -> SELURUH artikel
(yang sudah lolos klasifikasi) hilang. TTP itu pengayaan opsional, klasifikasi
bukan -- perlakuannya harus beda.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from cti_core.db.models.article import Article
from cti_core.urlkit import url_hash
from cti_enrich import pipeline
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.score import ScoreResult
from sqlalchemy import select
from sqlalchemy.orm import Session

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


@pytest.fixture(autouse=True)
def _stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Semua stage yang butuh LLM/jaringan diganti; `persist`/`routing` ASLI."""
    monkeypatch.setattr(
        pipeline,
        "classify",
        lambda title: ClassifyResult(
            related_cyber=True, confidence=0.9, reason="ransomware", industries_impacted=["General"]
        ),
    )
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "Isi artikel lengkap. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda text: "Ringkasan insiden ransomware.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())
    # Default sukses tanpa TTP -- WAJIB di-stub: tanpa ini `extract_ttps` asli
    # manggil LLM beneran (lolos di laptop yang punya `.env`, OpenAIError di CI).
    monkeypatch.setattr(
        pipeline, "extract_ttps", lambda s: pipeline.TtpResult(has_techniques=False)
    )


def _run(session: Session):
    return pipeline.run_pipeline(
        title="Ransomware hits hospital",
        url=URL,
        posted_on=None,
        source="Test",
        scraper_id="t",
        session=session,
    )


def _article(session: Session) -> Article | None:
    return session.scalar(select(Article).where(Article.url_hash == url_hash(URL)))


def test_ttp_json_failure_keeps_the_article_without_ttps(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_json(summary: str):
        raise json.JSONDecodeError("Expecting value", "I don't see an article summary", 0)

    monkeypatch.setattr(pipeline, "extract_ttps", no_json)

    outcome = _run(session)

    assert outcome.accepted and outcome.article_id is not None
    article = _article(session)
    assert article is not None and article.ttps == []  # tersimpan TANPA TTP
    assert len(alerts) == 1  # alert tetap keluar: artikelnya relevan


def test_empty_summary_skips_the_ttp_call_entirely(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Halaman diblokir -> `fetch_text` "" -> summary "" -> gak ada panggilan LLM
    buat TTP (dan gak ada boilerplate WAF yang dikirim ke model)."""
    monkeypatch.setattr(pipeline, "fetch_text", lambda url: "")
    monkeypatch.setattr(pipeline, "summarize", lambda text: "")
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "extract_ttps", lambda s: calls.append(s))

    outcome = _run(session)

    assert outcome.accepted and calls == []
    assert _article(session) is not None


def test_a_failing_classify_still_raises_so_celery_can_retry(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Beda dari TTP: tanpa klasifikasi kita GAK TAU artikel ini relevan atau
    bukan -- jangan ditebak, biarkan naik ke retry Celery."""

    def broken(title: str):
        raise json.JSONDecodeError("Expecting value", "", 0)

    monkeypatch.setattr(pipeline, "classify", broken)

    with pytest.raises(json.JSONDecodeError):
        _run(session)
    assert alerts == []


def test_non_json_errors_from_the_ttp_stage_are_not_swallowed(
    session: Session, alerts: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cuma JSONDecodeError yang di-degrade. LLM mati / kuota abis tetap naik."""

    def quota(summary: str):
        raise RuntimeError("OpenAI credit exhausted")

    monkeypatch.setattr(pipeline, "extract_ttps", quota)

    with pytest.raises(RuntimeError):
        _run(session)


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

    _run(session)  # `extract_ttps` di-stub default -> sukses penuh

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
