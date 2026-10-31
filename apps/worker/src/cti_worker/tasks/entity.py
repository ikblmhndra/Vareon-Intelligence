"""Task `entity.alias_sync`: unduh tiga file MISP Galaxy, validasi, simpan ke
`reference_snapshots`, lalu jalankan merge Galaxy mode apply (P7c spec 4.3).

Satu file yang ditolak (HTTP gagal, skema rusak, menyusut >20 %) mempertahankan salinan lamanya;
dua file lain tetap diperbarui. Cluster Galaxy tanpa entitas yang cocok tidak membuat apa pun
(Ruling 19)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog
from cti_core.config import get_settings
from cti_core.db.models.entity import ReferenceSnapshot
from cti_core.entity.galaxy import (
    GALAXY_FILES,
    GalaxyResult,
    apply_plan,
    galaxy_sources,
    load_galaxy,
    plan_merges,
    snapshot_name,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_MAINTENANCE

log = structlog.get_logger()

GALAXY_URL = "https://raw.githubusercontent.com/MISP/misp-galaxy/main/clusters/{name}.json"
HTTP_TIMEOUT_S = 30.0
MAX_SHRINK = 0.20
"""Salinan baru dengan cluster lebih sedikit dari 80 % salinan sebelumnya dianggap korup."""


def galaxy_url(name: str) -> str:
    return GALAXY_URL.format(name=name)


def http_fetch(url: str) -> dict[str, Any]:
    resp = httpx.get(url, timeout=HTTP_TIMEOUT_S, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise ValueError("isi bukan objek JSON")
    return data  # type: ignore[no-any-return]


@dataclass
class SyncResult:
    stored: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)
    applied: GalaxyResult | None = None


def _previous_count(session: Session, name: str) -> int:
    """Jumlah cluster salinan tersimpan, atau snapshot bawaan paket bila belum ada."""
    return len(load_galaxy(name, galaxy_sources(session)[name]))


def sync_galaxy(session: Session, fetch: Callable[[str], dict[str, Any]]) -> SyncResult:
    """Commit urusan pemanggil."""
    result = SyncResult()
    for name in GALAXY_FILES:
        try:
            content = fetch(galaxy_url(name))
            new_count = len(load_galaxy(name, content))
            old_count = _previous_count(session, name)
            if old_count and new_count < old_count * (1 - MAX_SHRINK):
                raise ValueError(f"menyusut terlalu jauh: {old_count} -> {new_count} cluster")
        except Exception as exc:  # satu file gagal tidak boleh menjatuhkan file lain
            result.rejected[name] = f"{type(exc).__name__}: {exc}"
            log.warning("galaxy_sync_rejected", file=name, error=result.rejected[name])
            continue
        digest = hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        session.merge(ReferenceSnapshot(name=snapshot_name(name), sha256=digest, content=content))
        session.flush()
        result.stored.append(name)

    has_copy = session.scalars(
        select(ReferenceSnapshot.name).where(
            ReferenceSnapshot.name.in_([snapshot_name(n) for n in GALAXY_FILES])
        )
    ).first()
    if result.stored or has_copy:
        sources = galaxy_sources(session)
        clusters = [c for n, content in sources.items() for c in load_galaxy(n, content)]
        result.applied = apply_plan(session, plan_merges(session, clusters))
    return result


@app.task(name="entity.alias_sync", queue=QUEUE_MAINTENANCE)
def alias_sync() -> dict[str, Any]:
    if not get_settings().entity.alias_sync_enabled:
        log.info("entity_alias_sync_disabled")
        return {"skipped": "disabled"}
    from cti_core.db.engine import sync_session

    with sync_session() as session:
        res = sync_galaxy(session, http_fetch)
        session.commit()
    applied = res.applied
    out = {
        "stored": res.stored,
        "rejected": res.rejected,
        "merged": applied.merged if applied else 0,
        "aliases_added": applied.aliases_added if applied else 0,
        "merge_errors": len(applied.errors) if applied else 0,
    }
    log.info("entity_alias_synced", **out)
    return out
