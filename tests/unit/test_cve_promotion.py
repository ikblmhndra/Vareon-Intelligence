"""Aturan pencocokan mirror -> techstack (`cti_core.cve_promotion.choose`), murni tanpa DB:
kekhususan, tie-break, entri bertarget tidak dicocokkan lewat teks, gate teks untuk entri tanpa
target, dan satu pilihan per client. Jalur DB ada di `tests/integration/test_cve_promotion.py`."""

from __future__ import annotations

from cti_core.cve_promotion import (
    SPEC_FAMILY,
    SPEC_TEXT,
    SPEC_VENDOR,
    EntryView,
    RecordView,
    choose,
)


def entry(
    i: int, name: str, client: str = "acme", *, v: set[int] = (), f: set[int] = ()
) -> EntryView:
    return EntryView(i, client, name, frozenset(v), frozenset(f))


FORTIOS = RecordView(
    "CVE-2026-0001",
    summary="FortiOS buffer overflow",
    vendor_ids=frozenset({1}),
    family_ids=frozenset({10, 11}),
    texts=("Fortinet", "FortiOS", "fortios"),
)


def test_family_target_beats_vendor_target_beats_text() -> None:
    entries = [
        entry(1, "a-text"),  # tanpa target, teks tak menyebutnya
        entry(2, "fortinet", v={1}),
        entry(3, "fortigate", f={10}),
        entry(
            4,
            "fortios",
        ),  # entri teks yang cocok
    ]
    got = choose(FORTIOS, entries)
    assert got["acme"].entry.name == "fortigate" and got["acme"].specificity == SPEC_FAMILY
    assert got["acme"].label == "family"


def test_vendor_target_wins_over_text_match() -> None:
    got = choose(FORTIOS, [entry(1, "fortios"), entry(2, "zzz-vendor", v={1})])
    assert (got["acme"].entry.name, got["acme"].label) == ("zzz-vendor", "vendor")


def test_text_entry_uses_the_legacy_whole_word_gate() -> None:
    got = choose(FORTIOS, [entry(1, "fortios")])
    assert got["acme"].specificity == SPEC_TEXT
    assert choose(FORTIOS, [entry(1, "forti")]) == {}  # bukan kata utuh
    assert choose(FORTIOS, [entry(1, "juniper")]) == {}


def test_text_gate_falls_back_to_summary_only_without_usable_products() -> None:
    no_products = RecordView("CVE-2026-0002", summary="Grafana XSS in dashboards")
    assert choose(no_products, [entry(1, "grafana")])["acme"].specificity == SPEC_TEXT
    junk = RecordView("CVE-2026-0003", summary="Grafana XSS", texts=("n/a",))
    assert choose(junk, [entry(1, "grafana")])["acme"].specificity == SPEC_TEXT
    other = RecordView("CVE-2026-0004", summary="mentions grafana", texts=("Zabbix",))
    assert choose(other, [entry(1, "grafana")]) == {}  # produk terdampak lain: bukan CVE-nya


def test_entry_with_targets_never_matches_by_name_text() -> None:
    # nama "fortios" ada di teks CVE, tapi targetnya keluarga lain: tidak cocok
    assert choose(FORTIOS, [entry(1, "fortios", f={99})]) == {}
    assert choose(FORTIOS, [entry(1, "fortios", v={99})]) == {}


def test_ties_break_alphabetically_then_by_entry_id() -> None:
    got = choose(FORTIOS, [entry(5, "bravo", f={10}), entry(6, "alpha", f={11})])
    assert got["acme"].entry.name == "alpha"
    got = choose(FORTIOS, [entry(9, "same", f={10}), entry(3, "same", f={11})])
    assert got["acme"].entry.entry_id == 3


def test_one_choice_per_client_and_unmatched_clients_are_absent() -> None:
    got = choose(
        FORTIOS,
        [
            entry(1, "fortinet", "acme", v={1}),
            entry(2, "fortigate", "acme", f={10}),
            entry(3, "fortinet", "globex", v={1}),
            entry(4, "juniper", "initech", v={77}),
        ],
    )
    assert set(got) == {"acme", "globex"}
    assert got["acme"].entry.name == "fortigate" and got["globex"].entry.name == "fortinet"


def test_entry_with_several_targets_matches_through_any_of_them() -> None:
    junos = entry(1, "junos", f={100, 101, 11})  # satu dari tiga keluarga ada di CVE
    assert choose(FORTIOS, [junos])["acme"].specificity == SPEC_FAMILY
    assert SPEC_VENDOR < SPEC_FAMILY and SPEC_TEXT < SPEC_VENDOR


def test_no_entries_or_no_match_gives_nothing() -> None:
    assert choose(FORTIOS, []) == {}
