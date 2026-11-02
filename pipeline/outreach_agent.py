import logging
import re
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

from core.llm_router import llm_router, TaskType
from core.schemas import LeadRecord, AgencyType, OutreachStatus, PriorityTier, LeadClassification

logger = logging.getLogger("OutreachAgent")

class OutreachPitchGeneration(BaseModel):
    recommended_scraping_pitch: str = Field(description="Specific custom scraper or dataset pitch tailored to the agency's client niche")
    custom_outreach_hook: str = Field(description="Targeted zero-link pain point hook tailored to agency type")
    outreach_angle: str = Field(description="Evidence-backed observation or hook referencing their exact work")
    outreach_draft: str = Field(description="Value-first cold message under 75 words, plain-text, zero links, offering 25-50 free sample leads")

class OutreachAgent:
    def __init__(self):
        pass

    def _get_v2_standard_hook(self, agency_type: AgencyType) -> str:
        if agency_type in (AgencyType.COLD_EMAIL, AgencyType.B2B_LEAD_GEN):
            return "I can build custom APIs to scrape thousands of fresh, verified leads daily from Apollo/LinkedIn for your client campaigns."
        elif agency_type == AgencyType.LOCAL_SEO:
            return "I can automate scraping Yelp/GMB ranking data and reviews to feed your client reporting dashboards."
        elif agency_type == AgencyType.DIGITAL_MARKETING:
            return "I can set up automated competitor price tracking and out-of-stock monitoring pipelines for your clients."
        else:
            return "I can build automated custom data pipelines to collect fresh niche prospects and market signals directly from primary web sources."

    def _is_valid_email_body(self, draft: Optional[str]) -> bool:
        if not draft:
            return False
        clean = draft.strip()
        if len(clean) < 120:
            return False
        first_line = clean.split("\n")[0].lower()
        if not any(g in first_line for g in ["hi ", "hey ", "hello ", "dear "]):
            return False
        lower = clean.lower()
        if not any(k in lower for k in ["sample", "leads", "prospects", "pipeline", "scraper"]):
            return False
        return True

    def _fallback_pitch(self, lead: LeadRecord) -> OutreachPitchGeneration:
        niche = lead.client_industries_served[0] if lead.client_industries_served else "B2B companies"
        has_real_dm = bool(
            lead.decision_maker_name
            and len(lead.decision_maker_name.strip()) > 2
            and lead.decision_maker_name.strip().lower() not in ["not identified", "none", "n/a", "not found", "founder", "owner", "leadership"]
        )
        greeting = f"Hi {lead.decision_maker_name.split()[0].title()}," if has_real_dm else f"Hi {lead.business_name} team,"
        standard_hook = self._get_v2_standard_hook(lead.agency_type)
        
        pitch = f"Custom-scraped list of verified B2B decision-makers in {niche} with MX-checked emails not found on stale databases."
        angle = f"Noticed {lead.business_name} drives outbound campaigns and client acquisition for {niche}."
        draft = (
            f"{greeting}\n\n"
            f"Saw {lead.business_name}'s outbound work for {niche}. "
            f"We engineer bespoke web scrapers and automated lead data pipelines that extract fresh, verified decision-maker prospects directly from live company sites and directories—bypassing stale database platforms.\n\n"
            f"Could I send across a free sample of 25 custom-verified {niche} leads for your team to inspect?\n\n"
            f"Best regards,\nLead Data Specialist"
        )

        return OutreachPitchGeneration(
            recommended_scraping_pitch=pitch,
            custom_outreach_hook=standard_hook,
            outreach_angle=angle,
            outreach_draft=draft.strip()
        )

    def _format_clean_outreach_draft(self, draft: str, dm_first_name: Optional[str], brand_name: str) -> str:
        clean = (draft or "").strip()
        greeting = f"Hi {dm_first_name}," if dm_first_name else f"Hi {brand_name} team,"
        
        # Strip existing greeting if present
        clean = re.sub(r"^(?:hi|hey|hello|dear)[^\n,]*[,:]?\s*", "", clean, flags=re.IGNORECASE).strip()
        
        # Ensure paragraph separation if single long block
        if "\n" not in clean:
            sentences = re.split(r"(?<=[.!?])\s+", clean)
            if len(sentences) >= 3:
                body = " ".join(sentences[:-1])
                cta = sentences[-1]
                clean = f"{body}\n\n{cta}"
        
        # Add sign-off if missing
        if not any(s in clean.lower() for s in ["best regards", "regards", "best,", "sincerely"]):
            clean = f"{clean}\n\nBest regards,\nLead Data Specialist"
            
        full_draft = f"{greeting}\n\n{clean}"
        return (
            full_draft.replace("—", " - ")
            .replace("–", " - ")
            .replace("‘", "'")
            .replace("’", "'")
            .replace("“", '"')
            .replace("”", '"')
            .replace("\u00a0", " ")
            .strip()
        )

    def generate_outreach(self, lead: LeadRecord) -> LeadRecord:
        # Bug 2: Never generate outreach for rejected leads
        if lead.overall_priority == PriorityTier.REJECTED or lead.lead_classification == LeadClassification.REJECTED:
            return lead

        act_email = lead.verified_email or lead.email
        has_email = bool(act_email and str(act_email).strip().lower() not in ["", "none", "nan", "null"])

        has_real_dm = bool(
            lead.decision_maker_name
            and len(lead.decision_maker_name.strip()) > 2
            and lead.decision_maker_name.strip().lower() not in ["not identified", "none", "n/a", "not found", "founder", "owner", "leadership"]
        )
        first_name = lead.decision_maker_name.split()[0].title() if has_real_dm else None

        # Zero token burn: If email is missing, do NOT call LLM (saves tokens per Bug 2)
        if not has_email:
            fallback = self._fallback_pitch(lead)
            lead.recommended_scraping_pitch = fallback.recommended_scraping_pitch
            lead.custom_outreach_hook = fallback.custom_outreach_hook
            lead.outreach_angle = fallback.outreach_angle
            if lead.overall_priority in (PriorityTier.HOT_LEAD, PriorityTier.HIGH_POTENTIAL):
                lead.outreach_draft = self._format_clean_outreach_draft(fallback.outreach_draft, first_name, lead.business_name)
            return lead

        standard_hook = self._get_v2_standard_hook(lead.agency_type)

        # Check if already crafted by AI Supervisor and valid (Bug 1 Fix: No truncated drafts accepted)
        if self._is_valid_email_body(lead.outreach_draft):
            lead.outreach_draft = self._format_clean_outreach_draft(lead.outreach_draft, first_name, lead.business_name)
            lead.outreach_status = OutreachStatus.DRAFT
            if not lead.recommended_scraping_pitch:
                lead.recommended_scraping_pitch = lead.personalization_guide or standard_hook
            if not lead.custom_outreach_hook:
                lead.custom_outreach_hook = standard_hook
            return lead

        niche_str = ", ".join(lead.client_industries_served) if lead.client_industries_served else "B2B companies"
        dm_label = f"{lead.decision_maker_name} ({lead.decision_maker_role or 'Owner'})" if has_real_dm else "Not identified"

        system_prompt = (
            "You are an expert B2B copywriter for custom web scraping and data pipeline engineering services.\n"
            "Your objective: Pitch agency owners custom web-scraped datasets tailored to the EXACT clients they serve.\n"
            "STRICT RULES:\n"
            "1. Outreach draft MUST be UNDER 75 WORDS.\n"
            "2. Plain-text only, NO hyperlinks, NO brackets.\n"
            "3. Offer a small free sample dataset of 25-50 custom-scraped leads in their exact niche.\n"
            "4. Conversational, respectful, zero fluff, value-first.\n"
            "5. STRICT GREETING (ZERO HALLUCINATIONS):\n"
            f"- {f'Start strictly with \"Hi {first_name},\"' if has_real_dm else f'Start strictly with \"Hi {lead.business_name} team,\"'}\n"
            "- NEVER invent random names (e.g. NEVER say 'Hey Eric' unless Eric is verified). NEVER write 'Hi founder'."
        )

        user_prompt = (
            f"Agency Name: {lead.business_name}\n"
            f"Agency Type: {lead.agency_type.value}\n"
            f"Client Industries Served: {niche_str}\n"
            f"Services: {', '.join(lead.core_services)}\n"
            f"Decision Maker: {dm_label}\n"
            f"Website: {lead.website or 'N/A'}\n"
            f"Evidence Snippet: {lead.evidence.get('evidence_quote_niche', '')}"
        )

        try:
            res = llm_router.route(
                task=TaskType.OUTREACH_IDEATION,
                prompt=user_prompt,
                system_prompt=system_prompt,
                schema=OutreachPitchGeneration
            )
            data: OutreachPitchGeneration = res["data"]
            lead.recommended_scraping_pitch = data.recommended_scraping_pitch
            lead.custom_outreach_hook = data.custom_outreach_hook or standard_hook
            lead.outreach_angle = data.outreach_angle
            lead.outreach_draft = data.outreach_draft
            if not self._is_valid_email_body(lead.outreach_draft):
                logger.info(f"LLM draft for {lead.business_name} was truncated or incomplete; applying fallback template.")
                lead.outreach_draft = self._fallback_pitch(lead).outreach_draft
        except Exception as e:
            logger.warning(f"LLM outreach generation failed ({e}), falling back to heuristic generator.")
            fallback = self._fallback_pitch(lead)
            lead.recommended_scraping_pitch = fallback.recommended_scraping_pitch
            lead.custom_outreach_hook = fallback.custom_outreach_hook
            lead.outreach_angle = fallback.outreach_angle
            lead.outreach_draft = fallback.outreach_draft

        if not self._is_valid_email_body(lead.outreach_draft):
            lead.outreach_draft = self._fallback_pitch(lead).outreach_draft

        lead.outreach_draft = self._format_clean_outreach_draft(lead.outreach_draft, first_name, lead.business_name)
        lead.outreach_status = OutreachStatus.DRAFT
        return lead

outreach_agent = OutreachAgent()

