"""qa 2026-10-05: kolom `raw_enrichment` di rejected_articles

Commit e0454f0 menulis audit trail respons LLM klasifikasi ke `RejectedArticle.raw_enrichment`, tapi
model dan migrasinya tidak pernah punya kolomnya -> setiap penolakan artikel gagal tersimpan.

Revision ID: d7b1f3a9c2e5
Revises: c3a7e9d1f2b4
Create Date: 2026-10-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7b1f3a9c2e5"
down_revision: str | None = "c3a7e9d1f2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default hanya untuk mengisi baris lama; model memakai default Python (`dict`).
    op.add_column(
        "rejected_articles",
        sa.Column(
            "raw_enrichment",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("rejected_articles", "raw_enrichment", server_default=None)


def downgrade() -> None:
    op.drop_column("rejected_articles", "raw_enrichment")
