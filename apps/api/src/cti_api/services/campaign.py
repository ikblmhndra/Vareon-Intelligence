"""Port `cluster_service.py`'s `get_recent_campaigns()` -- Pipeline 2
dari "mesin cluster" (Fase 7.4 Grup A, 2026-09-23). TF-IDF UNION-FIND
clustering (threshold 0.75 tetap, BEDA dari Pipeline 1's greedy fixed-
centroid tunable) + enrichment kaya per-campaign (severity, prioritized
CVE, diamond model, kill chain, PIR matching, campaign links). Backing
`GET /api/clusters/recent` + `GET /api/intelligence/geopolitical`.

**NOL cache/persist** -- port apa adanya, legacy juga hitung ulang dari
nol tiap request (beda dari Pipeline 1 yang di-cache 900s + persist ke
tabel `clusters`). Lihat docstring `cti_api.services.cluster`.

Orkestrasi SEKUENSIAL (bukan `asyncio.gather` per-cluster kayak legacy)
-- satu `AsyncSession` gak aman dipakai concurrent, constraint yang
udah didokumentasikan berkali-kali sesi ini.

`iocs`/`cve_ids` per campaign: SATU sumber (`AsyncIOCRepo.
list_by_article_ids`, IOC apa pun termasuk `type="cve"`) -- gantiin DUA
sumber legacy (koleksi `iocs` + array `article.cves` terpisah, keduanya
hasil regex CVE yang sama persis dari `iocExtractor.py`). Lihat
docstring method itu."""

from __future__ import annotations

import asyncio
import datetime
from collections import Counter
from typing import Any

import structlog
from cti_core.db.models.article import Article
from cti_core.db.repositories.article import AsyncArticleRepo, all_country_codes
from cti_core.db.repositories.article_cve import AsyncArticleCveRepo
from cti_core.db.repositories.ioc import AsyncIOCRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.source_reliability import AsyncSourceReliabilityRepo
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import campaign_analysis, cve_priority, diamond_model
from cti_api.services.cluster_tokenize import cluster_id, derive_cluster_name, tfidf_tokenize

log = structlog.get_logger()

_SIM_THRESHOLD = 0.75
_RELIABILITY_RANK = {"A": 6, "B": 5, "C": 4, "D": 3, "E": 2, "F": 1}
_ARTICLE_CAP = 2000
"""Batas artikel jendela yang dikelompokkan (yang terbaru dulu, urutan `list_filtered`)."""


async def get_recent_campaigns(
    session: AsyncSession,
    *,
    days: int = 7,
    client_id: str | None = None,
    min_size: int = 3,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
) -> list[dict[str, Any]]:
    """Klaster kampanye dari artikel di jendela tanggal.

    Tanpa `start`/`end` jendelanya `days` hari terakhir DIHITUNG DARI HARI INI: perilaku lama, yang
    dipakai semua pemanggil lama. `start` (inklusif) menggantikan batas bawah itu; `end` (inklusif)
    menutup batas atasnya, dan kalau `start` tidak diberikan `days` dihitung mundur dari `end`.
    Recap mingguan memberi keduanya (#21): tanpa itu pekan yang di-backfill mendapat klaster pekan
    saat ia dijalankan, bukan klaster pekannya sendiri.

    Paling banyak `_ARTICLE_CAP` artikel yang dibaca. Kalau jendelanya lebih padat, klaster dibangun
    dari yang terbaru saja (kumpulan tidak lengkap) dan itu dicatat sebagai peringatan, bukan
    diam-diam."""
    cutoff = start or (end or datetime.date.today()) - datetime.timedelta(days=days)
    articles, total = await AsyncArticleRepo(session).list_filtered(
        posted_on_start=cutoff, posted_on_end=end, page=1, page_size=_ARTICLE_CAP
    )
    if total > len(articles):
        log.warning(
            "campaign_article_cap_hit",
            cap=_ARTICLE_CAP,
            articles_in_window=total,
            start=cutoff.isoformat(),
            end=end.isoformat() if end else None,
        )
    if len(articles) < 2:
        return []

    ratings = await AsyncSourceReliabilityRepo(session).get_all_ratings()
    raw = _article_to_dict(articles, ratings)

    article_ids = [a["id"] for a in raw]
    ioc_rows = await AsyncIOCRepo(session).list_by_article_ids(article_ids)
    ioc_map = _build_ioc_map(ioc_rows, set(article_ids))

    cve_map = await AsyncArticleCveRepo(session).cve_ids_by_article(article_ids)

    campaigns = await asyncio.to_thread(_build_campaign_groups, raw, ioc_map, cve_map, min_size)
    if not campaigns:
        return []

    cid = client_id or "default"

    # Sekuensial -- satu AsyncSession gak aman dipakai concurrent lewat
    # asyncio.gather (constraint yang sama didokumentasikan berkali-kali
    # sesi ini).
    for c in campaigns:
        c["prioritized_cves"] = await cve_priority.prioritize_campaign_cves(
            session, c["cve_ids"], client_id=cid
        )
    for c in campaigns:
        sev = await campaign_analysis.compute_campaign_severity(session, c, c.pop("_articles_raw"))
        c.update(sev)

    campaigns.sort(key=lambda x: x["severity_score"], reverse=True)

    await _match_pirs(session, campaigns, cid)
    await diamond_model.build_diamond_models(session, campaigns)

    links = campaign_analysis.compute_campaign_links(campaigns)
    _index: dict[str, list[dict[str, Any]]] = {}
    for lk in links:
        for own_id, peer_id, peer_name in [
            (lk["source_id"], lk["target_id"], lk["target_name"]),
            (lk["target_id"], lk["source_id"], lk["source_name"]),
        ]:
            _index.setdefault(own_id, []).append(
                {
                    "cluster_id": peer_id,
                    "cluster_name": peer_name,
                    "link_score": lk["score"],
                    "link_type": lk["link_type"],
                    "shared_elements": {
                        "tas": lk["shared_tas"],
                        "ttps": lk["shared_ttps"],
                        "iocs": lk["shared_iocs"],
                    },
                }
            )
    for c in campaigns:
        c["related_campaigns"] = sorted(
            _index.get(c["cluster_id"], []), key=lambda x: x["link_score"], reverse=True
        )

    return campaigns


def _article_to_dict(articles: list[Article], ratings: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for a in articles:
        rating = ratings.get((a.source or "").lower())
        out.append(
            {
                "id": a.id,
                "title": a.title,
                "posted_on": a.posted_on.isoformat() if a.posted_on else "",
                "source_reliability": rating.reliability_grade if rating else "",
                "threat_actors": [t.threat_actor for t in a.threat_actors if t.threat_actor],
                "impacted_industries": [i.industry for i in a.industries if i.industry],
                # Role apa pun -- konsisten sama PIR matching (`dominant_countries`
                # dibandingin ke `criteria.countries` PIR, yang match role apa pun).
                "countries": all_country_codes(a),
                "ttps": [{"id": t.ttp_id, "name": t.ttp_name} for t in a.ttps],
            }
        )
    return out


def _build_ioc_map(ioc_rows: list[Any], article_ids: set[int]) -> dict[int, list[dict[str, Any]]]:
    ioc_map: dict[int, list[dict[str, Any]]] = {}
    for ioc in ioc_rows:
        for s in ioc.sources:
            if s.article_id in article_ids:
                ioc_map.setdefault(s.article_id, []).append(
                    {"id": ioc.id, "type": ioc.type, "value": ioc.value}
                )
    return ioc_map


def _build_campaign_groups(
    articles: list[dict[str, Any]],
    ioc_map: dict[int, list[dict[str, Any]]],
    cve_map: dict[int, set[str]],
    min_size: int,
) -> list[dict[str, Any]]:
    """CPU-bound murni (TF-IDF union-find + agregasi) -- dijalanin lewat
    `asyncio.to_thread`. `_articles_raw` (dilampirin ke tiap campaign,
    di-`pop()` caller sebelum dikirim ke response) nampung member dict
    asli buat `compute_campaign_severity`'s `_source_quality_factor`."""
    titles = [a["title"] for a in articles]
    vectorizer = TfidfVectorizer(
        tokenizer=tfidf_tokenize, token_pattern=None, lowercase=False, min_df=1
    )
    try:
        tfidf_matrix = vectorizer.fit_transform(titles)
    except ValueError:
        return []

    n = len(articles)
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x: int, y: int) -> None:
        px, py = _find(x), _find(y)
        if px != py:
            parent[px] = py

    sim_matrix = cosine_similarity(tfidf_matrix)
    for i in range(n):
        for j in range(i + 1, n):
            if sim_matrix[i, j] >= _SIM_THRESHOLD:
                _union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(n):
        root = _find(idx)
        groups.setdefault(root, []).append(idx)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    today_s = today.isoformat()
    yesterday_s = yesterday.isoformat()

    results: list[dict[str, Any]] = []
    for positions in groups.values():
        if len(positions) < min_size:
            continue

        members = [articles[p] for p in positions]
        sorted_members = sorted(members, key=lambda x: x.get("posted_on", ""), reverse=True)

        dates = [a.get("posted_on", "") for a in sorted_members if a.get("posted_on")]
        first_seen = dates[-1] if dates else ""
        last_seen = dates[0] if dates else ""

        first_dt = _parse_date(first_seen)
        last_dt = _parse_date(last_seen)
        days_active = (last_dt - first_dt).days if first_dt and last_dt else 0
        velocity_articles_per_day = len(members) / max(1, days_active)

        if velocity_articles_per_day > 3:
            velocity_label = "surging"
        elif velocity_articles_per_day > 1:
            velocity_label = "active"
        elif velocity_articles_per_day > 0.3:
            velocity_label = "moderate"
        else:
            velocity_label = "slow"

        cutoff_3d = (today - datetime.timedelta(days=3)).isoformat()
        recent_count = sum(1 for a in members if a.get("posted_on", "") >= cutoff_3d)
        prior_count = len(members) - recent_count
        prior_days = max(1, days_active - 3)
        rate_recent = recent_count / 3.0
        rate_prior = prior_count / prior_days
        acceleration = round(rate_recent - rate_prior, 4)
        velocity_alert = acceleration > 2.0

        recent_aids = {a["id"] for a in members if a.get("posted_on", "") in (today_s, yesterday_s)}
        new_iocs_set: set[str] = set()
        for a in members:
            if a["id"] in recent_aids:
                for ioc in ioc_map.get(a["id"], []):
                    new_iocs_set.add(f"{ioc['type']}:{ioc['value']}")
        new_iocs_24h = len(new_iocs_set)

        summary_member = max(
            members,
            key=lambda a: _RELIABILITY_RANK.get((a.get("source_reliability") or "").upper(), 0),
            default=members[0],
        )

        ta_counter: Counter[str] = Counter()
        ind_counter: Counter[str] = Counter()
        ctr_counter: Counter[str] = Counter()
        tech_set: set[str] = set()
        attack_techniques: list[str] = []
        cve_set: set[str] = set()
        cve_ids: list[str] = []
        member_article_ids: list[int] = []
        titles_list: list[str] = []
        iocs: list[dict[str, Any]] = []
        ioc_seen: set[str] = set()

        for a in members:
            aid = a["id"]
            member_article_ids.append(aid)
            titles_list.append(a.get("title", ""))
            for ta in a.get("threat_actors", []):
                ta_counter[ta] += 1
            for ind in a.get("impacted_industries", []):
                ind_counter[ind] += 1
            for ctr in a.get("countries", []):
                ctr_counter[ctr] += 1
            for ttp in a.get("ttps", []):
                # legacy: `ttp.get("name", "")` doang -- `or ttp.get("id")`
                # fallback DITAMBAHIN (bukan literal port) buat jaga-jaga
                # `ttp_name` kosong; `attack_techniques` (dipakai
                # `analyze_kill_chain`'s regex `T\d{4}`) tetap ke-isi
                # selama salah satu field ada.
                name = ttp.get("name") or ttp.get("id") or ""
                if name and name not in tech_set:
                    tech_set.add(name)
                    attack_techniques.append(name)
            for cve in sorted(cve_map.get(aid, ())):
                if cve not in cve_set:
                    cve_set.add(cve)
                    cve_ids.append(cve)
            for ioc in ioc_map.get(aid, []):
                key = f"{ioc['type']}:{ioc['value']}"
                if key not in ioc_seen:
                    ioc_seen.add(key)
                    iocs.append(ioc)

        dominant_tas = [ta for ta, _ in ta_counter.most_common(5)]
        dominant_industries = [ind for ind, _ in ind_counter.most_common(5)]
        dominant_countries = [ctr for ctr, _ in ctr_counter.most_common(5)]

        cluster_name = derive_cluster_name([a["title"] for a in sorted_members])
        cid = cluster_id(cluster_name)

        results.append(
            {
                "cluster_id": cid,
                "cluster_name": cluster_name,
                "size": len(members),
                "first_seen": first_seen,
                "last_seen": last_seen,
                "member_article_ids": member_article_ids,
                "titles": titles_list,
                "summary_title": summary_member.get("title", ""),
                "dominant_tas": dominant_tas,
                "dominant_industries": dominant_industries,
                "dominant_countries": dominant_countries,
                "attack_techniques": attack_techniques[:20],
                "kill_chain": campaign_analysis.analyze_kill_chain(attack_techniques),
                "iocs": iocs[:50],
                "cve_ids": cve_ids[:20],
                "velocity_articles_per_day": round(velocity_articles_per_day, 2),
                "velocity_label": velocity_label,
                "acceleration": acceleration,
                "velocity_alert": velocity_alert,
                "new_iocs_24h": new_iocs_24h,
                "days_active": days_active,
                "_articles_raw": members,
            }
        )

    return results


def _parse_date(s: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


async def _match_pirs(
    session: AsyncSession, clusters: list[dict[str, Any]], client_id: str
) -> None:
    """Annotate tiap cluster dict dengan `matched_pirs: [{...}]` -- port
    `_match_pirs()`. PIR aktif DI-SCOPE `client_id` (beda dari
    `AsyncPIRRepo.list_active_unscoped()` yang lintas client)."""
    pirs = await AsyncPIRRepo(session).list_active_by_client(client_id)

    for cluster in clusters:
        tas = {t.lower() for t in cluster.get("dominant_tas", [])}
        inds = {i.lower() for i in cluster.get("dominant_industries", [])}
        ctrs = {c.lower() for c in cluster.get("dominant_countries", [])}

        matched: list[dict[str, Any]] = []
        for pir in pirs:
            crit = pir.criteria or {}
            pir_tas = {t.lower() for t in crit.get("threat_actors", [])}
            pir_inds = {i.lower() for i in crit.get("industries", [])}
            pir_ctrs = {c.lower() for c in crit.get("countries", [])}
            if (tas & pir_tas) or (inds & pir_inds) or (ctrs & pir_ctrs):
                matched.append(
                    {
                        "id": pir.id,
                        "title": pir.title,
                        "description": pir.description,
                        "priority": pir.priority,
                        "status": pir.status,
                        "criteria": pir.criteria,
                    }
                )

        cluster["matched_pirs"] = matched
