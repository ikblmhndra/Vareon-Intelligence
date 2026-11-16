"""Kursor daftar entitas (spec 4.7, C6): bentuk `name` `[name_key, id]` tetap sama supaya kursor
lama jalan, bentuk `mentions` `[n30, name_key, id]`; bentuk yang salah untuk `sort` -> ValueError
(router -> 422)."""

from __future__ import annotations

import base64
import json

import pytest
from cti_api.services.entities import decode_cursor, encode_cursor


def _raw(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def test_name_cursor_round_trip_and_legacy_shape() -> None:
    cur = encode_cursor("ärger", 7)
    assert cur == _raw(["ärger", 7])  # kursor lama (sebelum C6) persis sama
    assert decode_cursor(cur) == (None, "ärger", 7)
    assert decode_cursor(cur, sort="name") == (None, "ärger", 7)


def test_mentions_cursor_round_trip() -> None:
    cur = encode_cursor("apt", 9, count=3)
    assert decode_cursor(cur, sort="mentions") == (3, "apt", 9)
    assert decode_cursor(encode_cursor("apt", 9, count=0), sort="mentions") == (0, "apt", 9)


def test_wrong_shape_for_sort_raises() -> None:
    with pytest.raises(ValueError):
        decode_cursor(encode_cursor("apt", 9), sort="mentions")
    with pytest.raises(ValueError):
        decode_cursor(encode_cursor("apt", 9, count=3), sort="name")


@pytest.mark.parametrize(
    "cursor",
    [
        "!!nope",
        _raw("apt"),
        _raw(["apt"]),
        _raw(["apt", 0]),
        _raw(["apt", "9"]),
        _raw([-1, "apt", 9]),
        _raw([True, "apt", 9]),
        _raw([1.5, "apt", 9]),
        _raw([3, 4, 9]),
    ],
)
def test_garbage_raises(cursor: str) -> None:
    for sort in ("name", "mentions"):
        with pytest.raises(ValueError):
            decode_cursor(cursor, sort=sort)  # type: ignore[arg-type]
