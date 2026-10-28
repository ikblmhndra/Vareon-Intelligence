"""Replay model Admiralty P6 atas snapshot dev (spec 1 sukses 2, 8.2): distribusi tidak boleh
jenuh. Bobot/ambang TIDAK boleh diubah demi lulus; kalau gagal, laporkan angkanya."""

import csv
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from cti_core.confidence import ArticleFacts, assess

FIXTURE = Path(__file__).parents[1] / "fixtures" / "confidence_replay" / "dev_2026-10.csv"


def _b(v: str) -> bool:
    return v == "t"


def _load() -> list[dict]:
    rows = []
    with FIXTURE.open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            facts = ArticleFacts(
                reliability_grade=r["reliability_grade"] or None,
                content_kind=r["content_kind"] or None,
                story_source_count=int(r["story_source_count"]),
                has_cve=_b(r["has_cve"]),
                has_ioc=_b(r["has_ioc"]),
                explicit_ttp_count=int(r["explicit_ttp_count"]),
                bonus_ttp_count=int(r["bonus_ttp_count"]),
                has_actor=_b(r["has_actor"]),
                confirmed_incident=_b(r["confirmed_incident"]),
                kev=_b(r["kev"]),
                poc=_b(r["poc"]),
            )
            a = assess(facts)
            rows.append(
                {
                    "id": int(r["id"]),
                    "story": r["story_id"] or None,
                    "week": date.fromisoformat(r["posted_on"]).isocalendar()[:2]
                    if r["posted_on"]
                    else None,
                    "priority": a.priority_score,
                    "code": a.admiralty_code,
                }
            )
    return rows


def test_dev_snapshot_distribution() -> None:
    rows = _load()
    n = len(rows)
    assert n > 1000

    max_share = max(Counter(r["priority"] for r in rows).values()) / n
    assert max_share <= 0.20, max_share

    ordered = sorted(rows, key=lambda r: -r["priority"])
    top = ordered[: n // 10]
    assert len({r["priority"] for r in top}) >= 20

    assert len({r["code"] for r in rows}) >= 8

    weeks: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["week"] is not None:  # beberapa baris dev tanpa posted_on: tak ikut cek mingguan
            weeks[r["week"]].append(r)
    for week, items in weeks.items():
        if len(items) < 20:
            continue
        best: dict[object, dict] = {}
        for r in items:
            key = r["story"] or f"id:{r['id']}"
            if key not in best or r["priority"] > best[key]["priority"]:
                best[key] = r
        top10 = sorted(best.values(), key=lambda r: -r["priority"])[:10]
        assert len(top10) >= 5, week  # satu key per story, jadi len = story berbeda
