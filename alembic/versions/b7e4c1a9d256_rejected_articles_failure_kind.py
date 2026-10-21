"""rejected_articles.failure_kind: pisahkan artikel GAGAL di-enrich dari yang DITOLAK klasifikasi

Penanda satu-satunya adalah awalan teks `[enrichment_failed]` di `reason` (ROADMAP #24): tidak bisa
difilter, dihitung, atau di-replay dengan rapi. Kolom nullable: NULL = ditolak klasifikasi LLM.
Baris lama diisi terbaik-usaha dari nama kelas error di `reason`: kelas yang sama dengan
`_TRANSIENT_ERRORS` di task `enrich.article` = `transient`, `JSONDecodeError` = `json`, sisanya
(401, kuota, 400, bug) = `permanent`.

Revision ID: b7e4c1a9d256
Revises: a3f81c2d9b47
Create Date: 2026-10-21 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e4c1a9d256"
down_revision: str | None = "a3f81c2d9b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRANSIENT_NAMES = (
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "RateLimitError",
    "EmptyLLMResponse",
    "OperationalError",
    "InterfaceError",
    "TransportError",
    "TimeoutException",
    "ConnectTimeout",
    "ReadTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "NetworkError",
    "ConnectError",
    "ReadError",
    "WriteError",
    "CloseError",
    "ProtocolError",
    "LocalProtocolError",
    "RemoteProtocolError",
    "ProxyError",
    "UnsupportedProtocol",
)


def upgrade() -> None:
    op.add_column(
        "rejected_articles", sa.Column("failure_kind", sa.String(length=30), nullable=True)
    )
    names = ", ".join(f"'{n}'" for n in _TRANSIENT_NAMES)
    # `[enrichment_failed] ` = 20 karakter; nama kelas berhenti di ':' pertama.
    op.execute(
        f"""
        UPDATE rejected_articles SET failure_kind = CASE
            WHEN btrim(split_part(substr(reason, 21), ':', 1)) IN ({names}) THEN 'transient'
            WHEN btrim(split_part(substr(reason, 21), ':', 1)) = 'JSONDecodeError' THEN 'json'
            ELSE 'permanent'
        END
        WHERE starts_with(reason, '[enrichment_failed]')
        """
    )


def downgrade() -> None:
    op.drop_column("rejected_articles", "failure_kind")
