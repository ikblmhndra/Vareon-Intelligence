"""`make_dek`: potongan ringkasan 600 karakter (spec 5a 4.5)."""

from __future__ import annotations

from cti_enrich.stages.summarize import make_dek

ELL = chr(0x2026)


def test_make_dek_empty_is_none() -> None:
    assert make_dek("") is None
    assert make_dek(" \n\t ") is None


def test_make_dek_collapses_whitespace() -> None:
    assert make_dek("a \n\n b\t c") == "a b c"


def test_make_dek_short_text_unchanged() -> None:
    text = ("word " * 120).strip()
    assert len(text) == 599
    text = text + "x"
    assert len(text) == 600
    assert make_dek(text) == text


def test_make_dek_cuts_at_last_sentence_end() -> None:
    text = "Sentence one is here. " * 40
    out = make_dek(text)
    assert out is not None
    assert out.endswith(".")
    assert len(out) <= 600
    assert text.startswith(out + " ")


def test_make_dek_without_sentence_end_cuts_at_word_with_ellipsis() -> None:
    out = make_dek("word " * 300)
    assert out is not None
    assert out.endswith(ELL)
    assert not out.endswith(" " + ELL)
    assert len(out) <= 601
    early = "Short start. " + "word " * 300
    out2 = make_dek(early)
    assert out2 is not None
    assert out2.endswith(ELL)


def test_make_dek_never_exceeds_max_chars_plus_ellipsis() -> None:
    for text in ("Sentence one is here. " * 40, "word " * 300, "x" * 2000):
        for limit in (600, 250):
            out = make_dek(text, max_chars=limit)
            assert out is not None
            assert len(out) <= limit + 1


def test_make_dek_long_text_without_spaces() -> None:
    out = make_dek("x" * 2000)
    assert out is not None
    assert len(out) == 601
    assert out.endswith(ELL)
    assert make_dek("ab " + "x" * 2000) == "ab" + ELL
