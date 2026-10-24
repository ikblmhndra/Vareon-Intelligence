"""Task Celery `enrich.article` -- kebijakan kegagalan (Fase 10.A2).

Latar: di e2e staging 3 dari 30 artikel HILANG tanpa jejak, karena artikel yang
sudah lolos dedup (`scraper_seen` di-commit pas `send_task`) dan gagal di
pipeline cuma ninggalin baris log. Prinsip yang dikunci di sini: artikel gak
boleh hilang tanpa catatan -- entah di-retry sampai berhasil, atau dicatat ke
`rejected_articles` ([enrichment_failed]) buat direview/di-restore analis.

Task dijalankan lewat `apply()` (eager, sinkron): `self.retry()` langsung
ngeulang tanpa nunggu countdown, jadi jumlah percobaan bisa dihitung tepat.
DB beneran (testcontainers) -- `on_failure` commit sendiri, jadi baris hasilnya
dibersihin manual biar gak bocor ke test lain.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from types import SimpleNamespace

import httpx
import openai
import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.article import Article, RejectedArticle
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
def alerts(mod, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, int]]:
    """Alert enrichment gagal dicatat, bukan dikirim (Redis + Telegram nyata tidak ada di sini)."""
    seen: list[tuple[str, str, int]] = []
    monkeypatch.setattr(mod, "_alert_enrichment_failure", lambda *a: seen.append(a))
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
        return SimpleNamespace(accepted=True, news_type="global", article_id=1)

    monkeypatch.setattr("cti_enrich.pipeline.run_pipeline", fake)
    return calls


def rejected_reason() -> str | None:
    with sync_session() as s:
        return s.scalar(
            select(RejectedArticle.reason).where(RejectedArticle.url_hash == url_hash(URL))
        )


def rejected_kind() -> str | None:
    with sync_session() as s:
        return s.scalar(
            select(RejectedArticle.failure_kind).where(RejectedArticle.url_hash == url_hash(URL))
        )


def conn_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=_REQ)


# --- retry ------------------------------------------------------------------


def test_transient_llm_errors_are_retried_until_success(mod, monkeypatch) -> None:
    calls = stub_pipeline(monkeypatch, conn_error(), conn_error(), None)

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.successful() and len(calls) == 3
    assert rejected_reason() is None  # sukses -> gak ada catatan gagal


def test_persistent_transient_error_is_retried_6_times_then_recorded(
    mod, monkeypatch, alerts
) -> None:
    calls = stub_pipeline(monkeypatch, conn_error())

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed() and len(calls) == 1 + 6  # percobaan awal + 6 retry
    reason = rejected_reason()
    assert reason and reason.startswith("[enrichment_failed] APIConnectionError")
    assert rejected_kind() == "transient"
    [(error_type, _message, waiting)] = alerts  # SATU alert, di kegagalan final saja
    assert error_type == "APIConnectionError" and waiting >= 1


def test_replay_flag_silences_the_alerts_and_plain_messages_do_not(mod, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake(**kw: object) -> SimpleNamespace:
        seen.update(kw)
        return SimpleNamespace(accepted=True, news_type="global", article_id=1)

    monkeypatch.setattr("cti_enrich.pipeline.run_pipeline", fake)

    assert mod.enrich_article.apply(kwargs={**KWARGS, "replay": True}).successful()
    assert seen["alert"] is False
    assert mod.enrich_article.apply(kwargs=KWARGS).successful()  # pesan lama tanpa `replay`
    assert seen["alert"] is True


def test_empty_llm_response_is_retried_like_a_5xx(mod, monkeypatch) -> None:
    from cti_core.llm.client import EmptyLLMResponse

    calls = stub_pipeline(monkeypatch, EmptyLLMResponse("LLM membalas tanpa choices: None"), None)

    assert mod.enrich_article.apply(kwargs=KWARGS).successful()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "error",
    [
        openai.InternalServerError("boom", response=httpx.Response(502, request=_REQ), body=None),
        openai.RateLimitError("slow down", response=httpx.Response(429, request=_REQ), body=None),
        httpx.ConnectError("refused"),
    ],
)
def test_each_transient_category_is_retried(mod, monkeypatch, error: Exception) -> None:
    calls = stub_pipeline(monkeypatch, error, None)

    assert mod.enrich_article.apply(kwargs=KWARGS).successful()
    assert len(calls) == 2


def test_db_connection_drop_is_retried(mod, monkeypatch) -> None:
    import sqlalchemy.exc

    err = sqlalchemy.exc.OperationalError("SELECT 1", {}, Exception("server closed the connection"))
    calls = stub_pipeline(monkeypatch, err, None)

    assert mod.enrich_article.apply(kwargs=KWARGS).successful()
    assert len(calls) == 2


def test_json_errors_get_only_two_retries(mod, monkeypatch) -> None:
    calls = stub_pipeline(monkeypatch, json.JSONDecodeError("Expecting value", "prosa", 0))

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed() and len(calls) == 1 + 2
    assert "[enrichment_failed] JSONDecodeError" in (rejected_reason() or "")
    assert rejected_kind() == "json"


# --- tanpa retry, langsung dicatat ----------------------------------------------


def test_auth_error_is_not_retried_and_is_recorded(mod, monkeypatch) -> None:
    err = openai.AuthenticationError(
        "bad key", response=httpx.Response(401, request=_REQ), body=None
    )
    calls = stub_pipeline(monkeypatch, err)

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert (
        result.failed() and len(calls) == 1
    )  # retry cuma buang waktu: key salah gak sembuh sendiri
    assert "AuthenticationError" in (rejected_reason() or "")
    assert rejected_kind() == "config"


def test_quota_exhausted_is_not_retried_and_is_recorded(mod, monkeypatch) -> None:
    from cti_enrich.stages.classify import OpenAIQuotaExhausted

    calls = stub_pipeline(monkeypatch, OpenAIQuotaExhausted("credit exhausted"))

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed() and len(calls) == 1
    assert "OpenAIQuotaExhausted" in (rejected_reason() or "")


def test_recorded_row_carries_the_article_metadata(mod, monkeypatch) -> None:
    stub_pipeline(monkeypatch, RuntimeError("bug tak terduga"))

    mod.enrich_article.apply(kwargs=KWARGS)

    with sync_session() as s:
        row = s.scalar(select(RejectedArticle).where(RejectedArticle.url_hash == url_hash(URL)))
        assert row is not None
        assert (row.title, row.source, row.scraper_id) == (KWARGS["title"], "Test", "t")
        assert str(row.posted_on) == "2026-09-20"


def test_failing_to_record_never_hides_the_original_failure(mod, monkeypatch) -> None:
    from cti_core.db.repositories.article import RejectedArticleRepo

    stub_pipeline(monkeypatch, RuntimeError("bug tak terduga"))

    def broken_upsert(self: object, **_kw: object) -> None:
        raise ConnectionError("db mati")

    monkeypatch.setattr(RejectedArticleRepo, "upsert", broken_upsert)

    result = mod.enrich_article.apply(kwargs=KWARGS)

    assert result.failed() and isinstance(result.result, RuntimeError)  # aslinya utuh


# --- gagal SESUDAH persist: artikel harus selamat -----------------------------------


def test_alert_failure_does_not_roll_back_the_persisted_article(mod, monkeypatch, alerts) -> None:
    """`persist` + `route_alerts` satu transaksi; exception dari alert bikin
    `sync_session()` ROLLBACK. Dulu artikel yang sudah ke-persist ikut batal
    cuma karena notifikasi Telegram-nya gagal."""
    from cti_enrich import pipeline
    from cti_enrich.stages.classify import ClassifyResult
    from cti_enrich.stages.score import ScoreResult

    relevant = ClassifyResult(
        related_cyber=True, confidence=0.9, reason="r", industries_impacted=["General"]
    )
    monkeypatch.setattr(pipeline, "classify", lambda t: relevant)
    monkeypatch.setattr(pipeline, "fetch_text", lambda u: "Isi artikel. " * 40)
    monkeypatch.setattr(pipeline, "summarize", lambda t: "Ringkasan.")
    monkeypatch.setattr(
        pipeline, "extract_ttps", lambda s: pipeline.TtpResult(has_techniques=False)
    )
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
    assert rejected_reason() is None  # dan gak salah dicatat sbg hilang
    assert alerts == []  # dan tidak ada alert "enrichment gagal" palsu


def test_failure_reason_never_contains_configured_secrets(mod, monkeypatch) -> None:
    """Pesan error provider bisa ngecho (sebagian) API key; `reason` masuk DB dan
    tampil di UI Filtered Articles -- secret yang dikonfigurasi harus di-scrub."""
    from cti_core.config import get_settings

    secret = "sk-SUPER-SECRET-KEY-1234567890"
    monkeypatch.setenv("LLM__API_KEY", secret)
    get_settings.cache_clear()
    stub_pipeline(
        monkeypatch, RuntimeError(f"Incorrect API key provided: {secret}. Check dashboard")
    )

    mod.enrich_article.apply(kwargs=KWARGS)
    reason = rejected_reason() or ""
    get_settings.cache_clear()

    assert "[enrichment_failed]" in reason and "Incorrect API key provided" in reason
    assert secret not in reason and "***" in reason
