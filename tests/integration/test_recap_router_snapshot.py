"""Snapshot test `routers/recap.py` -- Fase 7.6 (lanjutan pola pilot
`test_cve_router_snapshot.py`). `recap_service._call_llm` di-mock, titik
sama kayak dipakai `_extract_json` (Fase 7.5) buat verifikasi kontrak."""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cti_api.services import recap as recap_service
from cti_core.db.repositories.auth import AsyncAuditLogRepo
from cti_core.db.repositories.recap import AsyncRecapRepo
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


# --- kualitas recap mingguan lewat API (#21, PR 3) --------------------------------------------

WEEK_BEFORE = "2026-02-23"

_WITH_TIMES = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?generated_at$": (str,),
        r"(.*\.)?input_chars$": (int,),
        r"(.*\.)?at$": (str,),  # waktu override analis
        # id artikel dari sequence autoincrement, yang TIDAK di-reset rollback antar test
        r"(.*\.)?article_id$": (int,),
    },
    regex=True,
    strict=False,
)


def _llm_reply(user_msg: str, system_prompt: str, *, task: str) -> tuple[str, str, dict[str, int]]:
    """Balasan yang disusun dari prompt yang diterima: story mengutip id artikel dari `[#id]`."""
    article_id = int(re.search(r"\[#(\d+)\] \[CISA\]", user_msg).group(1))  # type: ignore[union-attr]
    payload = {
        "headline": "Hospital week",
        "recap": {
            "summary": "One story, see CVE-2026-9999.",
            "top_stories": [
                {
                    "article_id": article_id,
                    "title": "Hospital hit",
                    "why_it_matters": "patients",
                    "source": "CISA",
                },
                {"article_id": 424242, "title": "Not a real article"},
            ],
        },
        "forecast": {
            "summary": "s",
            "likely_events": [{"event": "Another hit", "basis": "the story", "confidence": "high"}],
        },
        "forecast_review": [
            {"id": "f1", "verdict": "happened", "evidence": "The hospital story."},
            {"id": "f2", "verdict": "not_happened", "evidence": "Nothing seen."},
        ],
    }
    return json.dumps(payload), "test-model", _FAKE_LLM_USAGE


async def _two_weeks(
    api_client: AsyncClient, api_session: AsyncSession, headers: dict[str, str]
) -> dict[str, Any]:
    """Pekan 2 Maret dibuat lewat API dengan pekan 23 Feb (tanpa id event, tanpa `quality`: baris
    dari sebelum PR 3) di belakangnya, jadi scorecard-nya ada. Mengembalikan dokumen pekan itu."""
    await _seed_one_article_in_the_week(api_session)
    await AsyncRecapRepo(api_session).upsert(
        WEEK_BEFORE,
        kind="weekly",
        period_start=datetime.date(2026, 2, 23),
        period_end=datetime.date(2026, 3, 1),
        headline="last week",
        forecast={
            "likely_events": [
                {"event": "Ransomware wave continues", "basis": "hits", "confidence": "high"},
                {"event": "VPN exploitation grows", "basis": "PoC", "confidence": "med"},
            ]
        },
        counts={"articles": 0, "tweets": 0, "iocs": 0, "cves": 0, "campaigns": 0},
    )
    with patch.object(recap_service, "_call_llm", MagicMock(side_effect=_llm_reply)):
        resp = await api_client.post(
            "/api/recap/generate", headers=headers, params={"kind": "weekly", "week_start": WEEK}
        )
    assert resp.status_code == 200
    recap: dict[str, Any] = resp.json()["recap"]
    return recap


async def test_a_weekly_recap_returns_its_quality_with_grounding_comparison_and_scorecard(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    recap = await _two_weeks(api_client, api_session, auth_header())

    assert set(recap["quality"]) == {"grounding", "comparison", "scorecard"}
    assert recap["yesterday"]["top_stories"][0]["url"] == "https://example.com/weekly-router"
    assert recap == snapshot(matcher=_WITH_TIMES)


async def test_latest_and_the_weekly_read_carry_the_hit_rate_and_a_daily_read_does_not(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    headers = auth_header()
    await _two_weeks(api_client, api_session, headers)

    latest = await api_client.get("/api/recap/latest", headers=headers)
    weekly = await api_client.get(f"/api/recap/{WEEK}", headers=headers, params={"kind": "weekly"})

    assert latest.json()["hit_rate"] == weekly.json()["hit_rate"]
    assert latest.json()["recap"]["quality"] == weekly.json()["recap"]["quality"]
    assert latest.json()["hit_rate"] == snapshot
    # Satu event "happened" (high), satu "not_happened" (med); keduanya dinilai model.
    rates = {k: v["rate_pct"] for k, v in latest.json()["hit_rate"]["by_confidence"].items()}
    assert rates == {"low": None, "med": 0.0, "high": 100.0}

    # Recap harian di Senin yang sama tidak punya scorecard: balasannya tetap `{"recap": ...}`.
    with patch.object(
        recap_service,
        "_call_llm",
        MagicMock(return_value=(_FAKE_LLM_RESPONSE, "test-model", _FAKE_LLM_USAGE)),
    ):
        await api_client.post("/api/recap/generate", headers=headers, params={"date": WEEK})
    daily = await api_client.get(f"/api/recap/{WEEK}", headers=headers)
    assert set(daily.json()) == {"recap"}
    assert daily.json()["recap"]["quality"] == {}


async def test_the_hit_rate_is_empty_but_present_before_any_weekly_recap_exists(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/recap/latest", headers=auth_header())

    body = resp.json()
    assert body["recap"] is None
    assert (body["hit_rate"]["weeks"], body["hit_rate"]["overall"]["rate_pct"]) == (0, None)


async def test_an_analyst_override_is_saved_audited_and_changes_the_hit_rate(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    headers = auth_header("analyst1", role="analyst")
    # Generate butuh `manage_intel` (memanggil LLM); override verdict cukup untuk analyst.
    week = await _two_weeks(api_client, api_session, auth_header())

    resp = await api_client.patch(
        f"/api/recap/{week['id']}/scorecard/f2", headers=headers, json={"verdict": "happened"}
    )

    assert resp.status_code == 200
    body = resp.json()
    f1, f2 = body["recap"]["quality"]["scorecard"]["events"]
    assert (f2["verdict"], f2["override"]["verdict"], f2["override"]["by"]) == (
        "not_happened",  # verdict model tetap di tempatnya
        "happened",
        "analyst1",
    )
    assert "override" not in f1
    assert body["hit_rate"]["by_confidence"]["med"]["rate_pct"] == 100.0  # sebelumnya 0.0
    assert body == snapshot(matcher=_WITH_TIMES)
    # Tersimpan: dibaca ulang lewat GET.
    again = await api_client.get(f"/api/recap/{WEEK}", headers=headers, params={"kind": "weekly"})
    assert (
        again.json()["recap"]["quality"]["scorecard"]["events"][1]["override"]["by"] == "analyst1"
    )
    assert again.json()["hit_rate"] == body["hit_rate"]
    # Audit log, seperti `generate`.
    [entry], total = await AsyncAuditLogRepo(api_session).query(action="override_recap_scorecard")
    assert total == 1
    assert (entry.username, entry.target_id) == ("analyst1", str(week["id"]))
    assert entry.detail == {
        "week_start": WEEK,
        "event_id": "f2",
        "verdict": "happened",
        "model_verdict": "not_happened",
    }


async def test_a_second_override_replaces_the_first_and_each_one_is_audited(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    headers = auth_header()
    week = await _two_weeks(api_client, api_session, headers)
    url = f"/api/recap/{week['id']}/scorecard/f1"

    await api_client.patch(url, headers=headers, json={"verdict": "partly"})
    resp = await api_client.patch(url, headers=auth_header("other"), json={"verdict": "unclear"})

    f1 = resp.json()["recap"]["quality"]["scorecard"]["events"][0]
    assert (f1["override"]["verdict"], f1["override"]["by"]) == ("unclear", "other")
    assert resp.json()["hit_rate"]["by_confidence"]["high"]["rate_pct"] is None  # keluar penyebut
    _, total = await AsyncAuditLogRepo(api_session).query(action="override_recap_scorecard")
    assert total == 2


@pytest.mark.parametrize(
    ("target", "status", "detail"),
    [
        ("missing", 404, "No recap with id"),
        ("no_scorecard", 404, "has no forecast scorecard"),
        ("no_event", 404, "has no scorecard entry f9"),
    ],
)
async def test_overriding_something_that_does_not_exist_is_a_404_and_is_not_audited(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    target: str,
    status: int,
    detail: str,
) -> None:
    headers = auth_header()
    week = await _two_weeks(api_client, api_session, headers)
    before = await api_client.get(
        f"/api/recap/{WEEK_BEFORE}", headers=headers, params={"kind": "weekly"}
    )
    recap_id, event = {
        "missing": (10**9, "f1"),
        "no_scorecard": (before.json()["recap"]["id"], "f1"),  # pekan pertama: tanpa scorecard
        "no_event": (week["id"], "f9"),
    }[target]

    resp = await api_client.patch(
        f"/api/recap/{recap_id}/scorecard/{event}", headers=headers, json={"verdict": "happened"}
    )

    assert resp.status_code == status
    assert detail in resp.json()["detail"]
    _, total = await AsyncAuditLogRepo(api_session).query(action="override_recap_scorecard")
    assert total == 0


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/recap/1/scorecard/f1", {"verdict": "mostly"}),  # bukan salah satu dari empat verdict
        ("/api/recap/1/scorecard/f1", {}),
        ("/api/recap/1/scorecard/f1", {"verdict": None}),
        ("/api/recap/not-a-number/scorecard/f1", {"verdict": "happened"}),
    ],
)
async def test_a_bad_override_request_is_rejected_before_anything_is_read(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    path: str,
    body: dict[str, Any],
) -> None:
    resp = await api_client.patch(path, headers=auth_header(), json=body)

    assert resp.status_code == 422


async def test_overriding_needs_a_login_like_generating_does(
    api_client: AsyncClient, api_session: AsyncSession
) -> None:
    resp = await api_client.patch("/api/recap/1/scorecard/f1", json={"verdict": "happened"})

    assert resp.status_code == 401
