"""`/api/enrich-jobs` (P7g Task 6): daftar + filter, keputusan analis, coba ulang, audit log, dan
bukti `AsyncEnrichJobRepo.list/retry/counts` dengan hitungan pasti."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import pytest
from cti_core.db.models.article import Article
from cti_core.db.models.auth import AuditLogEntry
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.enrich_job import AsyncEnrichJobRepo
from cti_core.urlkit import url_hash
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.UTC)


def _job(
    n: int,
    kind: str = "classify",
    state: str = "pending",
    *,
    title: str | None = None,
    source: str = "darkreading",
    context: dict[str, object] | None = None,
    age_min: int = 0,
    article_id: int | None = None,
) -> EnrichJob:
    url = f"https://example.com/job-{n}"
    return EnrichJob(
        kind=kind,
        url=url,
        url_hash=url_hash(url),
        title=title or f"Job {n}",
        source=source,
        posted_on=datetime.date(2026, 11, 1),
        state=state,
        attempts=n,
        last_error="boom" if state == "failed" else None,
        context=context or {},
        created_at=NOW - datetime.timedelta(minutes=age_min),
        next_attempt_at=NOW,
        article_id=article_id,
    )


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str | None]]:
    calls: list[tuple[int, str | None]] = []
    monkeypatch.setattr(
        "cti_api.routers.enrich_jobs.send_enrich_llm",
        lambda job_id, decision=None: calls.append((job_id, decision)),
    )
    return calls


async def _seed(session: AsyncSession) -> dict[str, EnrichJob]:
    await session.execute(delete(EnrichJob))
    article = await AsyncArticleRepo(session).upsert(
        url="https://example.com/ttp-article", title="A", source="S", llm_ttp_status="pending"
    )
    jobs = {
        "c1": _job(
            1,
            title="Ransomware hits hospital",
            context={"relevance": {"probs": {"threat_news": 0.91}}},
            age_min=30,
        ),
        "c2": _job(
            2, "classify", "failed", title="Vendor webinar", source="vendorblog", age_min=20
        ),
        "t1": _job(3, "ttp", article_id=article.id, age_min=10),
        "t2": _job(4, "ttp", "failed", source="vendorblog", age_min=5, article_id=article.id),
    }
    # `ttp` unik per (kind, url_hash): dua job ttp butuh URL beda, sudah beda lewat n.
    session.add_all(jobs.values())
    await session.flush()
    return jobs


async def test_list_filters_search_and_pagination(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    jobs = await _seed(api_session)

    async def get(**params: object) -> dict:
        resp = await api_client.get("/api/enrich-jobs", params=params, headers=auth_header())
        assert resp.status_code == 200
        return resp.json()

    everything = await get()
    assert everything["total"] == 4 and everything["page"] == 1 and everything["page_size"] == 20
    # terbaru dulu
    assert [i["id"] for i in everything["items"]] == [jobs[k].id for k in ("t2", "t1", "c2", "c1")]
    first = everything["items"][-1]
    assert first["title"] == "Ransomware hits hospital"
    assert first["kind"] == "classify" and first["state"] == "pending"
    assert first["attempts"] == 1 and first["last_error"] is None
    assert first["posted_on"] == "2026-11-01" and first["p_threat_news"] == pytest.approx(0.91)
    assert everything["items"][0]["p_threat_news"] is None  # tanpa audit relevansi

    assert (await get(kind="ttp"))["total"] == 2
    assert (await get(kind="classify", state="failed"))["total"] == 1
    assert (await get(state="pending"))["total"] == 2
    assert (await get(search="webinar"))["total"] == 1
    assert (await get(search="VENDORBLOG"))["total"] == 2  # cocok sumber, tanpa beda huruf

    page2 = await get(page=2, page_size=3)
    assert page2["total"] == 4 and [i["id"] for i in page2["items"]] == [jobs["c1"].id]


async def test_list_rejects_bad_filters_and_requires_login(
    api_client: AsyncClient, auth_header: Callable[..., dict[str, str]]
) -> None:
    for params in ({"kind": "other"}, {"state": "done"}, {"page_size": 0}):
        resp = await api_client.get("/api/enrich-jobs", params=params, headers=auth_header())
        assert resp.status_code == 422
    assert (await api_client.get("/api/enrich-jobs")).status_code == 401


@pytest.mark.parametrize("decision", ["accept", "reject"])
async def test_decision_sends_the_task_and_writes_audit(
    decision: str,
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    sent: list[tuple[int, str | None]],
) -> None:
    jobs = await _seed(api_session)
    job = jobs["c2"]

    resp = await api_client.post(f"/api/enrich-jobs/{job.id}/{decision}", headers=auth_header())

    assert resp.status_code == 200 and resp.json() == {"success": True}
    assert sent == [(job.id, decision)]
    entry = (
        await api_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.action == f"enrich_job_{decision}")
        )
    ).scalar_one()
    assert entry.target_id == str(job.id) and entry.detail["url"] == job.url


async def test_decision_refuses_ttp_missing_and_non_managers(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    sent: list[tuple[int, str | None]],
) -> None:
    jobs = await _seed(api_session)
    ttp, classify = jobs["t1"], jobs["c1"]

    conflict = await api_client.post(f"/api/enrich-jobs/{ttp.id}/accept", headers=auth_header())
    missing = await api_client.post("/api/enrich-jobs/999999/reject", headers=auth_header())
    forbidden = await api_client.post(
        f"/api/enrich-jobs/{classify.id}/accept", headers=auth_header(role="analyst")
    )

    assert (conflict.status_code, missing.status_code, forbidden.status_code) == (409, 404, 403)
    assert sent == []


async def test_retry_resets_a_failed_job_and_writes_audit(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    sent: list[tuple[int, str | None]],
) -> None:
    jobs = await _seed(api_session)
    job = jobs["c2"]
    job.json_failures = 3
    job.next_attempt_at = NOW + datetime.timedelta(hours=5)
    await api_session.flush()

    resp = await api_client.post(f"/api/enrich-jobs/{job.id}/retry", headers=auth_header())

    assert resp.status_code == 200 and resp.json() == {"success": True}
    await api_session.refresh(job)
    assert job.state == "pending" and job.json_failures == 0
    assert job.next_attempt_at <= datetime.datetime.now(datetime.UTC)
    assert sent == []  # dispatcher yang mengirim
    entry = (
        await api_session.execute(
            select(AuditLogEntry).where(AuditLogEntry.action == "enrich_job_retry")
        )
    ).scalar_one()
    assert entry.target_id == str(job.id)


async def test_retry_refuses_pending_missing_and_non_managers(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    jobs = await _seed(api_session)
    failed_id = jobs["c2"].id

    pending = await api_client.post(
        f"/api/enrich-jobs/{jobs['c1'].id}/retry", headers=auth_header()
    )
    missing = await api_client.post("/api/enrich-jobs/999999/retry", headers=auth_header())
    forbidden = await api_client.post(
        f"/api/enrich-jobs/{failed_id}/retry", headers=auth_header(role="analyst")
    )

    assert (pending.status_code, missing.status_code, forbidden.status_code) == (409, 404, 403)


async def test_async_repo_counts_are_exact(api_session: AsyncSession) -> None:
    jobs = await _seed(api_session)
    counts = await AsyncEnrichJobRepo(api_session).counts()

    assert (counts.pending_classify, counts.pending_ttp, counts.failed) == (1, 1, 2)
    assert counts.oldest_pending_at == jobs["c1"].created_at


async def test_article_out_exposes_llm_ttp_status(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
) -> None:
    await api_session.execute(
        delete(Article).where(Article.url == "https://example.com/pending-ttp")
    )
    await AsyncArticleRepo(api_session).upsert(
        url="https://example.com/pending-ttp",
        title="Pending TTP article",
        source="S",
        llm_ttp_status="pending",
    )
    await api_session.flush()

    resp = await api_client.get(
        "/api/articles", params={"search": "Pending TTP article"}, headers=auth_header()
    )

    assert resp.status_code == 200
    [item] = resp.json()["articles"]
    assert item["llm_ttp_status"] == "pending"
