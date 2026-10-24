"""Stage: SATU-SATUNYA penulis (plan §5: "persist satu-satunya penulis, dan
route_alerts terpisah TOTAL dari persist") -- gabungan `dbMongo.upsert_article`
+ `iocExtractor` hasil masuk field `iocs` + `update_cve_mention` dari
`nlp.py`. Dipanggil SEBELUM `stages/alert.py` (lihat `pipeline.py`) -- beda
dari `_sendAlert()` lama yang nulis DB di tengah/akhir proses kirim
Telegram, di sini urutannya kebalik: artikel HARUS udah tersimpan sebelum
alert dicoba, jadi kegagalan Telegram gak pernah bisa bikin artikel gak
kesimpen (lihat `cti_alerts.telegram` docstring).

Country role (`ArticleCountry.role`): map dari TIGA field lama
(`mentioned_countries`/`victim_countries`/`actor_countries`) ke skema
ternormalisasi. `actor` = SELALU dari GPT (`classify_result.actor_countries`,
konsisten kode lama -- gak pernah regex fallback). `victim` = GPT
(`classify_result.victim_countries`) kalau ada, else fallback ke negara
hasil regex/NER (`score_result.mentioned_countries`, cabang Regional/TA
Group -- port `nlp.py:612/657`; cabang Global gak punya fallback ini,
`victim_countries` GPT langsung dipakai apa adanya). `mentioned` = GABUNGAN
negara regex/NER + victim + actor -- persis `mentioned_countries` lama
(`nlp.py:351/551/611/656/702`: `regex_countries + gpt_victim_countries +
gpt_actor_countries`). Jadi satu negara bisa punya DUA baris (mis. `victim`
DAN `mentioned`) -- unique constraint-nya per (artikel, negara, role).

Dulu `mentioned` cuma SISA negara regex yang belum kepakai victim/actor --
padahal SEMUA pembacanya (filter `countries`, dropdown negara, Risk Matrix,
top-country dashboard, kampanye, STIX, newsletter) menganggap role ini =
field `mentioned_countries` lama. Akibatnya role ini nyaris selalu kosong:
Risk Matrix staging 0 sel (QA BUG-D4), dropdown negara cuma 4 kode. Artikel
lama dibetulkan `python -m cti_enrich.backfill`."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from cti_core.db.models.article import RejectedArticle
from cti_core.db.repositories.article import ArticleRepo, RejectedArticleRepo
from cti_core.db.repositories.ioc import IOCRepo
from cti_core.ioc.allowlist import allowlist_match
from cti_core.ioc.canonical import canonical
from sqlalchemy import delete

from cti_enrich.countries import country_code
from cti_enrich.stages.classify import resolve_industries
from cti_enrich.stages.extract_iocs import _get_allowlist
from cti_enrich.stages.extract_ttps import as_normalized

if TYPE_CHECKING:
    from cti_core.db.models.article import Article, RejectedArticle
    from sqlalchemy.orm import Session

    from cti_enrich.routing import RoutingResult
    from cti_enrich.stages.classify import ClassifyResult
    from cti_enrich.stages.extract_ttps import TtpResult
    from cti_enrich.stages.score import ScoreResult

_IOC_TYPE_MAP = {
    "ips": "ip",
    "urls": "url",
    "urls_with_path": "url",
    "domains": "domain",
    "emails": "email",
    "sha256": "sha256",
    "sha1": "sha1",
    "md5": "md5",
    "cves": "cve",
}


def _country_roles(
    classify_result: ClassifyResult, score_result: ScoreResult | None, *, is_global_branch: bool
) -> list[tuple[str, str]]:
    victims = classify_result.victim_countries or (
        [] if is_global_branch or score_result is None else score_result.mentioned_countries
    )
    actors = classify_result.actor_countries
    regex_countries = [] if score_result is None else score_result.mentioned_countries
    mentioned = list(dict.fromkeys([*regex_countries, *victims, *actors]))

    pairs: list[tuple[str, str]] = []
    for name in victims:
        code = country_code(name)
        if code:
            pairs.append((code, "victim"))
    for name in actors:
        code = country_code(name)
        if code:
            pairs.append((code, "actor"))
    for name in mentioned:
        code = country_code(name)
        if code:
            pairs.append((code, "mentioned"))
    return pairs


def _audit_fields(classify_result: ClassifyResult) -> dict[str, dict[str, object]]:
    return {"raw_enrichment": {"classify": classify_result.audit}} if classify_result.audit else {}


def persist(
    *,
    session: Session,
    url: str,
    title: str,
    source: str,
    scraper_id: str | None,
    posted_on: datetime.date | None,
    classify_result: ClassifyResult,
    score_result: ScoreResult | None,
    routing_result: RoutingResult,
    ttp_result: TtpResult | None,
    ioc_data: dict[str, list[str]],
    c2_indicator: bool,
) -> Article:
    article_repo = ArticleRepo(session)
    article = article_repo.upsert(
        url=url,
        title=title,
        source=source,
        scraper_id=scraper_id,
        posted_on=posted_on,
        news_type=routing_result.news_type,
        confidence_score=round(classify_result.confidence * 100)
        if classify_result.confidence
        else None,
        confirmed_incident=bool(classify_result.confirmed_incident),
        incident_confidence=(
            round(classify_result.incident_confidence * 100)
            if classify_result.incident_confidence is not None
            else None
        ),
        victim_name=classify_result.victim_name,
        c2_indicator=c2_indicator,
        # Audit trail respons LLM mentah (`raw_enrichment`, lihat `ClassifyResult.audit`).
        # Cuma kalau ada isinya, supaya pemanggil tanpa audit gak mengosongkan yang lama.
        **_audit_fields(classify_result),
    )

    industries = resolve_industries(classify_result.industries_impacted)

    article_repo.set_enrichment(
        article,
        countries=_country_roles(
            classify_result, score_result, is_global_branch=routing_result.is_global_branch
        ),
        industries=industries,
        threat_actors=routing_result.threat_actors,
        ttps=[as_normalized(t) for t in ttp_result.techniques] if ttp_result else [],
    )

    ioc_repo = IOCRepo(session)
    allowlist = _get_allowlist(session)
    for key, values in ioc_data.items():
        ioc_type = _IOC_TYPE_MAP.get(key)
        if not ioc_type:
            continue
        for value in values:
            canon = canonical(ioc_type, value)
            ioc_repo.upsert(
                type=ioc_type,
                value=canon,
                source_url=url,
                source_name=source,
                article_id=article.id,
                suppression_reason=allowlist_match(ioc_type, canon, allowlist),
            )

    # Artikel ini sekarang DITERIMA -- buang catatan "ditolak"/"gagal di-enrich"
    # (`rejected_articles`) untuk URL yang sama kalau ada. Tanpa ini artikel yang
    # dulu `[enrichment_failed]` lalu berhasil di-replay muncul DUA kali: sebagai
    # artikel DAN sebagai "ditolak" di halaman Filtered Articles.
    session.execute(delete(RejectedArticle).where(RejectedArticle.url_hash == article.url_hash))
    return article


def persist_rejected(
    *,
    session: Session,
    url: str,
    title: str,
    source: str,
    scraper_id: str | None,
    posted_on: datetime.date | None,
    classify_result: ClassifyResult,
) -> RejectedArticle:
    """Tulis `rejected_articles` -- dipanggil `pipeline.py` pas
    `classify_result.related_cyber == False` (satu-satunya jalur reject
    sekarang). BARU di Fase 7.3 (router `filtered_articles.py`, keputusan
    eksplisit user buat gak diem-diemin) -- Fase 5 gak nulis apa pun buat
    artikel yang ditolak, cuma `return` dari `run_pipeline()`.

    Fungsi TERPISAH dari `persist()` (bukan cabang if/else di situ) --
    `persist()` kontraknya "artikel yang keterima, full enrichment", nulis
    row REJECTED gak punya country/industry/TTP/IOC apa pun buat diisi,
    nyampur dua kontrak beda di satu fungsi cuma bikin bingung."""
    return RejectedArticleRepo(session).upsert(
        url=url,
        title=title,
        source=source,
        scraper_id=scraper_id,
        posted_on=posted_on,
        reason=classify_result.reason,
        raw_enrichment=_audit_fields(classify_result).get("raw_enrichment"),
    )
