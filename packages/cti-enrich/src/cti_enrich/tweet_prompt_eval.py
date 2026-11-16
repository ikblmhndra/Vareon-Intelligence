"""Bandingkan prompt artikel lama (`classify`) dengan prompt tweet pendek (`classify_tweet`).

Dipakai sekali sebelum prompt pendek dipercaya: jalankan kedua prompt pada tweet yang sama,
lihat seberapa sering verdict `related_cyber` dan `confirmed_incident` sama. Memanggil LLM
sungguhan (berbayar), jadi tidak pernah dijalankan di test -- test memakai classifier stub.

    python -m cti_enrich.tweet_prompt_eval --limit 50 [--file tweets.jsonl]

`--file` (JSONL `{"text": ...}`) jalan tanpa DB -- dipakai untuk menyertakan tweet yang ditolak
(tidak tersimpan di `tweets`) dari dry-run dev. Tanpa `--file`, tweet terbaru dibaca dari DB.

Ukuran prompt: dilaporkan dalam KARAKTER system prompt, bukan token. Jumlah token per panggilan
hanya ada di tabel `llm_calls` (ditulis klien di belakang layar) dan tidak dikembalikan ke
`ClassifyResult`; menariknya ke sini butuh perubahan invasif. 1 token ~ 4 karakter.
"""

from __future__ import annotations

import argparse
import json
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
    """Jalankan kedua classifier pada tiap teks dan hitung kesepakatan."""
    related: list[tuple[Any, Any]] = []
    incident: list[tuple[Any, Any]] = []
    for text in texts:
        a, b = old(text), new(text)
        related.append((a.related_cyber, b.related_cyber))
        incident.append((bool(a.confirmed_incident), bool(b.confirmed_incident)))
    return {
        "n": len(texts),
        "related_cyber_agreement": _agreement(related),
        "confirmed_incident_agreement": _agreement(incident),
        "old_prompt_chars": len(_PROMPT),
        "new_prompt_chars": len(_TWEET_PROMPT),
    }


def _load_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line)["text"] for line in fh if line.strip()]


def _load_db(limit: int) -> list[str]:
    from cti_core.db.engine import sync_session
    from cti_core.db.models.tweet import Tweet
    from sqlalchemy import select

    with sync_session() as session:
        stmt = select(Tweet.text).order_by(Tweet.id.desc()).limit(limit)
        return list(session.execute(stmt).scalars())


def main() -> None:
    parser = argparse.ArgumentParser(description="Bandingkan prompt classify vs classify_tweet.")
    parser.add_argument("--limit", type=int, default=50, help="jumlah tweet terbaru dari DB")
    parser.add_argument("--file", help="JSONL {'text': ...}; bila diberikan, DB tidak dipakai")
    args = parser.parse_args()

    texts = _load_file(args.file) if args.file else _load_db(args.limit)
    report = compare(texts, classify, classify_tweet)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
