"""`AsyncRuntimeSecretRepo` -- sisi TULIS `runtime_secrets` buat router admin (ROADMAP #23, PR 2).

`RuntimeSecretRepo` (sync, baca-saja, buat overlay) sudah dites di `test_runtime_secrets_db.py`;
ini pasangan async-nya: `list_platform`, `get_platform`, `upsert_platform`, `delete_platform`,
`record_test`. Yang dikunci:

- upsert idempoten per provider (satu baris platform, bukan dua) dan yang ditimpa saat update:
  `secrets_enc`, `updated_by`, `last_test_ok`, `last_test_at` (hasil probe lama tidak boleh
  menempel di key baru yang belum dites). `created_at` tetap, `updated_at` naik. Upsert menarget
  INDEKS parsial platform, dan ORM `onupdate` tidak jalan buat `ON CONFLICT DO UPDATE`, jadi
  `updated_at` yang naik adalah yang perlu dibuktikan -- di transaksi sungguhan, karena `now()`
  Postgres konstan dalam satu transaksi (tes lain di sini di-rollback dalam satu transaksi);
- `record_test` hanya memperbarui baris yang ADA, tidak pernah membuat baris;
- semua metode hanya menyentuh `client_id IS NULL`: baris per-workspace (BYOK, nanti) tidak
  boleh tersentuh oleh operasi scope platform.
"""

from __future__ import annotations

import datetime

import pytest
from cti_core.db.engine import get_async_engine
from cti_core.db.models.auth import Client
from cti_core.db.models.runtime_secret import RuntimeSecret
from cti_core.db.repositories.runtime_secret import AsyncRuntimeSecretRepo
from cti_core.runtime_secrets.crypto import encrypt_fields
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.runtime_secrets_helpers import KEYS

pytestmark = pytest.mark.asyncio

T1 = datetime.datetime(2026, 10, 16, 9, 0, tzinfo=datetime.UTC)
T2 = datetime.datetime(2026, 10, 16, 10, 30, tzinfo=datetime.UTC)
CLIENT = "rs-acme"
COMMIT_TAGS = ("repo-commit-test-1", "repo-commit-test-2")


def token(value: str, provider: str = "nvd") -> bytes:
    return encrypt_fields(provider, {"api_key": value}, keys=KEYS)


TOKEN_A = token("nvd-repo-aaaaaa")  # gitleaks:allow
TOKEN_B = token("nvd-repo-bbbbbb")  # gitleaks:allow


async def count(session: AsyncSession, provider: str, *, platform: bool | None = None) -> int:
    stmt = select(func.count()).select_from(RuntimeSecret).where(RuntimeSecret.provider == provider)
    if platform is True:
        stmt = stmt.where(RuntimeSecret.client_id.is_(None))
    elif platform is False:
        stmt = stmt.where(RuntimeSecret.client_id.is_not(None))
    return await session.scalar(stmt) or 0


async def fresh(session: AsyncSession, provider: str, *, client_id: str | None) -> RuntimeSecret:
    """Baca ulang dari DB (bukan dari identity map) supaya yang dicek benar-benar isi tabel."""
    stmt = (
        select(RuntimeSecret)
        .where(RuntimeSecret.provider == provider, RuntimeSecret.client_id == client_id)
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one()


async def add_client_row(session: AsyncSession, provider: str = "nvd") -> RuntimeSecret:
    """Baris scope workspace `rs-acme` (bukan platform) dengan isi yang gampang dikenali."""
    session.add(Client(client_id=CLIENT, name="Acme"))
    await session.flush()
    row = RuntimeSecret(
        provider=provider,
        client_id=CLIENT,
        secrets_enc=b"client-owned-token",
        updated_by="client-admin",
    )
    session.add(row)
    await session.flush()
    return row


# --- upsert_platform --------------------------------------------------------------------------


async def test_upsert_inserts_a_platform_row_and_returns_it(async_db_session: AsyncSession) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)

    row = await repo.upsert_platform("nvd", TOKEN_A, "root")

    assert row.provider == "nvd"
    assert row.client_id is None
    assert bytes(row.secrets_enc) == TOKEN_A
    assert row.updated_by == "root"
    assert row.last_test_ok is None
    assert row.last_test_at is None
    assert row.created_at is not None
    assert row.updated_at is not None
    assert await count(async_db_session, "nvd", platform=True) == 1


@pytest.mark.parametrize("ok", [True, False])
async def test_upsert_stores_the_probe_result_when_given(
    async_db_session: AsyncSession, ok: bool
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)

    await repo.upsert_platform("nvd", TOKEN_A, "root", last_test_ok=ok, last_test_at=T1)

    row = await fresh(async_db_session, "nvd", client_id=None)
    assert row.last_test_ok is ok
    assert row.last_test_at == T1


async def test_upserting_the_same_provider_twice_keeps_a_single_row(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)

    await repo.upsert_platform("nvd", TOKEN_A, "root")
    await repo.upsert_platform("nvd", TOKEN_B, "root")

    assert await count(async_db_session, "nvd") == 1


async def test_the_second_upsert_overwrites_the_ciphertext_and_the_author(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "first-admin")

    returned = await repo.upsert_platform("nvd", TOKEN_B, "second-admin")

    stored = await fresh(async_db_session, "nvd", client_id=None)
    assert bytes(stored.secrets_enc) == TOKEN_B
    assert stored.updated_by == "second-admin"
    # Objek yang dikembalikan juga harus mencerminkan penulisan terbaru, bukan salinan basi.
    assert bytes(returned.secrets_enc) == TOKEN_B
    assert returned.updated_by == "second-admin"


async def test_the_second_upsert_replaces_the_probe_result_with_the_new_one(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root", last_test_ok=True, last_test_at=T1)

    await repo.upsert_platform("nvd", TOKEN_B, "root", last_test_ok=False, last_test_at=T2)

    row = await fresh(async_db_session, "nvd", client_id=None)
    assert row.last_test_ok is False
    assert row.last_test_at == T2


async def test_the_second_upsert_without_a_probe_result_clears_the_old_one(
    async_db_session: AsyncSession,
) -> None:
    """Hasil test milik key lama tidak boleh menempel di key baru yang belum pernah dites."""
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root", last_test_ok=True, last_test_at=T1)

    await repo.upsert_platform("nvd", TOKEN_B, "root")

    row = await fresh(async_db_session, "nvd", client_id=None)
    assert row.last_test_ok is None
    assert row.last_test_at is None


async def test_an_update_moves_updated_at_forward_and_keeps_created_at(
    _migrated_schema: None,
) -> None:
    """Dua transaksi sungguhan: ORM `onupdate` tidak jalan buat `ON CONFLICT DO UPDATE`, jadi
    `updated_at` harus diset eksplisit oleh upsert-nya. Satu-satunya tes di file ini yang commit."""
    engine = get_async_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            first = await AsyncRuntimeSecretRepo(session).upsert_platform(
                "nvd", TOKEN_A, COMMIT_TAGS[0]
            )
            await session.commit()
            created_at, first_updated_at = first.created_at, first.updated_at
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await AsyncRuntimeSecretRepo(session).upsert_platform("nvd", TOKEN_B, COMMIT_TAGS[1])
            await session.commit()
        async with AsyncSession(engine, expire_on_commit=False) as session:
            stored = await fresh(session, "nvd", client_id=None)
            second_updated_at, second_created_at = stored.updated_at, stored.created_at
            second_author = stored.updated_by
    finally:
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(RuntimeSecret).where(RuntimeSecret.updated_by.in_(COMMIT_TAGS))
            )
            await session.commit()

    assert second_author == COMMIT_TAGS[1]
    assert second_created_at == created_at
    assert second_updated_at > first_updated_at


# --- get_platform / list_platform -------------------------------------------------------------


async def test_get_platform_returns_none_when_there_is_no_row(
    async_db_session: AsyncSession,
) -> None:
    assert await AsyncRuntimeSecretRepo(async_db_session).get_platform("nvd") is None


async def test_get_platform_returns_the_row_of_that_provider_only(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")
    await repo.upsert_platform("github", token("ghp-repo-aaaaaa", "github"), "other")

    row = await repo.get_platform("nvd")

    assert row is not None
    assert (row.provider, row.updated_by) == ("nvd", "root")


async def test_list_platform_is_empty_on_an_empty_table(async_db_session: AsyncSession) -> None:
    assert await AsyncRuntimeSecretRepo(async_db_session).list_platform() == []


async def test_list_platform_is_ordered_by_provider(async_db_session: AsyncSession) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    for provider in ("virustotal", "github", "llm", "nvd"):
        await repo.upsert_platform(provider, token("v-repo-aaaaaa", provider), "root")

    rows = await repo.list_platform()

    assert [row.provider for row in rows] == ["github", "llm", "nvd", "virustotal"]


# --- delete_platform --------------------------------------------------------------------------


async def test_delete_platform_removes_the_row_and_returns_true(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")

    deleted = await repo.delete_platform("nvd")

    assert deleted is True
    assert await count(async_db_session, "nvd") == 0
    assert await repo.get_platform("nvd") is None


async def test_delete_platform_returns_false_when_there_is_no_row(
    async_db_session: AsyncSession,
) -> None:
    assert await AsyncRuntimeSecretRepo(async_db_session).delete_platform("nvd") is False


async def test_delete_platform_returns_false_the_second_time(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")
    await repo.delete_platform("nvd")

    assert await repo.delete_platform("nvd") is False


async def test_delete_platform_leaves_other_providers_alone(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")
    await repo.upsert_platform("github", token("ghp-repo-aaaaaa", "github"), "root")

    await repo.delete_platform("nvd")

    assert [row.provider for row in await repo.list_platform()] == ["github"]


# --- record_test ------------------------------------------------------------------------------


async def test_record_test_updates_the_probe_result_of_an_existing_row(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")

    result = await repo.record_test("nvd", True, T1)

    row = await fresh(async_db_session, "nvd", client_id=None)
    assert result is None
    assert row.last_test_ok is True
    assert row.last_test_at == T1


async def test_record_test_can_flip_a_previous_result_to_failed(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root", last_test_ok=True, last_test_at=T1)

    await repo.record_test("nvd", False, T2)

    row = await fresh(async_db_session, "nvd", client_id=None)
    assert row.last_test_ok is False
    assert row.last_test_at == T2


async def test_record_test_does_not_touch_the_ciphertext_or_the_author(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")

    await repo.record_test("nvd", True, T1)

    row = await fresh(async_db_session, "nvd", client_id=None)
    assert bytes(row.secrets_enc) == TOKEN_A
    assert row.updated_by == "root"


async def test_record_test_does_not_create_a_row_for_a_provider_without_an_override(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)

    await repo.record_test("nvd", True, T1)

    assert await count(async_db_session, "nvd") == 0
    assert await repo.get_platform("nvd") is None


async def test_record_test_only_updates_the_named_provider(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")
    await repo.upsert_platform("github", token("ghp-repo-aaaaaa", "github"), "root")

    await repo.record_test("nvd", True, T1)

    other = await fresh(async_db_session, "github", client_id=None)
    assert other.last_test_ok is None
    assert other.last_test_at is None


# --- baris workspace tidak tersentuh ----------------------------------------------------------


async def test_get_platform_ignores_a_client_row(async_db_session: AsyncSession) -> None:
    await add_client_row(async_db_session)

    assert await AsyncRuntimeSecretRepo(async_db_session).get_platform("nvd") is None


async def test_list_platform_excludes_client_rows(async_db_session: AsyncSession) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await add_client_row(async_db_session, "github")
    await repo.upsert_platform("nvd", TOKEN_A, "root")

    rows = await repo.list_platform()

    assert [row.provider for row in rows] == ["nvd"]
    assert all(row.client_id is None for row in rows)


async def test_upsert_platform_creates_its_own_row_and_leaves_the_client_row_untouched(
    async_db_session: AsyncSession,
) -> None:
    await add_client_row(async_db_session)

    await AsyncRuntimeSecretRepo(async_db_session).upsert_platform(
        "nvd", TOKEN_A, "root", last_test_ok=True, last_test_at=T1
    )

    assert await count(async_db_session, "nvd", platform=True) == 1
    assert await count(async_db_session, "nvd", platform=False) == 1
    client_row = await fresh(async_db_session, "nvd", client_id=CLIENT)
    assert bytes(client_row.secrets_enc) == b"client-owned-token"
    assert client_row.updated_by == "client-admin"
    assert client_row.last_test_ok is None


async def test_upsert_platform_updating_leaves_the_client_row_untouched(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await add_client_row(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")

    await repo.upsert_platform("nvd", TOKEN_B, "root")

    client_row = await fresh(async_db_session, "nvd", client_id=CLIENT)
    assert bytes(client_row.secrets_enc) == b"client-owned-token"
    assert client_row.updated_by == "client-admin"


async def test_delete_platform_returns_false_when_only_a_client_row_exists(
    async_db_session: AsyncSession,
) -> None:
    await add_client_row(async_db_session)

    deleted = await AsyncRuntimeSecretRepo(async_db_session).delete_platform("nvd")

    assert deleted is False
    assert await count(async_db_session, "nvd", platform=False) == 1


async def test_delete_platform_removes_only_the_platform_row_when_both_exist(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await add_client_row(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")

    deleted = await repo.delete_platform("nvd")

    assert deleted is True
    assert await count(async_db_session, "nvd", platform=True) == 0
    assert await count(async_db_session, "nvd", platform=False) == 1


async def test_record_test_does_not_touch_a_client_row(async_db_session: AsyncSession) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await add_client_row(async_db_session)

    await repo.record_test("nvd", True, T1)  # tidak ada baris platform: tidak ada yang berubah

    client_row = await fresh(async_db_session, "nvd", client_id=CLIENT)
    assert client_row.last_test_ok is None
    assert client_row.last_test_at is None
    assert await count(async_db_session, "nvd", platform=True) == 0


async def test_record_test_updates_the_platform_row_and_not_the_client_row(
    async_db_session: AsyncSession,
) -> None:
    repo = AsyncRuntimeSecretRepo(async_db_session)
    await add_client_row(async_db_session)
    await repo.upsert_platform("nvd", TOKEN_A, "root")

    await repo.record_test("nvd", True, T1)

    platform_row = await fresh(async_db_session, "nvd", client_id=None)
    client_row = await fresh(async_db_session, "nvd", client_id=CLIENT)
    assert platform_row.last_test_ok is True
    assert client_row.last_test_ok is None
