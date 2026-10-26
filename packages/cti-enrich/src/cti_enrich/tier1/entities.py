"""Pencocok entitas tier 1 (actor/malware/tool) di teks artikel.

Pure. Dua regex alternasi (satu case-insensitive, satu case-sensitive) dikompilasi
sekali per versi kamus. Alternasi dibangun sebagai trie (bukan `a|b|c` datar):
dengan ~5000 nama, alternasi datar mencoba semua cabang di tiap posisi teks dan
lambat di artikel panjang; trie cuma menelusuri cabang yang awalannya cocok.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cti_enrich.tier1.dictionary import EntityDictionary, Kind

# Nama yang juga kata biasa; wajib ada kata konteks di dekatnya.
AMBIGUOUS: frozenset[str] = frozenset(
    {
        "cobalt",
        "play",
        "royal",
        "hive",
        "medusa",
        "castle",
        "slug",
        "akira",
        "cactus",
        "cicada",
        "dune",
        "lynx",
        "karma",
        "everest",
        "nemesis",
        "phobos",
        "mercury",
        "nickel",
        "copper",
        "outlaw",
        # P4 eval: nama software/grup ATT&CK yang juga kata biasa (false positive di 57 artikel).
        "tor",
        "chaos",
        "exodus",
        "cuba",
        "embargo",
        "responder",
        "equation",
        "silence",
        "harvester",
        "comando",
        "rtm",
    }
)

# P4 eval: software ATT&CK yang namanya utilitas Windows / kata Inggris umum ("at" 40x salah,
# "cmd" 9x, "Net" 6x, "route" 6x, ...). Untuk nama ini HANYA bentuk `<nama>.exe` yang cocok;
# kata telanjang tidak pernah. Canonical tetap nama ATT&CK. Nama yang khas (netstat, certutil,
# Nltest, PsExec, schtasks) sengaja TIDAK di sini. Daftar kurasi: kebanyakan nama <= 6 huruf yang
# juga kata Inggris/perintah umum (at, cmd, net, whoami, ...), plus tiga perintah > 6 huruf yang
# lazim muncul di prosa (tasklist, systeminfo, ipconfig).
WINDOWS_UTILITY_NAMES: frozenset[str] = frozenset(
    {
        "at",
        "cmd",
        "net",
        "route",
        "expand",
        "reg",
        "netsh",
        "ping",
        "tasklist",
        "systeminfo",
        "whoami",
        "ipconfig",
        "arp",
        "sc",
        "ftp",
        "find",
        "copy",
        "del",
        "dir",
        "query",
    }
)

CONTEXT_WORDS: tuple[str, ...] = (
    "ransomware",
    "group",
    "gang",
    "APT",
    "threat actor",
    "hackers",
    "operators",
    "affiliate",
    "crew",
    "cluster",
    "tracked as",
    "malware",
    "backdoor",
    "loader",
    "stealer",
    "RAT",
)
CONTEXT_WINDOW = 200

_CONTEXT_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(w) for w in CONTEXT_WORDS) + r")(?!\w)", re.IGNORECASE
)


@dataclass(frozen=True)
class EntityHit:
    canonical: str
    kind: Kind
    matched: str
    offset: int


def _trie_pattern(words: list[str]) -> str:
    """Regex alternasi dari trie; cabang terpanjang dicoba dulu di tiap simpul."""
    root: dict[str, Any] = {}
    for word in words:
        node = root
        for ch in word:
            node = node.setdefault(ch, {})
        node[""] = {}

    def render(node: dict[str, Any]) -> str:
        branches = [re.escape(ch) + render(child) for ch, child in sorted(node.items()) if ch != ""]
        if len(branches) == 1 and "" not in node:
            return branches[0]
        body = "|".join(branches)
        if "" in node:
            # Akhir kata boleh berhenti di sini; cabang yang lebih panjang dicoba lebih dulu.
            return f"(?:{body})?" if body else ""
        return f"(?:{body})"

    return render(root)


_COMPILED: dict[str, tuple[re.Pattern[str] | None, re.Pattern[str] | None]] = {}
_COMPILED_MAX = 4  # kamus berganti versi tiap data berubah; simpan beberapa terakhir saja


def _compile(dictionary: EntityDictionary) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    cached = _COMPILED.get(dictionary.version)
    if cached is not None:
        return cached
    insensitive = [k for k, e in dictionary.entries.items() if not e.case_sensitive]
    sensitive = [k for k, e in dictionary.entries.items() if e.case_sensitive]

    def build(keys: list[str], flags: int) -> re.Pattern[str] | None:
        if not keys:
            return None
        # Case-folding dibatasi ASCII lewat flag lokal: tanpa itu U+017F (s panjang) dan U+212A
        # (tanda Kelvin) ikut cocok dengan "s"/"k" tapi `.lower()`-nya bukan key kamus (KeyError).
        # Batas kata tetap Unicode, jadi teks CJK/aksara lain tidak berubah.
        body = f"(?a:{_trie_pattern(keys)})" if flags else _trie_pattern(keys)
        return re.compile(rf"(?<!\w)(?:{body})(?!\w)", flags)

    compiled = (build(insensitive, re.IGNORECASE), build(sensitive, 0))
    _COMPILED[dictionary.version] = compiled
    while len(_COMPILED) > _COMPILED_MAX:
        del _COMPILED[next(iter(_COMPILED))]
    return compiled


def _has_context(text: str, start: int, end: int) -> bool:
    left = text[max(0, start - CONTEXT_WINDOW) : start]
    right = text[end : end + CONTEXT_WINDOW]
    return bool(_CONTEXT_RE.search(left) or _CONTEXT_RE.search(right))


def match_entities(text: str, dictionary: EntityDictionary) -> list[EntityHit]:
    """Satu hit per canonical (kemunculan pertama), urut offset."""
    insensitive, sensitive = _compile(dictionary)
    spans: list[tuple[int, int, str]] = []  # (start, end, key)
    if insensitive is not None:
        spans.extend((m.start(), m.end(), m.group().lower()) for m in insensitive.finditer(text))
    if sensitive is not None:
        spans.extend((m.start(), m.end(), m.group()) for m in sensitive.finditer(text))

    # Overlap: pertahankan span terpanjang ("Cobalt Strike" menang atas "Cobalt").
    spans.sort(key=lambda s: (-(s[1] - s[0]), s[0]))
    starts: list[int] = []
    accepted: dict[int, tuple[int, str]] = {}
    for start, end, key in spans:
        i = bisect.bisect_left(starts, start)
        if i > 0 and accepted[starts[i - 1]][0] > start:
            continue
        if i < len(starts) and starts[i] < end:
            continue
        starts.insert(i, start)
        accepted[start] = (end, key)

    hits: list[EntityHit] = []
    seen: set[str] = set()
    for start in starts:
        end, key = accepted[start]
        entity = dictionary.entries[key]
        if entity.canonical in seen:
            continue
        if entity.needs_context and not _has_context(text, start, end):
            continue
        seen.add(entity.canonical)
        hits.append(EntityHit(entity.canonical, entity.kind, text[start:end], start))
    return hits
