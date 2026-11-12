"""Exec redesign (sub-proyek 3): tabel `exec_briefs`, brief eksekutif harian bersama.

Satu baris per tanggal Jakarta, tanpa `client_id` (brief platform-wide). Tabel baru dan tanpa
foreign key, jadi aditif: container lama mengabaikannya, aman untuk `deploy.sh` (migrate dulu).
Rollback deploy.sh hanya re-tag image dan tidak men-downgrade.

Revision ID: c4e8a1f2b9d6
Revises: b7d41e9a2c63
Create Date: 2026-11-11 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4e8a1f2b9d6"
down_revision: str | Sequence[str] | None = "b7d41e9a2c63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exec_briefs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("brief_date", sa.Date(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("generated_by", sa.String(200), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("prompt_version", sa.String(16), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exec_briefs")),
        sa.UniqueConstraint("brief_date", name="uq_exec_briefs_brief_date"),
    )


def downgrade() -> None:
    op.drop_table("exec_briefs")
