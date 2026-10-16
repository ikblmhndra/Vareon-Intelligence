"""Tabel `runtime_secrets` + repo + overlay di Postgres beneran (ROADMAP #23).

Yang dikunci:
- skema: TIDAK ada kolom nilai plaintext (semua field override, secret maupun non-secret, ada di
  `secrets_enc`) dan `secrets_enc` NOT NULL, jadi tidak ada baris "setengah plaintext";
- keunikan lewat DUA indeks parsial: satu baris platform (`client_id IS NULL`) per provider, dan
  satu baris per (client, provider). Unique constraint biasa tidak cukup karena NULL dianggap beda;
- `list_platform()` hanya mengembalikan baris platform;
- ujung-ke-ujung: baris terenkripsi di Postgres -> `effective_settings()` memberi nilai override
  (termasuk perjalanan bytea yang tidak terlihat di tes unit), dan token yang dipindah antar baris
  lewat SQL ditolak (pengikatan provider/client ada di dalam payload);
- TIDAK ADA nilai override plaintext di kolom mana pun (inti keamanan fitur ini: backup DB saja
  tidak membuka apa-apa).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cti_core.db.engine import sync_session
from cti_core.db.models.auth import Client
from cti_core.db.models.runtime_secret import RuntimeSecret
from cti_core.db.repositories.runtime_secret import RuntimeSecretRepo
from cti_core.runtime_secrets import overlay
from cti_core.runtime_secrets.crypto import decrypt_fields, encrypt_fields
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.unit.runtime_secrets_helpers import ENV_VALUES, KEYS, make_settings

DB_LLM = "sk-db-llm-bbbbbb"  # gitleaks:allow
DB_NVD = "nvd-db-bbbbbb"  # gitleaks:allow
DB_MODEL = "model-db-bbbbbb"

EXPECTED_COLUMNS = {
    "id",
    "provider",
    "client_id",
    "secrets_enc",
    "updated_by",
    "last_test_ok",
    "last_test_at",
    "created_at",
    "updated_at",
}


@pytest.fixture(autouse=True)
def _fresh_overlay() -> Iterator[None]:
    overlay.invalidate()
    yield
    overlay.invalidate()


def _client(session: Session, client_id: str) -> None:
    session.add(Client(client_id=client_id, name=client_id.title()))
    session.flush()


def _token(
    provider: str, fields: dict[str, str] | None = None, *, client_id: str | None = None
) -> bytes:
    return encrypt_fields(provider, fields or {"api_key": DB_NVD}, client_id=client_id, keys=KEYS)


def _add(
    session: Session, provider: str, *, client_id: str | None = None, **columns: Any
) -> RuntimeSecret:
    """Baris dengan token terenkripsi yang SAH (terikat ke provider dan client-nya)."""
    columns.setdefault("secrets_enc", _token(provider, client_id=client_id))
    row = RuntimeSecret(provider=provider, client_id=client_id, updated_by="tester", **columns)
    session.add(row)
    session.flush()
    return row


def _count(session: Session, provider: str) -> int:
    stmt = select(func.count()).select_from(RuntimeSecret).where(RuntimeSecret.provider == provider)
    return session.scalar(stmt) or 0


def _use_database_rows(monkeypatch: pytest.MonkeyPatch, session: Session) -> None:
    """Overlay membaca lewat repo di sesi tes (yang belum commit), bukan `sync_session()` baru."""
    monkeypatch.setattr(overlay, "get_settings", lambda: make_settings(keys=KEYS))
    monkeypatch.setattr(overlay, "_fetch_rows", lambda: RuntimeSecretRepo(session).list_platform())


# --- skema ------------------------------------------------------------------------------------


def test_the_table_has_no_plaintext_value_column(db_session: Session) -> None:
    columns = set(
        db_session.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'runtime_secrets'"
            )
        )
    )

    assert columns == EXPECTED_COLUMNS


def test_secrets_enc_is_not_null_at_the_database_level(db_session: Session) -> None:
    nullable = db_session.scalar(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'runtime_secrets' "
            "AND column_name = 'secrets_enc'"
        )
    )

    assert nullable == "NO"


def test_an_orm_insert_without_secrets_enc_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(RuntimeSecret(provider="nvd", updated_by="tester"))
        db_session.flush()

    assert _count(db_session, "nvd") == 0


def test_a_raw_sql_insert_without_secrets_enc_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(
            text("INSERT INTO runtime_secrets (provider, updated_by) VALUES ('nvd', 'tester')")
        )

    assert _count(db_session, "nvd") == 0


def test_a_new_row_starts_without_a_probe_result_and_with_timestamps(db_session: Session) -> None:
    row = _add(db_session, "nvd")

    db_session.refresh(row)

    assert row.last_test_ok is None
    assert row.last_test_at is None
    assert row.created_at is not None
    assert row.updated_at is not None


def test_the_ciphertext_survives_the_bytea_round_trip_with_every_field(
    db_session: Session,
) -> None:
    fields = {"api_key": DB_LLM, "model": DB_MODEL, "url": "https://gw.db.example.test/v1"}
    row = _add(db_session, "llm", secrets_enc=_token("llm", fields))

    db_session.expire(row)

    assert decrypt_fields("llm", row.secrets_enc, keys=KEYS) == fields


# --- keunikan (dua indeks parsial) ------------------------------------------------------------


def test_two_platform_rows_for_the_same_provider_are_rejected(db_session: Session) -> None:
    _add(db_session, "nvd")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        _add(db_session, "nvd")

    assert _count(db_session, "nvd") == 1


def test_platform_rows_for_different_providers_coexist(db_session: Session) -> None:
    _add(db_session, "nvd")
    _add(db_session, "llm")

    assert _count(db_session, "nvd") == _count(db_session, "llm") == 1


def test_the_same_provider_is_allowed_for_different_clients(db_session: Session) -> None:
    _client(db_session, "rs-acme")
    _client(db_session, "rs-globex")

    _add(db_session, "nvd", client_id="rs-acme")
    _add(db_session, "nvd", client_id="rs-globex")

    assert _count(db_session, "nvd") == 2


def test_the_same_provider_is_allowed_for_the_platform_and_for_a_client(
    db_session: Session,
) -> None:
    _client(db_session, "rs-acme")

    _add(db_session, "nvd")
    _add(db_session, "nvd", client_id="rs-acme")

    assert _count(db_session, "nvd") == 2


def test_two_rows_for_the_same_client_and_provider_are_rejected(db_session: Session) -> None:
    _client(db_session, "rs-acme")
    _add(db_session, "nvd", client_id="rs-acme")

    with pytest.raises(IntegrityError), db_session.begin_nested():
        _add(db_session, "nvd", client_id="rs-acme")

    assert _count(db_session, "nvd") == 1


def test_a_row_for_an_unknown_client_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        _add(db_session, "nvd", client_id="rs-no-such-client")


# --- repo -------------------------------------------------------------------------------------


def test_list_platform_returns_only_rows_without_a_client(db_session: Session) -> None:
    _client(db_session, "rs-acme")
    _add(db_session, "nvd")
    _add(db_session, "llm")
    _add(db_session, "nvd", client_id="rs-acme")
    _add(db_session, "github", client_id="rs-acme")

    rows = RuntimeSecretRepo(db_session).list_platform()

    assert {row.provider for row in rows} == {"nvd", "llm"}
    assert all(row.client_id is None for row in rows)
    assert len(rows) == 2


def test_list_platform_is_empty_on_an_empty_table(db_session: Session) -> None:
    assert RuntimeSecretRepo(db_session).list_platform() == []


# --- ujung-ke-ujung: Postgres -> overlay ------------------------------------------------------


def test_effective_settings_returns_the_override_stored_in_postgres(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = make_settings(keys=KEYS)
    _add(db_session, "llm", secrets_enc=_token("llm", {"api_key": DB_LLM, "model": DB_MODEL}))
    _use_database_rows(monkeypatch, db_session)

    effective = overlay.effective_settings()

    assert effective.llm.api_key == DB_LLM
    assert effective.llm.model == DB_MODEL  # field non-secret juga dari payload terenkripsi
    assert effective.nvd.api_key == ENV_VALUES[("nvd", "api_key")]  # provider tanpa baris = env
    assert base.llm.api_key == ENV_VALUES[("llm", "api_key")]


def test_a_client_row_in_postgres_does_not_reach_the_effective_settings(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client(db_session, "rs-acme")
    _add(db_session, "nvd", client_id="rs-acme")
    _use_database_rows(monkeypatch, db_session)

    snapshot = overlay.load_snapshot()

    assert snapshot.overrides == {}
    assert snapshot.errors == {}


def test_a_token_moved_to_another_provider_row_with_sql_is_rejected(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pengikatan ada di dalam payload terotentikasi: orang yang bisa UPDATE tabel (tapi tidak
    punya master key) tidak bisa memakai token `otx` sebagai key `nvd`."""
    _add(db_session, "nvd", secrets_enc=_token("otx", {"api_key": DB_NVD}))
    _use_database_rows(monkeypatch, db_session)

    snapshot = overlay.load_snapshot()

    assert snapshot.overrides == {}
    assert snapshot.errors == {"nvd": "decrypt_failed"}


def test_the_real_fetch_rows_returns_committed_rows_that_stay_readable_after_the_session_closes(
    _migrated_schema: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Seam `_fetch_rows` yang SEBENARNYA (`sync_session()` sendiri, bukan `db_session`): baris
    dibaca lalu sesinya ditutup, jadi atribut harus tetap terbaca (bukan DetachedInstanceError).
    Satu-satunya tes di file ini yang commit; barisnya ditandai `updated_by`, dihapus di akhir."""
    tag = "rs-fetch-rows-test"
    token = _token("nvd", {"api_key": DB_NVD})
    with sync_session() as session:
        session.add(RuntimeSecret(provider="nvd", secrets_enc=token, updated_by=tag))
    monkeypatch.setattr(overlay, "get_settings", lambda: make_settings(keys=KEYS))
    try:
        platform_rows = [r for r in overlay._fetch_rows() if r.client_id is None]
        snapshot = overlay.load_snapshot()
    finally:
        with sync_session() as session:
            session.execute(delete(RuntimeSecret).where(RuntimeSecret.updated_by == tag))

    assert [(r.provider, r.updated_by) for r in platform_rows] == [("nvd", tag)]
    assert snapshot.errors == {}
    assert snapshot.overrides == {"nvd": {"api_key": DB_NVD}}


# --- tidak ada plaintext di DB ----------------------------------------------------------------


def test_no_override_value_is_stored_in_plaintext_in_any_column(db_session: Session) -> None:
    secret = DB_LLM
    _add(db_session, "llm", secrets_enc=_token("llm", {"api_key": secret, "model": DB_MODEL}))

    raw = db_session.execute(
        text("SELECT secrets_enc FROM runtime_secrets WHERE provider = 'llm'")
    ).scalar_one()
    whole_row = db_session.execute(
        text("SELECT t::text FROM runtime_secrets t WHERE provider = 'llm'")
    ).scalar_one()

    assert secret.encode() not in bytes(raw)
    assert DB_MODEL.encode() not in bytes(raw)
    # `t::text` menampilkan bytea sebagai hex, jadi cek bentuk hex-nya juga.
    for value in (secret, DB_MODEL):
        assert value not in whole_row
        assert value.encode().hex() not in whole_row
    # Kontrol positif: query benar-benar melihat barisnya (kolom plaintext memang terbaca).
    assert "llm" in whole_row
    assert "tester" in whole_row
