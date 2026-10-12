"""Kualitas recap MINGGUAN (#21, PR 3): perbandingan dengan pekan sebelumnya, scorecard forecast,
dan hit rate. Murni (tanpa DB, tanpa LLM): `services/recap.py` yang mengambil baris dan memanggil
model, modul ini hanya menghitung dari dict yang diberikan, jadi tiap aturan bisa dites dengan
data buatan tangan.

**Perbandingan** (`quality.comparison`): selisih `counts` pekan ini dengan baris mingguan pekan
sebelumnya, mutlak dan persen, plus yang BARU pekan ini untuk threat actor, kampanye, dan CVE
(himpunan selisih terhadap item yang tersimpan di baris pekan lalu). Dihitung dari keluaran yang
SUDAH lolos grounding, supaya "baru pekan ini" tidak memuat karangan yang sudah dibuang. Tanpa
baris pekan sebelumnya perbandingannya tidak ada (`None`), bukan semuanya nol.

**Scorecard** (`quality.scorecard`): forecast pekan lalu (`likely_events`, tiap item punya id
`f1`, `f2`, ... menurut urutannya) di-review di panggilan LLM pekan ini juga: verdict
`happened | partly | not_happened | unclear` plus satu baris bukti per id. Baris yang dibuat
sebelum ada id tidak dimigrasi: id-nya diturunkan dari urutan saat membangun masukan review. Verdict
analis disimpan DI SAMPING verdict model (`override`: `verdict`, `by`, `at`), tidak menimpanya, dan
verdict analis yang dipakai di hit rate.

**Hit rate** (`hit_rate`): dihitung SAAT DIBACA dari scorecard di 8 recap mingguan terakhir, karena
override analis mengubah pekan yang sudah lewat. `partly` dihitung setengah, `unclear` tidak masuk
penyebut. Dibagi per confidence yang dinyatakan saat forecast dibuat (low/med/high): inilah yang
menjawab apakah "high" memang lebih sering terjadi daripada "low"."""

from __future__ import annotations

import copy
import datetime
from collections.abc import Mapping, Sequence
from typing import Any, Literal, get_args

from cti_api.services import grounding

Verdict = Literal["happened", "partly", "not_happened", "unclear"]
VERDICTS: tuple[str, ...] = get_args(Verdict)

CONFIDENCE_LEVELS = ("low", "med", "high")
COUNT_KEYS = ("articles", "tweets", "iocs", "cves", "campaigns", "new_threat_actors")
"""Kunci `counts` yang dibandingkan: sama dengan `WeeklyInputs.counts`."""
HIT_RATE_WEEKS = 8

_HIT_SCORE = {"happened": 1.0, "partly": 0.5, "not_happened": 0.0}
"""Nilai tiap verdict di hit rate. `unclear` sengaja tidak ada: keluar dari penyebut."""


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def week_ref(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Penunjuk ke satu recap mingguan (tanggal dan rentangnya) untuk `comparison.previous` dan
    `scorecard.reviewed`, supaya halaman bisa menyebut pekan yang dibandingkan/di-review."""
    return {k: doc.get(k) for k in ("date", "period_start", "period_end")}


# --- perbandingan dengan pekan sebelumnya ------------------------------------------------------


def _delta_pct(current: int, previous: int) -> float | None:
    """Selisih dalam persen terhadap pekan lalu, satu desimal. `previous == 0` tidak punya persen:
    `None` (halaman cukup menampilkan selisih mutlaknya), kecuali keduanya nol (0,0%)."""
    if previous == 0:
        return 0.0 if current == 0 else None
    return round((current - previous) / previous * 100, 1)


def week_items(recap: object) -> dict[str, list[str]]:
    """Yang dibandingkan antarpekan, dari isi recap yang tersimpan (`yesterday`): actor yang aktif,
    tema kampanye, dan CVE id kanonik (satu entri bisa memuat beberapa id)."""
    body = recap if isinstance(recap, dict) else {}
    cves: list[str] = []
    for entry in _list(body.get("notable_cves")):
        if isinstance(entry, str):
            cves.extend(grounding.extract_cve_ids(entry))
    return {
        "threat_actors": [a for a in _list(body.get("active_threat_actors")) if isinstance(a, str)],
        "campaigns": [
            c["theme"]
            for c in _list(body.get("active_campaigns"))
            if isinstance(c, dict) and isinstance(c.get("theme"), str)
        ],
        "cves": cves,
    }


def _new_items(current: Sequence[str], previous: Sequence[str]) -> list[str]:
    """Item `current` yang tidak ada di `previous`, tanpa ganda, urutan `current`. Dibandingkan
    lewat kunci huruf-angka ("APT 41" = "apt41"), supaya beda kapitalisasi/spasi bukan "baru"."""
    seen = {grounding.name_key(p) for p in previous}
    fresh: list[str] = []
    for item in current:
        key = grounding.name_key(item)
        if key and key not in seen:
            seen.add(key)
            fresh.append(item)
    return fresh


def build_comparison(
    counts: Mapping[str, Any], recap: object, previous: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """`quality.comparison`: `counts` pekan ini (total sebenarnya) terhadap baris pekan sebelumnya.

    `previous` = dokumen recap pekan sebelumnya (`date`, `period_*`, `counts`, `yesterday`), atau
    `None` kalau tidak ada: perbandingannya tidak ada, bukan semuanya nol."""
    if previous is None:
        return None
    before = previous.get("counts")
    before = before if isinstance(before, dict) else {}
    deltas: dict[str, Any] = {}
    for key in COUNT_KEYS:
        now, then = _int(counts.get(key)), _int(before.get(key))
        deltas[key] = {
            "current": now,
            "previous": then,
            "delta": now - then,
            "delta_pct": _delta_pct(now, then),
        }
    current_items, previous_items = week_items(recap), week_items(previous.get("yesterday"))
    return {
        "previous": week_ref(previous),
        "counts": deltas,
        "new_this_week": {k: _new_items(v, previous_items[k]) for k, v in current_items.items()},
    }


# --- scorecard forecast --------------------------------------------------------------------------


def event_id(position: int) -> str:
    return f"f{position}"


def stamp_event_ids(events: object) -> object:
    """`likely_events` yang disimpan: tiap item objek diberi `id` `f1`, `f2`, ... menurut posisinya
    di daftar (mulai 1), ditulis KODE, bukan model, supaya stabil. Id tulisan model ditimpa; item
    yang bukan objek dibiarkan (tanpa id: tidak ikut di-review) dan tetap menghitung posisi."""
    if not isinstance(events, list):
        return events
    return [
        {**item, "id": event_id(i)} if isinstance(item, dict) else item
        for i, item in enumerate(events, start=1)
    ]


def events_for_review(forecast: object, *, limit: int) -> list[dict[str, str]]:
    """Event forecast pekan lalu yang akan di-review: `id`, `event`, `basis`, `confidence`.

    Baris yang dibuat sebelum id ada tidak punya `id`: diturunkan dari posisi di daftar, aturan yang
    sama dengan `stamp_event_ids`, jadi barisnya tidak perlu dimigrasi. Item tanpa teks `event`
    dilewati (tak ada yang bisa dinilai), dan paling banyak `limit` item: yang melebihi batas yang
    diminta prompt tidak ikut membengkakkan prompt pekan berikutnya."""
    raw = forecast.get("likely_events") if isinstance(forecast, dict) else None
    events: list[dict[str, str]] = []
    for position, item in enumerate(_list(raw), start=1):
        if not isinstance(item, dict) or not _str(item.get("event")).strip():
            continue
        stored = _str(item.get("id")).strip()
        events.append(
            {
                "id": stored or event_id(position),
                "event": _str(item.get("event")).strip(),
                "basis": _str(item.get("basis")).strip(),
                "confidence": _str(item.get("confidence")).strip(),
            }
        )
    return events[:limit]


def normalize_verdict(value: object) -> str:
    """Verdict tulisan model menjadi salah satu `VERDICTS`; apa pun yang lain ("mostly", null,
    angka) menjadi `unclear`: tidak masuk penyebut hit rate, jadi tidak mengubahnya."""
    if isinstance(value, str):
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        if key in VERDICTS:
            return key
    return "unclear"


def effective_verdict(entry: Mapping[str, Any]) -> str:
    """Verdict analis kalau ada, kalau tidak verdict model: yang dipakai hit rate."""
    override = entry.get("override")
    if isinstance(override, dict) and override.get("verdict") in VERDICTS:
        return str(override["verdict"])
    return normalize_verdict(entry.get("verdict"))


def _overrides(scorecard: Mapping[str, Any] | None) -> dict[str, tuple[str, dict[str, Any]]]:
    """`id event -> (teks event, override)` dari scorecard lama."""
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    for entry in _list(scorecard.get("events")) if scorecard else []:
        if isinstance(entry, dict) and isinstance(entry.get("override"), dict):
            found[_str(entry.get("id"))] = (_str(entry.get("event")), entry["override"])
    return found


def build_scorecard(
    reviewed: Mapping[str, Any],
    events: Sequence[Mapping[str, str]],
    review: object,
    *,
    replacing: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`quality.scorecard`: satu entri per event yang di-review, dari `forecast_review` model.

    Event yang tidak dijawab model, atau dijawab dengan verdict yang bukan salah satu `VERDICTS`,
    berstatus `unclear` (model tidak menilainya: tidak masuk penyebut, tetap bisa di-override
    analis). Id di `review` yang bukan event masukan diabaikan. `replacing` = scorecard yang
    digantikan (force regen): override analis di dalamnya dipindahkan ke entri baru yang id DAN teks
    event-nya sama, supaya regenerasi tidak menghapus pekerjaan analis diam-diam."""
    answers: dict[str, Mapping[str, Any]] = {}
    for item in _list(review):
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            answers.setdefault(item["id"].strip(), item)
    carried = _overrides(replacing)
    entries: list[dict[str, Any]] = []
    for event in events:
        answer = answers.get(event["id"], {})
        entry: dict[str, Any] = {
            "id": event["id"],
            "event": event["event"],
            "basis": event["basis"],
            "confidence": event["confidence"],
            "verdict": normalize_verdict(answer.get("verdict")),
            "evidence": _str(answer.get("evidence")).strip(),
        }
        previous = carried.get(event["id"])
        if previous is not None and previous[0] == event["event"]:
            entry["override"] = previous[1]
        entries.append(entry)
    return {"reviewed": dict(reviewed), "events": entries}


def apply_override(
    scorecard: Mapping[str, Any], event: str, verdict: str, *, by: str, at: datetime.datetime
) -> dict[str, Any]:
    """Salinan `scorecard` dengan verdict analis di entri `event`, di samping verdict model
    (`override`: `verdict`, `by`, `at`). Override kedua menggantikan yang pertama (siapa dan kapan
    yang terakhir; riwayatnya ada di audit log). `LookupError` kalau tidak ada entri `event`."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {', '.join(VERDICTS)}, got {verdict!r}")
    updated = copy.deepcopy(dict(scorecard))
    for entry in _list(updated.get("events")):
        if isinstance(entry, dict) and entry.get("id") == event:
            entry["override"] = {"verdict": verdict, "by": by, "at": at.isoformat()}
            return updated
    raise LookupError(f"No scorecard entry {event!r}")


def verdict_counts(scorecard: Mapping[str, Any] | None) -> dict[str, int] | None:
    """Jumlah entri per verdict efektif (log `recap_weekly_generated`); `None` tanpa scorecard."""
    if scorecard is None:
        return None
    counts = dict.fromkeys(VERDICTS, 0)
    for entry in _list(scorecard.get("events")):
        if isinstance(entry, dict):
            counts[effective_verdict(entry)] += 1
    return counts


# --- hit rate ------------------------------------------------------------------------------------


def _confidence(value: object) -> str:
    """Confidence yang dinyatakan, jadi salah satu `CONFIDENCE_LEVELS`: "medium" = "med", dan yang
    kosong atau tak dikenal = "low" (sama dengan lencana di halaman, yang menampilkannya low)."""
    text = value.strip().lower() if isinstance(value, str) else ""
    text = "med" if text == "medium" else text
    return text if text in CONFIDENCE_LEVELS else "low"


def _tally() -> dict[str, Any]:
    return {"events": 0, "unclear": 0, "hits": 0.0}


def _finish(raw: Mapping[str, Any]) -> dict[str, Any]:
    judged = raw["events"] - raw["unclear"]
    return {
        "events": raw["events"],
        "judged": judged,
        "unclear": raw["unclear"],
        "hits": raw["hits"],
        "rate_pct": round(raw["hits"] / judged * 100, 1) if judged else None,
    }


def hit_rate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Hit rate scorecard dari recap mingguan `rows` (dict dengan `date` dan `quality`; pemanggil
    memberi paling banyak `HIT_RATE_WEEKS` terbaru).

    `partly` = 0,5, `unclear` keluar dari penyebut (`judged`), verdict analis menang atas model.
    `rate_pct` = `None` kalau belum ada yang dinilai. `weeks` = baris yang dilihat,
    `reviewed_weeks` = yang punya scorecard (baris pertama dan pekan sepi tidak punya)."""
    overall = _tally()
    by_confidence = {level: _tally() for level in CONFIDENCE_LEVELS}
    reviewed_weeks = 0
    for row in rows:
        quality = row.get("quality")
        scorecard = quality.get("scorecard") if isinstance(quality, dict) else None
        events = _list(scorecard.get("events")) if isinstance(scorecard, dict) else []
        entries = [e for e in events if isinstance(e, dict)]
        if not entries:
            continue
        reviewed_weeks += 1
        for entry in entries:
            verdict = effective_verdict(entry)
            for tally in (overall, by_confidence[_confidence(entry.get("confidence"))]):
                tally["events"] += 1
                if verdict == "unclear":
                    tally["unclear"] += 1
                else:
                    tally["hits"] += _HIT_SCORE[verdict]
    dates = [d for d in (row.get("date") for row in rows) if isinstance(d, str)]
    return {
        "weeks": len(rows),
        "reviewed_weeks": reviewed_weeks,
        "first_week": min(dates) if dates else None,
        "last_week": max(dates) if dates else None,
        "overall": _finish(overall),
        "by_confidence": {level: _finish(t) for level, t in by_confidence.items()},
    }
