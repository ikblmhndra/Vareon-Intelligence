"""AsyncMitreHeatmapRepo -- port `ScraperNewsWeb/app/services/
mitre_heatmap_service.py`. Fase 7.3 (router `mitre`, Bagian 3). Baca dari
`articles` + mention teknik/aktor/sektor (`mention_rows`, P7c; dulu `article_ttps`/
`article_threat_actors`/`article_industries`) -- BUKAN dari katalog `attack_techniques`
(Fase 7.3 Bagian 3 juga, tapi domain beda): heatmap ini ngukur TTP yang
BENERAN keobservasi di pemberitaan (mention teknik, hasil ekstraksi LLM
Fase 5), bukan katalog referensi MITRE. Dua sumber data yang gak saling
gantiin, sama kayak `source_score_service.py` vs `source_score_db_service.py`
di Bagian 2.

`view` ("ta" | "industry") nentuin tipe entitas "baris" heatmap: aktor (`intrusion-set`) atau
sektor (`identity`); nama baris = `entities.name` (alias satu entitas = satu baris)."""

from __future__ import annotations

import datetime
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cti_core.config import platform_name
from cti_core.db.models.article import Article
from cti_core.db.repositories.entity import ACTOR, SECTOR, TECHNIQUE, mention_rows
from cti_core.db.repositories.ttp_catalog import canonical_ttp_name


def _row_type(view: str) -> str:
    return SECTOR if view == "industry" else ACTOR


class AsyncMitreHeatmapRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_heatmap(
        self,
        *,
        view: str,
        days: int,
        top_rows: int = 15,
        top_ttps: int = 20,
        ttp_sources: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """`ttp_sources` (P4): hanya hitung baris TTP dengan sumber itu (explicit/keyword/llm)."""
        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        count_articles = func.count(func.distinct(Article.id))
        r = mention_rows(_row_type(view))
        t = mention_rows(TECHNIQUE)
        source_cond = [t.c.method.in_(ttp_sources)] if ttp_sources else []

        rows_stmt = (
            select(r.c.name, count_articles)
            .join(Article, r.c.article_id == Article.id)
            .where(Article.posted_on >= cutoff)
            .group_by(r.c.name)
        )
        top_rows_result = await self.session.execute(
            rows_stmt.order_by(count_articles.desc()).limit(top_rows)
        )
        row_names = [r[0] for r in top_rows_result.all()]

        # GROUP BY ID SAJA, nama kanonik dari katalog ATT&CK (QA BUG-C01: dulu
        # group by (id, nama) -> satu ID dgn 3 nama LLM = 3 kolom angka sama).
        top_ttps_result = await self.session.execute(
            select(t.c.external_id, canonical_ttp_name(t.c.external_id, t.c.name), count_articles)
            .join(Article, t.c.article_id == Article.id)
            .where(Article.posted_on >= cutoff, *source_cond)
            .group_by(t.c.external_id)
            .order_by(count_articles.desc())
            .limit(top_ttps)
        )
        ttp_rows = top_ttps_result.all()
        ttp_list = [{"id": tid, "name": name} for tid, name, _ in ttp_rows]
        ttp_ids = [t["id"] for t in ttp_list]

        if not row_names or not ttp_ids:
            return {"rows": [], "ttps": [], "matrix": [], "max_val": 0}

        co_stmt = (
            select(r.c.name, t.c.external_id, count_articles)
            .select_from(Article)
            .join(r, r.c.article_id == Article.id)
            .join(t, t.c.article_id == Article.id)
            .where(
                Article.posted_on >= cutoff,
                r.c.name.in_(row_names),
                t.c.external_id.in_(ttp_ids),
                *source_cond,
            )
            .group_by(r.c.name, t.c.external_id)
        )
        co_result = await self.session.execute(co_stmt)
        co_map = {(row, tid): count for row, tid, count in co_result.all()}

        matrix = [[co_map.get((row, tid), 0) for tid in ttp_ids] for row in row_names]
        max_val = max((max(row) for row in matrix if row), default=0)

        return {"rows": row_names, "ttps": ttp_list, "matrix": matrix, "max_val": max_val}

    async def get_navigator_layer(self, *, view: str, days: int) -> dict[str, Any]:
        cutoff = datetime.date.today() - datetime.timedelta(days=days)
        t = mention_rows(TECHNIQUE)
        result = await self.session.execute(
            select(
                t.c.external_id,
                func.min(t.c.name),
                func.count(func.distinct(Article.id)),
            )
            .join(Article, t.c.article_id == Article.id)
            .where(Article.posted_on >= cutoff)
            .group_by(t.c.external_id)
            .order_by(func.count(func.distinct(Article.id)).desc())
            .limit(500)
        )
        raw = result.all()
        max_count = max((c for _, _, c in raw), default=1) or 1

        techniques = []
        for tid, _name, count in raw:
            if not tid or not tid.startswith("T"):
                continue
            score = round((count / max_count) * 100)
            techniques.append(
                {
                    "techniqueID": tid,
                    "score": score,
                    "comment": f"Observed {count} time(s) in last {days} days",
                    "enabled": True,
                    "showSubtechniques": False,
                }
            )

        view_label = "Threat Actor" if view == "ta" else "Industry"
        label = f"{platform_name()} — {view_label} View ({days}d)"
        return {
            "name": label,
            "versions": {"attack": "14", "navigator": "4.9", "layer": "4.5"},
            "domain": "enterprise-attack",
            "description": f"Generated from scraped articles over the last {days} days.",
            "techniques": techniques,
            "gradient": {"colors": ["#ffe766", "#ff6666"], "minValue": 0, "maxValue": 100},
            "legendItems": [],
            "metadata": [],
            "showTacticRowBackground": True,
            "tacticRowBackground": "#1a1a2e",
            "selectTechniquesAcrossTactics": True,
        }

    async def get_ttp_articles(
        self,
        *,
        ttp_id: str,
        row: str,
        view: str,
        days: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Article], int]:
        cutoff = datetime.date.today() - datetime.timedelta(days=days)

        # `row` = nama baris heatmap (`entities.name`, keluaran `get_heatmap`): cocok per nama.
        r = mention_rows(_row_type(view))
        t = mention_rows(TECHNIQUE)
        base = (
            select(Article)
            .join(r, r.c.article_id == Article.id)
            .join(t, t.c.article_id == Article.id)
            .where(Article.posted_on >= cutoff, r.c.name == row, t.c.external_id == ttp_id)
            .distinct()
        )

        total = (
            await self.session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        list_stmt = (
            base.order_by(Article.posted_on.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        result = await self.session.execute(list_stmt)
        return list(result.scalars().unique().all()), total
