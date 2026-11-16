"""Integration test repo `cti_core.db.repositories.auth` -- Postgres REAL
(testcontainers, `alembic upgrade head` beneran), bukan mock. Fase 7 (7.1/7.2)."""

from __future__ import annotations

import pytest
from cti_core.db.repositories.auth import (
    AsyncAuditLogRepo,
    AsyncClientRepo,
    AsyncPasswordPolicyRepo,
    AsyncRoleRepo,
    AsyncUserRepo,
)
from sqlalchemy.ext.asyncio import AsyncSession


class TestAsyncClientRepo:
    async def test_ensure_default_is_idempotent(self, async_db_session: AsyncSession) -> None:
        repo = AsyncClientRepo(async_db_session)
        await repo.ensure_default()
        await repo.ensure_default()  # dipanggil dua kali -- gak boleh IntegrityError
        client = await repo.get("default")
        assert client is not None
        assert client.name == "Default"

    async def test_create_and_get_with_countries(self, async_db_session: AsyncSession) -> None:
        repo = AsyncClientRepo(async_db_session)
        created = await repo.create(client_id="acme", name="Acme Corp", countries=["US", "ID"])
        assert created.name == "Acme Corp"

        fetched = await repo.get("acme")
        assert fetched is not None
        assert {c.country_code for c in fetched.countries} == {"US", "ID"}

    async def test_update_replaces_countries(self, async_db_session: AsyncSession) -> None:
        repo = AsyncClientRepo(async_db_session)
        await repo.create(client_id="acme", name="Acme", countries=["US"])
        updated = await repo.update("acme", name="Acme Renamed", countries=["ID", "SG"])
        assert updated is not None
        assert updated.name == "Acme Renamed"
        assert {c.country_code for c in updated.countries} == {"ID", "SG"}

    async def test_cannot_delete_default_client(self, async_db_session: AsyncSession) -> None:
        repo = AsyncClientRepo(async_db_session)
        await repo.ensure_default()
        assert await repo.delete("default") is False

    async def test_delete_non_default_client(self, async_db_session: AsyncSession) -> None:
        repo = AsyncClientRepo(async_db_session)
        await repo.create(client_id="acme", name="Acme", countries=[])
        assert await repo.delete("acme") is True
        assert await repo.get("acme") is None


class TestAsyncRoleRepo:
    async def test_upsert_system_role_creates_then_updates(
        self, async_db_session: AsyncSession
    ) -> None:
        repo = AsyncRoleRepo(async_db_session)
        role = await repo.upsert_system_role(
            name="analyst", display_name="Analyst", permissions=["view_news"]
        )
        assert role.is_system is True
        assert role.permissions == ["view_news"]

        updated = await repo.upsert_system_role(
            name="analyst", display_name="Analyst v2", permissions=["view_news", "view_cve"]
        )
        assert updated.display_name == "Analyst v2"
        assert updated.permissions == ["view_news", "view_cve"]

    async def test_exists_false_for_unknown_role(self, async_db_session: AsyncSession) -> None:
        assert await AsyncRoleRepo(async_db_session).exists("nosuchrole") is False

    async def test_create_custom_role_and_delete(self, async_db_session: AsyncSession) -> None:
        repo = AsyncRoleRepo(async_db_session)
        await repo.create(
            name="viewer", display_name="Viewer", permissions=["view_news"], created_by="admin1"
        )
        assert await repo.exists("viewer") is True
        assert await repo.delete("viewer") is True
        assert await repo.exists("viewer") is False

    async def test_cannot_delete_system_role(self, async_db_session: AsyncSession) -> None:
        repo = AsyncRoleRepo(async_db_session)
        await repo.upsert_system_role(name="admin", display_name="Admin", permissions=[])
        with pytest.raises(ValueError, match="sistem"):
            await repo.delete("admin")

    async def test_delete_unknown_role_returns_false(self, async_db_session: AsyncSession) -> None:
        assert await AsyncRoleRepo(async_db_session).delete("ghost") is False


class TestAsyncUserRepo:
    async def _make_role(self, session: AsyncSession, name: str = "analyst") -> None:
        await AsyncRoleRepo(session).upsert_system_role(
            name=name, display_name=name.title(), permissions=[]
        )

    async def test_create_and_get_by_username(self, async_db_session: AsyncSession) -> None:
        await self._make_role(async_db_session)
        await AsyncClientRepo(async_db_session).ensure_default()
        repo = AsyncUserRepo(async_db_session)
        user = await repo.create(
            username="alice",
            password_hash="hashed",
            role_name="analyst",
            client_ids=["default"],
        )
        assert user.username == "alice"

        fetched = await repo.get_by_username("alice")
        assert fetched is not None
        assert [c.client_id for c in fetched.clients] == ["default"]

    async def test_count_reflects_created_users(self, async_db_session: AsyncSession) -> None:
        await self._make_role(async_db_session)
        await AsyncClientRepo(async_db_session).ensure_default()
        repo = AsyncUserRepo(async_db_session)
        assert await repo.count() == 0
        await repo.create(
            username="alice", password_hash="h", role_name="analyst", client_ids=["default"]
        )
        assert await repo.count() == 1

    async def test_update_role(self, async_db_session: AsyncSession) -> None:
        await self._make_role(async_db_session, "analyst")
        await self._make_role(async_db_session, "admin")
        await AsyncClientRepo(async_db_session).ensure_default()
        repo = AsyncUserRepo(async_db_session)
        await repo.create(
            username="alice", password_hash="h", role_name="analyst", client_ids=["default"]
        )
        assert await repo.update_role("alice", "admin") is True
        fetched = await repo.get_by_username("alice")
        assert fetched is not None
        assert fetched.role_name == "admin"

    async def test_update_role_unknown_user_returns_false(
        self, async_db_session: AsyncSession
    ) -> None:
        assert await AsyncUserRepo(async_db_session).update_role("ghost", "admin") is False

    async def test_update_client_ids_replaces_existing(
        self, async_db_session: AsyncSession
    ) -> None:
        await self._make_role(async_db_session)
        client_repo = AsyncClientRepo(async_db_session)
        await client_repo.ensure_default()
        await client_repo.create(client_id="acme", name="Acme", countries=[])
        repo = AsyncUserRepo(async_db_session)
        await repo.create(
            username="alice", password_hash="h", role_name="analyst", client_ids=["default"]
        )
        assert await repo.update_client_ids("alice", ["acme"]) is True
        fetched = await repo.get_by_username("alice")
        assert fetched is not None
        assert [c.client_id for c in fetched.clients] == ["acme"]

    async def test_reset_password_self_change_clears_force_pw_change(
        self, async_db_session: AsyncSession
    ) -> None:
        await self._make_role(async_db_session)
        await AsyncClientRepo(async_db_session).ensure_default()
        repo = AsyncUserRepo(async_db_session)
        user = await repo.create(
            username="alice", password_hash="old", role_name="analyst", client_ids=["default"]
        )
        user.force_pw_change = True
        await async_db_session.flush()

        assert await repo.reset_password("alice", "new-hash", force_change=False) is True
        fetched = await repo.get_by_username("alice")
        assert fetched is not None
        assert fetched.password_hash == "new-hash"
        assert fetched.force_pw_change is False

    async def test_reset_password_admin_reset_sets_force_pw_change(
        self, async_db_session: AsyncSession
    ) -> None:
        await self._make_role(async_db_session)
        await AsyncClientRepo(async_db_session).ensure_default()
        repo = AsyncUserRepo(async_db_session)
        await repo.create(
            username="alice", password_hash="old", role_name="analyst", client_ids=["default"]
        )

        assert await repo.reset_password("alice", "new-hash", force_change=True) is True
        fetched = await repo.get_by_username("alice")
        assert fetched is not None
        assert fetched.password_hash == "new-hash"
        assert fetched.force_pw_change is True

    async def test_update_last_sign_in_sets_timestamp(self, async_db_session: AsyncSession) -> None:
        await self._make_role(async_db_session)
        await AsyncClientRepo(async_db_session).ensure_default()
        repo = AsyncUserRepo(async_db_session)
        await repo.create(
            username="alice", password_hash="h", role_name="analyst", client_ids=["default"]
        )
        await repo.update_last_sign_in("alice")
        fetched = await repo.get_by_username("alice")
        assert fetched is not None
        assert fetched.last_sign_in is not None

    async def test_flag_force_pw_change_excludes_only_admin_role(
        self, async_db_session: AsyncSession
    ) -> None:
        """Port apa adanya dari legacy: filter cuma exclude role=="admin",
        "superadmin" IKUT ke-flag -- lihat docstring repo."""
        for role in ("analyst", "admin", "superadmin"):
            await self._make_role(async_db_session, role)
        await AsyncClientRepo(async_db_session).ensure_default()
        repo = AsyncUserRepo(async_db_session)
        await repo.create(
            username="a", password_hash="h", role_name="analyst", client_ids=["default"]
        )
        await repo.create(
            username="b", password_hash="h", role_name="admin", client_ids=["default"]
        )
        await repo.create(
            username="c", password_hash="h", role_name="superadmin", client_ids=["default"]
        )

        flagged = await repo.flag_force_pw_change_all_non_admin()
        assert flagged == 2

        a, b, c = [await repo.get_by_username(u) for u in ("a", "b", "c")]
        assert a is not None and a.force_pw_change is True
        assert b is not None and b.force_pw_change is False
        assert c is not None and c.force_pw_change is True


class TestAsyncAuditLogRepo:
    async def test_write_and_query_returns_newest_first(
        self, async_db_session: AsyncSession
    ) -> None:
        repo = AsyncAuditLogRepo(async_db_session)
        await repo.write(username="alice", action="login", ip_address="127.0.0.1")
        await repo.write(
            username="alice", action="create_user", target_id="bob", detail={"role": "analyst"}
        )

        entries, total = await repo.query(page=1, page_size=10)
        assert total == 2
        assert entries[0].action == "create_user"
        assert entries[0].target_id == "bob"
        assert entries[0].detail == {"role": "analyst"}
        assert entries[1].action == "login"

    async def test_query_filters_by_username_and_action(
        self, async_db_session: AsyncSession
    ) -> None:
        repo = AsyncAuditLogRepo(async_db_session)
        await repo.write(username="alice", action="login")
        await repo.write(username="bob", action="login")
        await repo.write(username="alice", action="change_password")

        entries, total = await repo.query(username="alice", action="login")
        assert total == 1
        assert entries[0].username == "alice"
        assert entries[0].action == "login"

    async def test_query_pagination(self, async_db_session: AsyncSession) -> None:
        repo = AsyncAuditLogRepo(async_db_session)
        for i in range(5):
            await repo.write(username="alice", action=f"action{i}")

        page1, total = await repo.query(page=1, page_size=2)
        page2, _ = await repo.query(page=2, page_size=2)
        assert total == 5
        assert len(page1) == 2
        assert len(page2) == 2
        assert {e.id for e in page1}.isdisjoint({e.id for e in page2})


class TestAsyncPasswordPolicyRepo:
    async def test_get_returns_defaults_when_no_row(self, async_db_session: AsyncSession) -> None:
        policy = await AsyncPasswordPolicyRepo(async_db_session).get()
        assert policy == {
            "min_length": 8,
            "require_upper": True,
            "require_lower": True,
            "require_number": True,
            "require_symbol": True,
        }

    async def test_save_then_get_roundtrip(self, async_db_session: AsyncSession) -> None:
        repo = AsyncPasswordPolicyRepo(async_db_session)
        new_policy = {
            "min_length": 12,
            "require_upper": False,
            "require_lower": True,
            "require_number": True,
            "require_symbol": False,
        }
        await repo.save(new_policy)
        assert await repo.get() == new_policy

    async def test_save_twice_updates_same_row(self, async_db_session: AsyncSession) -> None:
        repo = AsyncPasswordPolicyRepo(async_db_session)
        await repo.save(
            {
                "min_length": 10,
                "require_upper": True,
                "require_lower": True,
                "require_number": True,
                "require_symbol": True,
            }
        )
        await repo.save(
            {
                "min_length": 16,
                "require_upper": True,
                "require_lower": True,
                "require_number": True,
                "require_symbol": True,
            }
        )
        policy = await repo.get()
        assert policy["min_length"] == 16
