"""Hunting packs (P7e): tabel `sigma_rules` dan `hunt_hypotheses`.

Rollback deploy.sh hanya re-tag image dan tidak men-downgrade; image lama mengabaikan kedua tabel.

Revision ID: 7e3b9c1d5a42
Revises: 7a3e91c5d2b4
Create Date: 2026-11-04 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7e3b9c1d5a42"
down_revision: str | Sequence[str] | None = "7a3e91c5d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sigma_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("ruleset", sa.String(20), nullable=False),
        sa.Column("logsource", postgresql.JSONB(), nullable=False),
        sa.Column("techniques", postgresql.ARRAY(sa.String(20)), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("release", sa.String(40), nullable=False),
        sa.Column("yaml", sa.Text(), nullable=False),
        sa.Column(
            "loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sigma_rules")),
    )
    op.create_index(
        "ix_sigma_rules_techniques", "sigma_rules", ["techniques"], postgresql_using="gin"
    )
    op.create_table(
        "hunt_hypotheses",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("anchor_type", sa.String(10), nullable=False),
        sa.Column("anchor_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("generated_by", sa.String(200), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "anchor_type IN ('story', 'entity')", name=op.f("ck_hunt_hypotheses_anchor_type")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hunt_hypotheses")),
        sa.UniqueConstraint("anchor_type", "anchor_id", name="uq_hunt_hypotheses_anchor"),
    )


def downgrade() -> None:
    op.drop_table("hunt_hypotheses")
    op.drop_index("ix_sigma_rules_techniques", table_name="sigma_rules")
    op.drop_table("sigma_rules")
