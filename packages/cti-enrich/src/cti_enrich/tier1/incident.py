"""Aturan insiden tier 1 (bayangan): korban + kata kerja insiden - judul panduan.

Murni regex, tanpa spaCy/LLM. Presisi di atas recall: judul advisori,
kerentanan, tren, atau panduan ("how to", "could", "may") tidak pernah
dianggap insiden terkonfirmasi, walau ada nama organisasi dan kata "breach".
Hasilnya hanya dibandingkan dengan `confirmed_incident` milik LLM (mode
bayangan); tidak mengubah keputusan pipeline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEAD_WINDOW = 500

# Nama berkapital 1-4 kata diikuti kata kerja pengumuman. Pemisah spasi tunggal
# (bukan `\s`) supaya tidak melompati kalimat/baris.
_NAME = r"[A-Z][\w&'-]*(?: [A-Z][\w&'-]*){0,3}"
_VICTIM_PATTERN = re.compile(rf"\b({_NAME}) (?:confirms|discloses|reports|says)\b")

_VERBS: tuple[str, ...] = (
    r"breached",
    r"hacked",
    r"confirms? (?:a |an )?(?:cyber)?[- ]?attack",
    r"ransomware attack on",
    r"data (?:was )?stolen",
    r"leaked",
    r"data breach at",
    r"disrupted by (?:a )?cyber[- ]?attack",
    r"systems encrypted",
    r"confirms? (?:a )?(?:data )?breach",
)
_VERB_RE = tuple((v, re.compile(rf"\b{v}\b", re.IGNORECASE)) for v in _VERBS)

_GUIDE: tuple[str, ...] = (
    r"how to",
    r"guide",
    r"best practices",
    r"what is",
    r"explained",
    r"tips",
    r"report:",
    r"predictions?",
    r"could",
    r"may",
)
_GUIDE_RE = tuple((g, re.compile(rf"\b{g}(?!\w)", re.IGNORECASE)) for g in _GUIDE)


@dataclass(frozen=True)
class IncidentVerdict:
    confirmed: bool
    reasons: tuple[str, ...]


def incident_verdict(title: str, text: str, victim_name: str | None) -> IncidentVerdict:
    """`confirmed` bila ada korban DAN kata kerja insiden DAN bukan judul panduan.

    Kata kerja dicari di judul + 500 karakter awal isi (lede berita);
    pola panduan hanya di judul (isi berita insiden wajar memuat "could").
    """
    head = f"{title}\n{text[:_HEAD_WINDOW]}"
    reasons: list[str] = []

    victim = False
    if victim_name and victim_name.strip():
        victim = True
        reasons.append("victim:llm")
    elif _VICTIM_PATTERN.search(head):
        victim = True
        reasons.append("victim:pattern")

    verb = False
    for phrase, rx in _VERB_RE:
        if rx.search(head):
            verb = True
            reasons.append(f"verb:{phrase}")
            break

    guide = False
    for phrase, rx in _GUIDE_RE:
        if rx.search(title):
            guide = True
            reasons.append(f"guide:{phrase}")
            break

    return IncidentVerdict(confirmed=victim and verb and not guide, reasons=tuple(reasons))
