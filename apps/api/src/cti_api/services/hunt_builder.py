"""Pembangun hunting pack yang murni (P7e): tanpa DB, tanpa I/O, tanpa FastAPI.

Menerima nilai polos dari collector (Task 6) dan menghasilkan SPL berbasis CIM, pilihan rule
Sigma, kelompok IOC, dan zip. Semua keluaran diurutkan supaya deterministik; waktu masuk lewat
``now``. Atribusi DRL 1.1 wajib: setiap rule membawa ``author`` dan link ke SigmaHQ.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Tier = Literal["primary", "inferred", "llm"]
MatchKind = Literal["exact", "sub", "parent"]

CHUNK = 200
_TIER_RANK: dict[str, int] = {"primary": 0, "inferred": 1, "llm": 2}
_LEVEL_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}
_STATUS_RANK = {"stable": 0, "test": 1, "experimental": 2}
_MATCH_RANK: dict[str, int] = {"exact": 0, "sub": 1, "parent": 2}
_SIGMA_BLOB = "https://github.com/SigmaHQ/sigma/blob"


@dataclass(frozen=True)
class AnchorIn:
    type: Literal["story", "entity"]
    id: int
    title: str
    entity_type: str | None


@dataclass(frozen=True)
class TechniqueIn:
    attack_id: str
    name: str
    tier: Tier


@dataclass(frozen=True)
class IndicatorIn:
    type: str
    value: str
    valid_until: datetime | None
    tlp: str


@dataclass(frozen=True)
class SigmaIn:
    id: str
    title: str
    level: str
    status: str
    author: str
    ruleset: str
    path: str
    release: str
    techniques: tuple[str, ...]
    logsource: dict[str, str]


@dataclass(frozen=True)
class CimDataset:
    key: str
    types: frozenset[str]
    datamodel: str
    fields: tuple[str, ...]


_HASHES = frozenset({"md5", "sha1", "sha256"})

CIM_MAP: tuple[CimDataset, ...] = (
    CimDataset(
        "network_traffic",
        frozenset({"ip"}),
        "Network_Traffic.All_Traffic",
        ("All_Traffic.src", "All_Traffic.dest"),
    ),
    CimDataset("dns", frozenset({"domain"}), "Network_Resolution.DNS", ("DNS.query",)),
    CimDataset("web_domain", frozenset({"domain"}), "Web.Web", ("Web.url_domain",)),
    CimDataset("web_url", frozenset({"url", "url_with_path"}), "Web.Web", ("Web.url",)),
    CimDataset("endpoint_processes", _HASHES, "Endpoint.Processes", ("Processes.process_hash",)),
    CimDataset("endpoint_filesystem", _HASHES, "Endpoint.Filesystem", ("Filesystem.file_hash",)),
    CimDataset("email", frozenset({"email"}), "Email.All_Email", ("All_Email.src_user",)),
)


@dataclass(frozen=True)
class SplSearch:
    dataset: str
    chunk: int
    value_count: int
    query: str


@dataclass(frozen=True)
class SigmaMatch:
    id: str
    title: str
    level: str
    status: str
    author: str
    ruleset: str
    link: str
    techniques: tuple[str, ...]
    logsource: dict[str, str]
    match: MatchKind
    via_technique: str


@dataclass(frozen=True)
class TechniqueOut:
    attack_id: str
    name: str
    tier: Tier
    sigma_count: int


@dataclass(frozen=True)
class HuntPack:
    anchor: AnchorIn
    generated_at: datetime
    sigma_release: str | None
    techniques: list[TechniqueOut]
    spl: list[SplSearch]
    sigma: list[SigmaMatch]
    iocs: dict[str, list[IndicatorIn]]
    counts: dict[str, int]
    truncated: bool
    include: list[str]


def merge_tiers(items: Iterable[TechniqueIn]) -> list[TechniqueIn]:
    """Satu entri per ATT&CK id dengan tier terkuat (primary > inferred > llm), urut id."""
    best: dict[str, TechniqueIn] = {}
    for t in items:
        cur = best.get(t.attack_id)
        if cur is None or _TIER_RANK[t.tier] < _TIER_RANK[cur.tier]:
            best[t.attack_id] = t
    return [best[k] for k in sorted(best)]


def spl_quote(value: str) -> str | None:
    """Kutip nilai untuk SPL; None bila memuat `*` (wildcard) atau karakter kontrol."""
    if "*" in value or any(ord(c) < 0x20 for c in value):
        return None
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def group_iocs(indicators: list[IndicatorIn]) -> dict[str, list[IndicatorIn]]:
    """Kelompok per dataset CIM (indikator muncul di tiap dataset yang cocok); sisanya `other`."""
    out: dict[str, list[IndicatorIn]] = {}
    known: set[str] = set()
    for ds in CIM_MAP:
        known |= ds.types
        rows = [i for i in indicators if i.type in ds.types]
        if rows:
            out[ds.key] = rows
    other = [i for i in indicators if i.type not in known]
    if other:
        out["other"] = other
    return {k: sorted(v, key=lambda i: (i.type, i.value)) for k, v in out.items()}


def build_spl(indicators: list[IndicatorIn]) -> tuple[list[SplSearch], int]:
    """Satu search per dataset dan chunk <= 200 nilai; kembalikan juga jumlah nilai terlewat."""
    searches: list[SplSearch] = []
    skipped: set[str] = set()
    for ds in CIM_MAP:
        quoted: list[str] = []
        for v in sorted({i.value for i in indicators if i.type in ds.types}):
            q = spl_quote(v)
            if q is None:
                skipped.add(v)
            else:
                quoted.append(q)
        for n, start in enumerate(range(0, len(quoted), CHUNK), 1):
            part = quoted[start : start + CHUNK]
            values = ", ".join(part)
            where = " OR ".join(f"{f} IN ({values})" for f in ds.fields)
            query = (
                "| tstats summariesonly=false count min(_time) as first_seen "
                f"max(_time) as last_seen\n  from datamodel={ds.datamodel}\n"
                f"  where {where}\n  by {' '.join(ds.fields)}\n"
                "| convert ctime(first_seen) ctime(last_seen)"
            )
            searches.append(SplSearch(ds.key, n, len(part), query))
    return searches, len(skipped)


def _match_kind(pack_id: str, rule_id: str) -> MatchKind | None:
    if pack_id == rule_id:
        return "exact"
    if rule_id.startswith(pack_id + "."):
        return "sub"
    if pack_id.startswith(rule_id + "."):
        return "parent"
    return None


def select_sigma(
    techniques: list[TechniqueIn], rules: list[SigmaIn], include: set[str]
) -> list[SigmaMatch]:
    tids = sorted({t.attack_id for t in techniques if t.tier == "primary" or t.tier in include})
    found: list[SigmaMatch] = []
    for r in rules:
        best: tuple[MatchKind, str] | None = None
        for rt in sorted(r.techniques):
            for pt in tids:
                kind = _match_kind(pt, rt)
                if kind and (best is None or _MATCH_RANK[kind] < _MATCH_RANK[best[0]]):
                    best = (kind, pt)
        if best:
            found.append(
                SigmaMatch(
                    r.id, r.title, r.level, r.status, r.author, r.ruleset,
                    f"{_SIGMA_BLOB}/{r.release}/{r.path}", r.techniques, r.logsource,
                    best[0], best[1],
                )
            )  # fmt: skip
    found.sort(
        key=lambda m: (
            m.ruleset != "core",
            _LEVEL_RANK.get(m.level, 9),
            _STATUS_RANK.get(m.status, 9),
            m.title,
            m.id,
        )
    )
    return found


def build_pack(
    anchor: AnchorIn,
    techniques: list[TechniqueIn],
    indicators: list[IndicatorIn],
    sigma_rules: list[SigmaIn],
    *,
    include: set[str],
    sigma_release: str | None,
    truncated: bool,
    now: datetime,
) -> HuntPack:
    merged = merge_tiers(techniques)
    sigma = select_sigma(merged, sigma_rules, include)
    spl, skipped = build_spl(indicators)
    tech_out = [
        TechniqueOut(
            t.attack_id,
            t.name,
            t.tier,
            sum(1 for m in sigma if _covers(t, m)),
        )
        for t in merged
    ]
    return HuntPack(
        anchor=anchor,
        generated_at=now,
        sigma_release=sigma_release,
        techniques=tech_out,
        spl=spl,
        sigma=sigma,
        iocs=group_iocs(indicators),
        counts={"indicators": len(indicators), "skipped_values": skipped},
        truncated=truncated,
        include=sorted(include),
    )


def _covers(t: TechniqueIn, m: SigmaMatch) -> bool:
    return any(_match_kind(t.attack_id, rt) for rt in m.techniques)


_README = """# Hunting pack: {title}

- Anchor: {atype} #{aid}
- Generated: {when}
- Sigma release: {release}

## How to run the SPL

Paste each file in `spl/` into a Splunk search and set the time picker to the period you want
to hunt. The searches use CIM data models (`tstats`), so the data models must be accelerated or
at least populated.

CIM assumption: field names follow the standard CIM; adjust them if your data model mappings
differ.

## Attribution

Sigma rules in `sigma/` were written by their respective authors (see the `author` field in
each rule) and are distributed under the Detection Rule License 1.1
(https://github.com/SigmaHQ/Detection-Rule-License). Source repository:
https://github.com/SigmaHQ/sigma. The licence text is in `LICENSE.Detection.Rules.md`.
"""


def _csv(rows: list[IndicatorIn]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["type", "value", "valid_until", "tlp"])
    for i in rows:
        w.writerow([i.type, i.value, i.valid_until.isoformat() if i.valid_until else "", i.tlp])
    return buf.getvalue()


def pack_zip(pack: HuntPack, sigma_yaml: dict[str, str], license_text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        readme = _README.format(
            title=pack.anchor.title,
            atype=pack.anchor.type,
            aid=pack.anchor.id,
            when=pack.generated_at.isoformat(),
            release=pack.sigma_release or "n/a",
        )
        z.writestr("README.md", readme)
        z.writestr("LICENSE.Detection.Rules.md", license_text)
        for s in pack.spl:
            z.writestr(f"spl/{s.dataset}-{s.chunk}.spl", s.query + "\n")
        for rule_id in sorted(sigma_yaml):
            z.writestr(f"sigma/{rule_id}.yml", sigma_yaml[rule_id])
        for key, rows in pack.iocs.items():
            z.writestr(f"iocs/{key}.csv", _csv(rows))
    return buf.getvalue()
