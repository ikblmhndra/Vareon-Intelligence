"""Jembatan DB <-> `cti_core.attack_ttp` (QA BUG-C01/BUG-04/BUG-B8):

- `load_catalog()` / `load_catalog_async()`: bangun `TechniqueCatalog` dari
  `attack_techniques` + `attack_tactics` + `attack_technique_aliases`.
  Tanpa cache -- dipanggil sekali per artikel di enrichment (sesudah
  beberapa panggilan LLM yang makan detik), ~1-2k baris kecil, murah.
- `canonical_ttp_name()`: ekspresi nama kanonik buat agregasi GROUP BY
  id teknik (heatmap/dashboard/PIR). Nama dari katalog ATT&CK,
  fallback nama entitas teknik kalau ID gak ada di katalog (belum sync).
- `remap_article_ttps()`: backfill mention teknik lama (dulu `article_ttps`) ke aturan
  normalisasi -- dipanggil `tools/ops/remap_article_ttps.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, aliased

from cti_core.attack_ttp import NormalizedTTP, TechniqueCatalog, normalize_ttps
from cti_core.db.models.article import Article
from cti_core.db.models.attack import AttackTactic, AttackTechnique, AttackTechniqueAlias
from cti_core.db.repositories.article import apply_ttps
from cti_core.db.repositories.entity import TECHNIQUE, mention_rows


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


def canonical_ttp_name(ttp_id: Any, ttp_name: Any) -> Any:
    """Kolom nama buat query yang GROUP BY id teknik (`ttp_id`, kolom `external_id` dari
    `mention_rows`) -- JANGAN group by nama juga (itu akar kolom dobel di heatmap: satu ID,
    beberapa nama karangan LLM = beberapa grup). Nama katalog ATT&CK menang; tanpa katalog
    (belum sync) nama entitas teknik (`ttp_name`, P7c: satu entitas per id)."""
    catalog_name = (
        select(func.min(AttackTechnique.name))
        .where(AttackTechnique.attack_id == ttp_id)
        .correlate_except(AttackTechnique)
        .scalar_subquery()
    )
    return func.coalesce(catalog_name, func.min(ttp_name))


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


class _TTPRow(NamedTuple):
    """Satu mention teknik artikel dalam bentuk baris `article_ttps` lama: `ttp_id`/`ttp_name`
    dari entitas teknik (P7c: nama = `entities.name`), `extracted_*` dari `extracted`,
    `source` = method mention."""

    id: int
    ttp_id: str
    ttp_name: str
    extracted_id: str | None
    extracted_name: str | None
    source: str
    evidence: str | None


def _ttp_rows(article: Article) -> list[_TTPRow]:
    rows = []
    for m in article.mentions_of(TECHNIQUE):
        ext = m.extracted or {}
        # method selain llm/explicit/keyword (mis. `legacy`) dibaca `llm`: itu satu-satunya
        # sumber teknik lama tanpa label, dan `apply_ttps` hanya menerima tiga sumber Tier 1.
        source = m.method if m.method in _SOURCE_PRIORITY else "llm"
        rows.append(
            _TTPRow(
                m.id,
                m.entity.external_id or "",
                m.entity.name,
                ext.get("extracted_id"),
                ext.get("extracted_name"),
                source,
                m.evidence,
            )
        )
    return sorted(rows, key=lambda r: r.id)


def _identity(n: NormalizedTTP) -> tuple[Any, ...]:
    """Kunci perbandingan "hasil remap sama dengan yang tersimpan": tanpa nama teknik, karena
    nama tersimpan = nama entitas (satu per id), bukan nama yang dikirim remap."""
    return (n.ttp_id, n.extracted_id, n.extracted_name, n.source, n.evidence)


def _carry_sources(
    normalized: list[NormalizedTTP], rows: list[_TTPRow], catalog: TechniqueCatalog
) -> list[NormalizedTTP]:
    """`normalize_ttps` tidak tahu `source`/`evidence` (selalu default `llm`); tanpa ini remap
    menimpa baris explicit/keyword Tier 1 jadi `llm`. Tiap baris lama di-resolve sendiri untuk
    mendapat ID akhirnya, lalu baris dengan `source` terkuat (urutan baris menang bila seri)
    menyumbang `source`/`evidence`-nya ke hasil dengan ID itu."""
    best: dict[str, _TTPRow] = {}
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
    """Normalisasi ulang SEMUA mention teknik artikel pakai `catalog`. Sumber =
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
    t = mention_rows(TECHNIQUE)
    with_ttps = select(t.c.article_id).where(t.c.article_id.is_not(None)).distinct()
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
            rows = _ttp_rows(article)
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
            if sorted(map(_identity, current)) == sorted(map(_identity, normalized)):
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
