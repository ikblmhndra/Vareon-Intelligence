"""Seksi "Relevance model" di `GET /api/data-health` (P5, Task 11): angka dibaca dari baris model
aktif dan `raw_enrichment->'relevance'` di `articles` + `rejected_articles`."""

from __future__ import annotations

import datetime

from cti_core.db.models.article import RejectedArticle
from cti_core.db.models.relevance import RelevanceModel
from cti_core.db.repositories.article import AsyncArticleRepo
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

_BP = "Security Technology & Best Practices"


async def _article(
    session: AsyncSession,
    n: int,
    *,
    decision: str,
    in_band: bool,
    age: datetime.timedelta,
    best_practice: bool = False,
    embedding: bool = False,
) -> None:
    a = await AsyncArticleRepo(session).upsert(
        url=f"https://rel.example/a{n}", title=f"A{n}", source="S"
    )
    a.news_type = _BP if best_practice else "Threat News"
    a.created_at = datetime.datetime.now(datetime.UTC) - age
    a.raw_enrichment = {
        "relevance": {
            "model_id": 1,
            "probs": [0.1, 0.1, 0.8],
            "in_band": in_band,
            "decision": decision,
        }
    }
    if embedding:
        a.story_match = "title_embedding"
    await session.flush()


async def test_data_health_relevance_section(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    await api_session.execute(delete(RelevanceModel))
    now = datetime.datetime.now(datetime.UTC)
    api_session.add(
        RelevanceModel(
            status="active",
            feature_version="f",
            n_examples=1200,
            class_counts={},
            metrics={"agreement": 0.97, "band_share": 0.3},
            gate_state="gate",
            gate_changed_at=now - datetime.timedelta(days=2),
        )
    )
    h = datetime.timedelta(hours=1)
    d = datetime.timedelta(days=1)
    # shadow dalam band: 1 setuju, 1 best practice
    await _article(api_session, 1, decision="shadow", in_band=True, age=2 * d)
    await _article(api_session, 2, decision="shadow", in_band=True, age=2 * d, best_practice=True)
    # audit dalam band: 2 setuju, 1 tidak (+1 audit lama di luar jendela band)
    await _article(api_session, 3, decision="audit", in_band=True, age=h)
    await _article(api_session, 4, decision="audit", in_band=True, age=2 * h)
    await _article(api_session, 5, decision="audit", in_band=True, age=3 * h, best_practice=True)
    await _article(api_session, 6, decision="audit", in_band=True, age=20 * d)
    # gated: satu 2 jam lalu, satu 3 hari lalu; band tengah: satu artikel
    await _article(api_session, 7, decision="gated", in_band=True, age=2 * h)
    await _article(api_session, 8, decision="gated", in_band=True, age=3 * d)
    await _article(api_session, 9, decision="llm", in_band=False, age=h)
    await _article(api_session, 10, decision="llm", in_band=False, age=h, embedding=True)
    api_session.add_all(
        [
            RejectedArticle(
                url="https://rel.example/r1",
                url_hash=f"{1:064d}",
                title="R1",
                source="S",
                reason="x",
                rejected_at=now - h,
                raw_enrichment={"relevance": {"in_band": True, "decision": "shadow"}},
            ),
            RejectedArticle(
                url="https://rel.example/r2",
                url_hash=f"{2:064d}",
                title="R2",
                source="S",
                reason="x",
                rejected_at=now - h,
                raw_enrichment={"relevance": {"in_band": False, "decision": "llm"}},
            ),
        ]
    )
    await api_session.flush()

    body = (await api_client.get("/api/data-health", headers=auth_header(role="analyst"))).json()
    rel = body["relevance"]
    assert rel["mode"] == "auto"
    assert rel["gate_state"] == "gate"
    assert rel["gate_changed_at"] is not None
    assert rel["model_trained_at"] is not None
    assert rel["n_examples"] == 1200
    assert rel["holdout_agreement"] == 0.97
    assert rel["holdout_band_share"] == 0.3
    # band 14 hari: shadow 2 + audit 3 + rejected shadow 1 = 6; setuju 1 + 2 + 0 = 3
    assert rel["band_titles_14d"] == 6
    assert rel["band_agreement_14d"] == 0.5
    # di luar band: artikel 9, 10 + rejected r2
    assert rel["middle_band_14d"] == 3
    # audit terakhir (tanpa batas waktu): 4 baris, 3 setuju
    assert rel["audit_samples"] == 4
    assert rel["audit_agreement"] == 0.75
    assert rel["classify_avoided_24h"] == 1
    assert rel["classify_avoided_7d"] == 2
    assert body["llm"]["stories_24h"]["by_embedding"] >= 1


async def test_data_health_relevance_without_active_model(
    api_client: AsyncClient, api_session: AsyncSession, auth_header, fake_redis
) -> None:
    await api_session.execute(delete(RelevanceModel))
    rel = (await api_client.get("/api/data-health", headers=auth_header(role="analyst"))).json()[
        "relevance"
    ]
    assert rel["gate_state"] is None
    assert rel["n_examples"] is None
    assert rel["holdout_agreement"] is None
    assert rel["band_agreement_14d"] is None
    assert rel["audit_agreement"] is None
    assert rel["classify_avoided_7d"] == 0
