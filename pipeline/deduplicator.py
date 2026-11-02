import logging
from typing import List, Optional, Tuple, Dict, Any
from uuid import UUID, uuid4
from rapidfuzz import fuzz

from core.schemas import LeadRecord
from pipeline.normalizer import (
    normalize_domain, normalize_phone, normalize_agency_name_for_matching
)

logger = logging.getLogger("Deduplicator")

class DeduplicationEngine:
    def __init__(self, fuzzy_threshold: float = 0.88):
        self.fuzzy_threshold = fuzzy_threshold * 100  # RapidFuzz uses 0-100 scale

    def are_exact_duplicates(self, lead1: LeadRecord, lead2: LeadRecord) -> bool:
        dom1 = normalize_domain(lead1.website)
        dom2 = normalize_domain(lead2.website)
        if dom1 and dom2 and dom1 == dom2:
            return True

        p1 = normalize_phone(lead1.phone)
        p2 = normalize_phone(lead2.phone)
        if p1 and p2 and p1 == p2:
            return True

        return False

    def are_fuzzy_duplicates(self, lead1: LeadRecord, lead2: LeadRecord) -> bool:
        name1 = normalize_agency_name_for_matching(lead1.business_name)
        name2 = normalize_agency_name_for_matching(lead2.business_name)
        if not name1 or not name2:
            return False

        ratio = fuzz.token_sort_ratio(name1, name2)
        if ratio >= self.fuzzy_threshold:
            # If cities are specified, verify they match or at least don't directly conflict
            c1 = (lead1.city or "").strip().lower()
            c2 = (lead2.city or "").strip().lower()
            if c1 and c2 and c1 != c2:
                return False
            return True
        return False

    def merge_leads(self, primary: LeadRecord, secondary: LeadRecord) -> LeadRecord:
        """
        Merges two lead records while preserving provenance audit logs.
        """
        group_id = primary.duplicate_group_id or secondary.duplicate_group_id or uuid4()
        primary.duplicate_group_id = group_id
        secondary.duplicate_group_id = group_id

        # Merge sources and URLs
        for src in secondary.source_names:
            if src not in primary.source_names:
                primary.source_names.append(src)
        for url in secondary.source_urls:
            if url not in primary.source_urls:
                primary.source_urls.append(url)

        # Merge services & client industries
        for ind in secondary.client_industries_served:
            if ind not in primary.client_industries_served:
                primary.client_industries_served.append(ind)
        for srv in secondary.core_services:
            if srv not in primary.core_services:
                primary.core_services.append(srv)
        for sig in secondary.data_dependency_signals:
            if sig not in primary.data_dependency_signals:
                primary.data_dependency_signals.append(sig)

        # Preserve provenance in evidence
        merged_evidence = dict(primary.evidence)
        for k, v in secondary.evidence.items():
            if k not in merged_evidence:
                merged_evidence[k] = v
            else:
                # Store multiple provenance sources
                merged_evidence[f"{k}_secondary"] = v
        primary.evidence = merged_evidence

        # Fill in missing contact info
        if not primary.website and secondary.website:
            primary.website = secondary.website
        if not primary.phone and secondary.phone:
            primary.phone = secondary.phone
        if not primary.email and secondary.email:
            primary.email = secondary.email
        if not primary.decision_maker_name and secondary.decision_maker_name:
            primary.decision_maker_name = secondary.decision_maker_name
            primary.decision_maker_role = secondary.decision_maker_role
        if not primary.city and secondary.city:
            primary.city = secondary.city

        return primary

    def deduplicate_batch(self, leads: List[LeadRecord]) -> List[LeadRecord]:
        deduped: List[LeadRecord] = []
        for lead in leads:
            merged = False
            for existing in deduped:
                if self.are_exact_duplicates(existing, lead) or self.are_fuzzy_duplicates(existing, lead):
                    self.merge_leads(existing, lead)
                    merged = True
                    break
            if not merged:
                deduped.append(lead)
        return deduped

deduplication_engine = DeduplicationEngine()

