"""enrich_jobs menerima kind `tweet` (klasifikasi LLM tweet lewat antrean persist-first).

Hanya CHECK `kind_valid` yang diperlebar; tanpa kolom baru. Aditif untuk container lama (tidak
ada yang membuat job `tweet` sebelum kode barunya jalan), jadi aman untuk `deploy.sh` (migrate
dulu). Downgrade menghapus job `tweet` yang masih antre lebih dulu supaya CHECK lama bisa
dipasang; tweet itu hilang dari antrean (bukan dari `tweets`).

Revision ID: e3b7c5a9d1f4
Revises: d9f2b6a4c1e7
Create Date: 2026-11-16 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e3b7c5a9d1f4"
down_revision: str | Sequence[str] | None = "d9f2b6a4c1e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_enrich_jobs_kind_valid"), "enrich_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_enrich_jobs_kind_valid"),
        "enrich_jobs",
        "kind IN ('classify', 'ttp', 'tweet')",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM enrich_jobs WHERE kind = 'tweet'"))
    op.drop_constraint(op.f("ck_enrich_jobs_kind_valid"), "enrich_jobs", type_="check")
    op.create_check_constraint(
        op.f("ck_enrich_jobs_kind_valid"), "enrich_jobs", "kind IN ('classify', 'ttp')"
    )
