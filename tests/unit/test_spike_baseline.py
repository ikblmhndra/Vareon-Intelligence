"""Baseline deteksi spike menghitung hari tanpa artikel sebagai 0 (0.8.15).

Dulu `baseline_mean`/std dihitung dari hari yang ADA artikelnya saja, sehingga garis baseline di
kartu Early Warning lebih tinggi daripada batang deret `daily` (yang mengisi hari kosong dengan 0)
dan z-score entitas yang jarang muncul jadi lebih kecil dari seharusnya."""

from __future__ import annotations

import datetime
import statistics

from cti_api.services.spike import _detect_entity_spikes, _detect_overall_spikes

D0 = datetime.date(2026, 10, 1)


def _d(n: int) -> datetime.date:
    return D0 + datetime.timedelta(days=n)


def test_entity_baseline_counts_empty_days_as_zero() -> None:
    # Baseline 10 hari (d0..d9): 2 artikel tiap dua hari, 0 di sela-selanya; spike 6 di d10.
    raw = [(_d(n), "LockBit", 2) for n in (0, 2, 4, 6, 8)] + [(_d(10), "LockBit", 6)]

    spikes = _detect_entity_spikes(raw, _d(10), 2.0, baseline_start=D0)

    baseline = [2, 0] * 5
    expected_z = round((6 - statistics.mean(baseline)) / statistics.stdev(baseline), 2)
    assert len(spikes) == 1
    assert spikes[0]["baseline_mean"] == 1.0
    assert spikes[0]["z_score"] == expected_z


def test_entity_needs_five_baseline_days_with_articles() -> None:
    # Empat hari aktif saja: walau baseline terisi 10 hari (nol), entitas tetap dilewati.
    raw = [(_d(n), "Qilin", 3) for n in (0, 2, 4, 6)] + [(_d(10), "Qilin", 30)]

    assert _detect_entity_spikes(raw, _d(10), 2.0, baseline_start=D0) == []


def test_overall_baseline_counts_empty_days_as_zero() -> None:
    # Total harian d0..d9 dengan satu hari kosong (d5), lonjakan di d10.
    daily_total = [(_d(n), 10) for n in range(10) if n != 5] + [(_d(10), 40)]

    surges = _detect_overall_spikes(daily_total, _d(10), 2.0, baseline_start=D0)

    baseline = [10] * 5 + [0] + [10] * 4
    assert len(surges) == 1
    assert surges[0]["baseline_mean"] == round(statistics.mean(baseline), 2)
    assert surges[0]["z_score"] == round((40 - 9.0) / statistics.stdev(baseline), 2)
