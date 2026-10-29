"""Helper murni parameter TAXII 2.1 (P7b task 6): Accept, match[...], added_after."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from cti_api.routers.taxii import accepts_taxii, parse_added_after, parse_match

U1 = "6f0e1a52-6a43-4f0b-9b8e-2a7c1d9e4b10"
U2 = "11111111-2222-4333-8444-555555555555"


@pytest.mark.parametrize(
    ("accept", "expected"),
    [
        ("application/taxii+json;version=2.1", True),
        ("application/taxii+json", True),
        ("application/taxii+json; version=2.1", True),
        ("application/taxii+json;version=2.0", False),
        ("application/json", False),
        ("*/*", False),
        (None, False),
        ("text/html, application/taxii+json;version=2.1;q=0.9", True),
    ],
)
def test_accepts_taxii(accept: str | None, expected: bool) -> None:
    assert accepts_taxii(accept) is expected


def test_parse_match_defaults_and_unknown_ignored() -> None:
    m = parse_match({"match[foo]": "x", "other": "y"})
    assert m.ids is None and m.types is None and m.spec_versions is None
    assert m.version == "last"


def test_parse_match_comma_or() -> None:
    m = parse_match(
        {
            "match[id]": f"indicator--{U1},indicator--{U2}",
            "match[type]": "indicator,malware",
            "match[spec_version]": "2.0,2.1",
            "match[version]": "all",
        }
    )
    assert m.ids == {uuid.UUID(U1), uuid.UUID(U2)}
    assert m.types == {"indicator", "malware"}
    assert m.spec_versions == {"2.0", "2.1"}
    assert m.version == "all"


def test_parse_match_version_timestamp() -> None:
    m = parse_match({"match[version]": "2026-10-29T10:00:00.000Z"})
    assert m.version == datetime(2026, 10, 29, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    "query",
    [
        {"match[id]": "indicator--bad"},
        {"match[id]": U1},
        {"match[version]": "newest"},
        {"match[version]": "0001-01-01T00:00:00+01:00"},
    ],
)
def test_parse_match_malformed(query: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        parse_match(query)


def test_parse_added_after() -> None:
    assert parse_added_after(None) is None
    assert parse_added_after("2026-10-29T10:00:00.123Z") == datetime(
        2026, 10, 29, 10, 0, 0, 123000, tzinfo=UTC
    )


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-29T10:00:00",
        "garbage",
        "",
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
    ],
)
def test_parse_added_after_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        parse_added_after(value)
