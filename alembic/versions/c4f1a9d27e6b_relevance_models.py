"""relevance_models: model relevansi lokal + status gate (P5)

Buat `relevance_models` dengan indeks unik parsial `WHERE status = 'active'` (satu model
aktif). Downgrade menghapus tabel; model terlatih hilang dan dilatih ulang oleh task.

Revision ID: c4f1a9d27e6b
Revises: b8e2c4a6d1f3
Create Date: 2026-10-26 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f1a9d27e6b"
down_revision: str | None = "b8e2c4a6d1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "relevance_models",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("artifact", sa.LargeBinary(), nullable=True),
        sa.Column("feature_version", sa.String(length=200), nullable=False),
        sa.Column("n_examples", sa.Integer(), nullable=False),
        sa.Column("class_counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "gate_state", sa.String(length=10), server_default=sa.text("'shadow'"), nullable=False
        ),
        sa.Column("gate_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_relevance_models"),
    )
    op.create_index(
        "uq_relevance_models_active",
        "relevance_models",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_relevance_models_active", table_name="relevance_models")
    op.drop_table("relevance_models")
