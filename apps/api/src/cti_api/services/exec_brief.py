"""Port `ScraperNewsWeb/app/services/exec_brief_service.py`. Fase 7.3
(router `exec_dashboard`, Bagian 5). Ringkasan markdown 1-halaman buat
C-suite, dari data `get_exec_dashboard_v2()`.

**Bug ketemu, DIPERBAIKI (bukan asimetri desain):** `_build_user_message()`
lama baca `ta.get('name')`/`ta.get('count')`/`ta.get('velocity')` dari
entry `ta_velocity`, tapi `_compute_ta_velocity()` (`exec_dashboard_v2_
service.py`) beneran ngehasilin key `actor`/`total`/`velocity_pct` --
key-nya gak pernah cocok, jadi baris "TOP THREAT ACTORS BY VELOCITY" di
prompt LLM lama SELALU rendering "Unknown: 0 incidents" apa pun datanya.
Sama pola kayak bug `attack_techniques` di `risk_matrix.py` -- typo/field
salah yang ketauan pas baca detail buat porting, bukan keputusan desain.
Di sini pakai key yang BENERAN dihasilin `_compute_ta_velocity()`
(`cti_api.services.exec_dashboard`) supaya section ini beneran keisi."""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass
from typing import Any

from cti_core.config import get_settings
from cti_core.db.models.exec_brief import ExecBrief
from cti_core.db.repositories.exec_brief import AsyncExecBriefRepo
from cti_core.llm.client import get_llm_client
from cti_core.llm.usage import prompt_version
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services.exec_dashboard import get_exec_dashboard_v2

SYSTEM_PROMPT = """You are a Senior Cyber Threat Intelligence Analyst producing a concise 1-page executive briefing for C-suite and board-level audiences.

Output your response in Markdown. Structure it with exactly these five sections:

## Executive Summary
2-3 sentences covering the overall threat posture for the period, key risk drivers, and organizational implications.

## Threat Landscape
Highlight the highest-risk sectors with their risk scores, and flag any statistically significant industry spikes. Keep language risk-focused and free of operational jargon.

## Priority Threat Actors
Cover the top 3 threat actors by activity velocity. For each, note their name, article count, and why they matter strategically.

## Vulnerability Exposure
Summarize the critical CVE exposure: total critical-severity count and the top technologies affected. Note any active proof-of-concept exploits if present.

## Key Findings & Recommendations
3-5 concise bullet points with concrete, actionable recommendations leadership can act on or assign. Prioritize by risk impact.

Counting rule: the data counts threat news articles, not incidents. Use the word "incident" only for the confirmed incidents count given in the data; describe every other number as articles or reports.

Tone: Concise, risk-focused, suitable for non-technical executives. Avoid acronym overload. Quantify risk wherever possible."""


def _build_user_message(days: int, data: dict[str, Any]) -> str:
    """`total_incidents` dari dashboard sebenarnya jumlah ARTIKEL berita ancaman, bukan insiden;
    dulu dikirim sebagai "Total incidents tracked" sehingga brief menyebut 992 artikel sebagai 992
    insiden. Sekarang labelnya "Threat news articles", dan insiden terkonfirmasi dikirim terpisah
    (`round(total * rate / 100)`), satu-satunya angka yang boleh disebut insiden oleh prompt."""
    total_articles = data.get("total_incidents", 0)
    unique_sectors = len(data.get("top_sectors", []))
    unique_tas = data.get("unique_ta_count", 0)
    confirmed_incident_rate = data.get("confirmed_incident_rate")

    sector_risk_scores = data.get("sector_risk_scores", [])[:5]
    sector_lines = [
        f"  - {s.get('sector', 'Unknown')}: risk score {s.get('risk_score', 0)}"
        for s in sector_risk_scores
    ]

    industry_spikes = data.get("industry_spikes", [])
    spike_lines = [
        f"  - {sp.get('entity', '?')} on {sp.get('date', '?')}: "
        f"{sp.get('count', 0)} articles, z-score {sp.get('z_score', 0):.1f} ({sp.get('severity', 'unknown')} severity)"
        for sp in industry_spikes
    ]

    ta_velocity = data.get("ta_velocity", [])[:5]
    ta_lines = [
        f"  - {ta.get('actor', 'Unknown')}: {ta.get('total', 0)} articles "
        f"(velocity: {ta.get('velocity_pct', 0)}%)"
        for ta in ta_velocity
    ]

    cve_exposure = data.get("cve_exposure_v2", [])
    total_critical = sum(r.get("critical", 0) for r in cve_exposure)
    top_cve_techs = cve_exposure[:3]
    cve_lines = []
    for r in top_cve_techs:
        poc_note = (
            f", {r.get('poc_count', 0)} PoC exploit(s) known" if r.get("poc_count", 0) > 0 else ""
        )
        cve_lines.append(
            f"  - {r.get('tech', 'Unknown')}: {r.get('total', 0)} CVEs total, "
            f"{r.get('critical', 0)} critical, max CVSS {r.get('max_cvss', 'N/A')}{poc_note}"
        )

    top_ttps = data.get("top_ttps", [])[:5]
    ttp_lines = [
        f"  - {t.get('id', '?')} {t.get('name', '')}: {t.get('count', 0)} occurrences"
        for t in top_ttps
    ]

    ta_leaderboard = data.get("ta_leaderboard", [])[:3]
    leaderboard_lines = [
        f"  - {ta.get('name', '?')}: {ta.get('count', 0)} articles" for ta in ta_leaderboard
    ]

    confirmed_line = ""
    if confirmed_incident_rate is not None:
        confirmed = round(total_articles * confirmed_incident_rate / 100)
        confirmed_line = (
            f"\n- Confirmed incidents: {confirmed} "
            f"(AI-verified confirmed incident rate: {confirmed_incident_rate}%)"
        )

    return f"""Generate an executive intelligence brief based on the following CTI dashboard metrics.

REPORTING PERIOD
- Period: last {days} days
- Threat news articles: {total_articles}
- Unique sectors affected: {unique_sectors}
- Unique threat actors observed: {unique_tas}{confirmed_line}

TOP SECTORS AT RISK (by composite risk score)
{chr(10).join(sector_lines) if sector_lines else "  - No sector risk data available"}

INDUSTRY SPIKE ALERTS (statistically anomalous surges)
{chr(10).join(spike_lines) if spike_lines else "  - No significant spikes detected"}

TOP THREAT ACTORS BY VELOCITY
{chr(10).join(ta_lines) if ta_lines else "  - No threat actor velocity data"}

TOP THREAT ACTORS BY ARTICLE COUNT
{chr(10).join(leaderboard_lines) if leaderboard_lines else "  - No leaderboard data"}

VULNERABILITY EXPOSURE
- Total critical-severity CVEs: {total_critical}
- Top affected technologies:
{chr(10).join(cve_lines) if cve_lines else "  - No CVE exposure data"}

TOP ATTACK TECHNIQUES (MITRE ATT&CK)
{chr(10).join(ttp_lines) if ttp_lines else "  - No TTP data available"}

Now produce the 1-page executive briefing in Markdown as instructed."""


_PROMPT_VERSION = prompt_version(SYSTEM_PROMPT)


def _call_llm(user_msg: str) -> tuple[str, str]:
    """Panggil LLM; mengembalikan `(markdown, model)` supaya model yang dipakai ikut tersimpan
    di `exec_briefs.model` (sama dengan `llm_calls.model`)."""
    client, model_name = get_llm_client(task="exec_brief")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        prompt_version=_PROMPT_VERSION,
    )
    return completion.choices[0].message.content or "", model_name


# Role dashboard untuk brief (C5): brief satu untuk seluruh platform, tidak boleh bergantung pada
# peran pemanggil maupun klien. Role "exec" mematikan cluster_list, fp_feedback_queue,
# source_reliability_spread dan critical_cve_feed, jadi bagian analyst/klien itu tidak dihitung.
BRIEF_ROLE = "exec"
RETENTION_DAYS = 30


@dataclass(frozen=True)
class BriefFilters:
    days: int
    incident_only: bool
    confirmed_only: bool

    def as_json(self) -> dict[str, object]:
        return {
            "days": self.days,
            "incident_only": self.incident_only,
            "confirmed_only": self.confirmed_only,
        }


DEFAULT_FILTERS = BriefFilters(90, True, False)


def brief_today(now: datetime.datetime | None = None) -> datetime.date:
    """Tanggal brief hari ini (UTC + `worker.report_utc_offset_hours`, default Jakarta). Ada di
    sini supaya API dan worker sepakat soal "hari ini" untuk satu baris `exec_briefs`."""
    now = now or datetime.datetime.now(datetime.UTC)
    offset = datetime.timedelta(hours=get_settings().worker.report_utc_offset_hours)
    return (now + offset).date()


class BriefGenerationError(Exception):
    """Pembuatan brief gagal di sisi LLM (error atau jawaban kosong); tidak ada yang ditulis."""

    def __init__(self, error_type: str) -> None:
        super().__init__(error_type)
        self.error_type = error_type


@dataclass
class BriefDraft:
    markdown: str
    model: str
    prompt_version: str


async def draft_brief(session: AsyncSession, *, filters: BriefFilters) -> BriefDraft:
    """Susun brief tanpa menyimpannya. Error DB merambat apa adanya; error LLM atau jawaban
    kosong menjadi `BriefGenerationError`."""
    data = await get_exec_dashboard_v2(
        session,
        days=filters.days,
        incident_only=filters.incident_only,
        confirmed_only=filters.confirmed_only,
        role=BRIEF_ROLE,
    )
    user_msg = _build_user_message(filters.days, data)
    try:
        markdown, model = await asyncio.to_thread(_call_llm, user_msg)
    except Exception as exc:
        raise BriefGenerationError(type(exc).__name__) from exc
    if not markdown.strip():
        raise BriefGenerationError("empty")
    return BriefDraft(markdown=markdown, model=model, prompt_version=_PROMPT_VERSION)


async def store_brief(
    session: AsyncSession,
    *,
    brief_date: datetime.date,
    draft: BriefDraft,
    filters: BriefFilters,
    generated_by: str,
    replace: bool,
) -> ExecBrief | None:
    return await AsyncExecBriefRepo(session).upsert(
        brief_date=brief_date,
        markdown=draft.markdown,
        filters=filters.as_json(),
        generated_by=generated_by,
        model=draft.model,
        prompt_version=draft.prompt_version,
        replace=replace,
    )


async def generate_scheduled_brief(session: AsyncSession, now: datetime.datetime) -> str:
    """Lapis kedua dan ketiga anti-panggilan-ganda untuk task `exec.brief_daily` (lapis pertama:
    lock Redis di task). Baca ulang baris hari ini; hanya kalau masih kosong, panggil LLM.
    `replace=False` (`INSERT ... ON CONFLICT DO NOTHING`) menjamin brief manual yang masuk di
    antara baca-ulang dan insert (POST manual tidak mengambil lock) tidak pernah ditimpa
    scheduler. Mengembalikan `"present"` | `"stored"` | `"raced"`; `BriefGenerationError`
    merambat ke task dan tidak ada yang ditulis."""
    brief_date = brief_today(now)
    repo = AsyncExecBriefRepo(session)
    if await repo.get(brief_date) is not None:
        return "present"
    draft = await draft_brief(session, filters=DEFAULT_FILTERS)
    row = await store_brief(
        session,
        brief_date=brief_date,
        draft=draft,
        filters=DEFAULT_FILTERS,
        generated_by="scheduler",
        replace=False,
    )
    await session.commit()
    return "stored" if row is not None else "raced"
