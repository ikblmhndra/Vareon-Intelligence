"""Marking TLP 2.0 dan PAP. Urutan tuple = dari paling longgar ke paling ketat, jadi "lebih ketat"
cukup membandingkan indeks. Marking tidak pernah turun otomatis (spec P7a 3.2/3.4)."""

from typing import Literal

Tlp = Literal["clear", "green", "amber", "amber+strict", "red"]
Pap = Literal["clear", "green", "amber", "red"]

TLP_LEVELS: tuple[Tlp, ...] = ("clear", "green", "amber", "amber+strict", "red")
PAP_LEVELS: tuple[Pap, ...] = ("clear", "green", "amber", "red")


def tlp_allowed(max_tlp: str) -> tuple[Tlp, ...]:
    """TLP dari `clear` sampai `max_tlp` (inklusif); nilai di luar `TLP_LEVELS` -> `ValueError`."""
    return TLP_LEVELS[: TLP_LEVELS.index(_check(max_tlp, TLP_LEVELS)) + 1]


def stricter_tlp(a: str, b: str) -> Tlp:
    """TLP yang lebih ketat dari dua nilai; nilai di luar `TLP_LEVELS` -> `ValueError`."""
    return max((_check(a, TLP_LEVELS), _check(b, TLP_LEVELS)), key=TLP_LEVELS.index)


def stricter_pap(a: str, b: str) -> Pap:
    """PAP yang lebih ketat dari dua nilai; nilai di luar `PAP_LEVELS` -> `ValueError`."""
    return max((_check(a, PAP_LEVELS), _check(b, PAP_LEVELS)), key=PAP_LEVELS.index)


def _check[T: str](value: str, levels: tuple[T, ...]) -> T:
    for level in levels:
        if level == value:
            return level
    raise ValueError(f"marking tidak dikenal: {value!r}")
