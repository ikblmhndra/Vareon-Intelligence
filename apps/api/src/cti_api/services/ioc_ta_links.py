"""Port `ioc_service.get_ioc_ta_links()`. Fase 7.4 Grup D -- endpoint
`GET /api/iocs/ta-links/{type}/{value}` yang ketinggalan pas Fase 7.3
karena blocker router `ta_groups`/`attack` (SEKARANG udah keport,
Bagian 3).

Watchlist check UNSCOPED (lintas semua client) -- asimetri legacy
dipertahankan apa adanya, lihat docstring
`AsyncTARepo.get_watchlist_names_unscoped()`."""

from __future__ import annotations

from typing import Any

from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.attack import AsyncAttackQueryRepo
from cti_core.db.repositories.indicator import AsyncIndicatorRepo
from cti_core.db.repositories.ta import AsyncTARepo
from sqlalchemy.ext.asyncio import AsyncSession


async def get_ioc_ta_links(
    session: AsyncSession, ioc_type: str, value: str
) -> dict[str, Any] | None:
    ioc = await AsyncIndicatorRepo(session).get(type=ioc_type, value=value)
    if ioc is None:
        return None

    manual_tas: set[str] = {t.threat_actor for t in ioc.threat_actors if t.threat_actor}

    article_ids = {s.article_id for s in ioc.sources if s.article_id is not None}
    article_ta_counts: dict[str, int] = {}
    if article_ids:
        articles = await AsyncArticleRepo(session).get_by_ids(list(article_ids))
        for article in articles.values():
            for t in article.threat_actors:
                if t.threat_actor:
                    article_ta_counts[t.threat_actor] = article_ta_counts.get(t.threat_actor, 0) + 1

    all_ta_names = manual_tas | set(article_ta_counts.keys())
    if not all_ta_names:
        return {"threat_actors": []}

    watchlist_names = await AsyncTARepo(session).get_watchlist_names_unscoped()
    watchlist_lower = {n.lower() for n in watchlist_names}

    attack_repo = AsyncAttackQueryRepo(session)
    result_tas: list[dict[str, Any]] = []
    for ta_name in sorted(all_ta_names, key=lambda n: -article_ta_counts.get(n, 0)):
        is_manual = ta_name in manual_tas
        in_articles = ta_name in article_ta_counts
        source = "manual" if is_manual and not in_articles else ("both" if is_manual else "article")

        entry: dict[str, Any] = {
            "name": ta_name,
            "article_count": article_ta_counts.get(ta_name, 0),
            "is_watched": ta_name.lower() in watchlist_lower,
            "source": source,
        }
        attack_match = await attack_repo.get_group_by_name_or_alias_ci(ta_name)
        if attack_match is not None:
            entry["attack_group_id"] = attack_match.group_id
            entry["attack_group_name"] = attack_match.name
            entry["attack_group_aliases"] = (attack_match.aliases or [])[:6]
            entry["attack_group_domains"] = attack_match.domains or []
        result_tas.append(entry)

    return {"threat_actors": result_tas}
