"""Sektor industri: vocab STIX 2.1 `industry-sector-ov` dan pemetaan label industri lama."""

from __future__ import annotations

SECTORS: dict[str, str] = {
    "aerospace": "Aerospace",
    "agriculture": "Agriculture",
    "automotive": "Automotive",
    "chemical": "Chemical",
    "commercial": "Commercial",
    "communications": "Communications",
    "construction": "Construction",
    "defense": "Defense",
    "education": "Education",
    "emergency-services": "Emergency Services",
    "energy": "Energy",
    "entertainment": "Entertainment",
    "financial-services": "Financial Services",
    "government": "Government",
    "government-local": "Government (Local)",
    "government-national": "Government (National)",
    "government-public-services": "Government (Public Services)",
    "government-regional": "Government (Regional)",
    "healthcare": "Healthcare",
    "hospitality-leisure": "Hospitality & Leisure",
    "infrastructure": "Infrastructure",
    "infrastructure-dams": "Infrastructure (Dams)",
    "infrastructure-nuclear": "Infrastructure (Nuclear)",
    "infrastructure-water": "Infrastructure (Water)",
    "insurance": "Insurance",
    "manufacturing": "Manufacturing",
    "mining": "Mining",
    "non-profit": "Non-profit",
    "pharmaceuticals": "Pharmaceuticals",
    "retail": "Retail",
    "technology": "Technology",
    "telecommunications": "Telecommunications",
    "transportation": "Transportation",
    "utilities": "Utilities",
}

# Label industri yang pernah dipakai LLM/analis -> id vocab; "General" sengaja tanpa sektor.
_LABEL_TO_SECTOR: dict[str, str | None] = {
    "General": None,
    "Information Technology & Software": "technology",
    "Technology & Software": "technology",
    "Cloud & Hosting Providers": "technology",
    "Cloud Services": "technology",
    "Cloud Infrastructure Providers": "technology",
    "Critical Infrastructure": "infrastructure",
    "Finance & Insurance": "financial-services",
    "Cryptocurrency & Blockchain": "financial-services",
    "Government & Public Sector": "government",
    "Telecommunications": "telecommunications",
    "Healthcare & Life Sciences": "healthcare",
    "Retail & E-commerce": "retail",
    "Energy & Utilities": "energy",
    "Aerospace & Defense Contractors": "defense",
    "Manufacturing & Industrial": "manufacturing",
    "Media & Entertainment": "entertainment",
    "Gaming": "entertainment",
    "Education & Research": "education",
    "Science & Research": "education",
    "Education & Life Sciences": "education",
    "Transportation & Logistics": "transportation",
    "Legal & Professional Services": "commercial",
    "Security & Professional Services": "commercial",
    "Small Business Operations": "commercial",
    "Non-profit & NGOs": "non-profit",
    "Hospitality & Travel": "hospitality-leisure",
    "Agriculture & Food": "agriculture",
}


def sector_for_label(label: str) -> str | None:
    """Id vocab untuk label lama; `None` untuk "General" dan label yang tak dikenal."""
    return _LABEL_TO_SECTOR.get(label.strip())
