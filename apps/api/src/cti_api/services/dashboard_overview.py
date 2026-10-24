"""Overview dashboard (peta, perhatian, ransomware, eksposur CVE) untuk endpoint
`/api/dashboard/*`. Semua fungsi `get_*` "session-first"; hitungan datang dari repo
(`AsyncDashboardRepo`, `AsyncRansomwareVictimRepo`), service ini hanya menyatukan dan
menyusun kalimat `brief` deterministik (tanpa LLM: analis harus bisa menelusuri tiap angka).

Scope CVE sengaja sama dengan `GET /api/cve/stats`: tech = entri AKTIF client
(`visible_names`), false-positive dibuang lewat `exclude_cve_ids`. Repo CVE overview
tidak menyaring FP sendiri, jadi sini yang wajib mengopernya. Cache in-memory 900 detik
untuk `get_attention` saja (paling mahal: loop PIR), pola `spike`/`article_dashboard`."""

from __future__ import annotations

import datetime
import time
from collections.abc import Sequence
from typing import Any

from cti_core.db.models.pir import PIRRequirement
from cti_core.db.repositories.article import AsyncArticleRepo
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.cve import AsyncCveFalsePositiveRepo
from cti_core.db.repositories.dashboard import AsyncDashboardRepo
from cti_core.db.repositories.pir import AsyncPIRRepo
from cti_core.db.repositories.ransomware import AsyncRansomwareVictimRepo
from cti_core.db.repositories.techstack import AsyncTechStackRepo
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services.exec_dashboard import NON_INCIDENT_TYPES
from cti_api.services.trending import TrendItem, get_trending

_CACHE: dict[str, tuple[dict[str, Any], float]] = {}
_CACHE_TTL = 900

APAC_COUNTRY_CODES: frozenset[str] = frozenset(
    {
        "AU",
        "BD",
        "BN",
        "BT",
        "CN",
        "FJ",
        "HK",
        "ID",
        "IN",
        "JP",
        "KH",
        "KR",
        "LA",
        "LK",
        "MM",
        "MN",
        "MO",
        "MV",
        "MY",
        "NP",
        "NZ",
        "PG",
        "PH",
        "PK",
        "SG",
        "TH",
        "TL",
        "TW",
        "VN",
    }
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _period_start(days: int | None) -> datetime.date | None:
    """Awal periode = `today - days` (inklusif), konvensi yang sama dengan `/api/dashboard`."""
    return None if days is None else datetime.date.today() - datetime.timedelta(days=days)


_DRIVER_LABELS = {"apac": "APAC", "global": "Global"}


def driver_label(news_type: str) -> str:
    """Label `news_type` untuk kalimat brief: kunci mentah rubrik ("apac", "global") dibaca
    "APAC"/"Global"; tipe lain sudah berupa label ("Data Breach Article") dan dipakai apa
    adanya."""
    return _DRIVER_LABELS.get(news_type, news_type)


def build_brief(
    *,
    top_trend: TrendItem | None,
    trend_reliable: bool = True,
    kev_in_stack: int,
    incidents: int,
    prev_incidents: int | None,
    drivers: Sequence[str],
) -> dict[str, str]:
    """Dua kalimat ringkasan "apa yang perlu diperhatikan": `headline` dari tren teratas dan
    jumlah KEV di tech stack, `detail` dari perubahan insiden terkonfirmasi. Murni fungsi dari
    angka, supaya hasilnya bisa diuji persis."""
    parts: list[str] = []
    if top_trend is not None:
        name = f"{top_trend.ttp_id} {top_trend.name}" if top_trend.ttp_id else top_trend.name
        if not trend_reliable:
            # Periode pembanding nyaris kosong: jangan klaim "naik" (audit UI U4).
            parts.append(f"{name} paling sering muncul")
        elif top_trend.is_new:
            parts.append(f"{name} baru muncul")
        elif top_trend.change_pct is not None:
            parts.append(f"{name} naik {top_trend.change_pct}%")
        else:
            parts.append(f"{name} naik")
    if kev_in_stack > 0:
        parts.append(f"{kev_in_stack} CVE KEV cocok dengan tech stack klien")
    if not parts:
        headline = "Tidak ada lonjakan atau CVE KEV baru pada periode ini."
    elif top_trend is not None and kev_in_stack == 0:
        headline = f"{parts[0]} pada periode ini."
    else:
        headline = " dan ".join(parts) + "."

    if incidents <= 0:
        detail = "Belum ada insiden terkonfirmasi pada periode ini."
    else:
        if prev_incidents is not None and prev_incidents > 0:
            pct = round((incidents - prev_incidents) * 100 / prev_incidents)
            if pct == 0:
                base = "Insiden stabil dibanding periode sebelumnya"
            else:
                arah = "naik" if pct > 0 else "turun"
                base = f"Insiden {arah} {abs(pct)}% dibanding periode sebelumnya"
        else:
            base = f"{incidents} insiden terkonfirmasi pada periode ini"
        top = [d for d in drivers if d][:2]
        detail = f"{base}, didorong {' dan '.join(top)}." if top else f"{base}."
    return {"headline": headline, "detail": detail}


async def get_map(session: AsyncSession, *, client_id: str, days: int | None) -> dict[str, Any]:
    since = _period_start(days)
    profile = await AsyncDashboardRepo(session).incident_country_profile(posted_on_start=since)
    ransom = await AsyncRansomwareVictimRepo(session).summary(
        since=since, apac_codes=APAC_COUNTRY_CODES, client_codes=()
    )
    victims: dict[str, int] = ransom["by_country"]
    points: dict[str, dict[str, Any]] = {
        code: {
            "country_code": code,
            "incidents": n,
            "ransomware_victims": victims.get(code, 0),
            "top_actor": actor,
            "top_industry": industry,
        }
        for code, n, actor, industry in profile
    }
    for code, n in victims.items():
        points.setdefault(
            code,
            {
                "country_code": code,
                "incidents": 0,
                "ransomware_victims": n,
                "top_actor": None,
                "top_industry": None,
            },
        )
    ordered = sorted(
        points.values(),
        key=lambda p: (-(p["incidents"] + p["ransomware_victims"]), p["country_code"]),
    )
    client = await AsyncClientRepo(session).get(client_id)
    return {
        "points": ordered,
        "client_countries": sorted(c.country_code for c in client.countries) if client else [],
        "generated_at": _now(),
    }


async def _cve_scope(session: AsyncSession, client_id: str) -> dict[str, Any]:
    return {
        "client_id": client_id,
        "tech": await AsyncTechStackRepo(session).visible_names(client_id),
        "exclude_cve_ids": await AsyncCveFalsePositiveRepo(session).list_cve_ids(client_id) or None,
    }


async def _pir_hits(session: AsyncSession, client_id: str, since: datetime.date | None) -> int:
    """PIR aktif yang punya minimal satu artikel dalam jendela PIR-nya sendiri yang
    di-irisan dengan periode dashboard. Objek PIR sementara (tidak di-attach ke session)
    dipakai supaya `start_date` bisa digeser tanpa menyentuh baris aslinya."""
    pir_repo = AsyncPIRRepo(session)
    article_repo = AsyncArticleRepo(session)
    hits = 0
    for pir in await pir_repo.list_active_by_client(client_id):
        start = pir.start_date
        if since is not None and (start is None or start < since):
            start = since
        window = PIRRequirement(
            criteria=pir.criteria, start_date=start, end_date=pir.end_date, client_id=client_id
        )
        _, total = await pir_repo.list_articles_for_pir(window, article_repo, page=1, page_size=1)
        if total > 0:
            hits += 1
    return hits


async def get_attention(
    session: AsyncSession, *, client_id: str, days: int | None, incident_only: bool = False
) -> dict[str, Any]:
    """`incident_only` sama artinya dengan `/api/dashboard`: buang `NON_INCIDENT_TYPES`.
    Tanpa itu kalimat brief ("376 insiden") tidak cocok dengan kartu KPI di bawahnya ("363")
    yang memakai toggle yang sama (audit UI U2)."""
    today = datetime.date.today()
    cache_key = f"{client_id}|{days}|{incident_only}|{today.isoformat()}"
    now = time.monotonic()
    cached = _CACHE.get(cache_key)
    if cached is not None and now - cached[1] < _CACHE_TTL:
        return cached[0]

    since = _period_start(days)
    repo = AsyncDashboardRepo(session)
    # Sekuensial: satu AsyncSession tidak aman dipakai concurrent.
    cve = await repo.cve_exposure_counts(**await _cve_scope(session, client_id))
    client = await AsyncClientRepo(session).get(client_id)
    client_codes = [c.country_code for c in client.countries] if client else []
    ransom = await AsyncRansomwareVictimRepo(session).summary(
        since=since, apac_codes=APAC_COUNTRY_CODES, client_codes=client_codes
    )
    watchlist = await repo.watchlist_hit_count(client_id=client_id, posted_on_start=since)
    pir_hits = await _pir_hits(session, client_id, since)

    exclude = sorted(NON_INCIDENT_TYPES) if incident_only else None
    incidents = await repo.count_articles(
        confirmed_only=True, posted_on_start=since, posted_on_end=None, exclude_news_types=exclude
    )
    prev_incidents: int | None = None
    if days is not None and since is not None:
        prev_incidents = await repo.count_articles(
            confirmed_only=True,
            posted_on_start=today - datetime.timedelta(days=days * 2),
            posted_on_end=since,
            exclude_news_types=exclude,
        )
    by_type = await repo.news_type_breakdown(
        confirmed_only=True, posted_on_start=since, posted_on_end=None, exclude_news_types=exclude
    )
    drivers = [driver_label(nt) for nt, _ in by_type if nt][:2]
    trending = await get_trending(session, days=days)
    top = trending["items"][0] if trending["items"] else None

    result = {
        "kev_in_stack": cve["open_kev"],
        "kev_without_ticket": cve["kev_without_ticket"],
        "ransomware_in_client_scope": ransom["client_scope"],
        "watchlist_hits": watchlist,
        "pir_hits": pir_hits,
        "brief": build_brief(
            top_trend=TrendItem(**top) if top else None,
            trend_reliable=trending["baseline_reliable"],
            kev_in_stack=cve["open_kev"],
            incidents=incidents,
            prev_incidents=prev_incidents,
            drivers=drivers,
        ),
        "generated_at": _now(),
    }
    _CACHE[cache_key] = (result, now)
    return result


async def get_ransomware(session: AsyncSession, *, days: int | None) -> dict[str, Any]:
    repo = AsyncRansomwareVictimRepo(session)
    weekly = await repo.weekly_counts(weeks=8)
    summary = await repo.summary(
        since=_period_start(days), apac_codes=APAC_COUNTRY_CODES, client_codes=()
    )
    return {
        "weekly": [{"week_start": d, "victims": n} for d, n in weekly],
        "top_groups": [{"name": g, "count": n} for g, n in summary["top_groups"]],
        "total": summary["total"],
        "apac": summary["apac"],
        "undated": summary["undated"],
        "generated_at": _now(),
    }


async def get_cve_exposure(
    session: AsyncSession, *, client_id: str, days: int | None
) -> dict[str, Any]:
    repo = AsyncDashboardRepo(session)
    scope = await _cve_scope(session, client_id)
    rows = await repo.cve_exposure(limit=3, **scope)
    counts = await repo.cve_exposure_counts(**scope)
    closed, mean_days = await repo.tickets_closed(client_id=client_id, since=_period_start(days))
    today = datetime.date.today()
    return {
        "items": [
            {
                "cve_id": c.cve_id,
                "tech": c.tech,
                "cvss": c.cve_score,
                "cisa_kev": bool(c.cisa_kev),
                "ticket_id": t.ticket_id if t else None,
                "ticket_age_days": (today - t.created_at.date()).days if t else None,
                "public_poc": bool(c.poc_available),
            }
            for c, t in rows
        ],
        "open_critical": counts["open_critical"],
        "open_kev": counts["open_kev"],
        "closed_in_period": closed,
        "mean_days_to_close": mean_days,
        "generated_at": _now(),
    }
