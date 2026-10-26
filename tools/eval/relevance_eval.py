"""Evaluasi model relevansi P5: alat dev, bukan kode produk.

Pakai ekspor label prod (read-only) sebagai CSV dengan kolom
`kind,title,news_type,reason,failure_kind,at[,audit]` (`audit` opsional: teks JSON audit classify,
kosong bila tidak ada). Jalankan dari root repo dengan embedder asli (model sudah ada di disk):

  FASTEMBED_CACHE_PATH=DIR HF_HUB_OFFLINE=1 \\
      uv run python -m tools.eval.relevance_eval LABELS.csv [--folds 5]

Memakai fungsi produk apa adanya (`to_examples`, `fit`, `predict`, `split_holdout`,
`band_metrics`, `confusion_matrix`): holdout waktu 14 hari + CV berstrata. Judul prod tidak boleh
masuk repo, jadi alat ini hanya mencetak ke stdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
from cti_enrich.relevance.dataset import LabelRow, to_examples
from cti_enrich.relevance.embedder import Embedder, get_embedder
from cti_enrich.relevance.model import Example, Probs, fit, predict
from cti_enrich.relevance.train import band_metrics, confusion_matrix, split_holdout
from sklearn.model_selection import StratifiedKFold

THRESHOLDS = (0.85, 0.9)
GATE_AGREEMENT = 0.95
GATE_BAND_SHARE = 0.35


def _parse_at(value: str) -> datetime:
    # Format psql: "2026-09-26 04:21:31.509753+00"; fromisoformat butuh "+00:00".
    value = value.strip()
    if len(value) > 3 and value[-3] in "+-" and ":" not in value[-3:]:
        value += ":00"
    return datetime.fromisoformat(value)


def read_rows(path: Path) -> list[LabelRow]:
    rows: list[LabelRow] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            audit_text = (rec.get("audit") or "").strip()
            rows.append(
                LabelRow(
                    title=rec["title"],
                    kind=rec["kind"],  # type: ignore[arg-type]
                    # `news_type` di ekspor sudah memuat override analis.
                    news_type=rec.get("news_type") or None,
                    override_news_type=None,
                    audit=json.loads(audit_text) if audit_text else None,
                    reason=rec.get("reason") or None,
                    failure_kind=rec.get("failure_kind") or None,
                    at=_parse_at(rec["at"]),
                )
            )
    return rows


class CachedEmbedder:
    """Cache embedding per judul: CV memanggil `fit`/`predict` berulang atas judul yang sama."""

    def __init__(self, inner: Embedder) -> None:
        self._inner = inner
        self._cache: dict[str, np.ndarray] = {}
        self.name = inner.name

    def embed(self, titles: Sequence[str]) -> np.ndarray:
        missing = [t for t in dict.fromkeys(titles) if t not in self._cache]
        if missing:
            for t, v in zip(missing, self._inner.embed(missing), strict=True):
                self._cache[t] = v
        return np.stack([self._cache[t] for t in titles])


def _report(name: str, probs: list[Probs], labels: list[str]) -> dict[float, dict[str, float]]:
    print(f"\n== {name} (n={len(labels)}) ==")
    out: dict[float, dict[str, float]] = {}
    for th in THRESHOLDS:
        m = band_metrics(probs, labels, th)
        out[th] = {"band_share": float(m["band_share"]), "agreement": float(m["agreement"])}
        print(
            f"  threshold {th}: band_share={m['band_share']:.3f} "
            f"agreement={m['agreement']:.3f} band_n={m['band_n']}"
        )
    cm = confusion_matrix(probs, labels)
    print("  confusion (actual -> argmax predicted):")
    for actual, row in cm.items():
        print(f"    {actual:>13}: {row}")
    return out


def _gate(name: str, m: dict[float, dict[str, float]]) -> bool:
    ok = m[0.85]["agreement"] >= GATE_AGREEMENT and m[0.85]["band_share"] >= GATE_BAND_SHARE
    print(f"gate {name} @0.85: {'PASS' if ok else 'FAIL'}")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("labels", type=Path)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--holdout-days", type=int, default=14)
    args = ap.parse_args(argv)

    rows = read_rows(args.labels)
    examples = to_examples(rows)
    counts = {
        c: sum(1 for e in examples if e.label == c)
        for c in ("reject", "best_practice", "threat_news")
    }
    print(f"rows={len(rows)} examples={len(examples)} classes={counts}")
    embedder = CachedEmbedder(get_embedder())

    now = max(e.at for e in examples)
    hold = split_holdout(examples, now=now, holdout_days=args.holdout_days)
    print(f"holdout kind={hold.kind} train={len(hold.train)} test={len(hold.test)}")
    model = fit(hold.train, embedder)
    h_probs = predict(model, [e.title for e in hold.test], embedder)
    h = _report("holdout", h_probs, [e.label for e in hold.test])

    labels = np.array([e.label for e in examples])
    cv_probs: list[Probs] = []
    cv_labels: list[str] = []
    skf = StratifiedKFold(args.folds, shuffle=True, random_state=0)
    for tr, te in skf.split(np.zeros(len(examples)), labels):
        tr_ex: list[Example] = [examples[i] for i in tr]
        te_ex: list[Example] = [examples[i] for i in te]
        m = fit(tr_ex, embedder)
        cv_probs += predict(m, [e.title for e in te_ex], embedder)
        cv_labels += [e.label for e in te_ex]
    c = _report(f"{args.folds}-fold CV", cv_probs, cv_labels)

    print()
    ok_h = _gate("holdout", h)
    ok_c = _gate("cv", c)
    return 0 if ok_h and ok_c else 1


if __name__ == "__main__":
    sys.exit(main())
