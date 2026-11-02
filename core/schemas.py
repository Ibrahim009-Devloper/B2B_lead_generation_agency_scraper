import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def compute_domain_hash(domain: Optional[str]) -> str:
    if not domain:
        return ""
    clean = domain.strip().lower()
    if "://" in clean:
        clean = clean.split("://", 1)[1]
    if clean.startswith("www."):
        clean = clean[4:]
    clean = clean.split("/")[0].split("?")[0].split("#")[0].split(":")[0].strip()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()

class AgencyType(str, Enum):
    B2B_LEAD_GEN = "b2b_lead_gen"
    COLD_EMAIL = "cold_email"
    LOCAL_SEO = "local_seo"
    DIGITAL_MARKETING = "digital_marketing"
    RECRUITING = "recruiting"
    DATA_RESEARCH = "data_research"
    NON_ICP = "non_icp"

class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    LIKELY_VALID = "likely_valid"
    CONFLICTING = "conflicting"
    UNKNOWN = "unknown"
    INVALID = "invalid"

class PriorityTier(str, Enum):
    HOT_LEAD = "Hot Lead"
    HIGH_POTENTIAL = "High-Potential Prospect"
    QUALIFIED = "Qualified Prospect"
    NEEDS_REVIEW = "Needs Review"
    REJECTED = "Rejected"

class LeadClassification(str, Enum):
    HOT_LEAD = "Hot Lead"
    LINKEDIN_OUTREACH_CANDIDATE = "LinkedIn Outreach Candidate"
    CONTACT_RESEARCH_REQUIRED = "Contact Research Required"
    QUALIFIED_EMAIL_UNAVAILABLE = "Qualified Company — Email Unavailable"
    REJECTED = "Rejected Lead"

class EmailType(str, Enum):
    PERSONAL_PROFESSIONAL = "Owner / Personal Email"
    GENERIC_BUSINESS = "Generic Business Email"
    UNKNOWN = "Generic Business Email"

class OutreachStatus(str, Enum):
    DRAFT = "draft"
    DRAFTED = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXPORTED = "exported"
    SENT = "sent"

class EvidenceItem(BaseModel):
    url: Optional[str] = None
    snippet: Optional[str] = None
    timestamp: datetime = Field(default_factory=utc_now)

class LeadRecord(BaseModel):
    lead_id: UUID = Field(default_factory=uuid4)
    campaign_id: Optional[str] = None
    business_name: str
    domain_hash: Optional[str] = None
    agency_type: AgencyType = AgencyType.NON_ICP
    client_industries_served: List[str] = Field(default_factory=list)
    core_services: List[str] = Field(default_factory=list)
    data_dependency_signals: List[str] = Field(default_factory=list)
    scale_signals: List[str] = Field(default_factory=list)
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    verified_email: Optional[str] = None
    email_mx_status: VerificationStatus = VerificationStatus.UNKNOWN
    address: Optional[str] = None
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    decision_maker_name: Optional[str] = None
    decision_maker_role: Optional[str] = None
    decision_maker_linkedin: Optional[str] = None
    source_names: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    collected_at: datetime = Field(default_factory=utc_now)
    last_verified_at: Optional[datetime] = None
    last_scraped_at: Optional[datetime] = Field(default_factory=utc_now)
    duplicate_group_id: Optional[UUID] = None
    business_verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    email_verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    phone_verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    factual_confidence: float = 0.0
    icp_fit_score: int = 0
    opportunity_score: int = 0
    opportunity_tier: Optional[str] = None
    opportunity_signals: List[str] = Field(default_factory=list)
    opportunity_breakdown: Dict[str, Any] = Field(default_factory=dict)
    data_dependency_score: int = 0

    # Master Architecture (Version 3.0 Python-First AI-Supervised)
    backup_emails: List[str] = Field(default_factory=list)
    complete_business_summary: Optional[str] = None
    their_target_clients: Optional[str] = None
    personalization_guide: Optional[str] = None
    source_footprint: Optional[str] = None
    target_verification_status: Optional[str] = None

    # Master Prompt 100-Point Scoring Model (Section 8)
    company_size: Optional[str] = "2-10"
    company_size_score: int = 0
    service_fit_score: int = 0
    scale_automation_score: int = 0
    buying_intent_score: int = 0
    decision_maker_score: int = 0
    contactability_score: int = 0
    total_score: int = 0

    # Master Prompt Classification (Section 9)
    lead_classification: LeadClassification = LeadClassification.CONTACT_RESEARCH_REQUIRED
    email_type: EmailType = EmailType.UNKNOWN
    recommended_outreach_channel: str = "email"
    evidence_of_need: Optional[str] = None
    evidence_source_urls: List[str] = Field(default_factory=list)

    score_explanation: List[str] = Field(default_factory=list)
    overall_priority: PriorityTier = PriorityTier.NEEDS_REVIEW
    recommended_scraping_pitch: Optional[str] = None
    custom_outreach_hook: Optional[str] = None
    outreach_angle: Optional[str] = None
    outreach_draft: Optional[str] = None
    outreach_status: OutreachStatus = OutreachStatus.DRAFT
    rejection_reason: Optional[str] = None

    def model_post_init(self, __context: Any) -> None:
        if self.website and not self.domain_hash:
            self.domain_hash = compute_domain_hash(self.website)
        if self.opportunity_score and not self.data_dependency_score:
            self.data_dependency_score = self.opportunity_score

class CampaignGoal(BaseModel):
    campaign_id: UUID = Field(default_factory=uuid4)
    raw_prompt: str
    agency_types: List[AgencyType] = Field(default_factory=list)
    target_geography: List[str] = Field(default_factory=list)
    target_client_niches: List[str] = Field(default_factory=list)
    lead_quantity: int = 20
    quality_threshold: int = 65
    created_at: datetime = Field(default_factory=utc_now)

class LLMUsageMetric(BaseModel):
    provider: str
    model: str
    key_index: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    cost_estimate_usd: float = 0.0
    success: bool = True
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=utc_now)
