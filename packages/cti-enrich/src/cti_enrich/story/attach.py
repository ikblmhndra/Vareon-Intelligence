"""Jembatan resolver story <-> DB untuk pipeline (P3, spec 4.1-4.2).

`resolve_story` jalan di SESI SENDIRI, bukan sesi utama pipeline: sesi utama memegang kunci URL
(`_known_article`) sepanjang panggilan LLM, dan commit lebih awal di sana akan melepas kunci itu.
Di sesi sendiri kunci story cuma dipegang beberapa milidetik (lock -> kandidat -> resolve ->
create -> commit), jadi artikel kedua dari satu gelombang berita sudah melihat story yang dibuat
artikel pertama walau lead-nya masih di-enrich.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from cti_core.config import StorySettings
from cti_core.db.engine import sync_session
from cti_core.db.repositories.story import StoryRepo

from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.extract_cves import extract_cves

log = logging.getLogger(__name__)
_embedding_unavailable_logged = False


@dataclass(frozen=True)
class StoryLink:
    story_id: int
    rule: Literal["lead", "cve", "title_exact", "title", "title_embedding"]
    """`lead` = story baru dibuat untuk artikel ini; selain itu aturan resolver yang cocok."""
    inherited: dict[str, Any] | None
    """`stories.classify` saat resolve; `None` = belum bisa diwariskan (lead masih jalan, atau
    semua anggotanya Tier 0), jadi artikel di-enrich penuh."""
    lead_article_id: int | None
    cve_ids: frozenset[str]
    """CVE KUNCI artikel (`key_cves`), bukan semua CVE-nya: roundup tidak boleh menggabungkan
    daftar CVE panjangnya ke story."""


def resolve_story(
    *, title: str, source: str, text: str, now: datetime, cfg: StorySettings
) -> StoryLink:
    """Story tempat artikel ini bergabung; kalau tidak ada yang cocok, story baru (kosong,
    `article_count=0`) dibuat dan di-commit di sini. Kalau task gagal sesudahnya, replay
    menemukan story kosong itu lagi lewat aturan judul persis."""
    # Import lambat: resolver menarik scikit-learn/scipy, dan `cti_enrich.pipeline` harus tetap
    # bisa di-import tanpa extra `nlp` (`test_enrich_pipeline_imports_without_nlp_extra`;
    # scipy meledak saat `torch` diblok di `sys.modules`).
    from cti_enrich.story.resolver import ArticleKeys, key_cves, resolve

    cves = key_cves(extract_cves(f"{title} {text}"), cfg.max_key_cves)
    embed = _embedding_fn(cfg)
    with sync_session() as session:
        repo = StoryRepo(session)
        repo.lock()
        candidates = repo.candidates(
            now, window_hours=cfg.window_hours, max_age_days=cfg.max_age_days
        )
        match = resolve(
            ArticleKeys(title=title, source=source, cve_ids=cves, at=now),
            candidates,
            cfg,
            embedding_similarity=embed,
        )
        if match is None:
            story_id = repo.create(title=title, source=source, cve_ids=set(cves), now=now)
            return StoryLink(story_id, "lead", None, None, cves)
        classify, lead_article_id = repo.get_inherit(match.story_id)
        rule = match.rule
        if repo.own_empty_lead(match.story_id, title=title, source=source):
            # Story kosong buatan percobaan sebelumnya artikel ini (replay): bukan follow-up.
            rule = "lead"
        return StoryLink(match.story_id, rule, classify, lead_article_id, cves)


def _embedding_fn(cfg: StorySettings) -> Callable[[str, list[str]], list[float]] | None:
    """Fungsi embedding untuk resolver, hanya bila diaktifkan. Model tak ada di disk (image
    tanpa extra `nlp`) = resolve tanpa embedding, dicatat sekali per proses."""
    global _embedding_unavailable_logged
    if cfg.embedding_similarity <= 0:
        return None
    # Import lambat: fastembed hanya ada di image worker-nlp.
    from cti_enrich.relevance.embedder import EmbedderUnavailable, get_embedder
    from cti_enrich.story.similarity import embedding_similarity

    try:
        embedder = get_embedder()
    except EmbedderUnavailable as exc:
        if not _embedding_unavailable_logged:
            _embedding_unavailable_logged = True
            log.warning("story_embedding_unavailable", extra={"error": str(exc)})
        return None
    return lambda query, titles: embedding_similarity(query, titles, embedder)


def classify_from_story(
    data: dict[str, Any], *, story_id: int, rule: str, lead_article_id: int | None
) -> ClassifyResult:
    """`ClassifyResult` warisan dari `stories.classify`; asal-usulnya dicatat di audit."""
    names = {f.name for f in dataclasses.fields(ClassifyResult)} - {"audit"}
    return ClassifyResult(
        **{k: v for k, v in data.items() if k in names},
        audit={"inherited_from_story": story_id, "lead_article_id": lead_article_id, "match": rule},
    )


def classify_to_story(result: ClassifyResult) -> dict[str, Any]:
    """Bentuk `stories.classify`: semua field `ClassifyResult` kecuali `audit`."""
    data = dataclasses.asdict(result)
    data.pop("audit")
    return data
