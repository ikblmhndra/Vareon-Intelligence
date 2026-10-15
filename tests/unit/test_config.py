"""cti_core.config -- termasuk regression test buat bug nyata yang ketemu
waktu Fase 2: extra="forbid" di Settings gak otomatis nurun ke nested
BaseModel, jadi typo semacam TELEGRAM__BOTTOKEN diam-diam ke-drop."""

import pytest
from cti_core.config import Settings
from pydantic import ValidationError

VALID_ENV = {
    "DATABASE__URL": "postgresql+asyncpg://cti:cti@localhost/cti",
    "DATABASE__SYNC_URL": "postgresql+psycopg://cti:cti@localhost/cti",
    "AUTH__JWT_SECRET": "test-secret",
    "AUTH__SESSION_SECRET_KEY": "test-session",
}


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    for k, v in {**VALID_ENV, **overrides}.items():
        monkeypatch.setenv(k, v)
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_valid_config_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch)
    assert s.database.url.startswith("postgresql+asyncpg://")
    assert s.scraper.cold_start_max_items == 5  # default kepakai
    assert s.secrets_backend == "env"


def test_missing_required_secret_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pengganti RuntimeError manual di app lama (main.py L276-278)."""
    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE__URL", "x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "x")
    # AUTH__JWT_SECRET & AUTH__SESSION_SECRET_KEY sengaja gak di-set
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "bad_key",
    [
        "TELEGRAM__BOTTOKEN",  # bukan BOT_TOKEN -- kasus asli yang ketemu
        "DATABASE__UR",
        "AUTH__JWT_SEKRET",
        "SCRAPER__DEFAULT_RATELIMIT",
    ],
)
def test_typo_in_nested_field_is_rejected(monkeypatch: pytest.MonkeyPatch, bad_key: str) -> None:
    """Regression: nested BaseModel butuh extra='forbid' SENDIRI, gak
    otomatis kewarisin dari Settings. Lihat _StrictModel di config.py."""
    with pytest.raises(ValidationError, match=r"extra_forbidden|Extra inputs"):
        _settings(monkeypatch, **{bad_key: "oops"})


def test_vault_backend_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _settings(monkeypatch, SECRETS_BACKEND="vault")


def test_vault_backend_with_token_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, SECRETS_BACKEND="vault", VAULT_TOKEN="t")
    assert s.secrets_backend == "vault"


def test_telegram_thread_ids_parses_json_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, TELEGRAM__THREAD_IDS='{"apac": 12, "ot": 19}')
    assert s.telegram.thread_ids == {"apac": 12, "ot": 19}


def test_ioc_provider_keys_default_to_off_and_read_their_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    off = _settings(monkeypatch)
    assert off.abuseipdb.api_key == "" and off.virustotal.api_key == ""
    assert (off.abuseipdb.rate, off.virustotal.rate) == ("40/hour", "20/hour")

    on = _settings(
        monkeypatch,
        ABUSEIPDB__API_KEY="abuse-key",
        VIRUSTOTAL__API_KEY="vt-key",
        VIRUSTOTAL__RATE="5/hour",
    )
    assert (on.abuseipdb.api_key, on.virustotal.api_key) == ("abuse-key", "vt-key")
    assert on.virustotal.rate == "5/hour"


def test_a_typo_in_an_ioc_provider_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _settings(monkeypatch, ABUSEIPDB__APIKEY="typo")
