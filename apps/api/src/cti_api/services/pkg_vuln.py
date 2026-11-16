"""Port `ScraperNewsWeb/app/services/pkg_vuln_service.py`. Fase 7.3
(router `pkg_vuln`, Bagian 4, terbesar dari 4 router di bagian ini).

**`_enrich_vulns_composite()` lama (EPSS dari FIRST.org + KEV dari CISA,
lewat `epss_service.py`/`cisa_kev_service.py`) SENGAJA belum diport** --
dua modul itu SAMA yang udah didokumentasikan belum ke-port di
`routers/cve.py` (`POST /cisa-lookup`/`/epss-lookup`, lihat docstring
modul itu). Kolom `epss_*`/`kev*` tetap ada di skema (lihat
`cti_core.db.models.package`), cuma `adjusted_score`/`adjusted_severity`
dihitung SAAT SCAN dari `cvss_score` doang (`_compute_adjusted_score(cvss,
None, False)`) -- valid, cuma belum di-"boost" pass kedua.

**`asyncio.create_task(scan_package(...))` fire-and-forget lama DIPINDAH
KE ROUTER** (`routers/pkg_vuln.py`, pola `BackgroundTasks` + `async_session()`
yang sama kayak `routers/attack.py` -- lihat docstring modul itu). Fungsi
di sini MURNI CRUD+orkestrasi eksternal, gak nge-spawn task sendiri --
`add_package`/`update_package`/`import_lockfile` balikin INFO buat router
soal apa yang perlu di-scan, `resolve_package_deps` balikin `transitive_
targets` (bukan langsung fire scan) buat alasan yang sama. Sesi
`AsyncSession` request ditutup begitu response dikirim, task background
butuh sesi baru -- gak bisa dibikin dari dalam service yang jalan di
request context.

**`scan_all_packages()` SEKUENSIAL, bukan `asyncio.gather` batch-10 +
`sleep(2)` kayak lama** -- satu `AsyncSession` gak aman dipakai concurrent
(beda dari motor/Mongo async lama), sama constraint yang udah
didokumentasikan di `AsyncPIRRepo.list_pirs()`/`newsletter._enrich_articles()`.
Throttling batch/sleep lama tujuannya nahan concurrent request ke
osv.dev/deps.dev -- begitu eksekusinya sekuensial, gak ada concurrency
yang perlu ditahan, jadi throttling-nya ikut dibuang (bukan lupa)."""

from __future__ import annotations

import asyncio
import datetime
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

import httpx
from cti_core.db.repositories.auth import AsyncClientRepo
from cti_core.db.repositories.package import (
    AsyncMonitoredPackageRepo,
    AsyncPackageDepGraphRepo,
    AsyncPackageVulnRepo,
)
from sqlalchemy.ext.asyncio import AsyncSession

_DEPSDEV_URL = "https://api.deps.dev/v3"
_OSV_QUERY_URL = "https://api.osv.dev/v1/query"
_TIMEOUT = 30
_VALIDATION_TIMEOUT = 8  # timeout lebih pendek, khusus cek eksistensi
_HEADERS = {"User-Agent": "cti-platform/1.0", "Accept": "application/json"}

_VALID_ECOSYSTEMS = {
    "npm",
    "PyPI",
    "Go",
    "Maven",
    "crates.io",
    "NuGet",
    "RubyGems",
    "Packagist",
    "Hex",
}

_DEPSDEV_ECO = {
    "npm": "npm",
    "PyPI": "pypi",
    "Go": "go",
    "Maven": "maven",
    "crates.io": "cargo",
    "NuGet": "nuget",
    "RubyGems": "rubygems",
}
_DEPSDEV_SYSTEM_TO_ECO = {
    "NPM": "npm",
    "PYPI": "PyPI",
    "GO": "Go",
    "MAVEN": "Maven",
    "CARGO": "crates.io",
    "NUGET": "NuGet",
    "RUBYGEMS": "RubyGems",
}


# ── CVSS / severity parsing -- port byte-identik ────────────────────────────


def _parse_severity(osv_vuln: dict[str, Any]) -> tuple[str, float | None]:
    """Extract severity label dan CVSS score dari satu advisory OSV."""
    db_top = osv_vuln.get("database_specific", {})
    top_sev = db_top.get("severity", "")
    for sev in osv_vuln.get("severity", []):
        score_type = sev.get("type", "")
        vector = sev.get("score", "")
        if "CVSS" in score_type and vector:
            score = _cvss_vector_to_score(vector)
            if score is not None:
                return _score_to_label(score), score
    if top_sev:
        label = _normalize_sev_str(top_sev)
        return label, _label_to_midpoint(label)
    for affected in osv_vuln.get("affected", []):
        sev_str = affected.get("database_specific", {}).get("severity", "")
        if sev_str:
            label = _normalize_sev_str(sev_str)
            return label, _label_to_midpoint(label)
    return "UNKNOWN", None


def _normalize_sev_str(s: str) -> str:
    s = s.upper().strip()
    return (
        "MEDIUM"
        if s == "MODERATE"
        else (s if s in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "UNKNOWN")
    )


def _label_to_midpoint(label: str) -> float | None:
    return {"CRITICAL": 9.5, "HIGH": 7.5, "MEDIUM": 5.5, "LOW": 2.0}.get(label)


def _cvss_vector_to_score(vector: str) -> float | None:
    """Hitung CVSS v3 base score dari vector string."""
    if not vector or "CVSS:3" not in vector:
        return None
    try:
        import math

        parts = vector.split("/")
        metrics = {}
        for part in parts[1:]:
            if ":" in part:
                k, v = part.split(":", 1)
                metrics[k] = v

        _AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
        _AC = {"L": 0.77, "H": 0.44}
        _PR_US = {"N": 0.85, "L": 0.62, "H": 0.27}
        _PR_SC = {"N": 0.85, "L": 0.68, "H": 0.50}
        _UI = {"N": 0.85, "R": 0.62}
        _CIA = {"N": 0.00, "L": 0.22, "H": 0.56}

        S = metrics.get("S", "U")
        AV = _AV.get(metrics.get("AV", "N"), 0.85)
        AC = _AC.get(metrics.get("AC", "L"), 0.77)
        PR = (_PR_SC if S == "C" else _PR_US).get(metrics.get("PR", "N"), 0.85)
        UI = _UI.get(metrics.get("UI", "N"), 0.85)
        C = _CIA.get(metrics.get("C", "N"), 0.00)
        I = _CIA.get(metrics.get("I", "N"), 0.00)  # noqa: E741 -- nama CVSS resmi (Confidentiality/Integrity/Availability)
        A = _CIA.get(metrics.get("A", "N"), 0.00)

        isc_base = 1 - (1 - C) * (1 - I) * (1 - A)
        esc = 8.22 * AV * AC * PR * UI
        if isc_base == 0:
            return 0.0
        if S == "U":
            raw = min(10.0, 6.42 * isc_base + esc)
        else:
            isc = 7.52 * (isc_base - 0.029) - 3.25 * (isc_base - 0.02) ** 15
            raw = min(10.0, 1.08 * (isc + esc))

        return round(min(math.ceil(raw * 10) / 10, 10.0), 1)
    except Exception:
        return None


def _score_to_label(score: float) -> str:
    if score >= 9.0:
        return "CRITICAL"
    if score >= 7.0:
        return "HIGH"
    if score >= 4.0:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "UNKNOWN"


def _compute_adjusted_score(
    cvss: float | None, epss: float | None, kev: bool
) -> tuple[float | None, str | None]:
    """Composite score niru logic CVE Tracker: cvss x epss_mult x kev_mult."""
    if cvss is None:
        return None, None
    epss_mult = 1.3 if (epss or 0) >= 0.5 else (1.15 if (epss or 0) >= 0.1 else 1.0)
    kev_mult = 1.5 if kev else 1.0
    adj = min(10.0, cvss * epss_mult * kev_mult)
    adj = round(adj, 1)
    return adj, _score_to_label(adj)


# ── Extraction helpers -- port byte-identik ─────────────────────────────────


def _extract_fixed_version(osv_vuln: dict[str, Any]) -> str | None:
    latest = None
    for affected in osv_vuln.get("affected", []):
        for rng in affected.get("ranges", []):
            for event in rng.get("events", []):
                fixed = event.get("fixed")
                if fixed and (latest is None or fixed > latest):
                    latest = fixed
    return latest


def _extract_version_ranges(osv_vuln: dict[str, Any]) -> list[str]:
    ranges = []
    for affected in osv_vuln.get("affected", []):
        for rng in affected.get("ranges", []):
            events = rng.get("events", [])
            introduced = next((e.get("introduced") for e in events if "introduced" in e), None)
            fixed = next((e.get("fixed") for e in events if "fixed" in e), None)
            parts = []
            if introduced and introduced != "0":
                parts.append(f">= {introduced}")
            if fixed:
                parts.append(f"< {fixed}")
            if parts:
                ranges.append(", ".join(parts))
    return ranges[:5]


def _extract_references(osv_vuln: dict[str, Any]) -> list[str]:
    return [r["url"] for r in osv_vuln.get("references", []) if r.get("url")][:10]


def _extract_date(raw: str | None) -> datetime.date | None:
    """Port `raw[:10]` lama, diparse jadi `date` asli (kolom Postgres-nya
    `Date`, bukan string) -- osv.dev selalu ngasih RFC3339, defensif jaga2
    format aneh (system boundary eksternal)."""
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw[:10])
    except ValueError:
        return None


# ── External API fetches -- port byte-identik ───────────────────────────────


async def _fetch_osv_vulns(
    name: str, ecosystem: str, version: str | None = None
) -> list[dict[str, Any]]:
    """Fetch data vulnerability lengkap dari osv.dev. Version-pinned kalau ada."""
    payload: dict[str, Any] = {"package": {"name": name, "ecosystem": ecosystem}}
    if version:
        payload["version"] = version
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.post(_OSV_QUERY_URL, json=payload)
            if resp.status_code != 200:
                return []
            result: list[dict[str, Any]] = resp.json().get("vulns", [])
            return result
    except Exception:
        return []


async def _package_exists_on_registry(name: str, ecosystem: str) -> bool | None:
    """`True` kalau ketemu, `False` kalau 404, `None` kalau ekosistem gak
    didukung deps.dev atau cek-nya gagal (Packagist/Hex -- skip validasi)."""
    eco = _DEPSDEV_ECO.get(ecosystem)
    if not eco:
        return None
    enc = urllib.parse.quote(name, safe="")
    url = f"{_DEPSDEV_URL}/systems/{eco}/packages/{enc}"
    try:
        async with httpx.AsyncClient(timeout=_VALIDATION_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return False
            return resp.status_code == 200
    except Exception:
        return None  # network error -- jangan blokir penambahan package


async def _fetch_depsdev_latest_version(name: str, ecosystem: str) -> str | None:
    eco = _DEPSDEV_ECO.get(ecosystem)
    if not eco:
        return None
    enc = urllib.parse.quote(name, safe="")
    url = f"{_DEPSDEV_URL}/systems/{eco}/packages/{enc}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return None
            versions = resp.json().get("versions", [])
        if not versions:
            return None
        for v in versions:
            if v.get("isDefault"):
                default_version: str | None = v.get("versionKey", {}).get("version")
                return default_version
        last_version: str | None = versions[-1].get("versionKey", {}).get("version")
        return last_version
    except Exception:
        return None


async def _fetch_depsdev_deps(name: str, ecosystem: str, version: str) -> dict[str, Any]:
    """Fetch dependency graph transitif dari endpoint `:dependencies` deps.dev."""
    eco = _DEPSDEV_ECO.get(ecosystem)
    if not eco:
        return {
            "direct": [],
            "indirect": [],
            "total": 0,
            "error": f"Ecosystem {ecosystem} not supported by deps.dev",
        }
    enc_name = urllib.parse.quote(name, safe="")
    enc_ver = urllib.parse.quote(version, safe="")
    url = f"{_DEPSDEV_URL}/systems/{eco}/packages/{enc_name}/versions/{enc_ver}:dependencies"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {
                    "direct": [],
                    "indirect": [],
                    "total": 0,
                    "error": f"deps.dev HTTP {resp.status_code}",
                }
            data = resp.json()
        nodes = data.get("nodes", [])
        direct = [
            {
                "name": n["versionKey"]["name"],
                "version": n["versionKey"]["version"],
                "system": n["versionKey"]["system"],
            }
            for n in nodes
            if n.get("relation") == "DIRECT"
        ]
        indirect = [
            {
                "name": n["versionKey"]["name"],
                "version": n["versionKey"]["version"],
                "system": n["versionKey"]["system"],
            }
            for n in nodes
            if n.get("relation") == "INDIRECT"
        ]
        return {
            "direct": direct,
            "indirect": indirect[:200],
            "total": len(direct) + len(indirect),
            "error": data.get("error") or None,
        }
    except Exception as e:
        return {"direct": [], "indirect": [], "total": 0, "error": str(e)}


async def _fetch_depsdev_scorecard(
    name: str, ecosystem: str, version: str
) -> dict[str, Any] | None:
    """Fetch OSSF Scorecard lewat endpoint project deps.dev. `None` kalau gak ada."""
    eco = _DEPSDEV_ECO.get(ecosystem)
    if not eco:
        return None
    enc_name = urllib.parse.quote(name, safe="")
    enc_ver = urllib.parse.quote(version, safe="")
    ver_url = f"{_DEPSDEV_URL}/systems/{eco}/packages/{enc_name}/versions/{enc_ver}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(ver_url)
            if resp.status_code != 200:
                return None
            ver_data = resp.json()

        project_id: str | None = None
        for rp in ver_data.get("relatedProjects", []):
            if rp.get("relationType") == "SOURCE_REPO":
                project_id = rp.get("projectKey", {}).get("id")
                break
        if not project_id:
            for rp in ver_data.get("relatedProjects", []):
                pid = rp.get("projectKey", {}).get("id", "")
                if pid.startswith("github.com/"):
                    project_id = pid
                    break
        if not project_id:
            return None

        enc_proj = urllib.parse.quote(project_id, safe="")
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(f"{_DEPSDEV_URL}/projects/{enc_proj}")
            if resp.status_code != 200:
                return None
            proj_data = resp.json()

        sc = proj_data.get("scorecard", {})
        if not sc:
            return None
        checks = sc.get("checks", [])
        check_scores = [c.get("score") for c in checks if c.get("score") is not None]
        avg_score = round(sum(check_scores) / len(check_scores), 1) if check_scores else None
        risk_checks = sorted(checks, key=lambda x: x.get("score") or 10)[:6]
        return {
            "score": avg_score,
            "date": (sc.get("date") or "")[:10] or None,
            "project_id": project_id,
            "checks": [
                {
                    "name": c.get("name", ""),
                    "score": c.get("score"),
                    "reason": (c.get("reason") or "")[:200],
                }
                for c in risk_checks
            ],
        }
    except Exception:
        return None


# ── Lockfile parsing -- port byte-identik ───────────────────────────────────


def parse_requirements_txt(content: str) -> list[tuple[str, str, str | None]]:
    """Parse pip requirements.txt / requirements.lock -> [(name, 'PyPI', version|None)]."""
    results: list[tuple[str, str, str | None]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-", "git+")):
            continue
        line = re.sub(r"\[.*?\]", "", line)
        m = re.match(r"^([A-Za-z0-9_\-.]+)==([^\s;]+)", line)
        if m:
            results.append((m.group(1), "PyPI", m.group(2)))
            continue
        m = re.match(r"^([A-Za-z0-9_\-.]+)\s*$", line)
        if m:
            results.append((m.group(1), "PyPI", None))
    return results


def parse_package_json(content: str) -> list[tuple[str, str, str | None]]:
    """Parse dependencies package.json -> [(name, 'npm', version|None)]."""
    import json

    try:
        data = json.loads(content)
    except Exception:
        return []
    results: list[tuple[str, str, str | None]] = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        for name, ver_str in (data.get(section) or {}).items():
            ver = re.sub(r"^[\^~>=<*]", "", ver_str).strip() or None
            if ver and re.match(r"\d", ver):
                results.append((name, "npm", ver))
            else:
                results.append((name, "npm", None))
    return results


def parse_package_lock_json(content: str) -> list[tuple[str, str, str | None]]:
    """Parse package-lock.json (v2/v3) -> [(name, 'npm', version)]."""
    import json

    try:
        data = json.loads(content)
    except Exception:
        return []
    results: list[tuple[str, str, str | None]] = []
    packages = data.get("packages", {})
    for path, info in packages.items():
        if not path or path == "":
            continue
        name = path.split("node_modules/")[-1]
        if name:
            results.append((name, "npm", info.get("version")))
    if not results:
        for name, info in (data.get("dependencies") or {}).items():
            results.append((name, "npm", info.get("version")))
    return results


def parse_go_mod(content: str) -> list[tuple[str, str, str | None]]:
    """Parse go.mod -> [(module_path, 'Go', version)]."""
    results: list[tuple[str, str, str | None]] = []
    in_require = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("require ("):
            in_require = True
            continue
        if in_require and line == ")":
            in_require = False
            continue
        if line.startswith("require ") or in_require:
            raw = line.replace("require ", "").strip()
            parts = raw.split()
            if len(parts) >= 2:
                name, ver = parts[0], parts[1]
                ver = re.sub(r"-[0-9]{14}-[a-f0-9]+$", "", ver)
                results.append((name, "Go", ver.lstrip("v") or None))
    return results


def parse_pom_xml(content: str) -> list[tuple[str, str, str | None]]:
    """Parse Maven pom.xml -> [(groupId:artifactId, 'Maven', version)]."""
    results: list[tuple[str, str, str | None]] = []
    try:
        root = ET.fromstring(content)
        ns = {"m": "http://maven.apache.org/POM/4.0.0"}
        deps = root.findall(".//dependency", ns) or root.findall(".//dependency")
        for dep in deps:
            gid = (dep.findtext("groupId", namespaces=ns) or dep.findtext("groupId") or "").strip()
            aid = (
                dep.findtext("artifactId", namespaces=ns) or dep.findtext("artifactId") or ""
            ).strip()
            ver = (dep.findtext("version", namespaces=ns) or dep.findtext("version") or "").strip()
            if gid and aid:
                results.append((f"{gid}:{aid}", "Maven", ver or None))
    except Exception:
        pass
    return results


def parse_poetry_lock(content: str) -> list[tuple[str, str, str | None]]:
    """Parse poetry.lock -> [(name, 'PyPI', version)]."""
    results: list[tuple[str, str, str | None]] = []
    current_name: str | None = None
    current_ver: str | None = None
    for line in content.splitlines():
        line = line.strip()
        if line == "[[package]]":
            if current_name:
                results.append((current_name, "PyPI", current_ver))
            current_name = None
            current_ver = None
        m = re.match(r'^name\s*=\s*"([^"]+)"', line)
        if m:
            current_name = m.group(1)
        m = re.match(r'^version\s*=\s*"([^"]+)"', line)
        if m:
            current_ver = m.group(1)
    if current_name:
        results.append((current_name, "PyPI", current_ver))
    return results


def parse_gemfile_lock(content: str) -> list[tuple[str, str, str | None]]:
    """Parse Gemfile.lock -> [(gem, 'RubyGems', version)]. Hanya spec level-atas
    (indent 4 spasi) di bawah `specs:`; dependensi turunan (indent 6) dilewati."""
    results: list[tuple[str, str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    in_specs = False
    for raw in content.splitlines():
        if raw.strip() == "specs:":
            in_specs = True
            continue
        if in_specs and (not raw.strip() or not raw.startswith(" ")):
            in_specs = False
        if not in_specs:
            continue
        m = re.match(r"^ {4}([^\s(]+) \(([^)\s]+)\)\s*$", raw)
        if m and (m.group(1), m.group(2)) not in seen:
            seen.add((m.group(1), m.group(2)))
            results.append((m.group(1), "RubyGems", m.group(2)))
    return results


def parse_yarn_lock(content: str) -> list[tuple[str, str, str | None]]:
    """Parse yarn.lock (v1 dan berry) -> [(name, 'npm', version)]. Header entri di
    kolom 0 (`a@^1, a@^1.2:`), versi di baris `version "x"` (v1) / `version: x` (berry)."""
    results: list[tuple[str, str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    current: str | None = None
    for raw in content.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if not raw[0].isspace():
            current = None
            header = raw.rstrip()
            if not header.endswith(":"):
                continue
            spec = header[:-1].split(",")[0].strip().strip("\"'")
            at = spec.find("@", 1)
            if at <= 0 or spec[at + 1 :].startswith("workspace:"):
                continue
            current = spec[:at]
            continue
        if current is None:
            continue
        m = re.match(r"^\s+version:?\s+\"?([^\s\"]+)\"?\s*$", raw)
        if m:
            if (current, m.group(1)) not in seen:
                seen.add((current, m.group(1)))
                results.append((current, "npm", m.group(1)))
            current = None
    return results


def parse_go_sum(content: str) -> list[tuple[str, str, str | None]]:
    """Parse go.sum -> [(module, 'Go', version)]. Baris `/go.mod` dibuang dan modul
    yang sama dideduplikasi; baris rusak dilewati."""
    results: list[tuple[str, str, str | None]] = []
    seen: set[tuple[str, str]] = set()
    for line in content.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[1].startswith("v") or parts[1].endswith("/go.mod"):
            continue
        ver = re.sub(r"-[0-9]{14}-[a-f0-9]+$", "", parts[1]).lstrip("v")
        if not ver or (parts[0], ver) in seen:
            continue
        seen.add((parts[0], ver))
        results.append((parts[0], "Go", ver))
    return results


class UnknownLockfileError(ValueError):
    """Nama file tidak dikenali dan ecosystem tidak dipilih eksplisit."""


_PARSERS: dict[str, Callable[[str], list[tuple[str, str, str | None]]]] = {
    "requirements": parse_requirements_txt,
    "package-lock": parse_package_lock_json,
    "package-json": parse_package_json,
    "go-mod": parse_go_mod,
    "go-sum": parse_go_sum,
    "pom": parse_pom_xml,
    "poetry": parse_poetry_lock,
    "gemfile-lock": parse_gemfile_lock,
    "yarn-lock": parse_yarn_lock,
}

# Parser cadangan kalau nama file tidak dikenali tapi user memilih ecosystem.
FALLBACK_FORMAT_BY_ECOSYSTEM = {
    "PyPI": "requirements",
    "npm": "package-lock",
    "Go": "go-mod",
    "Maven": "pom",
    "RubyGems": "gemfile-lock",
}


def detect_lockfile_format(filename: str) -> str | None:
    """Nama file -> kode format, atau None kalau tidak dikenali."""
    fname = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if fname in (
        "requirements.txt",
        "requirements.lock",
        "requirements-dev.txt",
        "requirements-prod.txt",
    ) or fname.endswith(".requirements.txt"):
        return "requirements"
    return {
        "package-lock.json": "package-lock",
        "package.json": "package-json",
        "go.mod": "go-mod",
        "go.sum": "go-sum",
        "pom.xml": "pom",
        "poetry.lock": "poetry",
        "gemfile.lock": "gemfile-lock",
        "yarn.lock": "yarn-lock",
    }.get(fname)


def parse_lockfile(
    filename: str, content: str, ecosystem: str = "auto"
) -> tuple[str, list[tuple[str, str, str | None]]]:
    """Balikin (format, paket). Nama file yang dikenali selalu menang; nama asing
    + `auto` -> `UnknownLockfileError`; nama asing + ecosystem eksplisit -> parser cadangan."""
    fmt = detect_lockfile_format(filename)
    if fmt is None:
        fmt = FALLBACK_FORMAT_BY_ECOSYSTEM.get(ecosystem)
        if fmt is None:
            raise UnknownLockfileError(filename)
    return fmt, _PARSERS[fmt](content)


def detect_and_parse_lockfile(filename: str, content: str) -> list[tuple[str, str, str | None]]:
    """Auto-detect tipe lockfile dari nama file lalu parse."""
    return parse_lockfile(filename, content)[1]


# ── Package management ───────────────────────────────────────────────────────


async def add_package(
    session: AsyncSession,
    name: str,
    ecosystem: str,
    version: str | None = None,
    client_id: str = "default",
    source: str = "manual",
) -> dict[str, Any]:
    if ecosystem not in _VALID_ECOSYSTEMS:
        return {
            "success": False,
            "reason": f"invalid ecosystem — must be one of {sorted(_VALID_ECOSYSTEMS)}",
        }
    repo = AsyncMonitoredPackageRepo(session)
    existing = await repo.get_by_name_ci(name, ecosystem, client_id)
    if existing is not None:
        if version and existing.version != version:
            await repo.update_fields(existing, version=version)
        return {"success": False, "reason": "duplicate"}
    exists = await _package_exists_on_registry(name, ecosystem)
    if exists is False:
        return {
            "success": False,
            "reason": f'"{name}" not found on {ecosystem} registry — check spelling or ecosystem',
        }
    pkg = await repo.create(
        name=name, ecosystem=ecosystem, version=version, client_id=client_id, source=source
    )
    return {"success": True, "id": pkg.id, "name": name, "ecosystem": ecosystem, "version": version}


async def update_package(
    session: AsyncSession,
    pkg_id: int,
    version: str | None = None,
    ecosystem: str | None = None,
    client_id: str = "default",
) -> dict[str, Any]:
    pkg_repo = AsyncMonitoredPackageRepo(session)
    pkg = await pkg_repo.get_by_id(pkg_id, client_id)
    if pkg is None:
        return {"success": False, "reason": "not found"}
    old_name, old_ecosystem = pkg.name, pkg.ecosystem

    updates: dict[str, Any] = {}
    rescan = False
    if ecosystem is not None and ecosystem != pkg.ecosystem:
        if ecosystem not in _VALID_ECOSYSTEMS:
            return {
                "success": False,
                "reason": f"invalid ecosystem — must be one of {sorted(_VALID_ECOSYSTEMS)}",
            }
        updates["ecosystem"] = ecosystem
        rescan = True
    if version is not None and version != pkg.version:
        updates["version"] = version or None
        rescan = True
    if not updates:
        return {"success": True, "changed": False}

    new_eco = updates.get("ecosystem", pkg.ecosystem)
    new_ver = updates.get("version", pkg.version)
    await pkg_repo.update_fields(pkg, **updates)
    if rescan:
        await AsyncPackageVulnRepo(session).delete_for_package(old_name, old_ecosystem, client_id)

    return {
        "success": True,
        "changed": True,
        "rescan": rescan,
        "id": pkg.id,
        "name": old_name,
        "ecosystem": new_eco,
        "version": new_ver,
    }


async def delete_package(
    session: AsyncSession, pkg_id: int, client_id: str = "default"
) -> dict[str, Any]:
    pkg_repo = AsyncMonitoredPackageRepo(session)
    pkg = await pkg_repo.get_by_id(pkg_id, client_id)
    if pkg is None:
        return {"success": False, "reason": "not found"}
    name, ecosystem = pkg.name, pkg.ecosystem
    await AsyncPackageVulnRepo(session).delete_for_package(name, ecosystem, client_id)
    await pkg_repo.delete(pkg)
    return {"success": True, "deleted": name}


# ── Scanning ─────────────────────────────────────────────────────────────────


async def scan_package(
    session: AsyncSession,
    name: str,
    ecosystem: str,
    version: str | None = None,
    client_id: str = "default",
) -> dict[str, Any]:
    """Scan satu package ke osv.dev (version-pinned kalau ada) + deps.dev.
    Balikin ringkasan. Dipanggil dari `MonitoredPackage` yang ada MAUPUN
    dependensi transitif yang gak dimonitor (lihat docstring
    `cti_core.db.models.package`)."""
    pkg_repo = AsyncMonitoredPackageRepo(session)
    vuln_repo = AsyncPackageVulnRepo(session)

    if version is None:
        pkg = await pkg_repo.get_by_name_ci(name, ecosystem, client_id)
        if pkg is not None:
            version = pkg.version

    latest_ver, vulns = await asyncio.gather(
        _fetch_depsdev_latest_version(name, ecosystem),
        _fetch_osv_vulns(name, ecosystem, version),
    )

    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    now = datetime.datetime.now(datetime.UTC)

    for vuln in vulns:
        advisory_id = vuln.get("id", "")
        if not advisory_id:
            continue
        severity, cvss_score = _parse_severity(vuln)
        sev_counts[severity if severity in sev_counts else "UNKNOWN"] += 1
        adj_score, adj_sev = _compute_adjusted_score(cvss_score, None, False)
        await vuln_repo.upsert(
            package_name=name,
            ecosystem=ecosystem,
            advisory_id=advisory_id,
            client_id=client_id,
            pinned_version=version,
            aliases=vuln.get("aliases", []),
            summary=vuln.get("summary", ""),
            details=(vuln.get("details") or "")[:2000],
            severity=severity,
            cvss_score=cvss_score,
            adjusted_score=adj_score,
            adjusted_severity=adj_sev,
            published=_extract_date(vuln.get("published")),
            modified=_extract_date(vuln.get("modified")),
            fixed_version=_extract_fixed_version(vuln),
            affected_version_ranges=_extract_version_ranges(vuln),
            references=_extract_references(vuln),
            source="osv.dev",
            last_updated=now,
        )

    highest = next(
        (s for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW") if sev_counts.get(s, 0) > 0), "NONE"
    )
    total_vulns = sum(sev_counts.values())
    await pkg_repo.apply_scan_summary(
        name,
        ecosystem,
        client_id,
        last_scan=now,
        vuln_count=total_vulns,
        critical_count=sev_counts["CRITICAL"],
        high_count=sev_counts["HIGH"],
        medium_count=sev_counts["MEDIUM"],
        low_count=sev_counts["LOW"],
        highest_severity=highest,
        latest_version=latest_ver,
    )

    return {
        "package": name,
        "ecosystem": ecosystem,
        "version": version,
        "vulns_found": total_vulns,
        "critical": sev_counts["CRITICAL"],
        "high": sev_counts["HIGH"],
    }


async def scan_all_packages(session: AsyncSession, client_id: str = "default") -> dict[str, Any]:
    """SEKUENSIAL -- lihat catatan constraint `AsyncSession` di docstring modul."""
    pkg_repo = AsyncMonitoredPackageRepo(session)
    packages, _total = await pkg_repo.list_filtered(client_id, page=1, page_size=1000)
    if not packages:
        return {"scanned": 0, "total_vulns": 0}

    total_vulns = 0
    total_scanned = 0
    for pkg in packages:
        try:
            r = await scan_package(session, pkg.name, pkg.ecosystem, pkg.version, client_id)
            total_vulns += r["vulns_found"]
            total_scanned += 1
        except Exception:
            continue

    return {"scanned": total_scanned, "total_vulns": total_vulns}


async def scan_all_clients(session: AsyncSession) -> dict[str, Any]:
    """Orkestrasi lintas client -- gak diekspos router manapun (sama kayak
    lama, gak dipanggil `routers/pkg_vuln.py`), disediain buat scheduler
    (Fase 7.8) motong pakai ini nanti."""
    clients = await AsyncClientRepo(session).list_all()
    client_ids = [c.client_id for c in clients] or ["default"]
    total_scanned = total_vulns = 0
    for cid in client_ids:
        try:
            r = await scan_all_packages(session, cid)
            total_scanned += r["scanned"]
            total_vulns += r["total_vulns"]
        except Exception:
            continue
    return {"clients": len(client_ids), "scanned": total_scanned, "total_vulns": total_vulns}


# ── Dependency resolution ────────────────────────────────────────────────────


async def resolve_package_deps(
    session: AsyncSession,
    pkg_id: int,
    client_id: str = "default",
    scan_transitive: bool = False,
) -> dict[str, Any]:
    """Resolve dep graph transitif + scorecard, simpen ke `package_dep_graphs`.
    Kalau `scan_transitive`, balikin daftar target (`transitive_targets`)
    BUKAN langsung fire scan -- pemanggil (task background di router) yang
    nge-spawn task baru per target, masing-masing butuh sesi sendiri."""
    pkg_repo = AsyncMonitoredPackageRepo(session)
    pkg = await pkg_repo.get_by_id(pkg_id, client_id)
    if pkg is None:
        return {"success": False, "reason": "not found"}

    name = pkg.name
    ecosystem = pkg.ecosystem
    version = pkg.version or pkg.latest_version

    if not version:
        version = await _fetch_depsdev_latest_version(name, ecosystem)
    if not version:
        return {"success": False, "reason": "no version available for dependency resolution"}

    deps_data, scorecard = await asyncio.gather(
        _fetch_depsdev_deps(name, ecosystem, version),
        _fetch_depsdev_scorecard(name, ecosystem, version),
    )

    now = datetime.datetime.now(datetime.UTC)
    dep_repo = AsyncPackageDepGraphRepo(session)
    await dep_repo.upsert(
        pkg.id,
        package_name=name,
        ecosystem=ecosystem,
        version=version,
        resolved_at=now,
        direct_count=len(deps_data["direct"]),
        indirect_count=len(deps_data["indirect"]),
        total_count=deps_data["total"],
        direct_deps=deps_data["direct"],
        indirect_deps=deps_data["indirect"],
        scorecard_score=scorecard.get("score") if scorecard else None,
        scorecard_date=scorecard.get("date") if scorecard else None,
        scorecard_project=scorecard.get("project_id") if scorecard else None,
        scorecard_checks=scorecard.get("checks", []) if scorecard else [],
        error=deps_data.get("error"),
    )

    pkg_updates: dict[str, Any] = {
        "dep_direct_count": len(deps_data["direct"]),
        "dep_indirect_count": len(deps_data["indirect"]),
        "dep_total_count": deps_data["total"],
        "dep_resolved_at": now,
    }
    if scorecard:
        pkg_updates["scorecard_score"] = scorecard.get("score")
        pkg_updates["scorecard_date"] = scorecard.get("date")
    await pkg_repo.update_fields(pkg, **pkg_updates)

    transitive_targets: list[dict[str, str | None]] = []
    if scan_transitive:
        for dep in deps_data["direct"] + deps_data["indirect"][:50]:
            dep_eco = _DEPSDEV_SYSTEM_TO_ECO.get(dep.get("system", "").upper(), ecosystem)
            transitive_targets.append(
                {"name": dep["name"], "ecosystem": dep_eco, "version": dep.get("version")}
            )

    return {
        "success": True,
        "direct": len(deps_data["direct"]),
        "indirect": len(deps_data["indirect"]),
        "total": deps_data["total"],
        "scorecard": scorecard.get("score") if scorecard else None,
        "transitive_targets": transitive_targets,
    }


# ── Lockfile import ──────────────────────────────────────────────────────────


async def import_lockfile(
    session: AsyncSession,
    filename: str,
    content: str,
    client_id: str = "default",
    *,
    ecosystem: str = "auto",
    project: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Parse lockfile, bulk-add package baru. Balikin ringkasan import --
    `packages` dipakai router buat nge-jadwalin scan background per
    package yang BARU ditambahkan. `dry_run` cuma menghitung (new /
    already_monitored / version_changes), tanpa menulis apa pun.
    `UnknownLockfileError` dilempar ke caller (router -> 422)."""
    detected_format, parsed_pkgs = parse_lockfile(filename, content, ecosystem)
    # Kolom `source_path` String(500): nama yang kepanjangan dipotong, impor tidak gagal.
    source_path = (f"{project}/{filename}" if project else filename)[:500]
    result_eco = parsed_pkgs[0][1] if parsed_pkgs else ""
    if not parsed_pkgs:
        return {
            "parsed": 0,
            "added": 0,
            "skipped": 0,
            "errors": ["No packages detected — check file format"],
            "packages": [],
            "dry_run": dry_run,
            "detected_format": detected_format,
            "ecosystem": result_eco,
            "new": 0,
            "already_monitored": 0,
            "version_changes": 0,
            "unsupported": 0,
        }

    added = 0
    skipped = 0
    new = 0
    already = 0
    version_changes = 0
    unsupported = 0
    errors: list[str] = []
    pkg_list: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    repo = AsyncMonitoredPackageRepo(session)
    for name, eco, version in parsed_pkgs:
        if not name or eco not in _VALID_ECOSYSTEMS:
            unsupported += 1
            continue
        key = (name.lower(), eco)
        existing = await repo.get_by_name_ci(name, eco, client_id)
        if existing is not None or key in seen:
            skipped += 1
            if existing is None:
                already += 1  # duplikat dalam file yang sama
            else:
                if version and existing.version != version:
                    version_changes += 1  # sudah dimonitor tapi versinya berbeda
                    if not dry_run:
                        await repo.update_fields(existing, version=version)
                else:
                    already += 1
                if not dry_run and existing.source_path is None:
                    await repo.update_fields(existing, source_path=source_path)
            continue
        seen.add(key)
        new += 1
        pkg_list.append({"name": name, "ecosystem": eco, "version": version})
        if dry_run:
            continue
        try:
            await repo.create(
                name=name,
                ecosystem=eco,
                version=version,
                client_id=client_id,
                source="lockfile",
                source_path=source_path,
            )
            added += 1
        except Exception as e:
            errors.append(f"{name}: {e}")
            pkg_list.pop()

    return {
        "parsed": len(parsed_pkgs),
        "added": added,
        "skipped": skipped,
        "errors": errors[:20],
        "packages": pkg_list[:50],
        "dry_run": dry_run,
        "detected_format": detected_format,
        "ecosystem": result_eco,
        "new": new,
        "already_monitored": already,
        "version_changes": version_changes,
        "unsupported": unsupported,
    }
