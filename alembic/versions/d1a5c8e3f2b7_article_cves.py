"""article_cves: CVE artikel pindah dari iocs (type 'cve') ke tabel sendiri

Buat `article_cves`, salin setiap pasangan (artikel, CVE) dari `ioc_sources` + `iocs` bertipe
`cve`, lalu hapus IOC `cve` (sumber, tag, dan feedback ikut terhapus lewat cascade). Downgrade
hanya menghapus tabel: IOC `cve` yang sudah dihapus tidak dikembalikan.

Revision ID: d1a5c8e3f2b7
Revises: c4e7a2b9d1f0
Create Date: 2026-10-25 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1a5c8e3f2b7"
down_revision: str | None = "c4e7a2b9d1f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COPY_CVE_SQL = """
INSERT INTO article_cves (article_id, cve_id, in_title, first_seen_at)
SELECT s.article_id,
       upper(i.value),
       bool_or(position(upper(i.value) in upper(a.title)) > 0),
       min(s.first_seen_at)
FROM ioc_sources s
JOIN iocs i ON i.id = s.ioc_id
JOIN articles a ON a.id = s.article_id
WHERE i.type = 'cve' AND s.article_id IS NOT NULL AND length(i.value) <= 20
GROUP BY s.article_id, upper(i.value)
ON CONFLICT DO NOTHING
"""

DELETE_CVE_IOCS_SQL = "DELETE FROM iocs WHERE type = 'cve'"


def upgrade() -> None:
    op.create_table(
        "article_cves",
        sa.Column("article_id", sa.BigInteger(), nullable=False),
        sa.Column("cve_id", sa.String(length=20), nullable=False),
        sa.Column("in_title", sa.Boolean(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("article_id", "cve_id"),
    )
    op.create_index("ix_article_cves_cve_id", "article_cves", ["cve_id"])
    op.execute(COPY_CVE_SQL)
    op.execute(DELETE_CVE_IOCS_SQL)


def downgrade() -> None:
    op.drop_index("ix_article_cves_cve_id", table_name="article_cves")
    op.drop_table("article_cves")
