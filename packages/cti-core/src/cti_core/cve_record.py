"""Parser murni record CVE JSON 5.x (MITRE `cveawg` dan CVE List V5) -- ROADMAP #19, irisan 3.

Dulu menyatu di `NewCve._mitre_detail` (scraper `new_cve`), tercampur dengan HTTP dan dengan
`summary`/`link` dari kandidat NVD/Tenable. Dipisah supaya DUA pemakai berbagi satu definisi
"membaca record": `new_cve` (perilaku tidak berubah, tes `test_new_cve_*` jadi pengaman) dan ingest
mirror (`cti_core.cve_mirror_sync`, yang `summary`-nya dari `descriptions[en]`).

Murni: tanpa jaringan, tanpa DB. Yang di sini sengaja dipertahankan persis seperti parser lama
(termasuk `cvss_score=0.0` bila tak ada metrik dan `"No solution yet"`), karena `new_cve` menulis
nilai-nilai itu ke `cve_tracker`; mirror yang butuh `None` mengonversinya sendiri. Satu pengecualian
sadar: teks bebas di `versions[].version` dipakai apa adanya (lihat `_version_constraint`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from cti_core.catalog_resolve import AffectedEntry, entries_from_cna

STATE_PUBLISHED = "PUBLISHED"

_BARE_VERSION = re.compile(r"[vV]?\d[\w.+:~-]*")
"""Satu token versi polos (`1.12.0`, `22.7R2.4`, `v2.0.1-rc.1`, `0`). Selain itu
(`>= 3.3.0, < 3.5.4`, `All other versions`) adalah teks bebas dari CNA."""


def mitre_date(raw: str | None) -> date | None:
    if not raw or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def mitre_datetime(raw: str | None) -> datetime | None:
    """`cveMetadata.datePublished` lengkap dengan jam, tz-aware (UTC). MITRE menulisnya
    `2026-08-31T13:53:00.000Z`; tanpa penanda zona dianggap UTC (format CVE JSON 5.x). Hanya
    tanggal (`2026-08-31`) atau tak terbaca -> `None`: jam yang ditebak lebih buruk daripada
    kosong."""
    if not raw or len(raw) < 16 or "T" not in raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _version_constraint(raw: object) -> str:
    """Constraint untuk `versions[].version` yang tidak punya `lessThan*`; kosong bila tak bermakna.

    Versi polos tetap `<= X` (perilaku parser lama). Teks bebas dipakai apa adanya: CNA seperti
    GitHub menulis rentangnya sendiri di field ini (`">= 3.3.0, < 3.5.4"`, `"< 3.2.5"`), dan
    meng-awalinya dengan `<=` memberi `<= >= 3.3.0, < 3.5.4` (46 dari 333 teks di dev, 2026-10-09),
    yang lalu ikut mengisi Affected Version di form Ticket. Teks kosong tetap kosong; pemanggil
    melewatinya."""
    text = str(raw).strip()
    return f"<= {text}" if _BARE_VERSION.fullmatch(text) else text


def affected_products(cna: dict[str, Any]) -> list[str]:
    """vendor/product/packageName/CPE dari `containers.cna.affected` (bahan `relevant_techs`)."""
    out: list[str] = []
    for aff in cna.get("affected", []):
        for key in ("vendor", "product", "packageName"):
            value = aff.get(key)
            if isinstance(value, str) and value:
                out.append(value)
        out.extend(c for c in aff.get("cpes", []) if isinstance(c, str))
    return out


@dataclass(frozen=True)
class MitreDetail:
    fields: dict[str, Any]
    """Isian `CveItem` (tanpa `client_id`/`tech` -- tech ditentukan per client di `fetch()`)."""
    products: list[str]
    """Nama produk terdampak buat `relevant_techs`; BUKAN bagian dari `CveItem`."""
    affected_entries: list[AffectedEntry]
    """Elemen `affected` terstruktur, bahan `catalog_resolve.resolve_all`."""


def cve_state(data: dict[str, Any]) -> str:
    """`cveMetadata.state` (`PUBLISHED`/`REJECTED`/`RESERVED`); kosong bila tak ada."""
    meta = data.get("cveMetadata")
    state = meta.get("state") if isinstance(meta, dict) else None
    return state if isinstance(state, str) else ""


def cna_summary(data: dict[str, Any]) -> str:
    """Deskripsi bahasa Inggris pertama dari `containers.cna.descriptions` ("" bila tak ada)."""
    cna = data.get("containers", {}).get("cna", {})
    for desc in cna.get("descriptions", []):
        if isinstance(desc, dict) and desc.get("lang", "").lower().startswith("en"):
            value = desc.get("value")
            if isinstance(value, str) and value.strip():
                return value
    return ""


def parse_cve_record(data: dict[str, Any], *, cve_id: str, link: str, summary: str) -> MitreDetail:
    """Record CVE JSON 5.x -> isian `CveItem`. `summary`/`link` diberikan pemanggil (NVD/Tenable
    untuk `new_cve`, `cna_summary()` dan tautan NVD untuk mirror)."""
    cna = data.get("containers", {}).get("cna", {})

    references = [r["url"] for r in cna.get("references", []) if "url" in r]

    affected: list[str] = []
    seen_products: set[str] = set()
    for aff in cna.get("affected", []):
        product = aff.get("product")
        if not product or product in seen_products:
            continue
        seen_products.add(product)
        for version in aff.get("versions", []):
            if version.get("status") != "affected":
                continue
            if "lessThan" in version:
                constraint = f"< {version['lessThan']}"
            elif "lessThanOrEqual" in version:
                constraint = f"<= {version['lessThanOrEqual']}"
            elif "version" in version:
                constraint = _version_constraint(version["version"])
                if not constraint:
                    continue
            else:
                continue
            affected.append(f"{product}: {constraint}")

    base_score = 0.0
    severity = None
    vector = ""
    for metric_group in cna.get("metrics", []):
        for key, metric in metric_group.items():
            if key in ("scenarios", "format"):
                continue
            score = metric.get("baseScore", 0)
            if base_score <= score:
                base_score = score
                vector = metric.get("vectorString", "")
                severity = metric.get("baseSeverity")

    solutions = (
        "".join(s["value"] for s in cna.get("solutions", []) if s.get("lang") == "en")
        or "No solution yet"
    )

    cve_meta = data.get("cveMetadata", {})

    fields = {
        "cve_id": cve_id,
        "link": link,
        "summary": summary,
        "published": mitre_date(cve_meta.get("datePublished")),
        "published_at": mitre_datetime(cve_meta.get("datePublished")),
        "cve_modified_date": mitre_date(cve_meta.get("dateUpdated"))
        or mitre_date(cve_meta.get("datePublished")),
        "references": references,
        "affected": affected,
        "solutions": solutions,
        "cve_score": base_score,
        "cve_severity": severity,
        "cvss_vector": vector,
    }
    return MitreDetail(
        fields=fields,
        products=affected_products(cna),
        affected_entries=entries_from_cna(cna),
    )
