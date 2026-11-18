"""tweet_verdicts: catatan tiap klasifikasi tweet (label latih model relevansi tweet).

Tabel baru, aditif; tidak ada yang menulisnya sebelum kode barunya jalan, jadi aman untuk
`deploy.sh` (migrate dulu). Downgrade menjatuhkan tabel (data audit/latih hilang, bukan `tweets`).

Revision ID: f4c8a2d6b9e1
Revises: e3b7c5a9d1f4
Create Date: 2026-11-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f4c8a2d6b9e1"
down_revision: str | Sequence[str] | None = "e3b7c5a9d1f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tweet_verdicts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tweet_id", sa.String(length=50), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("related_cyber", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=True),
        sa.Column("relevance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source IN ('llm', 'gate')", name=op.f("ck_tweet_verdicts_source_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tweet_verdicts")),
        sa.UniqueConstraint("tweet_id", name=op.f("uq_tweet_verdicts_tweet_id")),
    )


def downgrade() -> None:
    op.drop_table("tweet_verdicts")
