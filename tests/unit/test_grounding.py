"""Unit test `cti_api.services.grounding` (#21 PR 3) -- tanpa DB, tanpa LLM. Modul ini dipakai
recap mingguan dan (PR 8) ringkasan newsletter, jadi yang dites di sini perilaku modulnya sendiri,
bukan bentuk keluaran recap: recap-nya dites di `test_recap_weekly.py` dan
`tests/integration/test_recap_service.py`."""

from __future__ import annotations

import ast
import copy
import pathlib
import sys
from typing import Any

import pytest
from cti_api.services import grounding as g

ARTICLES = {
    12: g.ArticleRef(url="https://example.com/a/12", source="CISA"),
    7: g.ArticleRef(url="https://example.com/a/7", source="BleepingComputer"),
}
NB_HYPHEN = chr(0x2011)  # tanda hubung tak-putus
EN_DASH = chr(0x2013)
ARABIC_YEAR = "".join(chr(c) for c in (0x662, 0x660, 0x662, 0x666))  # digit Arab-Indic
TEXT = (
    "- [#12] [CISA] Apt41 exploits CVE-2026-0001 in a VPN | actors: Apt41\n"
    "- [#7] [BleepingComputer] Lazarus Group hits an exchange\n"
    "- Apt41 wave - 3 articles | actors: Apt41"
)


def _known(**over: Any) -> g.Known:
    base: dict[str, Any] = {
        "text": TEXT,
        "cve_ids": ["CVE-2026-0002"],  # sah, tapi tidak ada di teks: dari daftar terstruktur
        "threat_actors": ["Apt41"],
        "campaigns": ["Apt41 wave"],
        "sources": ["CISA", "BleepingComputer"],
        "articles": ARTICLES,
    }
    return g.Known.build(**{**base, **over})


def _dropped(grounder: g.Grounder) -> list[tuple[str, str, str]]:
    return [(d.field, d.value, d.reason) for d in grounder.dropped]


# --- CVE id: bentuk kanonik dan variannya ------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "CVE-2026-0001",
        "cve-2026-0001",
        "  CVE-2026-0001  ",
        "CVE 2026 0001",
        "CVE_2026_0001",
        "CVE - 2026 - 0001",
        f"CVE{NB_HYPHEN}2026{NB_HYPHEN}0001",
        f"CVE{EN_DASH}2026{EN_DASH}0001",
        "cve2026-0001",
    ],
)
def test_cve_id_variants_normalise_to_one_canonical_form(raw: str) -> None:
    assert g.normalize_cve_id(raw) == "CVE-2026-0001"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "CVE-26-0001",  # tahun dua digit
        "CVE-2026-001",  # nomor urut kurang dari empat digit
        "CVE-2026",
        "CVE-2026-0001 critical",  # bukan id saja
        "XCVE-2026-0001",
        f"CVE-{ARABIC_YEAR}-0001",  # bukan digit ASCII
        "Log4Shell",
    ],
)
def test_text_that_is_not_a_cve_id_is_not_normalised(raw: str) -> None:
    assert g.normalize_cve_id(raw) is None


def test_a_long_sequence_number_is_kept_whole() -> None:
    assert g.normalize_cve_id("CVE-2021-1000001") == "CVE-2021-1000001"


def test_extract_finds_every_id_in_prose_once_in_order_of_first_appearance() -> None:
    text = "See CVE-2026-0002, cve 2026 0001 and again CVE-2026-0002. Not ABCVE-2026-0009."

    assert g.extract_cve_ids(text) == ["CVE-2026-0002", "CVE-2026-0001"]


def test_extract_finds_an_id_inside_a_url() -> None:
    assert g.extract_cve_ids("https://nvd.nist.gov/vuln/detail/CVE-2026-0001") == ["CVE-2026-0001"]


def test_name_key_ignores_case_spacing_and_punctuation_but_not_words() -> None:
    assert g.name_key("APT 41") == g.name_key("apt-41") == g.name_key("Apt41") == "apt41"
    assert g.name_key("Lazarus Group") != g.name_key("Lazarus")
    assert g.name_key("--") == ""


def test_known_collects_cve_ids_from_the_text_and_the_explicit_list() -> None:
    known = _known()

    assert known.cve_ids == {"CVE-2026-0001", "CVE-2026-0002"}  # teks + daftar terstruktur


def test_known_without_text_or_sets_knows_nothing() -> None:
    known = g.Known.build()

    assert known.cve_ids == frozenset() and known.articles == {}
    assert g.Grounder(known).cve_list("recap.notable_cves", ["CVE-2026-0001"]) == []


# --- daftar CVE id ----------------------------------------------------------------------------


def test_an_invented_cve_id_is_dropped_and_listed_while_a_real_one_stays() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.cve_list("recap.notable_cves", ["CVE-2026-0001", "CVE-2026-9999"])

    assert kept == ["CVE-2026-0001"]
    assert _dropped(grounder) == [("recap.notable_cves", "CVE-2026-9999", g.NOT_IN_INPUT)]
    assert grounder.report() == {
        "dropped": [
            {"field": "recap.notable_cves", "value": "CVE-2026-9999", "reason": "not_in_input"}
        ],
        "count": 1,
    }


def test_case_and_spacing_variants_of_a_real_id_stay_as_the_model_wrote_them() -> None:
    grounder = g.Grounder(_known())

    variants = ["cve-2026-0001", "CVE 2026 0002", f"CVE{NB_HYPHEN}2026{NB_HYPHEN}0001"]

    kept = grounder.cve_list("f", variants)

    assert kept == variants
    assert grounder.dropped == []


def test_a_variant_of_an_invented_id_is_dropped_too() -> None:
    grounder = g.Grounder(_known())

    assert grounder.cve_list("f", ["cve 2026 9999"]) == []
    assert _dropped(grounder) == [("f", "cve 2026 9999", g.NOT_IN_INPUT)]


def test_an_entry_with_extra_words_stays_only_if_every_id_in_it_is_real() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.cve_list(
        "f", ["CVE-2026-0001 (critical)", "CVE-2026-0001 and CVE-2026-9999", "CVE-2026-0002"]
    )

    assert kept == ["CVE-2026-0001 (critical)", "CVE-2026-0002"]
    assert _dropped(grounder) == [("f", "CVE-2026-0001 and CVE-2026-9999", g.NOT_IN_INPUT)]


def test_an_id_that_exists_only_in_an_article_title_in_the_text_is_real() -> None:
    known = _known(text="- [#1] [CISA] Patch CVE-2026-4444 now", cve_ids=[])

    assert g.Grounder(known).cve_list("f", ["CVE-2026-4444"]) == ["CVE-2026-4444"]


def test_things_that_are_not_ids_in_a_cve_list_are_malformed_and_listed() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.cve_list("f", ["Log4Shell", 42, None, {"id": "CVE-2026-0001"}])

    assert kept == []
    assert [(f, r) for f, _, r in _dropped(grounder)] == [("f", g.MALFORMED)] * 4


def test_a_list_field_that_is_not_a_list_is_listed_once_and_becomes_empty() -> None:
    grounder = g.Grounder(_known())

    assert grounder.cve_list("f", "CVE-2026-0001") == []
    assert _dropped(grounder) == [("f", "CVE-2026-0001", g.MALFORMED)]


def test_a_missing_or_null_list_is_not_a_drop() -> None:
    grounder = g.Grounder(_known())

    assert grounder.cve_list("f", None) == []
    assert grounder.name_list("f", None, "threat_actors") == []
    assert grounder.stories("f", None) == []
    assert grounder.dropped == []


def test_the_same_invented_id_in_one_field_is_listed_once() -> None:
    grounder = g.Grounder(_known())

    grounder.cve_list("f", ["CVE-2026-9999", "CVE-2026-9999"])

    assert len(grounder.dropped) == 1


# --- nama: actor, kampanye, sumber -------------------------------------------------------------


def test_an_invented_actor_is_dropped_and_listed_while_a_real_one_stays() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.name_list(
        "recap.active_threat_actors", ["Apt41", "Midnight Blizzard"], "threat_actors"
    )

    assert kept == ["Apt41"]
    assert _dropped(grounder) == [
        ("recap.active_threat_actors", "Midnight Blizzard", g.NOT_IN_INPUT)
    ]


def test_an_actor_written_with_other_spacing_or_case_is_still_the_same_actor() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.name_list("f", ["APT 41", "apt-41", "APT41"], "threat_actors")

    assert kept == ["APT 41", "apt-41", "APT41"]
    assert grounder.dropped == []


def test_an_actor_named_only_in_the_prompt_text_is_not_invented() -> None:
    """ "Lazarus Group" ada di judul, bukan di daftar actor terstruktur: membuangnya akan
    menyatakan karangan untuk sesuatu yang ada di masukan."""
    grounder = g.Grounder(_known())

    kept = grounder.name_list("f", ["Lazarus Group", "Lazarus"], "threat_actors")

    assert kept == ["Lazarus Group", "Lazarus"]  # "Lazarus" = satu kata utuh dari frasa di teks


def test_a_name_must_match_whole_words_in_the_text_not_a_piece_of_a_word() -> None:
    grounder = g.Grounder(_known())

    assert grounder.name_list("f", ["Laza", "azarus Gro"], "threat_actors") == []
    assert len(grounder.dropped) == 2


def test_a_very_short_name_is_never_matched_through_the_text() -> None:
    known = _known(text="a tale of an actor", threat_actors=[])
    grounder = g.Grounder(known)

    assert grounder.name_list("f", ["An", "Tale"], "threat_actors") == ["Tale"]
    assert _dropped(grounder) == [("f", "An", g.NOT_IN_INPUT)]


def test_an_invented_campaign_is_dropped_and_a_real_one_keeps_its_whole_object() -> None:
    grounder = g.Grounder(_known())
    campaigns = [
        {"theme": "Apt41 wave", "article_count": 3, "why_it_matters": "x"},
        {"theme": "Operation ShadowGate", "article_count": 9, "why_it_matters": "y"},
    ]

    kept = grounder.name_list("recap.active_campaigns", campaigns, "campaigns", key="theme")

    assert kept == [campaigns[0]]
    assert _dropped(grounder) == [
        ("recap.active_campaigns", "Operation ShadowGate", g.NOT_IN_INPUT)
    ]


def test_a_paraphrased_campaign_theme_is_dropped_and_listed_not_waved_through() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.name_list(
        "f", [{"theme": "Intrusion set around Apt41 activity"}], "campaigns", key="theme"
    )

    assert kept == []
    assert _dropped(grounder)[0][2] == g.NOT_IN_INPUT


def test_new_actor_objects_are_checked_by_their_name() -> None:
    grounder = g.Grounder(_known(text="", threat_actors=["Apt41"]))
    items = [{"name": "Apt41", "source": "mitre"}, {"name": "Ghost", "source": "x"}]

    kept = grounder.name_list("recap.new_threat_actors_added", items, "threat_actors", key="name")

    assert kept == [items[0]]
    assert _dropped(grounder) == [("recap.new_threat_actors_added", "Ghost", g.NOT_IN_INPUT)]


def test_names_that_are_not_names_are_malformed() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.name_list("f", ["", "--", 7, None], "threat_actors")

    assert kept == []
    assert {r for _, _, r in _dropped(grounder)} == {g.MALFORMED}
    kept = grounder.name_list("f2", [{"nama": "Apt41"}, "Apt41"], "campaigns", key="theme")
    assert kept == []
    assert [r for f, _, r in _dropped(grounder) if f == "f2"] == [g.MALFORMED, g.MALFORMED]


# --- story: lewat id artikel, bukan judul --------------------------------------------------------


def _story(**over: Any) -> dict[str, Any]:
    return {
        "article_id": 12,
        "title": "A paraphrase the model wrote, not the original title",
        "why_it_matters": "because",
        "source": "CISA",
        **over,
    }


def test_a_story_that_cites_an_article_in_the_input_stays_and_gets_its_url() -> None:
    grounder = g.Grounder(_known())

    [story] = grounder.stories("recap.top_stories", [_story()])

    assert story == {
        "article_id": 12,
        "title": "A paraphrase the model wrote, not the original title",  # judul tidak dibandingkan
        "why_it_matters": "because",
        "source": "CISA",
        "url": "https://example.com/a/12",
    }
    assert grounder.dropped == []


def test_a_story_citing_an_id_that_was_not_in_the_input_is_dropped_and_listed() -> None:
    grounder = g.Grounder(_known())

    kept = grounder.stories("recap.top_stories", [_story(article_id=999, title="Real-sounding")])

    assert kept == []
    assert _dropped(grounder) == [
        ("recap.top_stories", "Real-sounding [#999]", g.UNKNOWN_ARTICLE_ID)
    ]


def test_a_story_with_no_usable_article_id_cannot_be_verified_and_is_dropped() -> None:
    grounder = g.Grounder(_known())
    stories = [
        {"title": "no id at all"},
        _story(article_id="abc", title="not a number"),
        _story(article_id=None, title="null id"),
        _story(article_id=True, title="a bool is not an id"),
        _story(article_id=12.5, title="a float is not an id"),
    ]

    assert grounder.stories("f", stories) == []
    assert [(v, r) for _, v, r in _dropped(grounder)] == [
        ("no id at all", g.NO_ARTICLE_ID),
        ("not a number", g.NO_ARTICLE_ID),
        ("null id", g.NO_ARTICLE_ID),
        ("a bool is not an id", g.NO_ARTICLE_ID),
        ("a float is not an id", g.NO_ARTICLE_ID),
    ]


@pytest.mark.parametrize("written", ["12", "#12", "[#12]", " [ # 12 ] ", 12])
def test_the_article_id_may_be_written_the_way_the_prompt_shows_it(written: object) -> None:
    grounder = g.Grounder(_known())

    [story] = grounder.stories("f", [_story(article_id=written)])

    assert story["article_id"] == 12 and story["url"] == "https://example.com/a/12"


def test_the_source_shown_is_the_cited_articles_not_the_one_the_model_wrote() -> None:
    grounder = g.Grounder(_known())

    [story] = grounder.stories("f", [_story(article_id=7, source="CISA")])  # artikel 7: Bleeping

    assert story["source"] == "BleepingComputer"
    assert grounder.dropped == []  # "CISA" ada di masukan, jadi bukan karangan: hanya salah tempel


def test_a_source_label_that_is_not_in_the_input_at_all_is_listed_but_the_story_stays() -> None:
    grounder = g.Grounder(_known())

    [story] = grounder.stories("recap.top_stories", [_story(source="Reuters")])

    assert story["source"] == "CISA"
    assert _dropped(grounder) == [("recap.top_stories.source", "Reuters", g.NOT_IN_INPUT)]


def test_a_missing_or_blank_source_label_is_filled_in_without_a_record() -> None:
    grounder = g.Grounder(_known())

    stories = grounder.stories("f", [_story(source=""), {"article_id": 12, "title": "t"}])

    assert [s["source"] for s in stories] == ["CISA", "CISA"]
    assert grounder.dropped == []


def test_an_item_that_is_not_an_object_is_a_malformed_story() -> None:
    grounder = g.Grounder(_known())

    assert grounder.stories("f", ["a plain string", 3, _story()]) != []
    assert [(v, r) for _, v, r in _dropped(grounder)] == [
        ("a plain string", g.MALFORMED),
        ("3", g.MALFORMED),
    ]


def test_the_story_input_is_not_modified() -> None:
    grounder = g.Grounder(_known())
    stories = [_story(), _story(article_id=999)]
    before = copy.deepcopy(stories)

    grounder.stories("f", stories)

    assert stories == before


# --- teks bebas ---------------------------------------------------------------------------------


def test_an_invented_cve_id_in_free_text_is_replaced_by_a_visible_marker_and_listed() -> None:
    grounder = g.Grounder(_known())

    out = grounder.free_text("recap.summary", "Apt41 used CVE-2026-0001 and CVE-2026-9999 widely.")

    assert out == "Apt41 used CVE-2026-0001 and [unverified CVE] widely."
    assert _dropped(grounder) == [("recap.summary", "CVE-2026-9999", g.NOT_IN_INPUT)]


def test_a_real_id_in_free_text_is_left_exactly_as_written() -> None:
    grounder = g.Grounder(_known())

    text = f"see cve 2026 0001 and CVE{NB_HYPHEN}2026{NB_HYPHEN}0002"

    out = grounder.free_text("f", text)

    assert out == text
    assert grounder.dropped == []


def test_a_variant_of_an_invented_id_in_free_text_is_replaced_and_listed_canonically() -> None:
    grounder = g.Grounder(_known())

    out = grounder.free_text("f", "exploits cve 2026 9999 now")

    assert out == "exploits [unverified CVE] now"
    assert _dropped(grounder) == [("f", "CVE-2026-9999", g.NOT_IN_INPUT)]


def test_the_same_invented_id_twice_in_one_field_is_replaced_twice_and_listed_once() -> None:
    grounder = g.Grounder(_known())

    out = grounder.free_text("f", "CVE-2026-9999 here and CVE-2026-9999 there")

    assert out == "[unverified CVE] here and [unverified CVE] there"
    assert len(grounder.dropped) == 1


def test_the_marker_can_be_replaced_for_another_language() -> None:
    grounder = g.Grounder(_known(), cve_marker="[CVE belum diverifikasi]")

    assert grounder.free_text("f", "CVE-2026-9999") == "[CVE belum diverifikasi]"


def test_free_text_walks_nested_output_and_names_the_path_of_each_hit() -> None:
    grounder = g.Grounder(_known())
    output = {
        "headline": "Week of CVE-2026-8888",
        "recap": {
            "summary": "ok",
            "top_stories": [
                {"title": "fine", "why_it_matters": "x"},
                {"title": "t", "why_it_matters": "chains CVE-2026-9999"},
            ],
        },
        "forecast": {"watch_items": ["CVE-2026-0001 patching", "CVE-2026-7777 spread"]},
    }

    out = grounder.free_text("", output)

    assert out["recap"]["top_stories"][1]["why_it_matters"] == "chains [unverified CVE]"
    assert out["forecast"]["watch_items"] == ["CVE-2026-0001 patching", "[unverified CVE] spread"]
    assert out["headline"] == "Week of [unverified CVE]"
    assert sorted(f for f, _, _ in _dropped(grounder)) == [
        "forecast.watch_items[1]",
        "headline",
        "recap.top_stories[1].why_it_matters",
    ]


def test_free_text_does_not_touch_urls_numbers_or_nulls_and_does_not_mutate_its_input() -> None:
    grounder = g.Grounder(_known())
    output = {
        "story": {"url": "https://x.example/CVE-2026-9999-writeup", "article_id": 12, "n": None},
        "flag": True,
    }
    before = copy.deepcopy(output)

    out = grounder.free_text("recap", output)

    assert out == before
    assert output == before
    assert out is not output
    assert grounder.dropped == []


def test_structured_filtering_first_means_an_id_dropped_from_a_list_is_not_listed_twice() -> None:
    """Urutan yang dipakai pemanggil: bagian terstruktur dulu, lalu teks bebas atas seluruh
    keluaran. Id karangan di `notable_cves` sudah keluar dari daftar, jadi pemindaian teks tidak
    menemukannya lagi dan tidak mencatat ulang atau menggantinya dengan penanda di daftar itu."""
    grounder = g.Grounder(_known())
    output = {
        "recap": {"notable_cves": ["CVE-2026-0001", "CVE-2026-9999"], "summary": "CVE-2026-9999"}
    }

    output["recap"]["notable_cves"] = grounder.cve_list(
        "recap.notable_cves", output["recap"]["notable_cves"]
    )
    cleaned = grounder.free_text("", output)

    assert cleaned["recap"]["notable_cves"] == ["CVE-2026-0001"]
    assert cleaned["recap"]["summary"] == "[unverified CVE]"
    assert _dropped(grounder) == [
        ("recap.notable_cves", "CVE-2026-9999", g.NOT_IN_INPUT),
        ("recap.summary", "CVE-2026-9999", g.NOT_IN_INPUT),
    ]


def test_an_over_long_value_is_clipped_in_the_record() -> None:
    grounder = g.Grounder(_known())

    grounder.name_list("f", ["x" * 5000], "threat_actors")

    assert len(grounder.dropped[0].value) <= 200


def test_an_empty_report_has_zero_count() -> None:
    assert g.Grounder(_known()).report() == {"dropped": [], "count": 0}


# --- modul bersama: tidak bergantung pada recap -------------------------------------------------


def test_the_shared_module_imports_nothing_but_the_standard_library() -> None:
    """PR 8 memakainya untuk ringkasan newsletter. Kalau modul ini mengimpor service recap (atau
    apa pun dari `cti_*`), newsletter ikut menarik recap, dan siklus impor tinggal menunggu."""
    source = pathlib.Path(g.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])

    assert imported, "test ini harus benar-benar menemukan impornya"
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}
    assert not {name for name in imported if name.startswith(("cti_", "sqlalchemy"))}
