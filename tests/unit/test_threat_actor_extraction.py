"""Ekstraksi threat actor + peran negara -- QA staging 2026-10-01 (BUG-B2/D1/D4).

Yang dikunci di sini (logika murni, tanpa DB):
- nama grup TA di-escape sebelum jadi regex (paritas `nlp.py` lama): nama
  malpedia dengan `.`/`(`/`$` harus match literal, dan nama dengan kurung gak
  seimbang gak boleh bikin SETIAP artikel gagal di-enrich;
- bentuk nama yang disimpan (`Shinyhunters`) cocok dengan kriteria PIR lama;
- role `mentioned` = gabungan regex + victim + actor (= `mentioned_countries`
  lama), bukan sisa regex -- itu yang bikin Risk Matrix kosong.
"""

from __future__ import annotations

from cti_enrich.routing import RoutingInput, route, threat_actor_names
from cti_enrich.stages.classify import ClassifyResult
from cti_enrich.stages.persist import _country_roles
from cti_enrich.stages.score import ScoreResult, score_with_lists


def _score_title(title: str, groups: list[str], people: list[str] | None = None) -> ScoreResult:
    # body "" -> tanpa NER (spaCy gak perlu); judul tanpa CVE -> tanpa HTTP MITRE
    return score_with_lists(
        title, "", techstack=[], group_list=groups, apac_people_list=people or []
    )


def test_group_from_title_becomes_a_stored_threat_actor() -> None:
    groups = ["lazarus group", "shinyhunters", "star blizzard"]
    # P4: nama satu kata dari `threat_actor_groups` butuh kata konteks (aturan tier 1), jadi
    # "members" saja tidak cukup; "hackers" ditambahkan di judul.
    result = _score_title("FBI tells ShinyHunters hackers to turn themselves in", groups)

    assert result.mentioned_group == ["shinyhunters"]
    routed = route(
        RoutingInput(
            msg_data_base="",
            industries_impacted=["General"],
            mentioned_group=result.mentioned_group,
            mentioned_countries=result.mentioned_countries,
            mentioned_apac_people=result.mentioned_apac_people,
            cve_list_title=[],
            report_status=False,
            ot_status=False,
            related_tech_status=False,
            related_tech_cve_status=False,
            databreach_list=[],
            zero_day_list=[],
        )
    )
    # kriteria PIR staging "Monitor ShinyHunters" = ["Shinyhunters"]
    assert routed.threat_actors == ["Shinyhunters"]


def test_group_names_with_regex_characters_match_literally() -> None:
    groups = ["noname057(16)", "temp.periscope", "admin@338"]

    hit = _score_title("NoName057(16) DDoS hits Italian banks", groups)
    assert hit.mentioned_group == ["noname057(16)"]

    # `.` literal, bukan wildcard
    assert _score_title("tempXperiscope campaign", groups).mentioned_group == []
    assert _score_title("TEMP.Periscope returns", groups).mentioned_group == ["temp.periscope"]


def test_unbalanced_group_name_does_not_break_scoring() -> None:
    # nama kayak gini bisa masuk lewat UI `ta_groups`; dulu -> re.error di tiap artikel
    groups = ["apt (unbalanced", "shinyhunters"]
    # P4: "hackers" ditambahkan sebagai kata konteks, dan urutan = urutan kemunculan di teks.
    result = _score_title("ShinyHunters hackers leak, and apt (unbalanced too", groups)
    assert result.mentioned_group == ["shinyhunters", "apt (unbalanced"]


def test_threat_actor_names_dedupes_after_capitalize() -> None:
    assert threat_actor_names(["APT36", "apt36", "muddy\\-water"]) == ["Apt36", "Muddy-water"]


def test_mentioned_role_is_union_of_regex_victim_and_actor() -> None:
    classify = ClassifyResult(
        related_cyber=True,
        victim_countries=["United States"],
        actor_countries=["Russia"],
    )
    score = ScoreResult(mentioned_countries=["Germany", "United States"])

    roles = set(_country_roles(classify, score, is_global_branch=False))

    assert roles == {
        ("US", "victim"),
        ("RU", "actor"),
        ("DE", "mentioned"),
        ("US", "mentioned"),
        ("RU", "mentioned"),
    }


def test_mentioned_role_on_global_branch_comes_from_gpt_countries() -> None:
    """Cabang Global: regex kosong -> dulu `mentioned` SELALU kosong."""
    classify = ClassifyResult(related_cyber=True, victim_countries=["Indonesia"])

    roles = set(_country_roles(classify, ScoreResult(), is_global_branch=True))

    assert roles == {("ID", "victim"), ("ID", "mentioned")}


def test_regex_fallback_victims_are_also_mentioned() -> None:
    classify = ClassifyResult(related_cyber=True)  # GPT gak ngasih negara
    score = ScoreResult(mentioned_countries=["Japan"])

    roles = set(_country_roles(classify, score, is_global_branch=False))

    assert roles == {("JP", "victim"), ("JP", "mentioned")}
