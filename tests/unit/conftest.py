"""Fixture bersama test unit."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cti_enrich.stages import tier1


@pytest.fixture(autouse=True)
def _reset_tier1_caches() -> Iterator[None]:
    """Cache kamus/katalog Tier 1 hidup 1 jam per proses. Test pipeline yang memanggil
    `run_tier1` dengan sesi MagicMock mengisinya dengan kamus kosong berstatus "loaded";
    tanpa reset, test berikutnya mewarisi kamus itu."""
    tier1.reset_caches()
    yield
    tier1.reset_caches()
