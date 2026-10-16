"""`PUT /api/secrets/{provider}` -- simpan override key dari halaman admin (ROADMAP #23, PR 2).

Urutan pemeriksaan yang dikunci (tiap pasangan bertetangga punya tes): auth -> rate limit ->
provider tak dikenal (404) -> master key kosong (503) -> password (403) -> validasi field (422) ->
gabung dengan override lama (409 kalau tak terbaca) -> probe kandidat (422 kalau FAIL) -> enkripsi,
simpan, invalidate, audit, commit. Penolakan SESUDAH password benar (422/409/probe FAIL) tetap
diaudit (`secret_set_rejected`) dan ter-commit; PUT yang tidak mengubah apa pun (nilai sama) tidak
memicu probe, tulis, atau audit.

Yang paling penting dari sisi keamanan: nilai tidak pernah tersimpan atau kembali sebagai plaintext
(DB, response, audit, pesan error), key tidak pernah dikirim ke URL LLM yang masih berasal dari
`.env` (aturan bundel `llm`), dan key yang gagal probe tidak pernah tersimpan. Akses, re-auth
password dan rate limit yang dipakai bersama DELETE dites di `test_secrets_router.py`.
"""

from __future__ import annotations

import datetime
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from cti_core.config import Settings, get_settings
from cti_core.runtime_secrets import overlay
from cti_core.runtime_secrets.registry import PROVIDERS
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.secrets_router_support import (
    ENTRY_KEYS,
    LLM_BUNDLE,
    NEW_LLM_KEY,
    NEW_NVD,
    OLD_LLM_BUNDLE,
    OLD_LLM_KEY,
    OLD_NVD,
    PASSWORD,
    ROOT,
    Ctx,
    assert_no_value,
    open_ctx,
)
from tests.unit.runtime_secrets_helpers import ENV_VALUES, NON_SECRET_VALUES

pytestmark = pytest.mark.asyncio

ALLOWED_HOST = "gw.allowed.example.com"
SECRET_FIELDS = [
    (key, field.name) for key, p in PROVIDERS.items() for field in p.fields if field.secret
]


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


def bundle(**over: Any) -> dict[str, Any]:
    """Isian `llm` yang sah (provider, model, url, dan key baru), dengan sebagian diganti."""
    return {**LLM_BUNDLE, **over}


def fields_with(provider: str, name: str, value: Any) -> dict[str, Any]:
    """Isian sah buat `provider` dengan satu field diganti `value` (llm butuh bundelnya)."""
    base = dict(LLM_BUNDLE) if provider == "llm" else {}
    return {**base, name: value}


async def assert_rejected(ctx: Ctx, resp: Any, provider: str = "nvd", status: int = 422) -> None:
    """Ditolak: status benar, tidak ada probe, tidak ada baris tersimpan, tidak ada audit tulis."""
    assert resp.status_code == status, resp.text
    assert ctx.probe.calls == []
    assert await ctx.row(provider) is None
    assert await ctx.audit("secret_set") == []


# --- sukses: yang tersimpan dan yang dikembalikan ---------------------------------------------


async def test_put_stores_the_override_and_returns_the_provider_status(ctx: Ctx) -> None:
    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == ENTRY_KEYS
    assert body["key"] == "nvd"
    assert body["label"] == "NVD"
    assert body["source"] == "db"
    assert body["updated_by"] == ROOT
    assert body["updated_at"] is not None
    assert body["error"] is None
    assert body["probe"] == {"status": "OK", "detail": "probe palsu"}
    assert body["fields"] == [
        {
            "name": "api_key",
            "secret": True,
            "source": "db",
            "value": None,
            "last4": "Q7w2",
            "choices": [],
        }
    ]
    assert await ctx.stored("nvd") == {"api_key": NEW_NVD}


async def test_put_response_equals_the_entry_a_later_get_returns_plus_the_probe(ctx: Ctx) -> None:
    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    entry = await ctx.entry("nvd")
    assert entry["probe"] is None  # hasil probe hanya dibawa respons PUT
    assert resp.json() == {**entry, "probe": {"status": "OK", "detail": "probe palsu"}}


async def test_put_marks_only_that_provider_as_db(ctx: Ctx) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    body = (await ctx.get()).json()

    assert {p["key"]: p["source"] for p in body["providers"]} == {
        key: ("db" if key == "nvd" else "env") for key in PROVIDERS
    }


async def test_put_response_never_contains_the_new_value_or_the_password(ctx: Ctx) -> None:
    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    assert_no_value(resp.text, NEW_NVD, PASSWORD, ENV_VALUES[("nvd", "api_key")])


async def test_put_stores_the_value_encrypted_never_as_plaintext(ctx: Ctx) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    row = await ctx.row("nvd")
    assert row is not None
    raw = bytes(row.secrets_enc)
    whole_row = await ctx.raw_row_text("nvd")
    assert NEW_NVD.encode() not in raw
    assert NEW_NVD not in whole_row
    assert NEW_NVD.encode().hex() not in whole_row
    assert "nvd" in whole_row  # kontrol positif: query benar-benar melihat barisnya


async def test_put_twice_keeps_one_row_with_the_latest_value_and_author(ctx: Ctx) -> None:
    await ctx.add_user("second-admin")
    await ctx.put("nvd", {"api_key": OLD_NVD})

    resp = await ctx.put("nvd", {"api_key": NEW_NVD}, headers=ctx.headers("second-admin"))

    assert resp.status_code == 200
    assert await ctx.count_rows() == 1
    assert await ctx.stored("nvd") == {"api_key": NEW_NVD}
    row = await ctx.row("nvd")
    assert row is not None
    assert row.updated_by == "second-admin"


async def test_put_commits_the_change(ctx: Ctx) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    assert ctx.commits >= 1


async def test_put_makes_the_new_value_effective_without_waiting_for_the_cache_ttl(
    ctx: Ctx,
) -> None:
    """Cache overlay (30 dtk) diisi dulu dengan keadaan sebelum PUT; hanya `invalidate()` dari
    router yang membuat pembacaan berikutnya mengambil ulang."""
    assert overlay.effective_settings().nvd.api_key == ENV_VALUES[("nvd", "api_key")]

    resp = await ctx.put("nvd", {"api_key": NEW_NVD})
    await ctx.sync_overlay()

    assert resp.status_code == 200
    assert overlay.effective_settings().nvd.api_key == NEW_NVD


# --- audit ------------------------------------------------------------------------------------


async def test_put_writes_one_secret_set_audit_row_with_the_changed_field_names(
    ctx: Ctx,
) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    (entry,) = await ctx.audit("secret_set")
    assert entry.username == ROOT
    assert entry.target_id == "nvd"
    assert entry.detail == {"fields": ["api_key"], "values": {}}
    assert entry.ip_address


async def test_put_audit_records_the_values_of_changed_non_secret_fields_only(ctx: Ctx) -> None:
    """Forensik perlu tahu ke gateway mana key diarahkan; nilai secret tidak pernah dicatat."""
    await ctx.put("llm", bundle())

    (entry,) = await ctx.audit("secret_set")
    assert entry.detail == {
        "fields": ["api_key", "model", "provider", "url"],
        "values": {"model": "deepseek-chat", "provider": "deepseek", "url": ""},
    }


async def test_put_audit_covers_only_the_fields_that_actually_changed(ctx: Ctx) -> None:
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    await ctx.put("llm", {**OLD_LLM_BUNDLE, "model": "model-new-aaaaaa"})

    (entry,) = await ctx.audit("secret_set")
    assert entry.detail == {"fields": ["model"], "values": {"model": "model-new-aaaaaa"}}


async def test_put_audit_has_no_last4_of_any_key(ctx: Ctx) -> None:
    await ctx.put("llm", bundle())

    (entry,) = await ctx.audit("secret_set")
    assert "last4" not in entry.detail
    assert_no_value(await ctx.audit_text("secret_set"), NEW_LLM_KEY, NEW_LLM_KEY[-4:])


async def test_put_audit_row_never_contains_a_secret_value(ctx: Ctx) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    assert_no_value(await ctx.audit_text("secret_set"), NEW_NVD, PASSWORD)


# --- probe kandidat ---------------------------------------------------------------------------


async def test_put_probes_the_provider_with_the_candidate_settings_holding_the_new_value(
    ctx: Ctx,
) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    ((provider, settings),) = ctx.probe.calls
    assert provider == "nvd"
    assert settings.nvd.api_key == NEW_NVD
    assert settings.github.token == ENV_VALUES[("github", "token")]  # sisanya tetap dari .env


async def test_put_probes_before_anything_is_stored(ctx: Ctx) -> None:
    seen: dict[str, Any] = {}

    async def hook(provider: str, settings: Settings) -> None:
        seen["row_during_probe"] = await ctx.row(provider)
        seen["audit_during_probe"] = await ctx.audit("secret_set")

    ctx.probe.hook = hook

    await ctx.put("nvd", {"api_key": NEW_NVD})

    assert seen == {"row_during_probe": None, "audit_during_probe": []}


async def test_put_does_not_mutate_the_cached_base_settings(ctx: Ctx) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    assert get_settings().nvd.api_key == ENV_VALUES[("nvd", "api_key")]


async def test_put_probes_the_merged_llm_override_not_the_env_gateway(ctx: Ctx) -> None:
    """Hanya key yang dikirim, tapi model dan url override yang sudah ada ikut ke probe: key baru
    tidak boleh dites (atau dikirim) ke URL gateway yang masih di `.env`."""
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    await ctx.put("llm", {"api_key": NEW_LLM_KEY})

    ((_, settings),) = ctx.probe.calls
    assert settings.llm.api_key == NEW_LLM_KEY
    assert settings.llm.model == OLD_LLM_BUNDLE["model"]
    assert settings.llm.model != NON_SECRET_VALUES["llm_model"]
    assert settings.llm.url == ""
    assert settings.llm.provider == OLD_LLM_BUNDLE["provider"]


@pytest.mark.parametrize(
    ("status", "last_test_ok"), [("OK", True), ("NOTE", None), ("SKIP", None)], ids=str
)
async def test_put_stores_a_probe_that_did_not_fail_and_records_only_an_ok_as_tested(
    ctx: Ctx, status: str, last_test_ok: bool | None
) -> None:
    ctx.probe.respond(status)

    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    assert resp.status_code == 200
    assert resp.json()["last_test_ok"] is last_test_ok
    assert resp.json()["probe"]["status"] == status  # memberi tahu admin key belum terverifikasi
    row = await ctx.row("nvd")
    assert row is not None
    assert row.last_test_ok is last_test_ok
    assert (row.last_test_at is not None) is (last_test_ok is True)
    if last_test_ok:
        assert datetime.datetime.now(datetime.UTC) - row.last_test_at < datetime.timedelta(
            minutes=1
        )


async def test_put_rejects_a_failed_probe_with_the_probe_result_in_the_detail(ctx: Ctx) -> None:
    ctx.probe.respond("FAIL", "ditolak (HTTP 401) -- key salah/dicabut")

    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert set(detail) == {"message", "probe"}
    assert isinstance(detail["message"], str)
    assert detail["message"]
    assert detail["probe"] == {
        "status": "FAIL",
        "detail": "ditolak (HTTP 401) -- key salah/dicabut",
    }


async def test_put_stores_nothing_when_the_probe_fails(ctx: Ctx) -> None:
    ctx.probe.respond("FAIL", "ditolak")

    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    assert resp.status_code == 422
    assert len(ctx.probe.calls) == 1  # probe memang jalan; yang gagal adalah hasilnya
    assert await ctx.row("nvd") is None
    assert await ctx.audit("secret_set") == []


async def test_put_keeps_the_existing_override_and_the_effective_value_when_the_probe_fails(
    ctx: Ctx,
) -> None:
    await ctx.seed("nvd", {"api_key": OLD_NVD})
    ctx.probe.respond("FAIL", "ditolak")

    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    assert resp.status_code == 422
    assert await ctx.stored("nvd") == {"api_key": OLD_NVD}
    row = await ctx.row("nvd")
    assert row is not None
    assert row.updated_by == "seeder"
    assert overlay.effective_settings().nvd.api_key == OLD_NVD


async def test_put_does_not_echo_the_rejected_value_when_the_probe_fails(ctx: Ctx) -> None:
    ctx.probe.respond("FAIL", "ditolak")

    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    assert_no_value(resp.text, NEW_NVD, PASSWORD)


# --- validasi field (422): tidak ada probe, tidak ada yang tersimpan --------------------------


@pytest.mark.parametrize(
    ("provider", "fields"),
    [
        ("nvd", {"bogus": "value-aaaaaa"}),
        ("nvd", {"api_key": NEW_NVD, "extra": "value-aaaaaa"}),
        ("nvd", {"token": "value-aaaaaa"}),  # field milik provider lain
        ("telegram", {"chat_id": "-100123456"}),  # sengaja tidak bisa diatur dari halaman admin
        ("graph", {"tenant_id": "tenant-xyz-aaaaaa"}),  # identitas Graph tetap di .env
        ("llm", bundle(timeout_s="30")),
    ],
    ids=[
        "bogus",
        "known-plus-unknown",
        "other-provider",
        "tg-chat-id",
        "graph-tenant",
        "llm-timeout",
    ],
)
async def test_put_rejects_a_field_that_is_not_in_the_registry(
    ctx: Ctx, provider: str, fields: dict[str, Any]
) -> None:
    resp = await ctx.put(provider, fields)

    await assert_rejected(ctx, resp, provider)


@pytest.mark.parametrize(
    "value",
    [123456789012, True, 1.5, ["sk-test-aaaaaa"], {"k": "sk-test-aaaaaa"}],
    ids=["int", "bool", "float", "list", "object"],
)
async def test_put_rejects_a_value_that_is_neither_a_string_nor_null(ctx: Ctx, value: Any) -> None:
    resp = await ctx.put("nvd", {"api_key": value})

    await assert_rejected(ctx, resp)


@pytest.mark.parametrize("value", ["", "   ", "\t\n"], ids=["empty", "spaces", "tab-newline"])
@pytest.mark.parametrize(("provider", "name"), SECRET_FIELDS)
async def test_put_rejects_a_blank_secret_so_a_working_env_key_is_never_blanked(
    ctx: Ctx, provider: str, name: str, value: str
) -> None:
    resp = await ctx.put(provider, fields_with(provider, name, value))

    await assert_rejected(ctx, resp, provider)


@pytest.mark.parametrize("value", ["anthropic", "OpenAI", ""], ids=["unknown", "case", "empty"])
async def test_put_rejects_an_enum_value_outside_the_choices(ctx: Ctx, value: str) -> None:
    resp = await ctx.put("llm", bundle(provider=value))

    await assert_rejected(ctx, resp, "llm")


async def test_put_accepts_every_llm_provider_choice(ctx: Ctx) -> None:
    choices = next(f.choices for f in PROVIDERS["llm"].fields if f.name == "provider")
    assert choices  # kontrol: registry memang mendefinisikan enum-nya
    for choice in choices:
        resp = await ctx.put("llm", bundle(provider=choice))
        assert resp.status_code == 200, choice
        assert (await ctx.stored("llm") or {})["provider"] == choice


@pytest.mark.parametrize(
    "url",
    [
        "https://user:s3cretpass@gw.example.com/v1",
        "https://",
        "ftp://gw.example.com/v1",
        "gw.example.com/v1",
    ],
    ids=["userinfo", "no-host", "ftp", "no-scheme"],
)
async def test_put_rejects_an_invalid_llm_url_even_in_dev(ctx: Ctx, url: str) -> None:
    resp = await ctx.put("llm", bundle(url=url))

    await assert_rejected(ctx, resp, "llm")
    assert_no_value(resp.text, "s3cretpass")


async def test_put_accepts_any_http_or_https_llm_url_in_dev(ctx: Ctx) -> None:
    resp = await ctx.put("llm", bundle(url="http://localhost:20128/v1"))

    assert resp.status_code == 200
    assert (await ctx.stored("llm") or {})["url"] == "http://localhost:20128/v1"


@pytest.mark.parametrize("environment", ["staging", "prod"])
@pytest.mark.parametrize(
    "url",
    [
        "https://other.example.com/v1",
        f"http://{ALLOWED_HOST}/v1",
        f"https://{ALLOWED_HOST}:8443/v1",
    ],
    ids=["host-not-allowed", "http-not-https", "port-not-443"],
)
async def test_put_rejects_an_llm_url_outside_the_allowlist_when_not_dev(
    ctx: Ctx, environment: str, url: str
) -> None:
    ctx.configure(ENVIRONMENT=environment, SECRETS_LLM_URL_ALLOWED_HOSTS=ALLOWED_HOST)

    resp = await ctx.put("llm", bundle(url=url))

    await assert_rejected(ctx, resp, "llm")


@pytest.mark.parametrize("environment", ["staging", "prod"])
async def test_put_accepts_an_https_llm_url_on_the_allowlist_when_not_dev(
    ctx: Ctx, environment: str
) -> None:
    ctx.configure(
        ENVIRONMENT=environment, SECRETS_LLM_URL_ALLOWED_HOSTS=f"x.example.org, {ALLOWED_HOST}"
    )
    url = f"https://{ALLOWED_HOST}/v1"

    resp = await ctx.put("llm", bundle(url=url))

    assert resp.status_code == 200
    assert (await ctx.stored("llm") or {})["url"] == url


async def test_put_with_an_empty_allowlist_in_prod_refuses_any_custom_llm_url(ctx: Ctx) -> None:
    ctx.configure(ENVIRONMENT="prod", SECRETS_LLM_URL_ALLOWED_HOSTS="")

    resp = await ctx.put("llm", bundle(url=f"https://{ALLOWED_HOST}/v1"))

    await assert_rejected(ctx, resp, "llm")


async def test_put_with_an_empty_allowlist_in_prod_still_accepts_the_vendor_default_url(
    ctx: Ctx,
) -> None:
    """URL kosong = default vendor: provider/model/key tetap bisa diganti walau URL kustom
    tertutup."""
    ctx.configure(ENVIRONMENT="prod", SECRETS_LLM_URL_ALLOWED_HOSTS="")

    resp = await ctx.put("llm", bundle(url=""))

    assert resp.status_code == 200


# --- bundel llm: provider, model, DAN url bersama ---------------------------------------------


@pytest.mark.parametrize("missing", ["provider", "model", "url"])
async def test_put_rejects_an_llm_override_that_lacks_a_bundle_member(
    ctx: Ctx, missing: str
) -> None:
    fields = bundle()
    del fields[missing]

    resp = await ctx.put("llm", fields)

    await assert_rejected(ctx, resp, "llm")


async def test_put_rejects_a_lone_llm_key_without_the_bundle(ctx: Ctx) -> None:
    """Key baru dengan url `.env` yang masih menempel = key vendor terkirim ke gateway lama."""
    resp = await ctx.put("llm", {"api_key": NEW_LLM_KEY})

    await assert_rejected(ctx, resp, "llm")


async def test_put_accepts_the_llm_bundle_with_an_empty_url(ctx: Ctx) -> None:
    resp = await ctx.put("llm", bundle(url=""))

    assert resp.status_code == 200
    assert await ctx.stored("llm") == bundle(url="")
    assert resp.json()["source"] == "db"


async def test_put_accepts_the_llm_bundle_without_a_key(ctx: Ctx) -> None:
    fields = bundle()
    del fields["api_key"]

    resp = await ctx.put("llm", fields)

    assert resp.status_code == 200
    assert await ctx.stored("llm") == fields


async def test_put_accepts_a_lone_llm_key_when_the_existing_override_has_the_bundle(
    ctx: Ctx,
) -> None:
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    resp = await ctx.put("llm", {"api_key": NEW_LLM_KEY})

    assert resp.status_code == 200
    assert await ctx.stored("llm") == {**OLD_LLM_BUNDLE, "api_key": NEW_LLM_KEY}


# --- semantik: set, hapus (null), tidak dikirim = tetap ---------------------------------------


async def test_put_merges_a_partial_update_with_the_existing_override(ctx: Ctx) -> None:
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    resp = await ctx.put("llm", {"model": "model-new-aaaaaa"})

    assert resp.status_code == 200
    assert await ctx.stored("llm") == {**OLD_LLM_BUNDLE, "model": "model-new-aaaaaa"}


async def test_put_null_removes_the_field_from_the_override_so_it_falls_back_to_env(
    ctx: Ctx,
) -> None:
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    resp = await ctx.put("llm", {"api_key": None})

    assert resp.status_code == 200
    expected = {k: v for k, v in OLD_LLM_BUNDLE.items() if k != "api_key"}
    assert await ctx.stored("llm") == expected
    body = resp.json()
    fields = {f["name"]: f for f in body["fields"]}
    assert fields["api_key"]["source"] == "env"
    assert fields["model"]["source"] == "db"
    assert body["source"] == "db"


async def test_put_null_that_would_break_the_llm_bundle_is_rejected(ctx: Ctx) -> None:
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    resp = await ctx.put("llm", {"url": None})

    assert resp.status_code == 422
    assert await ctx.stored("llm") == OLD_LLM_BUNDLE
    assert ctx.probe.calls == []


async def test_put_all_null_removes_the_row_and_the_provider_is_back_on_env(ctx: Ctx) -> None:
    await ctx.seed("nvd", {"api_key": OLD_NVD})

    resp = await ctx.put("nvd", {"api_key": None})

    assert resp.status_code == 200
    assert resp.json()["source"] == "env"
    assert await ctx.row("nvd") is None


async def test_put_nulling_every_llm_field_removes_the_row(ctx: Ctx) -> None:
    """Tiap null sendirian merusak bundel, tapi hasil akhirnya kosong: bukan override sama
    sekali."""
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    resp = await ctx.put("llm", dict.fromkeys(OLD_LLM_BUNDLE))

    assert resp.status_code == 200
    assert resp.json()["source"] == "env"
    assert await ctx.row("llm") is None


async def test_put_on_an_override_that_cannot_be_decrypted_is_a_conflict(ctx: Ctx) -> None:
    """Penggabungan tidak mungkin tanpa isi lama; jalan keluarnya DELETE (revert ke .env)."""
    await ctx.seed_unreadable("llm")
    before = await ctx.row("llm")
    assert before is not None
    before_token = bytes(before.secrets_enc)

    resp = await ctx.put("llm", {"model": "model-new-aaaaaa"})

    assert resp.status_code == 409
    after = await ctx.row("llm")
    assert after is not None
    assert bytes(after.secrets_enc) == before_token
    assert ctx.probe.calls == []
    assert await ctx.audit("secret_set") == []


# --- karakter key, url llm yang divalidasi ulang ---------------------------------------------

BAD_KEYS = {
    "non-ascii": "kunci-" + chr(0xF1) + "-aaaaaa",
    "curly-quotes": "sk-" + chr(0x201C) + "test-aaaaaa" + chr(0x201D),
    "inner-space": "sk-test aaaaaa",
    "inner-newline": "sk-test" + chr(10) + "aaaaaa",
    "inner-tab": "sk-test" + chr(9) + "aaaaaa",
    "control-char": "sk-test" + chr(7) + "aaaaaa",
}


@pytest.mark.parametrize("value", BAD_KEYS.values(), ids=BAD_KEYS.keys())
async def test_put_rejects_a_secret_that_is_not_printable_ascii_without_whitespace(
    ctx: Ctx, value: str
) -> None:
    """Hasil paste ("..." melengkung, newline di tengah) gagal di header HTTP dengan galat samar
    dan tidak pernah sampai ke vendor: tolak di pintu, dengan alasan yang jelas."""
    resp = await ctx.put("nvd", {"api_key": value})

    await assert_rejected(ctx, resp)


@pytest.mark.parametrize(("provider", "name"), SECRET_FIELDS)
async def test_every_secret_field_rejects_a_key_with_inner_whitespace(
    ctx: Ctx, provider: str, name: str
) -> None:
    resp = await ctx.put(provider, fields_with(provider, name, BAD_KEYS["inner-space"]))

    await assert_rejected(ctx, resp, provider)


async def test_put_revalidates_the_stored_llm_url_even_when_the_url_is_not_sent(ctx: Ctx) -> None:
    """Url lama yang hostnya sudah dicabut dari allowlist tidak boleh menerima key baru."""
    ctx.configure(ENVIRONMENT="prod", SECRETS_LLM_URL_ALLOWED_HOSTS=ALLOWED_HOST)
    await ctx.seed("llm", {**OLD_LLM_BUNDLE, "url": "https://revoked.example.org/v1"})

    resp = await ctx.put("llm", {"api_key": NEW_LLM_KEY})

    assert resp.status_code == 422
    assert ctx.probe.calls == []
    assert (await ctx.stored("llm") or {})["api_key"] == OLD_LLM_KEY


async def test_put_accepts_a_key_rotation_while_the_stored_llm_url_is_still_allowed(
    ctx: Ctx,
) -> None:
    ctx.configure(ENVIRONMENT="prod", SECRETS_LLM_URL_ALLOWED_HOSTS=ALLOWED_HOST)
    await ctx.seed("llm", {**OLD_LLM_BUNDLE, "url": f"https://{ALLOWED_HOST}/v1"})

    resp = await ctx.put("llm", {"api_key": NEW_LLM_KEY})

    assert resp.status_code == 200
    assert (await ctx.stored("llm") or {})["api_key"] == NEW_LLM_KEY


async def test_put_trusts_an_llm_url_identical_to_the_one_in_env_even_off_the_allowlist(
    ctx: Ctx,
) -> None:
    """`LLM__URL` di `.env` konfigurasi operator yang sudah dipercaya: tanpa pengecualian ini key
    tidak bisa dirotasi di host yang memakai gateway dari `.env` (paket llm selalu membawa url)."""
    ctx.configure(ENVIRONMENT="prod", SECRETS_LLM_URL_ALLOWED_HOSTS="")
    env_url = NON_SECRET_VALUES["llm_url"]  # http://..., tidak di allowlist

    resp = await ctx.put("llm", bundle(url=env_url))

    assert resp.status_code == 200
    assert (await ctx.stored("llm") or {})["url"] == env_url


async def test_put_does_not_trust_an_llm_url_that_only_resembles_the_one_in_env(ctx: Ctx) -> None:
    ctx.configure(ENVIRONMENT="prod", SECRETS_LLM_URL_ALLOWED_HOSTS="")

    resp = await ctx.put("llm", bundle(url=NON_SECRET_VALUES["llm_url"] + "/extra"))

    await assert_rejected(ctx, resp, "llm")


# --- nilai yang sama tidak dihitung berubah ---------------------------------------------------


async def test_put_of_the_value_that_is_already_stored_changes_nothing(ctx: Ctx) -> None:
    """Kirim ulang key yang sama tidak boleh memakai kuota vendor, jatah tulis, atau audit."""
    await ctx.seed("nvd", {"api_key": OLD_NVD})

    resp = await ctx.put("nvd", {"api_key": OLD_NVD})

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "db"
    assert body["probe"] is None
    assert ctx.probe.calls == []
    row = await ctx.row("nvd")
    assert row is not None
    assert row.updated_by == "seeder"  # baris tidak ditulis ulang
    assert await ctx.audit("secret_set") == []


async def test_put_of_the_llm_bundle_that_is_already_stored_changes_nothing(ctx: Ctx) -> None:
    await ctx.seed("llm", OLD_LLM_BUNDLE)

    resp = await ctx.put("llm", OLD_LLM_BUNDLE)

    assert resp.status_code == 200
    assert ctx.probe.calls == []
    assert await ctx.audit("secret_set") == []
    assert await ctx.stored("llm") == OLD_LLM_BUNDLE


async def test_put_null_for_a_field_that_is_not_overridden_changes_nothing(ctx: Ctx) -> None:
    fields = {k: v for k, v in OLD_LLM_BUNDLE.items() if k != "api_key"}
    await ctx.seed("llm", fields)

    resp = await ctx.put("llm", {"api_key": None})

    assert resp.status_code == 200
    assert ctx.probe.calls == []
    assert await ctx.stored("llm") == fields
    assert await ctx.audit("secret_set") == []


async def test_put_null_without_any_override_changes_nothing(ctx: Ctx) -> None:
    resp = await ctx.put("nvd", {"api_key": None})

    assert resp.status_code == 200
    assert resp.json()["source"] == "env"
    assert ctx.probe.calls == []
    assert await ctx.count_rows() == 0
    assert await ctx.audit("secret_set") == []
    assert await ctx.audit("secret_clear") == []


# --- penolakan sesudah password benar: diaudit dan ter-commit ---------------------------------


async def test_a_validation_rejection_after_the_right_password_is_audited(ctx: Ctx) -> None:
    resp = await ctx.put("nvd", {"api_key": NEW_NVD, "bogus": "x-bogus-aaaaaa"})

    assert resp.status_code == 422
    (entry,) = await ctx.audit("secret_set_rejected")
    assert entry.username == ROOT
    assert entry.target_id == "nvd"
    assert entry.detail["fields"] == ["api_key", "bogus"]
    assert isinstance(entry.detail["reason"], str)
    assert entry.detail["reason"]
    assert entry.ip_address
    assert_no_value(
        await ctx.audit_text("secret_set_rejected"), NEW_NVD, "x-bogus-aaaaaa", PASSWORD
    )


async def test_a_failed_probe_is_audited_as_a_rejection(ctx: Ctx) -> None:
    ctx.probe.respond("FAIL", f"detail yang memuat {NEW_NVD}")

    await ctx.put("nvd", {"api_key": NEW_NVD})

    (entry,) = await ctx.audit("secret_set_rejected")
    assert entry.detail == {"fields": ["api_key"], "reason": "probe FAIL"}
    assert_no_value(await ctx.audit_text("secret_set_rejected"), NEW_NVD)


async def test_a_conflict_on_an_unreadable_override_is_audited_as_a_rejection(ctx: Ctx) -> None:
    await ctx.seed_unreadable("llm")

    resp = await ctx.put("llm", {"model": "model-new-aaaaaa"})

    assert resp.status_code == 409
    (entry,) = await ctx.audit("secret_set_rejected")
    assert entry.target_id == "llm"
    assert entry.detail["fields"] == ["model"]
    assert entry.detail["reason"]


@pytest.mark.parametrize("probe_status", ["OK", "FAIL"])
async def test_the_rejection_audit_row_is_committed_before_the_error_response(
    ctx: Ctx, probe_status: str
) -> None:
    """Handler yang raise tanpa commit membuat `get_db` me-rollback catatan auditnya."""
    ctx.probe.respond(probe_status)
    fields = {"bogus": "x-bogus-aaaaaa"} if probe_status == "OK" else {"api_key": NEW_NVD}

    resp = await ctx.put("nvd", fields)

    assert resp.status_code == 422
    assert ctx.commits >= 1


async def test_a_wrong_password_writes_no_rejection_audit_row(ctx: Ctx) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD}, password="wrong-password-1")

    assert await ctx.audit("secret_set_rejected") == []
    assert len(await ctx.audit("secret_reauth_failed")) == 1


async def test_a_successful_put_writes_no_rejection_audit_row(ctx: Ctx) -> None:
    await ctx.put("nvd", {"api_key": NEW_NVD})

    assert await ctx.audit("secret_set_rejected") == []


async def test_put_all_null_writes_a_secret_clear_audit_row_and_no_secret_set(ctx: Ctx) -> None:
    await ctx.seed("nvd", {"api_key": OLD_NVD})

    await ctx.put("nvd", {"api_key": None})

    (entry,) = await ctx.audit("secret_clear")
    assert entry.username == ROOT
    assert entry.target_id == "nvd"
    assert await ctx.audit("secret_set") == []


async def test_put_with_no_fields_at_all_is_rejected(ctx: Ctx) -> None:
    resp = await ctx.put("nvd", {})

    await assert_rejected(ctx, resp)


# --- urutan pemeriksaan -----------------------------------------------------------------------


async def test_put_of_an_unknown_provider_is_404(ctx: Ctx) -> None:
    resp = await ctx.put("tidak-ada", {"api_key": NEW_NVD})

    assert resp.status_code == 404
    assert ctx.probe.calls == []


async def test_an_unknown_provider_is_404_even_without_a_master_key(ctx: Ctx) -> None:
    ctx.configure(SECRETS_ENCRYPTION_KEYS="")

    resp = await ctx.put("tidak-ada", {"api_key": NEW_NVD})

    assert resp.status_code == 404


async def test_put_without_a_master_key_is_503_and_stores_nothing(ctx: Ctx) -> None:
    ctx.configure(SECRETS_ENCRYPTION_KEYS="")

    resp = await ctx.put("nvd", {"api_key": NEW_NVD})

    await assert_rejected(ctx, resp, status=503)


async def test_the_master_key_is_checked_before_the_password(ctx: Ctx) -> None:
    ctx.configure(SECRETS_ENCRYPTION_KEYS="")

    resp = await ctx.put("nvd", {"api_key": NEW_NVD}, password="wrong-password-1")

    assert resp.status_code == 503
    assert await ctx.audit("secret_reauth_failed") == []


async def test_the_password_is_checked_before_the_fields_are_validated(ctx: Ctx) -> None:
    resp = await ctx.put("nvd", {"bogus": "value-aaaaaa"}, password="wrong-password-1")

    assert resp.status_code == 403
    assert len(await ctx.audit("secret_reauth_failed")) == 1


# --- 422 tidak boleh memantulkan nilai --------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"fields": {"api_key": NEW_NVD, "bogus": "x-bogus-aaaaaa"}, "current_password": PASSWORD},
        {"fields": {"api_key": NEW_NVD}},  # tanpa current_password
        {"fields": {"api_key": NEW_NVD, "other": 123456789012}, "current_password": PASSWORD},
        {"fields": {"api_key": NEW_NVD}, "current_password": "wrong-password-1"},
        {"fields": "bukan-objek", "api_key": NEW_NVD, "current_password": PASSWORD},
        {"current_password": PASSWORD, "api_key": NEW_NVD},  # tanpa fields
    ],
    ids=[
        "unknown-field",
        "no-password",
        "non-string",
        "wrong-password",
        "fields-not-object",
        "no-fields",
    ],
)
async def test_a_rejected_put_never_echoes_the_secret_or_the_password(
    ctx: Ctx, body: dict[str, Any]
) -> None:
    """Default FastAPI memantulkan `input` (seluruh body) di 422 validasi skema: itu akan
    mengembalikan key yang baru diketik, dan password-nya, ke browser dan log proxy."""
    resp = await ctx.request("PUT", "/api/secrets/nvd", body)

    assert resp.status_code in {403, 422}
    assert_no_value(resp.text, NEW_NVD, PASSWORD, "wrong-password-1")
