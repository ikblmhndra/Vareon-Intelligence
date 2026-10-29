"""`indicator_uuid` harus identik dengan rumus ekspor STIX (`services/stix.py::_uuid5`)."""

from __future__ import annotations

import pytest
from cti_api.services import stix
from cti_core.indicator.stix_id import indicator_uuid


@pytest.mark.parametrize(
    ("t", "v"),
    [("ip", "1.2.3.4"), ("domain", "Example.COM "), ("url", "http://a/b\\c")],
)
def test_indicator_uuid_matches_stix_export(t: str, v: str) -> None:
    assert str(indicator_uuid(t, v)) == stix._uuid5(f"{t}:{v}")
