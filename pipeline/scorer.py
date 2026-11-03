import logging
from typing import Tuple, List, Optional
from core.schemas import (
    LeadRecord, AgencyType, VerificationStatus, PriorityTier,
    LeadClassification, EmailType
)
from adapters.website_enrichment import GENERIC_EMAIL_PREFIXES

logger = logging.getLogger("ScorerV2")

class ScrapingBuyerScorerV2:
    """
    Evidence-driven 100-Point Lead Qualification Model:
    Prioritizes:
    1. Targeted Company / ICP Fit (Max 30)
    2. Lead Need / Data Dependency Signals (Max 20)
    3. Company Size Sweet Spot (Max 15):
       - 2-10 employees: Highest value (15 pts) - Boutique, agile agency, owner-operated
       - 10-50 employees: Medium value (12 pts)
       - 50-200 employees: Lower value (8 pts, accepted)
       - 200+ employees: Enterprise (5 pts, accepted)
    4. Buying Intent (Max 20)
    5. Decision-Maker (Max 10) - LinkedIn is optional, no penalty if missing
    6. Contactability / Email Deliverability (Max 5) - Strictly email focused, phone is optional
    Total Score: 100 Points
    """

    def __init__(self):
        self.max_service_fit = 30
        self.max_data_dependency = 20
        self.max_scale_automation = 15
        self.max_buying_intent = 20
        self.max_decision_maker = 10
        self.max_contactability = 5

    def calculate_service_fit_score(self, agency_type: AgencyType, core_services: List[str]) -> Tuple[int, str]:
        """
        Factor A: Targeted Company & Service Fit (Max 30 Points)
        Accepts all commercial service agencies and data buyers (25-30 pts).
        """
        services_str = " ".join(core_services).lower()
        base = 28
        if any(term in services_str for term in ["prospecting", "cold email", "lead generation", "appointment setting", "ecommerce", "seo", "scraping", "data"]):
            base = 30
        return base, f"Commercial business / agency service fit ({base}/30)"

    def calculate_data_dependency_score(self, agency_type: AgencyType, signals: List[str], text_evidence: str = "") -> Tuple[int, str]:
        """
        Factor B: Data Dependency & Lead Need Signals (Max 20 Points)
        Evaluates signals that the company needs leads, prospect lists, directory scraping, or web data extraction.
        """
        score = 0
        reasons = []

        # Baseline based on agency core offering
        if agency_type in (AgencyType.COLD_EMAIL, AgencyType.B2B_LEAD_GEN):
            score += 14
            reasons.append("Outbound lead generation intrinsically requires continuous prospect lists (+14)")
        elif agency_type in (AgencyType.LOCAL_SEO, AgencyType.DATA_RESEARCH):
            score += 12
            reasons.append("Local SEO & data research operations require recurring directory and map data feeds (+12)")
        elif agency_type in (AgencyType.DIGITAL_MARKETING, AgencyType.RECRUITING):
            score += 8
            reasons.append("Agency relies on business discovery and prospect datasets (+8)")

        # Explicit lead / scraping need signals
        combined = (text_evidence + " " + " ".join(signals)).lower()
        lead_need_keywords = [
            "lead", "leads", "prospect", "prospecting", "scraping", "apollo",
            "linkedin", "list building", "directory", "enrichment", "database",
            "outbound", "email list", "b2b list"
        ]
        found = [k for k in lead_need_keywords if k in combined]
        if len(found) >= 2:
            score += 6
            reasons.append(f"Observed lead need markers: {', '.join(found[:3])} (+6)")
        elif len(found) == 1:
            score += 4
            reasons.append(f"Observed lead need marker: {found[0]} (+4)")

        final_score = min(self.max_data_dependency, score)
        return final_score, "; ".join(reasons) if reasons else "Moderate data dependency (8/20)"

    def calculate_company_size_score(self, company_size: Optional[str], scale_signals: List[str] = None) -> Tuple[int, str]:
        """
        Factor C: Company Size Sweet Spot & Scale (Max 15 Points)
        2-10 employees: 15 pts (Highest value! Boutique, agile agency, owner-operated, fast decision-makers)
        10-50 employees: 12 pts (Medium-high value)
        50-200 employees: 8 pts (Moderate value, accepted)
        200+ employees: 5 pts (Enterprise, accepted)
        Default / Small agency: 13 pts
        """
        raw = (company_size or "2-10").strip().lower()
        if any(term in raw for term in ["2-10", "1-10", "2 - 10", "2-9", "2 - 9", "small", "boutique", "1-9"]):
            return 15, "Company Size: 2-10 employees (Highest value boutique agency) (15/15)"
        elif any(term in raw for term in ["10-50", "11-50", "10 - 49", "10 - 50", "medium"]):
            return 12, "Company Size: 10-50 employees (Strong agency size) (12/15)"
        elif any(term in raw for term in ["50-200", "51-200", "50 - 249", "50-249"]):
            return 8, "Company Size: 50-200 employees (Larger agency, accepted) (8/15)"
        elif any(term in raw for term in ["200+", "250+", "500+", "1000+"]):
            return 5, "Company Size: 200+ employees (Enterprise agency, accepted) (5/15)"
        return 13, f"Company Size: {company_size or '2-10'} (Standard small agency) (13/15)"

    def calculate_buying_intent_score(self, agency_type: AgencyType, signals: List[str], text_evidence: str = "") -> Tuple[int, str]:
        """
        Factor D: Buying Intent (Max 20 Points)
        Active client prospecting campaigns or list building indicates high commercial buying intent.
        """
        score = 0
        reasons = []

        if agency_type in (AgencyType.COLD_EMAIL, AgencyType.B2B_LEAD_GEN):
            score += 12
            reasons.append("Running active client cold email campaigns creates perpetual demand for fresh scraped leads (+12)")
        elif agency_type in (AgencyType.LOCAL_SEO, AgencyType.DATA_RESEARCH):
            score += 8
            reasons.append("Continuous local audit and ranking tracker demand (+8)")

        combined = text_evidence.lower()
        intent_terms = ["custom leads", "hiring data", "lead mining", "scraping", "prospect list building", "list building", "cold email", "appointment setting"]
        matches = [t for t in intent_terms if t in combined]
        if len(matches) >= 2:
            score += 8
            reasons.append(f"Direct operational indicators: {', '.join(matches[:2])} (+8)")
        elif len(matches) == 1:
            score += 5
            reasons.append(f"Operational indicator: {matches[0]} (+5)")

        final_score = min(self.max_buying_intent, score)
        return final_score, "; ".join(reasons) if reasons else "Standard agency commercial intent (6/20)"

    def calculate_decision_maker_score(self, lead: LeadRecord) -> Tuple[int, str]:
        """
        Factor E: Decision-Maker (Max 10 Points)
        LinkedIn is purely optional - no penalty if missing!
        10 pts: Founder, Owner, CEO, Managing Director, Partner identified.
        7 pts: Head of Growth / Operations / Sales identified.
        5 pts: General team / leadership inferred from official company assets.
        """
        if not lead.decision_maker_name:
            return 5, "Leadership team inferred from official company assets (5/10)"

        role = (lead.decision_maker_role or "Founder/CEO").title()
        if any(t in role.lower() for t in ["founder", "ceo", "owner", "president", "partner", "managing director", "principal"]):
            return 10, f"Identified decision-maker: {lead.decision_maker_name} ({role}) (10/10)"
        return 8, f"Identified agency leader: {lead.decision_maker_name} ({role}) (8/10)"

    def calculate_contactability_score(self, lead: LeadRecord) -> Tuple[int, str]:
        """
        Factor F: Contactability / Email Focus (Max 5 Points)
        The user outreaches strictly via Email. Phone and LinkedIn are purely optional.
        5 pts: Deliverable verified email (MX verified / likely valid).
        3 pts: Email found on site.
        0 pts: No email found.
        """
        target_email = lead.verified_email or lead.email
        mx_status = lead.email_mx_status if lead.email_mx_status != VerificationStatus.UNKNOWN else lead.email_verification_status

        if target_email and mx_status in (VerificationStatus.LIKELY_VALID, VerificationStatus.VERIFIED):
            return 5, f"Deliverable verified email: {target_email} (5/5)"
        elif target_email:
            return 3, f"Email found on agency assets: {target_email} (3/5)"
        return 0, "No email address found on agency assets (0/5)"

    def _determine_email_type(self, email: Optional[str], decision_maker_name: Optional[str]) -> EmailType:
        if not email or "@" not in email:
            return EmailType.GENERIC_BUSINESS
        clean_email = email.strip().lower()
        local = clean_email.split("@")[0].strip()
        if local in GENERIC_EMAIL_PREFIXES:
            return EmailType.GENERIC_BUSINESS
        
        # Check if email contains part of the decision-maker name
        if decision_maker_name:
            dm_parts = [p.lower() for p in decision_maker_name.split() if len(p) >= 2]
            if dm_parts and any(p in local for p in dm_parts):
                return EmailType.PERSONAL_PROFESSIONAL

        if "." in local or "_" in local:
            return EmailType.PERSONAL_PROFESSIONAL
        return EmailType.GENERIC_BUSINESS

    def calculate_agency_opportunity_score(self, lead: LeadRecord) -> Tuple[int, str, List[str], dict]:
        """
        Agency Opportunity Detection Engine (Buying Likelihood for Custom Scraping & Data Pipelines)
        Evaluates 5 critical factors:
        1. Multi-Client Lead Generation (Max 25 pts)
        2. Cross-Industry Prospect Research (Max 20 pts)
        3. Custom Data Collection & List Building Offering (Max 20 pts)
        4. Internal Research Team / Manual Data Bottleneck (Max 20 pts)
        5. Recurring Fresh Data Source Need (Max 15 pts)
        Total: 100 Points
        """
        score = 0
        signals: List[str] = []
        breakdown: dict = {}

        combined_text = " ".join([
            lead.business_name or "",
            lead.complete_business_summary or "",
            lead.their_target_clients or "",
            " ".join(lead.core_services or []),
            " ".join(lead.client_industries_served or []),
            " ".join(lead.data_dependency_signals or []),
            lead.evidence.get("snippet", "") if isinstance(lead.evidence, dict) else ""
        ]).lower()

        # Factor 1: Multi-Client Lead Generation (Max 25 pts)
        multi_client_terms = [
            "our clients", "for clients", "client pipeline", "client growth",
            "b2b companies", "sdr as a service", "outsourced sdr", "outsourced sales",
            "appointment setting for", "lead generation for", "done-for-you", "dfy outbound"
        ]
        is_multi_client = any(t in combined_text for t in multi_client_terms) or lead.agency_type in (AgencyType.B2B_LEAD_GEN, AgencyType.COLD_EMAIL)
        if is_multi_client:
            f1_score = 25
            signals.append("Multi-Client Operations: Manages outbound campaigns & prospect lists across multiple client accounts (+25)")
        else:
            f1_score = 10
            signals.append("Single-Account Focus: Primarily self-sourcing or limited client accounts (+10)")
        score += f1_score
        breakdown["multi_client_leadgen"] = f1_score

        # Factor 2: Cross-Industry Prospect Research (Max 20 pts)
        distinct_industries = len(lead.client_industries_served) if lead.client_industries_served else 0
        cross_industry_terms = ["saas", "healthcare", "real estate", "logistics", "fintech", "ecommerce", "manufacturing", "construction", "professional services"]
        matched_industries = [ind for ind in cross_industry_terms if ind in combined_text]
        if distinct_industries >= 2 or len(matched_industries) >= 2:
            f2_score = 20
            signals.append(f"Cross-Industry Prospecting: Sourcing leads across diverse verticals ({', '.join(matched_industries[:3])}) (+20)")
        elif distinct_industries == 1 or len(matched_industries) == 1:
            f2_score = 12
            signals.append(f"Single-Niche Focus: Dedicated prospect research for {matched_industries[0] if matched_industries else 'one vertical'} (+12)")
        else:
            f2_score = 8
            signals.append("General B2B Prospecting (+8)")
        score += f2_score
        breakdown["cross_industry_research"] = f2_score

        # Factor 3: Custom Data Collection & List Building Offering (Max 20 pts)
        custom_data_terms = [
            "list building", "prospect list", "contact list", "custom data", "scraping",
            "account mapping", "prospect research", "tam analysis", "directory",
            "database enrichment", "lead mining", "verified leads"
        ]
        matched_data = [t for t in custom_data_terms if t in combined_text]
        if len(matched_data) >= 2:
            f3_score = 20
            signals.append(f"Custom Data Offering: Directly sells bespoke list building & prospect data ({', '.join(matched_data[:2])}) (+20)")
        elif len(matched_data) == 1:
            f3_score = 12
            signals.append(f"List Building Service: Mentions {matched_data[0]} (+12)")
        else:
            f3_score = 5
            signals.append("Standard Outbound Outreach (+5)")
        score += f3_score
        breakdown["custom_data_offering"] = f3_score

        # Factor 4: Internal Research Team / Manual Data Bottleneck (Max 20 pts)
        research_team_terms = [
            "research team", "researchers", "list builders", "prospecting specialists",
            "sdr team", "data analysts", "manual verification", "human-verified",
            "hand-curated", "manual qa", "virtual assistant"
        ]
        matched_team = [t for t in research_team_terms if t in combined_text]
        is_boutique = any(s in (lead.company_size or "") for s in ["2-10", "10-50", "boutique", "small"])
        if matched_team:
            f4_score = 20
            signals.append(f"Data Labor Bottleneck: Relies on manual list research ({', '.join(matched_team[:2])}) - prime candidate for scraping automation (+20)")
        elif is_boutique and is_multi_client:
            f4_score = 15
            signals.append("Agile Outbound Team: Boutique agency managing multiple client campaigns without large enterprise data budgets (+15)")
        else:
            f4_score = 10
            signals.append("Standard Research Capacity (+10)")
        score += f4_score
        breakdown["research_team_bottleneck"] = f4_score

        # Factor 5: Recurring Fresh Data Source Need (Max 15 pts)
        recurring_terms = [
            "monthly", "per month", "weekly", "campaigns", "cold email", "scale",
            "deliverability", "inbox", "warmup", "continuous", "ongoing pipeline"
        ]
        matched_recurring = [t for t in recurring_terms if t in combined_text]
        if len(matched_recurring) >= 2 or lead.agency_type == AgencyType.COLD_EMAIL:
            f5_score = 15
            signals.append("Continuous Fresh Data Need: Active cold email & outbound engines requiring perpetual fresh leads to prevent domain burns (+15)")
        elif len(matched_recurring) == 1:
            f5_score = 10
            signals.append("Periodic Lead Replenishment Need (+10)")
        else:
            f5_score = 5
            signals.append("Baseline Outbound Need (+5)")
        score += f5_score
        breakdown["recurring_data_need"] = f5_score

        final_opp_score = min(100, max(0, score))

        if final_opp_score >= 88:
            tier = "CRITICAL ICP FIT (Prime Buyer for Scraping & Pipelines)"
        elif final_opp_score >= 75:
            tier = "HIGH OPPORTUNITY (Strong Data Buyer Demand)"
        elif final_opp_score >= 55:
            tier = "MODERATE OPPORTUNITY (Potential Scraping Prospect)"
        else:
            tier = "LOW OPPORTUNITY (Limited Data Dependency)"

        return final_opp_score, tier, signals, breakdown

    def score_lead(self, lead: LeadRecord) -> LeadRecord:
        explanations: List[str] = []

        # 1. Non-ICP hard rejection (Strict ICP Lock)
        if lead.agency_type not in (AgencyType.COLD_EMAIL, AgencyType.B2B_LEAD_GEN) or lead.agency_type == AgencyType.NON_ICP:
            lead.service_fit_score = 0
            lead.data_dependency_score = 0
            lead.scale_automation_score = 0
            lead.buying_intent_score = 0
            lead.decision_maker_score = 0
            lead.contactability_score = 0
            lead.company_size_score = 0
            lead.total_score = 0
            lead.opportunity_score = 0
            lead.overall_priority = PriorityTier.REJECTED
            lead.lead_classification = LeadClassification.REJECTED
            if not lead.rejection_reason:
                lead.rejection_reason = f"Non-ICP category ({lead.agency_type.value if hasattr(lead.agency_type, 'value') else lead.agency_type}): Only B2B Lead Gen & Outbound Sales accepted."
            lead.target_verification_status = f"REJECTED: {lead.rejection_reason}"
            lead.score_explanation = [lead.rejection_reason]
            return lead

        # 2. Compute 6-Factor Model (Aligned with User Focus)
        evidence_text = f"{lead.business_name} {' '.join(lead.core_services)} {lead.evidence.get('snippet', '')}"
        
        s_fit, exp_fit = self.calculate_service_fit_score(lead.agency_type, lead.core_services)
        s_data, exp_data = self.calculate_data_dependency_score(lead.agency_type, lead.data_dependency_signals, evidence_text)
        s_size, exp_size = self.calculate_company_size_score(lead.company_size, lead.scale_signals)
        s_intent, exp_intent = self.calculate_buying_intent_score(lead.agency_type, lead.data_dependency_signals, evidence_text)
        s_dm, exp_dm = self.calculate_decision_maker_score(lead)
        s_contact, exp_contact = self.calculate_contactability_score(lead)

        total = s_fit + s_data + s_size + s_intent + s_dm + s_contact
        total = max(0, min(100, total))

        lead.service_fit_score = s_fit
        lead.data_dependency_score = s_data
        lead.company_size_score = s_size
        lead.scale_automation_score = s_size  # Aligned with 25-column schema column 8
        lead.buying_intent_score = s_intent
        lead.decision_maker_score = s_dm
        lead.contactability_score = s_contact
        lead.total_score = total
        lead.icp_fit_score = s_fit

        # 2.1 Calculate Dedicated Agency Opportunity Score (5 Buying Indicators)
        opp_score, opp_tier, opp_signals, opp_breakdown = self.calculate_agency_opportunity_score(lead)
        # If AI Judge previously evaluated opportunity score, blend with heuristic baseline
        if lead.opportunity_score and lead.opportunity_score > 0:
            lead.opportunity_score = max(lead.opportunity_score, opp_score)
        else:
            lead.opportunity_score = opp_score
        lead.opportunity_tier = opp_tier
        lead.opportunity_signals = opp_signals
        lead.opportunity_breakdown = opp_breakdown

        explanations.extend([exp_fit, exp_data, exp_size, exp_intent, exp_dm, exp_contact])
        explanations.extend([f"Opportunity Rating: {opp_tier} ({lead.opportunity_score}/100)"])
        lead.score_explanation = explanations

        # 3. Email Type Classification (Never output Unknown email type per Bug 4)
        active_email = lead.verified_email or lead.email
        lead.email_type = self._determine_email_type(active_email, lead.decision_maker_name)

        # 4. Evidence of Potential Need & Source URLs with Company Size
        size_label = lead.company_size or "2-10"
        services_text = ", ".join(lead.core_services[:2]) if lead.core_services else lead.agency_type.value
        lead.evidence_of_need = (
            f"[{size_label} team] {lead.business_name} specializes in {services_text}. "
            f"Delivering client campaigns requires recurring prospect research and web data extraction."
        )
        lead.evidence_source_urls = list(set([u for u in (lead.source_urls or []) if u]))

        # 5. Factual Confidence
        fact_conf = lead.factual_confidence or 0.70
        if lead.decision_maker_name and lead.email_mx_status in (VerificationStatus.LIKELY_VALID, VerificationStatus.VERIFIED):
            fact_conf = min(1.0, fact_conf + 0.15)
        lead.factual_confidence = round(fact_conf, 2)

        # 6. STRICT EMAIL HARD GATE (Bug 2 & Bug 4 Aligned)
        # Any verified ICP company with a valid MX-verified email promotes directly to Hot Lead!
        email_status = lead.email_mx_status
        if not email_status or email_status == VerificationStatus.UNKNOWN:
            email_status = lead.email_verification_status

        has_verified_email = bool(
            active_email
            and str(active_email).strip().lower() not in ["", "none", "nan", "null"]
            and "@" in str(active_email)
            and (
                email_status in (VerificationStatus.LIKELY_VALID, VerificationStatus.VERIFIED)
                or (bool(lead.verified_email) and email_status != VerificationStatus.INVALID)
            )
        )

        if has_verified_email:
            if not lead.verified_email:
                lead.verified_email = active_email
            # Verified ICP target with deliverable email -> Hot Lead!
            lead.overall_priority = PriorityTier.HOT_LEAD
            lead.lead_classification = LeadClassification.HOT_LEAD
            lead.recommended_outreach_channel = "email"
            cat = lead.agency_type.value if hasattr(lead.agency_type, "value") else str(lead.agency_type)
            clean_cat = cat.replace("_", " ").title()
            lead.target_verification_status = f"VERIFIED_TARGET ({clean_cat})"
        else:
            # Valid ICP company with ZERO valid emails found -> Contact Research Required (NEVER Hot Lead!)
            lead.overall_priority = PriorityTier.NEEDS_REVIEW
            lead.lead_classification = LeadClassification.CONTACT_RESEARCH_REQUIRED
            lead.recommended_outreach_channel = "manual_research"
            lead.verified_email = None
            if not lead.rejection_reason:
                lead.rejection_reason = "Contact research required: Missing deliverable email."
            lead.target_verification_status = "CONTACT_RESEARCH_REQUIRED"
            lead.score_explanation.append("Contact research required: Valid ICP business, but no deliverable email found.")

        return lead

ScrapingBuyerScorer = ScrapingBuyerScorerV2
scraping_buyer_scorer = ScrapingBuyerScorerV2()
