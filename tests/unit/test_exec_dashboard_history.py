"""Gating bulan "cukup data" di risk score & velocity Exec (`exec_dashboard`). Di prod data baru
±4 minggu: bulan hampir kosong bikin komponen trend/spike membaca lonjakan ingestion sebagai
lonjakan ancaman."""

from __future__ import annotations

from typing import Any

from cti_api.services import exec_dashboard as svc


def _trend() -> list[dict[str, Any]]:
    # Agu hampir kosong, Sep separuh, Okt (bulan terakhir) deras -- bentuk ramp ingestion.
    return [
        {"sector": "A", "data": [0, 50, 200]},
        {"sector": "B", "data": [0, 20, 100]},
    ]


def _scores(usable: list[bool] | None = None) -> dict[str, int]:
    rows = svc._compute_sector_risk_scores(_trend(), usable)
    return {r["sector"]: r["risk_score"] for r in rows}


def test_risk_score_without_gating_inflates_ramp_into_spike() -> None:
    # perilaku lama: volume 50 + spike (z besar) -> jauh di atas volume saja
    assert _scores()["A"] > 50


def test_risk_score_is_volume_only_until_history_is_usable() -> None:
    usable = [False, True, True]  # Agu terlalu sedikit -> cuma 1 bulan riwayat
    assert _scores(usable) == {"A": 50, "B": 25}  # (last / max_last) * 50, tanpa trend/spike


def test_ta_velocity_skips_actors_without_usable_history() -> None:
    raw = [("Apt41", "2026-09", 3), ("Apt41", "2026-10", 9)]
    months = ["2026-08", "2026-09", "2026-10"]
    assert svc._compute_ta_velocity(raw, months, [False, False, True]) == []
    rows = svc._compute_ta_velocity(raw, months, [False, True, True])
    assert [(r["actor"], r["avg_prev"], r["velocity_pct"]) for r in rows] == [("Apt41", 3, 200)]
