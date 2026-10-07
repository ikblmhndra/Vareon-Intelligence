"""techstack_entries.aliases: nama lain produk, dibaca satu pencocok bersama (ROADMAP #19 fase 1)

Nama techstack teks bebas dicocokkan oleh enam tempat dengan aturan berbeda (lihat
`docs/CVE_TECH_MATCHING.md` 2.4). Kolom ini menampung nama lain yang ditulis CNA/media untuk produk
yang sama ("PAN-OS" untuk "palo alto", "RouterOS" untuk "mikrotik"), dibaca `cti_core.tech_match`.

Seed: daftar `SELECT DISTINCT name FROM techstack_entries` produksi (2026-10-07, 34 nama) ditinjau
satu per satu; hanya nama yang memang punya nama lain yang tak terjangkau aturan kata utuh yang
diisi. Sengaja KONSERVATIF -- alias yang terlalu umum membawa balik masalah yang sedang diperbaiki
(CVE produk lain yang kebetulan cocok). Dicocokkan lewat `lower(name)`; nama yang tak ada di tabel
dilewati diam-diam, jadi aman dijalankan di database yang daftarnya beda. Alias dinormalisasi saat
dibaca (huruf kecil, non-alfanumerik jadi spasi), jadi penulisan di sini bebas.

Kolom NOT NULL ditambah dengan `server_default` lalu default-nya dilepas -- pola yang sama dengan
`d7b1f3a9c2e5`: nilai awal dipegang model (`default=list`), bukan skema.

Revision ID: a9d4e6f81b3c
Revises: e8c2a4b6d1f3
Create Date: 2026-10-07 16:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9d4e6f81b3c"
down_revision: str | None = "e8c2a4b6d1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Salinan beku, BUKAN impor dari kode aplikasi: migrasi harus tetap memberi hasil yang sama walau
# aplikasi berubah. Kunci = lower(name) di techstack_entries.
_SEED_ALIASES: dict[str, list[str]] = {
    "burp suite": ["burpsuite"],
    "fortigate": ["fortios"],  # FortiOS = sistem operasi FortiGate; CNA menulis produknya "FortiOS"
    "harmony sase": ["perimeter 81"],  # Check Point Harmony SASE = Perimeter 81 yang di-rebrand
    "microsoft 365": ["office 365", "m365"],
    "mikrotik": ["routeros"],
    "new relic": ["newrelic"],  # nama paket/CPE tanpa spasi
    "palo alto": ["paloaltonetworks", "pan-os", "panos", "globalprotect"],
    "perimeter81": ["perimeter 81"],  # nama tech tanpa spasi, vendor/CNA menulisnya dengan spasi
}


def upgrade() -> None:
    op.add_column(
        "techstack_entries",
        sa.Column(
            "aliases",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column("techstack_entries", "aliases", server_default=None)

    bind = op.get_bind()
    for name, aliases in _SEED_ALIASES.items():
        bind.execute(
            sa.text(
                "UPDATE techstack_entries SET aliases = CAST(:aliases AS jsonb) "
                "WHERE lower(name) = :name"
            ),
            {"aliases": json.dumps(aliases), "name": name},
        )


def downgrade() -> None:
    op.drop_column("techstack_entries", "aliases")
