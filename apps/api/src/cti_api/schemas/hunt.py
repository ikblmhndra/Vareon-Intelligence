"""Skema hunting pack (P7e spec 5.3): cermin dataclass `services.hunt_builder.HuntPack`. JSON
tidak pernah membawa YAML Sigma (hanya zip)."""

import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Attrs(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HuntAnchorOut(_Attrs):
    type: Literal["story", "entity"]
    id: int
    title: str
    entity_type: str | None


class HuntTechniqueOut(_Attrs):
    attack_id: str
    name: str
    tier: Literal["primary", "inferred", "llm"]
    sigma_count: int


class HuntSplOut(_Attrs):
    dataset: str
    chunk: int
    value_count: int
    query: str


class HuntSigmaOut(_Attrs):
    id: str
    title: str
    level: str
    status: str
    author: str
    ruleset: str
    link: str
    techniques: list[str]
    logsource: dict[str, str]
    match: Literal["exact", "sub", "parent"]
    via_technique: str


class HuntIocOut(_Attrs):
    type: str
    value: str
    valid_until: datetime.datetime | None
    tlp: str


class HuntPackOut(_Attrs):
    anchor: HuntAnchorOut
    generated_at: datetime.datetime
    sigma_release: str | None
    techniques: list[HuntTechniqueOut]
    spl: list[HuntSplOut]
    sigma: list[HuntSigmaOut]
    iocs: dict[str, list[HuntIocOut]]
    counts: dict[str, int]
    truncated: bool
    include: list[str]
