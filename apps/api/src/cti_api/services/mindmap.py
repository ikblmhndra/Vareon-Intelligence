"""Port `ScraperNewsWeb/app/services/mermaid_service.py`. Fase 7.3
(router `mindmap`, Bagian 4) ngeport 5 dari 6 builder lama (`newsletter`/
`threat_actor`/`cve`/`pir`/`ransomware`) penuh.

Builder `cluster` (Fase 7.4 Grup A, 2026-09-23) sekarang diport -- APA
ADANYA, TERMASUK BUG-nya: `build_cluster_mindmap()` legacy manggil
`get_clusters()` (Pipeline 1, greedy TF-IDF persisted -- cuma punya
field `cluster_name`/`article_count`/`source_count`/`sources`/
`first_date`/`last_date`), tapi baca field (`dominant_tas`/`iocs`/
`cve_ids`/`dominant_industries`/`dominant_countries`/`attack_techniques`)
yang CUMA ADA di Pipeline 2 (`get_recent_campaigns()`, union-find, gak
pernah persist). Hasilnya: branch "Adversary"/"Capability"/
"Infrastructure"/"CVEs" SELALU kosong, cuma "Stats" yang kepake --
begini juga perilaku aslinya. Ini genuinely bug penamaan fungsi salah
di kode lama (ketauan pas baca 2 fungsi cluster_service.py bareng),
BUKAN diselesaikan di sini -- pilih Pipeline mana + resolve cluster_id
gimana itu keputusan produk (dua pipeline beda algoritma & rentang
hari default, cluster_id yang sama dari Pipeline 1 belum tentu match
grouping Pipeline 2), di luar scope port murni.

**`doc_id` per feature_type dipetakan ke identifier yang SAMA dipakai
router lain buat domain itu, BUKAN internal PK Postgres:**
- `cve`: `cve_id` (string, kayak `get_by_cve_id_any_client()` di
  `crossref`), bukan `CveTracker.id` int.
- `threat_actor`: nama TA (string), bukan `ThreatActorGroup.id` -- SEMUA
  endpoint TA lain (`watchlist`/`profile`/`crossref`/`timeline`) juga
  alamatin TA by name, bukan by internal id. Kode lama nyoba ObjectId
  dulu baru fallback ke name-regex; di sini cuma name, konsisten sama
  pola yang udah established di router lain.
- `pir`/`newsletter`: `PIRRequirement.id`/`Newsletter.id` (int, dikirim
  sebagai string di path) -- ini emang identifier asli keduanya sekarang.
- `ransomware`: `group_name` (string) -- sama kayak kode lama, gak pernah
  ada ID lain buat domain ini.
- `cluster`: `cluster_id` (string, hash pendek `cti_api.services.
  cluster_tokenize.cluster_id()`)."""

from __future__ import annotations

import re
from typing import Any

from cti_core.db.models.mindmap import MindmapDoc
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.cve import AsyncCveTrackerRepo
from cti_core.db.repositories.mindmap import AsyncMindmapRepo
from cti_core.db.repositories.newsletter import AsyncNewsletterRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ransomware import AsyncRansomwareVictimRepo
from cti_core.db.repositories.ta import AsyncTAProfileRepo, AsyncTARepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import cluster as cluster_service

_TECHNIQUE_RE = re.compile(r"\b(T\d{4}(?:\.\d{3})?)\b")


# ── Syntax helpers -- port byte-identik dari mermaid_service.py ────────────


def _esc(text: str, limit: int = 80) -> str:
    text = str(text or "").strip()
    for ch in '()[]{}"\n\r\t`#;':
        text = text.replace(ch, " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _ind(level: int) -> str:
    return "    " * level


def _node(level: int, text: str, limit: int = 80) -> str:
    t = _esc(text, limit)
    return f"{_ind(level)}{t}\n" if t else ""


def _branch(level: int, label: str, items: list[Any], limit: int = 60) -> str:
    if not items:
        return ""
    out = _node(level, label)
    for item in items[:10]:
        out += _node(level + 1, str(item), limit)
    return out


def build_syntax(root_title: str, branches: list[str]) -> str:
    body = "".join(b for b in branches if b)
    return f"mindmap\n{_ind(1)}root(({_esc(root_title, 60)}))\n{body}"


def _extract_ttps(text: str) -> list[str]:
    return sorted(set(_TECHNIQUE_RE.findall(text)))[:10]


# ── Builders ─────────────────────────────────────────────────────────────


async def build_newsletter_mindmap(session: AsyncSession, doc_id: str) -> tuple[str, str] | None:
    row = await AsyncNewsletterRepo(session).get_by_id(int(doc_id))
    if row is None:
        return None

    title = f"Newsletter Week {row.week}/{row.year}"
    sections = row.sections
    section_meta = [
        ("highlight", "Highlights"),
        ("apac", "APAC"),
        ("global_news", "Global News"),
        ("indonesia", "Indonesia"),
    ]
    branches = []
    for key, label in section_meta:
        raw = sections.get(key)
        articles = [raw] if isinstance(raw, dict) and raw else (raw or [])
        if not articles:
            continue
        branches.append(_node(2, f"{label} ({len(articles)})"))
        for a in articles[:8]:
            branches.append(_node(3, a.get("title", "")[:60]))

    return title, build_syntax(title, branches)


async def build_threat_actor_mindmap(session: AsyncSession, doc_id: str) -> tuple[str, str] | None:
    group = await AsyncTARepo(session).get_by_name_ci(doc_id)
    if group is None:
        return None

    actor_name = group.name
    profile_row = await AsyncTAProfileRepo(session).get_profile(actor_name)
    profile = profile_row.profile if profile_row else None

    branches = []
    if profile:
        identity = profile.get("identity", {})
        id_items = []
        if identity.get("actor_type"):
            id_items.append(f"Type: {identity['actor_type']}")
        if identity.get("sponsoring_nation"):
            id_items.append(f"Nation: {identity['sponsoring_nation']}")
        if identity.get("active_status"):
            id_items.append(f"Status: {identity['active_status']}")
        id_items.extend(identity.get("aliases", [])[:3])
        branches.append(_branch(2, "Identity", id_items))

        mot = profile.get("motivation", {})
        mot_items = [
            m
            for m in [mot.get("primary_motivation"), *mot.get("secondary_motivations", [])[:2]]
            if m
        ]
        branches.append(_branch(2, "Motivation", mot_items))

        cap = profile.get("capability_assessment", {})
        cap_items = []
        if cap.get("sophistication_level"):
            cap_items.append(f"Sophistication: {cap['sophistication_level']}")
        for m in cap.get("known_malware", [])[:5]:
            name = m.get("name") if isinstance(m, dict) else m
            if name:
                cap_items.append(f"Malware: {name}")
        for t in cap.get("known_tools", [])[:3]:
            cap_items.append(f"Tool: {t}")
        branches.append(_branch(2, "Capabilities", cap_items))

        tgt = profile.get("targeting_profile", {})
        tgt_items = tgt.get("targeted_sectors", [])[:5] + tgt.get("targeted_geographies", [])[:4]
        branches.append(_branch(2, "Targets", tgt_items))

        inf = profile.get("infrastructure", {})
        inf_items = inf.get("c2_patterns", [])[:3] + inf.get("hosting_preferences", [])[:2]
        branches.append(_branch(2, "Infrastructure", inf_items))

    return f"Threat Actor: {actor_name}", build_syntax(actor_name, branches)


async def build_cve_mindmap(session: AsyncSession, doc_id: str) -> tuple[str, str] | None:
    cve = await AsyncCveTrackerRepo(session).get_by_cve_id_any_client(doc_id)
    if cve is None:
        return None

    branches = []
    overview = []
    if cve.cve_severity:
        overview.append(f"Severity: {cve.cve_severity} {cve.cve_score or ''}")
    if cve.published:
        overview.append(f"Published: {cve.published.isoformat()}")
    if cve.tech:
        overview.append(f"Tech: {cve.tech}")
    if cve.cisa_kev:
        overview.append("CISA KEV — Exploited in Wild")
    if cve.poc_available:
        overview.append("POC Available")
    branches.append(_branch(2, "Overview", overview))

    branches.append(_branch(2, "Affected", [a.affected for a in cve.affected][:5]))
    branches.append(_branch(2, "ATT&CK TTPs", _extract_ttps(cve.summary or "")))
    branches.append(_branch(2, "POC Exploits", [p.url[:60] for p in cve.pocs[:5] if p.url]))

    solutions = (cve.solutions or "").strip()
    if solutions and solutions != "No solution yet":
        branches.append(_branch(2, "Solution", [solutions[:80]]))

    return cve.cve_id, build_syntax(cve.cve_id, branches)


async def build_pir_mindmap(session: AsyncSession, doc_id: str) -> tuple[str, str] | None:
    pir_repo = AsyncPIRRepo(session)
    pir = await pir_repo.get_by_id(int(doc_id))
    if pir is None:
        return None

    article_repo = AsyncArticleRepo(session)
    articles, total = await pir_repo.list_articles_for_pir(pir, article_repo, page=1, page_size=30)

    all_titles = " ".join(a.title for a in articles)
    threat_actors = sorted({n for a in articles for n in a.entity_names("intrusion-set")})
    ttps = _extract_ttps(all_titles)

    criteria = pir.criteria
    branches = [
        _branch(2, "Threat Actors", threat_actors[:8]),
        _branch(2, "Malware and tools", criteria.get("malware", [])[:8]),
        _branch(2, "Industries", criteria.get("industries", [])[:6]),
        _branch(2, "Countries", criteria.get("countries", [])[:6]),
        _branch(2, "Keywords", criteria.get("keywords", [])[:6]),
        _branch(2, "TTPs", criteria.get("ttps", []) + ttps),
        _branch(2, "Coverage", [f"{total} matching articles"]),
    ]

    return pir.title, build_syntax(pir.title, branches)


async def build_ransomware_mindmap(
    session: AsyncSession, group_name: str
) -> tuple[str, str] | None:
    rows = await AsyncRansomwareVictimRepo(session).list_by_group_exact(group_name, limit=100)
    if not rows:
        return None

    industries: dict[str, int] = {}
    countries: dict[str, int] = {}
    victims = []
    for r in rows:
        if r.industry:
            industries[r.industry] = industries.get(r.industry, 0) + 1
        if r.country_code:
            countries[r.country_code] = countries.get(r.country_code, 0) + 1
        if r.victim:
            victims.append(r.victim)

    top_industries = sorted(industries.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_countries = sorted(countries.items(), key=lambda kv: kv[1], reverse=True)[:8]

    branches = [
        _branch(2, f"Victims {len(rows)}", victims[:10]),
        _branch(2, "Industries", [f"{ind} ({cnt})" for ind, cnt in top_industries]),
        _branch(2, "Countries", [f"{ctr} ({cnt})" for ctr, cnt in top_countries]),
    ]

    return f"Ransomware: {group_name}", build_syntax(group_name, branches)


async def build_cluster_mindmap(session: AsyncSession, doc_id: str) -> tuple[str, str] | None:
    clusters = await cluster_service.get_clusters(session, days=30)
    cluster = next((c for c in clusters if c["cluster_id"] == doc_id), None)
    if cluster is None:
        return None

    name = cluster.get("cluster_name", doc_id)
    branches = [
        _branch(2, "Adversary", cluster.get("dominant_tas", [])[:5]),
        _branch(2, "Capability", cluster.get("attack_techniques", [])[:8]),
        _branch(
            2,
            "Infrastructure",
            [f"{i['type']}: {i['value']}"[:50] for i in cluster.get("iocs", [])[:8]],
        ),
        _branch(2, "Victim Industries", cluster.get("dominant_industries", [])[:5]),
        _branch(2, "Victim Countries", cluster.get("dominant_countries", [])[:5]),
        _branch(2, "CVEs", cluster.get("cve_ids", [])[:6]),
        _branch(
            2,
            "Stats",
            [
                f"{cluster.get('article_count', 0)} articles",
                f"{cluster.get('source_count', 0)} sources",
                f"First: {cluster.get('first_date', '')}",
                f"Last: {cluster.get('last_date', '')}",
            ],
        ),
    ]

    return name, build_syntax(name, branches)


BUILDERS = {
    "newsletter": build_newsletter_mindmap,
    "threat_actor": build_threat_actor_mindmap,
    "cve": build_cve_mindmap,
    "pir": build_pir_mindmap,
    "ransomware": build_ransomware_mindmap,
    "cluster": build_cluster_mindmap,
}


async def get_or_generate(
    session: AsyncSession, feature_type: str, doc_id: str
) -> MindmapDoc | None:
    repo = AsyncMindmapRepo(session)
    cached = await repo.get_cached(feature_type, doc_id)
    if cached and cached.mermaid_syntax:
        return cached
    result = await BUILDERS[feature_type](session, doc_id)
    if result is None:
        return None
    title, syntax = result
    return await repo.save(feature_type, doc_id, title, syntax)
