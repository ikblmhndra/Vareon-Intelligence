"""relevance_models.kind: satu model relevansi aktif per jenis (article / tweet).

Kolom `kind` NOT NULL dengan server default `'article'`: baris P5 yang ada (model artikel
live) otomatis jadi `article`, perilaku artikel tidak berubah. Indeks unik parsial
`uq_relevance_models_active` dibuat ulang pada `kind` (sebelumnya pada `status`, yang hanya
mengizinkan satu `active` untuk seluruh tabel). Downgrade hanya aman bila tidak ada baris
`tweet` aktif; baris `tweet` dihapus dulu supaya indeks lama bisa dibuat lagi.

Revision ID: a7d3e1b5c9f2
Revises: f4c8a2d6b9e1
Create Date: 2026-11-16 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d3e1b5c9f2"
down_revision: str | Sequence[str] | None = "f4c8a2d6b9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "relevance_models",
        sa.Column(
            "kind", sa.String(length=10), server_default=sa.text("'article'"), nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_relevance_models_kind_valid"), "relevance_models", "kind IN ('article', 'tweet')"
    )
    op.drop_index("uq_relevance_models_active", table_name="relevance_models")
    op.create_index(
        "uq_relevance_models_active",
        "relevance_models",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM relevance_models WHERE kind <> 'article'")
    op.drop_index("uq_relevance_models_active", table_name="relevance_models")
    op.create_index(
        "uq_relevance_models_active",
        "relevance_models",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_constraint(op.f("ck_relevance_models_kind_valid"), "relevance_models", type_="check")
    op.drop_column("relevance_models", "kind")
