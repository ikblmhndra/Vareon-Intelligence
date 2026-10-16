"""`.env.example` dan `.env.prod.template` tidak boleh membawa master key (ROADMAP #23), dan
allowlist host LLM-nya harus terdokumentasi dan kosong.

`SECRETS_ENCRYPTION_KEYS` membuka SEMUA secret yang disimpan terenkripsi di DB; kuncinya sengaja
disimpan terpisah dari backup DB. Kalau satu nilai nyasar ke template yang ke-commit, pemisahan itu
hilang. Jadi key-nya harus ADA (terdokumentasi, salah ketik ketahuan) dan KOSONG di kedua file;
kosong juga berarti fitur mati dan deploy tidak pecah.

`SECRETS_LLM_URL_ALLOWED_HOSTS` juga harus ADA dan KOSONG: kosong berarti halaman admin tidak bisa
mengisi `llm.url` kustom di luar dev (default aman), dan host yang disetujui adalah keputusan
deploy per environment, bukan nilai bawaan template yang ikut ke setiap host baru.

Parser baris env sama gayanya dengan `tests/unit/test_env_prod_template.py`.
"""

from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
KEY = "SECRETS_ENCRYPTION_KEYS"
ALLOWLIST_KEY = "SECRETS_LLM_URL_ALLOWED_HOSTS"


def parse_env_lines(path: pathlib.Path) -> dict[str, str]:
    """Baris `KEY=value` yang AKTIF (bukan `#`-comment); komentar di ujung baris dibuang."""
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if " #" in value:
            value = value.split(" #", 1)[0]
        out[name.strip()] = value.strip()
    return out


@pytest.mark.parametrize("name", [".env.example", ".env.prod.template"])
def test_the_master_key_is_declared_and_left_empty(name: str) -> None:
    values = parse_env_lines(ROOT / name)

    assert KEY in values, f"{KEY} tidak ada di {name}"
    assert values[KEY] == "", f"{KEY} di {name} harus kosong (jangan commit master key)"


@pytest.mark.parametrize("name", [".env.example", ".env.prod.template"])
def test_the_llm_url_allowlist_is_declared_and_left_empty(name: str) -> None:
    values = parse_env_lines(ROOT / name)

    assert ALLOWLIST_KEY in values, f"{ALLOWLIST_KEY} tidak ada di {name}"
    assert values[ALLOWLIST_KEY] == "", f"{ALLOWLIST_KEY} di {name} harus kosong"
