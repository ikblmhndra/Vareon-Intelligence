"""Kursor keyset feed mesin (P7b): bulat-balik dan penolakan masukan cacat."""

from __future__ import annotations

import base64
import datetime

import pytest
from cti_api.services.feed import decode_cursor, encode_cursor

_TS = datetime.datetime(2026, 10, 29, 4, 0, 25, 542000, tzinfo=datetime.UTC)


def _b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode()


def test_cursor_round_trip() -> None:
    assert decode_cursor(encode_cursor(_TS, 42)) == (_TS, 42)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!!",
        _b64("x|1"),
        _b64("2026-10-29T00:00:00|1"),  # naive
        _b64("2026-10-29T00:00:00+00:00|abc"),
        _b64("2026-10-29T00:00:00+00:00|99999999999999999999999"),
        _b64("2026-10-29T00:00:00+00:00|0"),
        _b64("2026-10-29T00:00:00+00:00|9223372036854775808"),
        _b64("0001-01-01T00:00:00+01:00|1"),
    ],
)
def test_decode_cursor_rejects(cursor: str) -> None:
    with pytest.raises(ValueError):
        decode_cursor(cursor)
