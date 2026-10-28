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
_VICTIM_PATTERN = re.compile(rf"\b({_NAME}) (?:confirms|discloses)\b")

# (label terbaca untuk `reasons`, regex). "reports/says" sengaja TIDAK ada di pola
# korban: vendor/peneliti ("Mandiant says ...") bukan organisasi yang diretas.
_VERBS: tuple[tuple[str, str], ...] = (
    ("breached", r"breached"),
    ("hacked", r"hacked"),
    ("confirms attack", r"confirms? (?:a |an )?(?:ransomware |cyber)?[- ]?attack"),
    ("ransomware attack on", r"ransomware attack on"),
    ("data stolen", r"data (?:was )?stolen"),
    ("leaked", r"leaked"),
    ("data breach at", r"data breach at"),
    ("disrupted by cyberattack", r"disrupted by (?:a )?cyber[- ]?attack"),
    ("systems encrypted", r"systems encrypted"),
    ("confirms breach", r"confirms? (?:a )?(?:data )?breach"),
)
_VERB_RE = tuple((label, re.compile(rf"\b{rx}\b", re.IGNORECASE)) for label, rx in _VERBS)

# `may`/`could` dicocokkan case-sensitive huruf kecil supaya bulan "May" lolos.
_GUIDE: tuple[tuple[str, str, int], ...] = (
    ("how to", r"how to", re.IGNORECASE),
    ("guide", r"guide", re.IGNORECASE),
    ("best practices", r"best practices", re.IGNORECASE),
    ("what is", r"what is", re.IGNORECASE),
    ("explained", r"explained", re.IGNORECASE),
    ("tips", r"tips", re.IGNORECASE),
    ("report:", r"report:", re.IGNORECASE),
    ("predictions", r"predictions?", re.IGNORECASE),
    ("could", r"could", 0),
    ("may", r"may", 0),
)
_GUIDE_RE = tuple((label, re.compile(rf"\b{rx}(?!\w)", flags)) for label, rx, flags in _GUIDE)


@dataclass(frozen=True)
class IncidentVerdict:
    confirmed: bool
    reasons: tuple[str, ...]
    victim: str | None = None
    """Korban yang ditemukan aturan: nama dari LLM (di-strip) atau teks yang cocok dengan
    `_VICTIM_PATTERN`; dipakai artikel yang lolos gate relevansi (P5) karena LLM classify
    dilewati dan tidak ada `victim_name` lain."""


def incident_verdict(title: str, text: str, victim_name: str | None) -> IncidentVerdict:
    """`confirmed` bila ada korban DAN kata kerja insiden DAN bukan judul panduan.

    Kata kerja dicari di judul + 500 karakter awal isi (lede berita);
    pola panduan hanya di judul (isi berita insiden wajar memuat "could").
    """
    head = f"{title}\n{text[:_HEAD_WINDOW]}"
    reasons: list[str] = []

    victim: str | None = None
    if victim_name and victim_name.strip():
        victim = victim_name.strip()
        reasons.append("victim:llm")
    elif (m := _VICTIM_PATTERN.search(head)) is not None:
        victim = m.group(1).strip()
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

    return IncidentVerdict(
        confirmed=victim is not None and verb and not guide,
        reasons=tuple(reasons),
        victim=victim,
    )
