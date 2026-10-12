"""`daily_recaps`: kolom `quality` (JSONB): perbandingan pekan, grounding, scorecard forecast

ROADMAP #21, PR 3 (kualitas recap mingguan). `quality` menampung hasil yang dihitung KODE, bukan
ditulis LLM: `comparison` (selisih dengan pekan sebelumnya), `grounding` (item keluaran yang dibuang
karena tidak ada di masukan) dan `scorecard` (review forecast pekan lalu beserta override analis).
Baris harian dan baris lama tidak punya isinya: `{}`.

Aditif sepenuhnya. `server_default` TETAP dipasang (tidak dilepas seperti di migrasi kolom lain)
karena kolomnya NOT NULL: kode lama (rollback, atau deploy bergulir saat migrasi sudah jalan tapi
image lama belum diganti) tetap bisa INSERT tanpa menyebut `quality`, sama seperti `kind` di migrasi
sebelumnya. Downgrade membuang kolom beserta isinya; data yang hilang hanya hasil hitungan dan
override analis, bukan recapnya.

Revision ID: 7e51efe6d78b
Revises: a042eff910ac
Create Date: 2026-10-11 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e51efe6d78b"
down_revision: str | None = "a042eff910ac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_recaps",
        sa.Column(
            "quality",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("daily_recaps", "quality")
