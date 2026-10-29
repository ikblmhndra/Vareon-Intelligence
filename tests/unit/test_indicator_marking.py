"""cti_core.indicator.marking -- urutan TLP 2.0 / PAP dan pemilihan yang lebih ketat."""

import pytest
from cti_core.indicator.marking import stricter_pap, stricter_tlp


def test_stricter_tlp() -> None:
    assert stricter_tlp("clear", "amber") == "amber"
    assert stricter_tlp("red", "green") == "red"
    assert stricter_tlp("amber", "amber+strict") == "amber+strict"


def test_stricter_pap() -> None:
    assert stricter_pap("green", "clear") == "green"


def test_unknown_marking_raises() -> None:
    with pytest.raises(ValueError):
        stricter_tlp("purple", "clear")
    with pytest.raises(ValueError):
        stricter_pap("clear", "purple")
