"""newsletter: cache ringkasan per artikel dan kolom periode (ROADMAP #22, PR 5)

Dua perubahan, keduanya aditif:

- `newsletter_article_summaries`: cache `key_points`/`summary` plus IOC dan CVE id dari body, kunci
  `(article_id, language)`. Dengan ini `preview` dan `draft-email` tidak lagi mengulang fetch
  Playwright + panggilan LLM per artikel. Tabel baru dan kosong; baris diisi saat build pertama.
- `newsletters.period_start` / `period_end` (nullable): jendela yang diliput sebuah edisi. `week`
  dan `year` TETAP NOT NULL dan tetap diisi baris baru, jadi baris lama dan UI histori yang masih
  membaca "Week N, YYYY" tidak berubah. Baris lama dibiarkan NULL (tidak ada jendela yang bisa
  ditebak dari minggu ISO).

Revision ID: a042eff910ac
Revises: e5b2d8f4a7c1
Create Date: 2026-10-11 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a042eff910ac"
down_revision: str | None = "e5b2d8f4a7c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("newsletters", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("newsletters", sa.Column("period_end", sa.Date(), nullable=True))
    op.create_table(
        "newsletter_article_summaries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("key_points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body_source", sa.String(length=20), nullable=False),
        sa.Column("iocs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cve_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_newsletter_article_summaries_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_newsletter_article_summaries")),
        sa.UniqueConstraint("article_id", "language", name="uq_newsletter_article_summary"),
    )


def downgrade() -> None:
    op.drop_table("newsletter_article_summaries")
    op.drop_column("newsletters", "period_end")
    op.drop_column("newsletters", "period_start")
