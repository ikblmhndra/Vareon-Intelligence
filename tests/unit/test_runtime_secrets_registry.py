"""`cti_core.runtime_secrets.registry` -- daftar tunggal provider + field yang boleh di-override
dari halaman admin (ROADMAP #23).

Yang dikunci: registry TIDAK PERNAH melenceng dari `Settings` (typo nama provider/field = override
yang diam-diam tidak berlaku, atau lebih parah, secret yang tidak ikut disamarkan di log), dan
`scrub_values` mencakup SEMUA provider -- termasuk x/otx/abuseipdb/virustotal yang dulu bolong di
`_scrub_secrets`.
"""

from __future__ import annotations

import dataclasses
import typing

import pytest
from cti_core.config import LlmSettings, NvdSettings, Settings
from cti_core.runtime_secrets.registry import (
    MIN_SCRUB_LEN,
    PROVIDERS,
    SecretProvider,
    UnknownProvider,
    get_provider,
    scrub_values,
    secret_field_names,
)

from tests.unit.runtime_secrets_helpers import (
    ENV_VALUES,
    JWT_SECRET,
    KEYS,
    NON_SECRET_VALUES,
    OTHER_KEYS,
    make_settings,
)

EXPECTED_ORDER = [
    "llm",
    "telegram",
    "graph",
    "nvd",
    "github",
    "twitter",
    "x",
    "otx",
    "abuseipdb",
    "virustotal",
]

# provider -> {nama field: apakah secret}. Chat/thread id Telegram, identitas Graph, rate dan
# timeout SENGAJA tidak ada: itu keputusan deployment, tetap di `.env`.
EXPECTED_FIELDS: dict[str, dict[str, bool]] = {
    "llm": {"api_key": True, "provider": False, "model": False, "url": False},
    "telegram": {"bot_token": True},
    "graph": {"client_secret": True},
    "nvd": {"api_key": True},
    "github": {"token": True},
    "twitter": {"api_key": True},
    "x": {"bearer_token": True},
    "otx": {"api_key": True},
    "abuseipdb": {"api_key": True},
    "virustotal": {"api_key": True},
}


def _group_model(provider: str) -> typing.Any:
    return Settings.model_fields[provider].annotation


def test_providers_come_in_the_documented_order() -> None:
    assert list(PROVIDERS) == EXPECTED_ORDER


@pytest.mark.parametrize("key", EXPECTED_ORDER)
def test_dict_key_matches_the_provider_key(key: str) -> None:
    assert PROVIDERS[key].key == key


@pytest.mark.parametrize("key", EXPECTED_ORDER)
def test_every_provider_key_is_a_settings_group(key: str) -> None:
    assert key in Settings.model_fields


@pytest.mark.parametrize("key", EXPECTED_ORDER)
def test_every_field_exists_in_its_settings_group(key: str) -> None:
    group_fields = _group_model(key).model_fields

    missing = [f.name for f in PROVIDERS[key].fields if f.name not in group_fields]

    assert missing == []


@pytest.mark.parametrize("key", EXPECTED_ORDER)
def test_secret_fields_are_plain_strings_in_settings(key: str) -> None:
    group_fields = _group_model(key).model_fields

    for field in PROVIDERS[key].fields:
        if field.secret:
            assert group_fields[field.name].annotation is str, f"{key}.{field.name}"


@pytest.mark.parametrize("key", EXPECTED_ORDER)
def test_registry_lists_exactly_the_agreed_fields(key: str) -> None:
    assert {f.name: f.secret for f in PROVIDERS[key].fields} == EXPECTED_FIELDS[key]


@pytest.mark.parametrize("key", EXPECTED_ORDER)
def test_every_provider_has_a_label_to_show_in_the_ui(key: str) -> None:
    assert PROVIDERS[key].label.strip()


def test_llm_provider_is_the_only_enum_and_matches_the_settings_literal() -> None:
    enums = {(p.key, f.name): f.choices for p in PROVIDERS.values() for f in p.fields if f.choices}

    literal_args = typing.get_args(LlmSettings.model_fields["provider"].annotation)
    assert enums == {("llm", "provider"): ("openai", "deepseek", "gemini")}
    assert set(enums[("llm", "provider")]) == set(literal_args)


def test_provider_and_field_records_are_immutable() -> None:
    provider = PROVIDERS["nvd"]

    with pytest.raises(dataclasses.FrozenInstanceError):
        provider.label = "diubah"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        provider.fields[0].secret = False  # type: ignore[misc]


def test_get_provider_returns_the_registry_entry() -> None:
    provider = get_provider("llm")

    assert isinstance(provider, SecretProvider)
    assert provider is PROVIDERS["llm"]


def test_get_provider_rejects_an_unknown_key() -> None:
    with pytest.raises(UnknownProvider):
        get_provider("bitbucket")


def test_unknown_provider_is_a_key_error() -> None:
    """Pemanggil yang sudah menangkap `KeyError` untuk lookup dict tetap jalan."""
    assert issubclass(UnknownProvider, KeyError)


@pytest.mark.parametrize("key", EXPECTED_ORDER)
def test_secret_field_names_are_only_the_secret_ones(key: str) -> None:
    names = secret_field_names(key)

    assert isinstance(names, frozenset)
    assert names == {name for name, secret in EXPECTED_FIELDS[key].items() if secret}


# --- scrub_values -----------------------------------------------------------------------------


def test_min_scrub_len_is_six() -> None:
    assert MIN_SCRUB_LEN == 6


def test_scrub_values_cover_every_registry_secret_and_the_jwt_secret() -> None:
    values = scrub_values(make_settings())

    assert sorted(values) == sorted([*ENV_VALUES.values(), JWT_SECRET])


def test_scrub_values_also_cover_the_master_key() -> None:
    """Master key yang tertempel di pesan error (salah ketik di env, dump konfigurasi) membuka
    SEMUA secret di DB, jadi harus ikut disamarkan."""
    values = scrub_values(make_settings(keys=KEYS))

    assert sorted(values) == sorted([*ENV_VALUES.values(), JWT_SECRET, KEYS])


def test_scrub_values_cover_every_master_key_of_a_rotation_list() -> None:
    values = scrub_values(make_settings(keys=f" {KEYS} , {OTHER_KEYS} "))

    assert KEYS in values and OTHER_KEYS in values  # dipecah di koma, spasi dibuang
    assert not any(v != v.strip() for v in values)


def test_scrub_values_skip_empty_and_short_master_key_entries() -> None:
    """Dibangun lewat `model_copy` (tanpa validasi): Settings asli menolak kunci pendek."""
    settings = make_settings().model_copy(update={"secrets_encryption_keys": f" {KEYS} , abc ,, "})

    values = scrub_values(settings)

    assert KEYS in values
    assert "abc" not in values
    assert "" not in values


@pytest.mark.parametrize(
    ("provider", "field"),
    [
        ("x", "bearer_token"),
        ("otx", "api_key"),
        ("abuseipdb", "api_key"),
        ("virustotal", "api_key"),
    ],
)
def test_scrub_values_include_the_providers_the_old_scrub_missed(provider: str, field: str) -> None:
    assert ENV_VALUES[(provider, field)] in scrub_values(make_settings())


def test_scrub_values_skip_empty_secrets() -> None:
    settings = make_settings(llm=LlmSettings(api_key=""), nvd=NvdSettings(api_key=""))

    values = scrub_values(settings)

    assert "" not in values
    assert ENV_VALUES[("llm", "api_key")] not in values
    assert ENV_VALUES[("telegram", "bot_token")] in values  # yang terisi tetap ikut


def test_scrub_values_skip_values_shorter_than_six_but_keep_exactly_six() -> None:
    five, six = "abcde", "abcdef"
    assert len(five) == MIN_SCRUB_LEN - 1 and len(six) == MIN_SCRUB_LEN

    values = scrub_values(
        make_settings(llm=LlmSettings(api_key=five), nvd=NvdSettings(api_key=six))
    )

    assert five not in values
    assert six in values


def test_scrub_values_never_include_non_secret_fields() -> None:
    values = scrub_values(make_settings())

    for name, value in NON_SECRET_VALUES.items():
        assert value not in values, name
