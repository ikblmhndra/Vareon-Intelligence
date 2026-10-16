"""`RuntimeSecretRepo` (sync) -- baca override key third-party buat `runtime_secrets.overlay`.

Sengaja HANYA baca di irisan ini: overlay jalan di proses sync (Celery/CLI) dan di API lewat
`sync_session()`. Tulis (set/hapus/catat hasil test) datang bersama endpoint adminnya (PR 2) dalam
versi async, jadi tidak ada metode tulis yang menganggur di sini.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from cti_core.db.models.runtime_secret import RuntimeSecret


class RuntimeSecretRepo:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_platform(self) -> list[RuntimeSecret]:
        """Baris scope platform (`client_id IS NULL`), urut provider biar hasilnya deterministik."""
        stmt = (
            select(RuntimeSecret)
            .where(RuntimeSecret.client_id.is_(None))
            .order_by(RuntimeSecret.provider)
        )
        return list(self.session.scalars(stmt).all())
