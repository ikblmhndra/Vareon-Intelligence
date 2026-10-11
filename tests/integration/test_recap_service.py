"""Integration test `cti_api.services.recap` -- Postgres REAL
(testcontainers), panggilan LLM di-mock (`unittest.mock.patch`, sama
pola kayak `tests/unit/test_mailer.py`) -- verifikasi LIVE terhadap LLM
gateway beneran dilakuin terpisah, bukan bagian suite otomatis ini.
Fase 7.3 (router `recap`, Bagian 5)."""

from __future__ import annotations

import contextlib
import datetime
import json
import re
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import structlog
from cti_api.services import recap as recap_service
from cti_core.db.engine import get_async_engine
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.ioc import IOC
from cti_core.db.models.threat_reference import ThreatActorGroup
from cti_core.db.models.tweet import Tweet
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.ta import AsyncTARepo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.datetime.now(datetime.UTC).date()
"""UTC, bukan tanggal lokal mesin -- `IOC.first_seen_at` (app-set lewat
`datetime.datetime.now(datetime.UTC)`, lihat `AsyncIOCRepo.upsert()`),
`CveTracker.detected_on`, dan `ThreatActorGroup.created_at` (keduanya
`server_default=func.now()` Postgres) semua ke-stamp jam UTC. Tanggal
lokal (WIB/UTC+7) beda sama tanggal UTC di jendela ~00:00-07:00 WIB,
bikin `test_collect_iocs_and_cves_and_new_tas` flaky di jam segitu."""


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


async def test_collect_articles_sorted_by_reliability(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    await repo.upsert(
        url="https://x.com/a", title="from a tabloid", source="Vice", posted_on=_TODAY
    )
    await repo.upsert(url="https://x.com/b", title="from CISA", source="CISA", posted_on=_TODAY)

    articles = await recap_service._collect_articles(async_db_session, _TODAY)
    assert [a.source for a in articles] == ["CISA", "Vice"]


async def test_collect_iocs_and_cves_and_new_tas(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await AsyncIOCRepo(async_db_session).upsert(
        type="ip", value="203.0.113.5", source_url="https://x.com/ioc", source_name="s"
    )
    async_db_session.add(
        CveTracker(cve_id="CVE-2026-7777", client_id="default", tech="nginx", registered_date=None)
    )
    await AsyncTARepo(async_db_session).add_group("Apt41")
    await async_db_session.flush()

    iocs = await recap_service._collect_iocs(async_db_session, _TODAY)
    assert len(iocs) == 1

    cves = await recap_service._collect_cves(async_db_session, _TODAY)
    assert any(c.cve_id == "CVE-2026-7777" for c in cves)

    new_tas = await recap_service._collect_new_threat_actors(async_db_session, _TODAY)
    assert any(t.name == "Apt41" for t in new_tas)


async def test_collect_campaigns_empty_db_returns_empty(async_db_session: AsyncSession) -> None:
    """Fase 7.4 Grup A -- `_collect_campaigns()` manggil pipeline
    beneran sekarang, bukan stub. DB kosong (< 2 artikel) -> `[]` lewat
    `get_recent_campaigns()`'s guard sendiri, bukan lagi stub statis."""
    assert await recap_service._collect_campaigns(async_db_session) == []


async def test_collect_campaigns_maps_fields_for_build_user_message(
    async_db_session: AsyncSession,
) -> None:
    """Regression buat bug legacy DITEMUKAN & DIPERBAIKI (lihat docstring
    modul) -- `_collect_campaigns()` HARUS ngirim key `theme`/
    `article_ids`/`threat_actors` (bukan `cluster_name`/
    `member_article_ids`/`dominant_tas` mentah dari `get_recent_
    campaigns()`), soalnya itu yang dibaca `_build_user_message()`."""
    await _ensure_clients(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    # `_collect_campaigns()` manggil `get_recent_campaigns(min_size=3)`
    # (hardcoded, port apa adanya) -- butuh MINIMAL 3 artikel se-cluster.
    titles = [
        "Apt41 hits target one today",
        "Apt41 hits target two today",
        "Apt41 hits target three today",
    ]
    for i, title in enumerate(titles):
        a = await repo.upsert(
            url=f"https://example.com/recap-campaign-{i}",
            title=title,
            source=f"S{i}",
            posted_on=_TODAY,
        )
        await repo.set_enrichment(a, threat_actors=["Apt41"])

    campaigns = await recap_service._collect_campaigns(async_db_session)
    assert len(campaigns) == 1
    assert campaigns[0]["theme"]
    assert campaigns[0]["size"] == 3
    assert campaigns[0]["threat_actors"] == ["Apt41"]
    assert len(campaigns[0]["article_ids"]) == 3

    # `_build_user_message()` HARUS nampilin nama campaign + actor,
    # BUKAN "(unlabeled) — 0 articles" (bug lama).
    msg = recap_service._build_user_message(_TODAY.isoformat(), [], [], [], [], campaigns, [])
    assert "(unlabeled) — 0 articles" not in msg
    assert "Apt41" in msg


def _fake_completion(content: str, usage: SimpleNamespace | None = None) -> SimpleNamespace:
    """`usage=None` (bawaan) meniru gateway dev yang membuang `usage`."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=usage
    )


async def test_generate_daily_recap_caches_and_force_regenerates(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    fake_json = json.dumps(
        {
            "headline": "quiet day",
            "recap": {"summary": "nothing much happened"},
            "forecast": {"summary": "stay calm"},
        }
    )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: _fake_completion(fake_json))
        )
    )

    with patch.object(recap_service, "get_llm_client", return_value=(fake_client, "test-model")):
        date_iso = _TODAY.isoformat()
        first = await recap_service.generate_daily_recap(async_db_session, date=date_iso)
        assert first["headline"] == "quiet day"
        assert first["cached"] is False
        assert first["model"] == "test-model"

        second = await recap_service.generate_daily_recap(async_db_session, date=date_iso)
        assert second["cached"] is True
        assert second["id"] == first["id"]

        third = await recap_service.generate_daily_recap(
            async_db_session, date=date_iso, force=True
        )
        assert third["cached"] is False
        assert third["id"] == first["id"]


async def test_generate_daily_recap_handles_malformed_llm_json(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kw: _fake_completion("not valid json at all")
            )
        )
    )

    with patch.object(recap_service, "get_llm_client", return_value=(fake_client, "test-model")):
        result = await recap_service.generate_daily_recap(
            async_db_session, date="2026-08-01", force=True
        )
    assert result["headline"] == ""
    assert result["raw_llm"] == "not valid json at all"


_QUIET_JSON = json.dumps(
    {"headline": "quiet day", "recap": {"summary": "nothing"}, "forecast": {"summary": "calm"}}
)


def _capturing_client(sent: list[dict[str, Any]], usage: SimpleNamespace | None) -> SimpleNamespace:
    """Client LLM palsu yang menyimpan argumen tiap panggilan di `sent`; pesan user-nya ada di
    `sent[0]["messages"][1]["content"]`."""

    def create(**kw: Any) -> SimpleNamespace:
        sent.append(kw)
        return _fake_completion(_QUIET_JSON, usage)

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


async def _generate_today(
    session: AsyncSession, client: SimpleNamespace, **caps: int
) -> dict[str, Any]:
    """`generate_daily_recap` hari ini dengan client palsu; `caps` mengecilkan batas `_MAX_*`."""
    with (
        patch.object(recap_service, "get_llm_client", return_value=(client, "test-model")),
        patch.multiple(recap_service, **caps) if caps else contextlib.nullcontext(),
    ):
        return await recap_service.generate_daily_recap(session, date=_TODAY.isoformat())


async def test_generate_daily_recap_records_usage_wall_time_and_prompt_size(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    titles = ["Ransomware hits a hospital", "Zero-day in a VPN appliance", "Phishing kit for banks"]
    for i, title in enumerate(titles):
        await repo.upsert(url=f"https://x.com/u{i}", title=title, source="CISA", posted_on=_TODAY)
    sent: list[dict[str, Any]] = []
    usage = SimpleNamespace(prompt_tokens=1200, completion_tokens=300, total_tokens=1500)

    # Jam palsu hanya di modul `recap` (bukan `time.monotonic` global, itu dipakai event loop):
    # `_call_llm` membaca jam dua kali, sebelum dan sesudah panggilan API, jadi 0,25 s = 250 ms
    # terkunci pasti tanpa sleep, dan satuannya (detik -> ms, bilangan bulat) ikut teruji.
    ticks = iter([100.0, 100.25])
    fake_time = SimpleNamespace(monotonic=lambda: next(ticks))
    # `_MAX_ARTICLES` dikecilkan: yang dicatat harus yang BENAR-BENAR masuk prompt (2), bukan
    # total yang dikumpulkan (3, tetap utuh di `counts`).
    with patch.object(recap_service, "time", fake_time):
        result = await _generate_today(
            async_db_session, _capturing_client(sent, usage), _MAX_ARTICLES=2
        )

    user_msg = sent[0]["messages"][1]["content"]
    stored = result["token_usage"]
    assert {k: stored[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")} == {
        "prompt_tokens": 1200,
        "completion_tokens": 300,
        "total_tokens": 1500,
    }
    assert stored["wall_ms"] == 250
    assert stored["input_chars"] == len(user_msg)
    assert stored["prompt_items"] == {
        "articles": 2,
        "tweets": 0,
        "cves": 0,
        "iocs": 0,
        "campaigns": 0,
        "new_threat_actors": 0,
    }
    assert result["counts"]["articles"] == 3
    assert len(re.findall(r"^- \[", user_msg, flags=re.MULTILINE)) == 2


async def test_generate_daily_recap_without_gateway_usage_still_records_prompt_size(
    async_db_session: AsyncSession,
) -> None:
    """Gateway dev kadang membuang `usage`: tidak ada angka token yang dikarang, tetapi ukuran
    prompt dan waktu tetap tercatat (itu satu-satunya ukuran yang tersisa)."""
    await _ensure_clients(async_db_session)
    sent: list[dict[str, Any]] = []

    result = await _generate_today(async_db_session, _capturing_client(sent, usage=None))

    stored = result["token_usage"]
    assert set(stored) == {"wall_ms", "input_chars", "prompt_items"}
    assert stored["input_chars"] == len(sent[0]["messages"][1]["content"])


def _cve(cve_id: str, client_id: str = "default", **fields: Any) -> CveTracker:
    """Baris tracker yang masuk recap hari ini lewat `published`."""
    return CveTracker(cve_id=cve_id, client_id=client_id, published=_TODAY, **fields)


async def test_generate_daily_recap_counts_a_cve_tracked_by_two_clients_once(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    await AsyncClientRepo(async_db_session).create(client_id="acme", name="Acme", countries=[])
    async_db_session.add_all([_cve("CVE-2026-0001", "default"), _cve("CVE-2026-0001", "acme")])
    await async_db_session.flush()
    sent: list[dict[str, Any]] = []

    result = await _generate_today(async_db_session, _capturing_client(sent, usage=None))

    assert result["counts"]["cves"] == 1
    assert result["token_usage"]["prompt_items"]["cves"] == 1
    assert sent[0]["messages"][1]["content"].count("- CVE-2026-0001 (") == 1


async def test_generate_daily_recap_prompt_keeps_the_strongest_cves(
    async_db_session: AsyncSession,
) -> None:
    """Prompt memuat N CVE PERTAMA menurut urutan KEV -> PoC -> CVSS; CVSS tertinggi saja tidak
    cukup untuk lolos."""
    await _ensure_clients(async_db_session)
    async_db_session.add_all(
        [
            _cve("CVE-2026-0001", cve_score=9.9),
            _cve("CVE-2026-0002", cisa_kev=True),
            _cve("CVE-2026-0003", poc_available=True),
        ]
    )
    await async_db_session.flush()
    sent: list[dict[str, Any]] = []

    result = await _generate_today(
        async_db_session, _capturing_client(sent, usage=None), _MAX_CVES=2
    )

    user_msg = sent[0]["messages"][1]["content"]
    assert user_msg.index("- CVE-2026-0002 (") < user_msg.index("- CVE-2026-0003 (")
    assert "CVE-2026-0001 (" not in user_msg
    assert result["counts"]["cves"] == 3
    assert result["token_usage"]["prompt_items"]["cves"] == 2


# --- recap MINGGUAN (#21, PR 2) ------------------------------------------------------------------

WEEK_START = datetime.date(2026, 3, 2)
WEEK_END = datetime.date(2026, 3, 8)
FRIDAY = datetime.date(2026, 3, 6)
MONDAY_AFTER = datetime.date(2026, 3, 9)
"""Pekan Senin-Minggu jauh di masa lalu: jendela "7 hari dari hari ini" milik kode harian tidak
pernah menyentuhnya, jadi hasil tidak bergantung pada kapan test dijalankan."""


def _on(day: datetime.date, hour: int = 12) -> datetime.datetime:
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=datetime.UTC)


def _no_llm() -> Any:
    """Patch yang menggagalkan test kalau LLM dipanggil."""
    return patch.object(
        recap_service, "get_llm_client", side_effect=AssertionError("LLM must not be called")
    )


async def _generate_weekly(
    session: AsyncSession,
    client: SimpleNamespace,
    week_start: datetime.date | None = WEEK_START,
    force: bool = False,
    **caps: int,
) -> dict[str, Any]:
    with (
        patch.object(recap_service, "get_llm_client", return_value=(client, "test-model")),
        patch.multiple(recap_service, **caps) if caps else contextlib.nullcontext(),
    ):
        return await recap_service.generate_weekly_recap(session, week_start, force)


def _today(monkeypatch: pytest.MonkeyPatch, day: datetime.date) -> None:
    monkeypatch.setattr(recap_service, "_today_utc", lambda: day)


async def _seed_busy_week(session: AsyncSession) -> None:
    """Pekan 2-8 Maret: 5 artikel (judul sengaja berbeda jauh, supaya tidak jadi klaster), 3
    tweet, 4 CVE, 3 IOC, 2 threat actor baru; plus satu artikel/tweet/CVE sehari SEBELUM dan
    sesudahnya yang tidak boleh ikut."""
    await _ensure_clients(session)
    repo = AsyncArticleRepo(session)
    titles = [
        "Ransomware gang hits regional hospital network",
        "Zero-day exploited in VPN appliance firmware",
        "Phishing kit impersonates retail banks",
        "Botnet takedown announced by law enforcement",
        "Supply chain compromise found in npm package",
    ]
    for i, title in enumerate(titles):
        await repo.upsert(
            url=f"https://x.com/week-{i}",
            title=title,
            source="CISA",
            posted_on=WEEK_START + datetime.timedelta(days=i + 1),  # Selasa..Sabtu
            confidence_score=50 + i,
        )
    for slug, day in [("before", WEEK_START - datetime.timedelta(days=1)), ("after", MONDAY_AFTER)]:
        await repo.upsert(
            url=f"https://x.com/{slug}", title=f"outside {slug}", source="CISA", posted_on=day
        )
    for i in range(3):
        session.add(_week_tweet(i, _on(WEEK_START + datetime.timedelta(days=i))))
    session.add(_week_tweet(9, _on(MONDAY_AFTER, 0)))
    for n, day in enumerate([WEEK_START, WEEK_START, FRIDAY, WEEK_END], start=1):
        session.add(
            CveTracker(cve_id=f"CVE-2026-{n:04d}", client_id="default", published=day, cve_score=n)
        )
    session.add(CveTracker(cve_id="CVE-2026-0099", client_id="default", published=MONDAY_AFTER))
    for ioc_type, value in [("ip", "203.0.113.1"), ("ip", "203.0.113.2"), ("domain", "a.example")]:
        session.add(IOC(type=ioc_type, value=value, first_seen_at=_on(FRIDAY)))
    for name in ("Apt41", "Lazarus"):
        session.add(ThreatActorGroup(name=name, created_at=_on(WEEK_END)))
    await session.flush()


def _week_tweet(n: int, posted: datetime.datetime) -> Tweet:
    return Tweet(
        tweet_id=str(n),
        url=f"https://x.com/u/status/{n}",
        text=f"tweet {n}",
        author_username="u",
        posted_on=posted,
        incident_confidence=10 * n,
    )


async def test_generate_weekly_recap_summarises_the_whole_week_from_aggregates(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _today(monkeypatch, MONDAY_AFTER)
    await _seed_busy_week(async_db_session)
    sent: list[dict[str, Any]] = []
    usage = SimpleNamespace(prompt_tokens=900, completion_tokens=200, total_tokens=1100)

    result = await _generate_weekly(
        async_db_session,
        _capturing_client(sent, usage),
        _WEEKLY_MAX_ARTICLES=3,
        _WEEKLY_MAX_CVES=2,
    )

    assert (result["kind"], result["cached"], result["model"]) == ("weekly", False, "test-model")
    assert (result["date"], result["period_start"], result["period_end"]) == (
        "2026-03-02",
        "2026-03-02",
        "2026-03-08",
    )
    # `counts` = total SEBENARNYA walau daftar di prompt dipotong, dan yang di luar pekan tak ikut.
    assert result["counts"] == {
        "articles": 5,
        "tweets": 3,
        "iocs": 3,
        "cves": 4,
        "campaigns": 0,
        "new_threat_actors": 2,
    }
    stored = result["token_usage"]
    assert stored["prompt_items"] == {
        "articles": 3,
        "tweets": 3,
        "cves": 2,
        "iocs": 3,
        "campaigns": 0,
        "new_threat_actors": 2,
    }
    assert {k: stored[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")} == {
        "prompt_tokens": 900,
        "completion_tokens": 200,
        "total_tokens": 1100,
    }
    system_msg, user_msg = (m["content"] for m in sent[0]["messages"])
    assert system_msg == recap_service.WEEKLY_SYSTEM_PROMPT
    assert stored["input_chars"] == len(user_msg)
    assert "2026-03-02 (Monday) to 2026-03-08 (Sunday)" in user_msg
    assert "(5 total, 3 strongest shown;" in user_msg
    assert "(4 total, 2 strongest shown;" in user_msg
    assert "ip=2, domain=1" in user_msg
    assert "outside before" not in user_msg and "outside after" not in user_msg
    # Dua CVE teratas menurut urutan (CVSS menurun karena tak ada KEV/PoC).
    assert user_msg.index("- CVE-2026-0004 (") < user_msg.index("- CVE-2026-0003 (")
    assert "CVE-2026-0002 (" not in user_msg and "CVE-2026-0099" not in user_msg
    # Tweet terkuat (incident_confidence terbesar) di atas.
    assert user_msg.index("tweet 2") < user_msg.index("tweet 1") < user_msg.index("tweet 0")


async def test_weekly_recap_is_cached_per_week_and_coexists_with_a_daily_one_on_the_same_monday(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _today(monkeypatch, MONDAY_AFTER)
    await _seed_busy_week(async_db_session)
    sent: list[dict[str, Any]] = []
    client = _capturing_client(sent, usage=None)

    first = await _generate_weekly(async_db_session, client)
    second = await _generate_weekly(async_db_session, client)
    forced = await _generate_weekly(async_db_session, client, force=True)

    assert (second["cached"], second["id"]) == (True, first["id"])
    assert (forced["cached"], forced["id"]) == (False, first["id"])
    assert len(sent) == 2  # cache hit tidak memanggil LLM

    with patch.object(recap_service, "get_llm_client", return_value=(client, "test-model")):
        daily = await recap_service.generate_daily_recap(async_db_session, date="2026-03-02")
    assert (daily["kind"], daily["period_start"], daily["period_end"]) == (
        "daily",
        "2026-03-02",
        "2026-03-02",
    )
    assert daily["id"] != first["id"]
    assert (await recap_service.get_recap(async_db_session, "2026-03-02"))["id"] == daily["id"]  # type: ignore[index]
    weekly = await recap_service.get_recap(async_db_session, "2026-03-02", "weekly")
    assert weekly is not None and weekly["id"] == first["id"]
    assert (await recap_service.get_latest_recap(async_db_session, "weekly"))["id"] == first["id"]  # type: ignore[index]
    listed = await recap_service.list_recaps(async_db_session)
    assert [(r["kind"], r["period_start"], r["period_end"]) for r in listed] == [
        ("weekly", "2026-03-02", "2026-03-08"),
        ("daily", "2026-03-02", "2026-03-02"),
    ]


async def test_a_week_without_articles_tweets_or_cves_makes_no_llm_call_and_stores_a_plain_result(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _today(monkeypatch, MONDAY_AFTER)
    await _ensure_clients(async_db_session)
    # IOC dan threat actor baru saja bukan aktivitas yang layak dirangkum, tapi tetap terhitung.
    async_db_session.add(IOC(type="ip", value="203.0.113.1", first_seen_at=_on(FRIDAY)))
    async_db_session.add(ThreatActorGroup(name="Apt41", created_at=_on(FRIDAY)))
    await async_db_session.flush()

    with _no_llm():
        result = await recap_service.generate_weekly_recap(async_db_session, WEEK_START)

    assert (result["kind"], result["model"], result["raw_llm"]) == ("weekly", "", None)
    assert result["token_usage"] == {"skipped": True, "reason": "no_activity"}
    assert result["headline"] == "No notable cyber activity this week."
    assert result["yesterday"]["top_stories"] == [] and result["yesterday"]["notable_cves"] == []
    assert result["forecast"]["likely_events"] == []
    assert result["counts"] == {
        "articles": 0,
        "tweets": 0,
        "iocs": 1,
        "cves": 0,
        "campaigns": 0,
        "new_threat_actors": 1,
    }
    cached = await recap_service.get_recap(async_db_session, "2026-03-02", "weekly")
    assert cached is not None and cached["id"] == result["id"]


async def test_a_friday_run_is_refused_so_the_monday_run_builds_the_full_week(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Skenario yang dijaga penolakan pekan belum selesai: tangan yang menjalankannya Jumat tidak
    boleh meninggalkan pekan bolong sebagai cache yang lalu dikembalikan run terjadwal Senin."""
    await _seed_busy_week(async_db_session)
    client = _capturing_client([], usage=None)

    _today(monkeypatch, FRIDAY)
    with pytest.raises(recap_service.RecapWindowError, match="not finished yet"):
        await _generate_weekly(async_db_session, client)
    assert await recap_service.get_recap(async_db_session, "2026-03-02", "weekly") is None

    _today(monkeypatch, MONDAY_AFTER)
    monday = await _generate_weekly(async_db_session, client, week_start=None)

    assert monday["cached"] is False
    assert monday["date"] == "2026-03-02"
    assert monday["counts"]["articles"] == 5  # termasuk Sabtu, yang belum ada kalau Jumat jalan


@pytest.mark.parametrize("today", [MONDAY_AFTER, datetime.date(2026, 3, 11)])
async def test_without_a_week_start_the_last_finished_week_is_generated(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, today: datetime.date
) -> None:
    """Senin 00:15 UTC (run terjadwal) dan run yang telat (Rabu) mendapat pekan yang sama."""
    _today(monkeypatch, today)
    await _ensure_clients(async_db_session)

    with _no_llm():
        result = await recap_service.generate_weekly_recap(async_db_session)

    assert (result["date"], result["period_end"]) == ("2026-03-02", "2026-03-08")


async def test_weekly_prompt_lists_the_campaigns_of_its_own_week_and_collapses_each_to_a_line(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dulu klaster dihitung mundur dari HARI INI: pekan di masa lalu dapat klaster kosong. Dan
    tiga artikel satu kampanye harus jadi SATU baris artikel (plus satu baris kampanye)."""
    _today(monkeypatch, MONDAY_AFTER)
    await _ensure_clients(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    for i, title in enumerate(
        [
            "Apt41 hits target one today",
            "Apt41 hits target two today",
            "Apt41 hits target three today",
        ]
    ):
        a = await repo.upsert(
            url=f"https://example.com/weekly-campaign-{i}",
            title=title,
            source=f"S{i}",
            posted_on=WEEK_START + datetime.timedelta(days=i),
        )
        await repo.set_enrichment(a, threat_actors=["Apt41"])
    sent: list[dict[str, Any]] = []

    result = await _generate_weekly(async_db_session, _capturing_client(sent, usage=None))

    user_msg = sent[0]["messages"][1]["content"]
    assert result["counts"]["campaigns"] == 1
    assert result["counts"]["articles"] == 3  # total sebenarnya
    assert result["token_usage"]["prompt_items"]["articles"] == 1  # satu baris untuk satu klaster
    assert len(re.findall(r"^- \[S\d\]", user_msg, flags=re.MULTILINE)) == 1
    assert "| cluster: 3 articles" in user_msg
    assert "— 3 articles | actors: Apt41" in user_msg


async def test_weekly_recap_with_an_unparseable_reply_keeps_the_raw_text_and_logs_it(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _today(monkeypatch, MONDAY_AFTER)
    await _seed_busy_week(async_db_session)
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kw: _fake_completion("not json"))
        )
    )

    with structlog.testing.capture_logs() as logs:
        result = await _generate_weekly(async_db_session, client)

    assert (result["headline"], result["raw_llm"]) == ("", "not json")
    [entry] = [e for e in logs if e["event"] == "recap_weekly_generated"]
    assert entry["parse_failed"] is True


async def test_weekly_generation_logs_one_structured_line_per_run(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gaya `cve_mirror_synced`: satu baris `recap_weekly_generated` per generate, supaya log worker
    menunjukkan tiap run (rentang, total, token) tanpa membuka DB."""
    _today(monkeypatch, MONDAY_AFTER)
    await _seed_busy_week(async_db_session)
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)

    with structlog.testing.capture_logs() as logs:
        result = await _generate_weekly(async_db_session, _capturing_client([], usage))
        await _generate_weekly(async_db_session, _capturing_client([], usage))  # cache: tanpa log

    [entry] = [e for e in logs if e["event"] == "recap_weekly_generated"]
    assert entry["log_level"] == "info"
    assert (entry["kind"], entry["period_start"], entry["period_end"]) == (
        "weekly",
        "2026-03-02",
        "2026-03-08",
    )
    assert entry["counts"] == result["counts"]
    assert entry["token_usage"] == result["token_usage"]
    assert (entry["skipped"], entry["parse_failed"], entry["force"]) == (False, False, False)
    assert entry["model"] == "test-model"


async def test_a_skipped_week_logs_the_skipped_flag(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _today(monkeypatch, MONDAY_AFTER)
    await _ensure_clients(async_db_session)

    with structlog.testing.capture_logs() as logs, _no_llm():
        await recap_service.generate_weekly_recap(async_db_session, WEEK_START)

    [entry] = [e for e in logs if e["event"] == "recap_weekly_generated"]
    assert entry["skipped"] is True
    assert entry["token_usage"] == {"skipped": True, "reason": "no_activity"}
    assert entry["counts"]["articles"] == 0


async def test_the_database_session_timezone_is_utc(_migrated_schema: None) -> None:
    """Jendela mingguan memakai `func.date(timestamptz)`, yang mengikuti timezone sesi DB: kalau
    ini bukan UTC, hari bergeser dan pekannya salah tanpa error. Dijaga di CI di sini, dan di
    produksi lewat peringatan `recap_weekly_db_timezone_not_utc`."""
    async with get_async_engine().connect() as conn:
        zone = (await conn.execute(text("SHOW TIME ZONE"))).scalar_one()
        late_utc = (
            await conn.execute(text("SELECT date(TIMESTAMPTZ '2026-03-01 23:30:00+00')"))
        ).scalar_one()

    assert zone in {"UTC", "Etc/UTC"}
    assert late_utc == datetime.date(2026, 3, 1)  # 23:30 UTC masih tanggal 1, bukan 2


async def test_weekly_generation_warns_but_does_not_fail_when_the_session_is_not_utc(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _today(monkeypatch, MONDAY_AFTER)
    await _ensure_clients(async_db_session)
    await async_db_session.execute(text("SET LOCAL TIME ZONE 'Asia/Jakarta'"))

    with structlog.testing.capture_logs() as logs, _no_llm():
        result = await recap_service.generate_weekly_recap(async_db_session, WEEK_START)

    [warning] = [e for e in logs if e["event"] == "recap_weekly_db_timezone_not_utc"]
    assert (warning["log_level"], warning["timezone"]) == ("warning", "Asia/Jakarta")
    assert result["kind"] == "weekly"  # peringatan, bukan exception


async def test_weekly_generation_does_not_warn_on_a_utc_session(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _today(monkeypatch, MONDAY_AFTER)
    await _ensure_clients(async_db_session)

    with structlog.testing.capture_logs() as logs, _no_llm():
        await recap_service.generate_weekly_recap(async_db_session, WEEK_START)

    assert [e for e in logs if e["event"] == "recap_weekly_db_timezone_not_utc"] == []


async def test_a_legacy_row_without_a_period_reads_as_a_one_day_range(
    async_db_session: AsyncSession,
) -> None:
    """Penulis lama (rollback, deploy bergulir) tidak mengisi `kind`/`period_*`."""
    await async_db_session.execute(
        text(
            "INSERT INTO daily_recaps (date, headline, yesterday, forecast, counts, model, "
            "token_usage) VALUES ('2026-09-01', 'old writer', '{}', '{}', '{}', '', '{}')"
        )
    )

    doc = await recap_service.get_recap(async_db_session, "2026-09-01")

    assert doc is not None
    assert (doc["kind"], doc["period_start"], doc["period_end"]) == (
        "daily",
        "2026-09-01",
        "2026-09-01",
    )
