"""katalog tech, mirror CVE, dan target Monitor (ROADMAP #19, irisan 2)

Tabel baru (rancangan: `docs/CVE_CATALOG_DESIGN.md` 3):
- `catalog_vendors`, `catalog_families`, `catalog_family_aliases`: katalog, PERMANEN (statistik
  hanya naik).
- `cve_records`, `cve_record_products`: mirror CVE, dibuang retensi tahun kalender; sengaja tanpa
  FK ke `cve_tracker`.
- `techstack_targets`: sasaran katalog (vendor ATAU keluarga, tepat satu) per entri techstack.

Kolom baru `techstack_entries.active` (default true): semua entri yang ada tetap aktif. Entri
tanpa target (semua entri sekarang) tetap dicocokkan lewat teks seperti sebelumnya, jadi migrasi
ini tidak mengubah perilaku apa pun. FK ke katalog `RESTRICT`: vendor/keluarga yang dirujuk
Monitor atau mirror tidak bisa terhapus.

Revision ID: b7e3d9a1c5f2
Revises: e8c2a4b6d1f3
Create Date: 2026-10-07 10:59:00.473455

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3d9a1c5f2"
down_revision: str | None = "e8c2a4b6d1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_vendors",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=False),
        sa.Column("display_source", sa.String(length=3), nullable=False),
        sa.Column("monitorable", sa.Boolean(), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_cve_at", sa.Date(), nullable=True),
        sa.Column("cve_seen_total", sa.Integer(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_vendors")),
        sa.UniqueConstraint("key", name=op.f("uq_catalog_vendors_key")),
    )
    op.create_table(
        "cve_records",
        sa.Column("cve_id", sa.String(length=20), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("solutions", sa.Text(), nullable=True),
        sa.Column("cvss_score", sa.Float(), nullable=True),
        sa.Column("cvss_severity", sa.String(length=20), nullable=True),
        sa.Column("cvss_vector", sa.String(length=100), nullable=True),
        sa.Column("reference_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("affected_lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("has_identity", sa.Boolean(), nullable=False),
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
        sa.PrimaryKeyConstraint("cve_id", name=op.f("pk_cve_records")),
    )
    op.create_index(
        op.f("ix_cve_records_published_date"), "cve_records", ["published_date"], unique=False
    )
    op.create_table(
        "catalog_families",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("vendor_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.String(length=400), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("display_source", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=True),
        sa.Column("last_cve_at", sa.Date(), nullable=True),
        sa.Column("cve_seen_total", sa.Integer(), nullable=False),
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
            ["vendor_id"],
            ["catalog_vendors.id"],
            name=op.f("fk_catalog_families_vendor_id_catalog_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_families")),
        sa.UniqueConstraint("vendor_id", "key", name="uq_catalog_families_vendor_key"),
    )
    op.create_index(
        op.f("ix_catalog_families_vendor_id"), "catalog_families", ["vendor_id"], unique=False
    )
    op.create_table(
        "catalog_family_aliases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("alias_key", sa.String(length=800), nullable=False),
        sa.Column("family_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=True),
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
            ["family_id"],
            ["catalog_families.id"],
            name=op.f("fk_catalog_family_aliases_family_id_catalog_families"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_family_aliases")),
        sa.UniqueConstraint("alias_key", name=op.f("uq_catalog_family_aliases_alias_key")),
    )
    op.create_index(
        op.f("ix_catalog_family_aliases_family_id"),
        "catalog_family_aliases",
        ["family_id"],
        unique=False,
    )
    op.create_table(
        "cve_record_products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("cve_id", sa.String(length=20), nullable=False),
        sa.Column("vendor_id", sa.BigInteger(), nullable=False),
        sa.Column("family_id", sa.BigInteger(), nullable=False),
        sa.Column("vendor_raw", sa.Text(), nullable=False),
        sa.Column("product_raw", sa.Text(), nullable=False),
        sa.Column("product_norm", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["cve_id"],
            ["cve_records.cve_id"],
            name=op.f("fk_cve_record_products_cve_id_cve_records"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["catalog_families.id"],
            name=op.f("fk_cve_record_products_family_id_catalog_families"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["catalog_vendors.id"],
            name=op.f("fk_cve_record_products_vendor_id_catalog_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cve_record_products")),
        sa.UniqueConstraint("cve_id", "family_id", name="uq_cve_record_products_cve_family"),
    )
    op.create_index(
        op.f("ix_cve_record_products_family_id"), "cve_record_products", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_cve_record_products_vendor_id"), "cve_record_products", ["vendor_id"], unique=False
    )
    op.create_table(
        "techstack_targets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entry_id", sa.BigInteger(), nullable=False),
        sa.Column("vendor_id", sa.BigInteger(), nullable=True),
        sa.Column("family_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "(vendor_id IS NOT NULL) <> (family_id IS NOT NULL)",
            name=op.f("ck_techstack_targets_exactly_one_target"),
        ),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["techstack_entries.id"],
            name=op.f("fk_techstack_targets_entry_id_techstack_entries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["catalog_families.id"],
            name=op.f("fk_techstack_targets_family_id_catalog_families"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["catalog_vendors.id"],
            name=op.f("fk_techstack_targets_vendor_id_catalog_vendors"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_techstack_targets")),
    )
    op.create_index(
        op.f("ix_techstack_targets_entry_id"), "techstack_targets", ["entry_id"], unique=False
    )
    op.create_index(
        op.f("ix_techstack_targets_family_id"), "techstack_targets", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_techstack_targets_vendor_id"), "techstack_targets", ["vendor_id"], unique=False
    )
    op.create_index(
        "uq_techstack_targets_entry_family",
        "techstack_targets",
        ["entry_id", "family_id"],
        unique=True,
        postgresql_where=sa.text("family_id IS NOT NULL"),
    )
    op.create_index(
        "uq_techstack_targets_entry_vendor",
        "techstack_targets",
        ["entry_id", "vendor_id"],
        unique=True,
        postgresql_where=sa.text("vendor_id IS NOT NULL"),
    )
    op.add_column(
        "techstack_entries",
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("techstack_entries", "active")
    op.drop_index(
        "uq_techstack_targets_entry_vendor",
        table_name="techstack_targets",
        postgresql_where=sa.text("vendor_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_techstack_targets_entry_family",
        table_name="techstack_targets",
        postgresql_where=sa.text("family_id IS NOT NULL"),
    )
    op.drop_index(op.f("ix_techstack_targets_vendor_id"), table_name="techstack_targets")
    op.drop_index(op.f("ix_techstack_targets_family_id"), table_name="techstack_targets")
    op.drop_index(op.f("ix_techstack_targets_entry_id"), table_name="techstack_targets")
    op.drop_table("techstack_targets")
    op.drop_index(op.f("ix_cve_record_products_vendor_id"), table_name="cve_record_products")
    op.drop_index(op.f("ix_cve_record_products_family_id"), table_name="cve_record_products")
    op.drop_table("cve_record_products")
    op.drop_index(op.f("ix_catalog_family_aliases_family_id"), table_name="catalog_family_aliases")
    op.drop_table("catalog_family_aliases")
    op.drop_index(op.f("ix_catalog_families_vendor_id"), table_name="catalog_families")
    op.drop_table("catalog_families")
    op.drop_index(op.f("ix_cve_records_published_date"), table_name="cve_records")
    op.drop_table("cve_records")
    op.drop_table("catalog_vendors")
