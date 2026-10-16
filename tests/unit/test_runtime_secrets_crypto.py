"""`cti_core.runtime_secrets.crypto` -- enkripsi at-rest field secret (MultiFernet, ROADMAP #23).

Yang dikunci: round-trip, token TIDAK memuat plaintext, rotasi kunci master tanpa migrasi data
(kunci pertama mengenkripsi, semua kunci mendekripsi), dan SEMUA kegagalan dekripsi (kunci salah,
token rusak, provider tertukar, isi bentuknya salah) berujung `SecretDecryptError` -- satu jenis
error yang bisa ditangkap overlay tanpa membocorkan apa pun.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator

import pytest
from cryptography.fernet import Fernet
from cti_core.config import get_settings
from cti_core.runtime_secrets.crypto import (
    SecretDecryptError,
    SecretsNotConfigured,
    decrypt_fields,
    encrypt_fields,
    generate_key,
    is_configured,
)

KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()
SECRET = "sk-test-aaaaaa"  # gitleaks:allow
FIELDS = {"api_key": SECRET}


# --- generate_key -----------------------------------------------------------------------------


def test_generate_key_returns_a_valid_fernet_key_as_str() -> None:
    key = generate_key()

    assert isinstance(key, str)
    Fernet(key.encode())  # tidak raise = bentuknya kunci Fernet yang sah


def test_generate_key_is_different_every_time() -> None:
    assert generate_key() != generate_key()


def test_a_generated_key_is_directly_usable() -> None:
    key = generate_key()

    token = encrypt_fields("nvd", FIELDS, keys=key)

    assert is_configured(key) is True
    assert decrypt_fields("nvd", token, keys=key) == FIELDS


# --- round trip -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "fields"),
    [
        ("llm", {"api_key": SECRET}),
        ("telegram", {"bot_token": "111:tg-test-aaaaaa"}),
        ("llm", {"api_key": SECRET, "model": "gpt-test"}),
    ],
)
def test_encrypt_then_decrypt_returns_the_same_fields(
    provider: str, fields: dict[str, str]
) -> None:
    token = encrypt_fields(provider, fields, keys=KEY_A)

    assert isinstance(token, bytes)
    assert decrypt_fields(provider, token, keys=KEY_A) == fields


def test_unicode_quotes_and_backslashes_survive_the_round_trip() -> None:
    awkward = "p\"a\\s's-" + chr(0x00E9) + chr(0x4E2D) + chr(0x1F511)
    token = encrypt_fields("nvd", {"api_key": awkward}, keys=KEY_A)

    assert decrypt_fields("nvd", token, keys=KEY_A) == {"api_key": awkward}


def test_the_token_does_not_contain_the_plaintext_value() -> None:
    token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    assert SECRET.encode() not in token
    assert b"api_key" not in token


# --- payload terikat ke provider DAN client_id --------------------------------------------------


def test_the_payload_binds_provider_client_id_and_fields_inside_the_ciphertext() -> None:
    """Pengikatan ada DI DALAM payload terotentikasi (bukan kolom DB di sampingnya): menukar token
    antar baris lewat SQL tidak lolos."""
    token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    payload = json.loads(Fernet(KEY_A.encode()).decrypt(token))

    assert payload == {"provider": "llm", "client_id": None, "fields": FIELDS}


def test_a_client_scoped_round_trip_returns_the_fields() -> None:
    token = encrypt_fields("llm", FIELDS, client_id="acme", keys=KEY_A)

    assert decrypt_fields("llm", token, client_id="acme", keys=KEY_A) == FIELDS


def test_a_token_encrypted_for_a_client_is_rejected_as_platform() -> None:
    token = encrypt_fields("llm", FIELDS, client_id="acme", keys=KEY_A)

    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", token, keys=KEY_A)


def test_a_platform_token_cannot_be_used_on_a_client_row() -> None:
    token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", token, client_id="acme", keys=KEY_A)


def test_a_token_encrypted_for_one_client_is_rejected_for_another() -> None:
    token = encrypt_fields("llm", FIELDS, client_id="acme", keys=KEY_A)

    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", token, client_id="globex", keys=KEY_A)


def test_the_client_mismatch_error_does_not_echo_the_secret() -> None:
    token = encrypt_fields("llm", FIELDS, client_id="acme", keys=KEY_A)

    with pytest.raises(SecretDecryptError) as excinfo:
        decrypt_fields("llm", token, keys=KEY_A)

    assert SECRET not in str(excinfo.value)


def test_a_payload_without_client_id_counts_as_platform() -> None:
    """Token tanpa kunci `client_id` (bentuk lama) = scope platform."""
    legacy = Fernet(KEY_A.encode()).encrypt(
        json.dumps({"provider": "llm", "fields": FIELDS}).encode()
    )

    assert decrypt_fields("llm", legacy, keys=KEY_A) == FIELDS
    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", legacy, client_id="acme", keys=KEY_A)


# --- is_configured / tanpa kunci master -------------------------------------------------------


def test_empty_keys_means_not_configured() -> None:
    assert is_configured("") is False


@pytest.mark.parametrize("keys", [KEY_A, f"{KEY_A},{KEY_B}"])
def test_one_or_more_keys_means_configured(keys: str) -> None:
    assert is_configured(keys) is True


def test_encrypt_without_a_master_key_is_refused() -> None:
    with pytest.raises(SecretsNotConfigured):
        encrypt_fields("llm", FIELDS, keys="")


def test_secrets_not_configured_is_a_runtime_error() -> None:
    assert issubclass(SecretsNotConfigured, RuntimeError)


# --- kunci dari Settings (keys=None) ----------------------------------------------------------


@pytest.fixture
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """`get_settings()` beneran (cache dibersihkan sebelum dan sesudah) dengan env minimal."""
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def test_without_explicit_keys_is_configured_reads_the_settings(
    settings_env: pytest.MonkeyPatch,
) -> None:
    settings_env.setenv("SECRETS_ENCRYPTION_KEYS", KEY_A)
    assert is_configured() is True

    get_settings.cache_clear()
    settings_env.setenv("SECRETS_ENCRYPTION_KEYS", "")
    assert is_configured() is False


def test_without_explicit_keys_encrypt_and_decrypt_use_the_settings_key(
    settings_env: pytest.MonkeyPatch,
) -> None:
    settings_env.setenv("SECRETS_ENCRYPTION_KEYS", KEY_A)

    token = encrypt_fields("llm", FIELDS)

    assert decrypt_fields("llm", token, keys=KEY_A) == FIELDS
    assert decrypt_fields("llm", token) == FIELDS


# --- rotasi kunci master ----------------------------------------------------------------------


def test_a_token_made_with_the_old_key_still_decrypts_after_the_key_is_rotated() -> None:
    old_token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    assert decrypt_fields("llm", old_token, keys=f"{KEY_B},{KEY_A}") == FIELDS


def test_the_first_key_encrypts_new_tokens() -> None:
    new_token = encrypt_fields("llm", FIELDS, keys=f"{KEY_B},{KEY_A}")

    assert decrypt_fields("llm", new_token, keys=KEY_B) == FIELDS
    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", new_token, keys=KEY_A)  # kunci lama saja tidak cukup lagi


def test_whitespace_around_the_commas_in_the_key_list_is_tolerated() -> None:
    old_token = encrypt_fields("llm", FIELDS, keys=KEY_A)
    spaced = f"  {KEY_B}  ,  {KEY_A}  "

    assert is_configured(spaced) is True
    assert decrypt_fields("llm", old_token, keys=spaced) == FIELDS
    new_token = encrypt_fields("llm", FIELDS, keys=spaced)
    assert decrypt_fields("llm", new_token, keys=KEY_B) == FIELDS


# --- kegagalan dekripsi -----------------------------------------------------------------------


def test_the_wrong_key_raises_decrypt_error() -> None:
    token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", token, keys=KEY_B)


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(lambda t: b"bukan-token-fernet", id="garbage"),
        pytest.param(lambda t: b"", id="empty"),
        pytest.param(lambda t: t[:-10], id="truncated"),
    ],
)
def test_a_damaged_token_raises_decrypt_error(mangle: Callable[[bytes], bytes]) -> None:
    token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", mangle(token), keys=KEY_A)


def test_a_token_encrypted_for_another_provider_is_rejected() -> None:
    """Baris `nvd` yang isinya token milik `llm` (salah salin / salah tulis) tidak boleh diam-diam
    dipakai sebagai key `nvd`."""
    token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    with pytest.raises(SecretDecryptError):
        decrypt_fields("nvd", token, keys=KEY_A)


def test_the_provider_mismatch_error_does_not_echo_the_secret() -> None:
    token = encrypt_fields("llm", FIELDS, keys=KEY_A)

    with pytest.raises(SecretDecryptError) as excinfo:
        decrypt_fields("nvd", token, keys=KEY_A)

    assert SECRET not in str(excinfo.value)


def _forged(plaintext: bytes) -> bytes:
    """Token Fernet SAH (kunci benar) yang isinya bukan `{"provider", "fields"}` yang benar."""
    return Fernet(KEY_A.encode()).encrypt(plaintext)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(json.dumps([1, 2, 3]), id="json-list"),
        pytest.param(json.dumps({"fields": FIELDS}), id="provider-missing"),
        pytest.param(json.dumps({"provider": "llm"}), id="fields-missing"),
        pytest.param(json.dumps({"provider": "llm", "fields": "oops"}), id="fields-not-a-dict"),
        pytest.param("bukan json sama sekali", id="not-json"),
    ],
)
def test_a_valid_token_with_a_malformed_payload_raises_decrypt_error(payload: str) -> None:
    with pytest.raises(SecretDecryptError):
        decrypt_fields("llm", _forged(payload.encode()), keys=KEY_A)


def test_the_error_types_are_distinct_so_callers_can_tell_them_apart() -> None:
    """Tanpa kunci master = konfigurasi (503 di API); dekripsi gagal = data/kunci salah."""
    assert not issubclass(SecretDecryptError, SecretsNotConfigured)
    assert not issubclass(SecretsNotConfigured, SecretDecryptError)
