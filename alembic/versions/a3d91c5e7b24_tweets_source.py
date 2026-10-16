"""`tweets.source`: scraper yang pertama menyimpan tweet

Jalur `tweet_alerts_*` akan ikut menulis ke `tweets` (tweet yang lolos klasifikasi dan di-alert ke
Telegram, supaya tab X Intel tidak buta terhadap akun yang cuma ada di daftar alert). `source`
membedakan penulisnya. `monitor_x` memakai `MAX(tweet_id)` per akun sebagai `since_id`, jadi baris
dari jalur alert HARUS dikecualikan dari perhitungan itu (lihat
`cti_scraper.reference_data._resolve_tweet_last_seen_ids`).

Baris lama diisi `monitor_x` lewat `server_default`: sampai sekarang `monitor_x` satu-satunya
penulis `tweets`. Aditif, jadi kode lama (rollback, atau deploy bergulir) tetap bisa INSERT tanpa
kolom ini.

Revision ID: a3d91c5e7b24
Revises: 7e51efe6d78b
Create Date: 2026-10-16 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d91c5e7b24"
down_revision: str | None = "7e51efe6d78b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tweets",
        sa.Column("source", sa.String(length=100), server_default="monitor_x", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("tweets", "source")
