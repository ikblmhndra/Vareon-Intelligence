"""`check_c2_hit`: feed C2 (`threat_feed_entries`) disimpan kanonik sejak 0.8.6, jadi nilai
ip/domain artikel (bisa defanged / huruf besar) harus dikanonikkan dulu sebelum diirisan."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cti_enrich.stages import extract_iocs as stage


@pytest.fixture(autouse=True)
def _feed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        stage, "_get_c2_feed", lambda session: {"ips": {"1.2.3.4"}, "domains": {"evil.com"}}
    )


def test_defanged_mixed_case_domain_hits_feed() -> None:
    assert stage.check_c2_hit({"domains": ["Evil[.]COM"]}, MagicMock()) is True


def test_defanged_ip_hits_feed() -> None:
    assert stage.check_c2_hit({"ips": ["1[.]2[.]3[.]4"]}, MagicMock()) is True


def test_unrelated_values_miss() -> None:
    assert stage.check_c2_hit({"domains": ["good.com"], "ips": ["5.6.7.8"]}, MagicMock()) is False
