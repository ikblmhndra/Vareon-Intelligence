"""Skema body `POST /api/pir/preview`: batas `days` dan penolakan kunci kriteria asing."""

from __future__ import annotations

import pytest
from cti_api.schemas.pir import PIRPreviewIn
from pydantic import ValidationError


@pytest.mark.parametrize("days", [0, 366])
def test_days_bounds(days: int) -> None:
    with pytest.raises(ValidationError):
        PIRPreviewIn.model_validate({"criteria": {}, "days": days})
    assert PIRPreviewIn.model_validate({"criteria": {}, "days": 365}).days == 365


def test_unknown_criteria_key_rejected() -> None:
    # `extra="forbid"` supaya typo kunci tidak diam-diam menghasilkan hitungan tanpa filter.
    with pytest.raises(ValidationError):
        PIRPreviewIn.model_validate({"criteria": {"sectors": ["x"]}})
