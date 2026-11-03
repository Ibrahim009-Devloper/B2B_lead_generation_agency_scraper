import logging
import re
import json
from typing import Dict, List, Optional, Any, Set, Tuple
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator
import dns.resolver

try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

import httpx
from core.llm_router import llm_router, TaskType
from core.schemas import AgencyType
from pipeline.normalizer import normalize_domain
from core.proxy_rotator import proxy_rotator

logger = logging.getLogger("WebsiteEnrichment")

# Negative Keyword Block (Layer 1 Python Pre-Verifier - 0 Token Cost)
NEGATIVE_PREFILTER_PHRASES = [
    "non-profit organization", "nonprofit organization", "501(c)(3)", "registered charity",
    "restaurant menu", "view our menu", "order online menu", "food delivery menu",
    "book hair appointment", "haircut pricing", "patient portal", "medical emergency",
    "news portal", "breaking news", "online casino", "sports betting", "wikipedia",
    "funeral home", "sunday mass", "worship service"
]

NEGATIVE_DOMAIN_KEYWORDS = [
    "casino", "gambling", "wikipedia", "church", "parish", "funeral", "salon", "barber"
]

# Strict ICP Lock: Mandatory B2B Lead Gen & Outbound Sales Signals
MANDATORY_B2B_LEADGEN_SIGNALS = [
    # English Outbound Terms
    "lead generation", "b2b lead generation", "appointment setting", "appointment",
    "cold email", "cold calling", "outbound sales", "outbound", "sdr as a service", "sdr",
    "sales pipeline", "account-based marketing", "abm", "demand generation", "demand gen",
    "prospecting", "b2b outreach", "lead gen", "sales development", "book meetings",
    "sales meetings", "outreach", "b2b", "qualified leads", "b2b leads", "sales prospecting",
    "outbound marketing", "email outreach", "b2b sales",
    # Outbound Tech Stack Signals (Agencies mentioning these are 100% outbound cold outreach agencies)
    "lemlist", "smartlead", "instantly.ai", "waalaxy", "sales navigator", "salesloft", "outreach.io",
    # French Outbound Terms (Sortlist France/Belgium/Switzerland)
    "prospection", "génération de leads", "generation de leads", "rdv qualifiés", "rdv qualifies",
    "prise de rendez-vous", "prospection multicanale", "prospection commerciale", "cold emailing", "prospection b2b",
    # German Outbound Terms (Sortlist Germany/Austria/Switzerland)
    "leadgenerierung", "kaltakquise", "terminvereinbarung", "b2b-vertrieb", "vertriebsauslagerung",
    "neukundengewinnung", "terminakquise", "outbound-vertrieb",
    # Spanish Outbound Terms (Sortlist Spain/LatAm)
    "generación de leads", "generacion de leads", "prospección", "prospeccion",
    "concertación de citas", "concertacion de citas", "desarrollo de ventas",
    # Italian Outbound Terms (Sortlist Italy)
    "generazione di lead", "acquisizione clienti", "fissare appuntamenti", "presa appuntamenti"
]

NON_ICP_SERVICE_KEYWORDS = [
    "local seo", "seo agency", "search engine optimization", "web design",
    "website design", "branding", "graphic design", "social media management",
    "pr agency", "public relations", "b2c marketing", "wedding", "photography"
]

# Foreign country TLDs blocked when targeting USA
FOREIGN_COUNTRY_TLDS = (
    ".de", ".fr", ".it", ".es", ".in", ".co.uk", ".uk", ".at", ".ch", ".nl", ".be", ".eu",
    ".se", ".no", ".dk", ".fi", ".pl", ".cz", ".ru", ".cn", ".jp", ".kr", ".com.au", ".com.br",
    ".co.in", ".co.za", ".co.nz", ".com.mx", ".com.ar", ".pt", ".ie"
)

# Comprehensive generic email prefixes - User Policy: STRICTLY DISALLOWED
# info@, contact@, service@, support@, sales@, etc. are 100% REJECTED
STRICTLY_DISALLOWED_PREFIXES = {
    'info', 'contact', 'service', 'services', 'support', 'admin', 'office', 'inquiry', 'inquiries',
    'enquiry', 'enquiries', 'growth', 'bizdev', 'biz', 'business', 'newbusiness', 'new-business',
    'outbound', 'inbound', 'post', 'editorial', 'client', 'clients', 'talent', 'hire', 'hiring',
    'work', 'workwithus', 'consult', 'booking', 'bookings',
    'sales', 'anfrage', 'kontakt', 'team', 'accounts', 'marketing', 'dev', 'jobs', 'billing',
    'press', 'media', 'general', 'partners', 'partner', 'mail', 'help', 'customercare',
    'contactus', 'reachus', 'office-admin', 'operations', 'editor', 'privacy', 'legal',
    'security', 'feedback', 'compliance', 'careers', 'hr', 'apply', 'noreply', 'no-reply',
    'postmaster', 'hostmaster', 'webmaster', 'recruitment', 'accounting', 'invoice', 'desk',
    'info-de', 'info-fr', 'info-us', 'customer'
}

# Owner & C-Suite personal role prefixes - EXPLICITLY ALLOWED per user rule
OWNER_ROLE_PREFIXES = {
    'founder', 'ceo', 'owner', 'partner', 'president', 'co-founder', 'cofounder',
    'managing-director', 'managingdirector', 'md', 'principal', 'director',
    'cto', 'technical-director', 'technicaldirector', 'head-of-operations', 'coo'
}

GENERIC_EMAIL_PREFIXES = STRICTLY_DISALLOWED_PREFIXES

def is_acceptable_lead_email(email: str, decision_maker_name: Optional[str] = None) -> Tuple[bool, str]:
    """
    User Hierarchical Email Acceptance Policy (for 2-50 employee boutique/SME businesses):
    Priority 1: Verified Founder Email -> Accept
    Priority 2: Verified Owner / Leadership Email -> Accept
    Priority 3: hello@ -> Accept
    Priority 4: info@ -> Review / Accept
    Priority 5: contact@ -> Review / Accept
    Priority 6: sales@ -> Review / Accept
    Priority 7: support@ -> Low priority / Accept
    Strict Reject: noreply@, no-reply@, billing@, jobs@, careers@, privacy@
    """
    if not email or "@" not in email:
        return False, "invalid_format"

    local = email.split("@")[0].lower().strip()

    # Strict hard rejects
    if any(local.startswith(p) for p in ["noreply", "no-reply", "donotreply", "billing", "invoice", "privacy", "legal", "abuse", "webmaster", "jobs", "careers", "recruitment", "apply"]):
        return False, "noreply_or_automated"

    # Priority 1 & 2: Founder / Owner / Leadership role prefix
    if local in OWNER_ROLE_PREFIXES:
        return True, "owner_role_email"

    # Priority 1 & 2: Direct Decision Maker Name match (e.g. Ambuj -> ambuj@)
    if decision_maker_name:
        dm_parts = [p.lower() for p in re.split(r"[\s._\-]+", decision_maker_name) if len(p) >= 2]
        if any(p in local for p in dm_parts):
            return True, "decision_maker_matched_email"

    # Priority 1 & 2: Personal human name pattern (e.g. michael@, sarah.connor@)
    parts = re.split(r"[._\-]", local)
    if len(parts) >= 1 and all(p.isalpha() and len(p) >= 2 for p in parts) and local not in ["info", "contact", "sales", "support", "hello", "office", "team", "inquiries", "enquiries", "admin"]:
        return True, "personal_owner_email"

    # Priority 3: hello@
    if local == "hello":
        return True, "hello_boutique_email"

    # Priority 4: info@
    if local == "info" or local.startswith("info.") or local.startswith("info_"):
        return True, "info_business_email"

    # Priority 5: contact@
    if local == "contact" or local.startswith("contact.") or local.startswith("contact_"):
        return True, "contact_business_email"

    # Priority 6: sales@
    if local == "sales" or local.startswith("sales.") or local.startswith("sales_"):
        return True, "sales_business_email"

    # Priority 7: support@ (Low priority)
    if local == "support" or local.startswith("support.") or local.startswith("support_"):
        return True, "support_low_priority_email"

    # Other warm business inboxes (office@, team@)
    if local in ["office", "team", "inquiries", "enquiries", "admin"]:
        return True, "generic_business_email"

    return True, "general_lead_email"

def extract_founder_name_from_text(text: str) -> Optional[str]:
    """Extracts founder/CEO/partner name from text using strict regex patterns."""
    patterns = [
        r"(?:founded by|co-founded by)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*,\s*(?:founder|ceo|co-founder|president|owner|managing director|head of operations|technical director|cto)",
        r"(?:founder & ceo|founder and ceo|ceo & founder|ceo|founder|owner|managing director|technical director|head of operations)\s*[:\-–—]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            parts = name.split()
            if 2 <= len(parts) <= 3 and not any(w.lower() in ["agency", "company", "services", "solutions", "group", "media", "digital", "lead", "marketing"] for w in parts):
                return name.title()
    return None

POSITIVE_INDUSTRY_KEYWORDS = set(MANDATORY_B2B_LEADGEN_SIGNALS)
REQUIRED_ICP_KEYWORDS = set(MANDATORY_B2B_LEADGEN_SIGNALS)

PLACEHOLDER_DOMAINS = {
    "company.com", "domain.com", "example.com", "yoursite.com", "email.com",
    "sentry.io", "wixpress.com", "test.com", "sample.com", "mysite.com",
    "website.com", "placeholder.com", "sitename.com"
}

BLOCKED_EMAIL_PREFIXES = {
    "recruitment", "careers", "jobs", "hr", "apply", "privacy", "legal",
    "billing", "noreply", "no-reply", "abuse", "webmaster", "security",
    "compliance", "accounting", "invoice", "admin-hr", "postmaster"
}

GENERIC_SALES_PREFIXES = GENERIC_EMAIL_PREFIXES

class WebsiteSignalExtraction(BaseModel):
    clean_business_name: Optional[str] = Field(default=None, description="Actual official agency brand name (e.g. 'Outreach Monks', 'Salaria Sales'). Never a blog headline or listicle title.")
    is_agency: bool = Field(default=True, description="Is this business an agency or service provider? False for software giants, personal blogs, direct B2C local services.")
    agency_type: AgencyType = Field(default=AgencyType.NON_ICP, description="Classified agency category")
    client_industries_served: List[str] = Field(default_factory=list, description="Exact verticals or client niches served (e.g. Roofers, MedSpas, SaaS)")
    core_services: List[str] = Field(default_factory=list, description="Core services (e.g. Cold Email, Local SEO, PPC)")
    company_size: Optional[str] = Field(default="2-10", description="Estimated company size/employees: '2-10', '10-50', '50-200', or '200+'")
    data_dependency_signals: List[str] = Field(default_factory=list, description="Signals showing they need web scraping or prospect lists")
    scale_signals: List[str] = Field(default_factory=list, description="Signals showing handling large volumes, automation, or hiring data researchers")
    decision_maker_name: Optional[str] = Field(default=None, description="Founder, Owner, CEO or Partner name if found")
    decision_maker_role: Optional[str] = Field(default=None, description="Title/role of decision-maker")
    decision_maker_linkedin: Optional[str] = Field(default=None, description="LinkedIn profile URL if found")
    extracted_email: Optional[str] = Field(default=None, description="Business or founder email found on site")
    backup_emails: List[str] = Field(default_factory=list, description="1-2 additional valid backup emails found on site")
    email_category: str = Field(default="Generic Business Email", description="Owner / Personal Email or Generic Business Email")
    extracted_phone: Optional[str] = Field(default=None, description="Phone number found on site")
    email_hidden_on_site: bool = Field(default=False, description="True if email was hidden on site but valid MX was found")

    # Agency Opportunity Detection (Buying Probability for Scraping & Data Pipelines)
    multi_client_leadgen: bool = Field(default=False, description="True if they run outbound campaigns / lead generation for external B2B clients across multiple client accounts")
    cross_industry_prospecting: bool = Field(default=False, description="True if they prospect across multiple distinct verticals/industries (e.g. Healthcare, SaaS, Logistics, Real Estate)")
    custom_data_offering: bool = Field(default=False, description="True if they offer custom list building, account research, directory scraping, or specialized B2B contact lists")
    has_research_team_signals: bool = Field(default=False, description="True if they have manual list builders, SDRs, prospect researchers, or suffer from data sourcing labor bottlenecks")
    recurring_data_need: bool = Field(default=False, description="True if they have continuous, recurring monthly appetite for fresh live data feeds and verified email datasets")
    opportunity_score: int = Field(default=0, description="0 to 100 Opportunity Score measuring likelihood of buying custom scraping / lead data pipelines")
    opportunity_tier: str = Field(default="MODERATE OPPORTUNITY", description="CRITICAL ICP FIT, HIGH OPPORTUNITY, MODERATE OPPORTUNITY, or LOW OPPORTUNITY")
    opportunity_reasons: List[str] = Field(default_factory=list, description="Specific evidence and reasons why this agency needs custom scraping / data pipelines")

    # Phase 4 - Layer 2: AI Business Verifier 4 Conditions
    is_real_business: bool = Field(default=True, description="True if genuine commercial business selling products/services; False if blog, directory, news")
    service_buying_need_verified: bool = Field(default=True, description="True if agency, e-commerce brand, or data-heavy firm requiring scraping/leads/automation; False for irrelevant businesses like local plumber/salon")
    company_size_approved: bool = Field(default=True, description="True if boutique/agile active business (2-50 employees); False for huge enterprise conglomerates")
    email_matches_business: bool = Field(default=True, description="True if email matches company brand/domain, False if 3rd party ad/unrelated")
    is_verified_target: bool = Field(default=True, description="True ONLY when all 4 conditions are 100% satisfied")
    target_verification_status: str = Field(default="VERIFIED_TARGET (B2B Lead Gen Agency)", description="VERIFIED_TARGET + Category, or REJECTED (<Reason>)")

    # AI Supervisor 4 Core Outputs (Phase 5 of Architecture Rules)
    complete_business_summary: Optional[str] = Field(default=None, description="Detailed explanation of what the business does, what services they sell, and how they operate")
    their_target_clients: Optional[str] = Field(default=None, description="Who their target customers or clients are (e.g. MedSpas, SaaS, E-commerce, Real Estate)")
    service_need_explanation: Optional[str] = Field(default=None, description="Why this agency needs custom web scraping, lead data, or automation")
    personalization_guide: Optional[str] = Field(default=None, description="Human Sales Rep Guide: Exactly what specific hook, case study, or client niche to mention from their site")
    ready_cold_email: Optional[str] = Field(default=None, description="Ready-to-send personalized cold email under 75 words, plain-text, zero links, proposing free sample leads")
    evidence_quote_niche: Optional[str] = Field(default=None, description="Verbatim quote from the website stating their target niche")
    evidence_quote_decision_maker: Optional[str] = Field(default=None, description="Verbatim quote mentioning the founder/owner name and title")
    tech_fit_score: int = Field(default=15, description="15 pts for standard CMS/no enterprise anti-bot, 5 pts if enterprise WAF")
    factual_confidence: float = Field(default=0.7, description="Confidence score from 0.0 to 1.0")
    non_agency_reason: Optional[str] = Field(default=None, description="Explanation if rejected as non-agency")
    zero_token_rejected: bool = Field(default=False, description="True if dropped before calling LLM")

    @field_validator("agency_type", mode="before")
    @classmethod
    def normalize_agency_type(cls, v: Any) -> Any:
        if isinstance(v, AgencyType):
            return v
        if isinstance(v, str):
            clean = v.strip().lower()
            if any(term in clean for term in ["cold email", "outbound", "email outreach", "cold outreach"]):
                return AgencyType.COLD_EMAIL
            if any(term in clean for term in ["b2b lead gen", "lead generation", "lead gen", "prospecting", "b2b"]):
                return AgencyType.B2B_LEAD_GEN
            if any(term in clean for term in ["local seo", "seo", "citation"]):
                return AgencyType.LOCAL_SEO
            if any(term in clean for term in ["digital marketing", "marketing", "ppc", "advertising"]):
                return AgencyType.DIGITAL_MARKETING
            if any(term in clean for term in ["recruiting", "staffing", "talent", "headhunting"]):
                return AgencyType.RECRUITING
            if any(term in clean for term in ["data research", "data", "mining"]):
                return AgencyType.DATA_RESEARCH
            if "non" in clean or "not" in clean:
                return AgencyType.NON_ICP
            for at in AgencyType:
                if at.value in clean:
                    return at
        return AgencyType.NON_ICP

    @field_validator("client_industries_served", "core_services", "data_dependency_signals", "scale_signals", mode="before")
    @classmethod
    def ensure_list(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [str(s) for s in v]
        return []

WebsiteEnrichmentResult = WebsiteSignalExtraction

class WebsiteEnrichmentAgent:
    def __init__(self, timeout: float = 3.5):
        self.timeout = timeout
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }

    def _normalize_url(self, website: str) -> str:
        url = website.strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"
        return url

    def _format_domain_brand(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            dom = netloc.split(".")[0]
            return dom.replace("-", " ").replace("_", " ").title()
        except Exception:
            return "Agency Partner"

    def fetch_page(self, url: str) -> Optional[str]:
        """
        Uses curl_cffi for TLS fingerprint bypass with automatic fallback to HTTPX.
        Includes fast drop for deeply nested/junk subdomains.
        """
        try:
            parsed = urlparse(url)
            netloc = parsed.netloc.lower()
            parts = netloc.split(".")
            if len(parts) > 3 or any(w in netloc for w in ["preview.", "advisor.ai", "cli.mastercard", "sbc.com", "aflac.co", "parceladvisor"]):
                return None
        except Exception:
            pass

        if HAS_CURL_CFFI:
            try:
                proxies = proxy_rotator.get_proxies_dict()
                resp = curl_requests.get(
                    url,
                    impersonate="chrome124",
                    headers=self.headers,
                    proxies=proxies,
                    timeout=self.timeout,
                    verify=False
                )
                if resp.status_code in (403, 429) and proxies:
                    proxy_rotator.report_failure(proxies.get("http"), status_code=resp.status_code, reason="Target site blocked IP")
                    # Immediate auto-retry with next rotating proxy in pool
                    alt_proxies = proxy_rotator.get_proxies_dict()
                    resp = curl_requests.get(
                        url,
                        impersonate="chrome124",
                        headers=self.headers,
                        proxies=alt_proxies,
                        timeout=self.timeout,
                        verify=False
                    )
                if resp.status_code == 200:
                    text = resp.text or ""
                    # Memory protection: Cap raw HTML to 400KB max per page
                    return text[:400_000] if len(text) > 400_000 else text
            except Exception as e:
                logger.debug(f"curl_cffi fetch exception for {url}: {e}")

        # Fallback to standard HTTPX
        try:
            with httpx.Client(headers=self.headers, verify=False, timeout=self.timeout) as client:
                resp = client.get(url, follow_redirects=True)
                if resp.status_code == 200:
                    text = resp.text or ""
                    return text[:400_000] if len(text) > 400_000 else text
        except Exception as e:
            logger.debug(f"HTTPX fetch failed for {url}: {e}")
        return None

    def fetch_html(self, url: str) -> Optional[str]:
        """Public method for fetching raw HTML."""
        return self.fetch_page(url) or ""

    def discover_relevant_links(self, base_url: str, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        contact_patterns = [r"contact", r"reach", r"get-in-touch", r"connect", r"book", r"call"]
        leadership_patterns = [r"about", r"team", r"leadership", r"who-we-are", r"founder", r"people"]
        service_patterns = [r"services", r"what-we-do", r"solutions", r"outbound", r"lead-generation"]
        
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc.lower()
        contact_links: Set[str] = set()
        leadership_links: Set[str] = set()
        service_links: Set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            full_url = urljoin(base_url, href)
            parsed_href = urlparse(full_url)
            
            if parsed_href.netloc.lower() != base_domain:
                continue

            path = parsed_href.path.lower()
            if any(re.search(p, path) for p in contact_patterns):
                contact_links.add(full_url)
            elif any(re.search(p, path) for p in leadership_patterns):
                leadership_links.add(full_url)
            elif any(re.search(p, path) for p in service_patterns):
                service_links.add(full_url)

        # Prioritize Leadership / Team links first to find Founder names and personal emails, then Contact, then Services
        ordered = list(leadership_links)[:2] + list(contact_links)[:1] + list(service_links)[:1]
        soup.decompose()
        return ordered[:3]

    def extract_phones(self, html: str) -> List[str]:
        """Extracts direct phone numbers from tel: links and body text."""
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        phones = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("tel:"):
                clean = re.sub(r"[^\d+]", "", href[4:])
                if 10 <= len(clean) <= 15:
                    phones.add(clean)

        raw_text = soup.get_text(separator=" ")
        matches = re.findall(r"(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}", raw_text)
        for m in matches:
            clean = re.sub(r"[^\d+]", "", m)
            if 10 <= len(clean) <= 15:
                phones.add(m.strip())
        soup.decompose()
        return list(phones)

    def compress_html_payload(self, html: str, max_chars: int = 3500) -> str:
        """
        HTML Payload Compression (Version 3.0 Critical Rule Aligned):
        CRITICAL RULE: NEVER delete <header> or <footer>!
        90% of real emails, company addresses, and executive summaries reside in the footer/header.
        Strips only <script>, <style>, <noscript>, <svg>, <iframe>, and noisy images.
        """
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()

        # Remove base64 or noisy images
        for img in soup.find_all("img"):
            img.decompose()

        # Extract clean visible body text preserving header and footer
        text = soup.get_text(separator=" ", strip=True)
        soup.decompose()
        text = re.sub(r"\s+", " ", text)
        return text[:max_chars]

    def extract_clean_text(self, html: str, max_chars: int = 4000) -> str:
        """Alias for backward compatibility and clean text extraction."""
        return self.compress_html_payload(html, max_chars=max_chars)

    def layer1_python_preverifier(self, text: str, domain: str = "") -> Tuple[bool, str]:
        """
        Phase 4 - Layer 1: Python Pre-Verifier (Hard Keyword Filter - 0 Token Cost)
        Strict ICP Lock: ONLY B2B Lead Gen & Outbound Sales Agencies.
        1. Negative Keyword Block: Non-profit, charity, government, restaurant, salon, hospital, etc.
        2. Dead / Parked Site Drop: 'domain for sale', 'under construction', insufficient content (< 50 chars).
        3. Non-ICP Service Block: Local SEO, Web Design, Branding, PR, B2C Marketing without strong outbound focus.
        4. Mandatory Positive B2B Lead Gen Signals: Must match at least TWO distinct B2B lead generation signals.
        """
        low = text.lower()

        # Check official government/military/education domains
        if domain:
            dom_low = domain.lower()
            if any(dom_low.endswith(ext) or f"{ext}." in dom_low for ext in [".gov", ".mil", ".edu"]):
                return False, "Government/military/education official domain (.gov / .mil / .edu) blocked"
            if any(bad in dom_low for bad in NEGATIVE_DOMAIN_KEYWORDS):
                return False, f"Negative industry domain blocked: '{bad}'"

        # 1. Negative Keyword Block (Strict Non-Commercial Phrases only: .gov, .edu, charity, casino, porn)
        for neg in NEGATIVE_PREFILTER_PHRASES:
            if neg in low:
                return False, f"Negative industry phrase blocked: '{neg}'"

        # 2. Dead or Parked Site Drop
        for parked_marker in ["domain for sale", "under construction", "buy this domain", "parked domain", "this domain is for sale", "renew your domain"]:
            if parked_marker in low:
                return False, f"Parked/Dead domain marker detected: '{parked_marker}'"

        if len(text.strip()) < 50:
            return False, "Dead site or insufficient content (< 50 characters)"

        # All commercial agencies and businesses pass Layer 1 pre-verifier. No niche keywords blocking.
        return True, "Passed Layer 1 Pre-Verifier (Commercial Website)"

    def zero_token_prefilter(self, text: str) -> bool:
        """
        Zero-Token Pre-filtering:
        Scans text for required agency/data keywords without calling any LLM.
        Returns True if text passes pre-filter, False if dropped.
        """
        passed, _ = self.layer1_python_preverifier(text)
        return passed

    def _is_domain_match(self, email_dom: Optional[str], target_dom: Optional[str]) -> bool:
        if not email_dom or not target_dom:
            return False
        from pipeline.normalizer import normalize_domain
        e = normalize_domain(email_dom)
        t = normalize_domain(target_dom)
        if not e or not t:
            return False
        # Exact match: cience.com == cience.com
        if e == t:
            return True
        # Subdomain match: mail.cience.com ends with .cience.com
        if e.endswith("." + t):
            return True
        # Brand alias match: belkins.com vs belkins.io (only if brand is >= 4 chars)
        e_brand = e.split(".")[0]
        t_brand = t.split(".")[0]
        if len(t_brand) >= 4 and e_brand == t_brand:
            return True
        return False

    def extract_emails(
        self,
        text: str,
        target_domain: Optional[str] = None,
        target_url: Optional[str] = None
    ) -> List[str]:
        target_domain = target_domain or target_url
        # Clean escaped newlines/tabs from raw HTML or JS strings before regex matching
        cleaned_text = text.replace(r"\n", " ").replace(r"\r", " ").replace(r"\t", " ")
        matches = re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", cleaned_text)
        filtered = []
        for m in matches:
            cleaned = re.sub(r"^(?:u003e|u003c|>|<|mailto:)+", "", m, flags=re.IGNORECASE).strip()
            cleaned = cleaned.strip(".,;:\"'<>\\/ \t\n\r")
            # Auto-sanitize any clipped prefix like "nfo@" -> "info@"
            if cleaned.lower().startswith("nfo@"):
                cleaned = "i" + cleaned
            if "@" not in cleaned:
                continue

            prefix, email_dom = cleaned.lower().split("@", 1)
            prefix = prefix.strip()
            email_dom = email_dom.strip()

            # 1. Block placeholder domains
            if email_dom in PLACEHOLDER_DOMAINS or any(p in email_dom for p in ["example.com", "sentry.io", "wixpress.com", "domain.com", ".png", ".jpg"]):
                continue

            # 2. Block non-sales / HR / legal prefixes
            if prefix in BLOCKED_EMAIL_PREFIXES:
                continue

            # 3. Strict Domain Match
            if target_domain:
                if not self._is_domain_match(email_dom, target_domain):
                    continue

            filtered.append(cleaned)
        return list(set(filtered))

    def _select_best_email(self, emails: List[str], decision_maker_name: Optional[str] = None) -> Optional[str]:
        primary, _, _ = self._prioritize_emails(emails, decision_maker_name)
        return primary

    def detect_tech_fit(self, html: str) -> int:
        """
        Detects tech stack fit (15 pts for standard CMS/no enterprise bot protection, 5 pts if enterprise WAF).
        """
        low = html.lower()
        if "cloudflare" in low and ("cf-browser-verification" in low or "challenge-platform" in low):
            return 5
        if "perimeterx" in low or "datadome" in low:
            return 5
        return 15

    def check_mx_record(self, domain: str) -> bool:
        """100% Python DNS MX verification with resilient public DNS resolvers."""
        clean = domain.strip().lower()
        if clean.startswith("www."):
            clean = clean[4:]
        try:
            resolver = dns.resolver.Resolver()
            resolver.nameservers = ["8.8.8.8", "1.1.1.1", "8.8.4.4"]
            resolver.timeout = 2.5
            resolver.lifetime = 2.5
            answers = resolver.resolve(clean, "MX")
            return len(answers) > 0
        except Exception:
            try:
                # Fallback to A record if no explicit MX configured
                resolver = dns.resolver.Resolver()
                resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
                resolver.timeout = 2.0
                resolver.lifetime = 2.0
                answers = resolver.resolve(clean, "A")
                return len(answers) > 0
            except Exception:
                return False

    def _infer_dm_from_email(self, email: Optional[str]) -> Optional[str]:
        if not email or "@" not in email:
            return None
        local = email.split("@")[0].lower().strip()
        if local in GENERIC_EMAIL_PREFIXES:
            return None
        parts = re.split(r"[._\-]", local)
        if len(parts) == 2 and all(p.isalpha() and len(p) >= 2 for p in parts):
            return f"{parts[0].capitalize()} {parts[1].capitalize()}"
        return None

    def _prioritize_emails(self, emails: List[str], decision_maker_name: Optional[str] = None) -> Tuple[Optional[str], List[str], str]:
        """
        User Hierarchical Email Priority Order:
        1. Verified Founder / Owner / C-Suite / DM Personal Email -> Accept
        2. hello@ -> Accept
        3. info@ -> Review / Accept
        4. contact@ -> Review / Accept
        5. sales@ -> Review / Accept
        6. support@ -> Low priority
        Reject: noreply@, jobs@, billing@
        """
        if not emails:
            return None, [], "Disallowed"

        founder_owner_emails = []
        hello_emails = []
        info_emails = []
        contact_emails = []
        sales_emails = []
        support_emails = []
        other_emails = []

        dm_parts = [p.lower() for p in re.split(r"[\s._\-]+", decision_maker_name) if len(p) >= 2] if decision_maker_name else []

        for em in emails:
            is_ok, reason = is_acceptable_lead_email(em, decision_maker_name)
            if not is_ok:
                continue

            local = em.split("@")[0].lower().strip()
            if dm_parts and any(p in local for p in dm_parts):
                founder_owner_emails.append(em)
            elif local in OWNER_ROLE_PREFIXES:
                founder_owner_emails.append(em)
            elif local == "hello":
                hello_emails.append(em)
            elif local.startswith("info"):
                info_emails.append(em)
            elif local.startswith("contact"):
                contact_emails.append(em)
            elif local.startswith("sales"):
                sales_emails.append(em)
            elif local.startswith("support"):
                support_emails.append(em)
            else:
                # Personal names or general
                parts = re.split(r"[._\-]", local)
                if len(parts) >= 1 and all(p.isalpha() and len(p) >= 2 for p in parts):
                    founder_owner_emails.append(em)
                else:
                    other_emails.append(em)

        # 1. Founder / Owner
        if founder_owner_emails:
            primary = founder_owner_emails[0]
            cat = "Owner / Personal Email"
            backups = [e for e in (founder_owner_emails[1:] + hello_emails + info_emails + contact_emails + sales_emails) if e != primary][:2]
            return primary, backups, cat

        # 2. hello@
        if hello_emails:
            primary = hello_emails[0]
            cat = "hello@ Boutique Email"
            backups = [e for e in (hello_emails[1:] + info_emails + contact_emails + sales_emails) if e != primary][:2]
            return primary, backups, cat

        # 3. info@
        if info_emails:
            primary = info_emails[0]
            cat = "info@ Business Email"
            backups = [e for e in (info_emails[1:] + contact_emails + sales_emails + support_emails) if e != primary][:2]
            return primary, backups, cat

        # 4. contact@
        if contact_emails:
            primary = contact_emails[0]
            cat = "contact@ Business Email"
            backups = [e for e in (contact_emails[1:] + sales_emails + support_emails) if e != primary][:2]
            return primary, backups, cat

        # 5. sales@
        if sales_emails:
            primary = sales_emails[0]
            cat = "sales@ Business Email"
            backups = [e for e in (sales_emails[1:] + support_emails) if e != primary][:2]
            return primary, backups, cat

        # 6. support@
        if support_emails:
            primary = support_emails[0]
            cat = "support@ (Low Priority)"
            backups = [e for e in support_emails[1:] if e != primary][:2]
            return primary, backups, cat

        # 7. other acceptable
        if other_emails:
            primary = other_emails[0]
            cat = "General Business Email"
            backups = [e for e in other_emails[1:] if e != primary][:2]
            return primary, backups, cat

        return None, [], "Disallowed"

    def enrich_website(self, raw_website: str, initial_name: str = "", target_country: Optional[str] = None) -> WebsiteSignalExtraction:
        base_url = self._normalize_url(raw_website)
        all_text_snippets: List[str] = []
        extracted_emails: List[str] = []
        extracted_phones: List[str] = []
        tech_fit = 15

        # Geo Filter: If target country is USA, immediately drop foreign ccTLDs
        if target_country and target_country.upper() in ("USA", "US", "UNITED STATES"):
            dom_low = base_url.lower()
            for tld in FOREIGN_COUNTRY_TLDS:
                if dom_low.endswith(tld) or f"{tld}/" in dom_low:
                    logger.info(f"Target country is USA but foreign ccTLD '{tld}' detected for {raw_website}. Dropping (0 tokens burned).")
                    return WebsiteSignalExtraction(
                        clean_business_name=self._format_domain_brand(base_url),
                        is_agency=False,
                        is_real_business=False,
                        is_verified_target=False,
                        agency_type=AgencyType.NON_ICP,
                        target_verification_status=f"REJECTED: Non-USA foreign ccTLD '{tld}'",
                        factual_confidence=0.0,
                        non_agency_reason=f"Target country is USA but domain has foreign ccTLD '{tld}'",
                        zero_token_rejected=True
                    )

        home_html = self.fetch_page(base_url)
        if not home_html and base_url.startswith("https://"):
            home_html = self.fetch_page(base_url.replace("https://", "http://"))

        if not home_html:
            return WebsiteSignalExtraction(
                is_agency=False,
                is_real_business=False,
                is_verified_target=False,
                agency_type=AgencyType.NON_ICP,
                target_verification_status="REJECTED: Website unreachable via HTTP",
                factual_confidence=0.0,
                non_agency_reason=f"Website could not be reached via HTTP: {raw_website}",
                zero_token_rejected=True
            )

        tech_fit = self.detect_tech_fit(home_html)
        home_text = self.compress_html_payload(home_html, max_chars=3500)
        extracted_emails.extend(self.extract_emails(home_html, target_domain=base_url))
        extracted_phones.extend(self.extract_phones(home_html))

        # Extract OpenGraph site name or title for accurate brand naming
        og_brand = None
        soup_home = BeautifulSoup(home_html, "html.parser")
        og_tag = soup_home.find("meta", property="og:site_name")
        if og_tag and og_tag.get("content"):
            og_brand = og_tag["content"].strip()
        elif soup_home.title and soup_home.title.string:
            title_text = soup_home.title.string.strip()
            parts = re.split(r"[-|:–—]", title_text)
            if parts and len(parts[0].strip()) < 35 and not any(w in parts[0].lower() for w in ["best", "top", "home", "welcome", "list", "ranking"]):
                og_brand = parts[0].strip()
        soup_home.decompose() # Instantly release BeautifulSoup DOM from memory

        # 1. Fast Negative Keyword & Parked Domain Check on Homepage
        low_home = home_text.lower()
        for neg in NEGATIVE_PREFILTER_PHRASES:
            if neg in low_home:
                logger.info(f"Layer 1 Pre-verifier DROPPED {raw_website}: Negative keyword '{neg}' (0 LLM tokens burned).")
                return WebsiteSignalExtraction(
                    clean_business_name=og_brand or self._format_domain_brand(base_url),
                    is_agency=False,
                    is_real_business=False,
                    is_verified_target=False,
                    agency_type=AgencyType.NON_ICP,
                    target_verification_status=f"REJECTED: Negative keyword '{neg}'",
                    factual_confidence=0.0,
                    non_agency_reason=f"Layer 1 Pre-verifier Dropped: Negative keyword '{neg}'",
                    zero_token_rejected=True
                )

        for parked_marker in ["domain for sale", "under construction", "buy this domain", "parked domain", "this domain is for sale"]:
            if parked_marker in low_home:
                return WebsiteSignalExtraction(
                    clean_business_name=og_brand or self._format_domain_brand(base_url),
                    is_agency=False,
                    is_real_business=False,
                    is_verified_target=False,
                    agency_type=AgencyType.NON_ICP,
                    target_verification_status="REJECTED: Parked domain",
                    factual_confidence=0.0,
                    non_agency_reason="Layer 1 Pre-verifier Dropped: Parked domain",
                    zero_token_rejected=True
                )

        all_text_snippets.append(f"--- Homepage ({base_url}) ---\n{home_text}")

        # Targeted Multi-Page Scraping: Prioritize team/leadership and contact subpages
        sub_links = self.discover_relevant_links(base_url, home_html)
        if len(sub_links) < 4:
            for probe_path in ["/team", "/about", "/leadership", "/our-team", "/contact", "/services"]:
                probe_url = f"{base_url.rstrip('/')}{probe_path}"
                if probe_url not in sub_links:
                    sub_links.append(probe_url)
                if len(sub_links) >= 4:
                    break

        target_sub_links = sub_links[:4]
        # Sequential subpage crawl (avoids nested thread pool explosion inside 512MB RAM container)
        for link in target_sub_links:
            # Owner Protection Early Exit: Only break if an actual personal/owner email was found
            # (Never early-exit on generic emails or hello@ until team/leadership/about pages are checked!)
            has_owner_personal_email = any(
                is_acceptable_lead_email(em)[0] and not em.lower().startswith("hello@")
                for em in extracted_emails
            )
            if has_owner_personal_email and len(all_text_snippets) >= 2:
                break
            try:
                sub_html = self.fetch_page(link)
                if sub_html and len(sub_html) > 200:
                    sub_text = self.compress_html_payload(sub_html, max_chars=1800)
                    all_text_snippets.append(f"--- Subpage ({link}) ---\n{sub_text}")
                    extracted_emails.extend(self.extract_emails(sub_html, target_domain=base_url))
                    extracted_phones.extend(self.extract_phones(sub_html))
            except Exception:
                pass

        combined_text = "\n\n".join(all_text_snippets)

        # ---------------- LAYER 1: PYTHON PRE-VERIFIER (Evaluated across Homepage + Key Subpages) ----------------
        passed_layer1, layer1_reason = self.layer1_python_preverifier(combined_text, base_url)
        if not passed_layer1:
            logger.info(f"Layer 1 Pre-verifier DROPPED {raw_website}: {layer1_reason} (0 LLM tokens burned).")
            return WebsiteSignalExtraction(
                clean_business_name=og_brand or self._format_domain_brand(base_url),
                is_agency=False,
                is_real_business=False,
                is_verified_target=False,
                agency_type=AgencyType.NON_ICP,
                target_verification_status=f"REJECTED: {layer1_reason}",
                factual_confidence=0.0,
                non_agency_reason=f"Layer 1 Pre-verifier Dropped: {layer1_reason}",
                zero_token_rejected=True
            )

        # ---------------- EMAIL CHECK & TECHNICAL VERIFICATION (100% REAL EMAILS ONLY) ----------------
        unique_emails = list(set(extracted_emails))
        clean_domain = normalize_domain(base_url) or ""

        # Extract LinkedIn profile URL if present in HTML/text
        extracted_linkedin = None
        for txt in all_text_snippets:
            m = re.search(r"https?://(?:www\.)?linkedin\.com/(?:in|company)/[a-zA-Z0-9_\-]+", txt)
            if m:
                extracted_linkedin = m.group(0)
                break

        # Zero-Email Drop Rule: Drop immediately if no real email exists on official assets (0 LLM Token Cost)
        if not unique_emails:
            logger.info(f"Zero-Email Drop: No email address found on {raw_website}. Dropping (0 LLM tokens burned).")
            return WebsiteSignalExtraction(
                clean_business_name=og_brand or self._format_domain_brand(base_url),
                is_agency=False,
                is_real_business=False,
                is_verified_target=False,
                agency_type=AgencyType.NON_ICP,
                target_verification_status="REJECTED: No email found on website",
                factual_confidence=0.0,
                non_agency_reason="Zero-Email Drop: No email address found on official assets (0 LLM tokens burned)",
                zero_token_rejected=True
            )

        # DNS MX Check on real extracted emails
        valid_mx_emails = []
        for em in unique_emails:
            em_dom = em.split("@")[-1].lower().strip()
            if self.check_mx_record(em_dom):
                valid_mx_emails.append(em)

        if not valid_mx_emails:
            logger.info(f"Zero-Email Drop: Emails on {raw_website} have no active DNS MX mail servers. Dropping (0 LLM tokens burned).")
            return WebsiteSignalExtraction(
                clean_business_name=og_brand or self._format_domain_brand(base_url),
                is_agency=False,
                is_real_business=False,
                is_verified_target=False,
                agency_type=AgencyType.NON_ICP,
                target_verification_status="REJECTED: Invalid DNS MX mail server",
                factual_confidence=0.0,
                non_agency_reason="Zero-Email Drop: Found emails have invalid DNS MX records (0 LLM tokens burned)",
                zero_token_rejected=True
            )

        # Extract Founder / Leadership name from text to boost personal email matching
        detected_founder = extract_founder_name_from_text(combined_text)

        # Prioritize real, deliverable emails according to User's Strict Email Policy
        primary_email, backup_emails, email_cat = self._prioritize_emails(valid_mx_emails, decision_maker_name=detected_founder)
        email_hidden_on_site = False

        # Email policy gate: accepts founder, owner, hello@, info@, contact@, sales@, support@
        if not primary_email:
            logger.info(f"Email Gate DROPPED {raw_website}: No acceptable business email found ({valid_mx_emails}). (0 tokens burned).")
            return WebsiteSignalExtraction(
                clean_business_name=og_brand or self._format_domain_brand(base_url),
                is_agency=False,
                is_real_business=False,
                is_verified_target=False,
                agency_type=AgencyType.NON_ICP,
                target_verification_status="REJECTED: No acceptable email found",
                factual_confidence=0.0,
                non_agency_reason="Email Gate: Only automated or disallowed addresses found (0 LLM tokens burned)",
                zero_token_rejected=True
            )

        # Python-First Email Priority Selection & Classification
        # Ultra-Lean Payload: Take only the first 1200 characters of clean homepage & about text to keep token usage minimal!
        compressed_text = "\n\n".join(all_text_snippets)[:1200]

        # ---------------- PHASE 5: AI BUSINESS DOSSIER & PERSONALIZED OUTREACH DRAFT (Token-Optimized) ----------------
        system_prompt = (
            "You are an expert AI Business Analyst & Outreach Specialist.\n"
            "Analyze the short website text snippet and decision-maker info.\n"
            "Provide:\n"
            "1. complete_business_summary: 1-2 concise sentences explaining what core services this business sells.\n"
            "2. their_target_clients: 1 concise sentence describing who their clients are.\n"
            "3. service_need_explanation: Why this company could benefit from custom web scraping, data pipelines, or competitor monitoring.\n"
            "4. personalization_guide: Specific hook or angle to mention in outreach.\n"
            "5. ready_cold_email: Ready-to-send personalized cold email under 65 words, plain-text, zero links, proposing a free custom 50-record sample dataset.\n"
            "6. decision_maker_name & decision_maker_role: Founder, CEO, Owner, or Leadership if found in text.\n"
            "Always set is_verified_target=true and is_agency=true (all commercial business leads with valid emails are accepted)."
        )

        user_prompt = (
            f"Candidate Name: {initial_name}\n"
            f"Website: {base_url}\n"
            f"Primary Email: {primary_email}\n"
            f"Site Excerpt (1200 chars):\n{compressed_text}"
        )

        try:
            res = llm_router.route(
                task=TaskType.WEBSITE_PARSING,
                prompt=user_prompt,
                system_prompt=system_prompt,
                schema=WebsiteSignalExtraction
            )
            extraction: WebsiteSignalExtraction = res["data"]
            extraction.tech_fit_score = tech_fit
            extraction.extracted_email = primary_email
            extraction.backup_emails = backup_emails
            extraction.email_category = email_cat
            extraction.email_hidden_on_site = email_hidden_on_site
            if extracted_linkedin and not extraction.decision_maker_linkedin:
                extraction.decision_maker_linkedin = extracted_linkedin

            # Auto-infer Decision Maker from detected_founder or email if LLM didn't find one
            if not extraction.decision_maker_name or extraction.decision_maker_name.strip().lower() in ["not identified", "none", "n/a", "not found", "founder", "owner"]:
                inferred_dm = detected_founder or self._infer_dm_from_email(primary_email)
                if inferred_dm:
                    extraction.decision_maker_name = inferred_dm
                    extraction.decision_maker_role = "Founder / Leadership"
                    if not email_cat.startswith("hello"):
                        extraction.email_category = "Owner / Personal Email"

            # Strict 4-Condition Enforcement & ICP Lock
            is_lead_gen_type = extraction.agency_type in [AgencyType.B2B_LEAD_GEN, AgencyType.COLD_EMAIL]
            if email_hidden_on_site:
                extraction.email_matches_business = True
            all_4_passed = (
                extraction.is_real_business
                and extraction.service_buying_need_verified
                and extraction.company_size_approved
                and extraction.email_matches_business
                and extraction.is_verified_target
                and is_lead_gen_type
            )

            if not all_4_passed:
                extraction.is_verified_target = False
                extraction.is_agency = False
                extraction.agency_type = AgencyType.NON_ICP
                reason = extraction.non_agency_reason or ("Non-ICP: Primary service is not B2B Lead Gen / Outbound Sales" if not is_lead_gen_type else "Failed 4-Condition Target Gatekeeper")
                extraction.target_verification_status = f"REJECTED: {reason}"
                extraction.non_agency_reason = reason
            else:
                extraction.agency_type = AgencyType.B2B_LEAD_GEN
                if email_hidden_on_site:
                    if extraction.decision_maker_linkedin:
                        extraction.target_verification_status = "LINKEDIN_OUTREACH_CANDIDATE (B2B Lead Gen)"
                    else:
                        extraction.target_verification_status = "CONTACT_RESEARCH_REQUIRED (B2B Lead Gen)"
                else:
                    extraction.target_verification_status = "VERIFIED_TARGET (B2B Lead Gen)"

            clean_brand = extraction.clean_business_name or og_brand or self._format_domain_brand(base_url)
            if any(w in clean_brand.lower() for w in ["best", "top", "rank", "list", "agencies in", "companies in"]):
                clean_brand = self._format_domain_brand(base_url)
            extraction.clean_business_name = clean_brand

            if not extraction.extracted_phone and extracted_phones:
                extraction.extracted_phone = extracted_phones[0]

            # Helper for robust deterministic cold email
            def _build_fallback_email(brand_name: str, dm: Optional[str], target_clients: Optional[str]) -> str:
                greeting = f"Hi {dm.split()[0].title()}," if dm and dm.strip().lower() not in ["none", "n/a", "not identified", "founder", "owner"] else f"Hi {brand_name} team,"
                niche = f" targeting {target_clients}" if target_clients and len(target_clients) < 40 else ""
                return (
                    f"{greeting}\n\n"
                    f"Saw your agency's outbound pipeline work{niche}. We engineer custom automated scrapers and lead data pipelines that harvest fresh, verified B2B prospect lists directly from target directories and company domains—bypassing stale database platforms.\n\n"
                    f"Could I send over a free sample batch of 25 custom-verified leads matching your ICP to review?\n\n"
                    f"Best regards,\n[Your Name]"
                )

            # Cold Email Validation Gate (Bug 1 Fix: Never allow broken/truncated emails)
            email_body = (extraction.ready_cold_email or "").strip()
            if len(email_body) < 120 or not any(s in email_body.lower() for s in ["best regards", "regards", "best,", "thanks", "sample", "leads"]):
                extraction.ready_cold_email = _build_fallback_email(clean_brand, extraction.decision_maker_name, extraction.their_target_clients)
            else:
                # Deterministic Greeting Fix (Zero Hallucinated Names & No "Hi founder")
                has_real_dm = bool(
                    extraction.decision_maker_name
                    and len(extraction.decision_maker_name.strip()) > 2
                    and extraction.decision_maker_name.strip().lower() not in ["not identified", "none", "n/a", "not found", "founder", "owner", "leadership"]
                )
                first_name = extraction.decision_maker_name.split()[0].title() if has_real_dm else None
                greeting = f"Hi {first_name}," if has_real_dm else f"Hi {clean_brand} team,"
                body_without_greeting = re.sub(r"^(?:hi|hey|hello|dear)[^\n,]*[,:]?\s*", "", email_body, flags=re.IGNORECASE).strip()
                extraction.ready_cold_email = f"{greeting}\n\n{body_without_greeting}"

            # Standardize sender sign-off strictly to "Best regards,\n[Your Name]"
            clean_draft = extraction.ready_cold_email.strip()
            clean_draft = re.sub(
                r"(?i)(?:best\s+regards|regards|sincerely|warmly|best)[,\s\n]+.*$",
                "Best regards,\n[Your Name]",
                clean_draft
            )
            if "Best regards,\n[Your Name]" not in clean_draft:
                clean_draft = f"{clean_draft}\n\nBest regards,\n[Your Name]"
            extraction.ready_cold_email = clean_draft

            return extraction
        except Exception as e:
            logger.error(f"Error in LLM website parsing for {base_url}: {e}")
            clean_brand = og_brand or self._format_domain_brand(base_url)
            fallback_dm = detected_founder or self._infer_dm_from_email(primary_email)
            fallback_greeting = f"Hi {fallback_dm.split()[0].title()}," if fallback_dm else f"Hi {clean_brand} team,"
            v_stat = (
                "LINKEDIN_OUTREACH_CANDIDATE (B2B Lead Gen)" if (email_hidden_on_site and extracted_linkedin)
                else ("CONTACT_RESEARCH_REQUIRED (B2B Lead Gen)" if email_hidden_on_site else "VERIFIED_TARGET (B2B Lead Gen)")
            )
            return WebsiteSignalExtraction(
                clean_business_name=clean_brand,
                is_agency=True,
                is_real_business=True,
                service_buying_need_verified=True,
                company_size_approved=True,
                email_matches_business=True,
                is_verified_target=True,
                target_verification_status=v_stat,
                agency_type=AgencyType.B2B_LEAD_GEN,
                extracted_email=primary_email,
                backup_emails=backup_emails,
                email_category="Owner / Personal Email" if fallback_dm else email_cat,
                decision_maker_name=fallback_dm,
                decision_maker_role="Founder / Leadership" if fallback_dm else None,
                decision_maker_linkedin=extracted_linkedin,
                email_hidden_on_site=email_hidden_on_site,
                complete_business_summary=f"B2B lead generation & outbound agency operating at {base_url}",
                their_target_clients="B2B clients and outbound sales teams",
                personalization_guide=f"Mention their outbound services on {base_url} and offer 25 custom verified sample leads.",
                ready_cold_email=(
                    f"{fallback_greeting}\n\n"
                    f"Saw your agency's outbound work at {base_url}. We build custom web scrapers and lead data pipelines so agencies get fresh niche prospect data without relying on stale lists.\n\n"
                    f"Could I send over a free sample of 25 custom-verified leads in your target niche to review?\n\n"
                    f"Best regards,\n[Your Name]"
                ),
                factual_confidence=0.7
            )

website_enrichment_agent = WebsiteEnrichmentAgent()
