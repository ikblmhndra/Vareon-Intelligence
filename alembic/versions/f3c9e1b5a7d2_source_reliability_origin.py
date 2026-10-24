"""`source_reliability_entries.origin`: asal baris grade sumber (rilis 0.8.6, spec P2 5.1)

`default` = baris awal dari `content_kind` scraper (dibuat saat API start), `analyst` = diketik
atau diedit analis. Baris yang sudah ada hasil kurasi analis, jadi `server_default` 'analyst'.
Baris `default` TIDAK dibuat di migrasi: bootstrap API membuatnya dari registry scraper.

Revision ID: f3c9e1b5a7d2
Revises: e7b2d4a9c6f1
Create Date: 2026-10-25 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c9e1b5a7d2"
down_revision: str | None = "e7b2d4a9c6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_reliability_entries",
        sa.Column("origin", sa.String(length=10), server_default="analyst", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("source_reliability_entries", "origin")
