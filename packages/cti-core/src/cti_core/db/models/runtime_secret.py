"""`runtime_secrets` -- override key third-party yang diatur dari halaman admin (ROADMAP #23).

Satu baris per provider (`llm`, `telegram`, `otx`, ...). SEMUA field override, secret maupun
non-secret (mis. `llm.model`, `llm.url`), ada di satu blob `secrets_enc`: token Fernet dari JSON
`{provider, client_id, fields}`. Tidak ada kolom plaintext yang mempengaruhi perilaku: penyerang
yang hanya bisa MENULIS DB (tanpa master key) tidak bisa mengarahkan `llm.url` ke host miliknya atau
menyisipkan token bot, dan penyerang yang hanya bisa MEMBACA DB/backup tidak melihat apa pun.
Master key-nya tidak di DB (`Settings.secrets_encryption_keys`).

`client_id` NULL = scope platform (operator memegang key). Irisan pertama fitur ini hanya menulis
NULL; kolomnya sudah ada supaya key per-workspace (BYOK) nanti cukup aditif. Karena NULL tidak
dianggap sama oleh unique constraint biasa, keunikannya dua indeks parsial: satu baris platform per
provider, dan satu baris per (client, provider).
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cti_core.db.base import Base, TimestampMixin


class RuntimeSecret(TimestampMixin, Base):
    __tablename__ = "runtime_secrets"
    __table_args__ = (
        Index(
            "uq_runtime_secrets_platform",
            "provider",
            unique=True,
            postgresql_where=text("client_id IS NULL"),
        ),
        Index(
            "uq_runtime_secrets_client",
            "client_id",
            "provider",
            unique=True,
            postgresql_where=text("client_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    """Kunci di `cti_core.runtime_secrets.registry.PROVIDERS` (= nama atribut di `Settings`)."""
    client_id: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("clients.client_id", ondelete="CASCADE")
    )
    """NULL = platform. Lihat docstring modul."""
    secrets_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    """Token Fernet dari semua field override provider ini (lihat docstring modul)."""
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    last_test_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True))
