"""Task model relevansi lokal (P5): latih mingguan, evaluasi gate tiap jam. Keduanya jalan per kind
model (`article`, `tweet`; spec tweet-llm-cost Part C), masing-masing dengan transaksi, kunci, gate
state dan alert sendiri. Alert dan key Redis kind `article` sama persis dengan sebelum ada kind.

Import `cti_enrich` LAZY di dalam fungsi -- image `worker` tanpa extra `nlp` tetap harus bisa
start (lihat `tasks/enrich.py` dan `tasks/story.py`)."""

from __future__ import annotations

import html
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

import structlog

from cti_worker.celery_app import app
from cti_worker.queues import QUEUE_ENRICH

if TYPE_CHECKING:
    import datetime

    from cti_core.config import RelevanceSettings

log = structlog.get_logger()

KINDS = ("article", "tweet")


def _kind_key(base: str, kind: str) -> str:
    """Key Redis per kind; `article` memakai key lama apa adanya (dedupe tetap nyambung)."""
    return base if kind == "article" else f"{base}:{kind}"


def _kind_label(kind: str) -> str:
    """Sisipan nama kind di teks alert: kosong untuk `article` (teks lama), " tweet" untuk tweet."""
    return "" if kind == "article" else f" {kind}"


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
def train(kind: str | None = None) -> dict[str, Any]:
    """Latih model `kind`, atau semua kind (`None`, jadwal mingguan). Model tweet hanya terlatih
    kalau `tweet_verdicts` memenuhi minimum yang sama dengan artikel; sebelum itu `skipped`."""
    import datetime

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session
    from cti_enrich.relevance.embedder import get_embedder
    from cti_enrich.relevance.train import run_training

    outcomes: dict[str, Any] = {}
    for k in KINDS if kind is None else (kind,):
        # Satu transaksi per kind; `sync_session` commit saat blok selesai: itu commit task ini
        # (run_training tidak commit). Gagal satu kind di-log dan kind lain tetap dilatih:
        # model tweet yang rusak tidak boleh menahan latih mingguan model artikel, dan sebaliknya.
        try:
            with sync_session() as session:
                outcome = run_training(
                    session,
                    get_embedder(),
                    get_settings().relevance,
                    datetime.datetime.now(datetime.UTC),
                    kind=k,
                )
        except Exception:
            log.error("relevance_train_failed", kind=k, exc_info=True)
            continue
        log.info("relevance_trained", kind=k, status=outcome.status, model_id=outcome.model_id)
        if outcome.status == "rejected":
            # Teks alert memakai parse mode HTML Telegram: nilai dinamis WAJIB di-escape. Alasan
            # seperti "agreement 0.949 < 0.95" membuat Telegram menolak pesan (dev, 2026-10-26).
            alert_ops(
                f"<b>Model relevansi{_kind_label(k)} baru DITOLAK</b>: "
                f"{html.escape(outcome.reason or '')}. Model sebelumnya tetap aktif.",
                key=_kind_key("cti:relevance:train_rejected", k),
                cooldown_s=6 * 24 * 3600,
            )
        outcomes[k] = asdict(outcome)
    return outcomes


def _trigger_train(kind: str = "article") -> bool:
    """Picu `relevance.train` paling sering sekali per 24 jam per kind (Redis `SET NX EX`). Tanpa
    dedupe, evaluate tiap jam akan melatih ulang penuh terus selama model belum ada/tidak terpakai.
    Redis error -> TIDAK memicu (lebih baik terlambat daripada banjir latih). Pemicu `article`
    tetap `train.delay()` tanpa argumen seperti sebelum ada kind (melatih semua kind)."""
    try:
        import redis
        from cti_core.config import get_settings

        client = redis.Redis.from_url(get_settings().redis.url)
        if not client.set(_kind_key("relevance:train_trigger", kind), "1", nx=True, ex=86400):
            return False
    except Exception as trigger_error:
        log.warning("relevance_train_trigger_skipped", kind=kind, error=str(trigger_error)[:200])
        return False
    if kind == "article":
        train.delay()
    else:
        train.delay(kind)
    return True


def _alert_gate_change(
    old: str,
    new: str,
    band_n: int,
    band_agree: int,
    audit_pct: float | None,
    kind: str = "article",
) -> None:
    agree_pct = 100 * band_agree / band_n if band_n else 0.0
    audit_txt = f"{audit_pct:.1f}%" if audit_pct is not None else "belum ada sampel"
    log.info("relevance_gate_changed", kind=kind, old=old, new=new, band_n=band_n)
    alert_ops(
        f"<b>Gate relevansi{_kind_label(kind)} berubah: "
        f"{html.escape(old)} ke {html.escape(new)}</b>\n"
        f"Judul dalam band: {band_n}, kesepakatan dengan LLM {agree_pct:.1f}%, "
        f"kesepakatan sampel audit {audit_txt}.",
        key=_kind_key("relevance:gate", kind) + f":{new}",
    )


@app.task(name="relevance.evaluate", queue=QUEUE_ENRICH)
def evaluate() -> dict[str, Any]:
    """Tiap jam: ukur kesepakatan band model dengan LLM dan geser gate shadow <-> gate, per kind.
    Hasil kind `article` di level atas (bentuk lama), kind lain di bawah nama kind-nya."""
    import datetime

    from cti_core.config import get_settings

    cfg = get_settings().relevance
    now = datetime.datetime.now(datetime.UTC)
    result: dict[str, Any] = {}
    for kind in KINDS:
        # Per kind dalam try: gagal evaluasi satu kind (mis. model tweet) di-log dan kind lain tetap
        # dievaluasi; tanpa ini error artikel menghentikan gate tweet, dan sebaliknya.
        try:
            out = _evaluate_kind(kind, cfg, now)
        except Exception:
            log.error("relevance_evaluate_failed", kind=kind, exc_info=True)
            continue
        if kind == "article":
            result.update(out)
        else:
            result[kind] = out
    return result


def _evaluate_kind(kind: str, cfg: RelevanceSettings, now: datetime.datetime) -> dict[str, Any]:
    """Evaluasi gate satu kind dalam transaksinya sendiri. Model tidak bisa dimuat atau perlu
    latih ulang -> picu `relevance.train` (dibatasi sekali per 24 jam per kind, tidak pernah saat
    mode `off`), tidak menilai gate.

    Beda kind `tweet`: tanpa model aktif TIDAK memicu latih. Model tweet baru ada sesudah
    `tweet_verdicts` memenuhi minimum (bisa berminggu-minggu); memicu latih tiap hari sampai saat
    itu hanya membuang tenaga. Latih mingguan yang menanganinya."""
    import datetime

    from cti_core.db.engine import sync_session
    from cti_core.db.repositories.relevance import GateStats, RelevanceModelRepo
    from cti_enrich.relevance import model as model_mod
    from cti_enrich.relevance.evaluate import next_state
    from cti_enrich.stages import relevance as stage

    # Kind `article` memakai bentuk panggilan lama (tanpa argumen kind).
    def trigger() -> bool:
        return _trigger_train() if kind == "article" else _trigger_train(kind)

    change: tuple[str, str, int, int, float | None] | None = None
    result: dict[str, Any] = {"action": "none", "train_triggered": False}
    with sync_session() as session:
        repo = RelevanceModelRepo(session)
        repo.lock(kind)
        row = repo.get_active(kind)
        if cfg.mode != "auto" and row is not None and row.gate_state == "gate":
            # Operator menurunkan mode: status di DB harus ikut, sebelum cabang lain.
            # Commit DULU, alert best-effort sesudahnya.
            repo.set_gate_state(row.id, "shadow", now)
            session.commit()
            change = ("gate", "shadow", 0, 0, None)
            result.update(action="changed", state="shadow")
        if change is None and cfg.mode != "off" and (kind == "article" or row is not None):
            if row is not None:
                try:
                    model_mod.loads(row.artifact or b"")
                except Exception as load_error:
                    alert_ops(
                        f"<b>Model relevansi{_kind_label(kind)} aktif gagal dimuat</b>: "
                        f"{html.escape(str(load_error)[:200])}. "
                        "Pelatihan ulang dipicu; sementara itu LLM classify dipakai.",
                        key=_kind_key("relevance:load", kind),
                    )
                    return {
                        "action": "retrain",
                        "reason": "load_failed",
                        "train_triggered": trigger(),
                    }
            retrain = (
                stage.needs_retrain(session)
                if kind == "article"
                else stage.needs_retrain(session, kind)
            )
            if retrain:
                return {
                    "action": "retrain",
                    "reason": "needs_retrain",
                    "train_triggered": trigger(),
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
                kind=kind,
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
        _alert_gate_change(*change, kind=kind)
    return result
