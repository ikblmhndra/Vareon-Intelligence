"""stories: kelompok artikel berita sama + articles.story_id / story_match

Buat `stories` (korpus global), tambah `articles.story_id` (FK `ON DELETE SET NULL`, indeks)
dan `articles.story_match`. Downgrade menghapus kolom lalu tabel; story yang sudah terbentuk
hilang, artikelnya tetap.

Revision ID: a7d3f1c9e5b2
Revises: f3c9e1b5a7d2
Create Date: 2026-10-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3f1c9e5b2"
down_revision: str | None = "f3c9e1b5a7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("lead_source", sa.String(length=200), nullable=False),
        sa.Column("lead_article_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "cve_ids",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("classify", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("article_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("source_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["lead_article_id"],
            ["articles.id"],
            name="fk_stories_lead_article_id_articles",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stories"),
    )
    op.create_index("ix_stories_cve_ids", "stories", ["cve_ids"], postgresql_using="gin")
    op.create_index("ix_stories_last_seen_at", "stories", ["last_seen_at"])

    op.add_column("articles", sa.Column("story_id", sa.BigInteger(), nullable=True))
    op.add_column("articles", sa.Column("story_match", sa.String(length=20), nullable=True))
    op.create_foreign_key(
        "fk_articles_story_id_stories",
        "articles",
        "stories",
        ["story_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_articles_story_id", "articles", ["story_id"])


def downgrade() -> None:
    op.drop_index("ix_articles_story_id", table_name="articles")
    op.drop_constraint("fk_articles_story_id_stories", "articles", type_="foreignkey")
    op.drop_column("articles", "story_match")
    op.drop_column("articles", "story_id")
    op.drop_index("ix_stories_last_seen_at", table_name="stories")
    op.drop_index("ix_stories_cve_ids", table_name="stories", postgresql_using="gin")
    op.drop_table("stories")
