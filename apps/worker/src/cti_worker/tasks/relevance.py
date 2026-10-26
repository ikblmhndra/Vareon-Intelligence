"""Task model relevansi lokal (P5): latih mingguan.

Import `cti_enrich` LAZY di dalam fungsi -- image `worker` tanpa extra `nlp` tetap harus bisa
start (lihat `tasks/enrich.py` dan `tasks/story.py`)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_ENRICH

log = structlog.get_logger()


def alert_ops(text: str, *, key: str, cooldown_s: int = 3600) -> None:
    """Satu alert Telegram per `key` per jendela cooldown (dedupe lewat Redis `SET NX EX`).
    BEST-EFFORT: tidak pernah melempar, supaya masalah alert tidak menutupi kerja aslinya
    (pola `_alert_enrichment_failure`)."""
    try:
        import redis
        from cti_alerts.telegram import send_alert
        from cti_core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis.url)
        if not client.set(key, "1", nx=True, ex=cooldown_s):
            return
        send_alert("scraper_health", text)
    except Exception as alert_error:
        log.error("relevance_alert_failed", error=str(alert_error)[:200])


@app.task(name="relevance.train", queue=QUEUE_ENRICH)
def train() -> dict[str, Any]:
    import datetime

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_enrich.relevance.embedder import get_embedder
    from cti_enrich.relevance.train import run_training

    # `sync_session` commit saat blok selesai: itu commit task ini (run_training tidak commit).
    with sync_session() as session:
        outcome = run_training(
            session, get_embedder(), get_settings().relevance, datetime.datetime.now(datetime.UTC)
        )
    log.info("relevance_trained", status=outcome.status, model_id=outcome.model_id)
    if outcome.status == "rejected":
        alert_ops(
            f"<b>Model relevansi baru DITOLAK</b>: {outcome.reason}. Model sebelumnya tetap aktif.",
            key="cti:relevance:train_rejected",
            cooldown_s=6 * 24 * 3600,
        )
    return asdict(outcome)


@app.task(name="relevance.evaluate", queue=QUEUE_ENRICH)
def evaluate() -> dict[str, Any]:
    """Tiap jam: ukur kesepakatan band model dengan LLM dan geser gate shadow <-> gate.
    Model tidak bisa dimuat atau perlu latih ulang -> picu `relevance.train`, tidak menilai gate."""
    import datetime

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.relevance import RelevanceModelRepo
    from cti_enrich.relevance import model as model_mod
    from cti_enrich.relevance.evaluate import next_state
    from cti_enrich.stages.relevance import needs_retrain

    cfg = get_settings().relevance
    now = datetime.datetime.now(datetime.UTC)
    change: tuple[str, str, int, int, float | None] | None = None
    with sync_session() as session:
        repo = RelevanceModelRepo(session)
        row = repo.get_active()
        if row is not None:
            try:
                model_mod.loads(row.artifact or b"")
            except Exception as load_error:
                alert_ops(
                    f"<b>Model relevansi aktif gagal dimuat</b>: {str(load_error)[:200]}. "
                    "Pelatihan ulang dipicu; sementara itu LLM classify dipakai.",
                    key="relevance:load",
                )
                train.delay()
                return {"action": "retrain", "reason": "load_failed"}
        if needs_retrain(session):
            train.delay()
            return {"action": "retrain", "reason": "needs_retrain"}
        repo.lock()
        row = repo.get_active()
        if row is None:
            return {"action": "none"}
        stats = repo.gate_stats(
            since=now - datetime.timedelta(days=cfg.gate_window_days),
            revert_samples=cfg.revert_samples,
        )
        current = "gate" if row.gate_state == "gate" else "shadow"
        new_state = next_state(current, stats, cfg)
        result: dict[str, Any] = {
            "action": "none",
            "state": current,
            "band_n": stats.band_n,
            "band_agree": stats.band_agree,
        }
        if new_state != current:
            # Commit DULU: alert best-effort tidak boleh membatalkan perubahan status.
            repo.set_gate_state(row.id, new_state, now)
            session.commit()
            audit_pct = (
                100 * sum(stats.audit_last) / len(stats.audit_last) if stats.audit_last else None
            )
            change = (
                current,
                new_state,
                stats.band_n,
                stats.band_agree,
                audit_pct,
            )
            result.update(action="changed", state=new_state)
    if change is not None:
        old, new, band_n, band_agree, audit_pct = change
        agree_pct = 100 * band_agree / band_n if band_n else 0.0
        audit_txt = f"{audit_pct:.1f}%" if audit_pct is not None else "belum ada sampel"
        log.info("relevance_gate_changed", old=old, new=new, band_n=band_n)
        alert_ops(
            f"<b>Gate relevansi berubah: {old} -> {new}</b>\n"
            f"Judul dalam band: {band_n}, kesepakatan dengan LLM {agree_pct:.1f}%, "
            f"kesepakatan sampel audit {audit_txt}.",
            key=f"relevance:gate:{new}",
        )
    return result
