"""Dashboard 5a: kolom `articles.summary`, kutipan ekstraktif yang disimpan.

Nullable dan tanpa backfill: teks artikel tidak disimpan di database (hanya diambil saat
enrichment), jadi artikel lama tidak bisa dihitung ulang dan tetap NULL. Kolom aditif tanpa
default, jadi container lama mengabaikannya: aman untuk `deploy.sh` (migrate dulu). Rollback
deploy.sh hanya re-tag image dan tidak men-downgrade.

Revision ID: d9f2b6a4c1e7
Revises: c4e8a1f2b9d6
Create Date: 2026-11-14 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9f2b6a4c1e7"
down_revision: str | Sequence[str] | None = "c4e8a1f2b9d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "summary")
