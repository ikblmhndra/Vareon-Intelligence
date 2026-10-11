"""Pemeriksaan grounding keluaran LLM terhadap masukannya (#21 PR 3; dipakai lagi oleh ringkasan
newsletter di PR 8). Murni: tanpa LLM, tanpa DB, dan SENGAJA tanpa impor dari service mana pun
(hanya stdlib, dijaga test), supaya recap dan newsletter memakai satu kode yang sama dan modul ini
tidak ikut berubah kalau bentuk keluaran salah satunya berubah.

**Kenapa.** CVE, threat actor, atau kampanye yang tidak ada di masukan adalah karangan model, dan
satu yang lolos cukup untuk menghilangkan kepercayaan analis pada seluruh ringkasan. Maka tiap CVE
id, nama threat actor, tema kampanye, dan sumber di keluaran harus ada di MASUKAN yang dipakai
membangun prompt (`Known`, dikembalikan pembangun prompt bersama prompt-nya). Yang gagal DIBUANG
dari yang ditampilkan DAN dicatat (`Grounder.report`): tidak ada yang hilang diam-diam.

**Story diverifikasi lewat ID artikel, bukan judul.** Model memparafrasekan judul, jadi pencocokan
judul membuang berita yang nyata. Tiap baris artikel di prompt membawa `[#<id>]`, tiap story
mengembalikan `article_id`, dan hanya id yang ada di masukan yang lolos; story yang lolos mendapat
`url` dan `source` dari artikelnya sendiri (halaman menautkannya).

**CVE id di teks bebas.** Yang berbentuk id bisa dikenali di teks apa pun (`extract_cve_ids`), jadi
id yang tidak ada di masukan diganti penanda `[unverified CVE]` (dan dicatat) alih-alih membuang
satu kalimat utuh: kalimatnya tetap terbaca dan penggantinya terlihat. Id dikenali apa adanya dari
teks prompt: id dari judul artikel atau teks tweet juga sah, bukan hanya yang ada di daftar CVE.

**Nama (actor, kampanye, sumber).** Dikenali kalau kuncinya (huruf/angka saja, tanpa kapitalisasi,
spasi, atau tanda hubung: "APT 41" = "apt-41") ada di himpunan masukan, ATAU frasanya muncul utuh
(per kata) di teks prompt. Yang kedua mencegah buangan palsu untuk nama yang hanya disebut di judul
atau tweet; yang memang karangan tetap tidak ada di teks. Parafrasa tema kampanye TIDAK dikenali:
prompt meminta salinan persis, dan yang diparafrasekan dibuang serta dicatat, bukan lolos diam-diam.

Alasan (`Dropped.reason`): `not_in_input`, `malformed` (bukan bentuk yang diharapkan),
`no_article_id` (story tanpa id yang bisa dibaca), `unknown_article_id` (id ada tapi bukan artikel
di masukan)."""

from __future__ import annotations

import dataclasses
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any, Literal

NOT_IN_INPUT = "not_in_input"
MALFORMED = "malformed"
NO_ARTICLE_ID = "no_article_id"
UNKNOWN_ARTICLE_ID = "unknown_article_id"

CVE_MARKER = "[unverified CVE]"
"""Pengganti CVE id yang tidak ada di masukan, di teks bebas. Pemanggil berbahasa lain (ringkasan
newsletter Indonesia) memberi penanda sendiri lewat `Grounder(cve_marker=...)`."""

NameKind = Literal["threat_actors", "campaigns", "sources"]

_CLIP = 200
"""Panjang maksimum `value` yang dicatat: keluaran model tidak dipercaya ukurannya."""
_MIN_TEXT_KEY = 3
"""Nama dengan kunci lebih pendek dari ini hanya cocok lewat himpunan masukan, tidak lewat teks:
kata sependek itu ("a", "of") ada di teks apa pun dan membuat pencocokan teks tak berarti."""

# Tanda hubung yang sering dikeluarkan model selain "-": U+2010..U+2015 dan tanda minus U+2212.
# Dibangun dari kode titiknya, bukan ditulis sebagai karakter: aturan RUF001 menolak karakter
# mirip "-" di string literal.
_DASHES = "".join(chr(c) for c in (*range(0x2010, 0x2016), 0x2212))
_SEP = rf"[\s_\-{_DASHES}]"
_CVE_RE = re.compile(rf"(?<![A-Za-z0-9])CVE{_SEP}*([0-9]{{4}}){_SEP}+([0-9]{{4,}})", re.IGNORECASE)
_ARTICLE_ID_RE = re.compile(r"\s*\[?\s*#?\s*([0-9]+)\s*\]?\s*")
_SKIP_KEYS = frozenset({"url"})
"""Kunci yang tidak dipindai `Grounder.free_text`: URL bukan tulisan model, dan slug-nya bisa
memuat string mirip CVE id."""


def normalize_cve_id(raw: str) -> str | None:
    """`CVE-YYYY-NNNN` kanonik dari satu id yang ditulis bebas ("cve-2026-0001", "CVE 2026 0001",
    atau dengan tanda hubung Unicode seperti U+2011); `None` kalau `raw` bukan id."""
    m = _CVE_RE.fullmatch(raw.strip())
    return f"CVE-{m.group(1)}-{m.group(2)}" if m else None


def extract_cve_ids(text: str) -> list[str]:
    """Semua CVE id di `text`, kanonik, unik, urutan kemunculan pertama."""
    seen: dict[str, None] = {}
    for m in _CVE_RE.finditer(text):
        seen.setdefault(f"CVE-{m.group(1)}-{m.group(2)}")
    return list(seen)


def _fold(raw: str) -> str:
    return unicodedata.normalize("NFKC", raw).casefold()


def name_key(raw: str) -> str:
    """Kunci pembanding nama: huruf dan angka saja, tanpa kapitalisasi ("APT 41" == "apt-41")."""
    return "".join(ch for ch in _fold(raw) if ch.isalnum())


def _spaced(raw: str) -> str:
    """Teks dengan tanda baca jadi satu spasi, dibungkus spasi: `" apt41 "` dicari utuh per kata
    lewat `in` tanpa ikut cocok di tengah kata lain."""
    words = re.sub(r"[\W_]+", " ", _fold(raw)).strip()
    return f" {words} " if words else " "


@dataclasses.dataclass(frozen=True)
class ArticleRef:
    """Artikel yang ada di masukan: tujuan tautan dan sumber yang benar untuk sebuah story."""

    url: str
    source: str


@dataclasses.dataclass(frozen=True)
class Known:
    """Yang BOLEH muncul di keluaran: apa yang benar-benar ada di masukan.

    `text` = teks yang dilihat model (sudah dinormalkan); CVE id diambil dari sana juga, jadi id di
    judul atau teks tweet ikut sah. Bangun lewat `Known.build`, dari objek yang SAMA yang dipakai
    menulis prompt, supaya himpunan ini tidak menyimpang dari yang sebenarnya dikirim."""

    text: str
    cve_ids: frozenset[str]
    names: Mapping[str, frozenset[str]]
    articles: Mapping[int, ArticleRef]

    @classmethod
    def build(
        cls,
        *,
        text: str = "",
        cve_ids: Iterable[str] = (),
        threat_actors: Iterable[str] = (),
        campaigns: Iterable[str] = (),
        sources: Iterable[str] = (),
        articles: Mapping[int, ArticleRef] | None = None,
    ) -> Known:
        ids = {c for raw in cve_ids if (c := normalize_cve_id(raw))}
        ids.update(extract_cve_ids(text))

        def keys(names: Iterable[str]) -> frozenset[str]:
            return frozenset(k for n in names if (k := name_key(n)))

        return cls(
            text=_spaced(text),
            cve_ids=frozenset(ids),
            names={
                "threat_actors": keys(threat_actors),
                "campaigns": keys(campaigns),
                "sources": keys(sources),
            },
            articles=dict(articles or {}),
        )


@dataclasses.dataclass(frozen=True)
class Dropped:
    """Satu hal yang dibuang dari keluaran: `field` (jalur di keluaran), `value` (apa yang ditulis
    model, dipotong), `reason` (salah satu konstanta di atas)."""

    field: str
    value: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "value": self.value, "reason": self.reason}


def _clip(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= _CLIP else text[: _CLIP - 1] + "…"


def _article_id(value: object) -> int | None:
    """ID artikel dari `article_id` yang ditulis model: 12, "12", "#12", "[#12]"; selain itu `None`
    (bool bukan id: `True == 1` akan lolos sebagai artikel nomor 1)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and (m := _ARTICLE_ID_RE.fullmatch(value)):
        return int(m.group(1))
    return None


class Grounder:
    """Memeriksa bagian-bagian satu keluaran terhadap `Known` dan mengumpulkan yang dibuang.

    Satu instance per keluaran: panggil metode per bagian (`cve_list`, `name_list`, `stories`),
    lalu `free_text` atas seluruh keluaran, lalu `report()`. Tidak ada yang diubah di tempat: tiap
    metode mengembalikan salinan yang sudah bersih."""

    def __init__(self, known: Known, *, cve_marker: str = CVE_MARKER) -> None:
        self.known = known
        self.cve_marker = cve_marker
        self.dropped: list[Dropped] = []

    def _drop(self, field: str, value: object, reason: str) -> None:
        entry = Dropped(field, _clip(value), reason)
        if entry not in self.dropped:  # id yang sama di dua kalimat satu bidang dicatat sekali
            self.dropped.append(entry)

    def _as_list(self, field: str, value: object) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        self._drop(field, value, MALFORMED)
        return []

    def _knows(self, kind: NameKind, name: str) -> bool:
        key = name_key(name)
        if not key:
            return False
        if key in self.known.names.get(kind, frozenset()):
            return True
        return len(key) >= _MIN_TEXT_KEY and _spaced(name) in self.known.text

    def cve_list(self, field: str, value: object) -> list[Any]:
        """Daftar CVE id (`notable_cves`). Satu entri lolos kalau memuat setidaknya satu id dan
        SEMUA id di dalamnya ada di masukan (model kadang menulis "CVE-2026-1 (critical)": entri
        utuh dipertahankan apa adanya)."""
        kept = []
        for item in self._as_list(field, value):
            ids = extract_cve_ids(item) if isinstance(item, str) else []
            if not ids:
                self._drop(field, item, MALFORMED)
            elif all(i in self.known.cve_ids for i in ids):
                kept.append(item)
            else:
                self._drop(field, item, NOT_IN_INPUT)
        return kept

    def name_list(
        self, field: str, value: object, kind: NameKind, *, key: str | None = None
    ) -> list[Any]:
        """Daftar nama (`active_threat_actors`), atau daftar objek yang namanya ada di `key`
        (`new_threat_actors_added`: `name`, `active_campaigns`: `theme`)."""
        kept = []
        for item in self._as_list(field, value):
            name = item if key is None else (item.get(key) if isinstance(item, dict) else None)
            if not isinstance(name, str) or not name_key(name):
                self._drop(field, item, MALFORMED)
            elif self._knows(kind, name):
                kept.append(item)
            else:
                self._drop(field, name, NOT_IN_INPUT)
        return kept

    def stories(self, field: str, value: object) -> list[dict[str, Any]]:
        """Top stories, diverifikasi lewat `article_id` (lihat docstring modul). Yang lolos
        mendapat `url` dan `source` dari artikelnya; `source` tulisan model yang tidak dikenal
        dicatat (labelnya diganti sumber artikel, ceritanya tetap)."""
        kept = []
        for item in self._as_list(field, value):
            if not isinstance(item, dict):
                self._drop(field, item, MALFORMED)
                continue
            title = item.get("title") if isinstance(item.get("title"), str) else ""
            article_id = _article_id(item.get("article_id"))
            if article_id is None:
                self._drop(field, title or item, NO_ARTICLE_ID)
                continue
            ref = self.known.articles.get(article_id)
            if ref is None:
                self._drop(field, f"{title} [#{article_id}]".strip(), UNKNOWN_ARTICLE_ID)
                continue
            label = item.get("source")
            if isinstance(label, str) and label.strip() and not self._knows("sources", label):
                self._drop(f"{field}.source", label, NOT_IN_INPUT)
            kept.append({**item, "article_id": article_id, "source": ref.source, "url": ref.url})
        return kept

    def free_text(self, field: str, value: Any) -> Any:
        """Salinan `value` (teks, daftar, atau objek bersarang) dengan CVE id yang tidak ada di
        masukan diganti `cve_marker` dan dicatat di jalurnya (mis. `recap.summary`, atau
        `recap.top_stories[0].why_it_matters`). Dijalankan SESUDAH bagian terstruktur, supaya
        indeks di jalurnya cocok dengan keluaran yang disimpan dan id yang sudah dibuang dari
        daftar tidak dicatat dua kali."""
        if isinstance(value, str):
            return self._scrub(field, value)
        if isinstance(value, list):
            return [self.free_text(f"{field}[{i}]", item) for i, item in enumerate(value)]
        if isinstance(value, dict):
            return {
                k: v if k in _SKIP_KEYS else self.free_text(f"{field}.{k}" if field else str(k), v)
                for k, v in value.items()
            }
        return value

    def _scrub(self, field: str, text: str) -> str:
        def replace(m: re.Match[str]) -> str:
            cve = f"CVE-{m.group(1)}-{m.group(2)}"
            if cve in self.known.cve_ids:
                return m.group(0)
            self._drop(field, cve, NOT_IN_INPUT)
            return self.cve_marker

        return _CVE_RE.sub(replace, text)

    def report(self) -> dict[str, Any]:
        """Bentuk yang disimpan di `quality.grounding`."""
        return {"dropped": [d.as_dict() for d in self.dropped], "count": len(self.dropped)}
