"""`cti_api.services.runtime_secrets` -- fungsi murni (ROADMAP #23, PR 2).

Dua hal yang dikunci di sini:
- `validate_llm_url`: penjaga `llm.url` dari halaman admin. `llm.url` menerima key LLM beserta
  seluruh teks artikel, jadi di luar `dev` hanya https ke host di allowlist yang lolos, dan
  pesan penolakan TIDAK PERNAH memuat URL-nya (bisa berisi `user:pass@`);
- `mask_last4`: empat karakter terakhir buat tampilan "key ini yang mana", hanya kalau key cukup
  panjang sehingga empat karakter itu tidak membocorkan porsi besar key.

Tes router (alur HTTP, probe, audit) ada di `tests/integration/test_secrets_router*.py`.
"""

from __future__ import annotations

import pytest
from cti_api.services.runtime_secrets import mask_last4, validate_llm_url

ALLOWED = "gw.example.com"
NON_DEV = ["staging", "prod"]


# --- mask_last4 -------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "a", "short", "x" * 11])
def test_mask_last4_returns_none_for_values_shorter_than_12(value: str) -> None:
    assert mask_last4(value) is None


def test_mask_last4_returns_the_last_four_characters_at_exactly_12() -> None:
    assert mask_last4("abcdefgh1234") == "1234"


def test_mask_last4_returns_the_last_four_characters_of_a_long_value() -> None:
    assert mask_last4("sk-test-aaaaaa-ZZ99") == "ZZ99"


# --- validate_llm_url: bentuk dasar (berlaku di semua environment) ----------------------------


@pytest.mark.parametrize("environment", ["dev", *NON_DEV])
def test_an_empty_url_is_valid_and_means_the_vendor_default(environment: str) -> None:
    assert validate_llm_url("", environment=environment, allowed_hosts="") == ""


@pytest.mark.parametrize("environment", ["dev", *NON_DEV])
def test_a_whitespace_only_url_is_stripped_to_empty(environment: str) -> None:
    assert validate_llm_url("  \t ", environment=environment, allowed_hosts="") == ""


@pytest.mark.parametrize("environment", ["dev", *NON_DEV])
def test_the_returned_url_is_stripped_and_otherwise_untouched(environment: str) -> None:
    url = f"  https://{ALLOWED}/v1/  \n"

    result = validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED)

    assert result == f"https://{ALLOWED}/v1/"


@pytest.mark.parametrize("environment", ["dev", *NON_DEV])
@pytest.mark.parametrize(
    "url",
    [
        f"https://user:s3cretpass@{ALLOWED}/v1",
        f"https://user@{ALLOWED}/v1",
        f"http://:s3cretpass@{ALLOWED}/v1",
        # host "betulan" ada di allowlist, tapi yang diterima koneksi adalah evil.test
        f"https://{ALLOWED}@evil.test/v1",
    ],
)
def test_a_url_with_userinfo_is_rejected_everywhere(environment: str, url: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED)


@pytest.mark.parametrize("environment", ["dev", *NON_DEV])
@pytest.mark.parametrize("url", ["https://", "https:///v1", "just-a-path", f"{ALLOWED}/v1", "/v1"])
def test_a_url_without_a_host_is_rejected_everywhere(environment: str, url: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED)


@pytest.mark.parametrize("environment", ["dev", *NON_DEV])
@pytest.mark.parametrize(
    "url", [f"ftp://{ALLOWED}/v1", f"ws://{ALLOWED}/v1", f"gopher://{ALLOWED}"]
)
def test_a_scheme_other_than_http_or_https_is_rejected_everywhere(
    environment: str, url: str
) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED)


@pytest.mark.parametrize("environment", ["dev", *NON_DEV])
@pytest.mark.parametrize(
    "url",
    [
        "https://user:s3cretpass@gw.example.com/v1",
        "ftp://gw.example.com/v1",
        "https:///v1?token=s3cretpass",
    ],
)
def test_the_rejection_message_never_contains_the_url(environment: str, url: str) -> None:
    """URL bisa membawa `user:pass@` atau token di query; pesan error ikut ke response dan log."""
    with pytest.raises(ValueError) as excinfo:
        validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED)

    message = str(excinfo.value)
    assert message  # alasan harus ada, bukan ValueError kosong
    assert url not in message
    assert "s3cretpass" not in message


@pytest.mark.parametrize("environment", NON_DEV)
def test_the_allowlist_rejection_message_never_contains_the_url_either(environment: str) -> None:
    url = "https://other.example.com/v1?token=s3cretpass"

    with pytest.raises(ValueError) as excinfo:
        validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED)

    message = str(excinfo.value)
    assert message
    assert url not in message
    assert "s3cretpass" not in message


# --- validate_llm_url: dev --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:20128/v1",
        "http://9router:20128/v1",
        "https://gw.anything.example/v1",
        "http://10.0.0.5/v1",
    ],
)
def test_dev_accepts_http_and_https_to_any_host(url: str) -> None:
    assert validate_llm_url(url, environment="dev", allowed_hosts="") == url


def test_dev_ignores_the_allowlist() -> None:
    url = "https://not-listed.example.com/v1"

    assert validate_llm_url(url, environment="dev", allowed_hosts=ALLOWED) == url


# --- validate_llm_url: staging dan prod -------------------------------------------------------


@pytest.mark.parametrize("environment", NON_DEV)
def test_non_dev_accepts_https_to_an_allowlisted_host(environment: str) -> None:
    url = f"https://{ALLOWED}/v1"

    assert validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED) == url


@pytest.mark.parametrize("environment", NON_DEV)
def test_non_dev_rejects_http_even_for_an_allowlisted_host(environment: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(f"http://{ALLOWED}/v1", environment=environment, allowed_hosts=ALLOWED)


@pytest.mark.parametrize("environment", NON_DEV)
def test_non_dev_rejects_a_host_that_is_not_in_the_allowlist(environment: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(
            "https://other.example.com/v1", environment=environment, allowed_hosts=ALLOWED
        )


@pytest.mark.parametrize("environment", NON_DEV)
def test_non_dev_with_an_empty_allowlist_rejects_every_non_empty_url(environment: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(f"https://{ALLOWED}/v1", environment=environment, allowed_hosts="")


@pytest.mark.parametrize("environment", NON_DEV)
@pytest.mark.parametrize("allowed", [" , ", ",,", "   "])
def test_an_allowlist_with_only_separators_allows_nothing(environment: str, allowed: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(f"https://{ALLOWED}/v1", environment=environment, allowed_hosts=allowed)


@pytest.mark.parametrize("environment", NON_DEV)
@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://GW.Example.COM/v1", "gw.example.com"),
        ("https://gw.example.com/v1", "GW.EXAMPLE.COM"),
    ],
)
def test_the_host_match_is_case_insensitive(environment: str, url: str, allowed: str) -> None:
    assert validate_llm_url(url, environment=environment, allowed_hosts=allowed) == url


@pytest.mark.parametrize("environment", NON_DEV)
def test_an_explicit_443_port_is_accepted_and_the_host_still_matches(environment: str) -> None:
    url = f"https://{ALLOWED}:443/v1"

    assert validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED) == url


@pytest.mark.parametrize("environment", NON_DEV)
@pytest.mark.parametrize("port", ["8443", "80", "0", "99999"])
def test_a_port_other_than_443_is_rejected_outside_dev(environment: str, port: str) -> None:
    """Allowlist-nya hostname saja; tanpa ini `allowed.example.com:8443` (layanan lain di host yang
    sama) lolos, dan port di luar rentang membuat parser URL melempar."""
    with pytest.raises(ValueError):
        validate_llm_url(
            f"https://{ALLOWED}:{port}/v1", environment=environment, allowed_hosts=ALLOWED
        )


def test_any_port_is_fine_in_dev() -> None:
    url = "http://localhost:20128/v1"

    assert validate_llm_url(url, environment="dev", allowed_hosts="") == url


@pytest.mark.parametrize("environment", NON_DEV)
def test_the_allowlist_is_comma_separated_and_spaces_are_stripped(environment: str) -> None:
    allowed = "  first.example.com ,  gw.example.com  ,third.example.com "
    url = "https://gw.example.com/v1"

    assert validate_llm_url(url, environment=environment, allowed_hosts=allowed) == url


@pytest.mark.parametrize("environment", NON_DEV)
@pytest.mark.parametrize(
    "url",
    [
        f"https://{ALLOWED}.evil.test/v1",  # allowlist sebagai prefiks host
        f"https://evil{ALLOWED}/v1",  # allowlist sebagai sufiks host
        f"https://sub.{ALLOWED}/v1",  # subdomain bukan host yang sama
        f"https://evil.test/{ALLOWED}",  # allowlist hanya ada di path
        f"https://evil.test/v1?host={ALLOWED}",  # allowlist hanya ada di query
    ],
)
def test_lookalike_hosts_do_not_pass_the_allowlist(environment: str, url: str) -> None:
    with pytest.raises(ValueError):
        validate_llm_url(url, environment=environment, allowed_hosts=ALLOWED)
