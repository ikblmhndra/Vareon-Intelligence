"""AsyncUserRepo/AsyncRoleRepo/AsyncClientRepo/AsyncAuditLogRepo/AsyncPasswordPolicyRepo
-- satu-satunya jalur baca/tulis `users`/`roles`/`clients`/`audit_log`/
`password_policies`. Async-only (bukan dual sync+async kayak `ArticleRepo`/
`ScraperRunRepo`) -- konsumen SATU-SATUNYA `apps/api` (Fase 7), gak ada
task Celery/CLI yang nyentuh tabel-tabel ini, jadi sisi sync gak ada
gunanya (lihat pola `CveTrackerRepo`/`TweetRepo` -- sync-only karena
konsumen tunggal juga, arah kebalikannya).

Gantiin `auth_service.py`/`role_service.py`/`client_service.py`/
`audit_service.py`/`policy_service.py` (`ScraperNewsWeb`) -- kelimanya
sengaja disatukan di sini (bukan lima file terpisah) karena kelimanya
sama-sama CRUD tipis atas lima tabel yang deklarasinya udah nempel di satu
modul model (`db/models/auth.py`), bukan lima domain concern yang beda."""

from __future__ import annotations

import datetime
from typing import Any, cast

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cti_core.db.models.auth import (
    ApiToken,
    AuditLogEntry,
    Client,
    ClientCountry,
    PasswordPolicy,
    Role,
    User,
    UserClient,
)

_DEFAULT_POLICY = {
    "min_length": 8,
    "require_upper": True,
    "require_lower": True,
    "require_number": True,
    "require_symbol": True,
}


class AsyncUserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_username(self, username: str) -> User | None:
        result = await self.session.execute(
            select(User).options(selectinload(User.clients)).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self.session.execute(select(User.id))
        return len(result.all())

    async def create(
        self,
        *,
        username: str,
        password_hash: str,
        role_name: str,
        client_ids: list[str],
    ) -> User:
        user = User(username=username, password_hash=password_hash, role_name=role_name)
        self.session.add(user)
        await self.session.flush()
        for cid in client_ids:
            self.session.add(UserClient(user_id=user.id, client_id=cid))
        await self.session.flush()
        await self.session.refresh(user, attribute_names=["clients"])
        return user

    async def list_all(self) -> list[User]:
        result = await self.session.execute(
            select(User).options(selectinload(User.clients)).order_by(User.username)
        )
        return list(result.scalars().all())

    async def update_role(self, username: str, role_name: str) -> bool:
        user = await self.get_by_username(username)
        if user is None:
            return False
        user.role_name = role_name
        await self.session.flush()
        return True

    async def update_client_ids(self, username: str, client_ids: list[str]) -> bool:
        user = await self.get_by_username(username)
        if user is None:
            return False
        for existing in list(user.clients):
            await self.session.delete(existing)
        await self.session.flush()
        for cid in client_ids:
            self.session.add(UserClient(user_id=user.id, client_id=cid))
        await self.session.flush()
        # `session.delete()` pada child gak otomatis nyabut dia dari
        # koleksi `user.clients` yang UDAH ke-load di memori (beda dari
        # `parent.children.remove(child)`) -- tanpa expire ini, caller yang
        # baca `user.clients` di sesi YANG SAMA (mis. `get_by_username`
        # abis ini, di-cache lewat identity map) masih liat client_ids
        # LAMA walau row di DB udah bener. Ketauan LIVE lewat test
        # integrasi (Fase 7), bukan dugaan.
        self.session.expire(user, attribute_names=["clients"])
        return True

    async def reset_password(self, username: str, password_hash: str) -> bool:
        user = await self.get_by_username(username)
        if user is None:
            return False
        user.password_hash = password_hash
        user.force_pw_change = False
        await self.session.flush()
        return True

    async def update_last_sign_in(self, username: str) -> None:
        user = await self.get_by_username(username)
        if user is not None:
            user.last_sign_in = datetime.datetime.now(datetime.UTC)
            await self.session.flush()

    async def flag_force_pw_change_all_non_admin(self) -> int:
        """UPDATE massal (bukan loop per-row) -- dipanggil admin toggle
        "force all users to change password", bisa kena ratusan user.

        Filter PERSIS port dari `role_service.py` lama: `{"role": {"$ne":
        "admin"}}` -- cuma exclude role == "admin", role "superadmin" IKUT
        ke-flag. Kemungkinan bug legacy (superadmin harusnya ikut
        dikecualikan?) tapi gak ada di daftar bug yang didokumentasiin plan
        §7 -- dipertahankan apa adanya, bukan diam-diam "diperbaiki"."""
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(User).where(User.role_name != "admin").values(force_pw_change=True)
            ),
        )
        await self.session.flush()
        return result.rowcount


class AsyncRoleRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, name: str) -> Role | None:
        result = await self.session.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    async def exists(self, name: str) -> bool:
        return await self.get(name) is not None

    async def list_all(self) -> list[Role]:
        result = await self.session.execute(select(Role).order_by(Role.name))
        return list(result.scalars().all())

    async def upsert_system_role(
        self, *, name: str, display_name: str, permissions: list[str]
    ) -> Role:
        role = await self.get(name)
        if role is None:
            role = Role(
                name=name,
                display_name=display_name,
                permissions=permissions,
                is_system=True,
                created_by="system",
            )
            self.session.add(role)
        else:
            role.display_name = display_name
            role.permissions = permissions
        await self.session.flush()
        return role

    async def create(
        self, *, name: str, display_name: str, permissions: list[str], created_by: str
    ) -> Role:
        role = Role(
            name=name,
            display_name=display_name,
            permissions=permissions,
            is_system=False,
            created_by=created_by,
        )
        self.session.add(role)
        await self.session.flush()
        return role

    async def delete(self, name: str) -> bool:
        """`ValueError` kalau role sistem -- caller (router) yang ubah jadi
        HTTP 400, bukan repo yang tau soal HTTP."""
        role = await self.get(name)
        if role is None:
            return False
        if role.is_system:
            raise ValueError(f"role sistem '{name}' gak bisa dihapus")
        await self.session.delete(role)
        await self.session.flush()
        return True


class AsyncClientRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, client_id: str) -> Client | None:
        result = await self.session.execute(
            select(Client)
            .options(selectinload(Client.countries))
            .where(Client.client_id == client_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Client]:
        result = await self.session.execute(
            select(Client).options(selectinload(Client.countries)).order_by(Client.client_id)
        )
        return list(result.scalars().all())

    async def ensure_default(self) -> None:
        if await self.get("default") is None:
            self.session.add(Client(client_id="default", name="Default"))
            await self.session.flush()

    async def create(self, *, client_id: str, name: str, countries: list[str]) -> Client:
        client = Client(client_id=client_id, name=name)
        self.session.add(client)
        await self.session.flush()
        for code in countries:
            self.session.add(ClientCountry(client_id=client_id, country_code=code))
        await self.session.flush()
        await self.session.refresh(client, attribute_names=["countries"])
        return client

    async def update(
        self, client_id: str, *, name: str, countries: list[str] | None = None
    ) -> Client | None:
        """`countries=None` = country gak disentuh (semantik PATCH); `[]`
        eksplisit = sengaja dikosongin."""
        client = await self.get(client_id)
        if client is None:
            return None
        client.name = name
        if countries is None:
            await self.session.flush()
            return client
        for existing in list(client.countries):
            await self.session.delete(existing)
        await self.session.flush()
        for code in countries:
            self.session.add(ClientCountry(client_id=client_id, country_code=code))
        await self.session.flush()
        await self.session.refresh(client, attribute_names=["countries"])
        return client

    async def delete(self, client_id: str) -> bool:
        if client_id == "default":
            return False
        client = await self.get(client_id)
        if client is None:
            return False
        await self.session.delete(client)
        await self.session.flush()
        return True


class AsyncAuditLogRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self,
        *,
        username: str,
        action: str,
        target_id: str = "",
        detail: dict[str, Any] | None = None,
        ip_address: str = "",
    ) -> None:
        self.session.add(
            AuditLogEntry(
                username=username,
                action=action,
                target_id=target_id,
                detail=detail or {},
                ip_address=ip_address or None,
            )
        )
        await self.session.flush()

    async def query(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        username: str | None = None,
        action: str | None = None,
    ) -> tuple[list[AuditLogEntry], int]:
        stmt = select(AuditLogEntry)
        if username:
            stmt = stmt.where(AuditLogEntry.username.ilike(f"%{username}%"))
        if action:
            stmt = stmt.where(AuditLogEntry.action.ilike(f"%{action}%"))
        count_result = await self.session.execute(stmt)
        total = len(count_result.all())
        stmt = (
            stmt.order_by(AuditLogEntry.at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total


class AsyncPasswordPolicyRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self) -> dict[str, Any]:
        result = await self.session.execute(select(PasswordPolicy).where(PasswordPolicy.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            return dict(_DEFAULT_POLICY)
        return {
            "min_length": row.min_length,
            "require_upper": row.require_upper,
            "require_lower": row.require_lower,
            "require_number": row.require_number,
            "require_symbol": row.require_symbol,
        }

    async def save(self, policy: dict[str, Any]) -> dict[str, Any]:
        result = await self.session.execute(select(PasswordPolicy).where(PasswordPolicy.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            row = PasswordPolicy(id=1, **policy)
            self.session.add(row)
        else:
            for key, value in policy.items():
                setattr(row, key, value)
        await self.session.flush()
        return policy


class AsyncApiTokenRepo:
    """Token mesin P7b. Nilai token tidak pernah lewat sini, hanya sha256-nya."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        name: str,
        token_prefix: str,
        token_hash: str,
        scopes: list[str],
        max_tlp: str,
        created_by: str,
        expires_at: datetime.datetime | None,
    ) -> ApiToken:
        row = ApiToken(
            name=name,
            token_prefix=token_prefix,
            token_hash=token_hash,
            scopes=scopes,
            max_tlp=max_tlp,
            created_by=created_by,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_all(self) -> list[ApiToken]:
        result = await self.session.execute(
            select(ApiToken).order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        )
        return list(result.scalars().all())

    async def get(self, token_id: int) -> ApiToken | None:
        return await self.session.get(ApiToken, token_id)

    async def get_by_hash(self, token_hash: str) -> ApiToken | None:
        result = await self.session.execute(
            select(ApiToken).where(ApiToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, token: ApiToken, *, by: str) -> ApiToken:
        """Mencabut token; `revoked_at` pertama dipertahankan kalau sudah dicabut."""
        if token.revoked_at is None:
            token.revoked_at = datetime.datetime.now(datetime.UTC)
            token.revoked_by = by
            await self.session.flush()
        return token

    async def touch_last_used(self, token_id: int) -> None:
        """Satu UPDATE bersyarat: hanya menulis kalau nilai lama lebih tua dari 60 detik."""
        await self.session.execute(
            update(ApiToken)
            .where(
                ApiToken.id == token_id,
                or_(
                    ApiToken.last_used_at.is_(None),
                    ApiToken.last_used_at < func.now() - text("interval '60 seconds'"),
                ),
            )
            .values(last_used_at=func.now())
        )
