"""tabel `runtime_secrets`: override key third-party yang diatur dari halaman admin

ROADMAP #23, PR 1 (inti). Tabel BARU dan kosong, jadi aditif sepenuhnya: tidak ada yang berubah
selama `SECRETS_ENCRYPTION_KEYS` kosong atau tidak ada baris. Semua field override disimpan
terenkripsi dan terotentikasi di `secrets_enc` (token Fernet); tidak ada kolom plaintext yang
mempengaruhi perilaku. `client_id` NULL = scope platform;
irisan ini hanya menulis NULL (kolomnya ada supaya key per-workspace nanti tidak butuh migrasi
ulang). Keunikan lewat dua indeks parsial karena NULL tidak dianggap sama oleh unique constraint
biasa.

Downgrade membuang tabel beserta isinya: key yang sudah diatur dari UI hilang dan kode jatuh ke
nilai `.env` (yang sengaja dibiarkan terisi sebagai fallback), jadi tidak ada yang berhenti jalan.

Revision ID: a3f81c2d9b47
Revises: 7e51efe6d78b
Create Date: 2026-10-16 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f81c2d9b47"
down_revision: str | None = "7e51efe6d78b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_secrets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("client_id", sa.String(length=50), nullable=True),
        sa.Column("secrets_enc", sa.LargeBinary(), nullable=False),
        sa.Column("updated_by", sa.String(length=200), nullable=False),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name=op.f("fk_runtime_secrets_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runtime_secrets")),
    )
    op.create_index(
        "uq_runtime_secrets_platform",
        "runtime_secrets",
        ["provider"],
        unique=True,
        postgresql_where=sa.text("client_id IS NULL"),
    )
    op.create_index(
        "uq_runtime_secrets_client",
        "runtime_secrets",
        ["client_id", "provider"],
        unique=True,
        postgresql_where=sa.text("client_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_runtime_secrets_client",
        table_name="runtime_secrets",
        postgresql_where=sa.text("client_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_runtime_secrets_platform",
        table_name="runtime_secrets",
        postgresql_where=sa.text("client_id IS NULL"),
    )
    op.drop_table("runtime_secrets")
