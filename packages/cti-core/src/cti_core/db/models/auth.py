"""Auth, RBAC, multi-tenant -- gantiin `users`/`roles`/`clients`/`audit_log`.

`client_id` dipakai sebagai PRIMARY KEY string (bukan surrogate int) karena
dia udah jadi natural key yang direferensikan banyak tabel lain (cve_tracker,
dst) di sistem lama -- lihat CveTracker.client_id.

31 permission (`ALL_PERMISSIONS` di app lama, role_service.py) tetap jadi
konstanta Python di layer service (Fase 7), BUKAN tabel terpisah di sini --
itu closed enumeration yang di-enforce di kode, disimpan di `Role.permissions`
sebagai JSONB list. Kalau nanti butuh query "role mana yang punya permission
X", baru dipertimbangin jadi tabel join.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cti_core.db.base import Base, TimestampMixin


class Client(TimestampMixin, Base):
    """Tenant. `client_id` PK -- natural key, direferensikan tabel lain."""

    __tablename__ = "clients"

    client_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    countries: Mapped[list[ClientCountry]] = relationship(
        back_populates="client", cascade="all, delete-orphan", lazy="selectin"
    )


class ClientCountry(Base):
    __tablename__ = "client_countries"
    __table_args__ = (UniqueConstraint("client_id", "country_code", name="uq_client_country"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False
    )
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)

    client: Mapped[Client] = relationship(back_populates="countries")


class Role(TimestampMixin, Base):
    """System role (superadmin/admin/analyst, di-seed startup) atau custom."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    permissions: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False, default="system")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role_name: Mapped[str] = mapped_column(ForeignKey("roles.name"), nullable=False)
    force_pw_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_sign_in: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship()
    clients: Mapped[list[UserClient]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )


class UserClient(Base):
    """Satu user bisa akses banyak client (multi-tenant, v3.8.0 di app
    lama). Gantiin `client_ids: list` di dokumen user Mongo."""

    __tablename__ = "user_clients"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_user_client"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("clients.client_id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="clients")


class AuditLogEntry(Base):
    """Gantiin `audit_log`. Sengaja gak FK ke users.id -- log harus tetap
    kebaca walau user-nya udah dihapus."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    """Objek yang kena aksi (mis. username target `reset_password`/`create_user`)
    -- string kosong kalau aksi gak punya target tunggal (mis. `login`).
    Kolom eksplisit, bukan dilebur ke `detail` -- field ini yang paling
    sering dipakai buat filter "riwayat perubahan user X", nge-JSONB-in dia
    berarti tiap query filter butuh operator JSONB alih-alih index biasa."""
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class PasswordPolicy(Base):
    """Singleton (satu baris, `id=1`) -- kebijakan kompleksitas password yang
    bisa diubah admin lewat UI. Kolom eksplisit (bukan JSONB) karena
    bentuknya udah pasti/tetap (5 field, gak pernah nambah dinamis) --
    beda kasus sama `detail`/`errors` yang memang cair (lihat catatan
    JSONB di docstring modul, dan §3 plan)."""

    __tablename__ = "password_policies"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, default=1)
    min_length: Mapped[int] = mapped_column(nullable=False, default=8)
    require_upper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_lower: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_number: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    require_symbol: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ApiToken(Base):
    """Token mesin (P7b) untuk feed REST/TAXII. Hanya sha256 token yang disimpan (token acak 256
    bit, jadi tanpa stretching); baris dicabut tetap disimpan untuk audit."""

    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint(
            "max_tlp IN ('clear', 'green', 'amber', 'amber+strict', 'red')", name="max_tlp"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    max_tlp: Mapped[str] = mapped_column(String(12), nullable=False, server_default="clear")
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(200))
