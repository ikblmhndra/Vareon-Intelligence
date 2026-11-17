"""Bandingkan prompt artikel lama (`classify`) dengan prompt tweet pendek (`classify_tweet`).

Dipakai sekali sebelum prompt pendek dipercaya: jalankan kedua prompt pada tweet yang sama,
lihat seberapa sering verdict `related_cyber` dan `confirmed_incident` sama. Memanggil LLM
sungguhan (berbayar), jadi tidak pernah dijalankan di test -- test memakai classifier stub.

    python -m cti_enrich.tweet_prompt_eval --limit 50 [--file tweets.jsonl]
    python -m cti_enrich.tweet_prompt_eval --limit 200 --export tweets.jsonl   # tanpa LLM

Sumber teks tanpa `--file`: `tweet_verdicts` terbaru (semua vonis, TERMASUK yang ditolak), atau
`tweets` bila `tweet_verdicts` masih kosong (sebelum 0.8.19 jalan). `--export` menulis teks itu ke
JSONL `{"text": ...}` tanpa memanggil LLM; `--file` membaca JSONL itu tanpa DB (mis. diekspor di
dev, dijalankan di mesin lain, atau ditambah teks tweet yang ditolak dari dry-run).

Panggilan LLM eval memakai task `classify_eval` / `classify_tweet_eval`, BUKAN `classify` /
`classify_tweet`: eval yang gagal massal tidak boleh membuka breaker job atau mengubah status
Data health. Error per teks dihitung (`errors`) dan teksnya dilewati, tidak menghentikan eval.
`old_related_new_not` / `old_not_new_related` = arah ketidaksepakatan `related_cyber`.

Ukuran prompt: dilaporkan dalam KARAKTER system prompt, bukan token. Jumlah token per panggilan
hanya ada di tabel `llm_calls` (ditulis klien di belakang layar) dan tidak dikembalikan ke
`ClassifyResult`; menariknya ke sini butuh perubahan invasif. 1 token ~ 4 karakter.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

from cti_enrich.stages.classify import (
    _PROMPT,
    _TWEET_PROMPT,
    ClassifyResult,
    classify,
    classify_tweet,
)

Classifier = Callable[[str], ClassifyResult]


def _agreement(pairs: list[tuple[Any, Any]]) -> float:
    return round(sum(a == b for a, b in pairs) / len(pairs), 4) if pairs else 0.0


def compare(texts: Sequence[str], old: Classifier, new: Classifier) -> dict[str, Any]:
    """Jalankan kedua classifier pada tiap teks dan hitung kesepakatan. Teks yang membuat salah
    satu classifier error dilewati dan dihitung di `errors` (eval berbayar; satu respons rusak
    tidak boleh membuang hasil puluhan panggilan sebelumnya)."""
    related: list[tuple[Any, Any]] = []
    incident: list[tuple[Any, Any]] = []
    errors = 0
    for text in texts:
        try:
            a, b = old(text), new(text)
        except Exception as e:
            errors += 1
            print(f"error: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
            continue
        related.append((a.related_cyber, b.related_cyber))
        incident.append((bool(a.confirmed_incident), bool(b.confirmed_incident)))
    return {
        "n": len(related),
        "errors": errors,
        "related_cyber_agreement": _agreement(related),
        "old_related_new_not": sum(bool(a) and not b for a, b in related),
        "old_not_new_related": sum(not a and bool(b) for a, b in related),
        "confirmed_incident_agreement": _agreement(incident),
        "old_prompt_chars": len(_PROMPT),
        "new_prompt_chars": len(_TWEET_PROMPT),
    }


def eval_old(text: str) -> ClassifyResult:
    """Prompt artikel, task `classify_eval` (di luar breaker dan status Data health)."""
    return classify(text, task="classify_eval")


def eval_new(text: str) -> ClassifyResult:
    """Prompt tweet, task `classify_tweet_eval` (di luar breaker dan status Data health)."""
    return classify_tweet(text, task="classify_tweet_eval")


def export(texts: Sequence[str], path: str) -> None:
    """Tulis teks ke JSONL `{"text": ...}` (format `--file`)."""
    with open(path, "w", encoding="utf-8") as fh:
        for text in texts:
            fh.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")


def _load_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line)["text"] for line in fh if line.strip()]


def _load_db(limit: int) -> list[str]:
    from cti_core.db.engine import sync_session
    from cti_core.db.models.tweet import Tweet
    from cti_core.db.models.tweet_verdict import TweetVerdict
    from sqlalchemy import select

    with sync_session() as session:
        stmt = select(TweetVerdict.text).order_by(TweetVerdict.id.desc()).limit(limit)
        texts = list(session.execute(stmt).scalars())
        if not texts:
            stmt = select(Tweet.text).order_by(Tweet.id.desc()).limit(limit)
            texts = list(session.execute(stmt).scalars())
        return texts


def main() -> None:
    parser = argparse.ArgumentParser(description="Bandingkan prompt classify vs classify_tweet.")
    parser.add_argument("--limit", type=int, default=50, help="jumlah tweet terbaru dari DB")
    parser.add_argument("--file", help="JSONL {'text': ...}; bila diberikan, DB tidak dipakai")
    parser.add_argument("--export", help="tulis teks ke JSONL ini lalu berhenti (tanpa LLM)")
    args = parser.parse_args()

    texts = _load_file(args.file) if args.file else _load_db(args.limit)
    if args.export:
        export(texts, args.export)
        print(f"{len(texts)} teks ditulis ke {args.export}")
        return
    report = compare(texts, eval_old, eval_new)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
