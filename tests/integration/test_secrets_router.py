"""Router `/api/secrets`: akses, daftar (GET), hapus (DELETE), uji (POST) dan perilaku yang dipakai
bersama endpoint tulis (re-auth password, rate limit) -- ROADMAP #23, PR 2.

Ini endpoint paling sensitif di API: satu sesi superadmin yang dicuri bisa membaca atau memutar
SEMUA key vendor, dan MENULIS lebih buruk daripada membaca (mengarahkan `llm.url` ke host penyerang
mengirim seluruh teks artikel ke sana). Yang dikunci di sini: hanya superadmin, API tidak pernah
mengembalikan nilai secret (response, audit, error), password saat ini wajib untuk tiap tulis/hapus
dan percobaan yang gagal dihitung + diaudit, dan tiap perubahan benar-benar commit.

Lockout password (5 kegagalan, pencabutan sesi, penghitung bersama change-password) ada di
`test_secrets_password_lockout.py`.

PUT (validasi, bundel LLM, probe sebelum simpan, merge) ada di `test_secrets_router_put.py`.
Bahan bersama (`.env` palsu, probe palsu, jembatan overlay): `secrets_router_support.py`.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from cti_core.config import get_settings
from cti_core.db.models.auth import Client
from cti_core.db.models.runtime_secret import RuntimeSecret
from cti_core.runtime_secrets import overlay
from cti_core.runtime_secrets.crypto import encrypt_fields
from cti_core.runtime_secrets.registry import PROVIDERS
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.secrets_router_support import (
    ENTRY_KEYS,
    FIELD_KEYS,
    NEW_NVD,
    OLD_NVD,
    PASSWORD,
    ROOT,
    Ctx,
    assert_no_value,
    open_ctx,
)
from tests.unit.runtime_secrets_helpers import ENV_VALUES, KEYS, NON_SECRET_VALUES, OTHER_KEYS

pytestmark = pytest.mark.asyncio

DB_LLM_KEY = "fake-llm-key-stored-in-db-0001"
DB_GITHUB = "fake-github-token-stored-in-db-0002"


@pytest.fixture
async def ctx(
    api_client: AsyncClient,
    api_session: AsyncSession,
    auth_header: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    fake_redis: Any,
) -> AsyncIterator[Ctx]:
    async with open_ctx(api_client, api_session, auth_header, monkeypatch, fake_redis) as context:
        yield context


def put_request(password: str = PASSWORD) -> tuple[str, str, dict[str, Any]]:
    return (
        "PUT",
        "/api/secrets/nvd",
        {"fields": {"api_key": NEW_NVD}, "current_password": password},
    )


def delete_request(password: str = PASSWORD) -> tuple[str, str, dict[str, Any]]:
    return "DELETE", "/api/secrets/nvd", {"current_password": password}


WRITES = [pytest.param(put_request, id="put"), pytest.param(delete_request, id="delete")]
ENDPOINTS = [
    pytest.param("GET", "/api/secrets", None, id="list"),
    pytest.param("PUT", "/api/secrets/nvd", put_request()[2], id="put"),
    pytest.param("DELETE", "/api/secrets/nvd", delete_request()[2], id="delete"),
    pytest.param("POST", "/api/secrets/nvd/test", None, id="test"),
]


# --- akses: hanya superadmin ------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
async def test_a_request_without_a_token_is_unauthorized(
    ctx: Ctx, method: str, path: str, body: Any
) -> None:
    resp = await ctx.request(method, path, body, headers={})

    assert resp.status_code == 401


@pytest.mark.parametrize("role", ["admin", "analyst"])
@pytest.mark.parametrize(("method", "path", "body"), ENDPOINTS)
async def test_a_role_below_superadmin_is_forbidden_and_nothing_happens(
    ctx: Ctx, method: str, path: str, body: Any, role: str
) -> None:
    await ctx.seed("nvd")

    resp = await ctx.request(method, path, body, headers=ctx.headers("someone", role))

    assert resp.status_code == 403
    assert ctx.probe.calls == []
    assert await ctx.stored("nvd") == {"api_key": OLD_NVD}
    assert await ctx.audit("secret_set") == []
    assert await ctx.audit("secret_clear") == []
    assert await ctx.audit("secret_test") == []


# --- GET: bentuk ------------------------------------------------------------------------------


async def test_get_returns_one_entry_per_registry_provider_in_registry_order(ctx: Ctx) -> None:
    resp = await ctx.get()

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"enabled", "providers"}
    assert [entry["key"] for entry in body["providers"]] == list(PROVIDERS)
    for entry in body["providers"]:
        assert set(entry) == ENTRY_KEYS
        assert entry["label"] == PROVIDERS[entry["key"]].label


async def test_get_describes_every_registry_field_with_its_secret_flag_and_choices(
    ctx: Ctx,
) -> None:
    body = (await ctx.get()).json()

    for entry in body["providers"]:
        specs = {f.name: f for f in PROVIDERS[entry["key"]].fields}
        assert {f["name"] for f in entry["fields"]} == set(specs)
        for field in entry["fields"]:
            assert set(field) == FIELD_KEYS
            assert field["secret"] is specs[field["name"]].secret
            assert field["choices"] == list(specs[field["name"]].choices)


async def test_get_enabled_is_true_when_a_master_key_is_configured(ctx: Ctx) -> None:
    assert (await ctx.get()).json()["enabled"] is True


async def test_get_enabled_is_false_without_a_master_key_but_still_lists_the_providers(
    ctx: Ctx,
) -> None:
    ctx.configure(SECRETS_ENCRYPTION_KEYS="")

    resp = await ctx.get()

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert [entry["key"] for entry in body["providers"]] == list(PROVIDERS)


# --- GET: sumber (env / unset / db) -----------------------------------------------------------


async def test_get_marks_every_provider_and_field_as_env_when_nothing_is_overridden(
    ctx: Ctx,
) -> None:
    body = (await ctx.get()).json()

    for entry in body["providers"]:
        assert entry["source"] == "env", entry["key"]
        assert {f["source"] for f in entry["fields"]} == {"env"}, entry["key"]
        assert entry["updated_by"] is None
        assert entry["updated_at"] is None
        assert entry["last_test_ok"] is None
        assert entry["last_test_at"] is None
        assert entry["error"] is None
        assert entry["probe"] is None  # hanya respons PUT yang membawa hasil probe


async def test_get_marks_a_provider_with_an_empty_env_key_as_unset(ctx: Ctx) -> None:
    ctx.configure(NVD__API_KEY="")

    nvd = await ctx.entry("nvd")

    assert nvd["source"] == "unset"
    (field,) = nvd["fields"]
    assert (field["source"], field["value"], field["last4"]) == ("unset", None, None)
    assert (await ctx.entry("github"))["source"] == "env"  # provider lain tidak ikut berubah


async def test_get_secret_fields_never_carry_a_value_and_show_the_last_four_of_env_keys(
    ctx: Ctx,
) -> None:
    body = (await ctx.get()).json()

    for entry in body["providers"]:
        for field in entry["fields"]:
            if field["secret"]:
                env_value = ENV_VALUES[(entry["key"], field["name"])]
                assert field["value"] is None
                assert field["last4"] == env_value[-4:]


async def test_get_non_secret_fields_show_the_effective_value(ctx: Ctx) -> None:
    llm = {f["name"]: f for f in (await ctx.entry("llm"))["fields"]}

    assert llm["provider"]["value"] == "openai"
    assert llm["model"]["value"] == NON_SECRET_VALUES["llm_model"]
    assert llm["url"]["value"] == NON_SECRET_VALUES["llm_url"]
    assert llm["provider"]["choices"] == ["openai", "deepseek", "gemini"]
    assert llm["provider"]["last4"] is None  # last4 hanya untuk field secret


async def test_get_shows_a_db_override_as_db_with_who_and_when(ctx: Ctx) -> None:
    tested_at = datetime.datetime(2026, 10, 16, 8, 30, tzinfo=datetime.UTC)
    await ctx.seed(
        "nvd", {"api_key": OLD_NVD}, updated_by="alice", last_test_ok=True, last_test_at=tested_at
    )

    nvd = await ctx.entry("nvd")

    assert nvd["source"] == "db"
    assert nvd["updated_by"] == "alice"
    assert datetime.datetime.fromisoformat(nvd["updated_at"])
    assert nvd["last_test_ok"] is True
    assert datetime.datetime.fromisoformat(nvd["last_test_at"]) == tested_at
    assert nvd["error"] is None
    assert (await ctx.entry("github"))["source"] == "env"


async def test_get_shows_a_failed_last_test(ctx: Ctx) -> None:
    tested_at = datetime.datetime(2026, 10, 16, 8, 30, tzinfo=datetime.UTC)
    await ctx.seed("nvd", last_test_ok=False, last_test_at=tested_at)

    assert (await ctx.entry("nvd"))["last_test_ok"] is False


async def test_get_marks_every_field_of_an_overridden_provider_as_db(ctx: Ctx) -> None:
    fields = {"api_key": DB_LLM_KEY, "provider": "deepseek", "model": "model-db-1", "url": ""}
    await ctx.seed("llm", fields)

    llm = {f["name"]: f for f in (await ctx.entry("llm"))["fields"]}

    assert {f["source"] for f in llm.values()} == {"db"}
    assert llm["provider"]["value"] == "deepseek"
    assert llm["model"]["value"] == "model-db-1"


async def test_get_an_empty_non_secret_override_is_a_real_db_value_not_unset(ctx: Ctx) -> None:
    """`llm.url=""` berarti "pakai default vendor" dan menimpa URL gateway yang ada di `.env`."""
    await ctx.seed("llm", {"provider": "openai", "model": "m", "url": ""})

    url = {f["name"]: f for f in (await ctx.entry("llm"))["fields"]}["url"]

    assert url["source"] == "db"
    assert url["value"] == ""


async def test_get_a_field_missing_from_the_override_keeps_the_env_source(ctx: Ctx) -> None:
    await ctx.seed("llm", {"provider": "deepseek", "model": "m", "url": ""})

    llm = await ctx.entry("llm")

    fields = {f["name"]: f for f in llm["fields"]}
    assert llm["source"] == "db"
    assert fields["api_key"]["source"] == "env"
    assert fields["provider"]["source"] == "db"


async def test_get_last4_of_a_db_secret_comes_from_the_db_value_not_the_env(ctx: Ctx) -> None:
    await ctx.seed("nvd", {"api_key": "fake-nvd-key-stored-in-db-0003"})

    (field,) = (await ctx.entry("nvd"))["fields"]

    assert field["last4"] == "0003"
    assert field["value"] is None


@pytest.mark.parametrize(
    ("secret", "last4"),
    [("abcdef012345", "2345"), ("abcdef01234", None), ("abc123", None)],
    ids=["12-chars", "11-chars", "6-chars"],
)
async def test_get_last4_appears_only_for_db_secrets_of_12_or_more_characters(
    ctx: Ctx, secret: str, last4: str | None
) -> None:
    await ctx.seed("nvd", {"api_key": secret})

    (field,) = (await ctx.entry("nvd"))["fields"]

    assert field["last4"] == last4


async def test_get_flags_an_unreadable_override_and_falls_back_to_env(ctx: Ctx) -> None:
    await ctx.seed_unreadable("nvd")

    body = (await ctx.get()).json()

    nvd = next(p for p in body["providers"] if p["key"] == "nvd")
    assert nvd["error"] == "decrypt_failed"
    assert nvd["source"] == "env"
    assert {f["source"] for f in nvd["fields"]} == {"env"}
    assert [p["key"] for p in body["providers"] if p["error"] is not None] == ["nvd"]


async def test_get_without_a_master_key_still_reads_the_rows_and_flags_each_one(ctx: Ctx) -> None:
    """Baris yang ada tetap tampil (admin bisa membersihkannya), tapi tidak dianggap aktif."""
    await ctx.seed("nvd", updated_by="alice")
    ctx.configure(SECRETS_ENCRYPTION_KEYS="")

    body = (await ctx.get()).json()

    nvd = next(p for p in body["providers"] if p["key"] == "nvd")
    assert body["enabled"] is False
    assert nvd["error"] == "master_key_missing"
    assert nvd["source"] == "env"  # bukan "db": override tidak berlaku tanpa master key
    assert {f["source"] for f in nvd["fields"]} == {"env"}
    assert nvd["updated_by"] == "alice"
    assert nvd["updated_at"] is not None
    assert [p["key"] for p in body["providers"] if p["error"] is not None] == ["nvd"]


async def test_get_shows_the_env_llm_url_without_userinfo_or_query(ctx: Ctx) -> None:
    """Nilai `.env` tidak divalidasi seketat override, jadi bisa memuat kredensial atau token."""
    ctx.configure(LLM__URL="https://svc:pw-Zz9y8x@gw.example.com/v1?key=qk-4f3e2d")

    resp = await ctx.get()

    llm = next(p for p in resp.json()["providers"] if p["key"] == "llm")
    url = {f["name"]: f for f in llm["fields"]}["url"]
    assert url["value"] == "https://gw.example.com/v1"
    assert_no_value(resp.text, "pw-Zz9y8x", "qk-4f3e2d")


async def test_get_ignores_workspace_scoped_rows(ctx: Ctx) -> None:
    ctx.session.add(Client(client_id="rs-acme", name="Acme"))
    await ctx.session.flush()
    ctx.session.add(
        RuntimeSecret(
            provider="nvd",
            client_id="rs-acme",
            secrets_enc=encrypt_fields("nvd", {"api_key": OLD_NVD}, client_id="rs-acme", keys=KEYS),
            updated_by="client-admin",
        )
    )
    await ctx.session.flush()

    nvd = await ctx.entry("nvd")

    assert nvd["source"] == "env"
    assert nvd["updated_by"] is None


async def test_get_never_serializes_a_secret_value_from_the_db_the_env_or_the_master_key(
    ctx: Ctx,
) -> None:
    await ctx.seed("llm", {"api_key": DB_LLM_KEY, "provider": "openai", "model": "m", "url": ""})
    await ctx.seed("github", {"token": DB_GITHUB})
    await ctx.seed_unreadable("telegram")
    secrets = [
        *ENV_VALUES.values(),
        DB_LLM_KEY,
        DB_GITHUB,
        "fake-unreadable-key-0004",
        KEYS,
        OTHER_KEYS,
        get_settings().auth.jwt_secret,
    ]

    resp = await ctx.get()

    assert resp.status_code == 200
    assert_no_value(resp.text, *secrets)
    assert_no_value(json.dumps(resp.json()), *secrets)


# --- DELETE -----------------------------------------------------------------------------------


async def test_delete_removes_the_override_and_reports_the_env_source(ctx: Ctx) -> None:
    await ctx.seed("nvd")

    resp = await ctx.delete("nvd")

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == ENTRY_KEYS
    assert body["key"] == "nvd"
    assert body["source"] == "env"
    assert {f["source"] for f in body["fields"]} == {"env"}
    assert body["updated_by"] is None
    assert body["probe"] is None
    assert await ctx.row("nvd") is None


async def test_delete_reports_unset_when_the_env_has_no_key_either(ctx: Ctx) -> None:
    ctx.configure(NVD__API_KEY="")
    await ctx.seed("nvd")

    resp = await ctx.delete("nvd")

    assert resp.status_code == 200
    assert resp.json()["source"] == "unset"


async def test_delete_response_equals_the_entry_a_later_get_returns(ctx: Ctx) -> None:
    await ctx.seed("nvd")

    resp = await ctx.delete("nvd")

    assert resp.json() == await ctx.entry("nvd")


async def test_delete_works_without_a_master_key(ctx: Ctx) -> None:
    """Master key hilang: admin tetap harus bisa membersihkan baris yang tidak terbaca."""
    await ctx.seed("nvd")
    ctx.configure(SECRETS_ENCRYPTION_KEYS="")

    resp = await ctx.delete("nvd")

    assert resp.status_code == 200
    assert resp.json()["error"] is None
    assert await ctx.row("nvd") is None


async def test_delete_only_removes_the_named_provider(ctx: Ctx) -> None:
    await ctx.seed("nvd")
    await ctx.seed("github", {"token": DB_GITHUB})

    await ctx.delete("nvd")

    assert await ctx.stored("github") == {"token": DB_GITHUB}


async def test_delete_is_404_when_there_is_no_override(ctx: Ctx) -> None:
    resp = await ctx.delete("nvd")

    assert resp.status_code == 404


async def test_delete_of_an_unknown_provider_is_404(ctx: Ctx) -> None:
    resp = await ctx.delete("tidak-ada")

    assert resp.status_code == 404


async def test_delete_can_remove_an_override_that_can_no_longer_be_decrypted(ctx: Ctx) -> None:
    """Satu-satunya jalan keluar dari baris yang rusak (master key salah/rotasi lupa)."""
    await ctx.seed_unreadable("nvd")

    resp = await ctx.delete("nvd")

    assert resp.status_code == 200
    assert resp.json()["error"] is None
    assert await ctx.row("nvd") is None


async def test_delete_writes_a_secret_clear_audit_row_without_any_value(ctx: Ctx) -> None:
    await ctx.seed("nvd")

    await ctx.delete("nvd")

    (entry,) = await ctx.audit("secret_clear")
    assert entry.username == ROOT
    assert entry.target_id == "nvd"
    assert entry.ip_address
    assert_no_value(await ctx.audit_text("secret_clear"), OLD_NVD, PASSWORD)


async def test_delete_commits_the_removal_and_the_audit_row(ctx: Ctx) -> None:
    await ctx.seed("nvd")

    await ctx.delete("nvd")

    assert ctx.commits >= 1


async def test_delete_invalidates_the_overlay_cache(ctx: Ctx) -> None:
    await ctx.seed("nvd")
    assert overlay.effective_settings().nvd.api_key == OLD_NVD  # mengisi cache dengan override

    await ctx.delete("nvd")
    await ctx.sync_overlay()

    assert overlay.effective_settings().nvd.api_key == ENV_VALUES[("nvd", "api_key")]


# --- re-auth password (PUT dan DELETE) --------------------------------------------------------


@pytest.mark.parametrize("build", WRITES)
async def test_a_wrong_password_is_refused_with_403(ctx: Ctx, build: Any) -> None:
    await ctx.seed("nvd")

    resp = await ctx.request(*build("wrong-password-1"))

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Password confirmation failed"


@pytest.mark.parametrize("build", WRITES)
async def test_a_wrong_password_leaves_the_override_untouched_and_skips_the_probe(
    ctx: Ctx, build: Any
) -> None:
    await ctx.seed("nvd")

    await ctx.request(*build("wrong-password-1"))

    row = await ctx.row("nvd")
    assert row is not None
    assert row.updated_by == "seeder"
    assert await ctx.stored("nvd") == {"api_key": OLD_NVD}
    assert ctx.probe.calls == []
    assert await ctx.audit("secret_set") == []
    assert await ctx.audit("secret_clear") == []


@pytest.mark.parametrize("build", WRITES)
async def test_a_wrong_password_is_audited_without_the_attempt_or_any_secret(
    ctx: Ctx, build: Any
) -> None:
    await ctx.seed("nvd")

    await ctx.request(*build("wrong-password-1"))

    (entry,) = await ctx.audit("secret_reauth_failed")
    assert entry.username == ROOT
    assert entry.ip_address
    assert_no_value(
        await ctx.audit_text("secret_reauth_failed"), "wrong-password-1", PASSWORD, NEW_NVD, OLD_NVD
    )


@pytest.mark.parametrize("build", WRITES)
async def test_the_reauth_failure_audit_row_is_committed_before_the_403(
    ctx: Ctx, build: Any
) -> None:
    """Kalau handler cuma flush lalu raise, baris audit ikut di-rollback bersama request."""
    await ctx.seed("nvd")

    await ctx.request(*build("wrong-password-1"))

    assert ctx.commits >= 1


@pytest.mark.parametrize("build", WRITES)
async def test_a_user_without_a_local_password_is_forbidden(ctx: Ctx, build: Any) -> None:
    """Login lewat OIDC saja: tidak ada password lokal yang bisa dipakai buat konfirmasi."""
    await ctx.add_user("sso-admin", password_hash="")
    await ctx.seed("nvd")

    resp = await ctx.request(*build(), headers=ctx.headers("sso-admin"))

    assert resp.status_code == 403
    assert await ctx.stored("nvd") == {"api_key": OLD_NVD}
    assert ctx.probe.calls == []


@pytest.mark.parametrize("build", WRITES)
async def test_a_write_without_the_password_field_is_rejected(ctx: Ctx, build: Any) -> None:
    await ctx.seed("nvd")
    method, path, body = build()
    body.pop("current_password")

    resp = await ctx.request(method, path, body)

    assert resp.status_code == 422
    assert await ctx.stored("nvd") == {"api_key": OLD_NVD}


# --- rate limit (PUT dan DELETE: 5 per menit per user) ----------------------------------------


@pytest.mark.parametrize("build", WRITES)
async def test_the_sixth_write_request_within_a_minute_is_rate_limited(
    ctx: Ctx, build: Any
) -> None:
    for _ in range(5):
        assert (await ctx.request(*build())).status_code != 429

    resp = await ctx.request(*build())

    assert resp.status_code == 429


@pytest.mark.parametrize("build", WRITES)
async def test_the_write_limit_is_per_user(ctx: Ctx, build: Any) -> None:
    await ctx.add_user("second-admin")
    for _ in range(6):
        await ctx.request(*build())  # budget root habis

    resp = await ctx.request(*build(), headers=ctx.headers("second-admin"))

    assert resp.status_code != 429


async def test_the_rate_limit_is_checked_before_the_provider_lookup(ctx: Ctx) -> None:
    for _ in range(5):
        assert (await ctx.put("tidak-ada", {"api_key": NEW_NVD})).status_code == 404

    resp = await ctx.put("tidak-ada", {"api_key": NEW_NVD})

    assert resp.status_code == 429


# --- POST /test -------------------------------------------------------------------------------


async def test_test_returns_the_probe_status_and_detail(ctx: Ctx) -> None:
    ctx.probe.respond("OK", "key diterima vendor")

    resp = await ctx.run_test("nvd")

    assert resp.status_code == 200
    assert resp.json() == {"status": "OK", "detail": "key diterima vendor"}


async def test_test_reports_a_failed_probe_in_the_body_not_as_an_http_error(ctx: Ctx) -> None:
    ctx.probe.respond("FAIL", "ditolak (HTTP 401)")

    resp = await ctx.run_test("nvd")

    assert resp.status_code == 200
    assert resp.json() == {"status": "FAIL", "detail": "ditolak (HTTP 401)"}


async def test_test_probes_the_provider_it_was_asked_for(ctx: Ctx) -> None:
    await ctx.run_test("github")

    assert [provider for provider, _ in ctx.probe.calls] == ["github"]


async def test_test_probes_the_env_configuration_when_there_is_no_override(ctx: Ctx) -> None:
    await ctx.run_test("nvd")

    ((_, settings),) = ctx.probe.calls
    assert settings.nvd.api_key == ENV_VALUES[("nvd", "api_key")]


async def test_test_probes_the_effective_configuration_with_the_db_override(ctx: Ctx) -> None:
    await ctx.seed("nvd", {"api_key": OLD_NVD})

    await ctx.run_test("nvd")

    ((_, settings),) = ctx.probe.calls
    assert settings.nvd.api_key == OLD_NVD
    assert settings.github.token == ENV_VALUES[("github", "token")]


async def test_test_does_not_need_a_password_or_a_request_body(ctx: Ctx) -> None:
    resp = await ctx.client.post("/api/secrets/nvd/test", headers=ctx.auth)

    assert resp.status_code == 200


@pytest.mark.parametrize(("status", "ok"), [("OK", True), ("FAIL", False)])
async def test_test_stores_the_result_on_the_override_row(ctx: Ctx, status: str, ok: bool) -> None:
    await ctx.seed("nvd")
    ctx.probe.respond(status)

    await ctx.run_test("nvd")

    row = await ctx.row("nvd")
    assert row is not None
    assert row.last_test_ok is ok
    assert row.last_test_at is not None
    assert datetime.datetime.now(datetime.UTC) - row.last_test_at < datetime.timedelta(minutes=1)
    assert await ctx.stored("nvd") == {"api_key": OLD_NVD}  # key tidak ikut berubah
    assert ctx.commits >= 1


@pytest.mark.parametrize("status", ["NOTE", "SKIP"])
async def test_test_does_not_record_a_note_or_a_skip_as_a_tested_result(
    ctx: Ctx, status: str
) -> None:
    """NOTE (kena batas pemakaian) bukan bukti key valid, dan SKIP tidak mengetes apa pun."""
    tested_at = datetime.datetime(2026, 10, 16, 8, 30, tzinfo=datetime.UTC)
    await ctx.seed("nvd", last_test_ok=True, last_test_at=tested_at)
    ctx.probe.respond(status)

    resp = await ctx.run_test("nvd")

    assert resp.status_code == 200
    assert resp.json()["status"] == status
    row = await ctx.row("nvd")
    assert row is not None
    assert row.last_test_ok is True
    assert row.last_test_at == tested_at


async def test_test_does_not_record_a_result_on_an_override_that_cannot_be_read(ctx: Ctx) -> None:
    """Yang diprobe adalah `.env` (override tak terbaca), jadi hasilnya bukan milik baris itu."""
    await ctx.seed_unreadable("nvd")
    ctx.probe.respond("OK")

    await ctx.run_test("nvd")

    row = await ctx.row("nvd")
    assert row is not None
    assert row.last_test_ok is None
    assert row.last_test_at is None


async def test_test_without_an_override_row_creates_no_row(ctx: Ctx) -> None:
    await ctx.run_test("nvd")

    assert await ctx.count_rows() == 0


async def test_test_writes_a_secret_test_audit_row_with_only_the_status(ctx: Ctx) -> None:
    ctx.probe.respond("FAIL", f"detail yang memuat {OLD_NVD}")

    await ctx.run_test("nvd")

    (entry,) = await ctx.audit("secret_test")
    assert entry.username == ROOT
    assert entry.target_id == "nvd"
    assert entry.detail == {"status": "FAIL"}
    assert entry.ip_address


async def test_test_of_an_unknown_provider_is_404_and_runs_no_probe(ctx: Ctx) -> None:
    resp = await ctx.run_test("tidak-ada")

    assert resp.status_code == 404
    assert ctx.probe.calls == []


async def test_the_eleventh_test_request_within_a_minute_is_rate_limited(ctx: Ctx) -> None:
    for _ in range(10):
        assert (await ctx.run_test("nvd")).status_code == 200

    resp = await ctx.run_test("nvd")

    assert resp.status_code == 429
    assert len(ctx.probe.calls) == 10


# --- POST /test: cooldown provider berkuota ---------------------------------------------------


@pytest.mark.parametrize("provider", ["abuseipdb", "virustotal", "otx"])
async def test_a_second_test_of_a_quota_bound_provider_within_30_seconds_is_refused(
    ctx: Ctx, provider: str
) -> None:
    """Tiap tes memakai satu lookup dari kuota harian vendor (OTX: jatah per jam)."""
    first = await ctx.run_test(provider)

    second = await ctx.run_test(provider)

    assert first.status_code == 200
    assert second.status_code == 429
    assert [p for p, _ in ctx.probe.calls] == [provider]


async def test_the_test_cooldown_is_per_provider(ctx: Ctx) -> None:
    await ctx.run_test("abuseipdb")

    resp = await ctx.run_test("virustotal")

    assert resp.status_code == 200


@pytest.mark.parametrize("provider", ["nvd", "github", "twitter", "x", "telegram", "llm", "graph"])
async def test_a_provider_without_a_daily_quota_has_no_test_cooldown(
    ctx: Ctx, provider: str
) -> None:
    await ctx.run_test(provider)

    resp = await ctx.run_test(provider)

    assert resp.status_code == 200
