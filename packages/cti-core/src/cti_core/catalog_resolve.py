"""Resolver identitas produk: (vendor, produk) mentah dari data CNA -> (vendor, keluarga) katalog.

`docs/ROADMAP.md` #19, rancangan di `docs/CVE_CATALOG_DESIGN.md` 3.3. Modul MURNI: tanpa DB, tanpa
jaringan. Aturannya diturunkan dari spike di data penuh (117.220 CVE, `docs/spikes/`) dan dikunci
tes, bukan ditebak:

- **Normalisasi sadar-unicode** (huruf/angka apa pun, termasuk CJK; tanda baca jadi spasi). Versi
  ASCII di spike pertama menghapus nama produk CJK sehingga dihitung "placeholder".
- **Produk sampah -> tidak punya identitas** (`None`): placeholder (`n/a`, `unknown`, `_`), kata
  generik (`software`, `firmware`), mirip-versi, angka-saja, URL. SEMPIT dengan sengaja: bentuk
  janggal yang tetap produk asli (`owner/repo`, judul plugin panjang, nama memuat `and`/`&`) BUKAN
  sampah.
- **Vendor**: kunci = bentuk kompak tanpa akhiran legal (`Palo Alto Networks` = `paloaltonetworks`,
  `Oracle Corporation` = `oracle`). Vendor placeholder/kosong -> vendor "(tanpa vendor)" yang tidak
  bisa di-monitor di tingkat vendor.
- **Keluarga**: produk dengan token versi di ujung dibuang (`windows 10 version 1507` ->
  `windows`), ditambah akhiran noise yang diketahui (`server core installation`). Hanya 562 keluarga
  yang bervarian > 1 di data nyata, jadi di luar Windows/perangkat keras keluarga praktis sama
  dengan produk; Monitor tingkat vendor adalah jaring pengaman bila lipat otomatis salah.
- **Alias** (koreksi manual/merge admin, kelak): `alias_key -> family_key`, dicek SEBELUM lipat
  otomatis, sehingga koreksi tidak hilang saat ingest berikutnya.

Yang sengaja BUKAN tugas modul ini: menyimpan ke DB (irisan 2), dan memutuskan nama tampilan yang
dipakai (katalog memilih ejaan mentah paling sering; di sini hanya ejaan mentah pertama).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

VENDOR_NONE_KEY = "~none"
VENDOR_NONE_DISPLAY = "(tanpa vendor)"

_RE_TOKEN = re.compile(r"[^\W_]+")
_RE_VERSIONISH = re.compile(r"^v?\d+(\.\d+)+([a-z0-9.\-]*)$")
_RE_VERSION_TOKEN = re.compile(
    r"^(version|ver|v\d+|\d+[a-z]?\d*|\d+h\d|r\d+|sp\d+|edition|x64|x86|arm64|32|64|bit)$"
)
_RE_CPE23 = re.compile(r"^cpe:2\.3:[aho*-]:([^:]+):([^:]+):")
_RE_CPE22 = re.compile(r"^cpe:/[aho]:([^:]+):([^:]+)")

_PLACEHOLDERS = frozenset(
    {"", "n a", "na", "none", "unknown", "unspecified", "various", "not applicable", "tbd", "null"}
)
_GENERIC_PRODUCTS = frozenset(
    {
        "software", "application", "applications", "product", "products", "firmware", "plugin",
        "plugins", "system", "systems", "server", "website", "platform", "library", "module",
        "component", "components", "device", "devices", "all", "other", "multiple products",
        "multiple", "web application", "mobile application", "operating system",
    }
)  # fmt: skip
# Akhiran legal yang aman dibuang dari nama vendor. TIDAK memuat akhiran satu huruf atau yang
# ambigu (`as`, `s`, `a`): di data nyata itu menggabungkan `n` dengan `n a`. Dicek di katalog
# nyata: 127 grup vendor bergabung karena ini (Microsoft/Microsoft Inc, Oracle/Oracle Corporation,
# D-Link/D-Link Corporation, ...), semuanya benar.
_LEGAL_SUFFIXES = frozenset(
    {
        "inc", "incorporated", "corp", "corporation", "ltd", "limited", "llc", "gmbh", "co",
        "company", "plc", "pty", "pte", "bv", "nv", "ag", "sa", "ab", "oy", "kg", "lp", "llp",
        "srl", "spa", "sas", "kk",
    }
)  # fmt: skip
_NOISE_SUFFIXES = ("server core installation",)
_MIN_KEY_LEN = 2


def normalize(text: str) -> str:
    """Huruf kecil, semua non-huruf/angka jadi satu spasi (unicode: nama CJK tetap utuh)."""
    return " ".join(_RE_TOKEN.findall(text.lower()))


def compact(text: str) -> str:
    """Tanpa spasi: `Palo Alto` = `PaloAlto`."""
    return "".join(_RE_TOKEN.findall(text.lower()))


def junk_reason(product: str) -> str | None:
    """Alasan nama produk BUKAN identitas sama sekali, atau `None`."""
    norm = normalize(product)
    if norm in _PLACEHOLDERS:
        return "placeholder"
    if norm in _GENERIC_PRODUCTS:
        return "generik"
    if _RE_VERSIONISH.match(product.strip().lower()):
        return "mirip-versi"
    if re.fullmatch(r"[0-9 ]+", norm):
        return "angka-saja"
    lowered = product.lower()
    if "http://" in lowered or "https://" in lowered or "github.com" in lowered:
        return "url"
    return None


def vendor_key(vendor: str) -> str:
    """Kunci vendor: kompak, akhiran legal dibuang. `~none` untuk vendor placeholder/kosong."""
    tokens = normalize(vendor).split()
    if " ".join(tokens) in _PLACEHOLDERS:
        return VENDOR_NONE_KEY
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    key = "".join(tokens)
    return key if len(key) >= _MIN_KEY_LEN else VENDOR_NONE_KEY


def fold_family(product_norm: str) -> str:
    """Produk ternormalisasi -> keluarga: buang akhiran noise yang diketahui, lalu token versi di
    ujung (berulang). Selalu menyisakan >= 1 token."""
    text = product_norm
    for suffix in _NOISE_SUFFIXES:
        if text.endswith(" " + suffix):
            text = text[: -len(suffix) - 1].rstrip()
    tokens = text.split()
    while len(tokens) > 1 and _RE_VERSION_TOKEN.match(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


@dataclass(frozen=True)
class AffectedEntry:
    """Satu elemen `containers.cna.affected[]` dari CVE JSON 5.x (hanya field yang dipakai)."""

    vendor: str = ""
    product: str = ""
    package: str = ""
    cpes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Resolved:
    vendor_key: str
    vendor_display: str
    family_key: str
    family_display: str
    product_norm: str
    """Produk sebelum dilipat; disimpan di `cve_record_products` supaya pemetaan bisa dihitung
    ulang."""
    source: str
    """`cpe` atau `cna`."""

    @property
    def vendor_monitorable(self) -> bool:
        return self.vendor_key != VENDOR_NONE_KEY


def alias_key(vendor_k: str, product_norm: str) -> str:
    """Kunci tabel alias: vendor + produk kompak."""
    return f"{vendor_k}|{compact(product_norm)}"


def _identity_names(entry: AffectedEntry) -> tuple[str, str, str]:
    for cpe in entry.cpes:
        m = _RE_CPE23.match(cpe) or _RE_CPE22.match(cpe)
        if m and m.group(1) not in ("*", "-") and m.group(2) not in ("*", "-"):
            return m.group(1).replace("\\", ""), m.group(2).replace("\\", ""), "cpe"
    return entry.vendor, entry.product or entry.package, "cna"


def resolve(entry: AffectedEntry, *, aliases: Mapping[str, str] | None = None) -> Resolved | None:
    """`None` bila produk sampah. `aliases`: `alias_key -> family_key` (dicek sebelum lipat
    otomatis)."""
    vendor_raw, product_raw, source = _identity_names(entry)
    if junk_reason(product_raw) is not None:
        return None
    product_norm = normalize(product_raw)
    vkey = vendor_key(vendor_raw)

    mapped = aliases.get(alias_key(vkey, product_norm)) if aliases else None
    if mapped is not None:
        family = mapped
    else:
        family = fold_family(product_norm)
        # `Microsoft 365` tidak boleh terlipat jadi `microsoft` (= nama vendor): keluarga yang sama
        # dengan vendornya akan menipu Monitor tingkat keluarga.
        if family != product_norm and compact(family) == vkey:
            family = product_norm

    vendor_display = (
        vendor_raw.strip().replace("_", " ") if vkey != VENDOR_NONE_KEY else VENDOR_NONE_DISPLAY
    )
    # Ejaan mentah hanya cocok sebagai nama tampilan bila keluarga = produk itu sendiri; keluarga
    # hasil lipat/alias ("windows" dari "Windows 10 Version 1507") ditampilkan dari kuncinya.
    family_display = (
        product_raw.strip().replace("_", " ") if family == product_norm else family.title()
    )
    return Resolved(
        vendor_key=vkey,
        vendor_display=vendor_display,
        family_key=family,
        family_display=family_display,
        product_norm=product_norm,
        source=source,
    )


def resolve_all(
    entries: Iterable[AffectedEntry], *, aliases: Mapping[str, str] | None = None
) -> list[Resolved]:
    """Identitas unik (vendor_key, family_key) dari semua elemen `affected`, urutan kemunculan
    dijaga. Elemen sampah dilewati."""
    seen: dict[tuple[str, str], Resolved] = {}
    for entry in entries:
        r = resolve(entry, aliases=aliases)
        if r is not None:
            seen.setdefault((r.vendor_key, r.family_key), r)
    return list(seen.values())


def entries_from_cna(cna: Mapping[str, object]) -> list[AffectedEntry]:
    """`containers.cna` (dict) -> `AffectedEntry`. Toleran terhadap bentuk yang rusak."""
    out: list[AffectedEntry] = []
    affected = cna.get("affected")
    for aff in affected if isinstance(affected, list) else []:
        if not isinstance(aff, dict):
            continue
        raw_cpes = aff.get("cpes")
        cpes = (
            tuple(c for c in raw_cpes if isinstance(c, str)) if isinstance(raw_cpes, list) else ()
        )
        out.append(
            AffectedEntry(
                vendor=str(aff.get("vendor") or ""),
                product=str(aff.get("product") or ""),
                package=str(aff.get("packageName") or ""),
                cpes=cpes,
            )
        )
    return out
