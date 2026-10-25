"""Stage tier 1 + pencocok aktor di `score_with_lists` (P4, Task 6). Tanpa DB."""

from __future__ import annotations

import pytest
import structlog
from cti_core.attack_ttp import TechniqueCatalog
from cti_enrich.stages import tier1
from cti_enrich.stages.score import score_with_lists
from cti_enrich.stages.tier1 import Tier1Result, run_tier1
from cti_enrich.tier1.dictionary import build_dictionary


def _dictionary() -> object:
    return build_dictionary(
        groups=[("Lazarus Group", ["Hidden Cobra"]), ("Cobalt Group", [])],
        software=[("Cobalt Strike", "tool", []), ("LockBit", "malware", [])],
        ta_names=[],
        suppressed=[],
    )


def test_run_tier1_title_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tier1, "get_dictionary", lambda session: _dictionary())
    monkeypatch.setattr(tier1, "load_catalog", lambda session: TechniqueCatalog())

    result = run_tier1(
        session=None,  # type: ignore[arg-type]
        title="Lazarus Group hackers hit banks",
        text="",
        victim_name=None,
    )

    assert result.actors == ["Lazarus Group"]
    assert result.industries == ["Finance & Insurance"]
    assert set(result.audit()["versions"]) >= {"dictionary", "keyword_map", "industry"}  # type: ignore[call-overload]


def test_run_tier1_exception_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tier1, "get_dictionary", lambda session: _dictionary())
    monkeypatch.setattr(tier1, "load_catalog", lambda session: TechniqueCatalog())

    def boom(text: str, dictionary: object) -> list[object]:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tier1, "match_entities", boom)

    with structlog.testing.capture_logs() as logs:
        result = run_tier1(
            session=None,  # type: ignore[arg-type]
            title="Lazarus Group",
            text="body",
            victim_name=None,
        )

    assert result == Tier1Result.empty()
    assert any(entry["event"] == "tier1_failed" for entry in logs)


def _score(title: str, **kw: object):  # type: ignore[no-untyped-def]
    return score_with_lists(
        title, "", techstack=[], group_list=["cobalt", "lazarus group"], apac_people_list=[], **kw
    )


def test_score_with_lists_cobalt_strike() -> None:
    result = _score("Cobalt Strike beacon seen", non_actor_names=["cobalt strike"])
    assert result.mentioned_group == []


def test_score_with_lists_alias_canonical() -> None:
    dictionary = _dictionary()
    result = score_with_lists(
        "Hidden Cobra targets exchanges",
        "",
        techstack=[],
        group_list=[],
        apac_people_list=[],
        dictionary=dictionary,  # type: ignore[arg-type]
    )
    assert result.mentioned_group == ["lazarus group"]


def test_score_fallback_single_token_list_name_needs_no_context() -> None:
    # Ruling 10: monitor_x/tweet_alerts tanpa kamus; nama group_list bebas aturan konteks.
    result = score_with_lists(
        "Turla targets EU ministries",
        "",
        techstack=[],
        group_list=["turla"],
        apac_people_list=[],
    )
    assert "turla" in result.mentioned_group


def test_compiled_cache_is_bounded() -> None:
    from cti_enrich.tier1 import entities

    for i in range(10):
        entities.match_entities("x", build_dictionary([], [], [f"name{i}x"], []))
    assert len(entities._COMPILED) <= 4
