"""llm_calls + kolom auto-replay di rejected_articles + failure_kind 'config'

Tabel `llm_calls` (log metadata tiap panggilan LLM), dua kolom `rejected_articles`
(`auto_replay_count`, `last_auto_replay_at`) untuk replay otomatis, dan backfill: baris
`permanent` yang `reason`-nya BadRequest/NotFound/Authentication/PermissionDenied dipindah ke
`config` (kegagalan konfigurasi, tidak ikut replay otomatis).

Revision ID: c4e7a2b9d1f0
Revises: b7e4c1a9d256
Create Date: 2026-10-24 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e7a2b9d1f0"
down_revision: str | None = "b7e4c1a9d256"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_CONFIG_SQL = """
UPDATE rejected_articles SET failure_kind = 'config'
WHERE failure_kind = 'permanent' AND (
    reason LIKE '[enrichment_failed] BadRequestError%'
    OR reason LIKE '[enrichment_failed] NotFoundError%'
    OR reason LIKE '[enrichment_failed] AuthenticationError%'
    OR reason LIKE '[enrichment_failed] PermissionDeniedError%'
)
"""


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("task", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("error_type", sa.String(length=80), nullable=True),
        sa.Column("http_status", sa.SmallInteger(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_calls_at", "llm_calls", ["at"])
    op.create_index("ix_llm_calls_task_at", "llm_calls", ["task", "at"])
    op.add_column(
        "rejected_articles",
        sa.Column("auto_replay_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "rejected_articles",
        sa.Column("last_auto_replay_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(BACKFILL_CONFIG_SQL)


def downgrade() -> None:
    op.execute(
        "UPDATE rejected_articles SET failure_kind = 'permanent' WHERE failure_kind = 'config'"
    )
    op.drop_column("rejected_articles", "last_auto_replay_at")
    op.drop_column("rejected_articles", "auto_replay_count")
    op.drop_index("ix_llm_calls_task_at", table_name="llm_calls")
    op.drop_index("ix_llm_calls_at", table_name="llm_calls")
    op.drop_table("llm_calls")
