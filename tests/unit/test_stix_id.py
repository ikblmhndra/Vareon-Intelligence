"""Rumus `indicator_uuid` dipaku: unik per (type, value) persis, tanpa normalisasi."""

from __future__ import annotations

import uuid

from cti_core.indicator.stix_id import indicator_uuid


def test_indicator_uuid_formula() -> None:
    assert indicator_uuid("ip", "1.2.3.4") == uuid.uuid5(uuid.NAMESPACE_DNS, "ip:1.2.3.4")


def test_indicator_uuid_is_case_and_whitespace_sensitive() -> None:
    assert indicator_uuid("url", "http://a/B") != indicator_uuid("url", "http://a/b")
    assert indicator_uuid("domain", "x.com ") != indicator_uuid("domain", "x.com")
