"""Machine API (P7b): `api_tokens`, jam feed `indicators.feed_changed_at`, `indicators.stix_id`

`feed_changed_at` adalah jam feed (kursor REST, TAXII `date_added`, STIX `modified`). Ia dijaga
oleh TRIGGER Postgres, bukan kode aplikasi, supaya semua jalur tulis tercakup: kedua upsert,
feedback, PATCH marking, UPDATE mentah di `reconcile_validity`, dan tulisan lewat view
kompatibilitas `iocs` dari kode 0.8.2/0.8.10 hasil rollback. Confidence, actionability, enrichment
dan `updated_at` sengaja tidak dihitung supaya sapuan decay tidak menggeser jam.

`stix_id` diisi di Python (bukan SQL) karena rumusnya `uuid5(NAMESPACE_DNS, "type:value")` harus
identik dengan `cti_core.indicator.stix_id`; baris yang masuk dari kode lama diisi belakangan oleh
`reconcile_validity`. View `iocs` (`SELECT *` dibekukan saat dibuat) tidak ikut membawa kolom baru,
jadi INSERT lewat view memakai default tabel dasar.

Revision ID: c4f1a8d27b93
Revises: a9e4c7b1d3f6
Create Date: 2026-10-29 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from cti_core.indicator.stix_id import indicator_uuid
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4f1a8d27b93"
down_revision: str | Sequence[str] | None = "a9e4c7b1d3f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BATCH = 1000


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("token_prefix", sa.String(12), nullable=False),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("max_tlp", sa.String(12), server_default="clear", nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.String(200), nullable=True),
        sa.CheckConstraint(
            "max_tlp IN ('clear', 'green', 'amber', 'amber+strict', 'red')",
            name=op.f("ck_api_tokens_max_tlp"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )

    op.add_column(
        "indicators",
        sa.Column(
            "feed_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE indicators SET feed_changed_at ="
        " greatest(created_at, coalesce(revoked_at, created_at))"
    )
    op.add_column("indicators", sa.Column("stix_id", postgresql.UUID(as_uuid=True), nullable=True))
    conn = op.get_bind()
    last_id = 0
    while True:
        rows = conn.execute(
            sa.text("SELECT id, type, value FROM indicators WHERE id > :l ORDER BY id LIMIT :n"),
            {"l": last_id, "n": _BATCH},
        ).all()
        if not rows:
            break
        conn.execute(
            sa.text("UPDATE indicators SET stix_id = :s WHERE id = :i"),
            [{"s": indicator_uuid(r.type, r.value), "i": r.id} for r in rows],
        )
        last_id = rows[-1].id
    op.create_unique_constraint(op.f("uq_indicators_stix_id"), "indicators", ["stix_id"])
    op.create_index("ix_indicators_feed_changed_at_id", "indicators", ["feed_changed_at", "id"])

    # Trigger dibuat SESUDAH backfill supaya UPDATE di atas tidak menggeser jam.
    op.execute(
        """
        CREATE FUNCTION indicators_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.type IS DISTINCT FROM OLD.type
               OR NEW.value IS DISTINCT FROM OLD.value
               OR NEW.valid_from IS DISTINCT FROM OLD.valid_from
               OR NEW.valid_until IS DISTINCT FROM OLD.valid_until
               OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
               OR NEW.auto_suppressed IS DISTINCT FROM OLD.auto_suppressed
               OR NEW.tlp IS DISTINCT FROM OLD.tlp
               OR NEW.pap IS DISTINCT FROM OLD.pap
               OR NEW.seen_count IS DISTINCT FROM OLD.seen_count
               OR NEW.last_seen_at IS DISTINCT FROM OLD.last_seen_at
            THEN
                NEW.feed_changed_at = now();
            END IF;
            RETURN NEW;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_indicators_feed_bump BEFORE UPDATE ON indicators"
        " FOR EACH ROW EXECUTE FUNCTION indicators_feed_bump()"
    )
    op.execute(
        """
        CREATE FUNCTION indicator_tags_feed_bump() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE indicators SET feed_changed_at = now()
            WHERE id = COALESCE(NEW.indicator_id, OLD.indicator_id);
            RETURN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_indicator_tags_feed_bump AFTER INSERT OR DELETE ON indicator_tags"
        " FOR EACH ROW EXECUTE FUNCTION indicator_tags_feed_bump()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_indicator_tags_feed_bump ON indicator_tags")
    op.execute("DROP FUNCTION indicator_tags_feed_bump()")
    op.execute("DROP TRIGGER trg_indicators_feed_bump ON indicators")
    op.execute("DROP FUNCTION indicators_feed_bump()")
    op.drop_index("ix_indicators_feed_changed_at_id", table_name="indicators")
    op.drop_constraint(op.f("uq_indicators_stix_id"), "indicators", type_="unique")
    op.drop_column("indicators", "stix_id")
    op.drop_column("indicators", "feed_changed_at")
    op.drop_table("api_tokens")
