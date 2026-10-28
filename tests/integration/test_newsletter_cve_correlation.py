"""Integration test korelasi CVE dan penulisan temuan di newsletter (`_get_tp_cve_ids`,
`_find_cve_mentions`, `write_article_findings`) -- Postgres REAL (testcontainers). Fetch Playwright
dan LLM diganti stub (`newsletter_stubs`); alur lewat HTTP ada di
`test_newsletter_router_snapshot.py`."""

from __future__ import annotations

import pytest
from cti_api.services import newsletter as newsletter_service
from cti_core.db.models.article_cve import ArticleCve
from cti_core.db.models.cve import CveNewsletterMention, CveTracker
from cti_core.db.models.indicator import Indicator
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.cve_fp_scenario import (
    FP_IN_BOTH,
    FP_IN_DEFAULT_ONLY,
    FP_IN_ITS_ONLY_CLIENT,
    TRUE_POSITIVES,
    seed_per_client_false_positives,
)
from tests.integration.newsletter_stubs import IOC_IP, patched_pipeline, seed_articles

pytestmark = pytest.mark.asyncio


async def test_true_positive_cves_are_judged_per_client_row(async_db_session: AsyncSession) -> None:
    """FP itu per `(cve_id, client_id)`. CVE masih true positive selama ada SATU client yang
    men-track-nya tanpa menandai FP. Dulu hanya FP client "default" yang dihitung: artikel yang
    menyebut CVE yang FP di "default" tapi valid di client lain tidak ditandai, dan CVE yang
    di-FP-kan semua client selain "default" tetap ditandai. Skenarionya: `cve_fp_scenario`."""
    await seed_per_client_false_positives(async_db_session)

    tp = await newsletter_service._get_tp_cve_ids(async_db_session)
    assert tp == set(TRUE_POSITIVES)

    # Dua langkah terpisah sejak cache: id diekstrak dari judul + body saat fetch (di-cache
    # apa adanya), lalu diiriskan dengan set true-positive SAAT build.
    title = f"Patch {FP_IN_DEFAULT_ONLY}, {FP_IN_BOTH} and {FP_IN_ITS_ONLY_CLIENT} now"
    found = newsletter_service._extract_cve_ids(title, None)
    assert found == sorted([FP_IN_DEFAULT_ONLY, FP_IN_BOTH, FP_IN_ITS_ONLY_CLIENT])
    assert newsletter_service._find_cve_mentions(found, tp) == [FP_IN_DEFAULT_ONLY]


async def _cache_one_article(session: AsyncSession) -> dict[str, object]:
    """Satu artikel dengan baris cache yang sudah terisi (seolah build sebelumnya sudah jalan):
    IOC dari body, dan dua CVE id, satu true positive dan satu FP di semua client."""
    [article_id] = await seed_articles(session, 1)
    article = (await newsletter_service.fetch_articles_by_ids(session, [article_id]))[article_id]
    await AsyncNewsletterRepo(session).upsert_article_summary(
        article_id=article_id,
        language="id",
        key_points=["poin"],
        summary="ringkasan",
        body_source="fetched",
        iocs={"ips": [IOC_IP], "cves": [FP_IN_DEFAULT_ONLY, FP_IN_BOTH]},
        cve_ids=[FP_IN_DEFAULT_ONLY, FP_IN_BOTH],
        model="stub-model",
        token_usage={},
    )
    return article


async def _count(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_draft_step_writes_the_cached_iocs_and_cve_mentions_without_any_fetch(
    async_db_session: AsyncSession,
) -> None:
    await seed_per_client_false_positives(async_db_session)
    article = await _cache_one_article(async_db_session)

    with patched_pipeline() as pipeline:
        # Artikel yang sama sebagai highlight DAN kartu apac: temuannya tetap ditulis sekali.
        context = await newsletter_service.build_newsletter_context(
            async_db_session, article, [article], [], []
        )
        assert pipeline.calls == (0, 0)  # semuanya dari cache

        # Membangun konteks tidak menulis apa pun ke catatan.
        assert context["highlight"]["cve_mentions"] == [FP_IN_DEFAULT_ONLY]
        assert await _count(async_db_session, Indicator) == 0
        assert await _count(async_db_session, CveNewsletterMention) == 0

        await newsletter_service.save_newsletter(async_db_session, context, "<html/>", "tester")
        await newsletter_service.write_article_findings(async_db_session, context)

        assert pipeline.calls == (0, 0)  # menulis temuan pun tanpa fetch

    iocs = {
        (i.type, i.value): i for i in (await async_db_session.execute(select(Indicator))).scalars()
    }
    assert set(iocs) == {("ip", IOC_IP)}  # CVE tidak lagi jadi IOC
    cves = (await async_db_session.execute(select(ArticleCve.cve_id))).scalars().all()
    assert sorted(cves) == sorted([FP_IN_DEFAULT_ONLY, FP_IN_BOTH])
    assert {i.seen_count for i in iocs.values()} == {1}  # sekali, walau artikelnya muncul dua kali

    # Sebutan CVE hanya untuk yang true positive saat build; FP_IN_BOTH tidak ditulis.
    [mention] = (await async_db_session.execute(select(CveNewsletterMention))).scalars().all()
    assert mention.url == article["url"]
    assert mention.title == article["title"]
    tracker = (
        await async_db_session.execute(
            select(CveTracker).where(CveTracker.id == mention.cve_tracker_id)
        )
    ).scalar_one()
    assert tracker.cve_id == FP_IN_DEFAULT_ONLY


async def test_cve_mentions_follow_the_current_true_positive_set_not_the_set_at_cache_time(
    async_db_session: AsyncSession,
) -> None:
    """`cve_ids` di cache tidak tersaring; irisannya dihitung ulang tiap build. CVE yang tadinya
    true positive dan kemudian di-FP-kan di SEMUA client yang men-track-nya hilang dari edisi
    berikutnya tanpa fetch atau LLM lagi."""
    await seed_per_client_false_positives(async_db_session)
    article = await _cache_one_article(async_db_session)

    with patched_pipeline() as pipeline:
        before = await newsletter_service.build_newsletter_context(
            async_db_session, article, [], [], []
        )
        # FP_IN_DEFAULT_ONLY di-track `default` (sudah FP) dan `acme`: tandai FP juga di acme.
        await AsyncCveFalsePositiveRepo(async_db_session).mark(FP_IN_DEFAULT_ONLY, "acme")
        after = await newsletter_service.build_newsletter_context(
            async_db_session, article, [], [], []
        )

        assert pipeline.calls == (0, 0)

    assert before["highlight"]["cve_mentions"] == [FP_IN_DEFAULT_ONLY]
    assert before["highlight"]["possibly_exploited_wild"] is True
    assert after["highlight"]["cve_mentions"] == []
    assert after["highlight"]["possibly_exploited_wild"] is False
