"""Response model `GET /api/spikes`. Sebelumnya `dict[str, object]` (schema.d.ts tidak
bertipe); nama field dan tipenya sengaja sama persis dengan dict dari `spike.get_spikes`
(`entity_id` nullable), jadi bentuk JSON lama tidak berubah -- hanya `daily` yang baru."""

from __future__ import annotations

from pydantic import BaseModel


class EntitySpike(BaseModel):
    entity: str
    date: str
    count: int
    baseline_mean: float
    z_score: float
    severity: str
    entity_id: int | None = None


class OverallSpike(BaseModel):
    date: str
    count: int
    baseline_mean: float
    z_score: float
    severity: str


class SpikeDaily(BaseModel):
    """Seri harian sejajar `dates`, zero-filled; hanya entitas yang masuk daftar spike."""

    dates: list[str]
    threat_actors: dict[str, list[int]]
    countries: dict[str, list[int]]
    industries: dict[str, list[int]]
    overall: list[int]


class SpikeParameters(BaseModel):
    lookback_days: int
    z_threshold: float
    recent_window: str


class SpikesResponse(BaseModel):
    threat_actors: list[EntitySpike]
    countries: list[EntitySpike]
    industries: list[EntitySpike]
    overall: list[OverallSpike]
    generated_at: str
    parameters: SpikeParameters
    daily: SpikeDaily
