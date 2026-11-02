import logging
import re
from datetime import datetime, timezone
from typing import Tuple, Optional
import dns.resolver
import phonenumbers

from core.schemas import LeadRecord, VerificationStatus
from adapters.website_enrichment import GENERIC_EMAIL_PREFIXES

logger = logging.getLogger("LeadVerifier")

GENERIC_ROLE_PREFIXES = GENERIC_EMAIL_PREFIXES

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

class LeadVerifier:
    def __init__(self, dns_timeout: float = 3.0):
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = ["8.8.8.8", "1.1.1.1"]
        self.resolver.timeout = dns_timeout
        self.resolver.lifetime = dns_timeout

    def verify_email_syntax(self, email: str) -> bool:
        if not email or "@" not in email:
            return False
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        return bool(re.match(pattern, email.strip()))

    def is_personal_email(self, email: str) -> bool:
        if not email or "@" not in email:
            return False
        local_part = email.split("@")[0].lower().strip()
        return local_part not in GENERIC_ROLE_PREFIXES

    def verify_mx_records(self, domain: str) -> bool:
        clean_domain = domain.strip().lower()
        if clean_domain.startswith("www."):
            clean_domain = clean_domain[4:]
        try:
            answers = self.resolver.resolve(clean_domain, "MX")
            return len(answers) > 0
        except Exception:
            try:
                # Fallback to A record if no explicit MX
                answers = self.resolver.resolve(clean_domain, "A")
                return len(answers) > 0
            except Exception:
                return False

    def verify_email_mx(self, domain_or_email: str) -> VerificationStatus:
        if not domain_or_email:
            return VerificationStatus.UNKNOWN
        domain = domain_or_email.split("@")[-1].strip().lower()
        if domain.startswith("www."):
            domain = domain[4:]
        has_mx = self.verify_mx_records(domain)
        return VerificationStatus.LIKELY_VALID if has_mx else VerificationStatus.INVALID

    def _is_domain_match(self, email_dom: Optional[str], target_dom: Optional[str]) -> bool:
        if not email_dom or not target_dom:
            return False
        from pipeline.normalizer import normalize_domain
        e = normalize_domain(email_dom)
        t = normalize_domain(target_dom)
        if not e or not t:
            return False
        if e == t or e.endswith("." + t):
            return True
        e_brand = e.split(".")[0]
        t_brand = t.split(".")[0]
        if len(t_brand) >= 4 and e_brand == t_brand:
            return True
        return False

    def verify_email(self, email: Optional[str], target_website: Optional[str] = None) -> Tuple[VerificationStatus, bool]:
        """
        Returns (VerificationStatus, is_personal).
        Strict Rule: MX match gives LIKELY_VALID, never VERIFIED.
        Blocks placeholder domains, HR/legal prefixes, and third-party domain mismatch.
        """
        if not email or "@" not in email:
            return VerificationStatus.UNKNOWN, False
        if not self.verify_email_syntax(email):
            return VerificationStatus.INVALID, False

        local_part, domain = email.strip().lower().split("@", 1)

        # 1. Block placeholder domains
        if domain in PLACEHOLDER_DOMAINS or any(p in domain for p in ["example.com", "sentry.io", "wixpress.com", "domain.com", ".png", ".jpg"]):
            return VerificationStatus.INVALID, False

        # 2. Block non-sales / HR / legal prefixes
        if local_part in BLOCKED_EMAIL_PREFIXES:
            return VerificationStatus.INVALID, False

        # 3. Strict Domain Match
        if target_website:
            if not self._is_domain_match(domain, target_website):
                return VerificationStatus.INVALID, False

        has_mx = self.verify_mx_records(domain)
        is_personal = self.is_personal_email(email)

        if has_mx:
            return VerificationStatus.LIKELY_VALID, is_personal
        else:
            return VerificationStatus.INVALID, is_personal

    def verify_phone(self, phone: Optional[str], default_region: str = "US") -> VerificationStatus:
        if not phone:
            return VerificationStatus.UNKNOWN
        try:
            parsed = phonenumbers.parse(phone, default_region)
            if phonenumbers.is_valid_number(parsed):
                return VerificationStatus.VERIFIED
            return VerificationStatus.INVALID
        except Exception:
            return VerificationStatus.INVALID

    def verify_decision_maker(self, lead: LeadRecord) -> bool:
        """
        Verifies that decision-maker has accompanying evidence (URL, snippet, or LinkedIn profile).
        Zero-trust: Name without any verifiable snippet, URL, or LinkedIn evidence is rejected.
        """
        if not lead.decision_maker_name or len(lead.decision_maker_name.strip()) < 3:
            return False
        if lead.decision_maker_linkedin:
            return True
        evidence = lead.evidence or {}
        dm_ev = evidence.get("decision_maker_name") or evidence.get("decision_maker")
        if dm_ev:
            if isinstance(dm_ev, dict) and (dm_ev.get("snippet") or dm_ev.get("url")):
                return True
            if isinstance(dm_ev, str) and len(dm_ev) > 2:
                return True
        return False

    def verify_lead(self, lead: LeadRecord) -> LeadRecord:
        # 1. Strictly verify real found email with target domain matching
        if lead.email and str(lead.email).strip().lower() not in ["", "none", "nan", "null"]:
            st, is_pers = self.verify_email(lead.email, target_website=lead.website)
            lead.email_verification_status = st
            lead.email_mx_status = st
            if st == VerificationStatus.LIKELY_VALID:
                lead.verified_email = lead.email
            else:
                lead.verified_email = None
            if is_pers and "is_personal_email" not in lead.evidence:
                lead.evidence["is_personal_email"] = True
        else:
            # When email is missing, email status is UNKNOWN (NEVER LIKELY_VALID)
            lead.email_verification_status = VerificationStatus.UNKNOWN
            lead.email_mx_status = VerificationStatus.UNKNOWN
            lead.verified_email = None
            lead.email_mx_status = VerificationStatus.UNKNOWN
            lead.verified_email = None

        # 3. Verify phone
        if lead.phone:
            lead.phone_verification_status = self.verify_phone(lead.phone)
        else:
            lead.phone_verification_status = VerificationStatus.UNKNOWN

        # 4. Decision-maker verification & LinkedIn enrichment check
        has_dm_proof = self.verify_decision_maker(lead)
        if lead.decision_maker_name and not has_dm_proof:
            logger.warning(f"Decision maker '{lead.decision_maker_name}' for {lead.business_name} lacks verifiable evidence; clearing per zero-trust rule.")
            lead.decision_maker_name = None
            lead.decision_maker_role = None
        elif lead.decision_maker_name and not lead.decision_maker_linkedin:
            try:
                from ddgs import DDGS
                ddgs = DDGS()
                res = list(ddgs.text(f'"{lead.decision_maker_name}" "{lead.business_name}" site:linkedin.com/in', max_results=2, backend="duckduckgo,brave,yahoo"))
                for r in res:
                    href = r.get("href", "")
                    if "linkedin.com/in/" in href:
                        lead.decision_maker_linkedin = href
                        break
            except Exception:
                pass

        lead.last_verified_at = datetime.now(timezone.utc)
        return lead

lead_verifier = LeadVerifier()
