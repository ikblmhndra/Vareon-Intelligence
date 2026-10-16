"""Opsi per-scraper (`ScraperMeta.options`) yang dideklarasikan scraper harus konsisten --
kalau tidak, dropdown di control plane menawarkan pilihan yang bikin run gagal.

Jalan otomatis buat SEMUA scraper terdaftar, jadi opsi baru yang salah tulis (default yang
bukan salah satu pilihan, nama kredensial yang tidak dikenal) gagal di CI, bukan di jadwal
jam 3 pagi.
"""

from __future__ import annotations

import pytest
from cti_scraper import registry
from cti_scraper.credentials import _CREDENTIAL_RESOLVERS

WITH_OPTIONS = sorted(sid for sid, cls in registry.discover().items() if cls.meta.options)


def test_the_twitter_scrapers_are_the_ones_with_a_selectable_source() -> None:
    assert set(WITH_OPTIONS) == {"tweet_alerts_1h", "tweet_alerts_30m", "trending_cve", "monitor_x"}


@pytest.mark.parametrize("scraper_id", WITH_OPTIONS)
class TestDeclaredOptionsAreConsistent:
    def test_keys_and_choice_values_are_unique(self, scraper_id: str) -> None:
        options = registry.get(scraper_id).meta.options

        assert len({o.key for o in options}) == len(options)
        for o in options:
            assert len({c.value for c in o.choices}) == len(o.choices), o.key
            assert len(o.choices) >= 2, f"opsi '{o.key}' dengan <2 pilihan tak ada gunanya"

    def test_default_is_one_of_the_choices(self, scraper_id: str) -> None:
        for o in registry.get(scraper_id).meta.options:
            assert o.default in {c.value for c in o.choices}, f"{o.key}: default bukan pilihan"

    def test_option_credentials_are_known_names(self, scraper_id: str) -> None:
        """Nama kredensial typo = `ConfigError` di run pertama yang memilihnya."""
        for o in registry.get(scraper_id).meta.options:
            for c in o.choices:
                assert c.credential is None or c.credential in _CREDENTIAL_RESOLVERS, (
                    f"{o.key}={c.value}: kredensial '{c.credential}' tidak dikenal"
                )

    def test_meta_credential_is_the_default_choices_credential(self, scraper_id: str) -> None:
        """`ScraperMeta.credential` menentukan QUEUE (`queue_for`) dan kredensial dry-run/record
        tanpa opsi -- harus sama dengan pilihan DEFAULT, kalau tidak scraper yang tidak pernah
        disentuh admin jalan dengan kredensial lain dari yang dijanjikan dropdown."""
        meta = registry.get(scraper_id).meta
        credentials = [c for o in meta.options for c in o.choices if c.value == o.default]

        assert [c.credential for c in credentials if c.credential] == [meta.credential]

    def test_at_most_one_option_decides_the_credential(self, scraper_id: str) -> None:
        """Dua opsi yang sama-sama menentukan kredensial = urutan deklarasi jadi pemenang
        diam-diam. Belum ada kebutuhan; kalau muncul, putuskan aturannya secara eksplisit."""
        meta = registry.get(scraper_id).meta
        deciding = [o for o in meta.options if any(c.credential for c in o.choices)]

        assert len(deciding) <= 1
