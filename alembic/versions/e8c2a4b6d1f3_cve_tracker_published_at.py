"""cve_tracker.published_at: jam publish asli dari MITRE

`cve_tracker.published` cuma tanggal (scraper memotong `cveMetadata.datePublished`), padahal export
Excel butuh jamnya buat kolom "CVE Reported Date" (dibedakan dari "Reported by System" =
`detected_on`, waktu scraper dapat CVE-nya). Nullable: baris lama tidak punya jamnya sampai
di-backfill (`tools/ops/backfill_cve_published_at.py`) atau ditulis ulang scraper.

Revision ID: e8c2a4b6d1f3
Revises: d7b1f3a9c2e5
Create Date: 2026-10-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8c2a4b6d1f3"
down_revision: str | None = "d7b1f3a9c2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cve_tracker", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("cve_tracker", "published_at")
