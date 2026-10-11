"""newsletter: tabel saran konten bulanan (ROADMAP #22, PR 7)

`newsletter_suggestions`: satu baris per jendela edisi, `(period_start, period_end)` unik. Isinya
daftar artikel yang direkomendasikan (`items`, JSONB: `{article_id, section, tier, rank,
reasons}`) plus tempat untuk Executive Summary (`summary_text`, `summary_meta`) yang baru diisi
PR 8. Tidak ada kolom status (tidak dipilih user) dan tidak ada FK ke `articles` (snapshot hari
saran dibangun). Tabel baru dan kosong; tidak menyentuh tabel lain, jadi downgrade cukup
menjatuhkannya.

Revision ID: 1dbf6006abaf
Revises: a042eff910ac
Create Date: 2026-10-11 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1dbf6006abaf"
down_revision: str | None = "a042eff910ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "newsletter_suggestions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("summary_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_newsletter_suggestions")),
        sa.UniqueConstraint("period_start", "period_end", name="uq_newsletter_suggestion_period"),
    )


def downgrade() -> None:
    op.drop_table("newsletter_suggestions")
