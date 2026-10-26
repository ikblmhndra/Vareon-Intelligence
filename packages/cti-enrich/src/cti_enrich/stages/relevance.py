"""Stage relevansi (P5, spec 5): prediksi model lokal per judul dan keputusan gate.

Satu-satunya bagian jalur relevansi yang menyentuh DB. Kegagalan APA PUN (model tidak ada,
versi fitur beda, embedder hilang, artifact rusak, predict error) mengembalikan `None` dan
caller jatuh ke LLM classify seperti sebelum P5: tidak ada artikel yang gagal karena P5.

`cti_enrich.relevance.model` (sklearn/scipy) di-import di dalam fungsi, bukan di level modul:
`cti_enrich.pipeline` harus tetap bisa di-import tanpa extra `nlp`, dan scipy rusak saat torch
diblokir (lihat komentar di `story/attach.py`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import structlog
from cti_core.config import RelevanceSettings
from cti_core.db.repositories.relevance import RelevanceModelRepo
from cti_core.urlkit import url_hash as compute_url_hash
from sqlalchemy.orm import Session

from cti_enrich.relevance.embedder import EmbedderUnavailable, get_embedder
from cti_enrich.relevance.gate import GateDecision, decide

if TYPE_CHECKING:
    from cti_enrich.relevance.model import Probs, TrainedModel

log = structlog.get_logger()

CACHE_TTL_SECONDS = 600.0
"""Model aktif di-cache per proses selama 10 menit: tanpa ini tiap artikel membaca satu baris
BLOB dari Postgres. Efek samping: gate state baru terlihat paling lambat 10 menit kemudian."""


@dataclass(frozen=True)
class RelevanceResult:
    model_id: int
    probs: Probs
    decision: GateDecision

    def to_audit(self) -> dict[str, Any]:
        """Bentuk untuk `raw_enrichment["relevance"]`. SQL evaluasi gate membaca
        `->>'in_band'` dan `->>'decision'`, jadi nama key dan tipe JSON-nya tidak boleh berubah."""
        return {
            "model_id": self.model_id,
            "probs": {
                "reject": self.probs.reject,
                "best_practice": self.probs.best_practice,
                "threat_news": self.probs.threat_news,
            },
            "in_band": self.decision.in_band,
            "decision": self.decision.decision,
        }


@dataclass
class _Cached:
    model_id: int
    model: TrainedModel
    gate_state: str
    feature_version: str
    loaded_at: float


_cache: _Cached | None = None
_stale_warned: set[int] = set()


def _reset_cache() -> None:
    """Hook test: kosongkan cache model dan catatan peringatan stale."""
    global _cache
    _cache = None
    _stale_warned.clear()


def _active(session: Session) -> _Cached | None:
    """Model aktif dari cache; setelah TTL tanya DB lagi, muat ulang artifact hanya kalau
    `model_id` berganti (gate_state selalu diambil dari baris terbaru)."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache.loaded_at < CACHE_TTL_SECONDS:
        return _cache
    row = RelevanceModelRepo(session).get_active()
    if row is None or row.artifact is None:
        _cache = None
        return None
    if _cache is not None and _cache.model_id == row.id:
        _cache.gate_state = row.gate_state
        _cache.feature_version = row.feature_version
        _cache.loaded_at = now
        return _cache
    from cti_enrich.relevance import model as model_mod

    _cache = _Cached(
        model_id=row.id,
        model=model_mod.loads(row.artifact),
        gate_state=row.gate_state,
        feature_version=row.feature_version,
        loaded_at=now,
    )
    return _cache


def run_relevance(
    session: Session, *, title: str, url: str, cfg: RelevanceSettings
) -> RelevanceResult | None:
    if cfg.mode == "off":
        return None
    try:
        from cti_enrich.relevance import model as model_mod

        active = _active(session)
        if active is None:
            return None
        embedder = get_embedder()
        if active.feature_version != model_mod.feature_version(embedder):
            if active.model_id not in _stale_warned:
                _stale_warned.add(active.model_id)
                log.warning("relevance_model_stale", model_id=active.model_id)
            return None
        probs = model_mod.predict(active.model, [title], embedder)[0]
        decision = decide(
            probs,
            url_hash=compute_url_hash(url),
            gate_state=cast(Literal["shadow", "gate"], active.gate_state),
            cfg=cfg,
        )
        return RelevanceResult(active.model_id, probs, decision)
    except Exception as exc:
        log.warning("relevance_failed", error=str(exc), exc_info=True)
        return None


def needs_retrain(session: Session) -> bool:
    """True kalau tidak ada model aktif atau `feature_version`-nya beda dengan runtime.

    `EmbedderUnavailable` -> False: di proses yang embedder-nya tidak ada, model hasil latih
    ulang pun tidak bisa jalan, jadi melatih di sana hanya membuang tenaga."""
    try:
        from cti_enrich.relevance import model as model_mod

        runtime = model_mod.feature_version(get_embedder())
    except EmbedderUnavailable:
        return False
    row = RelevanceModelRepo(session).get_active()
    return row is None or row.feature_version != runtime
