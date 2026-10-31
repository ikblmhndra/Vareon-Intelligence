"""Daftar nama yang juga kata biasa (aturan konteks Tier 1, P4) dan aturan satu kata.

Dipindah dari `cti_enrich.tier1.entities` (P7c Task 7) supaya merge alias Galaxy di cti-core bisa
memakainya tanpa mengimpor cti-enrich; `cti_enrich.tier1.entities`/`dictionary` mengekspor ulang.
Pure: tanpa DB.
"""

from __future__ import annotations

import re

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


def is_single_token(lowered: str) -> bool:
    """Nama satu kata huruf saja ("turla", "basin"): aturan P4 meminta kata konteks untuk nama
    seperti ini kalau asalnya hanya `threat_actor_groups` (bukan kurasi ATT&CK)."""
    return re.fullmatch(r"[a-z]+", lowered) is not None
