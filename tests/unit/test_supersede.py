"""Cutover mirror CVE (`cti_scraper.supersede`): `new_cve` ditangguhkan HANYA saat mirror dan
promosi `live` menyala (dan flag cadangan mati); beat, health, dan daftar API memakai satu aturan
yang sama; `Runner` menolak menjalankannya. Rollback = flag, tanpa migrasi."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from cti_core.config import CveMirrorSettings
from cti_scraper import supersede
from cti_scraper.base import ScraperMeta
from cti_scraper.health import compute_health

META = ScraperMeta(id="new_cve", source="X", schedule="0 * * * *")
OTHER = ScraperMeta(id="other", source="Y", schedule="0 * * * *")


def use(monkeypatch: pytest.MonkeyPatch, **cfg: Any) -> None:
    settings = SimpleNamespace(cve_mirror=CveMirrorSettings(**cfg))
    monkeypatch.setattr(supersede, "get_settings", lambda: settings)


@pytest.mark.parametrize(
    ("cfg", "expected"),
    [
        ({}, False),  # default: semua mati
        ({"enabled": True, "promote": "off"}, False),
        ({"enabled": True, "promote": "shadow"}, False),
        ({"enabled": False, "promote": "live"}, False),  # live tanpa mirror menyala = tak berlaku
        ({"enabled": True, "promote": "live"}, True),
        ({"enabled": True, "promote": "live", "keep_legacy_new_cve": True}, False),
    ],
)
def test_new_cve_is_superseded_only_when_the_mirror_is_live(
    monkeypatch: pytest.MonkeyPatch, cfg: dict[str, Any], expected: bool
) -> None:
    use(monkeypatch, **cfg)
    assert supersede.superseded_by_mirror("new_cve") is expected


def test_other_scrapers_are_never_superseded(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, enabled=True, promote="live")
    assert supersede.superseded_by_mirror("github_poc_monitor") is False
    assert supersede.effective_enabled(OTHER, None) is True


def test_effective_enabled_keeps_control_plane_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    off = SimpleNamespace(enabled=False)
    on = SimpleNamespace(enabled=True)
    use(monkeypatch)
    assert supersede.effective_enabled(META, None) is True
    assert supersede.effective_enabled(META, on) is True  # type: ignore[arg-type]
    assert supersede.effective_enabled(META, off) is False  # type: ignore[arg-type]
    use(monkeypatch, enabled=True, promote="live")
    assert supersede.effective_enabled(META, on) is False  # type: ignore[arg-type]
    assert supersede.effective_enabled(META, None) is False
    use(monkeypatch, enabled=True, promote="live", keep_legacy_new_cve=True)
    assert supersede.effective_enabled(META, on) is True  # type: ignore[arg-type]
    assert supersede.effective_enabled(META, off) is False  # type: ignore[arg-type]


def test_health_reports_disabled_instead_of_stale_when_superseded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use(monkeypatch)
    assert compute_health(META, None, []) == "stale"  # belum pernah jalan
    use(monkeypatch, enabled=True, promote="live")
    assert compute_health(META, None, []) == "disabled"  # tidak mengotori digest Telegram
    assert compute_health(OTHER, None, []) == "stale"


def test_beat_does_not_schedule_a_superseded_new_cve(monkeypatch: pytest.MonkeyPatch) -> None:
    from cti_core.config import get_settings

    for k, v in {
        "DATABASE__URL": "postgresql+asyncpg://x:x@127.0.0.1:1/x",
        "DATABASE__SYNC_URL": "postgresql+psycopg://x:x@127.0.0.1:1/x",
        "AUTH__JWT_SECRET": "t",
        "AUTH__SESSION_SECRET_KEY": "t",
    }.items():
        monkeypatch.setenv(k, v)
    from cti_worker import beat

    monkeypatch.setattr(beat, "_scraper_configs", lambda: {})
    get_settings.cache_clear()
    try:
        assert "scrape-new_cve" in beat.build_beat_schedule()  # default: tetap dijadwalkan
        monkeypatch.setenv("CVE_MIRROR__ENABLED", "true")
        monkeypatch.setenv("CVE_MIRROR__PROMOTE", "live")
        get_settings.cache_clear()
        live = beat.build_beat_schedule()
        assert "scrape-new_cve" not in live
        assert "scrape-github_poc_monitor" in live and "cve-mirror-sync" in live
        monkeypatch.setenv("CVE_MIRROR__KEEP_LEGACY_NEW_CVE", "true")
        get_settings.cache_clear()
        assert "scrape-new_cve" in beat.build_beat_schedule()
        monkeypatch.setenv("CVE_MIRROR__KEEP_LEGACY_NEW_CVE", "false")
        monkeypatch.setenv("CVE_MIRROR__PROMOTE", "shadow")  # rollback = flag
        get_settings.cache_clear()
        assert "scrape-new_cve" in beat.build_beat_schedule()
    finally:
        get_settings.cache_clear()
