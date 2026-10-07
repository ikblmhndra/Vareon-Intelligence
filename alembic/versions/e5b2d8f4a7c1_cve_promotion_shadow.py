"""tabel `cve_promotion_shadow` (mode bayangan promosi mirror -> cve_tracker, ROADMAP #19 irisan 4)

Menampung hasil pencocokan mirror terhadap techstack TANPA menulis `cve_tracker`: untuk (CVE,
client) mana promosi AKAN membuat baris, dengan tech/entri/kekhususan apa. Dipakai
`tools/ops/compare_promotion_shadow.py` untuk membandingkan dengan hasil `new_cve` sebelum
cutover. Tabel baru, kosong, tidak dibaca aplikasi mana pun: tidak mengubah perilaku.

Revision ID: e5b2d8f4a7c1
Revises: d4a9c7e1b3f6
Create Date: 2026-10-08 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b2d8f4a7c1"
down_revision: str | None = "d4a9c7e1b3f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cve_promotion_shadow",
        sa.Column("cve_id", sa.String(length=20), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("tech", sa.String(length=200), nullable=False),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("specificity", sa.String(length=10), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name=op.f("fk_cve_promotion_shadow_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["techstack_entries.id"],
            name=op.f("fk_cve_promotion_shadow_entry_id_techstack_entries"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("cve_id", "client_id", name=op.f("pk_cve_promotion_shadow")),
    )
    op.create_index(
        op.f("ix_cve_promotion_shadow_client_id"), "cve_promotion_shadow", ["client_id"]
    )
    op.create_index(
        "ix_cve_promotion_shadow_published_date", "cve_promotion_shadow", ["published_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_cve_promotion_shadow_published_date", table_name="cve_promotion_shadow")
    op.drop_index(op.f("ix_cve_promotion_shadow_client_id"), table_name="cve_promotion_shadow")
    op.drop_table("cve_promotion_shadow")
