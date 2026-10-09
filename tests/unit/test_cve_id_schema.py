"""`cve_id` di request API: dinormalisasi (huruf besar, spasi dibuang) dan divalidasi.

Tanpa ini `cve-2026-1234` jadi baris FP/ticket tersendiri yang tak pernah ketemu oleh query
(semua pencocokan `cve_id` itu persis), dan id yang terlalu panjang untuk kolom `String(20)`
berujung 500 dari database."""

from __future__ import annotations

import pytest
from cti_api.schemas.cve import (
    BulkAcknowledgeBody,
    BulkFalsePositiveBody,
    DraftEmailBody,
    normalize_cve_id,
)
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CVE-2026-1234", "CVE-2026-1234"),
        ("cve-2026-1234", "CVE-2026-1234"),
        ("  Cve-2026-12345\n", "CVE-2026-12345"),
        ("CVE-1999-0001", "CVE-1999-0001"),
        ("CVE-2026-1234567", "CVE-2026-1234567"),
    ],
)
def test_normalize_cve_id_canonicalizes(raw: str, expected: str) -> None:
    assert normalize_cve_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "CVE",
        "CVE-2026",
        "CVE-2026-123",  # urutan minimal 4 digit
        "CVE-26-1234",
        "CVE-2026-1234-5",
        "CVE-2026-1234 extra",
        "xCVE-2026-1234",
        "CVE-2026-123456789012",  # 21 karakter: tidak muat di kolom String(20)
        "CVE-\uff12\uff10\uff12\uff16-1234",  # digit fullwidth bukan CVE ID
        "CVE-2026-\uff11\uff12\uff13\uff14",
    ],
)
def test_normalize_cve_id_rejects_malformed(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_cve_id(raw)


@pytest.mark.parametrize("body", [BulkFalsePositiveBody, DraftEmailBody])
def test_id_lists_in_request_bodies_are_normalized(body: type) -> None:
    assert body(cve_ids=["cve-2026-1234", " CVE-2026-0001 "]).cve_ids == [
        "CVE-2026-1234",
        "CVE-2026-0001",
    ]


def test_bulk_acknowledge_body_normalizes_ids() -> None:
    body = BulkAcknowledgeBody(cve_ids=["cve-2026-1234"])
    assert body.cve_ids == ["CVE-2026-1234"]


@pytest.mark.parametrize("body", [BulkFalsePositiveBody, DraftEmailBody])
def test_one_malformed_id_rejects_the_whole_list(body: type) -> None:
    with pytest.raises(ValidationError):
        body(cve_ids=["CVE-2026-1234", "nope"])
