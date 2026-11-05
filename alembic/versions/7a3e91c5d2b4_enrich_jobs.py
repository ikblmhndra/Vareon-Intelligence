"""P7g persist-first: tabel `enrich_jobs`, kolom `articles.llm_ttp_status`, dan pemindahan baris
`rejected_articles` yang sebenarnya kegagalan enrichment (`failure_kind IS NOT NULL`).

`transient`/`config`/`json` jadi job `classify` berstatus `pending`; `permanent` jadi `failed`
(alasan lama tetap di `last_error`). `input_text` NULL: pipeline menjalankan bagian depan dulu.
Setelah itu `rejected_articles` hanya berisi penolakan klasifikasi.

Revision ID: 7a3e91c5d2b4
Revises: 1387fae00908
Create Date: 2026-11-02 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7a3e91c5d2b4"
down_revision: str | Sequence[str] | None = "1387fae00908"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "enrich_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("scraper_id", sa.String(100), nullable=True),
        sa.Column("posted_on", sa.Date(), nullable=True),
        sa.Column("article_id", sa.BigInteger(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("state", sa.String(10), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("json_failures", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["articles.id"],
            name=op.f("fk_enrich_jobs_article_id_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_enrich_jobs")),
        sa.UniqueConstraint("kind", "url_hash", name="uq_enrich_jobs_kind_url_hash"),
        sa.CheckConstraint("kind IN ('classify', 'ttp')", name=op.f("ck_enrich_jobs_kind_valid")),
        sa.CheckConstraint(
            "state IN ('pending', 'failed')", name=op.f("ck_enrich_jobs_state_valid")
        ),
    )
    op.create_index(
        "ix_enrich_jobs_state_kind_next", "enrich_jobs", ["state", "kind", "next_attempt_at"]
    )
    op.add_column("articles", sa.Column("llm_ttp_status", sa.String(10), nullable=True))
    op.create_check_constraint(
        op.f("ck_articles_llm_ttp_status_valid"),
        "articles",
        "llm_ttp_status IN ('pending', 'done', 'skipped', 'failed')",
    )
    op.execute(
        """
        INSERT INTO enrich_jobs
            (kind, url, url_hash, title, source, scraper_id, posted_on, state, last_error,
             created_at)
        SELECT 'classify', url, url_hash, title, source, scraper_id, posted_on,
               CASE WHEN failure_kind = 'permanent' THEN 'failed' ELSE 'pending' END,
               CASE WHEN failure_kind = 'permanent' THEN reason END,
               rejected_at
        FROM rejected_articles
        WHERE failure_kind IS NOT NULL
        """
    )
    op.execute("DELETE FROM rejected_articles WHERE failure_kind IS NOT NULL")


def downgrade() -> None:
    """Hanya membuang tabel dan kolom. Baris `rejected_articles` yang sudah dipindahkan ke
    `enrich_jobs` TIDAK dikembalikan (isi job hilang bersama tabelnya)."""
    op.drop_constraint(op.f("ck_articles_llm_ttp_status_valid"), "articles", type_="check")
    op.drop_column("articles", "llm_ttp_status")
    op.drop_index("ix_enrich_jobs_state_kind_next", table_name="enrich_jobs")
    op.drop_table("enrich_jobs")
