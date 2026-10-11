"""Unit test `cti_api.services.recap_quality` (#21 PR 3): perbandingan dengan pekan sebelumnya,
scorecard forecast, dan hit rate -- logika murni, tanpa DB dan tanpa LLM. Alur lengkapnya (baris
pekan lalu dibaca dari Postgres, LLM palsu menjawab review) ada di
`tests/integration/test_recap_service.py`."""

from __future__ import annotations

import copy
import datetime
from typing import Any

import pytest
from cti_api.services import recap_quality as q

NOW = datetime.datetime(2026, 11, 2, 9, 30, tzinfo=datetime.UTC)


# --- perbandingan --------------------------------------------------------------------------------


def _counts(**over: int) -> dict[str, int]:
    base = {
        "articles": 100,
        "tweets": 50,
        "iocs": 200,
        "cves": 20,
        "campaigns": 4,
        "new_threat_actors": 2,
    }
    return {**base, **over}


def _doc(
    counts: dict[str, int] | None = None, recap: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Dokumen recap pekan sebelumnya, bentuk `_to_dict`."""
    return {
        "date": "2026-09-28",
        "period_start": "2026-09-28",
        "period_end": "2026-10-04",
        "counts": counts if counts is not None else _counts(),
        "yesterday": recap if recap is not None else {},
    }


def test_the_first_week_has_no_comparison_at_all() -> None:
    """Tanpa baris pekan sebelumnya: tidak ada perbandingan (bukan semuanya nol, yang akan terbaca
    "naik dari nol")."""
    assert q.build_comparison(_counts(), {}, None) is None


def test_counts_get_absolute_and_percentage_deltas_in_both_directions() -> None:
    previous = _doc(_counts(articles=100, tweets=200, iocs=3, cves=20))

    out = q.build_comparison(_counts(articles=150, tweets=150, iocs=4, cves=20), {}, previous)

    assert out is not None
    assert out["counts"]["articles"] == {
        "current": 150,
        "previous": 100,
        "delta": 50,
        "delta_pct": 50.0,
    }
    assert out["counts"]["tweets"]["delta"] == -50
    assert out["counts"]["tweets"]["delta_pct"] == -25.0
    assert out["counts"]["iocs"]["delta_pct"] == 33.3  # satu desimal
    assert out["counts"]["cves"] == {"current": 20, "previous": 20, "delta": 0, "delta_pct": 0.0}


def test_every_count_key_is_compared_even_when_the_previous_row_lacks_some() -> None:
    out = q.build_comparison(_counts(), {}, _doc({"articles": 10}))

    assert out is not None
    assert list(out["counts"]) == list(q.COUNT_KEYS)
    assert out["counts"]["tweets"]["previous"] == 0


@pytest.mark.parametrize(
    ("current", "previous", "delta", "pct"),
    [
        (5, 0, 5, None),  # dari nol ke lima: tidak ada persen, bukan pembagian nol
        (0, 0, 0, 0.0),  # tidak berubah
        (0, 8, -8, -100.0),  # hilang sama sekali
    ],
)
def test_a_zero_previous_value_has_no_percentage_instead_of_dividing_by_zero(
    current: int, previous: int, delta: int, pct: float | None
) -> None:
    out = q.build_comparison(_counts(cves=current), {}, _doc(_counts(cves=previous)))

    assert out is not None
    assert out["counts"]["cves"]["delta"] == delta
    assert out["counts"]["cves"]["delta_pct"] == pct


def test_the_comparison_names_the_week_it_was_made_against() -> None:
    out = q.build_comparison(_counts(), {}, _doc())

    assert out is not None
    assert out["previous"] == {
        "date": "2026-09-28",
        "period_start": "2026-09-28",
        "period_end": "2026-10-04",
    }


def test_new_this_week_is_the_set_difference_against_last_weeks_stored_items() -> None:
    last = {
        "active_threat_actors": ["Apt41", "Lazarus"],
        "active_campaigns": [{"theme": "Old wave"}],
        "notable_cves": ["CVE-2026-0001"],
    }
    this = {
        "active_threat_actors": ["Apt41", "Sandworm"],
        "active_campaigns": [{"theme": "Old wave"}, {"theme": "New wave"}],
        "notable_cves": ["CVE-2026-0001", "CVE-2026-0002"],
    }

    out = q.build_comparison(_counts(), this, _doc(recap=last))

    assert out is not None
    assert out["new_this_week"] == {
        "threat_actors": ["Sandworm"],
        "campaigns": ["New wave"],
        "cves": ["CVE-2026-0002"],
    }


def test_a_cve_that_appears_twice_in_one_week_is_listed_as_new_once() -> None:
    this = {"notable_cves": ["CVE-2026-0002", "cve 2026 0002", "CVE-2026-0002 (critical)"]}

    out = q.build_comparison(_counts(), this, _doc(recap={"notable_cves": []}))

    assert out is not None
    assert out["new_this_week"]["cves"] == ["CVE-2026-0002"]


def test_a_cve_that_was_in_both_weeks_is_not_new_whatever_its_spelling() -> None:
    last = {"notable_cves": ["CVE-2026-0001"]}
    this = {"notable_cves": ["cve-2026-0001", "CVE 2026 0001"]}

    out = q.build_comparison(_counts(), this, _doc(recap=last))

    assert out is not None
    assert out["new_this_week"]["cves"] == []


def test_actor_and_campaign_names_differing_only_in_case_or_spacing_are_not_new() -> None:
    last = {"active_threat_actors": ["APT 41"], "active_campaigns": [{"theme": "Apt41 Wave"}]}
    this = {"active_threat_actors": ["apt41"], "active_campaigns": [{"theme": "APT41 wave"}]}

    out = q.build_comparison(_counts(), this, _doc(recap=last))

    assert out is not None
    assert out["new_this_week"] == {"threat_actors": [], "campaigns": [], "cves": []}


def test_everything_is_new_when_last_weeks_row_has_no_items() -> None:
    this = {"active_threat_actors": ["Apt41"], "notable_cves": ["CVE-2026-0001"]}

    out = q.build_comparison(_counts(), this, _doc(recap={}))

    assert out is not None
    assert out["new_this_week"]["threat_actors"] == ["Apt41"]
    assert out["new_this_week"]["cves"] == ["CVE-2026-0001"]


@pytest.mark.parametrize("junk", [None, "text", 7, [], {"active_threat_actors": "Apt41"}])
def test_malformed_stored_items_are_ignored_not_fatal(junk: Any) -> None:
    out = q.build_comparison(_counts(), junk, _doc(recap=junk))

    assert out is not None
    assert out["new_this_week"] == {"threat_actors": [], "campaigns": [], "cves": []}


def test_the_comparison_does_not_modify_its_inputs() -> None:
    previous = _doc(recap={"notable_cves": ["CVE-2026-0001"]})
    this = {"notable_cves": ["CVE-2026-0002"]}
    before = (copy.deepcopy(previous), copy.deepcopy(this))

    q.build_comparison(_counts(), this, previous)

    assert (previous, this) == before


# --- id event dan review -------------------------------------------------------------------------


def test_events_get_stable_ids_by_position_written_by_code_not_the_model() -> None:
    events = [{"event": "a", "id": "model-wrote-this"}, {"event": "b"}, {"event": "c"}]

    stamped = q.stamp_event_ids(events)

    assert [e["id"] for e in stamped] == ["f1", "f2", "f3"]  # type: ignore[union-attr]
    assert events[0]["id"] == "model-wrote-this"  # masukan tidak diubah


def test_a_non_object_event_keeps_its_position_but_gets_no_id() -> None:
    stamped = q.stamp_event_ids([{"event": "a"}, "just text", {"event": "c"}])

    assert stamped == [{"event": "a", "id": "f1"}, "just text", {"event": "c", "id": "f3"}]


@pytest.mark.parametrize("value", [None, "x", {"a": 1}, 3])
def test_stamping_something_that_is_not_a_list_returns_it_untouched(value: Any) -> None:
    assert q.stamp_event_ids(value) is value


def _forecast(*events: Any) -> dict[str, Any]:
    return {"likely_events": list(events)}


def test_a_row_made_before_ids_existed_gets_them_derived_by_position() -> None:
    """Baris yang dibuat sebelum PR ini tidak punya `id` dan TIDAK dimigrasi: id turunan harus
    sama dengan yang akan ditulis `stamp_event_ids`, supaya review dan tampilan merujuk event
    yang sama."""
    old = _forecast(
        {"event": "ransomware wave", "basis": "three hospital hits", "confidence": "high"},
        {"event": "VPN exploitation", "basis": "PoC published", "confidence": "med"},
    )

    events = q.events_for_review(old, limit=5)

    assert events == [
        {
            "id": "f1",
            "event": "ransomware wave",
            "basis": "three hospital hits",
            "confidence": "high",
        },
        {"id": "f2", "event": "VPN exploitation", "basis": "PoC published", "confidence": "med"},
    ]
    stamped = q.stamp_event_ids(old["likely_events"])
    assert [e["id"] for e in events] == [e["id"] for e in stamped]  # type: ignore[union-attr]


def test_stored_ids_are_kept_and_positions_count_items_that_are_skipped() -> None:
    forecast = _forecast(
        {"id": "f1", "event": "kept"},
        "not an object",
        {"event": ""},  # tak ada yang bisa dinilai
        {"event": "derived from position four", "confidence": 3},
    )

    events = q.events_for_review(forecast, limit=5)

    assert [e["id"] for e in events] == ["f1", "f4"]
    assert events[1]["confidence"] == ""  # bukan string: dikosongkan, bukan "3"


def test_review_input_is_capped_so_a_chatty_model_cannot_inflate_next_weeks_prompt() -> None:
    forecast = _forecast(*({"event": f"e{i}"} for i in range(1, 9)))

    events = q.events_for_review(forecast, limit=5)

    assert [e["id"] for e in events] == ["f1", "f2", "f3", "f4", "f5"]


@pytest.mark.parametrize("value", [None, {}, {"likely_events": "x"}, "forecast", []])
def test_a_forecast_without_a_list_of_events_has_nothing_to_review(value: Any) -> None:
    assert q.events_for_review(value, limit=5) == []


# --- scorecard -----------------------------------------------------------------------------------

REVIEWED = {"date": "2026-10-26", "period_start": "2026-10-26", "period_end": "2026-11-01"}
EVENTS = [
    {"id": "f1", "event": "ransomware wave", "basis": "hits", "confidence": "high"},
    {"id": "f2", "event": "VPN exploitation", "basis": "PoC", "confidence": "med"},
    {"id": "f3", "event": "supply chain", "basis": "npm", "confidence": "low"},
    {"id": "f4", "event": "DDoS", "basis": "chatter", "confidence": "low"},
]


def _review(*items: tuple[str, Any, Any]) -> list[dict[str, Any]]:
    return [{"id": i, "verdict": v, "evidence": e} for i, v, e in items]


def test_each_reviewed_event_gets_the_models_verdict_and_evidence() -> None:
    review = _review(
        ("f1", "happened", "Two hospitals hit again."),
        ("f2", "partly", "One vendor confirmed."),
        ("f3", "not_happened", "Nothing seen."),
        ("f4", "unclear", "No coverage."),
    )

    card = q.build_scorecard(REVIEWED, EVENTS, review)

    assert card["reviewed"] == REVIEWED
    assert [(e["id"], e["verdict"], e["evidence"]) for e in card["events"]] == [
        ("f1", "happened", "Two hospitals hit again."),
        ("f2", "partly", "One vendor confirmed."),
        ("f3", "not_happened", "Nothing seen."),
        ("f4", "unclear", "No coverage."),
    ]
    assert card["events"][0]["event"] == "ransomware wave"
    assert card["events"][0]["confidence"] == "high"  # confidence yang dinyatakan SAAT forecast
    assert all("override" not in e for e in card["events"])


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("Happened", "happened"),
        (" NOT HAPPENED ", "not_happened"),
        ("not-happened", "not_happened"),
        ("Partly", "partly"),
        ("mostly", "unclear"),
        ("true", "unclear"),
        (None, "unclear"),
        (True, "unclear"),
        (1, "unclear"),
        ("", "unclear"),
    ],
)
def test_a_verdict_is_normalised_and_anything_unrecognised_is_unclear(
    written: Any, expected: str
) -> None:
    card = q.build_scorecard(REVIEWED, EVENTS[:1], _review(("f1", written, "e")))

    assert card["events"][0]["verdict"] == expected


def test_an_event_the_model_did_not_answer_is_unclear_not_missing() -> None:
    """Analis harus tetap bisa menilainya (override), dan `unclear` tidak mengubah hit rate."""
    card = q.build_scorecard(REVIEWED, EVENTS, _review(("f1", "happened", "x")))

    assert [e["verdict"] for e in card["events"]] == ["happened", "unclear", "unclear", "unclear"]
    assert card["events"][1]["evidence"] == ""


@pytest.mark.parametrize("review", [None, "text", {"id": "f1"}, [], [None, 3, "x"]])
def test_a_reply_without_a_usable_review_leaves_every_event_unclear(review: Any) -> None:
    card = q.build_scorecard(REVIEWED, EVENTS, review)

    assert [e["verdict"] for e in card["events"]] == ["unclear"] * 4


def test_answers_for_ids_that_were_not_asked_are_ignored_and_the_first_answer_wins() -> None:
    review = _review(
        ("f9", "happened", "invented id"),
        ("f1", "happened", "first"),
        ("f1", "not_happened", "second"),
        (" f2 ", "partly", "padded id"),
    )

    card = q.build_scorecard(REVIEWED, EVENTS[:2], review)

    assert [(e["id"], e["verdict"], e["evidence"]) for e in card["events"]] == [
        ("f1", "happened", "first"),
        ("f2", "partly", "padded id"),
    ]


def test_evidence_that_is_not_text_is_dropped_and_text_is_trimmed() -> None:
    review = [
        {"id": "f1", "verdict": "happened", "evidence": {"x": 1}},
        {"id": "f2", "verdict": "happened", "evidence": "  padded  "},
    ]

    card = q.build_scorecard(REVIEWED, EVENTS[:2], review)

    assert [e["evidence"] for e in card["events"]] == ["", "padded"]


def test_an_analyst_override_is_stored_next_to_the_models_verdict_with_who_and_when() -> None:
    card = q.build_scorecard(REVIEWED, EVENTS, _review(("f1", "happened", "model says so")))

    updated = q.apply_override(card, "f1", "partly", by="analyst1", at=NOW)

    entry = updated["events"][0]
    assert entry["verdict"] == "happened"  # verdict model tetap
    assert entry["evidence"] == "model says so"
    assert entry["override"] == {"verdict": "partly", "by": "analyst1", "at": NOW.isoformat()}
    assert "override" not in card["events"][0]  # salinan: scorecard asal tidak berubah
    assert q.effective_verdict(entry) == "partly"


def test_a_second_override_replaces_the_first() -> None:
    card = q.build_scorecard(REVIEWED, EVENTS, [])
    first = q.apply_override(card, "f2", "happened", by="a", at=NOW)

    second = q.apply_override(first, "f2", "not_happened", by="b", at=NOW + datetime.timedelta(1))

    assert second["events"][1]["override"]["verdict"] == "not_happened"
    assert second["events"][1]["override"]["by"] == "b"


def test_overriding_an_entry_that_does_not_exist_or_with_a_bad_verdict_is_refused() -> None:
    card = q.build_scorecard(REVIEWED, EVENTS, [])

    with pytest.raises(LookupError, match="f9"):
        q.apply_override(card, "f9", "happened", by="a", at=NOW)
    with pytest.raises(ValueError, match="verdict must be one of"):
        q.apply_override(card, "f1", "mostly", by="a", at=NOW)


def test_regenerating_keeps_an_analysts_override_only_for_the_same_event() -> None:
    """Force regen menghitung ulang verdict model, tetapi pekerjaan analis tidak boleh hilang
    diam-diam: dipindahkan ke entri dengan id DAN teks event yang sama."""
    old = q.build_scorecard(REVIEWED, EVENTS, _review(("f1", "happened", "x")))
    old = q.apply_override(old, "f1", "not_happened", by="analyst1", at=NOW)
    old = q.apply_override(old, "f2", "happened", by="analyst1", at=NOW)
    changed = [dict(e) for e in EVENTS]
    changed[1]["event"] = "a different forecast now sits at f2"

    new = q.build_scorecard(REVIEWED, changed, _review(("f1", "partly", "y")), replacing=old)

    assert new["events"][0]["verdict"] == "partly"  # model dihitung ulang
    assert new["events"][0]["override"]["verdict"] == "not_happened"  # override dibawa
    assert new["events"][0]["override"]["by"] == "analyst1"
    assert "override" not in new["events"][1]  # f2 sekarang event lain: tidak dibawa


def test_replacing_a_scorecard_without_overrides_or_with_junk_changes_nothing() -> None:
    plain = q.build_scorecard(REVIEWED, EVENTS, [])

    for replacing in (None, {}, {"events": "x"}, {"events": [None, {"id": 3}]}, plain):
        card = q.build_scorecard(REVIEWED, EVENTS, [], replacing=replacing)
        assert all("override" not in e for e in card["events"])


def test_verdict_counts_use_the_effective_verdict_and_none_without_a_scorecard() -> None:
    card = q.build_scorecard(
        REVIEWED,
        EVENTS,
        _review(("f1", "happened", ""), ("f2", "partly", ""), ("f3", "not_happened", "")),
    )
    card = q.apply_override(card, "f3", "happened", by="a", at=NOW)

    assert q.verdict_counts(card) == {
        "happened": 2,
        "partly": 1,
        "not_happened": 0,
        "unclear": 1,
    }
    assert q.verdict_counts(None) is None


# --- hit rate ------------------------------------------------------------------------------------


def _entry(confidence: str, verdict: str, override: str | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": "f1", "confidence": confidence, "verdict": verdict}
    if override:
        entry["override"] = {"verdict": override, "by": "a", "at": NOW.isoformat()}
    return entry


def _row(date: str, *entries: dict[str, Any]) -> dict[str, Any]:
    quality = {"scorecard": {"reviewed": {}, "events": list(entries)}} if entries else {}
    return {"date": date, "quality": quality}


def test_partly_counts_half_and_unclear_is_left_out_of_the_denominator() -> None:
    rows = [
        _row(
            "2026-10-19",
            _entry("high", "happened"),
            _entry("high", "partly"),
            _entry("high", "not_happened"),
            _entry("high", "unclear"),
        )
    ]

    out = q.hit_rate(rows)["by_confidence"]["high"]

    assert out == {"events": 4, "judged": 3, "unclear": 1, "hits": 1.5, "rate_pct": 50.0}


def test_the_rate_is_split_by_the_confidence_stated_when_the_forecast_was_made() -> None:
    rows = [
        _row("2026-10-12", _entry("high", "happened"), _entry("low", "not_happened")),
        _row("2026-10-19", _entry("high", "happened"), _entry("med", "partly")),
        _row("2026-10-26", _entry("low", "happened"), _entry("low", "not_happened")),
    ]

    out = q.hit_rate(rows)

    assert out["by_confidence"]["high"]["rate_pct"] == 100.0
    assert out["by_confidence"]["med"]["rate_pct"] == 50.0
    assert out["by_confidence"]["low"]["rate_pct"] == pytest.approx(33.3)  # 1 dari 3
    assert out["overall"] == {
        "events": 6,
        "judged": 6,
        "unclear": 0,
        "hits": 3.5,
        "rate_pct": 58.3,
    }


def test_the_analysts_verdict_wins_over_the_models_in_every_direction() -> None:
    rows = [
        _row(
            "2026-10-19",
            _entry("high", "not_happened", override="happened"),  # analis: terjadi
            _entry("high", "happened", override="not_happened"),  # analis: tidak
            _entry("high", "unclear", override="partly"),  # model ragu, analis menilai
            _entry("high", "happened", override="unclear"),  # analis keluarkan dari penyebut
        )
    ]

    out = q.hit_rate(rows)["by_confidence"]["high"]

    assert out == {"events": 4, "judged": 3, "unclear": 1, "hits": 1.5, "rate_pct": 50.0}


def test_an_override_changes_the_hit_rate_of_a_past_week() -> None:
    """Itu sebabnya hit rate dihitung saat dibaca, bukan disimpan di baris."""
    card = q.build_scorecard(REVIEWED, EVENTS[:1], _review(("f1", "not_happened", "")))
    before = q.hit_rate([{"date": "2026-11-02", "quality": {"scorecard": card}}])

    card = q.apply_override(card, "f1", "happened", by="a", at=NOW)
    after = q.hit_rate([{"date": "2026-11-02", "quality": {"scorecard": card}}])

    assert before["by_confidence"]["high"]["rate_pct"] == 0.0
    assert after["by_confidence"]["high"]["rate_pct"] == 100.0


@pytest.mark.parametrize(
    ("stated", "bucket"),
    [
        ("high", "high"),
        ("HIGH", "high"),
        ("medium", "med"),
        ("Med", "med"),
        ("low", "low"),
        ("", "low"),
        ("very high", "low"),
        (None, "low"),
        (3, "low"),
    ],
)
def test_the_stated_confidence_is_normalised_and_unknown_counts_as_low(
    stated: Any, bucket: str
) -> None:
    out = q.hit_rate([_row("2026-10-19", _entry(stated, "happened"))])

    assert out["by_confidence"][bucket]["events"] == 1


def test_nothing_judged_yet_has_no_rate_instead_of_zero() -> None:
    out = q.hit_rate([_row("2026-10-19", _entry("high", "unclear"))])

    assert out["by_confidence"]["high"]["rate_pct"] is None
    assert out["by_confidence"]["high"]["judged"] == 0
    assert out["overall"]["rate_pct"] is None


def test_weeks_without_a_scorecard_count_as_weeks_but_not_as_reviewed_weeks() -> None:
    rows = [
        _row("2026-10-26", _entry("low", "happened")),
        _row("2026-10-19"),  # pekan sepi atau baris dari sebelum scorecard ada
        _row("2026-10-12"),  # pekan pertama: tidak ada yang di-review
    ]

    out = q.hit_rate(rows)

    assert (out["weeks"], out["reviewed_weeks"]) == (3, 1)
    assert (out["first_week"], out["last_week"]) == ("2026-10-12", "2026-10-26")


def test_no_rows_is_a_valid_empty_answer() -> None:
    out = q.hit_rate([])

    assert (out["weeks"], out["reviewed_weeks"], out["first_week"], out["last_week"]) == (
        0,
        0,
        None,
        None,
    )
    assert out["overall"] == {"events": 0, "judged": 0, "unclear": 0, "hits": 0.0, "rate_pct": None}
    assert list(out["by_confidence"]) == ["low", "med", "high"]


@pytest.mark.parametrize(
    "quality",
    [
        None,
        {},
        {"scorecard": None},
        {"scorecard": "x"},
        {"scorecard": {"events": "x"}},
        {"scorecard": {"events": [None, 3, "x"]}},
        "text",
    ],
)
def test_malformed_stored_quality_is_skipped_not_fatal(quality: Any) -> None:
    out = q.hit_rate([{"date": "2026-10-19", "quality": quality}])

    assert out["reviewed_weeks"] == 0
    assert out["overall"]["events"] == 0
