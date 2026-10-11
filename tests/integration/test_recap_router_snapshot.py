"""Snapshot test `routers/recap.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`). `recap_service._call_llm` di-mock, titik
sama kayak dipakai `_extract_json` (Fase 7.5) buat verifikasi kontrak."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from cti_api.services import recap as recap_service
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

pytestmark = pytest.mark.asyncio

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?generated_at$": (str,),
        # `/latest` dan `/generate` balikin "yesterday" relatif ke hari
        # jalan test (routers/recap.py), bukan tanggal tetap -- literal
        # ke-bake di snapshot bakal basi tiap hari kalender maju. Rentang periode recap harian
        # (= tanggal itu) sama.
        r"(.*\.)?(date|period_start|period_end)$": (str,),
        # Panjang pesan user = panjang template prompt; tanpa ini snapshot ikut berubah setiap kali
        # teks prompt diedit, padahal yang dijaga di sini bentuk `token_usage`.
        r"(.*\.)?input_chars$": (int,),
    },
    regex=True,
    strict=False,
)

_FAKE_LLM_RESPONSE = (
    '{"headline": "Quiet day", "recap": {"summary": "No major incidents."}, '
    '"forecast": {"outlook": "stable"}}'
)
_FAKE_LLM_USAGE = {
    "prompt_tokens": 100,
    "completion_tokens": 20,
    "total_tokens": 120,
    "wall_ms": 7,
}


def _yesterday() -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)).strftime("%Y-%m-%d")


async def test_recap_list_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/recap/list", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_recap_latest_none(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/recap/latest", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


async def test_recap_get_not_found(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/recap/2026-01-01", headers=auth_header())
    assert resp.status_code == 404
    assert resp.json() == snapshot


async def test_recap_generate(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    with patch.object(
        recap_service,
        "_call_llm",
        MagicMock(return_value=(_FAKE_LLM_RESPONSE, "test-model", _FAKE_LLM_USAGE)),
    ):
        resp = await api_client.post(
            "/api/recap/generate", headers=auth_header(), params={"date": _yesterday()}
        )
    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_NORMALIZE)


# --- recap MINGGUAN lewat API (#21, PR 2) ---------------------------------------------------------

WEEK = "2026-03-02"
"""Senin jauh di masa lalu: pekannya (2-8 Maret) sudah selesai kapan pun test dijalankan, jadi
tanggal boleh literal di snapshot (beda dengan recap harian, yang "kemarin" relatif)."""

_FIXED_DATES = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?generated_at$": (str,),
        r"(.*\.)?input_chars$": (int,),
    },
    regex=True,
    strict=False,
)


async def _seed_one_article_in_the_week(session: AsyncSession) -> None:
    from cti_core.db.repositories.article import AsyncArticleRepo

    await AsyncArticleRepo(session).upsert(
        url="https://example.com/weekly-router",
        title="Ransomware gang hits regional hospital network",
        source="CISA",
        posted_on=datetime.date(2026, 3, 3),
        confidence_score=70,
    )


async def test_recap_generate_weekly_without_activity_makes_no_llm_call(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    boom = MagicMock(side_effect=AssertionError("LLM must not be called for a quiet week"))
    with patch.object(recap_service, "_call_llm", boom):
        resp = await api_client.post(
            "/api/recap/generate",
            headers=auth_header(),
            params={"kind": "weekly", "week_start": WEEK},
        )

    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_FIXED_DATES)


async def test_recap_generate_weekly_with_activity_calls_the_llm_with_the_weekly_prompt(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_one_article_in_the_week(api_session)
    llm = MagicMock(return_value=(_FAKE_LLM_RESPONSE, "test-model", _FAKE_LLM_USAGE))
    with patch.object(recap_service, "_call_llm", llm):
        resp = await api_client.post(
            "/api/recap/generate",
            headers=auth_header(),
            params={"kind": "weekly", "week_start": WEEK},
        )

    assert resp.status_code == 200
    assert resp.json() == snapshot(matcher=_FIXED_DATES)
    user_msg, system_prompt = llm.call_args.args
    assert system_prompt == recap_service.WEEKLY_SYSTEM_PROMPT
    assert "2026-03-02 (Monday) to 2026-03-08 (Sunday)" in user_msg


@pytest.mark.parametrize(
    ("params", "status", "detail"),
    [
        ({"kind": "weekly", "week_start": "2026-03-03"}, 400, "week_start must be a Monday"),
        ({"kind": "weekly", "week_start": "nope"}, 400, "week_start must be YYYY-MM-DD"),
        ({"kind": "weekly", "date": WEEK}, 400, "date is for kind=daily"),
        ({"kind": "daily", "week_start": WEEK}, 400, "week_start is for kind=weekly"),
        ({"kind": "daily", "date": "nope"}, 400, "date must be YYYY-MM-DD"),
        ({"kind": "monthly"}, 422, None),
    ],
)
async def test_recap_generate_rejects_bad_kind_and_date_combinations(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    params: dict[str, str],
    status: int,
    detail: str | None,
) -> None:
    boom = MagicMock(side_effect=AssertionError("rejected requests must not reach the LLM"))
    with patch.object(recap_service, "_call_llm", boom):
        resp = await api_client.post("/api/recap/generate", headers=auth_header(), params=params)

    assert resp.status_code == status
    if detail:
        assert detail in resp.json()["detail"]


async def test_recap_generate_weekly_refuses_a_week_that_has_not_ended_in_utc(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    """Senin pekan INI: Minggunya paling cepat hari ini, jadi belum selesai kapan pun test jalan."""
    today = datetime.datetime.now(datetime.UTC).date()
    this_monday = today - datetime.timedelta(days=today.weekday())
    boom = MagicMock(side_effect=AssertionError("must be refused before any LLM call"))

    with patch.object(recap_service, "_call_llm", boom):
        resp = await api_client.post(
            "/api/recap/generate",
            headers=auth_header(),
            params={"kind": "weekly", "week_start": this_monday.isoformat(), "force": "true"},
        )

    assert resp.status_code == 400
    assert "not finished yet" in resp.json()["detail"]
    stored = await api_client.get(
        f"/api/recap/{this_monday.isoformat()}", headers=auth_header(), params={"kind": "weekly"}
    )
    assert stored.status_code == 404  # tidak ada pekan bolong yang tersimpan


async def test_recap_reads_distinguish_weekly_from_daily_on_the_same_monday(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    await _seed_one_article_in_the_week(api_session)
    headers = auth_header()
    llm = MagicMock(return_value=(_FAKE_LLM_RESPONSE, "test-model", _FAKE_LLM_USAGE))

    missing = await api_client.get(f"/api/recap/{WEEK}", headers=headers, params={"kind": "weekly"})
    assert (missing.status_code, missing.json()) == (404, {"detail": f"No weekly recap for {WEEK}"})

    with patch.object(recap_service, "_call_llm", llm):
        await api_client.post(
            "/api/recap/generate", headers=headers, params={"kind": "weekly", "week_start": WEEK}
        )
        # Senin yang sama, jenis lain: dulu bentrok (unik di `date`) dan `get` jadi 500.
        await api_client.post("/api/recap/generate", headers=headers, params={"date": WEEK})

    weekly = await api_client.get(f"/api/recap/{WEEK}", headers=headers, params={"kind": "weekly"})
    daily = await api_client.get(f"/api/recap/{WEEK}", headers=headers)
    assert weekly.json()["recap"]["kind"] == "weekly"
    assert (weekly.json()["recap"]["period_start"], weekly.json()["recap"]["period_end"]) == (
        WEEK,
        "2026-03-08",
    )
    assert daily.json()["recap"]["kind"] == "daily"
    assert daily.json()["recap"]["period_end"] == WEEK
    assert weekly.json()["recap"]["id"] != daily.json()["recap"]["id"]

    listing = await api_client.get("/api/recap/list", headers=headers)
    assert listing.json() == snapshot(matcher=_FIXED_DATES)

    latest = await api_client.get("/api/recap/latest", headers=headers)
    assert latest.json()["recap"]["id"] == weekly.json()["recap"]["id"]  # yang MINGGUAN
    assert (latest.json()["kind"], latest.json()["date"]) == ("weekly", WEEK)


async def test_recap_generate_writes_an_audit_entry_per_kind(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    from cti_core.db.repositories.auth import AsyncAuditLogRepo

    headers = auth_header()
    llm = MagicMock(return_value=(_FAKE_LLM_RESPONSE, "test-model", _FAKE_LLM_USAGE))
    with patch.object(recap_service, "_call_llm", llm):
        await api_client.post(
            "/api/recap/generate", headers=headers, params={"kind": "weekly", "week_start": WEEK}
        )
        await api_client.post("/api/recap/generate", headers=headers, params={"date": WEEK})

    repo = AsyncAuditLogRepo(api_session)
    [weekly], _ = await repo.query(action="generate_weekly_recap")
    [daily], _ = await repo.query(action="generate_daily_recap")
    assert weekly.username == "tester"
    assert weekly.detail == {"week_start": WEEK, "period_end": "2026-03-08", "force": False}
    assert daily.detail == {"date": WEEK, "force": False}
