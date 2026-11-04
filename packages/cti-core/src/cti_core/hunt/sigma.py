"""Parser dan pemuat zip rilis SigmaHQ (P7e, spec 4.1).

`parse_sigma_zip` murni (tanpa DB). `load_sigma_zip` mengganti seluruh tabel `sigma_rules`
dalam satu transaksi caller (tidak commit) dan menolak zip yang mencurigakan: kurang dari
`MIN_RULES` aturan, atau menyusut lebih dari `MAX_SHRINK` dibanding isi tabel sekarang. Penolakan
terjadi sebelum `delete`, jadi salinan lama tetap utuh.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from typing import Any

import yaml
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from cti_core.db.models import SigmaRule
from cti_core.db.models.entity import ReferenceSnapshot

SIGMA_SNAPSHOT = "sigma"
MIN_RULES = 1000
MAX_SHRINK = 0.2
_BATCH = 500
_ROOTS = ("rules-emerging-threats", "rules")
_STATUSES = {"stable", "test", "experimental"}
_LEVELS = {"informational", "low", "medium", "high", "critical"}
_SKIP_DIRS = {"deprecated", "unsupported"}
_TECHNIQUE = re.compile(r"^attack\.(t\d{4}(?:\.\d{3})?)$", re.IGNORECASE)


class SigmaLoadError(Exception):
    """Zip Sigma tidak valid atau ditolak guard; baris lama tidak disentuh."""


@dataclass
class ParsedRule:
    id: uuid.UUID
    title: str
    author: str
    level: str
    status: str
    ruleset: str
    logsource: dict[str, str]
    techniques: list[str]
    path: str
    yaml: str


@dataclass
class ParsedSigma:
    rules: list[ParsedRule]
    skipped: dict[str, str]
    """path -> alasan."""


@dataclass
class SigmaLoadResult:
    release: str
    rules: int
    skipped: int
    sha256: str


def techniques_from_tags(tags: list[str]) -> list[str]:
    """`attack.t1059.001` -> `T1059.001`; tag taktik/grup/software diabaikan; urut dan unik."""
    found = {m.group(1).upper() for t in tags if (m := _TECHNIQUE.match(str(t)))}
    return sorted(found)


def _rule_path(name: str) -> str | None:
    """Buang folder teratas apa pun sebelum segmen `rules/` atau `rules-emerging-threats/`."""
    parts = name.replace("\\", "/").split("/")
    for i, seg in enumerate(parts):
        if seg in _ROOTS:
            return "/".join(parts[i:])
    return None


def parse_sigma_zip(data: bytes) -> ParsedSigma:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise SigmaLoadError(f"bukan zip: {e}") from e
    rules: list[ParsedRule] = []
    skipped: dict[str, str] = {}
    with zf:
        for info in zf.infolist():
            path = _rule_path(info.filename)
            if path is None or info.is_dir() or not path.endswith((".yml", ".yaml")):
                continue
            text = zf.read(info).decode("utf-8", errors="replace")
            try:
                doc = yaml.safe_load(text)
                if not isinstance(doc, dict):
                    raise ValueError("bukan mapping")
                if _SKIP_DIRS & set(path.split("/")):
                    skipped[path] = "deprecated/unsupported folder"
                    continue
                if doc.get("status") not in _STATUSES:
                    skipped[path] = f"status tidak didukung: {str(doc.get('status'))[:40]}"
                    continue
                if doc.get("level") not in _LEVELS:
                    skipped[path] = f"level tidak didukung: {str(doc.get('level'))[:40]}"
                    continue
                rule_id = uuid.UUID(str(doc["id"]))
                logsource = doc.get("logsource") or {}
                tags = doc.get("tags") or []
                rules.append(
                    ParsedRule(
                        id=rule_id,
                        title=str(doc["title"]),
                        author=str(doc.get("author") or ""),
                        level=str(doc.get("level") or ""),
                        status=str(doc.get("status") or ""),
                        ruleset="emerging-threats" if path.startswith(_ROOTS[0]) else "core",
                        logsource={str(k): str(v) for k, v in logsource.items()},
                        techniques=techniques_from_tags(tags if isinstance(tags, list) else []),
                        path=path,
                        yaml=text,
                    )
                )
            except (yaml.YAMLError, ValueError, KeyError, AttributeError) as e:
                skipped[path] = f"{type(e).__name__}: {e}"[:200]
    return ParsedSigma(rules=rules, skipped=skipped)


def load_sigma_zip(
    session: Session, data: bytes, *, release: str, source_url: str
) -> SigmaLoadResult:
    parsed = parse_sigma_zip(data)
    # id duplikat di zip akan melanggar PK; yang pertama dipakai, sisanya masuk skipped
    unique: dict[uuid.UUID, ParsedRule] = {}
    for r in parsed.rules:
        if r.id in unique:
            parsed.skipped[r.path] = "duplicate id"
        else:
            unique[r.id] = r
    n = len(unique)
    if n < MIN_RULES:
        raise SigmaLoadError(f"hanya {n} aturan unik (minimum {MIN_RULES})")
    current = session.scalar(select(func.count()).select_from(SigmaRule)) or 0
    if current and n < current * (1 - MAX_SHRINK):
        raise SigmaLoadError(f"menyusut {current} -> {n} aturan (batas {MAX_SHRINK:.0%})")

    session.execute(delete(SigmaRule))
    rows: list[dict[str, Any]] = [
        {
            "id": r.id,
            "title": r.title,
            "author": r.author,
            "level": r.level,
            "status": r.status,
            "ruleset": r.ruleset,
            "logsource": r.logsource,
            "techniques": r.techniques,
            "path": r.path,
            "release": release,
            "yaml": r.yaml,
        }
        for r in unique.values()
    ]
    for i in range(0, len(rows), _BATCH):
        session.execute(insert(SigmaRule), rows[i : i + _BATCH])
    sha = hashlib.sha256(data).hexdigest()
    session.merge(
        ReferenceSnapshot(
            name=SIGMA_SNAPSHOT,
            fetched_at=datetime.datetime.now(datetime.UTC),
            sha256=sha,
            content={
                "release": release,
                "rules": n,
                "skipped": len(parsed.skipped),
                "source_url": source_url,
                "last_error": None,
            },
        )
    )
    session.flush()
    return SigmaLoadResult(release=release, rules=n, skipped=len(parsed.skipped), sha256=sha)


def record_sigma_error(session: Session, error: str) -> None:
    snap = session.get(ReferenceSnapshot, SIGMA_SNAPSHOT)
    if snap is not None:
        snap.content = {**snap.content, "last_error": error}
        session.flush()
