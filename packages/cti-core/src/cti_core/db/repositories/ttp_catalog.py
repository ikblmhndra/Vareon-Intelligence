"""Jembatan DB <-> `cti_core.attack_ttp` (QA BUG-C01/BUG-04/BUG-B8):

- `load_catalog()` / `load_catalog_async()`: bangun `TechniqueCatalog` dari
  `attack_techniques` + `attack_tactics` + `attack_technique_aliases`.
  Tanpa cache -- dipanggil sekali per artikel di enrichment (sesudah
  beberapa panggilan LLM yang makan detik), ~1-2k baris kecil, murah.
- `canonical_ttp_name()`: ekspresi nama kanonik buat agregasi GROUP BY
  `ArticleTTP.ttp_id` (heatmap/dashboard/PIR). Nama dari katalog ATT&CK,
  fallback `min(ttp_name)` kalau ID gak ada di katalog (belum sync).
- `remap_article_ttps()`: backfill baris `article_ttps` lama ke aturan
  normalisasi -- dipanggil `tools/ops/remap_article_ttps.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from cti_core.attack_ttp import NormalizedTTP, TechniqueCatalog, normalize_ttps
from cti_core.db.models.article import Article, ArticleTTP
from cti_core.db.models.attack import AttackTactic, AttackTechnique, AttackTechniqueAlias
from cti_core.db.repositories.article import apply_ttps


def _catalog_statements() -> tuple[Any, Any, Any]:
    techniques = select(AttackTechnique.attack_id, AttackTechnique.name, AttackTechnique.domains)
    tactics = select(AttackTactic.name)
    target = aliased(AttackTechnique)
    revoked = select(
        AttackTechniqueAlias.attack_id, AttackTechniqueAlias.name, target.attack_id
    ).join(target, target.stix_id == AttackTechniqueAlias.revoked_by_stix_id)
    return techniques, tactics, revoked


def _build(techniques: Any, tactics: Any, revoked: Any) -> TechniqueCatalog:
    return TechniqueCatalog.build(
        techniques=[(tid, name, domains) for tid, name, domains in techniques],
        tactics=[name for (name,) in tactics],
        revoked=[(old_id, old_name, new_id) for old_id, old_name, new_id in revoked],
    )


def load_catalog(session: Session) -> TechniqueCatalog:
    tech_stmt, tactic_stmt, revoked_stmt = _catalog_statements()
    return _build(
        session.execute(tech_stmt).all(),
        session.execute(tactic_stmt).all(),
        session.execute(revoked_stmt).all(),
    )


async def load_catalog_async(session: AsyncSession) -> TechniqueCatalog:
    tech_stmt, tactic_stmt, revoked_stmt = _catalog_statements()
    return _build(
        (await session.execute(tech_stmt)).all(),
        (await session.execute(tactic_stmt)).all(),
        (await session.execute(revoked_stmt)).all(),
    )


def canonical_ttp_name() -> Any:
    """Kolom nama buat query yang GROUP BY `ArticleTTP.ttp_id` -- JANGAN
    group by `ttp_name` juga (itu akar kolom dobel di heatmap: satu ID,
    beberapa nama karangan LLM = beberapa grup)."""
    catalog_name = (
        select(func.min(AttackTechnique.name))
        .where(AttackTechnique.attack_id == ArticleTTP.ttp_id)
        .correlate(ArticleTTP)
        .scalar_subquery()
    )
    return func.coalesce(catalog_name, func.min(ArticleTTP.ttp_name))


@dataclass
class RemapStats:
    articles_scanned: int = 0
    articles_changed: int = 0
    rows_before: int = 0
    rows_after: int = 0
    examples: list[str] = field(default_factory=list)
    """Contoh perubahan (maks 20) buat ditampilkan di dry-run."""


_SOURCE_PRIORITY = {"explicit": 0, "llm": 1, "keyword": 2}
"""Urutan kekuatan `source` saat dua baris lama menyatu ke satu ID: explicit > llm > keyword."""


def _carry_sources(
    normalized: list[NormalizedTTP], rows: list[ArticleTTP], catalog: TechniqueCatalog
) -> list[NormalizedTTP]:
    """`normalize_ttps` tidak tahu `source`/`evidence` (selalu default `llm`); tanpa ini remap
    menimpa baris explicit/keyword Tier 1 jadi `llm`. Tiap baris lama di-resolve sendiri untuk
    mendapat ID akhirnya, lalu baris dengan `source` terkuat (urutan baris menang bila seri)
    menyumbang `source`/`evidence`-nya ke hasil dengan ID itu."""
    best: dict[str, ArticleTTP] = {}
    for r in rows:
        rid = r.extracted_id or r.ttp_id
        if not rid:
            continue
        hit = normalize_ttps([(rid, r.extracted_name or r.ttp_name)], catalog)
        if not hit:
            continue
        tid = hit[0].ttp_id
        cur = best.get(tid)
        if cur is None or _SOURCE_PRIORITY.get(r.source, 9) < _SOURCE_PRIORITY.get(cur.source, 9):
            best[tid] = r
    return [
        n._replace(source=best[n.ttp_id].source, evidence=best[n.ttp_id].evidence)
        if n.ttp_id in best
        else n
        for n in normalized
    ]


def remap_article_ttps(
    session: Session, catalog: TechniqueCatalog, *, batch_size: int = 500
) -> RemapStats:
    """Normalisasi ulang SEMUA `article_ttps` pakai `catalog`. Sumber =
    teks asli LLM (`extracted_id`/`extracted_name`) kalau ada, kalau belum
    (baris sebelum kolom itu ada) = `ttp_id`/`ttp_name` yang tersimpan
    (itu memang pasangan mentah LLM dulu). Idempoten: jalan ulang = hasil
    sama; artikel yang hasilnya gak berubah gak disentuh.

    Cuma `flush()` -- commit/rollback (dry-run) urusan caller."""
    if catalog.is_empty:
        raise ValueError(
            "Katalog ATT&CK kosong -- jalankan sync ATT&CK dulu (ATT&CK DB > Sync), "
            "remap tanpa katalog cuma akan menyalin data mentah."
        )
    stats = RemapStats()
    last_id = 0
    with_ttps = select(ArticleTTP.article_id).distinct().scalar_subquery()
    while True:
        articles = (
            session.execute(
                select(Article)
                .where(Article.id > last_id, Article.id.in_(with_ttps))
                .order_by(Article.id)
                .limit(batch_size)
            )
            .scalars()
            .all()
        )
        if not articles:
            break
        for article in articles:
            last_id = article.id
            stats.articles_scanned += 1
            rows = sorted(article.ttps, key=lambda r: r.id)
            stats.rows_before += len(rows)
            raw = [
                (r.extracted_id or r.ttp_id, r.extracted_name or r.ttp_name)
                for r in rows
                if (r.extracted_id or r.ttp_id)
            ]
            normalized = _carry_sources(normalize_ttps(raw, catalog), rows, catalog)
            stats.rows_after += len(normalized)
            current = [
                NormalizedTTP(
                    r.ttp_id, r.ttp_name, r.extracted_id, r.extracted_name, r.source, r.evidence
                )
                for r in rows
            ]
            if sorted(current) == sorted(normalized):
                continue
            stats.articles_changed += 1
            if len(stats.examples) < 20:
                before = ", ".join(f"{r.ttp_id} {r.ttp_name!r}" for r in rows)
                after = ", ".join(f"{n.ttp_id} {n.ttp_name!r}" for n in normalized)
                stats.examples.append(f"article {article.id}: [{before}] -> [{after}]")
            apply_ttps(article, normalized)
        session.flush()
        session.expunge_all()  # jaga identity map tetap kecil di tabel besar
    return stats
