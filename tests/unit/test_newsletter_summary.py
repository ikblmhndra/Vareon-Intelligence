"""Unit test Executive Summary newsletter (`cti_api.services.newsletter_summary`, ROADMAP #22 PR 8)
dengan recap dan klien LLM palsu: tanpa recap tidak ada panggilan, CVE karangan ditandai dan
dicatat, pekan yang dipakai dan rentang yang dicakup tercatat (termasuk ekor bulan yang pekannya
belum selesai), dan prompt memuat glosarium PR 6. Yang butuh Postgres ada di
`tests/integration/test_newsletter_prepare_monthly.py`."""

from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import structlog.testing
from cti_api.services import newsletter_glossary
from cti_api.services import newsletter_summary as summary

D = datetime.date

OCTOBER = (D(2026, 10, 1), D(2026, 10, 31))
NOVEMBER = (D(2026, 11, 1), D(2026, 11, 30))


def _recap(week_start: D, **overrides: Any) -> SimpleNamespace:
    """Satu baris recap mingguan palsu; `yesterday` = isi recap seperti yang disimpan PR 2."""
    body = {
        "summary": f"Narrative of the week of {week_start.isoformat()}.",
        "top_stories": [
            {"article_id": 1, "title": "Bank breached", "why_it_matters": "Big loss."},
            {"article_id": 2, "title": "Zero-day in VPN"},
        ],
        "active_threat_actors": ["APT41"],
        "new_threat_actors_added": [{"name": "Ghost Crew", "source": "X"}],
        "notable_cves": ["CVE-2026-1111"],
        "active_campaigns": [{"theme": "VPN exploitation wave", "article_count": 5}],
        "apac_signals": ["Indonesia ministry hit"],
    }
    row = {
        "date": week_start.isoformat(),
        "period_start": week_start,
        "period_end": week_start + datetime.timedelta(days=6),
        "headline": f"Headline {week_start.isoformat()}",
        "yesterday": body,
        "forecast": {"summary": "FORECAST-ONLY-TEXT", "likely_events": []},
        **overrides,
    }
    return SimpleNamespace(**row)


class _FakeRecapRepo:
    rows: list[Any] = []  # noqa: RUF012 - state kelas sengaja, direset tiap test
    asked: list[tuple[str, D, D]] = []  # noqa: RUF012

    def __init__(self, session: Any) -> None:
        pass

    async def list_overlapping(self, kind: str, start: D, end: D) -> list[Any]:
        type(self).asked.append((kind, start, end))
        return type(self).rows


class _FakeLlm:
    """Klien OpenAI palsu: membalas `reply` (string, atau JSON dari dict) dan mencatat panggilan."""

    def __init__(self, reply: str | dict[str, Any]) -> None:
        self.reply = reply if isinstance(reply, str) else json.dumps(reply)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.reply))],
            usage=SimpleNamespace(prompt_tokens=400, completion_tokens=150, total_tokens=550),
        )


@pytest.fixture
def recaps(monkeypatch: pytest.MonkeyPatch) -> type[_FakeRecapRepo]:
    _FakeRecapRepo.rows, _FakeRecapRepo.asked = [], []
    monkeypatch.setattr(summary, "AsyncRecapRepo", _FakeRecapRepo)
    return _FakeRecapRepo


def _llm(monkeypatch: pytest.MonkeyPatch, reply: str | dict[str, Any]) -> _FakeLlm:
    fake = _FakeLlm(reply)
    monkeypatch.setattr(summary, "get_llm_client", MagicMock(return_value=(fake, "stub-model")))
    return fake


async def _generate(window: tuple[D, D] = OCTOBER) -> tuple[str, dict[str, Any]]:
    return await summary.generate_executive_summary("SESSION", *window)  # type: ignore[arg-type]


OCTOBER_WEEKS = [D(2026, 9, 28), D(2026, 10, 5), D(2026, 10, 12), D(2026, 10, 19), D(2026, 10, 26)]


# --- tanpa recap -------------------------------------------------------------------------------


async def test_no_recaps_means_an_empty_summary_and_no_llm_call(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    monkeypatch.setattr(summary, "get_llm_client", MagicMock(side_effect=AssertionError("LLM")))

    text, meta = await _generate()

    assert text == ""
    assert meta == {
        "weeks": [],
        "covered_start": None,
        "covered_end": None,
        "uncovered": [{"start": "2026-10-01", "end": "2026-10-31"}],
        "model": "",
        "dropped": [],
        "parse_failed": False,
        "error": None,
        "token_usage": {"skipped": True, "reason": "no_recaps"},
    }
    assert recaps.asked == [("weekly", D(2026, 10, 1), D(2026, 10, 31))]


async def test_recaps_without_anything_to_summarise_do_not_count_as_used(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    """Recap yang balasan modelnya gagal di-parse (judul dan isi kosong): tidak ada yang
    diringkas, jadi bukan pekan yang dipakai dan tidak ada panggilan."""
    recaps.rows = [_recap(D(2026, 10, 5), headline="", yesterday={})]
    monkeypatch.setattr(summary, "get_llm_client", MagicMock(side_effect=AssertionError("LLM")))

    text, meta = await _generate()

    assert text == "" and meta["weeks"] == []
    assert meta["uncovered"] == [{"start": "2026-10-01", "end": "2026-10-31"}]


# --- dengan recap ------------------------------------------------------------------------------


async def test_one_call_condenses_the_weeks_and_records_what_was_used(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    recaps.rows = [_recap(w) for w in OCTOBER_WEEKS]
    llm = _llm(monkeypatch, {"summary": "Oktober diwarnai eksploitasi VPN dan CVE-2026-1111."})

    text, meta = await _generate()

    assert text == "Oktober diwarnai eksploitasi VPN dan CVE-2026-1111."
    assert len(llm.calls) == 1
    assert llm.calls[0]["temperature"] == 0
    assert meta["weeks"] == [
        {"week_start": "2026-09-28", "week_end": "2026-10-04"},
        {"week_start": "2026-10-05", "week_end": "2026-10-11"},
        {"week_start": "2026-10-12", "week_end": "2026-10-18"},
        {"week_start": "2026-10-19", "week_end": "2026-10-25"},
        {"week_start": "2026-10-26", "week_end": "2026-11-01"},
    ]
    # batas PEKAN, bukan batas bulan: pekan 28 Sep dan 26 Okt dipakai utuh
    assert (meta["covered_start"], meta["covered_end"]) == ("2026-09-28", "2026-11-01")
    assert meta["uncovered"] == []
    assert meta["model"] == "stub-model"
    assert meta["dropped"] == [] and meta["parse_failed"] is False and meta["error"] is None
    usage = meta["token_usage"]
    assert (usage["prompt_tokens"], usage["completion_tokens"], usage["total_tokens"]) == (
        400,
        150,
        550,
    )
    assert usage["input_chars"] == len(llm.calls[0]["messages"][1]["content"])
    assert isinstance(usage["wall_ms"], int)


async def test_the_model_sees_the_recap_texts_and_the_edition_but_not_the_forecast(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    recaps.rows = [_recap(D(2026, 10, 5))]
    llm = _llm(monkeypatch, {"summary": "Ringkasan."})

    await _generate()

    system, user = (m["content"] for m in llm.calls[0]["messages"])
    assert "Edition: October 2026 (1" in user and "31 October 2026" in user
    assert "Weekly recaps (1):" in user
    assert "=== Week 2026-10-05 to 2026-10-11 ===" in user
    for expected in (
        "Headline: Headline 2026-10-05",
        "Summary: Narrative of the week of 2026-10-05.",
        "- Bank breached: Big loss.",
        "- Zero-day in VPN",
        "Active threat actors: APT41",
        "Active campaigns: VPN exploitation wave",
        "Notable CVEs: CVE-2026-1111",
        "APAC signals: Indonesia ministry hit",
    ):
        assert expected in user, expected
    assert "FORECAST-ONLY-TEXT" not in user
    # `system` meminta SATU paragraf Indonesia tanpa rekomendasi, dalam JSON dengan kunci `summary`
    assert "ONE paragraph" in system and "Indonesian" in system
    assert "Do not give recommendations" in system
    assert '{"summary": ' in system


def test_the_prompt_carries_the_glossary_so_one_correction_applies_everywhere() -> None:
    prompt = summary.system_prompt()

    for kept in newsletter_glossary.KEEP_AS_WRITTEN:
        assert kept in prompt
    for english, indonesian in newsletter_glossary.TRANSLATIONS:
        assert f"- {english}: {indonesian}" in prompt
    for term in newsletter_glossary.KEEP_IN_ENGLISH:
        assert term in prompt
    assert "key_points" not in prompt  # kunci prompt ringkasan artikel, bukan milik prompt ini


async def test_an_invented_cve_id_is_replaced_by_the_indonesian_marker_and_listed(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    recaps.rows = [_recap(D(2026, 10, 5))]
    _llm(
        monkeypatch,
        {"summary": "Eksploitasi CVE-2026-1111 meluas, dan CVE-2026-9999 ikut disebut."},
    )

    text, meta = await _generate()

    assert text == ("Eksploitasi CVE-2026-1111 meluas, dan [CVE tidak terverifikasi] ikut disebut.")
    assert meta["dropped"] == [
        {"field": "summary", "value": "CVE-2026-9999", "reason": "not_in_input"}
    ]


async def test_a_cve_id_written_in_a_sloppy_form_is_still_checked(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    recaps.rows = [_recap(D(2026, 10, 5))]
    _llm(monkeypatch, {"summary": "Kerentanan cve 2026 7777 dan CVE-2026-1111."})

    text, meta = await _generate()

    assert "[CVE tidak terverifikasi]" in text and "CVE-2026-1111" in text
    assert [d["value"] for d in meta["dropped"]] == ["CVE-2026-7777"]


async def test_the_reply_is_collapsed_to_a_single_paragraph(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    recaps.rows = [_recap(D(2026, 10, 5))]
    _llm(monkeypatch, {"summary": "  Kalimat satu.\n\nKalimat   dua.\n"})

    text, _ = await _generate()

    assert text == "Kalimat satu. Kalimat dua."


@pytest.mark.parametrize(
    "reply",
    ["Ini bukan JSON sama sekali.", "", {"headline": "tanpa kunci summary"}, {"summary": ["list"]}],
)
async def test_a_reply_without_a_usable_summary_is_empty_and_flagged_not_an_error(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo], reply: str | dict[str, Any]
) -> None:
    recaps.rows = [_recap(D(2026, 10, 5))]
    _llm(monkeypatch, reply)

    text, meta = await _generate()

    assert text == ""
    assert meta["parse_failed"] is True and meta["dropped"] == []
    assert meta["token_usage"]["total_tokens"] == 550  # panggilannya tetap tercatat


def _broken_llm(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> MagicMock:
    broken = MagicMock()
    broken.chat.completions.create.side_effect = exc
    monkeypatch.setattr(summary, "get_llm_client", MagicMock(return_value=(broken, "m")))
    return broken


async def test_a_gateway_failure_is_recorded_not_raised_so_the_ranking_is_not_lost(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    recaps.rows = [_recap(w) for w in OCTOBER_WEEKS[:2]]
    broken = _broken_llm(monkeypatch, RuntimeError("gateway down"))

    with structlog.testing.capture_logs() as logs:
        text, meta = await _generate()

    assert text == ""
    assert broken.chat.completions.create.call_count == 1
    assert meta["error"] == "RuntimeError: gateway down"
    assert meta["token_usage"] == {"skipped": True, "reason": "llm_error"}
    assert meta["parse_failed"] is False and meta["dropped"] == [] and meta["model"] == ""
    # yang dihitung dari recap tetap ada, supaya composer bisa menampilkan apa yang dicakup
    assert [w["week_start"] for w in meta["weeks"]] == ["2026-09-28", "2026-10-05"]
    assert (meta["covered_start"], meta["covered_end"]) == ("2026-09-28", "2026-10-11")
    assert meta["uncovered"] == [{"start": "2026-10-12", "end": "2026-10-31"}]
    [failed] = [e for e in logs if e["event"] == "newsletter_summary_failed"]
    assert failed["log_level"] == "warning" and failed["error"] == meta["error"]


async def test_the_meta_has_the_same_keys_on_every_path(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    """Composer membaca satu bentuk: tanpa recap, sukses, balasan tak terpakai, dan gagal."""
    shapes = []
    _llm(monkeypatch, {"summary": "Ok."})
    shapes.append(await _generate())  # tanpa recap
    recaps.rows = [_recap(D(2026, 10, 5))]
    shapes.append(await _generate())  # sukses
    _llm(monkeypatch, "bukan JSON")
    shapes.append(await _generate())  # balasan tak terpakai
    _broken_llm(monkeypatch, RuntimeError("x"))
    shapes.append(await _generate())  # gagal

    assert len({frozenset(meta) for _, meta in shapes}) == 1
    assert [meta["error"] for _, meta in shapes] == [None, None, None, "RuntimeError: x"]


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TimeoutError(), "TimeoutError"),  # tanpa pesan: namanya saja
        (RuntimeError("one\n  two\tthree"), "RuntimeError: one two three"),  # satu baris
        (ValueError("x" * 500), "ValueError: " + "x" * summary.ERROR_CLIP),  # dipotong
    ],
)
async def test_the_error_text_is_one_short_line(
    monkeypatch: pytest.MonkeyPatch,
    recaps: type[_FakeRecapRepo],
    exc: Exception,
    expected: str,
) -> None:
    recaps.rows = [_recap(D(2026, 10, 5))]
    _broken_llm(monkeypatch, exc)

    _, meta = await _generate()

    assert meta["error"] == expected


async def test_only_the_llm_call_is_caught_a_database_failure_still_raises(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    async def broken_query(self: Any, kind: str, start: D, end: D) -> list[Any]:
        raise ConnectionError("db down")

    monkeypatch.setattr(_FakeRecapRepo, "list_overlapping", broken_query)

    with pytest.raises(ConnectionError, match="db down"):
        await _generate()


async def test_recap_content_of_an_unexpected_shape_does_not_crash_the_prompt(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    recaps.rows = [
        _recap(
            D(2026, 10, 5),
            yesterday={
                "summary": "Valid narrative.",
                "top_stories": "not a list",
                "active_campaigns": [None, 3, {"theme": ""}, {"theme": "Real theme"}],
                "notable_cves": [{"cve": "CVE-2026-1"}, "CVE-2026-1111"],
                "active_threat_actors": None,
                "apac_signals": 7,
            },
        )
    ]
    llm = _llm(monkeypatch, {"summary": "Ok."})

    await _generate()

    user = llm.calls[0]["messages"][1]["content"]
    assert "Summary: Valid narrative." in user
    assert "Active campaigns: Real theme" in user
    assert "Notable CVEs: CVE-2026-1111" in user
    assert "Top stories" not in user and "APAC signals" not in user


# --- ekor bulan dan pekan bolong ---------------------------------------------------------------


async def test_the_tail_of_a_month_whose_last_week_is_not_finished_is_not_covered(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    """November 2026 berakhir Senin 30 Nov; pekannya (30 Nov-6 Des) belum selesai pada Selasa
    1 Des, jadi recap-nya belum ada. Hari itu tidak masuk ringkasan, dan tercatat."""
    finished = [D(2026, 10, 26), D(2026, 11, 2), D(2026, 11, 9), D(2026, 11, 16), D(2026, 11, 23)]
    recaps.rows = [_recap(w) for w in finished]
    _llm(monkeypatch, {"summary": "November."})

    _, meta = await _generate(NOVEMBER)

    assert (meta["covered_start"], meta["covered_end"]) == ("2026-10-26", "2026-11-29")
    assert meta["uncovered"] == [{"start": "2026-11-30", "end": "2026-11-30"}]
    assert [w["week_start"] for w in meta["weeks"]] == [w.isoformat() for w in finished]


async def test_a_month_that_ends_on_a_sunday_has_no_uncovered_tail(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    """Mei 2026 berakhir Minggu 31 Mei: pekan terakhirnya (25-31 Mei) utuh."""
    weeks = [D(2026, 4, 27), D(2026, 5, 4), D(2026, 5, 11), D(2026, 5, 18), D(2026, 5, 25)]
    recaps.rows = [_recap(w) for w in weeks]
    _llm(monkeypatch, {"summary": "Mei."})

    _, meta = await _generate((D(2026, 5, 1), D(2026, 5, 31)))

    assert meta["uncovered"] == []
    assert meta["covered_end"] == "2026-05-31"


async def test_a_missing_week_in_the_middle_is_reported_as_uncovered_days(
    monkeypatch: pytest.MonkeyPatch, recaps: type[_FakeRecapRepo]
) -> None:
    """Recap pekan 12-18 Okt tidak ada (worker mati hari Senin itu): hanya pekan yang ADA dipakai
    dan lubangnya terlihat, tidak ditambal dari artikel mentah."""
    recaps.rows = [_recap(w) for w in OCTOBER_WEEKS if w != D(2026, 10, 12)]
    _llm(monkeypatch, {"summary": "Oktober."})

    _, meta = await _generate()

    assert meta["uncovered"] == [{"start": "2026-10-12", "end": "2026-10-18"}]
    assert len(meta["weeks"]) == 4


def test_uncovered_days_handles_edges_and_unsorted_input() -> None:
    weeks = [(D(2026, 10, 12), D(2026, 10, 18)), (D(2026, 9, 28), D(2026, 10, 4))]

    assert summary.uncovered_days(*OCTOBER, weeks) == [
        {"start": "2026-10-05", "end": "2026-10-11"},
        {"start": "2026-10-19", "end": "2026-10-31"},
    ]
    assert summary.uncovered_days(*OCTOBER, []) == [{"start": "2026-10-01", "end": "2026-10-31"}]
    full = [(D(2026, 9, 28), D(2026, 11, 1))]
    assert summary.uncovered_days(*OCTOBER, full) == []
