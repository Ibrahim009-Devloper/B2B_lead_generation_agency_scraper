import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from pydantic import BaseModel, Field, field_validator

from core.schemas import (
    LeadRecord, CampaignGoal, AgencyType, PriorityTier, VerificationStatus, LeadClassification
)
from core.llm_router import llm_router, TaskType
from core.database import LeadRepository
from adapters.search_api_adapter import SearchApiAdapter
from adapters.google_maps_adapter import GoogleMapsAdapter
from adapters.directory_adapter import DirectoryAdapter
from adapters.linkedin_xray_adapter import LinkedInXRayAdapter
from adapters.job_board_adapter import JobBoardAdapter
from adapters.website_enrichment import WebsiteEnrichmentAgent
from pipeline.normalizer import normalize_domain, normalize_phone, is_valid_agency_domain
from pipeline.deduplicator import DeduplicationEngine
from pipeline.verifier import LeadVerifier
from pipeline.scorer import ScrapingBuyerScorer
from pipeline.outreach_agent import OutreachAgent
from learning.memory_store import MemoryStore
from learning.evaluator import PipelineEvaluator

logger = logging.getLogger("Orchestrator")
logger.setLevel(logging.INFO)

DIRECTORY_AND_PORTAL_DOMAINS = {
    "clutch.co", "goodfirms.co", "sortlist.com", "upcity.com", "designrush.com",
    "yelp.com", "yellowpages.com", "linkedin.com", "google.com", "facebook.com",
    "twitter.com", "x.com", "instagram.com", "youtube.com", "crunchbase.com",
    "zoominfo.com", "apollo.io", "g2.com", "trustpilot.com", "wikipedia.org"
}

class ParsedCampaignPlan(BaseModel):
    agency_types: List[AgencyType] = Field(default_factory=list)
    target_geography: List[str] = Field(default_factory=list)
    target_client_niches: List[str] = Field(default_factory=list)
    lead_quantity: int = Field(default=10)
    search_queries: List[str] = Field(default_factory=list)
    quality_threshold: int = Field(default=65)

    @field_validator("target_geography", "target_client_niches", "search_queries", mode="before")
    @classmethod
    def ensure_string_list(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        if isinstance(v, list):
            return [str(s) for s in v]
        return []

    @field_validator("agency_types", mode="before")
    @classmethod
    def normalize_agency_types(cls, v: Any) -> List[AgencyType]:
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return [AgencyType.B2B_LEAD_GEN]
        normalized = []
        for item in v:
            if isinstance(item, AgencyType):
                normalized.append(item)
            elif isinstance(item, str):
                clean = item.lower()
                if "cold" in clean or "outbound" in clean:
                    normalized.append(AgencyType.COLD_EMAIL)
                elif "lead" in clean or "b2b" in clean:
                    normalized.append(AgencyType.B2B_LEAD_GEN)
                elif "seo" in clean:
                    normalized.append(AgencyType.LOCAL_SEO)
                elif "market" in clean:
                    normalized.append(AgencyType.DIGITAL_MARKETING)
                elif "recruit" in clean:
                    normalized.append(AgencyType.RECRUITING)
                elif "data" in clean:
                    normalized.append(AgencyType.DATA_RESEARCH)
                else:
                    normalized.append(AgencyType.NON_ICP)
        return normalized or [AgencyType.B2B_LEAD_GEN]

    @field_validator("quality_threshold", mode="before")
    @classmethod
    def normalize_quality_threshold(cls, v: Any) -> int:
        if isinstance(v, float):
            return int(v * 100) if v <= 1.0 else int(v)
        if isinstance(v, str):
            try:
                f = float(v)
                return int(f * 100) if f <= 1.0 else int(f)
            except ValueError:
                return 65
        return int(v) if v is not None else 65

class MasterOrchestrator:
    def __init__(self):
        self.repo = LeadRepository()
        self.search_adapter = SearchApiAdapter()
        self.maps_adapter = GoogleMapsAdapter()
        self.directory_adapter = DirectoryAdapter()
        self.xray_adapter = LinkedInXRayAdapter()
        self.job_board_adapter = JobBoardAdapter()
        self.enricher = WebsiteEnrichmentAgent()
        self.deduper = DeduplicationEngine()
        self.verifier = LeadVerifier()
        self.scorer = ScrapingBuyerScorer()
        self.outreach = OutreachAgent()
        self.memory = MemoryStore()
        self.evaluator = PipelineEvaluator()

    def parse_campaign_prompt(self, raw_prompt: str) -> ParsedCampaignPlan:
        system_prompt = (
            "You are the Master Campaign Planner for an autonomous B2B agency lead generation agent.\n"
            "Parse the user's campaign prompt into a structured campaign plan.\n"
            "Map desired agencies to: 'b2b_lead_gen', 'cold_email', 'local_seo', 'digital_marketing', 'recruiting', 'data_research'.\n"
            "Generate 3-5 high-intent search queries based on the target agencies, geographies, and client niches."
        )
        
        try:
            res = llm_router.route(
                task=TaskType.FAST_CLASSIFICATION,
                prompt=f"Campaign Request: {raw_prompt}",
                system_prompt=system_prompt,
                schema=ParsedCampaignPlan
            )
            plan: ParsedCampaignPlan = res["data"]
            if not plan.search_queries:
                plan.search_queries = [raw_prompt]
            return plan
        except Exception as e:
            logger.warning(f"LLM campaign parsing fallback: {e}")
            # Heuristic fallback
            queries = [raw_prompt]
            types = [AgencyType.COLD_EMAIL if "cold email" in raw_prompt.lower() else AgencyType.LOCAL_SEO if "seo" in raw_prompt.lower() else AgencyType.B2B_LEAD_GEN]
            return ParsedCampaignPlan(
                agency_types=types,
                search_queries=queries,
                lead_quantity=10
            )

    def run_campaign(
        self,
        prompt: str,
        target_count: Optional[int] = None,
        on_event: Optional[Any] = None
    ) -> Dict[str, Any]:
        campaign_id = uuid4()
        start_time = datetime.now(timezone.utc)
        logger.info(f"Starting campaign {campaign_id} for prompt: '{prompt}'")
        if on_event:
            on_event("Master Orchestrator", f"Campaign initialized for: '{prompt}'")

        # Step 1: Parse Campaign
        plan = self.parse_campaign_prompt(prompt)
        limit = target_count or plan.lead_quantity
        logger.info(f"Parsed plan: {len(plan.search_queries)} search queries, target limit={limit}")
        if on_event:
            on_event("Master Orchestrator", f"Plan parsed: {len(plan.search_queries)} queries, targeting {limit} leads.")

        # Step 2: Active Goal-Seeking Multi-Source Lead Harvesting Loop
        verified_leads: List[LeadRecord] = []
        all_campaign_records: List[LeadRecord] = []
        seen_domains = set()
        duplicates_removed_count = 0
        total_discovered_candidates = 0

        # Build dynamic discovery queries pool combining niches, footprints, and major agency cities
        base_term = plan.search_queries[0] if plan.search_queries else prompt
        agency_cities = [
            "New York", "London", "Austin", "Chicago", "Toronto",
            "San Francisco", "Atlanta", "Dallas", "Boston", "Miami",
            "Denver", "Los Angeles", "Seattle"
        ]
        search_queries_pool = list(plan.search_queries)
        
        # High-intent direct agency search footprints
        search_queries_pool.append('inurl:contact "b2b lead generation" "appointment setting" agency')
        search_queries_pool.append('inurl:services "cold email agency" "b2b lead generation"')
        search_queries_pool.append('inurl:services "sdr as a service" "sales pipeline"')
        search_queries_pool.append('inurl:about "outbound sales agency" "cold email"')
        search_queries_pool.append('"we help b2b companies" "appointment setting" "contact us"')

        for city in agency_cities:
            search_queries_pool.append(f"{base_term} {city}")
            search_queries_pool.append(f"b2b appointment setting agency {city}")
            search_queries_pool.append(f"cold email outreach agency {city}")

        logger.info(f"Targeting {limit} qualified leads with emails across {len(search_queries_pool)} discovery queries...")

        # Step 2: High-Intent B2B Directory Harvest (Decoupled from city search loop - runs once per batch)
        if on_event:
            on_event("Recon & Source Agent", "Harvesting B2B directories (DesignRush, The Manifest, Sortlist, GoodFirms)...")
        initial_candidates: List[Any] = []
        try:
            initial_candidates = self.directory_adapter.search(base_term, limit=max(60, limit * 3), on_event=on_event)
            total_discovered_candidates += len(initial_candidates)
            logger.info(f"Directory harvest yielded {len(initial_candidates)} candidates.")
        except Exception as e:
            logger.warning(f"Directory harvester initial run notice: {e}")

        # Thread-safe lock for campaign state updates
        state_lock = threading.Lock()

        def process_candidate_worker(cand: Any) -> Optional[LeadRecord]:
            nonlocal duplicates_removed_count

            with state_lock:
                if len(verified_leads) >= limit:
                    return None

            raw_url = cand.website or cand.source_url or ""
            dom = normalize_domain(raw_url)
            if not dom:
                return None

            # Domain validation: reject invalid characters, corporate telecoms, internal mail hosts
            if not is_valid_agency_domain(dom):
                with state_lock:
                    duplicates_removed_count += 1
                return None

            # Drop directory/portal domains
            if any(dom == d or dom.endswith("." + d) for d in DIRECTORY_AND_PORTAL_DOMAINS):
                with state_lock:
                    duplicates_removed_count += 1
                return None

            with state_lock:
                if dom in seen_domains:
                    duplicates_removed_count += 1
                    return None
                seen_domains.add(dom)

            # Pre-scrape check against permanent database (both leads and scraped_domains table)
            if self.repo.is_domain_scraped_before(dom) or self.repo.is_domain_in_cooldown(dom, cooldown_days=90):
                with state_lock:
                    duplicates_removed_count += 1
                return None

            # High-Speed Multi-Page Website Recon & Enrichment (Runs concurrently across worker threads!)
            website = cand.website or cand.source_url
            if on_event:
                on_event("Harvester Agent", f"Crawling {cand.business_name} ({website}) - multi-page crawl & email extraction...")

            enrichment = self.enricher.enrich_website(website, initial_name=cand.business_name)

            clean_name = enrichment.clean_business_name or cand.business_name
            if any(w in clean_name.lower() for w in ["best ", "top ", "list of ", "agencies in ", "companies in ", "services in "]):
                clean_name = self.enricher._format_domain_brand(website)

            # ZERO-EMAIL DROP RULE (user requirement: "email sara kono lead nibe na")
            if enrichment.zero_token_rejected or not enrichment.extracted_email:
                rec_reason = enrichment.non_agency_reason or "Zero-Email Drop: No deliverable email found on website"
                rej_lead = LeadRecord(
                    campaign_id=str(campaign_id),
                    business_name=clean_name,
                    agency_type=enrichment.agency_type,
                    website=dom,
                    source_footprint=cand.source_name or "Directory Harvester",
                    overall_priority=PriorityTier.NEEDS_REVIEW if enrichment.is_agency else PriorityTier.REJECTED,
                    lead_classification=LeadClassification.CONTACT_RESEARCH_REQUIRED if enrichment.is_agency else LeadClassification.REJECTED,
                    rejection_reason=rec_reason,
                    target_verification_status="CONTACT_RESEARCH_REQUIRED" if enrichment.is_agency else (enrichment.target_verification_status or "REJECTED")
                )
                with state_lock:
                    self.repo.record_scraped_domain(dom, status="rejected_no_email_zero_token")
                    all_campaign_records.append(rej_lead)
                if on_event:
                    on_event("Harvester Agent", f"Dropped {cand.business_name} ({dom}) - no email found on site (0 tokens burned).")
                return None

            if on_event:
                on_event("Harvester Agent", f"Found email for {cand.business_name} ({dom}): {enrichment.extracted_email}")

            # Lifetime Email Deduplication
            if self.repo.is_email_seen(enrichment.extracted_email):
                with state_lock:
                    duplicates_removed_count += 1
                if on_event:
                    on_event("Verification Agent", f"Skipped {cand.business_name}: Email {enrichment.extracted_email} already exists in DB.")
                return None

            lead = LeadRecord(
                campaign_id=str(campaign_id),
                business_name=clean_name,
                agency_type=enrichment.agency_type,
                client_industries_served=enrichment.client_industries_served,
                core_services=enrichment.core_services,
                company_size=enrichment.company_size or "2-10",
                data_dependency_signals=enrichment.data_dependency_signals,
                scale_signals=enrichment.scale_signals,
                website=dom,
                phone=normalize_phone(cand.phone or enrichment.extracted_phone),
                email=enrichment.extracted_email,
                verified_email=enrichment.extracted_email,
                backup_emails=enrichment.backup_emails,
                city=cand.city,
                decision_maker_name=enrichment.decision_maker_name,
                decision_maker_role=enrichment.decision_maker_role,
                decision_maker_linkedin=enrichment.decision_maker_linkedin,
                complete_business_summary=enrichment.complete_business_summary,
                their_target_clients=enrichment.their_target_clients,
                personalization_guide=enrichment.personalization_guide,
                opportunity_score=getattr(enrichment, 'opportunity_score', 0),
                opportunity_tier=getattr(enrichment, 'opportunity_tier', "MODERATE OPPORTUNITY"),
                opportunity_signals=getattr(enrichment, 'opportunity_reasons', []),
                source_footprint=cand.source_name or "Web Search",
                target_verification_status=enrichment.target_verification_status,
                source_names=[cand.source_name],
                source_urls=[cand.source_url],
                evidence={
                    "snippet": cand.snippet,
                    "evidence_quote_niche": enrichment.evidence_quote_niche,
                    "tech_fit_score": enrichment.tech_fit_score,
                    "decision_maker_name": {
                        "url": website,
                        "snippet": enrichment.evidence_quote_decision_maker or f"{enrichment.decision_maker_name} ({enrichment.decision_maker_role or 'Leadership'})"
                    } if enrichment.decision_maker_name else None
                },
                factual_confidence=enrichment.factual_confidence,
                rejection_reason=enrichment.non_agency_reason,
                outreach_draft=enrichment.ready_cold_email
            )

            # Layer 2 AI Verifier rejection check
            if not enrichment.is_verified_target:
                lead.overall_priority = PriorityTier.REJECTED
                lead.lead_classification = LeadClassification.REJECTED
                lead.target_verification_status = f"REJECTED: {enrichment.non_agency_reason or 'Failed AI gatekeeper'}"
                with state_lock:
                    self.repo.record_scraped_domain(dom, status="rejected_ai_gate")
                    all_campaign_records.append(lead)
                if on_event:
                    on_event("Verification Agent", f"AI Gatekeeper rejected {clean_name}: {enrichment.non_agency_reason or 'Not target agency'}")
                return None

            # Hidden-Email Handling for Verified B2B Lead Gen Agencies (Calendly / Booking forms)
            if enrichment.email_hidden_on_site:
                lead.verified_email = None # Not on public HTML
                if enrichment.decision_maker_linkedin:
                    lead.lead_classification = LeadClassification.LINKEDIN_OUTREACH_CANDIDATE
                    lead.overall_priority = PriorityTier.HIGH_POTENTIAL
                    lead.target_verification_status = "LINKEDIN_OUTREACH_CANDIDATE (B2B Lead Gen)"
                else:
                    lead.lead_classification = LeadClassification.CONTACT_RESEARCH_REQUIRED
                    lead.overall_priority = PriorityTier.NEEDS_REVIEW
                    lead.target_verification_status = "CONTACT_RESEARCH_REQUIRED (B2B Lead Gen)"
                
                with state_lock:
                    self.repo.save_lead(lead)
                    self.repo.record_scraped_domain(dom, status=lead.overall_priority.value, lead_id=str(lead.lead_id))
                    all_campaign_records.append(lead)
                if on_event:
                    on_event("Harvester Agent", f"Preserved B2B agency {clean_name} ({dom}) - email hidden behind booking form. Routed to {lead.lead_classification.value}.")
                return None

            # Step 5: Deterministic MX Verification
            lead = self.verifier.verify_lead(lead)
            if not lead.verified_email:
                lead.overall_priority = PriorityTier.NEEDS_REVIEW
                lead.lead_classification = LeadClassification.CONTACT_RESEARCH_REQUIRED
                lead.rejection_reason = "Contact research required: Invalid DNS MX mail server"
                lead.target_verification_status = "CONTACT_RESEARCH_REQUIRED"
                with state_lock:
                    self.repo.record_scraped_domain(dom, status="rejected_invalid_mx")
                    all_campaign_records.append(lead)
                if on_event:
                    on_event("Verification Agent", f"Dropped {clean_name}: DNS MX check failed for email {lead.email}")
                return None

            # Step 6: 100-Point Scoring Model
            lead = self.scorer.score_lead(lead)
            if lead.overall_priority == PriorityTier.REJECTED:
                with state_lock:
                    self.repo.record_scraped_domain(dom, status="rejected_low_score")
                    all_campaign_records.append(lead)
                if on_event:
                    on_event("The Judge", f"Dropped {clean_name}: Score {lead.total_score} below minimum threshold.")
                return None

            # Step 7: Value-First Outreach Pitch Generation
            if lead.verified_email and lead.overall_priority in (PriorityTier.HOT_LEAD, PriorityTier.HIGH_POTENTIAL, PriorityTier.QUALIFIED):
                if on_event:
                    on_event("Outreach Agent", f"Crafted bespoke outreach hook for {clean_name}...")
                lead = self.outreach.generate_outreach(lead)

            # Persist verified lead to SQLite database
            with state_lock:
                if len(verified_leads) >= limit:
                    return None
                self.repo.save_lead(lead)
                self.repo.record_scraped_domain(dom, status=lead.overall_priority.value, lead_id=str(lead.lead_id))
                verified_leads.append(lead)
                all_campaign_records.append(lead)

            if on_event:
                on_event("The Judge", f"[HOT LEAD] [{len(verified_leads)}/{limit}] Qualified Lead Collected: {clean_name} ({lead.verified_email})")
            return lead

        def run_candidates_pool(candidates_list: List[Any]):
            if not candidates_list:
                return
            with state_lock:
                if len(verified_leads) >= limit:
                    return

            # Run up to 8 parallel workers for high-speed multi-page crawling
            max_workers = min(8, max(2, len(candidates_list)))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(process_candidate_worker, c): c for c in candidates_list}
                for f in as_completed(futures):
                    with state_lock:
                        if len(verified_leads) >= limit:
                            # Stop early once target reached
                            for pending_f in futures:
                                pending_f.cancel()
                            break
                    try:
                        f.result()
                    except Exception as exc:
                        logger.debug(f"Candidate worker notice: {exc}")

        # Step 2: Continuous Goal-Seeking Multi-Batch Harvesting Loop
        max_campaign_rounds = 35
        round_idx = 0
        consecutive_empty_rounds = 0

        # First, process the initial candidate batch if already harvested
        if initial_candidates:
            run_candidates_pool(initial_candidates)

        # Continuous Goal-Seeking Loop: Keeps harvesting fresh directory pages & search footprints until `len(verified_leads) >= limit`
        while len(verified_leads) < limit and round_idx < max_campaign_rounds:
            round_idx += 1
            needed = limit - len(verified_leads)
            batch_target = max(60, min(600, needed * 4))

            if on_event:
                on_event(
                    "Recon & Source Agent",
                    f"Goal-Seeking Round {round_idx}: Harvesting fresh B2B directory pages [{len(verified_leads)}/{limit} verified leads collected]..."
                )

            batch_candidates: List[Any] = []
            try:
                batch_candidates = self.directory_adapter.search(base_term, limit=batch_target, on_event=on_event)
                total_discovered_candidates += len(batch_candidates)
            except Exception as e:
                logger.warning(f"Directory harvester round {round_idx} notice: {e}")

            if batch_candidates:
                run_candidates_pool(batch_candidates)

            # If directories returned fewer candidates than needed, seamlessly complement with rotated search footprints
            search_cands: List[Any] = []
            if len(verified_leads) < limit and (not batch_candidates or len(batch_candidates) < min(30, needed)):
                pool_len = len(search_queries_pool)
                q_start = ((round_idx - 1) * 4) % pool_len
                q_batch = [search_queries_pool[(q_start + i) % pool_len] for i in range(4)]

                for q in q_batch:
                    with state_lock:
                        if len(verified_leads) >= limit:
                            break
                    if on_event:
                        on_event("Recon & Source Agent", f"Searching for fresh agencies [{len(verified_leads)}/{limit} collected] using '{q}'...")
                    try:
                        c_search = self.search_adapter.search(q, limit=max(10, min(25, (limit - len(verified_leads)))), on_event=on_event)
                        search_cands.extend(c_search)
                        total_discovered_candidates += len(c_search)
                    except Exception as e:
                        logger.debug(f"Search adapter notice: {e}")

                if search_cands:
                    run_candidates_pool(search_cands)

            if not batch_candidates and not search_cands:
                consecutive_empty_rounds += 1
                if consecutive_empty_rounds >= 4:
                    logger.info("Exhausted all available fresh directory pages and search footprints across all categories.")
                    break
            else:
                consecutive_empty_rounds = 0

        # Step 8: Deduplicate final batch with provenance merging
        final_leads = self.deduper.deduplicate_batch(verified_leads)

        # Step 9: Evaluation & Metrics Telemetry
        metrics = self.evaluator.calculate_metrics(
            final_leads,
            total_discovered=max(total_discovered_candidates, len(final_leads)),
            duplicates_removed=duplicates_removed_count
        )

        logger.info(f"Campaign completed. Total: {len(final_leads)}, Qualified: {metrics['qualified_count']}, Duplicates Skipped: {duplicates_removed_count}")
        return {
            "campaign_id": str(campaign_id),
            "plan": plan.model_dump(),
            "metrics": metrics,
            "leads": final_leads,
            "all_records": all_campaign_records,
            "total_discovered": max(total_discovered_candidates, len(final_leads)),
            "duplicates_removed": duplicates_removed_count
        }

master_orchestrator = MasterOrchestrator()

