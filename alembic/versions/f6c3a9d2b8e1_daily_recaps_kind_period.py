"""`daily_recaps`: kolom `kind` + `period_start`/`period_end`, unik per `(kind, date)`

ROADMAP #21, PR 2 (recap mingguan). Recap mingguan memakai tabel yang sama (nama `daily_recaps`
tidak diganti, mengganti nama tidak sebanding dengan ributnya). `kind` = 'daily' | 'weekly'
(default 'daily'); `period_start` dan `period_end` = rentang tanggal yang dirangkum. Untuk baris
mingguan `date` = hari Senin pekan itu, `period_start` = Senin, `period_end` = Minggu. Baris lama
diisi `kind='daily'` dan kedua tanggal = `date`.

`uq_daily_recap_date` (unik di `date`) diganti `uq_daily_recap_kind_date` (unik di `(kind, date)`),
karena recap mingguan dan recap harian boleh berbagi tanggal (hari Senin yang sama).

Ini SATU-SATUNYA perubahan yang tidak aditif. **Downgrade bisa gagal** kalau saat itu ada baris
mingguan dan baris harian dengan `date` yang sama (constraint lama menolaknya): hapus salah satunya
dulu. Baris mingguan yang tidak bentrok tetap ada (dibaca kode lama sebagai baris biasa).

`period_start`/`period_end` sengaja NULLABLE: kode lama (rollback, atau deploy bergulir saat migrasi
sudah jalan tapi image lama belum diganti) tetap bisa INSERT tanpa keduanya, dan pembaca jatuh ke
`date` kalau NULL. `kind` cukup `server_default` untuk hal yang sama.

Revision ID: f6c3a9d2b8e1
Revises: e5b2d8f4a7c1
Create Date: 2026-10-11 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6c3a9d2b8e1"
down_revision: str | None = "e5b2d8f4a7c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_recaps",
        sa.Column("kind", sa.String(length=10), server_default="daily", nullable=False),
    )
    op.add_column("daily_recaps", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("daily_recaps", sa.Column("period_end", sa.Date(), nullable=True))
    # Baris lama = recap harian untuk `date` itu. `date` disimpan sebagai teks 'YYYY-MM-DD' dan
    # hanya bisa masuk lewat jalur yang sudah memvalidasinya (`fromisoformat`), jadi cast aman.
    op.execute(
        """
        UPDATE daily_recaps
        SET kind = 'daily', period_start = "date"::date, period_end = "date"::date
        """
    )
    op.drop_constraint("uq_daily_recap_date", "daily_recaps", type_="unique")
    op.create_unique_constraint("uq_daily_recap_kind_date", "daily_recaps", ["kind", "date"])


def downgrade() -> None:
    op.drop_constraint("uq_daily_recap_kind_date", "daily_recaps", type_="unique")
    # Gagal di sini kalau ada baris mingguan dan harian dengan `date` sama (lihat docstring).
    op.create_unique_constraint("uq_daily_recap_date", "daily_recaps", ["date"])
    op.drop_column("daily_recaps", "period_end")
    op.drop_column("daily_recaps", "period_start")
    op.drop_column("daily_recaps", "kind")
