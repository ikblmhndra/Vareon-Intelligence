"""Taksonomi industri tier 1: kata kunci sektor -> daftar industri classify.

Kunci = 19 industri spesifik di `_PROMPT` classify (tanpa "General"; "General"
adalah keputusan LLM, bukan sesuatu yang bisa dibuktikan dari kata kunci).

Prinsip: presisi di atas recall. Hanya istilah yang menyebut SEKTOR secara
spesifik ("hospital", "credit union", "power grid"); kata yang lazim di prosa
keamanan umum ("service", "network", "platform", "system") sengaja tidak ada.
Presisi diukur terhadap LLM pada sampel berlabel nanti, jadi daftar ini boleh
dipangkas/ditambah dan `INDUSTRY_TAXONOMY_VERSION` ikut berubah otomatis.

Pencocokan: tiap istilah dibungkus `\\b...\\b`, IGNORECASE, plural `s`/`es`
opsional. Murni string: tanpa Session, HTTP, atau spaCy.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

_TEXT_WINDOW = 1500
_MAX_INDUSTRIES = 3
_MIN_TEXT_HITS = 2

INDUSTRY_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "Government & Public Sector": (
        "ministry of",
        "government ministry",
        "municipality",
        "city council",
        "state government",
        "federal agency",
        "local government",
    ),
    "Finance & Insurance": (
        "credit union",
        "banks",
        "banking sector",
        "central bank",
        "commercial bank",
        "bank customers",
        "insurer",
        "insurance company",
        "insurance provider",
        "brokerage",
        "fintech",
        "payment processor",
        "asset manager",
        "mortgage lender",
    ),
    "Healthcare & Life Sciences": (
        "hospital",
        "health system",
        "healthcare provider",
        "clinic",
        "patient records",
        "pharmaceutical",
        "biotech",
        "medical center",
        "health insurer",
    ),
    "Energy & Utilities": (
        "power grid",
        "utility company",
        "electric utility",
        "oil and gas",
        "oil & gas",
        "power plant",
        "pipeline operator",
        "water utility",
        "energy company",
        "refinery",
    ),
    "Telecommunications": (
        "telecom",
        "telecommunications",
        "mobile carrier",
        "mobile operator",
        "internet service provider",
        "telco",
        "wireless carrier",
    ),
    "Information Technology & Software": (
        "software vendor",
        "software company",
        "managed service provider",
        "saas provider",
        "it services provider",
        "hosting provider",
    ),
    "Critical Infrastructure": (
        "critical infrastructure",
        "industrial control system",
        "water treatment",
        "dam operator",
        "emergency services",
        "operational technology",
    ),
    "Retail & E-commerce": (
        "retailer",
        "online store",
        "e-commerce site",
        "e-commerce platform",
        "e-commerce retailer",
        "e-commerce store",
        "online shop",
        "supermarket",
        "department store",
        "shopping platform",
        "point-of-sale",
    ),
    "Manufacturing & Industrial": (
        "manufacturer",
        "manufacturing",
        "automaker",
        "automotive supplier",
        "production plant",
        "industrial company",
        "steelmaker",
    ),
    "Education & Research": (
        "university",
        "community college",
        "school district",
        "research institute",
        "higher education",
        "academic institution",
    ),
    "Legal & Professional Services": (
        "law firm",
        "accounting firm",
        "consulting firm",
        "legal services",
        "audit firm",
        "staffing agency",
        "professional services firm",
    ),
    "Media & Entertainment": (
        "broadcaster",
        "news outlet",
        "newspaper",
        "streaming service",
        "game studio",
        "video game publisher",
        "film studio",
        "media company",
    ),
    "Transportation & Logistics": (
        "airline",
        "railway operator",
        "freight forwarder",
        "freight carrier",
        "airport",
        "port authority",
        "shipping company",
        "logistics company",
        "trucking company",
        "transit agency",
    ),
    "Real Estate & Construction": (
        "property developer",
        "real estate firm",
        "real estate company",
        "real estate agency",
        "construction company",
        "homebuilder",
        "property management",
        "estate agency",
        "title company",
    ),
    "Non-profit & NGOs": (
        "non-profit",
        "nonprofit",
        "charity",
        "humanitarian organization",
        "advocacy group",
    ),
    "Aerospace & Defense Contractors": (
        "defense contractor",
        "defence contractor",
        "aerospace",
        "defense industry",
        "defence industry",
        "military contractor",
        "shipbuilder",
    ),
    "Agriculture & Food": (
        "agriculture",
        "food processing",
        "food producer",
        "meatpacking",
        "beverage company",
        "food supply chain",
    ),
    "Mining & Natural Resources": (
        "mining company",
        "mining operator",
        "mine operator",
        "gold miner",
        "metals producer",
        "quarry",
        "coal producer",
    ),
    "Hospitality & Travel": (
        "hotel chain",
        "hotel group",
        "resort operator",
        "casino",
        "travel agency",
        "cruise line",
        "restaurant chain",
        "booking platform",
        "tourism",
    ),
}

INDUSTRY_TAXONOMY_VERSION = hashlib.sha256(
    repr(sorted(INDUSTRY_KEYWORDS.items())).encode()
).hexdigest()[:8]
"""Sidik jari kamus: berubah otomatis kalau kata kunci diedit (hasil lama bisa dihitung ulang)."""


def _compile(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term)}(?:e?s)?\b", re.IGNORECASE)


_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    name: tuple(_compile(t) for t in terms) for name, terms in INDUSTRY_KEYWORDS.items()
}


def match_industries(title: str, text: str) -> list[str]:
    """Industri yang terbukti dari kata kunci, maksimal 3.

    Satu kata kunci di judul cukup (judul padat dan sengaja memilih kata);
    di isi butuh >=2 kata kunci BERBEDA (satu sebutan sering cuma konteks
    sampingan). Urut: total hit terbanyak, lalu urutan taksonomi.
    """
    body = text[:_TEXT_WINDOW]
    scored: list[tuple[int, int, str]] = []
    for order, (name, patterns) in enumerate(_PATTERNS.items()):
        title_hits = sum(1 for p in patterns if p.search(title))
        body_hits = sum(1 for p in patterns if p.search(body))
        if title_hits >= 1 or body_hits >= _MIN_TEXT_HITS:
            scored.append((title_hits + body_hits, order, name))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [name for _, _, name in scored[:_MAX_INDUSTRIES]]
