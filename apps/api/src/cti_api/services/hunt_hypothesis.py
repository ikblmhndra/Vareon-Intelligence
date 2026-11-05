"""Hipotesis hunting LLM sesuai permintaan (P7e spec 3.2/7.2): teks polos untuk SOC, disimpan
satu baris per anchor (`hunt_hypotheses`) dan ditimpa saat dibuat ulang. Hanya web (tanpa token
mesin). Nilai indikator TIDAK dikirim ke LLM, hanya nama dataset yang berisi indikator."""

from __future__ import annotations

import asyncio
import datetime
from typing import Literal

from cti_core.db.models.entity import Entity
from cti_core.db.models.hunt import HuntHypothesis
from cti_core.db.models.story import Story
from cti_core.llm.client import _DEFAULT_MODELS, get_llm_client
from cti_core.llm.usage import prompt_version
from cti_core.runtime_secrets.overlay import effective_settings
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cti_api.services import hunt_pack

CONTEXT_CAP = 2000
HYPOTHESIS_DAYS = 90

_SYSTEM_PROMPT = """You are a senior threat hunter writing for a SOC team.
From the context in the user message (a threat report or threat entity, its ATT&CK techniques and
the kinds of indicator data observed), write 3 to 5 hunt hypotheses.
For each hypothesis give: the behaviour to look for, the data source or telemetry needed to test
it, and the ATT&CK technique id it relates to.
Ground every hypothesis in the provided context; do not invent indicators or techniques that the
context does not support.
Answer in plain text only: a numbered list, no markdown fencing, no JSON."""

_PROMPT_VERSION = prompt_version(_SYSTEM_PROMPT)


def _call_llm(user_msg: str) -> str:
    client, model_name = get_llm_client(task="hunt_hypothesis")
    completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        prompt_version=_PROMPT_VERSION,
    )
    return (completion.choices[0].message.content or "").strip()


def _model_name() -> str:
    llm = effective_settings().llm
    return llm.model or _DEFAULT_MODELS.get(llm.provider.lower(), llm.provider)


async def _context_text(
    session: AsyncSession, anchor_type: Literal["story", "entity"], anchor_id: int
) -> str:
    """Ringkasan anchor. Artikel tidak menyimpan ringkasan; story memakai `classify.reason`
    milik lead (kalau ada), entitas memakai `description`."""
    if anchor_type == "story":
        story = await session.get(Story, anchor_id)
        text = (story.classify or {}).get("reason") if story else None
    else:
        ent = await session.get(Entity, anchor_id)
        text = ent.description if ent else None
    return (text or "")[:CONTEXT_CAP]


async def generate_hypothesis(
    session: AsyncSession,
    anchor_type: Literal["story", "entity"],
    anchor_id: int,
    *,
    username: str,
) -> HuntHypothesis:
    """Raise `AnchorNotFound`/`AnchorMerged` bila anchor tak valid; galat LLM merambat dan baris
    lama tidak berubah (upsert baru jalan sesudah teks didapat)."""
    pack = await hunt_pack.get_pack(
        session, anchor_type, anchor_id, include=set(), days=HYPOTHESIS_DAYS, max_tlp=None
    )
    lines = [
        f"Title: {pack.anchor.title}",
        f"Summary: {await _context_text(session, anchor_type, anchor_id)}",
        "Techniques:",
        *(f"{t.attack_id} {t.name}" for t in pack.techniques if t.tier == "primary"),
        "Indicator datasets: " + ", ".join(sorted(pack.iocs)),
    ]
    text = await asyncio.to_thread(_call_llm, "\n".join(lines))
    values = {
        "text": text,
        "model": _model_name(),
        "generated_by": username,
        "generated_at": datetime.datetime.now(datetime.UTC),
    }
    row = await session.scalar(
        insert(HuntHypothesis)
        .values(anchor_type=anchor_type, anchor_id=anchor_id, **values)
        .on_conflict_do_update(constraint="uq_hunt_hypotheses_anchor", set_=values)
        .returning(HuntHypothesis)
    )
    assert row is not None
    return row
