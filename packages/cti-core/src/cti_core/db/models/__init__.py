"""Model SQLAlchemy -- satu sumber kebenaran skema, dipakai sesi sync
(Celery/CLI) dan async (FastAPI) sekaligus. Lihat db/engine.py.
"""

from cti_core.db.models.article import (
    Article,
    RejectedArticle,
)
from cti_core.db.models.attack import (
    AttackGroup,
    AttackMitigation,
    AttackRelationship,
    AttackSoftware,
    AttackSyncLog,
    AttackTactic,
    AttackTechnique,
    AttackTechniqueAlias,
)
from cti_core.db.models.auth import (
    ApiToken,
    AuditLogEntry,
    Client,
    ClientCountry,
    Role,
    User,
    UserClient,
)
from cti_core.db.models.catalog import CatalogFamily, CatalogFamilyAlias, CatalogVendor
from cti_core.db.models.cluster import Cluster
from cti_core.db.models.cve import (
    CveAffected,
    CveFalsePositive,
    CveNewsletterMention,
    CvePoc,
    CveReference,
    CveTicket,
    CveTracker,
)
from cti_core.db.models.cve_mirror import CvePromotionShadow, CveRecord, CveRecordProduct
from cti_core.db.models.enrich_job import EnrichJob
from cti_core.db.models.entity import (
    Entity,
    EntityAlias,
    EntityMention,
    EntityProfile,
    EntityWatch,
    ReferenceSnapshot,
    Relationship,
)
from cti_core.db.models.indicator import (
    Indicator,
    IndicatorFeedback,
    IndicatorSource,
    IndicatorTag,
)
from cti_core.db.models.ioc_reference import IocAllowlistEntry, ThreatFeedEntry
from cti_core.db.models.llm_call import LlmCall
from cti_core.db.models.malware_trend import MalwareTrend
from cti_core.db.models.mindmap import MindmapDoc
from cti_core.db.models.newsletter import (
    Newsletter,
    NewsletterArticleSummary,
    NewsletterPaywallHint,
    NewsletterSuggestion,
)
from cti_core.db.models.package import MonitoredPackage, PackageDepGraph, PackageVuln
from cti_core.db.models.pir import PIRNote, PIRRequirement
from cti_core.db.models.ransomware import RansomwareVictim
from cti_core.db.models.recap import DailyRecap
from cti_core.db.models.relevance import RelevanceModel
from cti_core.db.models.report_state import CveMention, JobState
from cti_core.db.models.rfi import RFIRequest
from cti_core.db.models.runtime_secret import RuntimeSecret
from cti_core.db.models.scraper import ScraperConfig, ScraperItem, ScraperRun, ScraperSeen
from cti_core.db.models.source_reliability import SourceReliabilityEntry
from cti_core.db.models.story import Story
from cti_core.db.models.techstack import TechStackEntry, TechStackTarget
from cti_core.db.models.threat_reference import MonitoredPerson, ThreatActorGroup
from cti_core.db.models.tweet import MonitoredAccount, Tweet

__all__ = [
    "ApiToken",
    "Article",
    "AttackGroup",
    "AttackMitigation",
    "AttackRelationship",
    "AttackSoftware",
    "AttackSyncLog",
    "AttackTactic",
    "AttackTechnique",
    "AttackTechniqueAlias",
    "AuditLogEntry",
    "CatalogFamily",
    "CatalogFamilyAlias",
    "CatalogVendor",
    "Client",
    "ClientCountry",
    "Cluster",
    "CveAffected",
    "CveFalsePositive",
    "CveMention",
    "CveNewsletterMention",
    "CvePoc",
    "CvePromotionShadow",
    "CveRecord",
    "CveRecordProduct",
    "CveReference",
    "CveTicket",
    "CveTracker",
    "DailyRecap",
    "EnrichJob",
    "Entity",
    "EntityAlias",
    "EntityMention",
    "EntityProfile",
    "EntityWatch",
    "Indicator",
    "IndicatorFeedback",
    "IndicatorSource",
    "IndicatorTag",
    "IocAllowlistEntry",
    "JobState",
    "LlmCall",
    "MalwareTrend",
    "MindmapDoc",
    "MonitoredAccount",
    "MonitoredPackage",
    "MonitoredPerson",
    "Newsletter",
    "NewsletterArticleSummary",
    "NewsletterPaywallHint",
    "NewsletterSuggestion",
    "PIRNote",
    "PIRRequirement",
    "PackageDepGraph",
    "PackageVuln",
    "RFIRequest",
    "RansomwareVictim",
    "ReferenceSnapshot",
    "RejectedArticle",
    "Relationship",
    "RelevanceModel",
    "Role",
    "RuntimeSecret",
    "ScraperConfig",
    "ScraperItem",
    "ScraperRun",
    "ScraperSeen",
    "SourceReliabilityEntry",
    "Story",
    "TechStackEntry",
    "TechStackTarget",
    "ThreatActorGroup",
    "ThreatFeedEntry",
    "Tweet",
    "User",
    "UserClient",
]
