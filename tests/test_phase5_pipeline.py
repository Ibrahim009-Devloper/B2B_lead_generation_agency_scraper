import pytest
from core.schemas import LeadRecord, AgencyType, VerificationStatus
from pipeline.normalizer import (
    normalize_domain, normalize_phone, normalize_agency_name_for_matching
)
from pipeline.deduplicator import DeduplicationEngine
from pipeline.verifier import LeadVerifier

def test_normalization():
    assert normalize_domain("https://www.apexoutbound.com/services?param=1#hash") == "apexoutbound.com"
    assert normalize_domain("http://leadagency.co.uk/") == "leadagency.co.uk"
    
    assert normalize_phone("(512) 555-0199") == "+15125550199"
    assert normalize_phone("+1 800 555 1212") == "+18005551212"

    clean_name = normalize_agency_name_for_matching("Apex Growth Media & Digital Agency LLC")
    assert clean_name == "apex growth"

def test_deduplication_exact_and_fuzzy():
    deduper = DeduplicationEngine()
    lead1 = LeadRecord(
        business_name="Apex Growth LLC",
        website="apexgrowth.io",
        phone="+15125550199",
        source_names=["google_maps"],
        source_urls=["https://maps.google.com/apex"],
        client_industries_served=["SaaS"]
    )
    lead2 = LeadRecord(
        business_name="Apex Growth Agency",
        website="https://www.apexgrowth.io/",
        source_names=["search_footprints"],
        source_urls=["https://search.com/apex"],
        client_industries_served=["Fintech"],
        decision_maker_name="Marcus Vance",
        evidence={"decision_maker_name": {"url": "https://apexgrowth.io/about", "snippet": "Founded by Marcus Vance"}}
    )

    assert deduper.are_exact_duplicates(lead1, lead2) is True
    merged = deduper.merge_leads(lead1, lead2)
    assert "google_maps" in merged.source_names
    assert "search_footprints" in merged.source_names
    assert "SaaS" in merged.client_industries_served
    assert "Fintech" in merged.client_industries_served
    assert merged.decision_maker_name == "Marcus Vance"
    assert merged.duplicate_group_id is not None

def test_verifier_email_mx_and_epistemic_honesty():
    verifier = LeadVerifier()
    # Live MX check on a known active domain
    status, is_pers = verifier.verify_email("alex@google.com")
    assert status == VerificationStatus.LIKELY_VALID  # Strict rule: never VERIFIED from MX alone
    assert is_pers is True

    # Generic role email test
    status_generic, is_pers_generic = verifier.verify_email("info@google.com")
    assert is_pers_generic is False

    # Fake domain without MX
    status_fake, _ = verifier.verify_email("user@nonexistent-fake-domain-1234987xyz.org")
    assert status_fake == VerificationStatus.INVALID

def test_verifier_zero_trust_decision_maker():
    verifier = LeadVerifier()
    # Unverified DM without evidence snippet should be cleared
    unverified_lead = LeadRecord(
        business_name="Shadow Agency",
        decision_maker_name="Ghost Founder",
        decision_maker_role="CEO",
        evidence={}
    )
    verified = verifier.verify_lead(unverified_lead)
    assert verified.decision_maker_name is None
    assert verified.decision_maker_role is None

