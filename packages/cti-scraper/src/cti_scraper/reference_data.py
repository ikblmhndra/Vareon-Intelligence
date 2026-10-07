"""Resolusi dataset internal (Postgres KITA, bukan sumber eksternal) yang
sebagian scraper bespoke butuh baca SEBELUM `fetch()` jalan -- techstack
(nentuin keyword pencarian NVD/Tenable/GitHub) dan CVE yang udah confirmed
true-positive (`githubPOCMonitor` fase 2, cari POC buat CVE yang udah
ketauan valid, bukan yang di-mark false-positive analis). Sama filosofi
kayak `credentials.py`: `fetch()` gak pernah pegang `Session`, cuma data
Python biasa (list/dict) lewat `ctx.reference`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cti_scraper.base import ConfigError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _resolve_techstack(session: Session) -> list[str]:
    """Semua nama tech stack DISTINCT lintas client, urut alfabet --
    setara `techstackStore.get_tech_list()` lama."""
    from cti_core.db.models.techstack import TechStackEntry
    from sqlalchemy import select

    rows = session.execute(select(TechStackEntry.name).distinct()).scalars().all()
    return sorted(rows)


def techstack_names(session: Session) -> list[str]:
    """Publik: dipakai laporan periodik worker (Fase 10.E), bukan cuma `Runner`."""
    return _resolve_techstack(session)


def _resolve_techstack_by_client(session: Session) -> dict[str, list[str]]:
    """{client_id: [tech_names]} -- setara `get_tech_list_by_client()`
    lama (di sana docs tanpa client_id fallback ke "default"; skema baru
    `client_id` NOT NULL jadi fallback itu gak kepake lagi, tapi
    dipertahankan buat jaga-jaga data lama/import yang longgar)."""
    from cti_core.db.models.techstack import TechStackEntry
    from sqlalchemy import select

    result: dict[str, list[str]] = {}
    rows = session.execute(select(TechStackEntry.client_id, TechStackEntry.name)).all()
    for client_id, name in rows:
        result.setdefault(client_id or "default", []).append(name)
    for client_id in result:
        result[client_id] = sorted(result[client_id])
    return result


def _resolve_true_positive_cves(session: Session) -> list[dict[str, Any]]:
    """CVE di `cve_tracker` yang BUKAN false positive -- [{cve_id,
    poc_urls}]. `CveTracker` baris per-(cve_id, client_id) (lihat model),
    jadi satu CVE yang dipantau N client punya N baris -- di-GABUNG di
    sini jadi SATU entry per cve_id (union `poc_urls` lintas baris) biar
    `githubPOCMonitor` gak nge-search GitHub berkali-kali buat CVE yang
    sama. Script lama TIDAK nge-dedup ini (iterasi mentah per dokumen
    Mongo, bisa search API yang sama 2-3x kalau CVE-nya dipantau banyak
    client) -- itu pemborosan rate-limit GitHub yang gak disengaja, bukan
    perilaku yang mau dipertahankan."""
    from cti_core.db.models.cve import CveFalsePositive, CveTracker
    from sqlalchemy import select

    fp_ids = set(session.execute(select(CveFalsePositive.cve_id)).scalars().all())
    rows = session.execute(select(CveTracker)).scalars().unique().all()

    merged: dict[str, set[str]] = {}
    for row in rows:
        if row.cve_id in fp_ids:
            continue
        merged.setdefault(row.cve_id, set()).update(p.url for p in row.pocs)
    return [{"cve_id": cve_id, "poc_urls": urls} for cve_id, urls in sorted(merged.items())]


def _resolve_threat_actor_groups(session: Session) -> list[str]:
    """Setara `list_threat_actor_groups()` (`cti_core.db.repositories.
    threat_reference`) -- dipisah di sini biar scraper bespoke (mis.
    `monitorX`) bisa minta lewat `ScraperMeta.reference_data` kayak
    techstack, tanpa `fetch()` pegang Session (lihat docstring modul)."""
    from cti_core.db.repositories.threat_reference import list_threat_actor_groups

    return list_threat_actor_groups(session)


def _resolve_monitored_people(session: Session) -> list[str]:
    from cti_core.db.repositories.threat_reference import list_monitored_people

    return list_monitored_people(session)


def _resolve_monitored_accounts(session: Session) -> list[str]:
    """Setara `list_monitored_accounts()` lama -- username X/Twitter aktif
    dari `monitored_accounts` (pola "web kurasi, scraper patuh", Fase 2)."""
    from cti_core.db.models.tweet import MonitoredAccount
    from sqlalchemy import select

    rows = (
        session.execute(select(MonitoredAccount.username).where(MonitoredAccount.active.is_(True)))
        .scalars()
        .all()
    )
    return list(rows)


def _resolve_tweet_last_seen_ids(session: Session) -> dict[str, str]:
    """{username: tweet_id terbesar yang UDAH tersimpan} -- gantiin
    `monitorX.py`'s `state.json` lokal (`load_state`/`save_state`). Query
    SEKALI di sini (bukan per-akun di `fetch()`) karena ini reference data,
    diresolve Runner SEBELUM `fetch()` jalan -- `fetch()` gak pegang
    Session (lihat docstring modul)."""
    from cti_core.db.models.tweet import Tweet
    from sqlalchemy import select

    rows = session.execute(select(Tweet.author_username, Tweet.tweet_id)).all()
    result: dict[str, str] = {}
    for username, tweet_id in rows:
        current = result.get(username)
        if current is None or int(tweet_id) > int(current):
            result[username] = tweet_id
    return result


_RESOLVERS = {
    "techstack": _resolve_techstack,
    "techstack_by_client": _resolve_techstack_by_client,
    "true_positive_cves": _resolve_true_positive_cves,
    "threat_actor_groups": _resolve_threat_actor_groups,
    "monitored_people": _resolve_monitored_people,
    "monitored_accounts": _resolve_monitored_accounts,
    "tweet_last_seen_ids": _resolve_tweet_last_seen_ids,
}


def resolve_reference_data(names: tuple[str, ...], session: Session) -> dict[str, Any]:
    """`names` (dari `ScraperMeta.reference_data`) -> dict siap pasang ke
    `ScrapeContext(reference=...)`. Raise `ConfigError` kalau ada nama
    yang gak dikenal -- gagal pas start run, bukan `KeyError` yang
    membingungkan di tengah `fetch()`."""
    result: dict[str, Any] = {}
    for name in names:
        resolver = _RESOLVERS.get(name)
        if resolver is None:
            raise ConfigError(
                f"reference_data '{name}' gak dikenal -- pilihan yang ada: {sorted(_RESOLVERS)}"
            )
        result[name] = resolver(session)
    return result
