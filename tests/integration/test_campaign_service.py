"""Integration test `cti_api.services.campaign.get_recent_campaigns()`
(Pipeline 2 -- union-find TF-IDF + enrichment kaya) -- Postgres REAL
(testcontainers). Fase 7.4 Grup A (2026-09-23).

Judul artikel di test ini SENGAJA dipilih lewat percobaan langsung
lawan `TfidfVectorizer` asli (bukan ditebak) -- threshold union-find
Pipeline 2 (0.75) jauh lebih ketat dari Pipeline 1 (0.35 default), dan
sensitif ke ukuran korpus (IDF bergeser kalau jumlah dokumen beda),
jadi judul yang "keliatan mirip" belum tentu lolos 0.75 secara
matematis -- diverifikasi similarity-nya dulu, bukan asumsi."""

from __future__ import annotations

import datetime

import pytest
import structlog
from cti_api.services import campaign as campaign_service
from cti_core.db.models.cve import CveTracker
from cti_core.db.models.pir import PIRRequirement
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.article_cve import AsyncArticleCveRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio

_TODAY = datetime.date.today()

_TITLES = [
    "Apt41 threat group breaches manufacturing networks alpha",
    "Apt41 threat group breaches manufacturing networks beta",
]


async def _ensure_clients(session: AsyncSession) -> None:
    await AsyncClientRepo(session).ensure_default()


async def _seed_campaign_articles(session: AsyncSession) -> list[int]:
    repo = AsyncArticleRepo(session)
    article_ids = []
    for i, title in enumerate(_TITLES):
        a = await repo.upsert(
            url=f"https://example.com/campaign-{i}",
            title=title,
            source=f"Source{i}",
            posted_on=_TODAY,
        )
        await repo.set_enrichment(
            a,
            threat_actors=["Apt41"],
            industries=["Manufacturing"],
            countries=[("US", "mentioned")],
            ttps=[("T1566", "T1566 Phishing")],
        )
        article_ids.append(a.id)
    return article_ids


async def _attach_iocs(session: AsyncSession, article_ids: list[int]) -> None:
    ioc_repo = AsyncIndicatorRepo(session)
    await ioc_repo.upsert(
        type="domain",
        value="evil-apt41.example",
        source_url="https://example.com/campaign-0",
        source_name="Source0",
        article_id=article_ids[0],
    )
    await AsyncArticleCveRepo(session).add_many(article_ids[1], ["CVE-2026-9001"], "t")


async def test_get_recent_campaigns_builds_enriched_campaign(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    article_ids = await _seed_campaign_articles(async_db_session)
    await _attach_iocs(async_db_session, article_ids)
    async_db_session.add(
        CveTracker(
            cve_id="CVE-2026-9001",
            client_id="default",
            tech="ManufacturingSoft",
            cve_score=9.1,
            cve_severity="CRITICAL",
            cisa_kev=True,
        )
    )
    await async_db_session.flush()

    campaigns = await campaign_service.get_recent_campaigns(
        async_db_session, days=7, client_id="default", min_size=2
    )

    assert len(campaigns) == 1
    c = campaigns[0]
    assert c["size"] == 2
    assert c["dominant_tas"] == ["Apt41"]
    assert c["dominant_industries"] == ["Manufacturing"]
    assert c["dominant_countries"] == ["US"]
    assert any("T1566" in t for t in c["attack_techniques"])
    assert c["cve_ids"] == ["CVE-2026-9001"]
    assert any(i["value"] == "evil-apt41.example" for i in c["iocs"])

    # kill chain (pure, wired)
    assert "initial_access" in c["kill_chain"]["phases_covered"]

    # severity (butuh CveTracker CISA KEV -> bonus tinggi)
    assert "severity_score" in c
    assert c["severity_score"] > 0
    assert c["severity_label"] in {"critical", "high", "medium", "low"}

    # cve prioritization wired
    assert c["prioritized_cves"]
    assert c["prioritized_cves"][0]["cve_id"] == "CVE-2026-9001"
    assert c["prioritized_cves"][0]["cisa_kev"] is True

    # diamond model wired (TA profile gak ada -> tetep kebentuk, kosong)
    assert "diamond_model" in c
    assert c["diamond_model"]["adversary"]["threat_actors"] == ["Apt41"]

    # PIR matching + related campaigns wired (kosong, cuma 1 campaign)
    assert c["matched_pirs"] == []
    assert c["related_campaigns"] == []

    # `_articles_raw` internal gak bocor ke response
    assert "_articles_raw" not in c


async def test_get_recent_campaigns_too_few_articles_returns_empty(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    repo = AsyncArticleRepo(async_db_session)
    await repo.upsert(
        url="https://example.com/solo", title="Solo article", source="A", posted_on=_TODAY
    )

    campaigns = await campaign_service.get_recent_campaigns(async_db_session, days=7)
    assert campaigns == []


async def test_get_recent_campaigns_uses_diamond_model_ta_profile(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    await _seed_campaign_articles(async_db_session)
    await AsyncTAProfileRepo(async_db_session).save_profile(
        "Apt41",
        {
            "identity": {"actor_type": "state-sponsored", "sponsoring_nation": "China"},
            "capability_assessment": {"sophistication_level": "nation-state"},
        },
    )

    campaigns = await campaign_service.get_recent_campaigns(async_db_session, days=7, min_size=2)
    assert len(campaigns) == 1
    dm = campaigns[0]["diamond_model"]
    assert dm["adversary"]["sophistication"] == "nation-state"
    assert dm["adversary"]["sponsoring_nations"] == ["China"]


async def test_get_recent_campaigns_matches_active_pir(async_db_session: AsyncSession) -> None:
    await _ensure_clients(async_db_session)
    await _seed_campaign_articles(async_db_session)
    async_db_session.add(
        PIRRequirement(
            title="Track Apt41 activity",
            client_id="default",
            status="active",
            criteria={"threat_actors": ["Apt41"]},
        )
    )
    await async_db_session.flush()

    campaigns = await campaign_service.get_recent_campaigns(
        async_db_session, days=7, client_id="default", min_size=2
    )
    assert len(campaigns) == 1
    matched = campaigns[0]["matched_pirs"]
    assert len(matched) == 1
    assert matched[0]["title"] == "Track Apt41 activity"


async def test_get_recent_campaigns_links_related_campaigns_by_shared_actor(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    await _seed_campaign_articles(async_db_session)  # Apt41, 2 artikel

    # kelompok kedua, TA SAMA (Apt41) tapi vocab judul beda total -- gak
    # masuk cluster yang sama (cosine similarity lintas grup ~0), tapi
    # TA overlap bikin `related_campaigns` link.
    repo = AsyncArticleRepo(async_db_session)
    second_titles = [
        "Lazarus deploys ransomware payload against victims alpha",
        "Lazarus deploys ransomware payload against victims beta",
    ]
    for i, title in enumerate(second_titles):
        a = await repo.upsert(
            url=f"https://example.com/second-{i}",
            title=title,
            source=f"Second{i}",
            posted_on=_TODAY,
        )
        await repo.set_enrichment(a, threat_actors=["Apt41"])

    campaigns = await campaign_service.get_recent_campaigns(async_db_session, days=7, min_size=2)
    assert len(campaigns) == 2
    for c in campaigns:
        assert len(c["related_campaigns"]) == 1
        assert c["related_campaigns"][0]["link_type"] == "same_actor"


# --- jendela tanggal eksplisit (recap mingguan, #21 PR 2) ----------------------------------------


async def _seed_pair(
    session: AsyncSession, titles: list[str], actor: str, posted_on: datetime.date, tag: str
) -> None:
    repo = AsyncArticleRepo(session)
    for i, title in enumerate(titles):
        a = await repo.upsert(
            url=f"https://example.com/{tag}-{i}",
            title=title,
            source=f"{tag}{i}",
            posted_on=posted_on,
        )
        await repo.set_enrichment(a, threat_actors=[actor])


_OTHER_TITLES = [
    "Lazarus deploys ransomware payload against victims alpha",
    "Lazarus deploys ransomware payload against victims beta",
]


async def test_get_recent_campaigns_with_a_window_clusters_that_period_not_the_last_days(
    async_db_session: AsyncSession,
) -> None:
    """Dulu jendelanya selalu `days` terakhir dari HARI INI, jadi recap pekan yang di-backfill
    mendapat klaster pekan saat ia dijalankan."""
    await _ensure_clients(async_db_session)
    old = _TODAY - datetime.timedelta(days=30)
    # Judul sama di kedua periode (yang terbukti lolos ambang 0.75 untuk korpus dua dokumen);
    # pembedanya aktor, jadi jelas klaster periode mana yang terbaca.
    await _seed_pair(async_db_session, _TITLES, "Apt41", old, "old")
    await _seed_pair(async_db_session, _TITLES, "Lazarus", _TODAY, "now")

    last_days = await campaign_service.get_recent_campaigns(async_db_session, days=7, min_size=2)
    old_week = await campaign_service.get_recent_campaigns(
        async_db_session,
        min_size=2,
        start=old - datetime.timedelta(days=3),
        end=old + datetime.timedelta(days=3),
    )

    assert [c["dominant_tas"] for c in last_days] == [["Lazarus"]]
    assert [c["dominant_tas"] for c in old_week] == [["Apt41"]]


async def test_get_recent_campaigns_end_alone_counts_days_back_from_end_not_from_today(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    old = _TODAY - datetime.timedelta(days=30)
    await _seed_pair(async_db_session, _TITLES, "Apt41", old, "old")

    inside = await campaign_service.get_recent_campaigns(
        async_db_session, days=7, min_size=2, end=old + datetime.timedelta(days=2)
    )
    outside = await campaign_service.get_recent_campaigns(
        async_db_session, days=1, min_size=2, end=old + datetime.timedelta(days=5)
    )

    assert len(inside) == 1
    assert outside == []


async def test_get_recent_campaigns_warns_when_the_article_cap_truncates_the_window(
    async_db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _ensure_clients(async_db_session)
    await _seed_pair(async_db_session, _TITLES, "Apt41", _TODAY, "cap")
    await _seed_pair(async_db_session, _OTHER_TITLES[:1], "Lazarus", _TODAY, "cap-extra")
    monkeypatch.setattr(campaign_service, "_ARTICLE_CAP", 2)

    with structlog.testing.capture_logs() as logs:
        await campaign_service.get_recent_campaigns(async_db_session, days=7, min_size=2)

    [warning] = [e for e in logs if e["event"] == "campaign_article_cap_hit"]
    assert warning["log_level"] == "warning"
    assert (warning["cap"], warning["articles_in_window"]) == (2, 3)


async def test_get_recent_campaigns_does_not_warn_when_the_window_fits_under_the_cap(
    async_db_session: AsyncSession,
) -> None:
    await _ensure_clients(async_db_session)
    await _seed_pair(async_db_session, _TITLES, "Apt41", _TODAY, "fits")

    with structlog.testing.capture_logs() as logs:
        await campaign_service.get_recent_campaigns(async_db_session, days=7, min_size=2)

    assert [e for e in logs if e["event"] == "campaign_article_cap_hit"] == []
