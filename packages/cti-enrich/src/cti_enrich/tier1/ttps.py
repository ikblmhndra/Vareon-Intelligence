"""Tier 1 teknik ATT&CK: ID eksplisit di teks + frasa perilaku (tanpa LLM).

Pure: tanpa Session, HTTP, atau spaCy. Eksplisit = ID `Txxxx[.xxx]` yang tertulis
di teks DAN ada di katalog (ID tak dikenal dibuang, sub-technique tak dikenal
tidak dipetakan ke induknya: menebak lebih berbahaya daripada kehilangan).
Keyword = aturan di `keyword_map`; untuk ID yang sama, eksplisit menang.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from cti_core.attack_ttp import TechniqueCatalog

from cti_enrich.tier1.keyword_map import KEYWORD_MAP, KeywordRule, sentence_at

TtpSource = Literal["explicit", "keyword", "llm"]

_EXPLICIT_RE = re.compile(r"(?<![\w.])T\d{4}(?:\.\d{3})?(?!\w|\.\d)")


@dataclass(frozen=True)
class SourcedTechnique:
    ttp_id: str
    ttp_name: str
    source: TtpSource
    evidence: str


def _compile(phrases: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(phrases) + r")\b", re.IGNORECASE)


# Dikompilasi sekali saat import; peta konstan.
_COMPILED: tuple[tuple[KeywordRule, re.Pattern[str], re.Pattern[str] | None], ...] = tuple(
    (rule, _compile(rule.phrases), _compile(rule.requires) if rule.requires else None)
    for rule in KEYWORD_MAP
)


def extract_techniques(text: str, catalog: TechniqueCatalog) -> list[SourcedTechnique]:
    found: dict[str, SourcedTechnique] = {}
    if not catalog.is_empty:
        for m in _EXPLICIT_RE.finditer(text):
            tid = m.group(0)
            if tid in catalog.names and tid not in found:
                found[tid] = SourcedTechnique(
                    tid, catalog.names[tid], "explicit", sentence_at(text, m.start())
                )
    for rule, pattern, requires in _COMPILED:
        if rule.ttp_id in found:
            continue
        m = pattern.search(text)
        if m is None or (requires is not None and requires.search(text) is None):
            continue
        # Katalog terisi: ID di luar katalog dibuang (konsisten dengan eksplisit).
        if not catalog.is_empty and rule.ttp_id not in catalog.names:
            continue
        name = catalog.names.get(rule.ttp_id, rule.ttp_name)
        found[rule.ttp_id] = SourcedTechnique(
            rule.ttp_id, name, "keyword", sentence_at(text, m.start())
        )
    return list(found.values())
