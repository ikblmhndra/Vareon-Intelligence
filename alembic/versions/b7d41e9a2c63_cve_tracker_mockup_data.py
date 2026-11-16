"""CVE Tracker redesign (2a): kolom alasan FP, jejak ubah ticket, tim pemilik, hide keluarga
katalog, dan `monitored_packages.source_path`.

Aditif dan nullable (kecuali tabel baru), aman untuk `deploy.sh` (migrate dulu, container lama
mengabaikan kolom/tabel baru). Rollback deploy.sh hanya re-tag image dan tidak men-downgrade.

Revision ID: b7d41e9a2c63
Revises: 7e3b9c1d5a42
Create Date: 2026-11-09 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7d41e9a2c63"
down_revision: str | Sequence[str] | None = "7e3b9c1d5a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_UPDATED_BY_SQL = (
    "UPDATE cve_tickets SET updated_by = acknowledged_by"
    " WHERE updated_by IS NULL AND acknowledged_by IS NOT NULL"
)
"""Ticket lama belum punya jejak pengubah; acknowledger adalah satu-satunya nama yang diketahui."""

BACKFILL_OWNER_TEAMS_SQL = (
    "INSERT INTO cve_owner_teams (client_id, name, active, created_at, updated_at)"
    " SELECT DISTINCT client_id, btrim(owner_team), true, now(), now() FROM cve_tickets"
    " WHERE btrim(coalesce(owner_team, '')) <> ''"
    " ON CONFLICT (client_id, name) DO NOTHING"
)
"""Seed dropdown tim dari teks bebas yang sudah dipakai ticket; idempoten lewat ON CONFLICT."""


def upgrade() -> None:
    op.add_column("cve_false_positives", sa.Column("reason", sa.String(40), nullable=True))
    op.add_column("cve_false_positives", sa.Column("note", sa.Text(), nullable=True))
    op.add_column("cve_tickets", sa.Column("updated_by", sa.String(200), nullable=True))
    op.add_column(
        "cve_tickets",
        sa.Column("escalation_notified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "cve_owner_teams",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("client_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("lead_name", sa.String(200), nullable=True),
        sa.Column("lead_email", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name=op.f("fk_cve_owner_teams_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cve_owner_teams")),
        sa.UniqueConstraint("client_id", "name", name="uq_cve_owner_teams_client_name"),
    )
    op.create_index(
        op.f("ix_cve_owner_teams_client_id"), "cve_owner_teams", ["client_id"], unique=False
    )
    op.create_table(
        "catalog_family_hides",
        sa.Column("client_id", sa.String(50), nullable=False),
        sa.Column("family_id", sa.BigInteger(), nullable=False),
        sa.Column("hidden_by", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.client_id"],
            name=op.f("fk_catalog_family_hides_client_id_clients"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["catalog_families.id"],
            name=op.f("fk_catalog_family_hides_family_id_catalog_families"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("client_id", "family_id", name=op.f("pk_catalog_family_hides")),
    )
    op.create_index(
        op.f("ix_catalog_family_hides_family_id"),
        "catalog_family_hides",
        ["family_id"],
        unique=False,
    )
    op.add_column("monitored_packages", sa.Column("source_path", sa.String(500), nullable=True))
    op.execute(BACKFILL_UPDATED_BY_SQL)
    op.execute(BACKFILL_OWNER_TEAMS_SQL)


def downgrade() -> None:
    op.drop_column("monitored_packages", "source_path")
    op.drop_index(op.f("ix_catalog_family_hides_family_id"), table_name="catalog_family_hides")
    op.drop_table("catalog_family_hides")
    op.drop_index(op.f("ix_cve_owner_teams_client_id"), table_name="cve_owner_teams")
    op.drop_table("cve_owner_teams")
    op.drop_column("cve_tickets", "escalation_notified_at")
    op.drop_column("cve_tickets", "updated_by")
    op.drop_column("cve_false_positives", "note")
    op.drop_column("cve_false_positives", "reason")
