"""Glosarium ringkasan Indonesia (`services/newsletter_glossary.py`) -- ROADMAP #22.

Yang dites BENTUKNYA, bukan pilihan katanya (itu keputusan analis): koreksi satu baris di glosarium
tidak boleh membuat prompt rusak, atau menaruh istilah yang sama di dua daftar sehingga model
menerima perintah yang bertentangan. Bahwa blok ini benar-benar masuk ke kedua prompt ringkasan
dites di `test_newsletter_summary_cache.py`."""

from __future__ import annotations

import pytest
from cti_api.services import newsletter_glossary as glossary


def _english_terms() -> list[str]:
    """Semua istilah Inggris, varian ` / ` dipecah, huruf kecil."""
    variants = [v for term, _ in glossary.TRANSLATIONS for v in term.split(" / ")]
    return [t.strip().lower() for t in (*variants, *glossary.KEEP_IN_ENGLISH)]


def test_no_english_term_is_listed_twice_or_in_both_lists() -> None:
    terms = _english_terms()
    assert len(terms) == len(set(terms)), (
        "istilah ganda atau ada di TRANSLATIONS dan KEEP_IN_ENGLISH"
    )


def test_a_translation_differs_from_its_term() -> None:
    """Padanan yang sama dengan istilahnya = istilah dibiarkan; tempatnya `KEEP_IN_ENGLISH`."""
    for english, indonesian in glossary.TRANSLATIONS:
        assert indonesian.strip().lower() != english.strip().lower(), english


def test_entries_are_one_clean_line_each() -> None:
    entries = [
        *(text for pair in glossary.TRANSLATIONS for text in pair),
        *glossary.KEEP_IN_ENGLISH,
        *glossary.KEEP_AS_WRITTEN,
    ]
    for entry in entries:
        assert entry == entry.strip() and entry, repr(entry)
        assert "\n" not in entry, repr(entry)


def test_the_indonesian_block_names_the_language_the_keep_rules_and_every_entry() -> None:
    block = glossary.language_instructions("id")

    assert "Indonesian (Bahasa Indonesia)" in block
    for category in glossary.KEEP_AS_WRITTEN:
        assert category in block
    for term in glossary.KEEP_IN_ENGLISH:
        assert term in block
    lines = block.splitlines()
    for english, indonesian in glossary.TRANSLATIONS:
        assert f"- {english}: {indonesian}" in lines


def test_the_english_block_only_names_the_language() -> None:
    block = glossary.language_instructions("en")

    assert "in English" in block
    assert "Indonesian" not in block
    assert "- " not in block  # tanpa glosarium
    assert "Keep the JSON keys exactly as shown" in block  # kunci JSON tetap Inggris


def test_an_unsupported_language_is_refused_instead_of_silently_falling_back() -> None:
    with pytest.raises(ValueError, match="unsupported summary language"):
        glossary.language_instructions("fr")  # type: ignore[arg-type]
