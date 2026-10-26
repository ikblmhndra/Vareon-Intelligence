"""Latih model relevansi dari label di DB, validasi di holdout, lalu simpan (spec 6).

`run_training` TIDAK commit: caller (task Celery / CLI lewat `sync_session`) yang memegang
transaksi, sama seperti method tulis `RelevanceModelRepo`. Kunci advisory diambil paling awal
dan baru lepas saat caller commit/rollback, jadi dua latih bersamaan berjalan bergantian.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Literal

from cti_core.config import RelevanceSettings
from cti_core.db.repositories.relevance import RelevanceModelRepo
from sqlalchemy.orm import Session

from cti_enrich.relevance.dataset import load_examples
from cti_enrich.relevance.embedder import Embedder
from cti_enrich.relevance.model import (
    CLASSES,
    Example,
    Probs,
    dumps,
    feature_version,
    fit,
    predict,
)

RETENTION_DAYS = 90
"""Baris non-aktif (retired/rejected) lebih tua dari ini dibuang; model aktif tidak pernah."""


@dataclass(frozen=True)
class Holdout:
    train: list[Example]
    test: list[Example]
    kind: Literal["time", "stratified"]


@dataclass(frozen=True)
class TrainOutcome:
    status: Literal["active", "rejected", "skipped"]
    model_id: int | None
    metrics: dict[str, Any]
    reason: str | None


def split_holdout(
    examples: list[Example], *, now: dt.datetime, holdout_days: int, min_time_holdout: int = 150
) -> Holdout:
    """Holdout waktu (contoh `holdout_days` terakhir) bila cukup besar; kalau tidak, 20%
    berstrata. Holdout waktu meniru pemakaian nyata: model menilai judul yang lebih baru."""
    cutoff = now - dt.timedelta(days=holdout_days)
    test = [e for e in examples if e.at >= cutoff]
    train = [e for e in examples if e.at < cutoff]
    if len(test) >= min_time_holdout and train:
        return Holdout(train, test, "time")
    from sklearn.model_selection import train_test_split

    train, test = train_test_split(
        examples, test_size=0.2, stratify=[e.label for e in examples], random_state=0
    )
    return Holdout(list(train), list(test), "stratified")


def band_metrics(probs: list[Probs], labels: list[str], threshold: float) -> dict[str, float | int]:
    """Metrik pada judul DALAM band saja (p(threat_news) >= threshold), karena hanya itu yang
    boleh di-gate. `agreement` = porsi yang labelnya memang threat_news; band kosong -> 0.0."""
    in_band = [label for p, label in zip(probs, labels, strict=True) if p.threat_news >= threshold]
    n = len(labels)
    band_n = len(in_band)
    agreement = sum(1 for label in in_band if label == "threat_news") / band_n if band_n else 0.0
    return {
        "band_share": band_n / n if n else 0.0,
        "band_n": band_n,
        "agreement": agreement,
        "n": n,
    }


def _skipped(reason: str, counts: dict[str, int]) -> TrainOutcome:
    return TrainOutcome("skipped", None, {"class_counts": counts}, reason)


def run_training(
    session: Session,
    embedder: Embedder,
    cfg: RelevanceSettings,
    now: dt.datetime,
    *,
    dry_run: bool = False,
) -> TrainOutcome:
    repo = RelevanceModelRepo(session)
    repo.lock()
    examples = load_examples(session)
    tally = Counter(e.label for e in examples)
    counts = {c: tally.get(c, 0) for c in CLASSES}

    # Minimum dicek pada SELURUH contoh sebelum dibelah: holdout kecil di kelas langka berisik.
    if len(examples) < cfg.train_min_examples:
        return _skipped(
            f"contoh {len(examples)} < train_min_examples {cfg.train_min_examples}", counts
        )
    short = [c for c in CLASSES if counts[c] < cfg.train_min_per_class]
    if short:
        return _skipped(
            f"kelas kurang dari train_min_per_class {cfg.train_min_per_class}: {short}", counts
        )

    split = split_holdout(examples, now=now, holdout_days=cfg.holdout_days)
    candidate = fit(split.train, embedder)
    probs = predict(candidate, [e.title for e in split.test], embedder)
    metrics: dict[str, Any] = dict(
        band_metrics(probs, [e.label for e in split.test], cfg.accept_threshold)
    )
    holdout_tally = Counter(e.label for e in split.test)
    metrics["holdout_kind"] = split.kind
    metrics["holdout_counts"] = {c: holdout_tally.get(c, 0) for c in CLASSES}

    version = feature_version(embedder)
    problems: list[str] = []
    if metrics["agreement"] < cfg.gate_min_agreement:
        problems.append(f"agreement {metrics['agreement']:.3f} < {cfg.gate_min_agreement}")
    if metrics["band_share"] < cfg.min_band_share:
        problems.append(f"band_share {metrics['band_share']:.3f} < {cfg.min_band_share}")

    if problems:
        reason = "; ".join(problems)
        model_id = None
        if not dry_run:
            model_id = repo.add_rejected(
                feature_version=version,
                n_examples=len(examples),
                class_counts=counts,
                metrics=metrics,
                reason=reason,
            )
            repo.purge(now - dt.timedelta(days=RETENTION_DAYS))
        return TrainOutcome("rejected", model_id, metrics, reason)

    model_id = None
    if not dry_run:
        # Lolos: refit di SEMUA contoh (holdout ikut belajar) lalu jadikan aktif.
        final = fit(examples, embedder)
        model_id = repo.activate(
            artifact=dumps(final),
            feature_version=version,
            n_examples=len(examples),
            class_counts=counts,
            metrics=metrics,
            now=now,
        )
        repo.purge(now - dt.timedelta(days=RETENTION_DAYS))
    return TrainOutcome("active", model_id, metrics, None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Latih model relevansi judul.")
    parser.add_argument("--dry-run", action="store_true", help="hitung semuanya, tanpa menulis")
    args = parser.parse_args()

    from cti_core.config import get_settings
    from cti_core.db.engine import sync_session

    from cti_enrich.relevance.embedder import get_embedder

    # `sync_session` commit saat blok selesai: itu commit milik CLI.
    with sync_session() as session:
        outcome = run_training(
            session,
            get_embedder(),
            get_settings().relevance,
            dt.datetime.now(dt.UTC),
            dry_run=args.dry_run,
        )
    print(json.dumps(asdict(outcome), indent=2, default=str))


if __name__ == "__main__":
    main()
