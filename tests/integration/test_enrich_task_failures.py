"""Task Celery `enrich.article` -- kebijakan kegagalan (Fase 10.A2, diubah P7g).

Latar: di e2e staging 3 dari 30 artikel HILANG tanpa jejak, karena artikel yang
sudah lolos dedup (`scraper_seen` di-commit pas `send_task`) dan gagal di
pipeline cuma ninggalin baris log. Prinsip yang dikunci di sini: artikel gak
boleh hilang tanpa catatan -- entah di-retry sampai berhasil, atau dicatat sebagai
job `classify` `failed` di `enrich_jobs` buat di-retry/diputuskan analis.

Sejak P7g task ini tidak memanggil LLM; yang di-retry Celery hanya error DB/jaringan. Error
gateway LLM (5xx, 429, respons kosong, JSON rusak, 401) ditangani job runner `enrich.llm`.

Task dijalankan lewat `apply()` (eager, sinkron): `self.retry()` langsung
ngeulang tanpa nunggu countdown, jadi jumlah percobaan bisa dihitung tepat.
DB beneran (testcontainers) -- `on_failure` commit sendiri, jadi baris hasilnya
dibersihin manual biar gak bocor ke test lain.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace

import httpx
import openai
import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article, RejectedArticle
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.urlkit import url_hash
from sqlalchemy import delete, select

URL = "https://example.com/enrich-fail/report-1"
KWARGS = {
    "title": "Ransomware hits hospital",
    "url": URL,
    "posted_on": "2026-09-20",
    "source": "Test",
    "scraper_id": "t",
}
_REQ = httpx.Request("POST", "http://gw/v1/chat/completions")


@pytest.fixture(autouse=True)
def _clean(_migrated_schema: None) -> Iterator[None]:
    def wipe() -> None:
        with sync_session() as s:
            s.execute(delete(EnrichJob).where(EnrichJob.url_hash == url_hash(URL)))
            s.execute(delete(RejectedArticle).where(RejectedArticle.url_hash == url_hash(URL)))
            s.execute(delete(Article).where(Article.url_hash == url_hash(URL)))

    wipe()
    yield
    wipe()


@pytest.fixture
def mod(_migrated_schema: None):
    # Import LAZY: `cti_worker.celery_app` baca settings + DB pas di-import.
    from cti_worker.tasks import enrich

    return enrich


@pytest.fixture(autouse=True)
def alerts(mod, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Alert "job gagal" (`llm_dispatch.alert_job_failed`) dicatat, bukan dikirim (Redis +
    Telegram nyata tidak ada di sini)."""
    from cti_worker.tasks import llm_dispatch

    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(llm_dispatch, "alert_job_failed", lambda *a: seen.append(a))
    return seen


def stub_pipeline(monkeypatch: pytest.MonkeyPatch, *outcomes: BaseException | None) -> list[int]:
    """`run_pipeline` palsu: tiap panggilan ngambil satu item dari `outcomes`
    (exception di-raise, `None` = sukses; item terakhir diulang selamanya)."""
    calls: list[int] = []

    def fake(**_kwargs: object) -> SimpleNamespace:
        calls.append(1)
        item = outcomes[min(len(calls), len(outcomes)) - 1]
        if item is not None:
            raise item
        return SimpleNamespace(accepted=True, news_type="global", article_id=1, pending_job_id=None)

    monkeypatch.setattr("cti_enrich.pipeline.run_pipeline", fake)
    return calls


def failed_job() -> EnrichJob | None:
    with sync_session() as s:
        job = s.scalar(
            select(EnrichJob).where(
                EnrichJob.kind == "classify", EnrichJob.url_hash == url_hash(URL)
            )
        )
        if job is not None:
            s.expunge(job)
        return job


def rejected_reason() -> str | None:
    with sync_session() as s:
        return s.scalar(
            select(RejectedArticle.reason).where(RejectedArticle.url_hash == url_hash(URL))
        )


def conn_error() -> httpx.ConnectError:
    return httpx.ConnectError("refused")


# --- retry ------------------------------------------------------------------


def test_transient_errors_are_retried_until_success(mod, monkeypatch) -> None:
    calls = stub_pipeline(monkeypatch, conn_error(), conn_error(), None)

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.successful() and len(calls) == 3
    assert failed_job() is None  # sukses -> gak ada catatan gagal


def test_persistent_transient_error_is_retried_6_times_then_recorded(
    mod, monkeypatch, alerts
) -> None:
    calls = stub_pipeline(monkeypatch, conn_error())

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed() and len(calls) == 1 + 6  # percobaan awal + 6 retry
    job = failed_job()
    assert job is not None and job.state == "failed" and job.input_text is None
    assert (job.last_error or "").startswith("ConnectError: refused")
    assert rejected_reason() is None  # bukan lagi baris `[enrichment_failed]`
    # Job `failed` baru = satu alert (dedupe per jendela ada di `alert_job_failed`).
    assert alerts == [(KWARGS["title"], job.last_error)]


def test_replay_flag_silences_the_alerts_and_plain_messages_do_not(mod, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake(**kw: object) -> SimpleNamespace:
        seen.update(kw)
        return SimpleNamespace(accepted=True, news_type="global", article_id=1, pending_job_id=None)

    monkeypatch.setattr("cti_enrich.pipeline.run_pipeline", fake)

    assert mod.enrich_article.apply(kwargs={**KWARGS, "replay": True}).successful()
    assert seen["alert"] is False
    assert mod.enrich_article.apply(kwargs=KWARGS).successful()  # pesan lama tanpa `replay`
    assert seen["alert"] is True


def test_db_connection_drop_is_retried(mod, monkeypatch) -> None:
    import sqlalchemy.exc

    err = sqlalchemy.exc.OperationalError("SELECT 1", {}, Exception("server closed the connection"))
    calls = stub_pipeline(monkeypatch, err, None)

    assert mod.enrich_article.apply(kwargs=KWARGS).successful()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "error",
    [
        openai.InternalServerError("boom", response=httpx.Response(502, request=_REQ), body=None),
        openai.AuthenticationError("bad", response=httpx.Response(401, request=_REQ), body=None),
    ],
)
def test_llm_errors_are_not_retried_by_this_task(mod, monkeypatch, error: Exception) -> None:
    """Pipeline tidak memanggil LLM lagi; kalaupun error LLM sampai sini (bug), retry Celery tidak
    akan menyembuhkannya: langsung dicatat sebagai job `failed`."""
    calls = stub_pipeline(monkeypatch, error)

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed() and len(calls) == 1
    job = failed_job()
    assert job is not None and (job.last_error or "").startswith(type(error).__name__)


# --- tanpa retry, langsung dicatat ----------------------------------------------


def test_recorded_job_carries_the_article_metadata(mod, monkeypatch) -> None:
    stub_pipeline(monkeypatch, RuntimeError("bug tak terduga"))

    mod.enrich_article.apply(kwargs=KWARGS)

    job = failed_job()
    assert job is not None
    assert (job.title, job.source, job.scraper_id) == (KWARGS["title"], "Test", "t")
    assert str(job.posted_on) == "2026-09-20"
    assert job.last_error == "RuntimeError: bug tak terduga"
    # `t` tidak terdaftar di registry: bawaan `_relevance_for`, ikut di context untuk job runner.
    assert job.context == {
        "content_kind": None,
        "default_relevance": "classify",
        "tlp": "clear",
        "pap": "clear",
    }


def test_failing_to_record_never_hides_the_original_failure(mod, monkeypatch) -> None:
    from cti_core.db.repositories.enrich_job import EnrichJobRepo

    stub_pipeline(monkeypatch, RuntimeError("bug tak terduga"))

    def broken_create(self: object, **_kw: object) -> None:
        raise ConnectionError("db mati")

    monkeypatch.setattr(EnrichJobRepo, "create", broken_create)

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed() and isinstance(result.result, RuntimeError)  # aslinya utuh


# --- gagal SESUDAH persist: artikel harus selamat -----------------------------------


def test_alert_failure_does_not_roll_back_the_persisted_article(mod, monkeypatch, alerts) -> None:
    """`persist` + `route_alerts` satu transaksi; exception dari alert bikin
    `sync_session()` ROLLBACK. Dulu artikel yang sudah ke-persist ikut batal
    cuma karena notifikasi Telegram-nya gagal. Jalur tanpa LLM: Tier 0 (`always`)."""
    from cti_enrich import pipeline
    from cti_enrich.stages.score import ScoreResult

    monkeypatch.setattr(mod, "_relevance_for", lambda sid: ("kev", "always", "clear", "clear"))
    monkeypatch.setattr(pipeline, "fetch_text", lambda u: "Isi artikel. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda t: "Ringkasan.")
    monkeypatch.setattr(pipeline.extract_iocs_stage, "extract_iocs", lambda *a, **k: {})
    monkeypatch.setattr(pipeline.extract_iocs_stage, "check_c2_hit", lambda *a, **k: False)
    monkeypatch.setattr(pipeline.score_stage, "score", lambda *a, **k: ScoreResult())

    def telegram_down(_result: object) -> None:
        raise ConnectionError("telegram unreachable")

    monkeypatch.setattr(pipeline, "route_alerts", telegram_down)

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed()  # tetap kelihatan gagal (alert-nya)
    with sync_session() as s:
        saved = s.scalar(select(Article.id).where(Article.url_hash == url_hash(URL)))
    assert saved is not None  # ... tapi ARTIKELNYA SELAMAT
    assert failed_job() is None  # dan gak salah dicatat sbg hilang
    assert alerts == []  # dan tidak ada alert "enrichment gagal" palsu


def test_failure_reason_never_contains_configured_secrets(mod, monkeypatch) -> None:
    """Pesan error provider bisa ngecho (sebagian) API key; `last_error` masuk DB dan
    tampil di UI antrean enrichment -- secret yang dikonfigurasi harus di-scrub."""
    from cti_core.config import get_settings

    secret = "sk-SUPER-SECRET-KEY-1234567890"
    monkeypatch.setenv("LLM__API_KEY", secret)
    get_settings.cache_clear()
    stub_pipeline(
        monkeypatch, RuntimeError(f"Incorrect API key provided: {secret}. Check dashboard")
    )

    mod.enrich_article.apply(kwargs=KWARGS)
    job = failed_job()
    get_settings.cache_clear()

    error = (job.last_error if job else None) or ""
    assert error.startswith("RuntimeError: Incorrect API key provided")
    assert secret not in error and "***" in error


def test_long_error_is_cut_to_300_chars(mod, monkeypatch) -> None:
    stub_pipeline(monkeypatch, RuntimeError("x" * 1000))

    mod.enrich_article.apply(kwargs=KWARGS)

    job = failed_job()
    assert job is not None and len(job.last_error or "") == 300
