"""`cti_core.runtime_secrets.overlay` -- `get_settings()` + override dari DB (ROADMAP #23).

DB-nya diganti `FetchSpy` (seam `_fetch_rows`), jam diganti `Clock`, dan `get_settings` di modul
overlay diganti `Settings` palsu, jadi tes ini tidak butuh Docker. Jalur ke Postgres beneran ada di
`tests/integration/test_runtime_secrets_db.py`.

Semua field override (secret DAN non-secret) datang HANYA dari payload terenkripsi; baris palsu
dibuat `make_row` lewat `encrypt_fields`.

Yang dikunci, berurutan dari yang paling mahal kalau salah:
- FAIL-OPEN: DB mati / dekripsi gagal / kunci master tidak ada TIDAK BOLEH menjatuhkan proses, dan
  override yang sudah jalan TIDAK BOLEH hilang gara-gara satu kegagalan sesaat (serve-stale): key
  yang baru dirotasi tidak boleh tiba-tiba balik ke key lama di `.env` karena DB berkedip.
- Tidak ada nilai secret di log, `repr`, atau pesan error.
- DB menang atas `.env`, field tanpa override jatuh ke `.env`, input tidak dimutasi.
- Cache: 30 detik kalau sukses, 10 detik kalau gagal; pemanggil yang datang saat thread lain
  me-refresh tidak ikut menunggu I/O; `invalidate()` tidak menunggu dan tidak bisa "dihidupkan lagi"
  oleh load yang sudah berjalan.
"""

from __future__ import annotations

import copy
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from cti_core.config import GithubSettings, LlmSettings
from cti_core.runtime_secrets import overlay
from cti_core.runtime_secrets.overlay import (
    RETRY_SECONDS,
    TTL_SECONDS,
    OverlaySnapshot,
    apply_overrides,
    effective_settings,
    invalidate,
    load_snapshot,
)

from tests.unit.runtime_secrets_helpers import (
    ENV_VALUES,
    JWT_SECRET,
    KEYS,
    OTHER_KEYS,
    FetchSpy,
    install_overlay,
    make_row,
    make_settings,
)

DB_NVD = "nvd-db-bbbbbb"  # gitleaks:allow
OLD_NVD = "nvd-old-aaaaaa"  # gitleaks:allow
DB_LLM = "sk-db-llm-bbbbbb"  # gitleaks:allow
DB_OTX = "otx-db-bbbbbb"  # gitleaks:allow
ENV_NVD = ENV_VALUES[("nvd", "api_key")]
ENV_LLM = ENV_VALUES[("llm", "api_key")]
ENV_GATEWAY = "http://gw.env.example/v1"


@pytest.fixture(autouse=True)
def _fresh_overlay() -> Iterator[None]:
    invalidate()
    yield
    invalidate()


class Clock:
    """Pengganti `overlay._clock` yang maju hanya kalau tes menyuruhnya."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class LogSpy:
    """Pengganti `overlay.log`: mencatat `(level, event, kwargs)` tanpa bergantung pada konfigurasi
    structlog global (urutan tes lain, `cache_logger_on_first_use`)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def record(event: str, **kwargs: Any) -> None:
            self.events.append((level, event, kwargs))

        return record


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> LogSpy:
    spy = LogSpy()
    monkeypatch.setattr(overlay, "log", spy)
    return spy


def _ignored(spy: LogSpy) -> list[tuple[Any, Any]]:
    return [
        (kwargs.get("provider"), kwargs.get("field"))
        for level, event, kwargs in spy.events
        if event == "runtime_secret_field_ignored" and level == "warning"
    ]


# --- apply_overrides: presedensi dan non-mutasi -----------------------------------------------


def test_a_database_override_wins_over_the_env_value() -> None:
    base = make_settings()

    result = apply_overrides(base, {"nvd": {"api_key": DB_NVD}})

    assert result.nvd.api_key == DB_NVD
    assert base.nvd.api_key == ENV_NVD


def test_a_field_without_an_override_falls_back_to_the_env_value() -> None:
    base = make_settings()

    result = apply_overrides(base, {"llm": {"api_key": DB_LLM}})

    assert result.llm.api_key == DB_LLM
    assert result.llm.model == base.llm.model
    assert result.llm.provider == base.llm.provider
    assert result.llm.timeout_s == base.llm.timeout_s


def test_an_override_does_not_disturb_the_rest_of_the_group_or_other_groups() -> None:
    base = make_settings()

    result = apply_overrides(base, {"telegram": {"bot_token": "222:db-telegram-bbbbbb"}})

    assert result.telegram.chat_id == base.telegram.chat_id
    assert result.telegram.thread_ids == base.telegram.thread_ids
    assert result.database == base.database
    assert result.auth == base.auth
    assert result.nvd == base.nvd


def test_several_providers_can_be_overridden_at_once() -> None:
    base = make_settings()

    result = apply_overrides(
        base, {"nvd": {"api_key": DB_NVD}, "otx": {"api_key": DB_OTX}, "llm": {"model": "m-db"}}
    )

    assert (result.nvd.api_key, result.otx.api_key, result.llm.model) == (DB_NVD, DB_OTX, "m-db")


def test_apply_overrides_returns_a_new_settings_and_leaves_the_input_untouched() -> None:
    base = make_settings()
    before = copy.deepcopy(base.model_dump())
    overrides = {"llm": {"api_key": DB_LLM, "model": "m-db"}, "github": {"token": "ghp-db-bbbbbb"}}
    overrides_before = copy.deepcopy(overrides)

    result = apply_overrides(base, overrides)

    assert result is not base
    assert type(result) is type(base)
    assert base.model_dump() == before
    assert overrides == overrides_before


def test_no_overrides_gives_the_same_values() -> None:
    base = make_settings()

    assert apply_overrides(base, {}).model_dump() == base.model_dump()


# --- apply_overrides: field secret ------------------------------------------------------------


def test_a_secret_value_is_stripped() -> None:
    """Tempel dari password manager sering membawa spasi/newline di ujung; key dengan spasi
    ditolak vendor dengan 401 yang membingungkan."""
    result = apply_overrides(make_settings(), {"nvd": {"api_key": f"  {DB_NVD}\n"}})

    assert result.nvd.api_key == DB_NVD


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_secret_that_is_empty_after_stripping_never_overwrites_a_working_env_value(
    blank: str,
) -> None:
    base = make_settings()

    result = apply_overrides(base, {"nvd": {"api_key": blank}, "llm": {"api_key": blank}})

    assert result.nvd.api_key == ENV_NVD
    assert result.llm.api_key == ENV_LLM


@pytest.mark.parametrize("bad", [123, None, ["k"], {"k": "v"}, True], ids=repr)
def test_a_non_string_secret_is_ignored(bad: object) -> None:
    base = make_settings()

    result = apply_overrides(base, {"nvd": {"api_key": bad}})  # type: ignore[dict-item]

    assert result.nvd.api_key == ENV_NVD


# --- apply_overrides: field non-secret --------------------------------------------------------


def test_an_empty_string_for_a_non_secret_field_overrides_the_env_value() -> None:
    """Kosong berarti "pakai default vendor": `llm.url=""` mematikan gateway custom di `.env`."""
    base = make_settings(
        llm=LlmSettings(api_key=ENV_LLM, url=ENV_GATEWAY, model="env-model-aaaaaa")
    )

    result = apply_overrides(base, {"llm": {"url": "", "model": ""}})

    assert result.llm.url == ""
    assert result.llm.model == ""
    assert result.llm.api_key == ENV_LLM  # field secret di grup yang sama tidak ikut berubah


def test_a_non_secret_value_is_stripped() -> None:
    result = apply_overrides(make_settings(), {"llm": {"model": "  m-db \n"}})

    assert result.llm.model == "m-db"


@pytest.mark.parametrize("bad", [5, None, ["m"]], ids=repr)
def test_a_non_string_non_secret_value_is_ignored(bad: object) -> None:
    base = make_settings()

    result = apply_overrides(base, {"llm": {"model": bad}})  # type: ignore[dict-item]

    assert result.llm.model == base.llm.model


# --- apply_overrides: field enum --------------------------------------------------------------


def test_a_valid_enum_value_is_accepted() -> None:
    base = make_settings()

    assert apply_overrides(base, {"llm": {"provider": "gemini"}}).llm.provider == "gemini"


def test_an_enum_value_is_stripped_before_it_is_checked_against_the_choices() -> None:
    base = make_settings()

    assert apply_overrides(base, {"llm": {"provider": " gemini\n"}}).llm.provider == "gemini"


@pytest.mark.parametrize("bad", ["anthropic", "", "   ", 7], ids=repr)
def test_an_enum_value_outside_the_choices_or_blank_is_ignored(bad: object) -> None:
    base = make_settings(llm=LlmSettings(provider="deepseek", api_key=ENV_LLM))

    result = apply_overrides(base, {"llm": {"provider": bad, "model": "m-db"}})  # type: ignore[dict-item]

    assert result.llm.provider == "deepseek"
    assert result.llm.model == "m-db"  # field lain di provider yang sama tetap berlaku


# --- apply_overrides: yang tidak dikenal ------------------------------------------------------


def test_an_unknown_provider_is_ignored_and_logged_without_its_value(logs: LogSpy) -> None:
    base = make_settings()
    value = "bb-db-bbbbbb"  # gitleaks:allow

    result = apply_overrides(base, {"bitbucket": {"token": value}})

    assert result.model_dump() == base.model_dump()
    ignored = _ignored(logs)
    assert len(ignored) == 1 and ignored[0][0] == "bitbucket"
    assert ignored[0][1] in {"token", "*"}  # provider tak dikenal: nama field atau penanda "semua"
    assert value not in repr(logs.events)


def test_a_field_outside_the_registry_is_ignored_and_logged_without_its_value(
    logs: LogSpy,
) -> None:
    """`chat_id` dan `timeout_s` memang ada di Settings tapi sengaja tidak bisa di-override."""
    base = make_settings()

    result = apply_overrides(
        base,
        {"telegram": {"chat_id": "-999", "bot_token": "222:db-bbbbbb"}, "llm": {"timeout_s": "1"}},
    )

    assert result.telegram.chat_id == base.telegram.chat_id
    assert result.telegram.bot_token == "222:db-bbbbbb"
    assert result.llm.timeout_s == base.llm.timeout_s
    assert sorted(_ignored(logs)) == [("llm", "timeout_s"), ("telegram", "chat_id")]
    assert "-999" not in repr(logs.events)


# --- load_snapshot ----------------------------------------------------------------------------


def test_without_a_master_key_the_snapshot_is_empty_and_the_database_is_not_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = make_row("nvd", {"api_key": DB_NVD})
    spy = install_overlay(monkeypatch, make_settings(keys=""), [row])

    snapshot = load_snapshot()

    assert snapshot == OverlaySnapshot(overrides={}, errors={})
    assert spy.calls == 0


def test_load_snapshot_uses_the_given_base_instead_of_get_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = install_overlay(
        monkeypatch, make_settings(keys=""), [make_row("nvd", {"api_key": DB_NVD})]
    )

    def forbidden() -> None:
        raise AssertionError("get_settings tidak boleh dipanggil kalau base diberikan")

    monkeypatch.setattr(overlay, "get_settings", forbidden)

    snapshot = load_snapshot(make_settings(keys=KEYS))

    assert snapshot.overrides == {"nvd": {"api_key": DB_NVD}}
    assert spy.calls == 1


def test_a_row_contributes_every_field_of_its_encrypted_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secret DAN non-secret (model, url) sama-sama dari payload terenkripsi; tidak ada kolom
    plaintext yang ikut dibaca."""
    row = make_row("llm", {"model": "m-db", "url": "https://gw.example.test/v1", "api_key": DB_LLM})
    install_overlay(monkeypatch, make_settings(keys=KEYS), [row])

    snapshot = load_snapshot()

    assert snapshot.overrides == {
        "llm": {"model": "m-db", "url": "https://gw.example.test/v1", "api_key": DB_LLM}
    }
    assert snapshot.errors == {}


def test_rows_of_several_providers_all_load(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [make_row("llm", {"api_key": DB_LLM}), make_row("nvd", {"api_key": DB_NVD})]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    assert load_snapshot().overrides == {"llm": {"api_key": DB_LLM}, "nvd": {"api_key": DB_NVD}}


def test_rows_scoped_to_a_client_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hanya scope platform yang berlaku di irisan ini; BYOK per-workspace belum dibangun."""
    rows = [make_row("nvd", {"api_key": DB_NVD}, client_id="acme")]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    assert load_snapshot() == OverlaySnapshot(overrides={}, errors={})


def test_a_client_row_never_shadows_the_platform_row(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        make_row("nvd", {"api_key": "client-nvd-cccccc"}, client_id="acme"),
        make_row("nvd", {"api_key": DB_NVD}),
    ]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    assert load_snapshot().overrides == {"nvd": {"api_key": DB_NVD}}


def test_a_row_of_an_unknown_provider_is_ignored_without_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Baris dari versi kode yang lebih baru (provider belum ada di registry ini)."""
    rows = [make_row("bitbucket", {"token": "bb-db-bbbbbb"}), make_row("nvd", {"api_key": DB_NVD})]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    snapshot = load_snapshot()

    assert snapshot.overrides == {"nvd": {"api_key": DB_NVD}}
    assert snapshot.errors == {}


def test_load_snapshot_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS))

    load_snapshot()
    load_snapshot()

    assert spy.calls == 2


def test_repr_of_a_snapshot_never_contains_a_decrypted_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot bisa tertangkap traceback/log/pytest; `repr` tidak boleh membuka secret."""
    row = make_row("llm", {"api_key": DB_LLM, "model": "model-db-bbbbbb"})
    install_overlay(monkeypatch, make_settings(keys=KEYS), [row])

    snapshot = load_snapshot()

    assert snapshot.overrides  # kontrol positif: nilainya memang ada di objek
    assert DB_LLM not in repr(snapshot)
    assert "model-db-bbbbbb" not in repr(snapshot)


# --- load_snapshot: DB gagal ------------------------------------------------------------------


class DbDown(Exception):
    """Exception DB tiruan; pesannya SENGAJA memuat secret seperti DSN di pesan driver asli."""


def _db_down(spy: FetchSpy) -> None:
    spy.error = DbDown(f"koneksi putus key={ENV_LLM} jwt={JWT_SECRET} postgresql://u:p@h/db")


def test_a_database_failure_gives_a_star_error_with_only_the_exception_type_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS))
    _db_down(spy)

    snapshot = load_snapshot()

    assert snapshot.overrides == {}
    assert snapshot.errors == {"*": "DbDown"}


def test_a_database_failure_keeps_the_previous_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS))
    _db_down(spy)
    previous = OverlaySnapshot(overrides={"nvd": {"api_key": DB_NVD}}, errors={})

    snapshot = load_snapshot(previous=previous)

    assert snapshot.overrides == {"nvd": {"api_key": DB_NVD}}
    assert snapshot.errors == {"*": "DbDown"}


def test_the_database_error_log_never_contains_a_secret_value(
    monkeypatch: pytest.MonkeyPatch, logs: LogSpy
) -> None:
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS))
    _db_down(spy)

    load_snapshot()

    assert logs.events  # kontrol positif: kegagalannya memang dicatat
    for leaked in (ENV_LLM, JWT_SECRET, "postgresql://"):
        assert leaked not in repr(logs.events)


# --- load_snapshot: baris bermasalah ----------------------------------------------------------


class ExplodingRow:
    """Baris yang atributnya meledak saat dibaca (kolom rusak, driver aneh)."""

    provider = "llm"
    client_id = None

    @property
    def secrets_enc(self) -> bytes:
        raise RuntimeError(f"kolom rusak {ENV_LLM}")


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"keys": OTHER_KEYS}, id="encrypted-with-another-master-key"),
        pytest.param({"secrets_enc": b"bukan-token-fernet"}, id="garbage-token"),
    ],
)
def test_a_provider_that_fails_to_decrypt_is_marked_decrypt_failed_and_others_still_load(
    monkeypatch: pytest.MonkeyPatch, broken: dict[str, Any]
) -> None:
    rows = [
        make_row("llm", {"model": "m-db", "api_key": DB_LLM}, **broken),
        make_row("nvd", {"api_key": DB_NVD}),
    ]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    snapshot = load_snapshot()

    assert snapshot.overrides == {"nvd": {"api_key": DB_NVD}}
    assert snapshot.errors == {"llm": "decrypt_failed"}


def test_a_token_bound_to_another_provider_or_scope_is_marked_decrypt_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token `nvd` yang disalin ke baris `otx`, atau token client yang masuk baris platform."""
    swapped = make_row("otx", secrets_enc=make_row("nvd", {"api_key": DB_NVD}).secrets_enc)
    rescoped = make_row(
        "github",
        secrets_enc=make_row("github", {"token": "gh-x-aaaaaa"}, client_id="acme").secrets_enc,
    )
    install_overlay(monkeypatch, make_settings(keys=KEYS), [swapped, rescoped])

    snapshot = load_snapshot()

    assert snapshot.overrides == {}
    assert snapshot.errors == {"otx": "decrypt_failed", "github": "decrypt_failed"}


def test_a_row_that_blows_up_is_marked_invalid_row_without_stopping_the_others(
    monkeypatch: pytest.MonkeyPatch, logs: LogSpy
) -> None:
    rows = [ExplodingRow(), make_row("nvd", {"api_key": DB_NVD})]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    snapshot = load_snapshot()

    assert snapshot.overrides == {"nvd": {"api_key": DB_NVD}}
    assert snapshot.errors == {"llm": "invalid_row"}
    assert ENV_LLM not in repr(
        logs.events
    )  # pesan exception baris tidak ikut dicatat mentah-mentah


@pytest.mark.parametrize("payload", [b"[1, 2, 3]", b'{"provider": "llm"}', b"bukan json"])
def test_a_valid_token_with_a_malformed_payload_is_an_error_for_that_provider_only(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    forged = Fernet(KEYS.encode()).encrypt(payload)
    rows = [make_row("llm", secrets_enc=forged), make_row("nvd", {"api_key": DB_NVD})]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    snapshot = load_snapshot()

    assert snapshot.overrides == {"nvd": {"api_key": DB_NVD}}
    assert snapshot.errors.keys() == {"llm"}
    assert snapshot.errors["llm"] in {"decrypt_failed", "invalid_row"}


def test_a_failing_provider_keeps_its_previous_overrides_while_others_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        make_row("llm", {"api_key": "sk-new-cccccc"}, keys=OTHER_KEYS),  # tidak bisa didekripsi
        make_row("nvd", {"api_key": DB_NVD}),
    ]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)
    previous = OverlaySnapshot(
        overrides={"llm": {"api_key": DB_LLM, "model": "m-old"}, "nvd": {"api_key": OLD_NVD}},
        errors={},
    )

    snapshot = load_snapshot(previous=previous)

    assert snapshot.overrides == {
        "llm": {"api_key": DB_LLM, "model": "m-old"},  # dipertahankan UTUH
        "nvd": {"api_key": DB_NVD},  # yang sehat tetap disegarkan
    }
    assert snapshot.errors == {"llm": "decrypt_failed"}


def test_a_failing_provider_without_a_previous_snapshot_is_simply_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [make_row("llm", {"api_key": DB_LLM}, keys=OTHER_KEYS)]
    install_overlay(monkeypatch, make_settings(keys=KEYS), rows)

    snapshot = load_snapshot(previous=OverlaySnapshot(overrides={"nvd": {"api_key": OLD_NVD}}))

    assert "llm" not in snapshot.overrides
    assert snapshot.errors == {"llm": "decrypt_failed"}


# --- effective_settings -----------------------------------------------------------------------


def test_effective_settings_applies_the_database_override_and_keeps_the_rest_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_settings(keys=KEYS)
    install_overlay(monkeypatch, base, [make_row("nvd", {"api_key": DB_NVD})])

    effective = effective_settings()

    assert effective.nvd.api_key == DB_NVD
    assert effective.github.token == base.github.token
    assert effective.secrets_encryption_keys == KEYS
    assert base.nvd.api_key == ENV_NVD  # base tidak dimutasi


def test_effective_settings_fills_a_key_that_is_empty_in_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_settings(keys=KEYS, github=GithubSettings(token=""))
    install_overlay(monkeypatch, base, [make_row("github", {"token": "ghp-db-bbbbbb"})])

    assert effective_settings().github.token == "ghp-db-bbbbbb"


def test_effective_settings_can_clear_a_gateway_url_that_is_set_in_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_settings(
        keys=KEYS, llm=LlmSettings(api_key=ENV_LLM, url=ENV_GATEWAY, model="env-model-aaaaaa")
    )
    install_overlay(monkeypatch, base, [make_row("llm", {"url": ""})])

    assert effective_settings().llm.url == ""


def test_without_a_master_key_effective_settings_is_get_settings_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_settings(keys="")
    spy = install_overlay(monkeypatch, base, [make_row("nvd", {"api_key": DB_NVD})])

    assert effective_settings() is base
    assert spy.calls == 0


def test_an_empty_table_gives_get_settings_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    base = make_settings(keys=KEYS)
    install_overlay(monkeypatch, base, [])

    assert effective_settings() is base


def test_a_first_load_that_fails_fails_open_to_the_env_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_settings(keys=KEYS)
    spy = install_overlay(monkeypatch, base)
    spy.error = ConnectionError("db mati")

    assert effective_settings() is base


def test_a_provider_that_fails_to_decrypt_falls_back_to_env_while_others_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_settings(keys=KEYS)
    rows = [
        make_row("llm", {"api_key": DB_LLM}, keys=OTHER_KEYS),
        make_row("nvd", {"api_key": DB_NVD}),
    ]
    install_overlay(monkeypatch, base, rows)

    effective = effective_settings()

    assert effective.llm.api_key == ENV_LLM
    assert effective.nvd.api_key == DB_NVD


def test_client_rows_leave_effective_settings_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    base = make_settings(keys=KEYS)
    row = make_row("nvd", {"api_key": DB_NVD}, client_id="acme")
    install_overlay(monkeypatch, base, [row])

    assert effective_settings() is base


# --- cache: TTL sukses, retry gagal, serve-stale ----------------------------------------------


def test_the_cache_defaults_are_thirty_seconds_on_success_ten_on_failure() -> None:
    assert TTL_SECONDS == 30.0
    assert RETRY_SECONDS == 10.0


def test_the_clock_defaults_to_the_monotonic_clock() -> None:
    assert overlay._clock is time.monotonic


def test_two_calls_within_the_ttl_hit_the_database_once(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    spy = install_overlay(
        monkeypatch, make_settings(keys=KEYS), [make_row("nvd", {"api_key": DB_NVD})]
    )

    first = effective_settings()
    clock.now += TTL_SECONDS - 5
    second = effective_settings()

    assert spy.calls == 1
    assert first.nvd.api_key == second.nvd.api_key == DB_NVD


def test_an_empty_table_is_cached_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hampir selalu tabelnya kosong; kalau hasil kosong tidak di-cache, tiap `get_llm_client()` dan
    tiap kirim Telegram memukul Postgres."""
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS), [])

    effective_settings()
    clock.now += 1
    effective_settings()

    assert spy.calls == 1


def test_after_the_ttl_the_database_is_read_again_and_changes_become_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    spy = install_overlay(
        monkeypatch, make_settings(keys=KEYS), [make_row("nvd", {"api_key": OLD_NVD})]
    )
    assert effective_settings().nvd.api_key == OLD_NVD

    spy.rows = [make_row("nvd", {"api_key": DB_NVD})]
    clock.now += TTL_SECONDS - 5
    assert effective_settings().nvd.api_key == OLD_NVD  # belum kedaluwarsa
    clock.now += 10  # total lewat TTL
    assert effective_settings().nvd.api_key == DB_NVD

    assert spy.calls == 2


def test_a_failed_load_is_retried_after_ten_seconds_not_thirty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS))
    spy.error = ConnectionError("db mati")

    effective_settings()
    clock.now += RETRY_SECONDS - 1
    effective_settings()
    assert spy.calls == 1  # masih di jendela retry: DB yang mati tidak dipukul tiap panggilan

    clock.now += 2  # 11 dtk sejak kegagalan, jauh sebelum TTL 30 dtk
    effective_settings()
    assert spy.calls == 2


def test_the_previous_override_is_still_served_when_the_database_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serve-stale: key yang baru dirotasi tidak boleh balik ke key lama di `.env` karena DB
    berkedip sesaat."""
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    spy = install_overlay(
        monkeypatch, make_settings(keys=KEYS), [make_row("nvd", {"api_key": DB_NVD})]
    )
    assert effective_settings().nvd.api_key == DB_NVD

    spy.error = ConnectionError("db mati")
    clock.now += TTL_SECONDS + 1
    assert effective_settings().nvd.api_key == DB_NVD  # gagal fetch, override lama tetap jalan
    assert spy.calls == 2

    clock.now += RETRY_SECONDS - 1
    assert effective_settings().nvd.api_key == DB_NVD  # jendela retry: tanpa fetch baru
    assert spy.calls == 2


def test_the_database_recovers_after_the_retry_window(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    spy = install_overlay(
        monkeypatch, make_settings(keys=KEYS), [make_row("nvd", {"api_key": OLD_NVD})]
    )
    effective_settings()
    spy.error = ConnectionError("db mati")
    clock.now += TTL_SECONDS + 1
    assert effective_settings().nvd.api_key == OLD_NVD

    spy.error = None
    spy.rows = [make_row("nvd", {"api_key": DB_NVD})]
    clock.now += RETRY_SECONDS + 1

    assert effective_settings().nvd.api_key == DB_NVD
    assert spy.calls == 3


def test_a_provider_failing_to_decrypt_keeps_its_previous_override_through_effective_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    spy = install_overlay(
        monkeypatch,
        make_settings(keys=KEYS),
        [make_row("llm", {"api_key": DB_LLM}), make_row("nvd", {"api_key": OLD_NVD})],
    )
    assert effective_settings().llm.api_key == DB_LLM

    spy.rows = [
        make_row("llm", {"api_key": "sk-new-cccccc"}, keys=OTHER_KEYS),  # rusak di refresh ini
        make_row("nvd", {"api_key": DB_NVD}),
    ]
    clock.now += TTL_SECONDS + 1
    effective = effective_settings()

    assert effective.llm.api_key == DB_LLM
    assert effective.nvd.api_key == DB_NVD


# --- cache: kunci (master key, DSN sync) ------------------------------------------------------


def _other_database() -> dict[str, str]:
    return {
        "url": "postgresql+asyncpg://x:x@other/x",
        "sync_url": "postgresql+psycopg://x:x@other/x",
    }


def test_a_different_database_url_does_not_reuse_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dua `Settings` dengan master key sama tapi DB beda (tes, atau pindah DSN) bukan data yang
    sama; kunci cache bukan sekadar string master key."""
    base_a = make_settings(keys=KEYS)
    base_b = make_settings(keys=KEYS, database=_other_database())
    spy = install_overlay(monkeypatch, base_a, [make_row("nvd", {"api_key": DB_NVD})])
    current = {"settings": base_a}
    monkeypatch.setattr(overlay, "get_settings", lambda: current["settings"])

    effective_settings()
    effective_settings()
    assert spy.calls == 1

    current["settings"] = base_b
    effective_settings()

    assert spy.calls == 2


def test_a_different_master_key_list_does_not_reuse_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_a = make_settings(keys=KEYS)
    base_b = make_settings(keys=f"{OTHER_KEYS},{KEYS}")  # rotasi: kunci baru di depan
    spy = install_overlay(monkeypatch, base_a, [make_row("nvd", {"api_key": DB_NVD})])
    current = {"settings": base_a}
    monkeypatch.setattr(overlay, "get_settings", lambda: current["settings"])
    effective_settings()

    current["settings"] = base_b

    assert effective_settings().nvd.api_key == DB_NVD
    assert spy.calls == 2


def test_a_stale_snapshot_is_not_served_across_a_different_cache_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Serve-stale hanya untuk kunci cache yang SAMA; override milik DB/master key lain tidak boleh
    bocor ke konfigurasi yang berbeda."""
    base_a = make_settings(keys=KEYS)
    base_b = make_settings(keys=KEYS, database=_other_database())
    spy = install_overlay(monkeypatch, base_a, [make_row("nvd", {"api_key": DB_NVD})])
    current = {"settings": base_a}
    monkeypatch.setattr(overlay, "get_settings", lambda: current["settings"])
    assert effective_settings().nvd.api_key == DB_NVD

    current["settings"] = base_b
    spy.error = ConnectionError("db mati")

    assert effective_settings() is base_b


# --- konkurensi -------------------------------------------------------------------------------


class SlowFetch:
    """`_fetch_rows` yang memblokir di panggilan ke-`gated_call` sampai `release` di-set.
    `batches[n-1]` = baris yang dikembalikan panggilan ke-n (yang terakhir dipakai seterusnya)."""

    def __init__(self, batches: list[list[Any]], *, gated_call: int) -> None:
        self.batches = batches
        self.gated_call = gated_call
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def __call__(self) -> list[Any]:
        with self._lock:
            self.calls += 1
            n = self.calls
        rows = self.batches[min(n, len(self.batches)) - 1]
        if n == self.gated_call:
            self.started.set()
            self.release.wait(
                timeout=5
            )  # batas atas: implementasi yang menyerialisasi tetap selesai
        return list(rows)


def _in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    out: list[Any] = []

    def run() -> None:
        try:
            out.append(fn())
        except BaseException as e:
            out.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


def test_a_caller_during_a_refresh_gets_the_previous_snapshot_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dipanggil dari event loop API: menunggu I/O thread lain membekukan SELURUH proses."""
    clock = Clock()
    monkeypatch.setattr(overlay, "_clock", clock)
    install_overlay(monkeypatch, make_settings(keys=KEYS))
    fetch = SlowFetch(
        [[make_row("nvd", {"api_key": OLD_NVD})], [make_row("nvd", {"api_key": DB_NVD})]],
        gated_call=2,
    )
    monkeypatch.setattr(overlay, "_fetch_rows", fetch)
    assert effective_settings().nvd.api_key == OLD_NVD  # panggilan 1: tidak digerbang
    clock.now += TTL_SECONDS + 1

    refresher, refreshed = _in_thread(effective_settings)
    assert fetch.started.wait(timeout=5)
    began = time.perf_counter()
    during = effective_settings()
    waited = time.perf_counter() - began
    fetch.release.set()
    refresher.join(timeout=5)

    assert waited < 1.0
    assert during.nvd.api_key == OLD_NVD
    assert refreshed[0].nvd.api_key == DB_NVD
    assert effective_settings().nvd.api_key == DB_NVD  # hasil refresh sudah ter-cache
    assert fetch.calls == 2


def test_concurrent_cold_callers_end_up_sharing_one_cached_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tanpa snapshot lama, pemanggil kedua boleh menunggu atau memuat sendiri; yang dikunci: dua-
    duanya selesai tanpa error dan sesudahnya cache terisi (panggilan berikutnya tidak fetch)."""
    install_overlay(monkeypatch, make_settings(keys=KEYS))
    fetch = SlowFetch([[make_row("nvd", {"api_key": DB_NVD})]], gated_call=1)
    monkeypatch.setattr(overlay, "_fetch_rows", fetch)

    first, first_out = _in_thread(effective_settings)
    assert fetch.started.wait(timeout=5)
    second, second_out = _in_thread(effective_settings)
    time.sleep(0.1)  # beri thread kedua kesempatan nyasar masuk ke fetch sendiri
    fetch.release.set()
    first.join(timeout=5)
    second.join(timeout=5)
    calls_after_burst = fetch.calls

    assert first_out[0].nvd.api_key == DB_NVD
    assert not isinstance(second_out[0], BaseException)
    assert effective_settings().nvd.api_key == DB_NVD
    assert fetch.calls == calls_after_burst  # cache hit: tidak ada fetch tambahan


def test_invalidate_does_not_wait_for_a_load_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS))
    fetch = SlowFetch([[make_row("nvd", {"api_key": OLD_NVD})]], gated_call=1)
    monkeypatch.setattr(overlay, "_fetch_rows", fetch)
    loader, _ = _in_thread(effective_settings)
    assert fetch.started.wait(timeout=5)

    began = time.perf_counter()
    invalidate()
    waited = time.perf_counter() - began
    fetch.release.set()
    loader.join(timeout=5)

    assert waited < 1.0


def test_a_load_that_started_before_invalidate_cannot_refill_the_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proses yang baru menulis memanggil `invalidate()` supaya langsung melihat key barunya;
    load lama yang masih terbang (membawa data SEBELUM tulis) tidak boleh menimpanya."""
    install_overlay(monkeypatch, make_settings(keys=KEYS))
    fetch = SlowFetch(
        [[make_row("nvd", {"api_key": OLD_NVD})], [make_row("nvd", {"api_key": DB_NVD})]],
        gated_call=1,
    )
    monkeypatch.setattr(overlay, "_fetch_rows", fetch)
    loader, _ = _in_thread(effective_settings)
    assert fetch.started.wait(timeout=5)

    invalidate()
    fetch.release.set()
    loader.join(timeout=5)

    assert effective_settings().nvd.api_key == DB_NVD
    assert fetch.calls == 2


def test_invalidate_forces_the_next_call_to_read_the_database_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = install_overlay(
        monkeypatch, make_settings(keys=KEYS), [make_row("nvd", {"api_key": OLD_NVD})]
    )
    assert effective_settings().nvd.api_key == OLD_NVD

    spy.rows = [make_row("nvd", {"api_key": DB_NVD})]
    invalidate()

    assert effective_settings().nvd.api_key == DB_NVD
    assert spy.calls == 2


# --- scrub_candidates -------------------------------------------------------------------------


def test_scrub_candidates_include_env_values_and_database_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS), [make_row("otx", {"api_key": DB_OTX})])

    candidates = overlay.scrub_candidates()

    assert DB_OTX in candidates
    assert ENV_VALUES[("otx", "api_key")] in candidates  # key LAMA di .env tetap disamarkan
    assert ENV_NVD in candidates
    assert JWT_SECRET in candidates
    assert KEYS in candidates  # master key


def test_scrub_candidates_have_no_duplicates_when_nothing_is_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS), [])

    candidates = overlay.scrub_candidates()

    assert len(candidates) == len(set(candidates))
    assert sorted(candidates) == sorted([*ENV_VALUES.values(), JWT_SECRET, KEYS])


def test_scrub_candidates_are_sorted_longest_first_then_by_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS), [make_row("otx", {"api_key": DB_OTX})])

    candidates = overlay.scrub_candidates()

    assert candidates == sorted(candidates, key=lambda v: (-len(v), v))


def test_scrub_candidates_survive_a_database_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS))
    spy.error = ConnectionError("db mati")

    candidates = overlay.scrub_candidates()

    assert ENV_NVD in candidates and KEYS in candidates


def test_scrub_candidates_survive_effective_settings_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS))

    def boom() -> None:
        raise RuntimeError("overlay rusak")

    monkeypatch.setattr(overlay, "effective_settings", boom)

    candidates = overlay.scrub_candidates()

    assert ENV_NVD in candidates  # nilai .env (base) tetap ada


def test_scrub_candidates_are_empty_when_settings_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> None:
        raise RuntimeError("Settings gagal dimuat")

    monkeypatch.setattr(overlay, "get_settings", boom)

    assert overlay.scrub_candidates() == []
