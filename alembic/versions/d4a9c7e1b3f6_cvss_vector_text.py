"""`cvss_vector` jadi TEXT di `cve_tracker` dan `cve_records`

Vektor CVSS yang memuat metrik temporal/environmental melewati 100 karakter: ketemu di backfill
mirror pada data nyata (CVE-2025-1787: v4.0 = 125 karakter; CVE-2025-27363: v3.1 = 117), 4 berkas
pertama gagal `StringDataRightTruncation`. Kolom `cve_tracker.cvss_vector` (`VARCHAR(100)` sejak
skema awal) punya batas yang sama, jadi `new_cve` dan promosi mirror (irisan 4) bisa gagal pada CVE
seperti itu. Vektor tidak punya panjang maksimum yang berguna untuk ditebak, jadi tipe TEXT
(`VARCHAR` -> `TEXT` di Postgres hanya mengubah metadata, tanpa menulis ulang tabel).

Downgrade memotong ke 100 karakter (vektor lebih panjang tidak muat di tipe lama).

Revision ID: d4a9c7e1b3f6
Revises: b7e3d9a1c5f2
Create Date: 2026-10-07 14:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4a9c7e1b3f6"
down_revision: str | None = "b7e3d9a1c5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("cve_tracker", "cve_records")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "cvss_vector",
            existing_type=sa.String(length=100),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "cvss_vector",
            existing_type=sa.Text(),
            type_=sa.String(length=100),
            existing_nullable=True,
            postgresql_using="left(cvss_vector, 100)",
        )
