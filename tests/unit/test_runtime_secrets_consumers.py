"""Titik baca key (consumer) yang harus ikut override DB (ROADMAP #23): satu tes per jalur.

Kontraknya: default `settings` di tiap consumer berasal dari `effective_settings()`, bukan
`get_settings()`. Jadi key yang diganti dari halaman admin dipakai oleh run scraper, panggilan LLM,
kirim Telegram dan draft email BERIKUTNYA tanpa restart. Parameter `settings=` eksplisit tetap
menang (tes lain bergantung padanya), jadi itu tidak diuji di sini.

Overlay diarahkan ke Settings palsu + baris palsu lewat `install_overlay`, tanpa DB.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cti_alerts import mailer
from cti_alerts import telegram as alerts_telegram
from cti_core.config import GithubSettings, LlmSettings
from cti_core.llm.client import get_llm_client, store_param
from cti_core.runtime_secrets import overlay
from cti_scraper.credentials import resolve_credential_headers

from tests.unit.runtime_secrets_helpers import (
    ENV_VALUES,
    KEYS,
    NON_SECRET_VALUES,
    install_overlay,
    make_row,
    make_settings,
)

DB_LLM = "sk-db-llm-bbbbbb"  # gitleaks:allow
DB_GITHUB = "ghp-db-bbbbbb"  # gitleaks:allow
DB_TELEGRAM = "222:db-telegram-bbbbbb"  # gitleaks:allow
DB_GRAPH = "db-graph-bbbbbb"  # gitleaks:allow


@pytest.fixture(autouse=True)
def _fresh_overlay() -> Iterator[None]:
    overlay.invalidate()
    yield
    overlay.invalidate()


# --- cti_core.llm.client ----------------------------------------------------------------------


def test_the_llm_client_is_built_from_the_overridden_key_model_and_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = make_row(
        "llm",
        {"api_key": DB_LLM, "model": "model-db-bbbbbb", "url": "https://gw.db.example.test/v1"},
    )
    install_overlay(monkeypatch, make_settings(keys=KEYS), [row])

    client, model = get_llm_client()

    assert client.api_key == DB_LLM
    assert model == "model-db-bbbbbb"
    assert str(client.base_url) == "https://gw.db.example.test/v1/"


def test_the_llm_client_keeps_using_the_env_values_when_nothing_is_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS), [])

    client, model = get_llm_client()

    assert client.api_key == ENV_VALUES[("llm", "api_key")]
    assert model == NON_SECRET_VALUES["llm_model"]


def test_an_empty_overridden_url_goes_back_to_the_vendor_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`llm.url=""` dari halaman admin = "pakai default vendor", walau `.env` menunjuk gateway."""
    base = make_settings(
        keys=KEYS,
        llm=LlmSettings(api_key=ENV_VALUES[("llm", "api_key")], url="http://gw.env.example/v1"),
    )
    install_overlay(monkeypatch, base, [make_row("llm", {"url": ""})])

    client, _ = get_llm_client()

    assert str(client.base_url) == "https://api.openai.com/v1/"
    assert store_param() == {"store": True}


def test_store_param_follows_the_overridden_gateway_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Klien yang sudah menunjuk gateway custom dari DB tidak boleh tetap mengirim `store=True`
    (itu cuma buat OpenAI asli); `store_param()` harus melihat URL efektif yang sama."""
    install_overlay(monkeypatch, make_settings(keys=KEYS), [])
    assert store_param() == {"store": True}  # `.env` tanpa url = OpenAI asli

    overlay.invalidate()
    row = make_row("llm", {"url": "https://gw.db.example.test/v1"})
    install_overlay(monkeypatch, make_settings(keys=KEYS), [row])

    assert store_param() == {}


# --- cti_scraper.credentials ------------------------------------------------------------------


def test_scraper_credentials_use_the_overridden_token_even_when_env_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Kasus yang paling berguna: `.env` kosong (provider "mati"), key diisi dari halaman admin."""
    base = make_settings(keys=KEYS, github=GithubSettings(token=""))
    install_overlay(monkeypatch, base, [make_row("github", {"token": DB_GITHUB})])

    assert resolve_credential_headers("github") == {"Authorization": f"Bearer {DB_GITHUB}"}


def test_scraper_credentials_keep_using_the_env_token_when_nothing_is_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_overlay(monkeypatch, make_settings(keys=KEYS), [])

    expected = ENV_VALUES[("github", "token")]
    assert resolve_credential_headers("github") == {"Authorization": f"Bearer {expected}"}


# --- cti_alerts -------------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["cti_alerts.telegram", "cti_alerts.mailer"])
def test_the_alert_modules_take_their_default_settings_from_effective_settings(
    module: str,
) -> None:
    assert callable(importlib.import_module(module).effective_settings)


def _fake_telegram_bot(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Ganti `telegram.Bot` dengan bot palsu; kembalikan daftar bot yang dibuat."""
    created: list[Any] = []

    class FakeBot:
        def __init__(self, token: str) -> None:
            self.token = token
            self.sent: list[dict[str, Any]] = []
            created.append(self)

        async def send_message(self, **kwargs: Any) -> None:
            self.sent.append(kwargs)

    monkeypatch.setattr(alerts_telegram.telegram, "Bot", FakeBot)
    return created


def test_send_alert_uses_the_overridden_bot_token_and_keeps_chat_and_thread_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bots = _fake_telegram_bot(monkeypatch)
    row = make_row("telegram", {"bot_token": DB_TELEGRAM})
    install_overlay(monkeypatch, make_settings(keys=KEYS), [row])

    alerts_telegram.send_alert("global", "halo")

    assert [bot.token for bot in bots] == [DB_TELEGRAM]
    assert bots[0].sent == [
        {
            "chat_id": NON_SECRET_VALUES["telegram_chat_id"],
            "text": "halo",
            "parse_mode": "HTML",
            "message_thread_id": 7,
        }
    ]


def test_send_alert_keeps_using_the_env_bot_token_when_nothing_is_overridden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bots = _fake_telegram_bot(monkeypatch)
    install_overlay(monkeypatch, make_settings(keys=KEYS), [])

    alerts_telegram.send_alert("global", "halo")

    assert [bot.token for bot in bots] == [ENV_VALUES[("telegram", "bot_token")]]


def test_the_graph_draft_authenticates_with_the_overridden_client_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = make_row("graph", {"client_secret": DB_GRAPH})
    install_overlay(monkeypatch, make_settings(keys=KEYS), [row])
    app = MagicMock()
    app.acquire_token_for_client.return_value = {"error_description": "stop di sini"}

    with (
        patch("cti_alerts.mailer.msal.ConfidentialClientApplication", return_value=app) as ctor,
        pytest.raises(mailer.GraphAuthError),
    ):
        mailer.create_graph_draft("<html/>", "subject")

    call = ctor.call_args
    assert DB_GRAPH in (*call.args, *call.kwargs.values())
    assert ENV_VALUES[("graph", "client_secret")] not in (*call.args, *call.kwargs.values())
