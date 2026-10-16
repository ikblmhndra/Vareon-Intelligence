"""Penyamaran secret di teks error (ROADMAP #23): `_scrub_secrets` (task enrich -> kolom
`rejected_articles.reason`, tampil di UI) dan `_log_detail` (log newsletter summary).

Daftar yang disamarkan dibangun SATU helper, `overlay.scrub_candidates()`: gabungan nilai `.env`
(base) dan nilai efektif (termasuk override DB), tanpa duplikat, diurutkan terpanjang dulu. Jadi:
(1) semua provider ikut, termasuk x/otx/abuseipdb/virustotal yang dulu bolong, dan master key;
(2) key yang baru diganti dari halaman admin disamarkan, DAN key lama di `.env` tetap disamarkan
(masih bisa muncul di pesan error dari proses yang belum menyegarkan cache atau dari log lama);
(3) secret yang menjadi awalan secret lain tidak menyisakan ekor; (4) penyamaran bersifat
best-effort, TIDAK PERNAH menggagalkan pencatatan error.

Yang di-patch adalah `get_settings` di modul overlay, karena kedua situs scrub memakai
`effective_settings` dari sana. Importnya lazy di dalam tes: `cti_worker.celery_app` memanggil
`get_settings()` saat diimpor, jadi env minimal harus terpasang dulu.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_core.config import OtxSettings, Settings, XSettings, get_settings
from cti_core.runtime_secrets import overlay

from tests.unit.runtime_secrets_helpers import (
    ENV_VALUES,
    JWT_SECRET,
    KEYS,
    install_overlay,
    make_row,
    make_settings,
)


@pytest.fixture(autouse=True)
def _env_and_fresh_overlay(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE__URL", "postgresql+asyncpg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("DATABASE__SYNC_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
    monkeypatch.setenv("AUTH__JWT_SECRET", "test-secret")
    monkeypatch.setenv("AUTH__SESSION_SECRET_KEY", "test-session")
    get_settings.cache_clear()
    overlay.invalidate()
    yield
    overlay.invalidate()
    get_settings.cache_clear()


def scrub(text: str) -> str:
    from cti_worker.tasks.enrich import _scrub_secrets

    return _scrub_secrets(text)


def log_detail(exc: Exception) -> str:
    from cti_api.services.newsletter_summary import _log_detail

    return _log_detail(exc)


EVERY_SECRET = [
    *((f"{provider}.{field}", value) for (provider, field), value in ENV_VALUES.items()),
    ("auth.jwt_secret", JWT_SECRET),
]


# --- _scrub_secrets ---------------------------------------------------------------------------


@pytest.mark.parametrize(("label", "value"), EVERY_SECRET, ids=[label for label, _ in EVERY_SECRET])
def test_scrub_masks_every_configured_secret(
    monkeypatch: pytest.MonkeyPatch, label: str, value: str
) -> None:
    install_overlay(monkeypatch, make_settings())

    assert scrub(f"401 dari gateway: key {value} ditolak") == "401 dari gateway: key *** ditolak"


def test_scrub_masks_every_occurrence_and_several_secrets_in_one_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings())
    otx, vt = ENV_VALUES[("otx", "api_key")], ENV_VALUES[("virustotal", "api_key")]

    result = scrub(f"{otx} lalu {vt} lalu {otx} lagi")

    assert result == "*** lalu *** lalu *** lagi"


def test_scrub_leaves_a_text_without_secrets_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    install_overlay(monkeypatch, make_settings())
    text = "openai.AuthenticationError: Incorrect API key provided"

    assert scrub(text) == text


def test_scrub_ignores_values_shorter_than_six_characters_but_masks_exactly_six(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = make_settings(x=XSettings(bearer_token="abcdef"), otx=OtxSettings(api_key="abcde"))
    install_overlay(monkeypatch, base)

    assert scrub("x=abcdef otx=abcde") == "x=*** otx=abcde"


def test_scrub_with_every_key_empty_does_not_mangle_the_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`"abc".replace("", "***")` menyisipkan `***` di antara SETIAP huruf; kunci kosong (provider
    mati) harus dilewati, bukan dipakai sebagai pola."""
    groups = {provider for provider, _ in ENV_VALUES}
    empties = {name: Settings.model_fields[name].annotation() for name in groups}  # type: ignore[misc]
    base = make_settings(auth={"jwt_secret": "", "session_secret_key": ""}, **empties)
    install_overlay(monkeypatch, base)

    assert scrub("pesan error biasa") == "pesan error biasa"


def test_scrub_masks_a_secret_that_was_overridden_from_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Key yang baru diganti lewat halaman admin yang bakal muncul di pesan error provider, bukan
    nilai lamanya di `.env`."""
    db_otx = "otx-db-bbbbbb"  # gitleaks:allow
    install_overlay(
        monkeypatch,
        make_settings(keys=KEYS),
        [make_row("otx", {"api_key": db_otx})],
    )

    assert scrub(f"OTX menolak {db_otx}") == "OTX menolak ***"


def test_scrub_still_masks_env_secrets_when_the_database_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS))

    def boom() -> list[object]:
        raise ConnectionError("db mati")

    monkeypatch.setattr(overlay, "_fetch_rows", boom)
    abuse = ENV_VALUES[("abuseipdb", "api_key")]

    assert scrub(f"gagal {abuse}") == "gagal ***"


def test_scrub_returns_the_text_as_is_when_settings_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> Settings:
        raise RuntimeError("Settings gagal dimuat")

    monkeypatch.setattr(overlay, "get_settings", broken)

    assert scrub("teks apa adanya") == "teks apa adanya"


def test_scrub_still_masks_the_old_env_key_after_it_was_overridden_from_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_otx = "otx-db-bbbbbb"  # gitleaks:allow
    old_otx = ENV_VALUES[("otx", "api_key")]
    install_overlay(monkeypatch, make_settings(keys=KEYS), [make_row("otx", {"api_key": db_otx})])

    assert scrub(f"lama={old_otx} baru={db_otx}") == "lama=*** baru=***"


def test_scrub_masks_the_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS))

    assert scrub(f"salah ketik: {KEYS}") == "salah ketik: ***"


def test_scrub_still_masks_env_secrets_when_effective_settings_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS))

    def boom() -> Settings:
        raise RuntimeError("overlay rusak")

    monkeypatch.setattr(overlay, "effective_settings", boom)

    assert scrub(f"gagal {ENV_VALUES[('nvd', 'api_key')]}") == "gagal ***"


def test_scrub_leaves_no_tail_when_one_secret_is_a_prefix_of_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kalau yang pendek diganti duluan, `abcdef-longer-tail` jadi `***-longer-tail` dan ekornya
    (bagian dari secret) lolos ke UI. Yang panjang harus diganti lebih dulu."""
    short, long = "abcdef", "abcdef-longer-tail-zzzz"
    base = make_settings(x=XSettings(bearer_token=short), otx=OtxSettings(api_key=long))
    install_overlay(monkeypatch, base)

    assert scrub(f"short={short} long={long}") == "short=*** long=***"


def test_scrub_leaves_no_tail_when_a_database_key_extends_the_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_key = ENV_VALUES[("nvd", "api_key")]
    rotated = f"{env_key}-rotated-9999"  # gitleaks:allow
    install_overlay(monkeypatch, make_settings(keys=KEYS), [make_row("nvd", {"api_key": rotated})])

    assert scrub(f"{rotated} dan {env_key}") == "*** dan ***"


# --- _log_detail ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "value"),
    [(label, value) for label, value in EVERY_SECRET if label != "llm.api_key"],
    ids=[label for label, _ in EVERY_SECRET if label != "llm.api_key"],
)
def test_log_detail_masks_provider_keys_other_than_llm(
    monkeypatch: pytest.MonkeyPatch, label: str, value: str
) -> None:
    install_overlay(monkeypatch, make_settings())

    assert log_detail(RuntimeError(f"gagal dengan {value}")) == "gagal dengan ***"


def test_log_detail_still_masks_the_llm_key(monkeypatch: pytest.MonkeyPatch) -> None:
    install_overlay(monkeypatch, make_settings())

    assert log_detail(RuntimeError(f"401 {ENV_VALUES[('llm', 'api_key')]}")) == "401 ***"


def test_log_detail_stays_one_line_and_clipped(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_api.services.newsletter_summary import LOG_DETAIL_CLIP

    install_overlay(monkeypatch, make_settings())

    detail = log_detail(RuntimeError("baris satu\n\n   baris   dua " + "x" * (LOG_DETAIL_CLIP * 2)))

    assert detail.startswith("baris satu baris dua x")
    assert "\n" not in detail
    assert len(detail) == LOG_DETAIL_CLIP


def test_log_detail_returns_the_message_as_is_when_settings_cannot_be_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken() -> Settings:
        raise RuntimeError("Settings gagal dimuat")

    monkeypatch.setattr(overlay, "get_settings", broken)

    assert log_detail(RuntimeError("gateway   mati")) == "gateway mati"


def test_log_detail_masks_a_database_override_and_still_the_old_env_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_otx = "otx-db-bbbbbb"  # gitleaks:allow
    old_otx = ENV_VALUES[("otx", "api_key")]
    install_overlay(monkeypatch, make_settings(keys=KEYS), [make_row("otx", {"api_key": db_otx})])

    assert log_detail(RuntimeError(f"lama={old_otx} baru={db_otx}")) == "lama=*** baru=***"


def test_log_detail_masks_the_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS))

    assert log_detail(RuntimeError(f"salah ketik {KEYS}")) == "salah ketik ***"


def test_log_detail_leaves_no_tail_when_one_secret_is_a_prefix_of_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    short, long = "abcdef", "abcdef-longer-tail-zzzz"
    base = make_settings(x=XSettings(bearer_token=short), otx=OtxSettings(api_key=long))
    install_overlay(monkeypatch, base)

    assert log_detail(RuntimeError(f"short={short} long={long}")) == "short=*** long=***"


def test_log_detail_still_masks_env_secrets_when_the_database_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = install_overlay(monkeypatch, make_settings(keys=KEYS))
    spy.error = ConnectionError("db mati")

    assert log_detail(RuntimeError(f"gagal {ENV_VALUES[('otx', 'api_key')]}")) == "gagal ***"
