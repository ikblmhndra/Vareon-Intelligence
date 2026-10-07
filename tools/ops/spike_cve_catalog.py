#!/usr/bin/env python3
"""Spike pengukuran katalog tech dari data CVE (docs/ROADMAP.md #19, fase 1: "spike").

HANYA BACA. Tidak menyentuh DB, tidak memanggil jaringan, tidak mengubah produk. Menjawab sebelum
satu baris skema ditulis: dari data CVE 2025 sampai sekarang, seberapa bersih "katalog tech
(vendor + produk)" yang bisa diturunkan, dan seberapa banyak dari 34 tech produksi ketemu bersih?

Hanya pustaka standar Python (3.10+): jalan di server dev atau laptop mana pun, tanpa image/venv
proyek. Pencocok kata-utuh di bawah SENGAJA salinan lokal `cti_core.tech_match` supaya skrip ini
tidak bergantung pada versi image yang terpasang.

Sumber data: CVE List V5 (https://github.com/CVEProject/cvelistV5), format CVE JSON 5.x.

    git clone --depth 1 https://github.com/CVEProject/cvelistV5      # beberapa GB, sekali saja
    python3 tools/ops/spike_cve_catalog.py --source cvelistV5 --out spike_report.md \\
        --catalog-csv spike_catalog.csv --tracker-csv tracker.csv

`--source` boleh direktori clone (berisi `cves/`) atau zip rilis (zip bersarang ditangani).
Tahun di nama berkas = tahun ID, BUKAN tahun terbit (CVE-2024-* banyak terbit 2025), jadi yang
disaring adalah `cveMetadata.datePublished >= --since`; tahun ID yang dipindai default
`since.year-1 .. tahun ini` (`--id-years 2023-2026` untuk melebarkan).

Perbandingan dengan tracker (opsional), dari server dev/produksi:

    docker compose ... exec -T postgres psql -U cti -d cti -c \\
      "\\copy (SELECT DISTINCT cve_id, tech FROM cve_tracker WHERE tech IS NOT NULL)
       TO STDOUT CSV HEADER" > tracker.csv

Isi laporan: korpus, cakupan produk, sampah per jenis, duplikasi ejaan, keluarga produk, ekor
panjang, produk teratas, hasil per tech (hit, vonis), dan recall terhadap tracker. Batas
pengukuran yang JUJUR ada di bagian terakhir laporan.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 34 nama dari `SELECT DISTINCT name FROM techstack_entries` produksi (2026-10-07).
DEFAULT_TECHS = (
    "anydesk", "burp suite", "crowdstrike", "ejbca", "esxi", "extrahop", "fortigate", "fortinet",
    "gitlab", "grafana", "graylog", "harmony sase", "jira", "juniper", "junos", "mariadb",
    "maxscale", "microsoft 365", "mikrotik", "n8n", "nagios", "nessus", "new relic", "nginx",
    "okta", "outlook", "palo alto", "perimeter81", "proofpoint", "proxmox", "splunk", "suricata",
    "thales", "wazuh",
)  # fmt: skip

_PLACEHOLDERS = frozenset(
    {"", "n a", "na", "none", "unknown", "unspecified", "various", "not applicable", "tbd", "null"}
)
_GENERIC = frozenset(
    {
        "software", "application", "applications", "product", "products", "firmware", "plugin",
        "plugins", "system", "systems", "server", "website", "platform", "library", "module",
        "component", "components", "device", "devices", "all", "other", "multiple products",
        "multiple", "web application", "mobile application", "operating system",
    }
)  # fmt: skip
_RE_ALNUM = re.compile(r"[a-z0-9]+")
_RE_VERSIONISH = re.compile(r"^v?\d+(\.\d+)+([a-z0-9.\-]*)$")
_RE_MULTI = re.compile(r";| and | & ")
_RE_VERSION_TOKEN = re.compile(
    r"^(version|ver|v\d+|\d+[a-z]?\d*|\d+h\d|r\d+|sp\d+|edition|x64|x86|arm64|32|64|bit)$"
)
_RE_CPE = re.compile(r"^cpe:2\.3:[aho*-]:([^:]+):([^:]+):")
_RE_CPE22 = re.compile(r"^cpe:/[aho]:([^:]+):([^:]+)")
_MIN_TERM_LEN = 2
_BERSIH = 0.8


# ── normalisasi + pencocok (salinan lokal `cti_core.tech_match`) ───────────────────────────────


def normalize(text: str) -> str:
    return " ".join(_RE_ALNUM.findall(text.lower()))


def compact(text: str) -> str:
    """Tanpa spasi untuk mengelompokkan ejaan: `Palo Alto Networks` = `paloaltonetworks`."""
    return "".join(_RE_ALNUM.findall(text.lower()))


def family(product_norm: str) -> str:
    """Perkiraan KASAR keluarga produk: token versi di UJUNG dibuang berulang (`windows 10 version
    1507` -> `windows`). Hanya untuk mengukur seberapa menggelembung katalog oleh varian versi;
    BUKAN aturan katalog (`microsoft 365` -> `microsoft` salah, dan itu juga pelajarannya)."""
    tokens = product_norm.split()
    while len(tokens) > 1 and _RE_VERSION_TOKEN.match(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def mentions(tech: str, text: str) -> bool:
    """Kata utuh; angka (maks 4 digit) menempel di ujung = versi mayor; huruf menempel = produk
    lain; istilah < 2 karakter tidak pernah cocok."""
    term = normalize(tech)
    if len(term) < _MIN_TERM_LEN:
        return False
    pattern = rf"(?<![a-z0-9]){re.escape(term)}[0-9]{{0,4}}(?![a-z0-9])"
    return re.search(pattern, normalize(text)) is not None


# ── ekstraksi dari satu record CVE JSON 5.x ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Product:
    vendor: str
    product: str
    package: str
    cpes: tuple[str, ...]
    source: str  # "cna" | "adp"

    def strings(self) -> list[str]:
        return [s for s in (self.vendor, self.product, self.package, *self.cpes) if s]

    def identity_names(self) -> tuple[str, str]:
        """(vendor, produk) mentah untuk identitas: CPE kalau ada (lebih bersih), jika tidak
        isian CNA."""
        for cpe in self.cpes:
            m = _RE_CPE.match(cpe) or _RE_CPE22.match(cpe)
            if m and m.group(1) not in ("*", "-") and m.group(2) not in ("*", "-"):
                return m.group(1).replace("\\", ""), m.group(2).replace("\\", "")
        return self.vendor, (self.product or self.package)


@dataclass
class CveRecord:
    cve_id: str
    state: str
    published: datetime.date | None
    cna: list[Product] = field(default_factory=list)
    adp: list[Product] = field(default_factory=list)


def _products(entries: Any, source: str) -> list[Product]:
    out: list[Product] = []
    for aff in entries if isinstance(entries, list) else []:
        if not isinstance(aff, dict):
            continue
        raw_cpes = aff.get("cpes")
        cpes = (
            tuple(c for c in raw_cpes if isinstance(c, str)) if isinstance(raw_cpes, list) else ()
        )
        out.append(
            Product(
                vendor=str(aff.get("vendor") or ""),
                product=str(aff.get("product") or ""),
                package=str(aff.get("packageName") or ""),
                cpes=cpes,
                source=source,
            )
        )
    return out


def _date(raw: Any) -> datetime.date | None:
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return datetime.date.fromisoformat(raw[:10])
    except ValueError:
        return None


def parse_record(data: Any) -> CveRecord | None:
    """`None` kalau bukan record CVE (mis. `delta.json`)."""
    if not isinstance(data, dict):
        return None
    meta = data.get("cveMetadata")
    if not isinstance(meta, dict) or not isinstance(meta.get("cveId"), str):
        return None
    containers = data.get("containers") if isinstance(data.get("containers"), dict) else {}
    cna = containers.get("cna") if isinstance(containers.get("cna"), dict) else {}
    adp_products: list[Product] = []
    adp_list = containers.get("adp")
    for adp in adp_list if isinstance(adp_list, list) else []:
        if isinstance(adp, dict):
            adp_products += _products(adp.get("affected"), "adp")
    return CveRecord(
        cve_id=meta["cveId"].upper(),
        state=str(meta.get("state") or ""),
        published=_date(meta.get("datePublished")),
        cna=_products(cna.get("affected"), "cna"),
        adp=adp_products,
    )


# ── sampah ─────────────────────────────────────────────────────────────────────────────────────


def junk_reason(product: str) -> str | None:
    """Alasan nama produk BUKAN identitas yang layak masuk katalog, atau `None`."""
    norm = normalize(product)
    if norm in _PLACEHOLDERS:
        return "placeholder"
    if norm in _GENERIC:
        return "generik"
    if _RE_VERSIONISH.match(product.strip().lower()):
        return "mirip-versi"
    if re.fullmatch(r"[0-9 ]+", norm):
        return "angka-saja"
    lowered = product.lower()
    if "/" in product or "http" in lowered or "github" in lowered:
        return "url-atau-repo"
    if len(product) > 80:
        return "terlalu-panjang"
    if _RE_MULTI.search(lowered):
        return "multi-produk"
    return None


# ── sumber data ────────────────────────────────────────────────────────────────────────────────


def _id_year(name: str) -> int | None:
    m = re.search(r"CVE-(\d{4})-\d+\.json$", name)
    return int(m.group(1)) if m else None


def _iter_zip(zf: zipfile.ZipFile, years: set[int]) -> Iterator[tuple[str, bytes]]:
    names = zf.namelist()
    inner = [n for n in names if n.lower().endswith(".zip")]
    if not any(n.lower().endswith(".json") for n in names) and len(inner) == 1:
        # rilis GitHub CVE List V5 dibungkus dua kali (`*.zip.zip`)
        yield from _iter_zip(zipfile.ZipFile(io.BytesIO(zf.read(inner[0]))), years)
        return
    for n in names:
        year = _id_year(n)
        if year is not None and year in years:
            yield n, zf.read(n)


def iter_raw(source: Path, years: set[int]) -> Iterator[tuple[str, bytes]]:
    if source.is_file():
        with zipfile.ZipFile(source) as zf:
            yield from _iter_zip(zf, years)
        return
    root = source / "cves" if (source / "cves").is_dir() else source
    for path in sorted(root.rglob("CVE-*.json")):
        year = _id_year(path.name)
        if year is not None and year in years:
            yield str(path), path.read_bytes()


@dataclass
class Corpus:
    scanned: int = 0
    parse_errors: int = 0
    not_published: int = 0
    before_since: int = 0
    no_date: int = 0
    records: list[CveRecord] = field(default_factory=list)


def load_corpus(
    raw: Iterable[tuple[str, bytes]], since: datetime.date, *, progress: bool = False
) -> Corpus:
    corpus = Corpus()
    for _name, blob in raw:
        corpus.scanned += 1
        if progress and corpus.scanned % 20000 == 0:
            print(f"  ... {corpus.scanned} berkas dibaca", file=sys.stderr)
        try:
            rec = parse_record(json.loads(blob))
        except (ValueError, UnicodeDecodeError):
            corpus.parse_errors += 1
            continue
        if rec is None:
            continue
        if rec.state != "PUBLISHED":
            corpus.not_published += 1
            continue
        if rec.published is None:
            corpus.no_date += 1
            continue
        if rec.published < since:
            corpus.before_since += 1
            continue
        corpus.records.append(rec)
    return corpus


# ── analisis ───────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Identity:
    vendor: str
    product: str

    @property
    def label(self) -> str:
        return f"{self.vendor or '?'} | {self.product or '?'}"


@dataclass
class TechResult:
    tech: str
    cves: set[str]
    identities: Counter[Identity]
    verdict: str
    top_share: float
    vendor_share: float = 0.0


@dataclass
class Report:
    since: datetime.date
    corpus: Corpus
    by_month: Counter[str]
    with_usable_cna: int
    only_junk_cna: int
    no_affected: int
    rescued_by_adp: int
    with_cpe: int
    raw_pairs: int
    normalized_ids: int
    clustered_ids: int
    families: int
    top_families: list[tuple[str, int, int]]
    vendors_normalized: int
    junk: Counter[str]
    junk_examples: dict[str, list[str]]
    catalog: dict[Identity, dict[str, Any]]
    clusters: list[tuple[str, int, list[tuple[str, int]]]]
    long_tail: dict[str, int]
    techs: list[TechResult]
    tracker: list[dict[str, Any]] | None
    tracker_note: str


def _identity(p: Product) -> Identity | None:
    vendor, product = p.identity_names()
    if junk_reason(product) is not None:
        return None
    return Identity(normalize(vendor), normalize(product))


def _verdict(hits: int, ids: Counter[Identity]) -> tuple[str, float, float]:
    """(vonis, bagian produk teratas, bagian vendor teratas). Vendor dibandingkan dalam bentuk
    kompak (`palo alto networks` = `paloaltonetworks`). Satu vendor dengan banyak produk BUKAN
    ambigu, itu kasus hierarki (Palo Alto: PAN-OS, Prisma, Cortex; satu tech, banyak produk)."""
    if hits == 0 or not ids:
        return "tidak ada", 0.0, 0.0
    total = sum(ids.values())
    product_share = ids.most_common(1)[0][1] / total
    vendors: Counter[str] = Counter()
    for ident, k in ids.items():
        vendors[compact(ident.vendor)] += k
    vendor_share = vendors.most_common(1)[0][1] / total
    if vendor_share >= _BERSIH and product_share >= _BERSIH:
        return "bersih", product_share, vendor_share
    if vendor_share >= _BERSIH:
        return "satu vendor, banyak produk", product_share, vendor_share
    return "ambigu", product_share, vendor_share


def analyze(
    corpus: Corpus,
    techs: Sequence[str],
    tracker_rows: Sequence[tuple[str, str]] | None = None,
    *,
    since: datetime.date = datetime.date(2025, 1, 1),
) -> Report:
    recs = corpus.records
    by_month: Counter[str] = Counter()
    catalog: dict[Identity, dict[str, Any]] = {}
    raw_pairs: set[tuple[str, str]] = set()
    junk: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    spellings: dict[str, Counter[str]] = defaultdict(Counter)
    usable = only_junk = no_aff = rescued = with_cpe = 0

    for rec in recs:
        published = rec.published
        assert published is not None  # dijamin `load_corpus`
        by_month[published.strftime("%Y-%m")] += 1
        if any(p.cpes for p in rec.cna):
            with_cpe += 1
        ids = {i for p in rec.cna if (i := _identity(p)) is not None}
        for p in rec.cna:
            vendor, product = p.identity_names()
            raw_pairs.add((vendor, product))
            why = junk_reason(product)
            if why:
                junk[why] += 1
                if len(examples[why]) < 5 and product not in examples[why]:
                    examples[why].append(product[:70])
        if ids:
            usable += 1
        elif rec.cna:
            only_junk += 1
        else:
            no_aff += 1
        if not ids:
            ids = {i for p in rec.adp if (i := _identity(p)) is not None}
            if ids:
                rescued += 1
        for ident in ids:
            entry = catalog.setdefault(
                ident, {"cves": 0, "first": published, "last": published, "raw": set()}
            )
            entry["cves"] += 1
            entry["first"] = min(entry["first"], published)
            entry["last"] = max(entry["last"], published)
        for p in rec.cna:
            ident = _identity(p)
            if ident is not None:
                vendor, product = p.identity_names()
                catalog[ident]["raw"].add((vendor, product))
                key = compact(ident.vendor) + "|" + compact(ident.product)
                spellings[key][f"{vendor} | {product}"] += 1

    clusters = [
        (k, sum(sp.values()), sp.most_common(6)) for k, sp in spellings.items() if len(sp) > 1
    ]
    clusters.sort(key=lambda c: (-c[1], c[0]))

    counts = [e["cves"] for e in catalog.values()]
    long_tail = {
        "1 CVE": sum(1 for c in counts if c == 1),
        "2-4 CVE": sum(1 for c in counts if 2 <= c <= 4),
        "5-19 CVE": sum(1 for c in counts if 5 <= c <= 19),
        ">=20 CVE": sum(1 for c in counts if c >= 20),
    }

    fam: dict[str, dict[str, int]] = defaultdict(lambda: {"variants": 0, "cves": 0})
    for ident, e in catalog.items():
        key = compact(ident.vendor) + "|" + family(ident.product)
        fam[key]["variants"] += 1
        fam[key]["cves"] += e["cves"]
    top_families = sorted(
        ((k, v["variants"], v["cves"]) for k, v in fam.items() if v["variants"] > 1),
        key=lambda t: (-t[1], t[0]),
    )

    tech_results = _match_techs(recs, techs)
    tracker, note = _compare_tracker(tech_results, recs, tracker_rows)

    return Report(
        since=since,
        corpus=corpus,
        by_month=by_month,
        with_usable_cna=usable,
        only_junk_cna=only_junk,
        no_affected=no_aff,
        rescued_by_adp=rescued,
        with_cpe=with_cpe,
        raw_pairs=len(raw_pairs),
        normalized_ids=len(catalog),
        clustered_ids=len({compact(i.vendor) + "|" + compact(i.product) for i in catalog}),
        families=len(fam),
        top_families=top_families,
        vendors_normalized=len({i.vendor for i in catalog}),
        junk=junk,
        junk_examples=dict(examples),
        catalog=catalog,
        clusters=clusters,
        long_tail=long_tail,
        techs=tech_results,
        tracker=tracker,
        tracker_note=note,
    )


def _match_techs(recs: Sequence[CveRecord], techs: Sequence[str]) -> list[TechResult]:
    out: list[TechResult] = []
    for tech in techs:
        cves: set[str] = set()
        ids: Counter[Identity] = Counter()
        for rec in recs:
            hit = False
            for p in rec.cna:
                if any(mentions(tech, s) for s in p.strings()):
                    hit = True
                    ident = _identity(p)
                    if ident is not None:
                        ids[ident] += 1
            if hit:
                cves.add(rec.cve_id)
        verdict, share, vshare = _verdict(len(cves), ids)
        out.append(TechResult(tech, cves, ids, verdict, share, vshare))
    return out


def _compare_tracker(
    results: Sequence[TechResult],
    recs: Sequence[CveRecord],
    rows: Sequence[tuple[str, str]] | None,
) -> tuple[list[dict[str, Any]] | None, str]:
    if rows is None:
        return None, "Tidak ada `--tracker-csv`: perbandingan dengan tracker dilewati."
    in_window = {r.cve_id for r in recs}
    by_tech: dict[str, set[str]] = defaultdict(set)
    for cve_id, tech in rows:
        by_tech[normalize(tech)].add(cve_id.strip().upper())
    out: list[dict[str, Any]] = []
    for res in results:
        tracker = by_tech.get(normalize(res.tech), set())
        inside = tracker & in_window
        out.append(
            {
                "tech": res.tech,
                "tracker": len(tracker),
                "outside": len(tracker - in_window),
                "inside": len(inside),
                "both": len(inside & res.cves),
                "only_tracker": sorted(inside - res.cves),
                "only_catalog": sorted(res.cves - inside),
            }
        )
    return out, ""


# ── laporan ────────────────────────────────────────────────────────────────────────────────────


def _pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f}%" if b else "-"


def render(report: Report, *, top: int = 40, today: datetime.date | None = None) -> str:
    c = report.corpus
    n = len(c.records)
    junk_total = sum(report.junk.values())
    o: list[str] = []
    o.append("# Spike katalog tech dari CVE List V5\n")
    o.append(f"Dibuat {today or datetime.date.today()}. Jendela: terbit >= {report.since}.\n")

    o.append("## 1. Korpus\n")
    o.append(
        f"- Berkas CVE dibaca: **{c.scanned}** (gagal parse: {c.parse_errors}; "
        f"bukan PUBLISHED: {c.not_published}; tanpa tanggal terbit: {c.no_date}; "
        f"terbit sebelum jendela: {c.before_since})."
    )
    o.append(f"- **CVE dianalisis: {n}**")
    o.append("\n| Bulan terbit | CVE |\n|---|---|")
    for month in sorted(report.by_month):
        o.append(f"| {month} | {report.by_month[month]} |")

    o.append("\n## 2. Cakupan data produk (CNA)\n")
    o.append("| | CVE | % |\n|---|---|---|")
    rows2 = [
        ("punya >= 1 produk yang layak jadi identitas", report.with_usable_cna),
        ("hanya produk sampah (placeholder/generik/...)", report.only_junk_cna),
        ("tanpa `affected` sama sekali", report.no_affected),
        ("diselamatkan data ADP (CNA tak berguna)", report.rescued_by_adp),
        ("memuat CPE di data CNA", report.with_cpe),
    ]
    for label, value in rows2:
        o.append(f"| {label} | {value} | {_pct(value, n)} |")
    o.append(
        "\nCVE tanpa produk layak (CNA maupun ADP) = yang di gate `new_cve` sekarang jatuh ke "
        "ringkasan teks; di desain baru mereka TIDAK punya identitas dan perlu jalur sendiri."
    )

    o.append("\n## 3. Ukuran dan kebersihan katalog\n")
    o.append(f"- Pasangan (vendor, produk) **mentah**: {report.raw_pairs}")
    o.append(
        "- Identitas **ternormalisasi** (huruf kecil, tanda baca jadi spasi, sampah dibuang): "
        f"**{report.normalized_ids}** ({report.vendors_normalized} vendor)"
    )
    dup = report.normalized_ids - report.clustered_ids
    o.append(
        f"- Setelah **menggabung ejaan** (tanpa spasi, `Palo Alto` = `PaloAlto`): "
        f"**{report.clustered_ids}** -> normalisasi saja menyisakan {dup} duplikat yang bisa "
        "digabung otomatis"
    )
    o.append(
        f"- Perkiraan **keluarga produk** (token versi di ujung dibuang; kasar): "
        f"**{report.families}** -- selisihnya dengan angka di atas adalah varian versi yang "
        "menggelembungkan katalog (mis. tiap versi Windows = satu produk)"
    )
    o.append(f"- Entri produk sampah: **{junk_total}**")
    o.append("\n| Jenis sampah | Entri | Contoh |\n|---|---|---|")
    for why, cnt in report.junk.most_common():
        o.append(f"| {why} | {cnt} | {'; '.join(report.junk_examples.get(why, []))} |")
    o.append("\n**Ekor panjang** (identitas menurut jumlah CVE di jendela):\n")
    o.append("| Jumlah CVE | Identitas |\n|---|---|")
    for label, cnt in report.long_tail.items():
        o.append(f"| {label} | {cnt} |")
    big = report.long_tail["5-19 CVE"] + report.long_tail[">=20 CVE"]
    o.append(
        f"\nKalau picker hanya menampilkan identitas dengan >= 5 CVE, ukuran katalog = {big}; "
        "sisanya ekor yang sebagian besar noise atau produk sekali-lewat."
    )
    o.append(
        "\n**Keluarga dengan varian terbanyak** (kandidat digabung atau disembunyikan di picker):\n"
    )
    o.append("| Vendor | Keluarga | Varian | CVE |\n|---|---|---|---|")
    for key, variants, cves in report.top_families[:15]:
        vend, _, fam_name = key.partition("|")
        o.append(f"| {vend} | {fam_name} | {variants} | {cves} |")
    if not report.top_families:
        o.append("| - | - | - | tidak ada |")

    o.append(f"\n## 4. Duplikasi ejaan (kandidat merge), {min(25, len(report.clusters))} teratas\n")
    o.append(
        "Ejaan berbeda yang setelah dikompaksi jadi identitas yang sama (sisa SESUDAH normalisasi "
        "huruf/tanda baca):\n"
    )
    o.append("| Kunci | CVE | Ejaan (jumlah) |\n|---|---|---|")
    for key, cnt, spell in report.clusters[:25]:
        o.append(f"| `{key}` | {cnt} | " + "; ".join(f"{s} ({k})" for s, k in spell) + " |")
    if not report.clusters:
        o.append("| - | - | tidak ada |")

    o.append(f"\n## 5. {top} identitas dengan CVE terbanyak\n")
    o.append(
        "| Vendor | Produk | CVE | Pertama | Terakhir | Ejaan mentah |\n|---|---|---|---|---|---|"
    )
    ranked = sorted(report.catalog.items(), key=lambda kv: (-kv[1]["cves"], kv[0].label))
    for ident, e in ranked[:top]:
        o.append(
            f"| {ident.vendor} | {ident.product} | {e['cves']} | {e['first']} | {e['last']} | "
            f"{len(e['raw'])} |"
        )

    o.append("\n## 6. 34 tech produksi terhadap katalog\n")
    o.append(
        "`hit` = CVE yang vendor/produk/paket/CPE CNA-nya menyebut tech itu (kata utuh), sama "
        "dengan gate `new_cve`. **Vonis**: `bersih` = satu vendor DAN satu produk menguasai >= 80% "
        "hit; `satu vendor, banyak produk` = vendor jelas tapi produknya tersebar (kasus hierarki: "
        "satu tech harus dipetakan ke beberapa produk); `ambigu` = vendor pun tersebar (perlu "
        "keputusan manusia saat memetakan); `tidak ada` = tak ada hit (nama tech bukan nama yang "
        "dipakai CNA, atau memang tak ada CVE di jendela).\n"
    )
    o.append(
        "| Tech | Hit | Vonis | Vendor teratas | Produk teratas | Identitas teratas (CVE) |"
        "\n|---|---|---|---|---|---|"
    )
    for res in report.techs:
        top_ids = "; ".join(f"{i.label} ({k})" for i, k in res.identities.most_common(3))
        hit = res.verdict != "tidak ada"
        vs = f"{res.vendor_share:.0%}" if hit else "-"
        ps = f"{res.top_share:.0%}" if hit else "-"
        o.append(
            f"| {res.tech} | {len(res.cves)} | {res.verdict} | {vs} | {ps} | {top_ids or '-'} |"
        )
    verdicts = Counter(r.verdict for r in report.techs)
    o.append(
        f"\nRingkas: bersih {verdicts['bersih']}, satu vendor banyak produk "
        f"{verdicts['satu vendor, banyak produk']}, ambigu {verdicts['ambigu']}, "
        f"tidak ada {verdicts['tidak ada']} dari {len(report.techs)}."
    )

    o.append("\n## 7. Recall terhadap tracker\n")
    if report.tracker is None:
        o.append(report.tracker_note)
    else:
        o.append(
            "Per tech, hanya CVE yang terbit di jendela (`di luar` = baris tracker yang terbit "
            "sebelum jendela, tidak bisa dinilai). `hanya-tracker` = ditemukan keyword search tapi "
            "TIDAK oleh pencocokan identitas (salah-cocok lama, atau nama CNA beda); "
            "`hanya-katalog` = ditemukan identitas tapi TIDAK ada di tracker (kelewat keyword "
            "search 8 hari, atau terbit sebelum tech ditambahkan).\n"
        )
        o.append(
            "| Tech | Tracker | Di luar | Di jendela | Keduanya | Hanya tracker | Hanya katalog |"
            "\n|---|---|---|---|---|---|---|"
        )
        tot_in = tot_both = 0
        for row in report.tracker:
            tot_in += row["inside"]
            tot_both += row["both"]
            if not (row["tracker"] or row["only_catalog"]):
                continue  # tech tanpa baris tracker dan tanpa hit: tidak ada yang dibandingkan
            o.append(
                f"| {row['tech']} | {row['tracker']} | {row['outside']} | {row['inside']} | "
                f"{row['both']} | {len(row['only_tracker'])} | {len(row['only_catalog'])} |"
            )
        o.append(
            f"\n**Tracker yang juga ditemukan katalog: {tot_both}/{tot_in} "
            f"({_pct(tot_both, tot_in)}).**"
        )
        o.append("\nContoh untuk ditinjau manual (maks 8 per tech):\n")
        for row in report.tracker:
            if row["only_tracker"] or row["only_catalog"]:
                only_t = ", ".join(row["only_tracker"][:8]) or "-"
                only_c = ", ".join(row["only_catalog"][:8]) or "-"
                o.append(f"- **{row['tech']}** hanya-tracker: {only_t} | hanya-katalog: {only_c}")

    o.append("\n## 8. Batas pengukuran\n")
    for line in (
        "Pencocokan tech memakai data CNA saja (ADP hanya menyelamatkan CVE tanpa produk layak). "
        "NVD/CPE yang diperkaya belakangan TIDAK ikut dihitung.",
        "`hit` mengukur kecocokan NAMA, bukan kebenaran; vonis `bersih` berarti identitasnya "
        "konsisten, bukan bahwa itu produk yang dimaksud client. Tinjau manusia tetap wajib.",
        "Gate `new_cve` juga jatuh ke ringkasan teks bila produk kosong; spike ini tidak meniru "
        "fallback itu.",
        "CVE terbit sebelum jendela tidak dihitung; tahun ID di luar `--id-years` tidak dipindai.",
        "Duplikat hanya yang lolos normalisasi sederhana; kemiripan yang butuh pengetahuan "
        "(`PAN-OS` vs `Palo Alto`) tidak terdeteksi. 'Keluarga produk' adalah perkiraan kasar.",
    ):
        o.append(f"- {line}")
    return "\n".join(o) + "\n"


def write_catalog_csv(report: Report, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["vendor", "product", "family", "cve_count", "first", "last", "spellings"])
        ranked = sorted(report.catalog.items(), key=lambda kv: (-kv[1]["cves"], kv[0].label))
        for ident, e in ranked:
            w.writerow(
                [ident.vendor, ident.product, family(ident.product), e["cves"], e["first"],
                 e["last"], len(e["raw"])]
            )  # fmt: skip


def read_tracker_csv(path: Path) -> list[tuple[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or not {"cve_id", "tech"} <= set(reader.fieldnames):
            raise SystemExit("--tracker-csv harus punya kolom header `cve_id` dan `tech`")
        return [(r["cve_id"], r["tech"]) for r in reader if r["cve_id"] and r["tech"]]


def _parse_years(spec: str) -> set[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return set(range(int(a), int(b) + 1))
    return {int(y) for y in spec.split(",")}


def main(argv: Sequence[str] | None = None) -> int:
    today = datetime.date.today()
    ap = argparse.ArgumentParser(description="Spike katalog tech dari CVE List V5 (hanya baca).")
    ap.add_argument("--source", required=True, type=Path, help="clone cvelistV5 atau zip rilis")
    ap.add_argument("--since", type=datetime.date.fromisoformat, default=datetime.date(2025, 1, 1))
    ap.add_argument("--id-years", help="mis. 2023-2026 atau 2024,2025 (default since.year-1..kini)")
    ap.add_argument(
        "--techs", type=Path, help="nama tech satu per baris (default 34 nama produksi)"
    )
    ap.add_argument("--tracker-csv", type=Path, help="CSV `cve_id,tech` dari cve_tracker")
    ap.add_argument("--out", type=Path, help="tulis laporan markdown ke berkas (default stdout)")
    ap.add_argument("--catalog-csv", type=Path, help="tulis kandidat katalog ke CSV")
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args(argv)

    years = (
        _parse_years(args.id_years)
        if args.id_years
        else set(range(args.since.year - 1, today.year + 1))
    )
    techs = (
        [t.strip() for t in args.techs.read_text(encoding="utf-8").splitlines() if t.strip()]
        if args.techs
        else list(DEFAULT_TECHS)
    )
    tracker = read_tracker_csv(args.tracker_csv) if args.tracker_csv else None

    print(f"Memindai tahun ID {sorted(years)} dari {args.source} ...", file=sys.stderr)
    corpus = load_corpus(iter_raw(args.source, years), args.since, progress=True)
    if not corpus.records:
        print("Tidak ada CVE dalam jendela: periksa --source/--since/--id-years.", file=sys.stderr)
        return 2
    report = analyze(corpus, techs, tracker, since=args.since)
    text = render(report, top=args.top, today=today)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"Laporan: {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    if args.catalog_csv:
        write_catalog_csv(report, args.catalog_csv)
        print(f"Kandidat katalog: {args.catalog_csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
