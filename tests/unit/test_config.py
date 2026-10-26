"""cti_core.config -- termasuk regression test buat bug nyata yang ketemu
waktu Fase 2: extra="forbid" di Settings gak otomatis nurun ke nested
BaseModel, jadi typo semacam TELEGRAM__BOTTOKEN diam-diam ke-drop."""

import pytest
from cryptography.fernet import Fernet
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


def test_story_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """P3 (story dedup): semua field punya default, jadi tidak ada key `.env` baru yang wajib."""
    monkeypatch.delenv("STORY__ENABLED", raising=False)
    s = _settings(monkeypatch)
    assert s.story.enabled is True
    assert s.story.window_hours == 72
    assert s.story.max_age_days == 7
    assert s.story.max_key_cves == 5
    assert s.story.cve_overlap == 0.5
    assert s.story.title_similarity == 0.5
    assert _settings(monkeypatch, STORY__ENABLED="false").story.enabled is False


def test_relevance_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """P5 (model relevansi lokal): semua field punya default, tanpa key `.env` baru yang wajib."""
    monkeypatch.delenv("RELEVANCE__MODE", raising=False)
    s = _settings(monkeypatch)
    assert s.relevance.mode == "auto"
    assert s.relevance.accept_threshold == 0.85
    assert s.relevance.audit_rate == 0.2
    assert (s.relevance.gate_min_titles, s.relevance.gate_window_days) == (200, 14)
    assert s.relevance.gate_min_agreement == 0.95
    assert (s.relevance.revert_samples, s.relevance.revert_min_agreement) == (50, 0.92)
    assert (s.relevance.train_min_examples, s.relevance.train_min_per_class) == (1000, 100)
    assert (s.relevance.holdout_days, s.relevance.min_band_share) == (14, 0.2)
    assert s.story.embedding_similarity == 0.0


def test_relevance_mode_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gate` adalah state, bukan mode: nilai selain off/shadow/auto harus gagal saat start."""
    with pytest.raises(ValidationError):
        _settings(monkeypatch, RELEVANCE__MODE="gate")


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


def test_otx_rate_defaults_and_reads_its_env(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings(monkeypatch).otx.rate == "300/hour"
    assert _settings(monkeypatch, OTX__RATE="50/hour").otx.rate == "50/hour"


# --- SECRETS_ENCRYPTION_KEYS (runtime secrets, ROADMAP #23) -----------------------------------


def _fernet_key() -> str:
    return Fernet.generate_key().decode()


def test_secrets_encryption_keys_defaults_to_empty_so_a_deploy_never_fails_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SECRETS_ENCRYPTION_KEYS", raising=False)

    assert _settings(monkeypatch).secrets_encryption_keys == ""


def test_secrets_encryption_keys_reads_its_env(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _fernet_key()

    assert _settings(monkeypatch, SECRETS_ENCRYPTION_KEYS=key).secrets_encryption_keys == key


def test_a_value_that_is_not_a_fernet_key_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kunci master yang salah ketik tidak boleh baru ketahuan saat admin menyimpan key pertama
    (atau lebih buruk, saat dekripsi diam-diam gagal): proses gagal start."""
    with pytest.raises(ValidationError, match=r"(?i)secrets_encryption_keys"):
        _settings(monkeypatch, SECRETS_ENCRYPTION_KEYS="bukan-kunci")


def test_one_bad_key_in_a_list_of_valid_ones_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        _settings(monkeypatch, SECRETS_ENCRYPTION_KEYS=f"{_fernet_key()},bukan-kunci")


def test_a_comma_separated_list_of_valid_keys_is_accepted_as_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = f"{_fernet_key()},{_fernet_key()}"

    assert _settings(monkeypatch, SECRETS_ENCRYPTION_KEYS=keys).secrets_encryption_keys == keys


def test_spaces_around_the_commas_do_not_fail_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sama dengan `crypto`, yang menoleransi spasi di sekitar koma: `.env` ditulis tangan."""
    keys = f"  {_fernet_key()}  ,  {_fernet_key()}  "

    assert _settings(monkeypatch, SECRETS_ENCRYPTION_KEYS=keys).secrets_encryption_keys


def test_a_failed_validation_never_prints_the_input_or_any_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tanpa `hide_input_in_errors`, `ValidationError` mencetak `input_value=` (potongan dict
    masukan yang berisi SEMUA secret): satu salah ketik di env menaruh potongan JWT/token di log
    boot."""
    secrets = {
        "AUTH__JWT_SECRET": "jwt-unik-aaaaaa",  # gitleaks:allow
        "AUTH__SESSION_SECRET_KEY": "sess-unik-bbbbbb",  # gitleaks:allow
        "VAULT_TOKEN": "vault-unik-cccccc",  # gitleaks:allow
    }

    with pytest.raises(ValidationError) as excinfo:
        _settings(monkeypatch, SECRETS_ENCRYPTION_KEYS="bukan-kunci", **secrets)

    text = str(excinfo.value)
    assert "input_value" not in text
    for value in secrets.values():
        assert value not in text
    assert "bukan-kunci" not in text  # kunci master yang salah ketik bisa mirip kunci aslinya


# --- SECRETS_LLM_URL_ALLOWED_HOSTS (runtime secrets, ROADMAP #23) -----------------------------


def test_secrets_llm_url_allowed_hosts_defaults_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kosong = halaman admin tidak bisa mengisi URL LLM kustom di luar dev; deploy tidak pecah."""
    monkeypatch.delenv("SECRETS_LLM_URL_ALLOWED_HOSTS", raising=False)

    assert _settings(monkeypatch).secrets_llm_url_allowed_hosts == ""


def test_secrets_llm_url_allowed_hosts_reads_its_env_as_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """String mentah dipisah koma; pemecahan dan strip spasi ada di `validate_llm_url`."""
    hosts = "gw.example.com, llm.example.org"

    s = _settings(monkeypatch, SECRETS_LLM_URL_ALLOWED_HOSTS=hosts)

    assert s.secrets_llm_url_allowed_hosts == hosts
