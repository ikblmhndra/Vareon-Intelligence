import datetime
import hashlib
from types import SimpleNamespace

import pytest
from cti_api.machine_auth import generate_token, hash_token, require_token, token_status
from cti_core.indicator.marking import tlp_allowed

NOW = datetime.datetime(2026, 10, 29, tzinfo=datetime.UTC)


def test_tlp_allowed():
    assert tlp_allowed("clear") == ("clear",)
    assert tlp_allowed("amber") == ("clear", "green", "amber")
    assert len(tlp_allowed("red")) == 5
    with pytest.raises(ValueError):
        tlp_allowed("x")


def test_generate_token_format():
    a, b = generate_token(), generate_token()
    assert a.startswith("vrn_") and len(a) >= 40
    assert a != b


def test_hash_token_is_sha256_hex():
    assert hash_token("vrn_abc") == hashlib.sha256(b"vrn_abc").hexdigest()


def test_token_status_precedence():
    past = NOW - datetime.timedelta(days=1)
    mk = lambda **kw: SimpleNamespace(expires_at=None, revoked_at=None, **kw)  # noqa: E731
    assert token_status(mk(), NOW) == "active"
    assert token_status(SimpleNamespace(expires_at=past, revoked_at=None), NOW) == "expired"
    assert token_status(SimpleNamespace(expires_at=past, revoked_at=past), NOW) == "revoked"


def test_require_token_unknown_scope_raises():
    with pytest.raises(ValueError):
        require_token("nope:read")
    assert require_token("indicators:read").scope == "indicators:read"  # type: ignore[attr-defined]
