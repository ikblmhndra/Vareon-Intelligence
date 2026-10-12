"""Integration test persiapan bulanan newsletter (ROADMAP #22, PR 8) -- Postgres REAL
(testcontainers), klien LLM diganti stub yang MENGHITUNG panggilan: yang dibuktikan di sini
justru "berapa kali dipanggil" (sekali per saran, nol tanpa recap, nol pada run kedua).

`prepare_monthly` dipanggil langsung dengan sesi test, bukan lewat task Celery: task membuka loop
dan engine-nya sendiri (`asyncio.run`), yang tidak bisa menumpang transaksi test. Pembungkus
task-nya dites di `tests/unit/test_newsletter_task.py`."""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import structlog.testing
from cti_api.services import newsletter_schedule, newsletter_suggestion, newsletter_summary
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.newsletter import NewsletterSuggestion
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from cti_core.db.repositories.recap import AsyncRecapRepo
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.newsletter_stubs import NOW, no_campaigns, suggestion_clock

pytestmark = pytest.mark.asyncio

D = datetime.date
UTC = datetime.UTC

OCTOBER = (D(2026, 10, 1), D(2026, 10, 31))
OCTOBER_WEEKS = [D(2026, 9, 28), D(2026, 10, 5), D(2026, 10, 12), D(2026, 10, 19), D(2026, 10, 26)]
REPLY = "Oktober diwarnai eksploitasi VPN dan CVE-2026-1111."


class CountingLlm:
    """Klien OpenAI palsu yang membalas `{"summary": reply}` dan menghitung panggilan."""

    def __init__(self, reply: str = REPLY) -> None:
        self.reply = reply
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps({"summary": self.reply}))
                )
            ],
            usage=SimpleNamespace(prompt_tokens=400, completion_tokens=150, total_tokens=550),
        )


def _patched_llm(llm: CountingLlm) -> Any:
    return patch.object(
        newsletter_summary, "get_llm_client", MagicMock(return_value=(llm, "stub-model"))
    )


class AuthenticationError(Exception):
    """Seperti `openai.AuthenticationError`: kode HTTP di exception, pesannya memuat kunci."""

    status_code = 401


SECRET = "sk-live-FAKE0123456789abcdef"


def _patched_broken_llm(exc: Exception | None = None) -> Any:
    """LLM yang melempar `exc` (default `RuntimeError`) di setiap panggilan (gateway mati)."""
    broken = MagicMock()
    broken.chat.completions.create.side_effect = exc or RuntimeError("gateway down")
    return patch.object(
        newsletter_summary, "get_llm_client", MagicMock(return_value=(broken, "stub-model"))
    )


async def _seed_recaps(session: AsyncSession, weeks: list[D] = OCTOBER_WEEKS) -> None:
    repo = AsyncRecapRepo(session)
    for week in weeks:
        await repo.upsert(
            week.isoformat(),
            kind="weekly",
            period_start=week,
            period_end=week + datetime.timedelta(days=6),
            headline=f"Headline of {week.isoformat()}",
            yesterday={
                "summary": f"Narrative {week.isoformat()}.",
                "notable_cves": ["CVE-2026-1111"],
                "top_stories": [{"article_id": 1, "title": "VPN zero-day", "why_it_matters": "x"}],
            },
            forecast={"summary": "FORECAST-ONLY-TEXT"},
            counts={},
            generated_at=datetime.datetime(2026, 11, 2, 0, 15, tzinfo=UTC),
            model="m",
            token_usage={},
            quality={},
        )


async def _seed_articles(session: AsyncSession) -> list[int]:
    """Dua artikel Oktober yang cukup kuat untuk masuk saran, dan satu di luar jendela."""
    await AsyncClientRepo(session).ensure_default()
    repo = AsyncArticleRepo(session)
    ids = []
    for n, (title, posted_on) in enumerate(
        [
            ("Ransomware crew breaches an Indonesian bank", D(2026, 10, 12)),
            ("Fortinet zero-day exploited in the wild", D(2026, 10, 20)),
            ("A September story outside the window", D(2026, 9, 30)),
        ]
    ):
        article = await repo.upsert(
            url=f"https://example.com/prep-{n}",
            title=title,
            source="CISA",
            posted_on=posted_on,
            confidence_score=90,
            confirmed_incident=True,
        )
        ids.append(article.id)
    return ids


async def _suggestions(session: AsyncSession) -> list[NewsletterSuggestion]:
    result = await session.execute(select(NewsletterSuggestion))
    return list(result.scalars().all())


# --- repo ---------------------------------------------------------------------------------------


async def test_list_overlapping_returns_the_weekly_rows_that_touch_the_window_in_order(
    async_db_session: AsyncSession,
) -> None:
    await _seed_recaps(
        async_db_session,
        [D(2026, 11, 2), D(2026, 10, 26), D(2026, 9, 28), D(2026, 9, 21), D(2026, 10, 5)],
    )
    await AsyncRecapRepo(async_db_session).upsert(  # harian di tengah Oktober: bukan mingguan
        "2026-10-14",
        period_start=D(2026, 10, 14),
        period_end=D(2026, 10, 14),
        headline="daily",
        yesterday={},
        forecast={},
        counts={},
        generated_at=datetime.datetime(2026, 10, 15, tzinfo=UTC),
        model="m",
        token_usage={},
    )

    rows = await AsyncRecapRepo(async_db_session).list_overlapping("weekly", *OCTOBER)

    # 21-27 Sep berakhir 27 Sep (di luar); 28 Sep-4 Okt dan 26 Okt-1 Nov menyentuh batas bulan;
    # 2-8 Nov mulai sesudah 31 Okt (di luar)
    assert [r.date for r in rows] == ["2026-09-28", "2026-10-05", "2026-10-26"]
    assert {r.kind for r in rows} == {"weekly"}


# --- prepare_monthly end to end -----------------------------------------------------------------


async def test_the_first_weekday_builds_the_suggestion_once_and_the_second_run_does_nothing(
    async_db_session: AsyncSession,
) -> None:
    ids = await _seed_articles(async_db_session)
    await _seed_recaps(async_db_session)
    llm = CountingLlm()

    with _patched_llm(llm), no_campaigns():
        first = await newsletter_schedule.prepare_monthly(async_db_session, NOW)  # Senin 2 Nov
        second = await newsletter_schedule.prepare_monthly(
            async_db_session,
            NOW + datetime.timedelta(days=1),  # Selasa 3 Nov
        )
        late = await newsletter_schedule.prepare_monthly(
            async_db_session,
            NOW + datetime.timedelta(days=5),  # Sabtu 7 Nov, sudah ada saran
        )

    assert first["prepared"] is True and first["summary"] is True and first["items"] == 2
    assert second == late == {"prepared": False, "period_start": "2026-10-01"}
    assert llm.calls == 1  # satu panggilan per edisi, run kedua dan ketiga tanpa LLM
    [row] = await _suggestions(async_db_session)
    assert (row.period_start, row.period_end) == OCTOBER
    assert sorted(i["article_id"] for i in row.items) == sorted(ids[:2])  # September tidak ikut
    assert row.summary_text == REPLY
    assert [w["week_start"] for w in row.summary_meta["weeks"]] == [
        w.isoformat() for w in OCTOBER_WEEKS
    ]
    assert (row.summary_meta["covered_start"], row.summary_meta["covered_end"]) == (
        "2026-09-28",
        "2026-11-01",
    )
    assert row.summary_meta["uncovered"] == []
    assert row.summary_meta["model"] == "stub-model"
    assert row.summary_meta["token_usage"]["total_tokens"] == 550
    assert row.summary_meta["dropped"] == []


async def test_a_worker_that_was_down_still_builds_it_inside_the_window_and_not_after(
    async_db_session: AsyncSession,
) -> None:
    await _seed_articles(async_db_session)
    await _seed_recaps(async_db_session)
    llm = CountingLlm()

    with _patched_llm(llm), no_campaigns():
        too_late = await newsletter_schedule.prepare_monthly(
            async_db_session,
            NOW + datetime.timedelta(days=8),  # Selasa 10 Nov
        )
        assert too_late["prepared"] is False and await _suggestions(async_db_session) == []
        catch_up = await newsletter_schedule.prepare_monthly(
            async_db_session,
            NOW + datetime.timedelta(days=3),  # Kamis 5 Nov
        )

    assert catch_up["prepared"] is True
    assert llm.calls == 1


async def test_a_month_without_weekly_recaps_gets_the_ranking_but_an_empty_summary_and_no_call(
    async_db_session: AsyncSession,
) -> None:
    await _seed_articles(async_db_session)
    llm = CountingLlm()

    with _patched_llm(llm), no_campaigns():
        result = await newsletter_schedule.prepare_monthly(async_db_session, NOW)

    assert result["prepared"] is True and result["summary"] is False and result["items"] == 2
    assert llm.calls == 0
    [row] = await _suggestions(async_db_session)
    assert row.summary_text == ""
    assert row.summary_meta["weeks"] == []
    assert row.summary_meta["uncovered"] == [{"start": "2026-10-01", "end": "2026-10-31"}]
    assert row.summary_meta["token_usage"] == {"skipped": True, "reason": "no_recaps"}


async def test_a_failing_llm_keeps_the_ranking_and_records_the_error(
    async_db_session: AsyncSession,
) -> None:
    """Gateway mati pada hari kerja pertama: rankingnya tersimpan, ringkasannya kosong dengan
    `error`, dan task melaporkan `prepared` (bukan gagal)."""
    ids = await _seed_articles(async_db_session)
    await _seed_recaps(async_db_session)

    with _patched_broken_llm(), no_campaigns(), structlog.testing.capture_logs() as logs:
        result = await newsletter_schedule.prepare_monthly(async_db_session, NOW)

    assert result["prepared"] is True and result["items"] == 2 and result["summary"] is False
    assert result["summary_error"] == "RuntimeError"
    [row] = await _suggestions(async_db_session)
    assert sorted(i["article_id"] for i in row.items) == sorted(ids[:2])
    assert row.summary_text == ""
    meta = row.summary_meta
    assert meta["error"] == "RuntimeError"
    assert meta["token_usage"] == {"skipped": True, "reason": "llm_error"}
    assert meta["parse_failed"] is False and meta["model"] == "" and meta["dropped"] == []
    assert len(meta["weeks"]) == 5 and meta["uncovered"] == []  # yang dihitung dari recap tetap ada
    events = {e["event"]: e for e in logs}
    assert events["newsletter_summary_failed"]["log_level"] == "warning"
    assert events["newsletter_prepared"]["summary_error"] == "RuntimeError"
    assert events["newsletter_summary_failed"]["detail"] == "gateway down"


async def test_the_next_catch_up_day_redoes_only_the_summary_and_clears_the_error(
    async_db_session: AsyncSession,
) -> None:
    await _seed_articles(async_db_session)
    await _seed_recaps(async_db_session)
    with _patched_broken_llm(), no_campaigns():
        await newsletter_schedule.prepare_monthly(async_db_session, NOW)
    [failed] = await _suggestions(async_db_session)
    items_before, built_at = failed.items, failed.created_at
    llm = CountingLlm()
    tuesday = NOW + datetime.timedelta(days=1)

    with _patched_llm(llm), no_campaigns(), structlog.testing.capture_logs() as logs:
        retried = await newsletter_schedule.prepare_monthly(async_db_session, tuesday)
        wednesday = await newsletter_schedule.prepare_monthly(
            async_db_session, NOW + datetime.timedelta(days=2)
        )

    assert retried["prepared"] is False and retried["summary_retried"] is True
    assert retried["summary"] is True and retried["summary_error"] is None
    assert wednesday == {"prepared": False, "period_start": "2026-10-01"}
    assert llm.calls == 1  # sekali untuk retry; hari berikutnya sehat, tidak ada LLM lagi
    [row] = await _suggestions(async_db_session)
    assert row.id == failed.id
    assert row.summary_text == REPLY
    assert row.summary_meta["error"] is None
    assert row.summary_meta["token_usage"]["total_tokens"] == 550
    assert row.items == items_before  # rankingnya tidak disentuh
    assert row.created_at == built_at
    assert [e["event"] for e in logs if e["event"].startswith("newsletter_")] == [
        "newsletter_summary_retried"  # bukan `newsletter_prepared`: tidak merangking ulang
    ]


async def test_a_summary_that_keeps_failing_is_retried_each_day_until_the_window_closes(
    async_db_session: AsyncSession,
) -> None:
    await _seed_articles(async_db_session)
    await _seed_recaps(async_db_session)

    with _patched_broken_llm(AuthenticationError(f"bad key {SECRET}")), no_campaigns():
        await newsletter_schedule.prepare_monthly(async_db_session, NOW)  # Senin 2 Nov
        retried = await newsletter_schedule.prepare_monthly(
            async_db_session, NOW + datetime.timedelta(days=1)
        )
        closed = await newsletter_schedule.prepare_monthly(
            async_db_session,
            NOW + datetime.timedelta(days=8),  # Selasa 10 Nov
        )

    assert retried["summary_retried"] is True
    assert retried["summary_error"] == "AuthenticationError (HTTP 401)"
    assert closed == {"prepared": False, "period_start": "2026-10-01"}  # sesudah jendela: manual


async def test_the_tail_of_november_is_recorded_as_uncovered(
    async_db_session: AsyncSession,
) -> None:
    """Edisi November disiapkan Selasa 1 Des 2026: pekan 30 Nov-6 Des belum selesai (belum ada
    recap-nya), jadi 30 Nov tidak masuk ringkasan dan tercatat di `uncovered`."""
    await AsyncClientRepo(async_db_session).ensure_default()
    await _seed_recaps(
        async_db_session,
        [D(2026, 10, 26), D(2026, 11, 2), D(2026, 11, 9), D(2026, 11, 16), D(2026, 11, 23)],
    )
    llm = CountingLlm("November.")
    december_first = datetime.datetime(2026, 12, 1, 2, 0, tzinfo=UTC)  # Selasa 09:00 WIB

    with _patched_llm(llm), no_campaigns():
        result = await newsletter_schedule.prepare_monthly(async_db_session, december_first)

    assert result["prepared"] is True and result["period_start"] == "2026-11-01"
    [row] = await _suggestions(async_db_session)
    assert row.summary_meta["uncovered"] == [{"start": "2026-11-30", "end": "2026-11-30"}]
    assert row.summary_meta["covered_end"] == "2026-11-29"


async def test_the_campaign_clusters_are_read_for_the_window_through_the_real_service(
    async_db_session: AsyncSession,
) -> None:
    """Pemanggilan sungguhan `get_recent_campaigns(start=, end=)`: tanpa stub `no_campaigns`."""
    await _seed_articles(async_db_session)

    campaigns = await newsletter_suggestion._campaigns(async_db_session, *OCTOBER)

    assert campaigns == []  # dua artikel Oktober tidak membentuk klaster berukuran 3


# --- rebuild lewat API --------------------------------------------------------------------------

_REBUILD = "/api/newsletter/suggestion/rebuild"


async def _rebuild(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    llm: CountingLlm,
) -> Any:
    with suggestion_clock(), no_campaigns(), _patched_llm(llm):
        return await api_client.post(_REBUILD, headers=auth_header(), json={})


async def test_rebuild_fills_the_summary_and_a_second_rebuild_regenerates_it(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_articles(api_session)
    await _seed_recaps(api_session, OCTOBER_WEEKS[:4])  # recap pekan 26 Okt belum ada
    llm = CountingLlm()

    first = await _rebuild(api_client, auth_header, llm)

    assert first.status_code == 200
    body = first.json()
    assert body["summary_text"] == REPLY
    assert len(body["summary_meta"]["weeks"]) == 4
    assert body["summary_meta"]["uncovered"] == [{"start": "2026-10-26", "end": "2026-10-31"}]
    assert llm.calls == 1

    # Recap Senin yang telat sudah ada: rebuild MENIMPA seluruh baris, ringkasan ikut dibuat ulang.
    await _seed_recaps(api_session, OCTOBER_WEEKS[4:])
    second = await _rebuild(api_client, auth_header, CountingLlm("Ringkasan kedua."))

    assert second.json()["id"] == body["id"]
    assert second.json()["summary_text"] == "Ringkasan kedua."
    assert len(second.json()["summary_meta"]["weeks"]) == 5
    assert second.json()["summary_meta"]["uncovered"] == []
    assert await api_session.scalar(select(func.count()).select_from(NewsletterSuggestion)) == 1
    got = await api_client.get("/api/newsletter/suggestion", headers=auth_header())
    assert got.json() == second.json()


async def test_rebuild_marks_an_invented_cve_id_in_the_stored_paragraph(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await _seed_articles(api_session)
    await _seed_recaps(api_session)

    resp = await _rebuild(
        api_client, auth_header, CountingLlm("Tercatat CVE-2026-1111 dan CVE-2026-9999.")
    )

    body = resp.json()
    assert body["summary_text"] == "Tercatat CVE-2026-1111 dan [CVE tidak terverifikasi]."
    assert body["summary_meta"]["dropped"] == [
        {"field": "summary", "value": "CVE-2026-9999", "reason": "not_in_input"}
    ]
    stored = await AsyncNewsletterRepo(api_session).get_suggestion(*OCTOBER)
    assert stored is not None and stored.summary_text == body["summary_text"]


async def test_rebuild_during_an_llm_outage_answers_200_with_the_ranking_and_the_error(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await _seed_articles(api_session)
    await _seed_recaps(api_session)

    with (
        suggestion_clock(),
        no_campaigns(),
        _patched_broken_llm(AuthenticationError(f"Incorrect API key provided: {SECRET}")),
    ):
        resp = await api_client.post(_REBUILD, headers=auth_header("rina"), json={})

    assert resp.status_code == 200
    body = resp.json()
    assert sorted(i["article_id"] for i in body["items"]) == sorted(ids[:2])
    assert body["summary_text"] == ""
    assert body["summary_meta"]["error"] == "AuthenticationError (HTTP 401)"
    assert SECRET not in resp.text  # nama kelas dan kode saja, tidak pernah pesan klien
    assert body["summary_meta"]["token_usage"] == {"skipped": True, "reason": "llm_error"}
    assert len(body["summary_meta"]["weeks"]) == 5
    entry = (
        await api_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.action == "rebuild_newsletter_suggestion")
        )
    ).scalar_one()
    assert entry.username == "rina" and entry.target_id == str(body["id"])
    stored = await AsyncNewsletterRepo(api_session).get_suggestion(*OCTOBER)
    assert stored is not None and stored.summary_meta["error"] == body["summary_meta"]["error"]
    assert SECRET not in json.dumps(stored.summary_meta)  # juga tidak di DB

    # gateway pulih: rebuild berikutnya mengisi ringkasan dan menghapus `error`
    healed = await _rebuild(api_client, auth_header, CountingLlm())
    assert healed.json()["id"] == body["id"]
    assert healed.json()["summary_text"] == REPLY
    assert healed.json()["summary_meta"]["error"] is None
