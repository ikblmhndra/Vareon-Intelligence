"""Normalisasi TTP hasil ekstraksi LLM ke katalog MITRE ATT&CK.

Latar (QA 2026-10-01, BUG-C01/BUG-04/BUG-B8): `extract_ttps` (cti-enrich)
minta LLM ngembaliin PASANGAN `(technique_id, technique_name)` dan pasangan
itu dulu disimpan apa adanya ke `article_ttps`. LLM sering ngasih pasangan
yang gak nyambung:

  - ID salah buat nama yang benar: "Exploitation for Privilege Escalation"
    dikasih T1548 (harusnya T1068), "Credential Dumping" dikasih T1110
    (harusnya T1003, nama lama "OS Credential Dumping").
  - Nama TACTIC dianggap technique: "Privilege Escalation" -> T1548,
    "Lateral Movement" -> T1570, "Persistence" -> T1547.
  - Nama karangan buat ID yang benar: T1203 "Remote Code Execution"
    (resminya "Exploitation for Client Execution").

Ditambah agregasi dashboard/heatmap yang GROUP BY `(ttp_id, ttp_name)` --
satu ID dengan tiga nama beda jadi tiga kolom dengan angka sama.

Modul ini murni (tanpa DB): `TechniqueCatalog` dibangun dari tabel
`attack_techniques`/`attack_tactics`/`attack_technique_aliases` (diisi sync
ATT&CK, lihat `cti_core.db.repositories.ttp_catalog`), lalu
`normalize_ttps()` mutusin ID + nama kanonik per pasangan LLM. Aturannya
(urutan penting):

  1. Nama dikenali katalog (nama technique kini, nama technique REVOKED
     dari bundel STIX, atau nama lama hasil rename -- `_RENAMED_SAME_ID`)
     -> NAMA yang menang, ID ikut katalog. LLM jauh lebih konsisten di
     nama daripada di nomor ID (semua kasus QA di atas: ID-nya yang salah).
     Pengecualian: ID LLM sub-technique dari technique yang disebut namanya
     (T1059.001 + "Command and Scripting Interpreter") -> ID LLM dipakai,
     lebih spesifik.
  2. Nama = nama TACTIC -> DIBUANG. Tactic bukan technique; ID yang
     nempel di situ tebakan LLM, gak bisa dipercaya.
  3. Nama gak dikenali tapi ID ada di katalog -> ID dipakai, nama diganti
     nama kanonik.
  4. ID technique REVOKED (mis. T1086) -> ID penggantinya (revoked-by).
  5. Sisanya (ID & nama sama-sama gak dikenal) -> dibuang.

Katalog KOSONG (ATT&CK belum pernah di-sync, mis. dev/test) -> mode
pass-through: cuma validasi format ID + buang nama tactic (daftar cadangan
`_FALLBACK_TACTIC_NAMES`), nama LLM disimpan apa adanya. Enrichment gak
boleh gagal/bisu cuma karena sync ATT&CK belum jalan.

Teks asli LLM tetap disimpan (`ArticleTTP.extracted_id`/`extracted_name`)
-- buat audit dan buat remap ulang (`tools/ops/remap_article_ttps.py`)
kalau katalog/aturannya berubah.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple

_TECHNIQUE_ID_RE = re.compile(r"^T\d{4}(?:\.\d{3})?$")
_ID_TOKEN_RE = re.compile(r"[\[(]?\bT\d{4}(?:\.\d{3})?\b[\])]?", re.IGNORECASE)

_MAX_EXTRACTED_ID = 50
_MAX_NAME = 300
"""Panjang kolom `article_ttps.extracted_id`/`ttp_name`/`extracted_name`."""

_FALLBACK_TACTIC_NAMES = frozenset(
    {
        "reconnaissance",
        "resource development",
        "initial access",
        "execution",
        "persistence",
        "privilege escalation",
        "defense evasion",
        "stealth",
        "defense impairment",
        "evasion",
        "credential access",
        "discovery",
        "lateral movement",
        "collection",
        "command and control",
        "exfiltration",
        "impact",
        "inhibit response function",
        "impair process control",
    }
)
"""Cadangan kalau tabel `attack_tactics` kosong -- SELALU digabung dengan
nama tactic dari DB (nama tactic lama tetap nama tactic, bukan technique)."""

_RENAMED_SAME_ID: Mapping[str, str] = {
    "credential dumping": "T1003",
    "command-line interface": "T1059",
    "standard application layer protocol": "T1071",
    "remote file copy": "T1105",
    "standard non-application layer protocol": "T1095",
    "connection proxy": "T1090",
    "indicator removal on host": "T1070",
    "exfiltration over command and control channel": "T1041",
    "exploitation for defense evasion": "T1211",
}
"""Technique yang DIGANTI NAMA tapi ID-nya tetap. Bundel STIX MITRE cuma
nyimpen nama TERBARU buat objek yang sama (beda dengan technique revoked,
yang objek lamanya ikut di bundel dan masuk `attack_technique_aliases`), jadi
nama lama ini gak bisa diturunkan dari data sync -- padahal LLM (data latih
lama) masih sering pakai. Cuma dipakai kalau ID tujuannya ADA di katalog."""


class NormalizedTTP(NamedTuple):
    """Satu baris `article_ttps` hasil normalisasi. `extracted_*` = teks
    asli LLM (sebelum dinormalisasi)."""

    ttp_id: str
    ttp_name: str
    extracted_id: str | None = None
    extracted_name: str | None = None
    source: str = "llm"
    """Asal teknik: `explicit`/`keyword` (Tier 1) atau `llm`. Default `llm`
    supaya semua pemanggil lama tetap jalan."""
    evidence: str | None = None
    """Kalimat bukti (Tier 1) atau bukti LLM."""


_PUNCT_MAP = str.maketrans({0x2019: "'", 0x2013: "-", 0x2014: "-"})
"""Kutip/strip "keriting" (sering muncul dari LLM) -> ASCII."""


def name_key(name: str) -> str:
    """Kunci pencocokan nama: lowercase, tanda kutip/strip disamakan, ID
    technique yang ikut ditulis di nama ("Phishing (T1566)") dibuang,
    whitespace dirapikan. BUKAN fuzzy -- cuma beda kosmetik yang disamakan."""
    s = name.translate(_PUNCT_MAP)
    s = _ID_TOKEN_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" \t-:.,;")
    return s.lower()


def _parent(attack_id: str) -> str:
    return attack_id.split(".", 1)[0]


@dataclass(frozen=True)
class TechniqueCatalog:
    names: Mapping[str, str] = field(default_factory=dict)
    """attack_id -> nama kanonik."""
    enterprise: frozenset[str] = frozenset()
    """attack_id yang ada di domain enterprise -- prioritas kalau nama ambigu."""
    by_name: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """`name_key` nama kanonik -> attack_id (bisa >1: "Spearphishing
    Attachment" = T1566.001 & T1598.002, "Cloud Accounts" = 4 ID, dst)."""
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """`name_key` nama LAMA (revoked/rename) -> attack_id pengganti."""
    revoked_ids: Mapping[str, str] = field(default_factory=dict)
    """attack_id revoked -> attack_id pengganti."""
    tactic_names: frozenset[str] = _FALLBACK_TACTIC_NAMES

    @property
    def is_empty(self) -> bool:
        return not self.names

    @classmethod
    def build(
        cls,
        *,
        techniques: Iterable[tuple[str, str, Sequence[str]]],
        tactics: Iterable[str] = (),
        revoked: Iterable[tuple[str, str, str]] = (),
    ) -> TechniqueCatalog:
        """`techniques`: `(attack_id, name, domains)`; `tactics`: nama
        tactic; `revoked`: `(attack_id lama, nama lama, attack_id pengganti)`."""
        names: dict[str, str] = {}
        enterprise: set[str] = set()
        by_name: dict[str, list[str]] = {}
        for attack_id, name, domains in techniques:
            if not attack_id or not name:
                continue
            names.setdefault(attack_id, name)
            if "enterprise-attack" in (domains or ()):
                enterprise.add(attack_id)
            ids = by_name.setdefault(name_key(name), [])
            if attack_id not in ids:
                ids.append(attack_id)

        aliases: dict[str, list[str]] = {}
        revoked_ids: dict[str, str] = {}
        for old_id, old_name, new_id in revoked:
            if new_id not in names:
                continue
            if old_id:
                revoked_ids.setdefault(old_id, new_id)
            key = name_key(old_name or "")
            if key and key not in by_name:
                ids = aliases.setdefault(key, [])
                if new_id not in ids:
                    ids.append(new_id)
        for key, new_id in _RENAMED_SAME_ID.items():
            if new_id in names and key not in by_name:
                ids = aliases.setdefault(key, [])
                if new_id not in ids:
                    ids.append(new_id)

        def _sorted(ids: list[str]) -> tuple[str, ...]:
            return tuple(sorted(ids, key=lambda i: (i not in enterprise, i)))

        return cls(
            names=names,
            enterprise=frozenset(enterprise),
            by_name={k: _sorted(v) for k, v in by_name.items()},
            aliases={k: _sorted(v) for k, v in aliases.items()},
            revoked_ids=revoked_ids,
            tactic_names=_FALLBACK_TACTIC_NAMES | {name_key(t) for t in tactics if t},
        )

    def _candidates(self, raw_name: str) -> tuple[str, ...]:
        key = name_key(raw_name)
        if not key:
            return ()
        if key in self.by_name:
            return self.by_name[key]
        if key in self.aliases:
            return self.aliases[key]
        # Format tampilan ATT&CK "Parent: Sub-technique" ("Phishing:
        # Spearphishing Attachment") -- cocokin bagian sub, prioritas yang
        # parent-nya sesuai bagian depan.
        if ":" in key:
            head, _, tail = key.partition(":")
            subs = self.by_name.get(tail.strip(), ())
            head_ids = set(self.by_name.get(head.strip(), ()))
            under_head = tuple(s for s in subs if _parent(s) in head_ids)
            return under_head or subs
        return ()

    def _pick(self, candidates: tuple[str, ...], raw_id: str) -> str:
        if raw_id in candidates:
            return raw_id
        # ID LLM = sub-technique dari technique yang disebut namanya -> lebih spesifik.
        if raw_id in self.names and _parent(raw_id) in candidates:
            return raw_id
        same_family = [c for c in candidates if _parent(c) == _parent(raw_id)]
        if same_family:
            return same_family[0]
        return candidates[0]

    def is_tactic_name(self, raw_name: str) -> bool:
        key = name_key(raw_name)
        return key in self.tactic_names and key not in self.by_name

    def resolve(self, raw_id: str, raw_name: str) -> tuple[str, str] | None:
        """`(attack_id, nama kanonik)` atau `None` (dibuang) -- aturan di
        docstring modul."""
        tid = (raw_id or "").strip().upper()
        if self.is_empty:
            if not _TECHNIQUE_ID_RE.match(tid) or self.is_tactic_name(raw_name):
                return None
            return tid, (raw_name or "").strip()[:_MAX_NAME] or tid

        candidates = self._candidates(raw_name or "")
        if candidates:
            chosen = self._pick(candidates, tid)
            return chosen, self.names[chosen]
        if self.is_tactic_name(raw_name or ""):
            return None
        if tid in self.names:
            return tid, self.names[tid]
        if tid in self.revoked_ids:
            new_id = self.revoked_ids[tid]
            return new_id, self.names[new_id]
        return None


def normalize_ttps(
    pairs: Iterable[tuple[str, str]], catalog: TechniqueCatalog
) -> list[NormalizedTTP]:
    """Normalisasi + dedup PER ID hasil akhir (pasangan pertama yang menang
    -- sama aturan `_first_ttps` di repo artikel). Urutan input dijaga."""
    out: dict[str, NormalizedTTP] = {}
    for raw_id, raw_name in pairs:
        resolved = catalog.resolve(raw_id or "", raw_name or "")
        if resolved is None:
            continue
        tid, tname = resolved
        if tid in out:
            continue
        out[tid] = NormalizedTTP(
            ttp_id=tid,
            ttp_name=tname[:_MAX_NAME],
            extracted_id=(raw_id or "").strip()[:_MAX_EXTRACTED_ID] or None,
            extracted_name=(raw_name or "").strip()[:_MAX_NAME] or None,
        )
    return list(out.values())


_CITATION_RE = re.compile(r"\s*\(Citation:[^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:https?://[^)\s]+)\)")
_CODE_TAG_RE = re.compile(r"</?code>")


def clean_attack_text(text: str | None) -> str:
    """Deskripsi STIX ATT&CK -> teks polos buat UI (BUG-C18): buang
    `(Citation: ...)`, link markdown `[Nama](https://...)` jadi `Nama`,
    tag `<code>` dibuang. Paragraf (baris baru) dipertahankan."""
    if not text:
        return ""
    s = _CITATION_RE.sub("", text)
    s = _MD_LINK_RE.sub(r"\1", s)
    s = _CODE_TAG_RE.sub("", s)
    s = re.sub(r"[ \t]+([.,;:])", r"\1", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()
