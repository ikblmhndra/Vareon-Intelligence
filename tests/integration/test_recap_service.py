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
from cti_api.services import recap as recap_service
from cti_core.db.models.cve import CveTracker
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.ta import AsyncTARepo
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
