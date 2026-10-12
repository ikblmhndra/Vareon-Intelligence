"""Snapshot test `routers/newsletter.py` -- Fase 7.6 (lanjutan pola
pilot `test_cve_router_snapshot.py`).

Tiga gaya di file ini:
- Test bentuk respons (snapshot): `_enrich_articles()` (Playwright browser real + LLM
  summarization) di-mock, titik yang SAMA persis kayak `test_newsletter_clusters.py` yang
  udah ada. `create_graph_draft` (imported LANGSUNG ke namespace `cti_api.routers.newsletter`,
  bukan cuma `cti_alerts.mailer`) di-patch di titik importnya sendiri, bukan sumbernya -- match
  `from X import Y` binding, bukan `import X`.
- Test alur (ROADMAP #22, PR 5): `_enrich_articles` dibiarkan JALAN beneran supaya cache
  ringkasan, urutan simpan, dan penulisan IOC/CVE terukur; yang di-stub hanya fetch Playwright,
  klien LLM, dan Graph (`newsletter_stubs`). Yang dibuktikan di sana adalah JUMLAH panggilan dan
  isi tabel, bukan bentuk JSON.
- Test saran konten (ROADMAP #22, PR 7): artikel sungguhan di DB, cluster kampanye dimatikan dan
  jam dipatok (`no_campaigns`, `suggestion_clock`); satu snapshot untuk bentuk respons, sisanya
  asersi perilaku (timpa saat rebuild, "terbaru", validasi, audit)."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from cti_api.schemas.newsletter import NewsletterSectionsBody
from cti_api.services import newsletter as newsletter_service
from cti_api.services import newsletter_edition
from cti_core.db.models.article import Article
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.cve import CveNewsletterMention, CveTracker
from cti_core.db.models.ioc import IOC
from cti_core.db.models.newsletter import Newsletter, NewsletterArticleSummary, NewsletterSuggestion
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from syrupy.assertion import SnapshotAssertion
from syrupy.matchers import path_type

from tests.integration.newsletter_stubs import (
    no_campaigns,
    patched_pipeline,
    seed_articles,
    seed_true_positive_cve,
    suggestion_clock,
)

pytestmark = pytest.mark.asyncio

# Dipin ke ISO week 39, 2026 (Senin 2026-09-21 s.d. Minggu 2026-09-27) supaya
# `week`/`year`/subject line di snapshot gak ikut geser tiap minggu kalender
# ASLI berganti -- lihat `newsletter_service._now()`.
_NOW = datetime.datetime(2026, 9, 24, 12, 0, tzinfo=datetime.UTC)

_GRAPH = "cti_api.routers.newsletter.create_graph_draft"

_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?newsletter_id$": (int,),
        r"(.*\.)?created_at$": (str,),
        r"(.*\.)?generated_at$": (str,),
        r"(.*\.)?html_bytes$": (int,),  # ukuran HTML berubah tiap template diubah
    },
    regex=True,
    strict=False,
)


async def _seed_article(session: AsyncSession) -> int:
    await AsyncClientRepo(session).ensure_default()
    a = await AsyncArticleRepo(session).upsert(
        url="https://example.com/highlight",
        title="APT41 breaches government network",
        source="gbhacker",
        posted_on=datetime.date(2026, 9, 1),
    )
    return a.id


def _fake_enrich_articles() -> AsyncMock:
    return AsyncMock(
        return_value=[
            {
                "id": 1,
                "title": "APT41 breaches government network",
                "url": "https://example.com/highlight",
                "source": "gbhacker",
                "key_points": ["Government network breached"],
                "summary": "APT41 breached a government network.",
            }
        ]
    )


async def test_source_hints(
    api_client: AsyncClient,
    api_session: AsyncSession,
    snapshot: SnapshotAssertion,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    resp = await api_client.get("/api/newsletter/source-hints", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_newsletter_history_empty(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    resp = await api_client.get("/api/newsletter/history", headers=auth_header())
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_preview_newsletter(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with (
        patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()),
        patch.object(newsletter_service, "_now", return_value=_NOW),
    ):
        resp = await api_client.post(
            "/api/newsletter/preview", headers=auth_header(), json={"highlights": [article_id]}
        )
    assert resp.status_code == 200
    body = resp.json()
    body.pop("html")  # HTML render -- bukan fokus shape test ini
    assert body == snapshot(matcher=_NORMALIZE)


async def test_get_saved_html(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with (
        patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()),
        patch(_GRAPH, MagicMock(return_value="graph-msg-0")),
    ):
        # Preview tidak lagi menyimpan baris; hanya `draft-email` yang membuat satu.
        draft_resp = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json={"highlights": [article_id]}
        )
    newsletter_id = draft_resp.json()["newsletter_id"]
    resp = await api_client.get(f"/api/newsletter/{newsletter_id}/html", headers=auth_header())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert len(resp.text) > 0


async def test_resend_newsletter(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with (
        patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()),
        patch.object(newsletter_service, "_now", return_value=_NOW),
        patch(_GRAPH, MagicMock(return_value="graph-msg-0")),
    ):
        draft_resp = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json={"highlights": [article_id]}
        )
    newsletter_id = draft_resp.json()["newsletter_id"]
    with patch(_GRAPH, MagicMock(return_value="graph-msg-1")):
        resp = await api_client.post(
            f"/api/newsletter/{newsletter_id}/resend", headers=auth_header()
        )
    assert resp.status_code == 200
    assert resp.json() == snapshot


async def test_draft_email(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    article_id = await _seed_article(api_session)
    with (
        patch.object(newsletter_service, "_enrich_articles", _fake_enrich_articles()),
        patch.object(newsletter_service, "_now", return_value=_NOW),
        patch(_GRAPH, MagicMock(return_value="graph-msg-2")),
    ):
        resp = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json={"highlights": [article_id]}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body == snapshot(matcher=_NORMALIZE)


# ── Alur nyata (cache, satu baris per draft, periode, tier) -- ROADMAP #22, PR 5 ──────────────────


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def _history(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> list[dict[str, object]]:
    resp = await api_client.get("/api/newsletter/history", headers=auth_header())
    assert resp.status_code == 200
    items: list[dict[str, object]] = resp.json()["newsletters"]
    return items


async def test_preview_twice_then_draft_leaves_one_row_and_repeats_no_fetch_or_llm_call(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await seed_articles(api_session, 2)
    await seed_true_positive_cve(api_session)
    payload = {"highlights": [ids[0]], "apac_full": [ids[1]]}

    with patched_pipeline() as pipeline, patch(_GRAPH, MagicMock(return_value="graph-1")) as graph:
        first = await api_client.post(
            "/api/newsletter/preview", headers=auth_header(), json=payload
        )
        assert first.status_code == 200
        assert first.json()["newsletter_id"] is None
        assert pipeline.calls == (2, 2)  # dingin: satu fetch + satu LLM per artikel

        second = await api_client.post(
            "/api/newsletter/preview", headers=auth_header(), json=payload
        )
        assert second.json()["html"] == first.json()["html"]
        assert pipeline.calls == (2, 2)  # preview kedua: nol panggilan baru

        # Dua preview tidak meninggalkan apa pun di catatan; hanya kedua cache yang terisi.
        assert await _count(api_session, Newsletter) == 0
        assert await _count(api_session, IOC) == 0
        assert await _count(api_session, CveNewsletterMention) == 0
        assert await _count(api_session, NewsletterArticleSummary) == 2

        draft = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json=payload
        )
        assert draft.status_code == 200
        assert pipeline.calls == (2, 2)  # draft sesudah preview: nol panggilan baru
        graph.assert_called_once()

    assert await _count(api_session, Newsletter) == 1
    [row] = (await api_session.execute(select(Newsletter))).scalars().all()
    assert draft.json()["newsletter_id"] == row.id

    # Temuan ditulis SEKALI oleh draft, dari cache (IOC dari body, sebutan CVE untuk true positive).
    ips = (await api_session.execute(select(IOC.value).where(IOC.type == "ip"))).scalars().all()
    assert ips == ["203.0.113.77"]
    mention_urls = {
        m.url for m in (await api_session.execute(select(CveNewsletterMention))).scalars()
    }
    assert mention_urls == {"https://example.com/story-1", "https://example.com/story-2"}


async def test_a_failing_graph_call_leaves_no_row_and_the_retry_reuses_the_cache(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await seed_articles(api_session, 2)
    await seed_true_positive_cve(api_session)
    payload = {"highlights": [ids[0]], "apac_full": [ids[1]]}

    with patched_pipeline() as pipeline:
        with patch(_GRAPH, MagicMock(side_effect=RuntimeError("graph is down"))):
            failed = await api_client.post(
                "/api/newsletter/draft-email", headers=auth_header(), json=payload
            )
        assert failed.status_code == 500
        assert "graph is down" in failed.json()["detail"]
        # `get_db` produksi me-rollback sesi kalau handler melempar; override di `api_client`
        # tidak, jadi tiru di sini. Tanpa ini yang tertinggal di sesi (flush, belum commit)
        # tetap terlihat dan test tidak bisa membedakan "sudah di-commit" dari "belum".
        await api_session.rollback()
        # Dulu barisnya sudah di-commit sebelum Graph dipanggil.
        assert await _count(api_session, Newsletter) == 0
        assert await _count(api_session, IOC) == 0
        assert await _count(api_session, CveNewsletterMention) == 0
        # Kerja fetch + LLM tidak hilang: cache sudah di-commit sebelum Graph.
        assert await _count(api_session, NewsletterArticleSummary) == 2
        after_failure = pipeline.calls

        with patch(_GRAPH, MagicMock(return_value="graph-ok")):
            retry = await api_client.post(
                "/api/newsletter/draft-email", headers=auth_header(), json=payload
            )
        assert retry.status_code == 200
        assert pipeline.calls == after_failure  # coba lagi: nol panggilan baru

    assert await _count(api_session, Newsletter) == 1


async def test_a_failed_save_after_graph_logs_the_message_id_and_still_returns_an_error(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await seed_articles(api_session, 1)

    with (
        patched_pipeline(),
        patch(_GRAPH, MagicMock(return_value="graph-msg-orphan")) as graph,
        patch.object(
            newsletter_service,
            "save_newsletter",
            AsyncMock(side_effect=RuntimeError("db exploded")),
        ),
        structlog.testing.capture_logs() as logs,
    ):
        resp = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json={"highlights": [ids[0]]}
        )

    assert resp.status_code == 500
    graph.assert_called_once()
    # Analis diberi tahu draft-nya ADA di Outlook (supaya tidak membuat yang kedua), dan id-nya
    # tercatat di log terstruktur supaya draft yatim bisa dicari.
    assert "graph-msg-orphan" in resp.json()["detail"]
    assert "db exploded" in resp.json()["detail"]
    [entry] = [e for e in logs if e["event"] == "newsletter_draft_unsaved"]
    assert entry["email_id"] == "graph-msg-orphan"
    assert entry["log_level"] == "error"
    assert await _count(api_session, Newsletter) == 0


async def test_regenerate_rebuilds_only_the_listed_article_and_only_once(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await seed_articles(api_session, 2)
    payload = {"highlights": [ids[0]], "apac_full": [ids[1]]}

    with patched_pipeline() as pipeline:
        await api_client.post("/api/newsletter/preview", headers=auth_header(), json=payload)
        assert pipeline.calls == (2, 2)

        redo = await api_client.post(
            "/api/newsletter/preview",
            headers=auth_header(),
            json={**payload, "regenerate": [ids[1]]},
        )
        assert redo.status_code == 200
        assert pipeline.calls == (3, 3)  # hanya artikel yang disebut

        await api_client.post("/api/newsletter/preview", headers=auth_header(), json=payload)
        assert pipeline.calls == (3, 3)  # build berikutnya memakai baris yang baru

    assert await _count(api_session, NewsletterArticleSummary) == 2  # menimpa, bukan menambah


async def test_tiered_request_fetches_only_full_cards_and_saves_the_compact_rows(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await seed_articles(api_session, 6)
    payload = {
        "highlights": [ids[0]],
        "apac_full": [ids[1]],
        "apac_compact": [ids[2], ids[3]],
        "global_news_compact": [ids[4]],
        "indonesia_full": [ids[5]],
    }

    with patched_pipeline() as pipeline, patch(_GRAPH, MagicMock(return_value="graph-t")):
        resp = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json=payload
        )

    assert resp.status_code == 200
    assert pipeline.calls == (3, 3)  # highlight + apac_full + indonesia_full; compact: nol
    [item] = await _history(api_client, auth_header)
    sections = item["sections"]
    assert isinstance(sections, dict)
    assert [a["title"] for a in sections["apac_compact"]] == [
        "Story 3 about intrusions",
        "Story 4 about intrusions",
    ]
    assert [a["title"] for a in sections["global_news_compact"]] == ["Story 5 about intrusions"]
    assert sections["indonesia_compact"] == []
    # Kartu penuh tetap di kunci lama, dan `highlight` (yang dirender template lama) = yang pertama.
    assert [a["id"] for a in sections["apac"]] == [ids[1]]
    assert [a["id"] for a in sections["indonesia"]] == [ids[5]]
    assert sections["highlight"]["id"] == ids[0]
    assert [a["id"] for a in sections["highlights"]] == [ids[0]]


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"highlights": [1, 2, 3, 4]}, "highlights: max 3 articles"),
        ({"highlights": [1], "apac_full": [1, 2, 3, 4, 5]}, "apac_full: max 4 articles"),
        (
            {"highlights": [1], "global_news_full": list(range(5))},
            "global_news_full: max 4 articles",
        ),
        ({"highlights": [1], "indonesia_full": list(range(5))}, "indonesia_full: max 4 articles"),
        ({"highlights": [1], "apac_compact": list(range(16))}, "apac_compact: max 15 articles"),
    ],
)
async def test_over_the_limit_is_a_400_naming_the_field(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    payload: dict[str, object],
    detail: str,
) -> None:
    for path in ("/api/newsletter/preview", "/api/newsletter/draft-email"):
        resp = await api_client.post(path, headers=auth_header(), json=payload)
        assert resp.status_code == 400
        assert resp.json()["detail"] == detail


@pytest.mark.parametrize(
    "payload",
    [
        {},  # tanpa highlight sama sekali
        {"apac_full": [1]},
        {"highlight": 1},  # field lama sudah dihapus: tidak dihitung sebagai highlight
        {"highlights": [1], "period_start": "2026-10-01"},  # hanya satu tanggal
        {"highlights": [1], "period_start": "2026-11-01", "period_end": "2026-10-31"},
        {"highlights": [1], "period_start": "bukan-tanggal", "period_end": "2026-10-31"},
    ],
)
async def test_malformed_requests_are_422(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    payload: dict[str, object],
) -> None:
    resp = await api_client.post("/api/newsletter/preview", headers=auth_header(), json=payload)
    assert resp.status_code == 422


async def test_an_unknown_article_id_is_a_404_in_any_tier(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await seed_articles(api_session, 1)
    resp = await api_client.post(
        "/api/newsletter/preview",
        headers=auth_header(),
        json={"highlights": [ids[0]], "apac_compact": [987654]},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Article 987654 not found"


async def test_the_row_gets_the_default_or_requested_period_and_still_the_iso_week(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    ids = await seed_articles(api_session, 1)
    payload = {"highlights": [ids[0]]}

    with patched_pipeline(), patch(_GRAPH, MagicMock(return_value="graph-p")):
        default = await api_client.post(
            "/api/newsletter/draft-email", headers=auth_header(), json=payload
        )
        explicit = await api_client.post(
            "/api/newsletter/draft-email",
            headers=auth_header(),
            json={**payload, "period_start": "2026-09-28", "period_end": "2026-10-04"},
        )

    # `week`/`year` = minggu ISO dari waktu pembuatan (pin 2 Nov 2026 = minggu 45), seperti dulu.
    for resp in (default, explicit):
        assert (resp.json()["week"], resp.json()["year"]) == (45, 2026)

    newest, older = await _history(api_client, auth_header)
    assert newest["id"] == explicit.json()["newsletter_id"]
    assert older["id"] == default.json()["newsletter_id"]
    # Tanpa periode di request: bulan kalender sebelumnya menurut WIB (Senin 2 Nov -> Oktober).
    assert (older["label"], older["period_start"], older["period_end"]) == (
        "October 2026",
        "2026-10-01",
        "2026-10-31",
    )
    assert (newest["label"], newest["period_start"], newest["period_end"]) == (
        "September - October 2026",
        "2026-09-28",
        "2026-10-04",
    )


async def test_newsletter_history_label(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    """Baris lama (tanpa periode) jatuh ke "Week N, YYYY"; baris dengan periode memakai labelnya.
    Field lama (`week`, `year`, ...) tetap ada untuk UI yang belum memakai `label`."""
    repo = AsyncNewsletterRepo(api_session)
    await repo.save(
        week=38,
        year=2026,
        generated_at="2026-09-19 10:00 UTC",
        created_by="analyst1",
        html="<html/>",
        sections={},
    )
    await repo.save(
        week=45,
        year=2026,
        period_start=datetime.date(2026, 10, 1),
        period_end=datetime.date(2026, 10, 31),
        generated_at="2026-11-02 02:00 UTC",
        created_by="analyst1",
        html="<html/>",
        sections={},
    )

    resp = await api_client.get("/api/newsletter/history", headers=auth_header())

    assert resp.status_code == 200
    assert [i["label"] for i in resp.json()["newsletters"]] == ["October 2026", "Week 38, 2026"]
    assert resp.json() == snapshot(matcher=_NORMALIZE)


# ── Saran konten (ROADMAP #22, PR 7) ─────────────────────────────────────────────────────────────

_SUGGESTION_NORMALIZE = path_type(
    {
        r"(.*\.)?id$": (int,),
        r"(.*\.)?article_id$": (int,),
        r"(.*\.)?created_at$": (str,),
    },
    regex=True,
    strict=False,
)

_OCTOBER = {"period_start": "2026-10-01", "period_end": "2026-10-31"}
_SUGGESTION = "/api/newsletter/suggestion"
_REBUILD = "/api/newsletter/suggestion/rebuild"


async def _seed_october(session: AsyncSession) -> dict[str, int]:
    """Satu client (negara SG, tech Fortinet), satu CVE KEV, dan enam artikel dengan skor berbeda
    supaya urutannya tidak bergantung id: tiga highlight, satu kartu penuh, satu tanpa sinyal,
    satu di luar jendela."""
    clients = AsyncClientRepo(session)
    await clients.ensure_default()
    await clients.update("default", name="Default", countries=["SG"])
    await AsyncTechStackRepo(session).create(name="Fortinet", client_id="default")
    session.add(
        CveTracker(cve_id="CVE-2026-1111", client_id="default", tech="Fortinet", cisa_kev=True)
    )
    await session.flush()
    repo = AsyncArticleRepo(session)
    day = datetime.date
    specs = [
        (
            "bank",
            "Indonesian bank breached by ransomware crew",
            "BleepingComputer",
            day(2026, 10, 12),
            90,
            True,
            [("ID", "victim"), ("ID", "mentioned")],
        ),
        (
            "zero_day",
            "Fortinet zero-day CVE-2026-1111 exploited in the wild",
            "CISA",
            day(2026, 10, 20),
            85,
            False,
            [],
        ),
        (
            "factory",
            "Japanese manufacturer hit by supply chain attack",
            "Wired",
            day(2026, 10, 3),
            75,
            False,
            [("JP", "victim")],
        ),
        (
            "roundup",
            "Quiet security roundup for the week",
            "Random Blog",
            day(2026, 10, 25),
            60,
            False,
            [],
        ),
        ("noise", "Phishing kit sold on a forum", "Random Blog", day(2026, 10, 28), 40, False, []),
        (
            "september",
            "A September story outside the window",
            "CISA",
            day(2026, 9, 30),
            95,
            True,
            [],
        ),
    ]
    ids = {}
    for name, title, source, posted_on, confidence, confirmed, countries in specs:
        article = await repo.upsert(
            url=f"https://example.com/{name}",
            title=title,
            source=source,
            posted_on=posted_on,
            confidence_score=confidence,
            confirmed_incident=confirmed,
        )
        if countries:
            await repo.set_enrichment(article, countries=countries)
        ids[name] = article.id
    return ids


async def _rebuild(
    api_client: AsyncClient,
    auth_header: Callable[..., dict[str, str]],
    body: dict[str, object] | None = None,
) -> Any:
    with suggestion_clock(), no_campaigns():
        return await api_client.post(_REBUILD, headers=auth_header(), json=body)


async def test_suggestion_is_a_404_until_one_has_been_built(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    latest = await api_client.get(_SUGGESTION, headers=auth_header())
    exact = await api_client.get(_SUGGESTION, params=_OCTOBER, headers=auth_header())

    assert (latest.status_code, exact.status_code) == (404, 404)
    assert latest.json() == {"detail": "No newsletter suggestion found"}


async def test_rebuild_builds_the_previous_month_and_get_returns_the_same_suggestion(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    snapshot: SnapshotAssertion,
) -> None:
    ids = await _seed_october(api_session)

    built = await _rebuild(api_client, auth_header)  # tanpa body: bulan sebelum 2 Nov 2026

    assert built.status_code == 200
    body = built.json()
    assert body == snapshot(matcher=_SUGGESTION_NORMALIZE)
    assert [i["article_id"] for i in body["items"]] == [
        ids["zero_day"],
        ids["bank"],
        ids["factory"],
        ids["roundup"],
    ]  # `noise` tanpa sinyal dan `september` di luar jendela tidak ikut
    latest = await api_client.get(_SUGGESTION, headers=auth_header())
    exact = await api_client.get(_SUGGESTION, params=_OCTOBER, headers=auth_header())
    assert latest.status_code == exact.status_code == 200
    assert latest.json() == exact.json() == body
    other = await api_client.get(
        _SUGGESTION,
        params={"period_start": "2026-09-01", "period_end": "2026-09-30"},
        headers=auth_header(),
    )
    assert other.status_code == 404  # jendela PERSIS, bukan yang beririsan


async def test_rebuild_accepts_an_empty_object_and_an_explicit_window(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _seed_october(api_session)

    empty = await _rebuild(api_client, auth_header, {})
    explicit = await _rebuild(api_client, auth_header, _OCTOBER)
    narrower = await _rebuild(
        api_client, auth_header, {"period_start": "2026-10-10", "period_end": "2026-10-15"}
    )

    assert empty.status_code == explicit.status_code == narrower.status_code == 200
    assert empty.json()["id"] == explicit.json()["id"]  # default = Oktober = jendela yang sama
    assert [i["rank"] for i in narrower.json()["items"]] == [1]  # hanya `bank` di 10-15 Okt
    assert narrower.json()["label"] == "October 2026"
    assert await api_session.scalar(select(func.count()).select_from(NewsletterSuggestion)) == 2


async def test_rebuilding_replaces_the_stored_suggestion_for_that_exact_window(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    ids = await _seed_october(api_session)
    first = (await _rebuild(api_client, auth_header)).json()
    assert ids["noise"] not in [i["article_id"] for i in first["items"]]
    await AsyncArticleRepo(api_session).set_overrides(
        await api_session.get_one(Article, ids["noise"]), confirmed_incident=True
    )

    second = (await _rebuild(api_client, auth_header)).json()

    assert second["id"] == first["id"]
    assert second["items"][0]["article_id"] == ids["zero_day"]
    assert ids["noise"] in [i["article_id"] for i in second["items"]]
    assert await api_session.scalar(select(func.count()).select_from(NewsletterSuggestion)) == 1


async def test_latest_is_the_window_that_ends_last_even_when_an_older_one_was_rebuilt_later(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _seed_october(api_session)
    october = (await _rebuild(api_client, auth_header)).json()
    september = await _rebuild(
        api_client, auth_header, {"period_start": "2026-09-01", "period_end": "2026-09-30"}
    )
    assert september.status_code == 200 and september.json()["id"] != october["id"]

    latest = await api_client.get(_SUGGESTION, headers=auth_header())

    assert latest.json()["id"] == october["id"]


@pytest.mark.parametrize(
    "body",
    [
        {"period_start": "2026-10-01"},
        {"period_end": "2026-10-31"},
        {"period_start": "2026-10-31", "period_end": "2026-10-01"},
        {"period_start": "2026-01-01", "period_end": "2026-12-31"},
        {"period_start": "2026-08-01", "period_end": "2026-11-02"},  # 94 hari: satu terlalu panjang
        {"period_start": "bukan-tanggal", "period_end": "2026-10-31"},
    ],
)
async def test_rebuild_rejects_a_malformed_window_and_stores_nothing(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    body: dict[str, object],
) -> None:
    resp = await _rebuild(api_client, auth_header, body)

    assert resp.status_code == 422
    assert await api_session.scalar(select(func.count()).select_from(NewsletterSuggestion)) == 0


async def test_the_longest_allowed_window_is_93_days(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    resp = await _rebuild(
        api_client, auth_header, {"period_start": "2026-08-01", "period_end": "2026-11-01"}
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "August - November 2026"


@pytest.mark.parametrize("params", [{"period_start": "2026-10-01"}, {"period_end": "2026-10-31"}])
async def test_get_needs_both_dates_or_neither(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]], params: dict[str, str]
) -> None:
    resp = await api_client.get(_SUGGESTION, params=params, headers=auth_header())
    assert resp.status_code == 422


async def test_both_suggestion_endpoints_require_login(api_client: AsyncClient) -> None:
    assert (await api_client.get(_SUGGESTION)).status_code == 401
    assert (await api_client.post(_REBUILD, json={})).status_code == 401


async def test_rebuild_is_written_to_the_audit_log(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    await _seed_october(api_session)
    with suggestion_clock(), no_campaigns():
        resp = await api_client.post(_REBUILD, headers=auth_header("rina"), json={})

    entry = (
        await api_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.action == "rebuild_newsletter_suggestion")
        )
    ).scalar_one()
    assert entry.username == "rina"
    assert entry.target_id == str(resp.json()["id"])
    assert entry.detail == {**_OCTOBER, "items": 4}


async def test_items_whose_article_was_deleted_are_left_out_of_the_response(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    ids = await _seed_october(api_session)
    await _rebuild(api_client, auth_header)
    await api_session.delete(await api_session.get_one(Article, ids["bank"]))
    await api_session.flush()

    resp = await api_client.get(_SUGGESTION, headers=auth_header())

    assert [i["article_id"] for i in resp.json()["items"]] == [
        ids["zero_day"],
        ids["factory"],
        ids["roundup"],
    ]


async def test_suggestion_items_map_straight_onto_the_tier_request_fields(
    api_client: AsyncClient, api_session: AsyncSession, auth_header: Callable[..., dict[str, str]]
) -> None:
    """Kontrak dengan PR 5/9: `highlights`, `<section>_full`, `<section>_compact` dan batasnya."""
    await AsyncClientRepo(api_session).ensure_default()
    repo = AsyncArticleRepo(api_session)
    for n in range(66):
        country = ("ID", "JP", "US")[n % 3]
        article = await repo.upsert(
            url=f"https://example.com/many-{n}",
            title=f"many{n:03d} headline{n:03d}",
            source="CISA",
            posted_on=datetime.date(2026, 10, 1 + n % 28),
            confidence_score=100,
            confirmed_incident=True,
        )
        await repo.set_enrichment(article, countries=[(country, "victim")])

    resp = await _rebuild(api_client, auth_header)

    items = resp.json()["items"]
    request: dict[str, list[int]] = {"highlights": []}
    for section in newsletter_edition.SECTIONS:
        request[f"{section}_full"] = []
        request[f"{section}_compact"] = []
    for item in items:
        key = "highlights" if item["tier"] == "highlight" else f"{item['section']}_{item['tier']}"
        request[key].append(item["article_id"])
    body = NewsletterSectionsBody(**request)  # tidak ada ValidationError
    plan = newsletter_edition.plan_sections(body)  # dan tidak ada SectionLimitError
    assert len(plan.highlights) == 3
    assert all(len(plan.full[s]) == 4 and len(plan.compact[s]) == 15 for s in plan.full)
    assert len(items) == 60
