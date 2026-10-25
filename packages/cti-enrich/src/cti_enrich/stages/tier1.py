"""Stage tier 1: ekstraksi deterministik (entitas, teknik ATT&CK, industri, insiden) tanpa LLM.

Kamus entitas dibangun dari ~5000 nama dan mahal, jadi di-cache per proses dengan TTL 1 jam
(pola `extract_iocs._get_allowlist`). Seluruh stage dibungkus try/except: tier 1 adalah
tambahan di atas LLM, kegagalannya TIDAK boleh menggagalkan enrichment artikel -- hasilnya
`Tier1Result.empty()` dan satu baris log `tier1_failed`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import structlog
from cti_core.attack_ttp import TechniqueCatalog
from cti_core.db.repositories.threat_reference import load_entity_sources
from cti_core.db.repositories.ttp_catalog import load_catalog
from sqlalchemy.orm import Session

from cti_enrich.tier1.dictionary import EntityDictionary, build_dictionary
from cti_enrich.tier1.entities import EntityHit, match_entities
from cti_enrich.tier1.incident import IncidentVerdict, incident_verdict
from cti_enrich.tier1.industry import INDUSTRY_TAXONOMY_VERSION, match_industries
from cti_enrich.tier1.keyword_map import KEYWORD_MAP_VERSION
from cti_enrich.tier1.ttps import SourcedTechnique, extract_techniques

log = structlog.get_logger()

_DICTIONARY_TTL = 3600.0

_RETRY_AFTER = 60.0  # gagal load tanpa kamus lama: coba lagi cepat, jangan tahan kamus kosong 1 jam

_dictionary_cache: EntityDictionary | None = None
_dictionary_cache_ts = 0.0
_dictionary_loaded = False  # True kalau cache berasal dari load yang sukses
_catalog_cache: TechniqueCatalog | None = None
_catalog_cache_ts = 0.0


def get_dictionary(session: Session) -> EntityDictionary:
    """Kamus dari cache proses. Gagal baca DB -> kamus terakhir yang baik, atau kosong."""
    global _dictionary_cache, _dictionary_cache_ts, _dictionary_loaded
    now = time.monotonic()
    ttl = _DICTIONARY_TTL if _dictionary_loaded else _RETRY_AFTER
    if _dictionary_cache is None or (now - _dictionary_cache_ts) > ttl:
        try:
            # SAVEPOINT: statement yang gagal tidak boleh membatalkan transaksi pemanggil.
            with session.begin_nested():
                _dictionary_cache = build_dictionary(*load_entity_sources(session))
            _dictionary_loaded = True
        except Exception as exc:
            log.warning("tier1_dictionary_load_failed", error=str(exc))
            if _dictionary_cache is None:
                _dictionary_cache = build_dictionary([], [], [], [])
                _dictionary_loaded = False
        _dictionary_cache_ts = now
    return _dictionary_cache


def _get_catalog(session: Session) -> TechniqueCatalog:
    """Katalog teknik ATT&CK, cache proses dengan TTL yang sama (tadinya 3 query per artikel)."""
    global _catalog_cache, _catalog_cache_ts
    now = time.monotonic()
    if _catalog_cache is None or (now - _catalog_cache_ts) > _DICTIONARY_TTL:
        _catalog_cache = load_catalog(session)
        _catalog_cache_ts = now
    return _catalog_cache


@dataclass
class Tier1Result:
    entities: list[EntityHit] = field(default_factory=list)
    techniques: list[SourcedTechnique] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    incident: IncidentVerdict | None = None
    versions: dict[str, str] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> Tier1Result:
        return cls()

    @property
    def actors(self) -> list[str]:
        return [e.canonical for e in self.entities if e.kind == "actor"]

    @property
    def malware(self) -> list[tuple[str, str]]:
        return [(e.canonical, e.kind) for e in self.entities if e.kind in ("malware", "tool")]

    def audit(self) -> dict[str, object]:
        """Jejak untuk `raw_enrichment["tier1"]`: versi, hit beserta offset, dan vonis insiden."""
        return {
            "versions": dict(self.versions),
            "hits": [
                {"canonical": e.canonical, "kind": e.kind, "matched": e.matched, "offset": e.offset}
                for e in self.entities
            ],
            "incident": (
                None
                if self.incident is None
                else {"confirmed": self.incident.confirmed, "reasons": list(self.incident.reasons)}
            ),
        }


def run_tier1(
    *,
    session: Session,
    title: str,
    text: str,
    victim_name: str | None,
    techniques: bool = True,
) -> Tier1Result:
    """Jalankan semua pencocok tier 1 untuk satu artikel.

    Entitas dicocokkan di `judul + isi`; teknik dan insiden di isi (judul kalau isi kosong);
    industri di judul + isi. `techniques=False` melewati ekstraksi teknik (artikel non-ATT&CK).
    Kegagalan apa pun -> `Tier1Result.empty()` + log `tier1_failed`, supaya enrichment LLM
    tetap jalan."""
    try:
        dictionary = get_dictionary(session)
        body = text or title
        entities = match_entities(f"{title}\n{text}", dictionary)
        found = extract_techniques(body, _get_catalog(session)) if techniques else []
        return Tier1Result(
            entities=entities,
            techniques=found,
            industries=match_industries(title, text),
            incident=incident_verdict(title, body, victim_name),
            versions={
                "dictionary": dictionary.version,
                "keyword_map": KEYWORD_MAP_VERSION,
                "industry": INDUSTRY_TAXONOMY_VERSION,
            },
        )
    except Exception as exc:
        log.warning("tier1_failed", error=str(exc))
        return Tier1Result.empty()
