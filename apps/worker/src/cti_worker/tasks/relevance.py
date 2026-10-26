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


def _trigger_train() -> bool:
    """Picu `relevance.train` paling sering sekali per 24 jam (Redis `SET NX EX`). Tanpa dedupe,
    evaluate tiap jam akan melatih ulang penuh terus selama model belum ada/tidak terpakai.
    Redis error -> TIDAK memicu (lebih baik terlambat daripada banjir latih)."""
    try:
        import redis
        from cti_core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis.url)
        if not client.set("relevance:train_trigger", "1", nx=True, ex=86400):
            return False
    except Exception as trigger_error:
        log.warning("relevance_train_trigger_skipped", error=str(trigger_error)[:200])
        return False
    train.delay()
    return True


def _alert_gate_change(
    old: str, new: str, band_n: int, band_agree: int, audit_pct: float | None
) -> None:
    agree_pct = 100 * band_agree / band_n if band_n else 0.0
    audit_txt = f"{audit_pct:.1f}%" if audit_pct is not None else "belum ada sampel"
    log.info("relevance_gate_changed", old=old, new=new, band_n=band_n)
    alert_ops(
        f"<b>Gate relevansi berubah: {old} -> {new}</b>\n"
        f"Judul dalam band: {band_n}, kesepakatan dengan LLM {agree_pct:.1f}%, "
        f"kesepakatan sampel audit {audit_txt}.",
        key=f"relevance:gate:{new}",
    )


@app.task(name="relevance.evaluate", queue=QUEUE_ENRICH)
def evaluate() -> dict[str, Any]:
    """Tiap jam: ukur kesepakatan band model dengan LLM dan geser gate shadow <-> gate.
    Model tidak bisa dimuat atau perlu latih ulang -> picu `relevance.train` (dibatasi sekali
    per 24 jam, tidak pernah saat mode `off`), tidak menilai gate."""
    import datetime

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.relevance import GateStats, RelevanceModelRepo
    from cti_enrich.relevance import model as model_mod
    from cti_enrich.relevance.evaluate import next_state
    from cti_enrich.stages.relevance import needs_retrain

    cfg = get_settings().relevance
    now = datetime.datetime.now(datetime.UTC)
    change: tuple[str, str, int, int, float | None] | None = None
    result: dict[str, Any] = {"action": "none", "train_triggered": False}
    with sync_session() as session:
        repo = RelevanceModelRepo(session)
        repo.lock()
        row = repo.get_active()
        if cfg.mode != "auto" and row is not None and row.gate_state == "gate":
            # Operator menurunkan mode: status di DB harus ikut, sebelum cabang lain.
            # Commit DULU, alert best-effort sesudahnya.
            repo.set_gate_state(row.id, "shadow", now)
            session.commit()
            change = ("gate", "shadow", 0, 0, None)
            result.update(action="changed", state="shadow")
        if change is None and cfg.mode != "off":
            if row is not None:
                try:
                    model_mod.loads(row.artifact or b"")
                except Exception as load_error:
                    alert_ops(
                        f"<b>Model relevansi aktif gagal dimuat</b>: {str(load_error)[:200]}. "
                        "Pelatihan ulang dipicu; sementara itu LLM classify dipakai.",
                        key="relevance:load",
                    )
                    return {
                        "action": "retrain",
                        "reason": "load_failed",
                        "train_triggered": _trigger_train(),
                    }
            if needs_retrain(session):
                return {
                    "action": "retrain",
                    "reason": "needs_retrain",
                    "train_triggered": _trigger_train(),
                }
        if change is None and row is not None:
            current = "gate" if row.gate_state == "gate" else "shadow"
            stats: GateStats = repo.gate_stats(
                since=now - datetime.timedelta(days=cfg.gate_window_days),
                revert_samples=cfg.revert_samples,
                # Audit hanya dipakai untuk revert; batasi ke periode gate sekarang supaya sampel
                # basi (sebelum revert terakhir) tidak membalik gate tiap jam. Di shadow tidak
                # dipakai untuk transisi.
                audit_since=row.gate_changed_at if current == "gate" else None,
            )
            new_state = next_state(current, stats, cfg)
            result.update(state=current, band_n=stats.band_n, band_agree=stats.band_agree)
            if new_state != current:
                # Commit DULU: alert best-effort tidak boleh membatalkan perubahan status.
                repo.set_gate_state(row.id, new_state, now)
                session.commit()
                audit_pct = (
                    100 * sum(stats.audit_last) / len(stats.audit_last)
                    if stats.audit_last
                    else None
                )
                change = (current, new_state, stats.band_n, stats.band_agree, audit_pct)
                result.update(action="changed", state=new_state)
    if change is not None:
        _alert_gate_change(*change)
    return result
