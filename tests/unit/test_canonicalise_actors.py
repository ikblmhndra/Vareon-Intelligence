"""`cti_enrich.canonicalise_actors` digantikan migrasi `entity_model` (P7c, Ruling 22): tetap bisa
dijalankan karena runbook prod menyebutnya, tapi tidak menulis apa pun dan keluar 0."""

from __future__ import annotations

import pytest
from cti_enrich import canonicalise_actors


@pytest.mark.parametrize("argv", [[], ["--apply"]])
def test_superseded_no_op(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert canonicalise_actors.main(argv) == 0
    assert "digantikan" in capsys.readouterr().out
