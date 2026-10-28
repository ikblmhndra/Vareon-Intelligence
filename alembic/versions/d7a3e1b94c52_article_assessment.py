"""article_assessment: kolom penilaian Admiralty artikel + content_kind sumber (P6)

Tambah `articles.reliability_grade/credibility/priority_score/score_reasons` (semua nullable
kecuali `score_reasons` default `{}`), check `credibility BETWEEN 1 AND 6`, indeks
`priority_score DESC NULLS LAST`, dan `source_reliability_entries.content_kind`. Tanpa backfill
(spec 4.4 yang mengisi). Downgrade membuang semuanya.

Revision ID: d7a3e1b94c52
Revises: c4f1a9d27e6b
Create Date: 2026-10-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7a3e1b94c52"
down_revision: str | None = "c4f1a9d27e6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("reliability_grade", sa.String(length=1), nullable=True))
    op.add_column("articles", sa.Column("credibility", sa.SmallInteger(), nullable=True))
    op.add_column("articles", sa.Column("priority_score", sa.SmallInteger(), nullable=True))
    op.add_column(
        "articles",
        sa.Column(
            "score_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_articles_credibility_range"), "articles", "credibility BETWEEN 1 AND 6"
    )
    op.create_index(
        "ix_articles_priority_score",
        "articles",
        [sa.text("priority_score DESC NULLS LAST")],
    )
    op.add_column(
        "source_reliability_entries",
        sa.Column("content_kind", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_reliability_entries", "content_kind")
    op.drop_index("ix_articles_priority_score", table_name="articles")
    op.drop_constraint(op.f("ck_articles_credibility_range"), "articles", type_="check")
    op.drop_column("articles", "score_reasons")
    op.drop_column("articles", "priority_score")
    op.drop_column("articles", "credibility")
    op.drop_column("articles", "reliability_grade")
