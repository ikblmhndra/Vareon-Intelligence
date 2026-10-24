"""Prompt classify: tanpa indentasi sia-sia, tanpa echo `title`, ada contoh batas."""

from __future__ import annotations

from cti_enrich.stages.classify import _PROMPT, PROMPT_VERSION

_OLD_PROMPT_VERSION = "8194393f"


def test_no_line_indented_with_eight_spaces() -> None:
    assert not [ln for ln in _PROMPT.splitlines() if ln.startswith(" " * 8)]


def test_json_format_block_has_no_title_key() -> None:
    fmt = _PROMPT.split("Respond strictly in the following JSON format:")[1]
    assert '"title"' not in fmt
    assert '"related_cyber"' in fmt
    assert '"confidence"' in fmt


def test_prompt_has_six_boundary_examples() -> None:
    examples = _PROMPT.split("Boundary examples")[1].split("Respond strictly")[0]
    lines = [ln for ln in examples.splitlines() if ln.startswith('- "')]
    assert len(lines) == 6
    assert sum('"related_cyber": false' in ln for ln in lines) == 4
    assert sum('"related_cyber": true' in ln for ln in lines) == 2


def test_prompt_version_changed() -> None:
    assert PROMPT_VERSION != _OLD_PROMPT_VERSION
